from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from .cli import CliCommand, resolve_codex_command
from .models import ConversationResult
from .process import ProgressCallback, ProgressReporter, run_process

SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]


class CodexProtocolError(RuntimeError):
    pass


_CODEX_ITEM_STATUS = {
    "agent_message": "Codex prepared a response",
    "command_execution": "Codex is running a command",
    "file_change": "Codex is preparing file changes",
    "mcp_tool_call": "Codex is using a tool",
    "reasoning": "Codex is reasoning",
    "todo_list": "Codex updated its plan",
    "web_search": "Codex is searching the web",
}


def codex_event_status(line: str) -> str | None:
    """Return a content-free status summary for one Codex JSONL event."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if event_type == "thread.started":
        return "Codex session started"
    if event_type == "turn.started":
        return "Codex is working"
    if event_type in {"item.started", "item.updated", "item.completed"}:
        item = event.get("item") or {}
        return _CODEX_ITEM_STATUS.get(item.get("type"), "Codex completed an action")
    if event_type == "turn.completed":
        return "Codex turn completed"
    if event_type in {"error", "turn.failed"}:
        return "Codex reported an error"
    return None


def parse_codex_events(output: str) -> ConversationResult:
    collector = CodexStreamCollector()
    for raw_line in output.splitlines():
        collector.feed(raw_line)
    return collector.result()


class CodexStreamCollector:
    """Incrementally retain only the fields required for the final response."""

    def __init__(self) -> None:
        self.thread_id: str | None = None
        self.last_message: str | None = None
        self.usage: dict[str, Any] = {}
        self.protocol_error = False
        self.turn_completed = False

    def feed(self, raw_line: str) -> None:
        line = raw_line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str):
                self.thread_id = thread_id
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                self.last_message = item["text"]
        elif event_type == "turn.completed":
            usage = event.get("usage") or {}
            self.usage = usage if isinstance(usage, dict) else {}
            self.turn_completed = True
        elif event_type in {"error", "turn.failed"}:
            self.protocol_error = True

    def result(self) -> ConversationResult:
        if self.protocol_error:
            raise CodexProtocolError("Codex reported an upstream error")
        if not self.thread_id:
            raise CodexProtocolError("Codex JSONL did not contain thread.started")
        if not self.last_message:
            raise CodexProtocolError("Codex JSONL did not contain an agent_message")
        if not self.turn_completed:
            raise CodexProtocolError("Codex JSONL did not contain turn.completed")
        return ConversationResult(
            result=self.last_message,
            session_id=self.thread_id,
            metadata={"usage": self.usage},
        )


class CodexClient:
    def __init__(
        self,
        command: CliCommand | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self.command = command or resolve_codex_command()
        self.idle_timeout_seconds = idle_timeout_seconds or float(
            os.getenv("MODEL_MCP_CLI_IDLE_TIMEOUT_SECONDS", "300")
        )

    async def start(
        self,
        prompt: str,
        *,
        cwd: Path,
        model: str | None = None,
        sandbox: SandboxMode = "read-only",
        reasoning_effort: ReasoningEffort | None = None,
        web_search: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> ConversationResult:
        args = [*self.command.prefix_args]
        if web_search:
            args.append("--search")
        if reasoning_effort:
            args.extend(("-c", f'model_reasoning_effort="{reasoning_effort}"'))
        args.extend(
            (
            "exec",
            "--json",
            "--sandbox",
            sandbox,
            "--skip-git-repo-check",
            "-C",
            str(cwd),
            )
        )
        if model:
            args.extend(("--model", model))
        args.append("-")
        reporter = ProgressReporter(progress_callback)
        collector = CodexStreamCollector()

        def observe(stream: str, line: str) -> None:
            if stream != "stdout":
                return
            collector.feed(line)
            if status := codex_event_status(line):
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

    async def reply(
        self,
        session_id: str,
        prompt: str,
        *,
        cwd: Path,
        model: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        web_search: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> ConversationResult:
        args = [*self.command.prefix_args]
        if web_search:
            args.append("--search")
        if reasoning_effort:
            args.extend(("-c", f'model_reasoning_effort="{reasoning_effort}"'))
        args.extend(
            (
            "exec",
            "resume",
            "--json",
            "--skip-git-repo-check",
            )
        )
        if model:
            args.extend(("--model", model))
        args.extend((session_id, "-"))
        reporter = ProgressReporter(progress_callback)
        collector = CodexStreamCollector()

        def observe(stream: str, line: str) -> None:
            if stream != "stdout":
                return
            collector.feed(line)
            if status := codex_event_status(line):
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
