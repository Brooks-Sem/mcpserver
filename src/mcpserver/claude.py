from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from .cli import CliCommand, resolve_claude_command
from .models import ConversationResult
from .process import ProgressCallback, ProgressReporter, run_process

ClaudeModel = Literal["fable", "opus", "sonnet", "haiku"]
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
ClaudeTool = Literal["Read", "Grep", "Glob", "WebSearch", "WebFetch"]


class ClaudeProtocolError(RuntimeError):
    pass


def _parse_claude_payload(payload: object) -> ConversationResult:
    if not isinstance(payload, dict):
        raise ClaudeProtocolError("Claude returned a non-object JSON payload")
    if payload.get("is_error"):
        raise ClaudeProtocolError("Claude returned an upstream error")
    result = payload.get("result")
    session_id = payload.get("session_id")
    if not isinstance(result, str) or not result:
        raise ClaudeProtocolError("Claude JSON did not contain a result")
    if not isinstance(session_id, str) or not session_id:
        raise ClaudeProtocolError("Claude JSON did not contain a session_id")
    model_usage = payload.get("modelUsage") or {}
    models = list(model_usage) if isinstance(model_usage, dict) else []
    return ConversationResult(
        result=result,
        session_id=session_id,
        model=models[0] if len(models) == 1 else None,
        metadata={
            "models": models,
            "costUsd": payload.get("total_cost_usd"),
            "usage": payload.get("usage") or {},
        },
    )


def parse_claude_result(output: str) -> ConversationResult:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise ClaudeProtocolError(f"Claude returned invalid JSON: {error}") from error
    return _parse_claude_payload(payload)


def parse_claude_stream(output: str) -> ConversationResult:
    collector = ClaudeStreamCollector()
    for raw_line in output.splitlines():
        collector.feed(raw_line)
    return collector.result()


class ClaudeStreamCollector:
    """Incrementally retain only Claude's terminal result event."""

    def __init__(self) -> None:
        self.result_payload: dict[str, object] | None = None
        self.invalid_lines = 0

    def feed(self, raw_line: str) -> None:
        line = raw_line.strip()
        if not line:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.invalid_lines += 1
            return
        if isinstance(payload, dict) and payload.get("type") == "result":
            self.result_payload = payload

    def result(self) -> ConversationResult:
        if self.result_payload is None:
            detail = f" ({self.invalid_lines} invalid JSONL lines)" if self.invalid_lines else ""
            raise ClaudeProtocolError(f"Claude stream did not contain a result event{detail}")
        return _parse_claude_payload(self.result_payload)


def claude_event_status(line: str) -> str | None:
    """Return a content-free status summary for one Claude stream event."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if event_type == "system":
        subtype = event.get("subtype")
        if subtype == "init":
            return "Claude session started"
        if subtype == "api_retry":
            return "Claude is retrying an API request"
        return "Claude updated its session state"
    if event_type == "stream_event":
        nested_event = event.get("event") or {}
        if nested_event.get("type") == "content_block_start":
            block = nested_event.get("content_block") or {}
            if block.get("type") == "tool_use":
                return "Claude is using a tool"
        return "Claude is composing a response"
    if event_type == "assistant":
        message = event.get("message") or {}
        content = message.get("content") or []
        if any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content):
            return "Claude is using a tool"
        return "Claude is reasoning"
    if event_type == "user":
        return "Claude received a tool result"
    if event_type == "result":
        return "Claude reported an error" if event.get("is_error") else "Claude turn completed"
    return None


class ClaudeClient:
    def __init__(
        self,
        command: CliCommand | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self.command = command or resolve_claude_command()
        self.idle_timeout_seconds = idle_timeout_seconds or float(
            os.getenv("MODEL_MCP_CLI_IDLE_TIMEOUT_SECONDS", "300")
        )

    async def start(
        self,
        prompt: str,
        *,
        cwd: Path,
        model: ClaudeModel | None = None,
        effort: ClaudeEffort = "high",
        tools: tuple[ClaudeTool, ...] = ("Read", "Grep", "Glob"),
        progress_callback: ProgressCallback | None = None,
    ) -> ConversationResult:
        return await self._run(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            tools=tools,
            progress_callback=progress_callback,
        )

    async def reply(
        self,
        session_id: str,
        prompt: str,
        *,
        cwd: Path,
        model: ClaudeModel | None = None,
        effort: ClaudeEffort = "high",
        tools: tuple[ClaudeTool, ...] = ("Read", "Grep", "Glob"),
        progress_callback: ProgressCallback | None = None,
    ) -> ConversationResult:
        return await self._run(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            tools=tools,
            session_id=session_id,
            progress_callback=progress_callback,
        )

    async def _run(
        self,
        prompt: str,
        *,
        cwd: Path,
        model: ClaudeModel | None,
        effort: ClaudeEffort,
        tools: tuple[ClaudeTool, ...],
        session_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> ConversationResult:
        args = [
            *self.command.prefix_args,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode",
            "plan",
            "--tools",
            ",".join(tools),
            "--effort",
            effort,
        ]
        if model:
            args.extend(("--model", model))
        if session_id:
            args.extend(("--resume", session_id))
        reporter = ProgressReporter(progress_callback)
        collector = ClaudeStreamCollector()

        def observe(stream: str, line: str) -> None:
            if stream != "stdout":
                return
            collector.feed(line)
            if status := claude_event_status(line):
                reporter.publish(status)

        try:
            await run_process(
                self.command.executable,
                args,
                prompt=prompt,
                cwd=cwd,
                idle_timeout_seconds=self.idle_timeout_seconds,
                output_observer=observe,
            )
        finally:
            await reporter.close()
        return collector.result()
