from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from .cli import CliCommand, resolve_claude_command
from .models import ConversationResult
from .process import run_process

ClaudeModel = Literal["fable", "opus", "sonnet", "haiku"]
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
ClaudeTool = Literal["Read", "Grep", "Glob", "WebSearch", "WebFetch"]


class ClaudeProtocolError(RuntimeError):
    pass


def parse_claude_result(output: str) -> ConversationResult:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise ClaudeProtocolError(f"Claude returned invalid JSON: {error}") from error
    if payload.get("is_error"):
        raise ClaudeProtocolError(str(payload.get("result") or "Claude returned an error"))
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


class ClaudeClient:
    def __init__(
        self,
        command: CliCommand | None = None,
        timeout_seconds: float | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self.command = command or resolve_claude_command()
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("MODEL_MCP_CLI_TIMEOUT_SECONDS", "900")
        )
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
    ) -> ConversationResult:
        return await self._run(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            tools=tools,
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
    ) -> ConversationResult:
        return await self._run(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            tools=tools,
            session_id=session_id,
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
    ) -> ConversationResult:
        args = [
            *self.command.prefix_args,
            "-p",
            "--output-format",
            "json",
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
        result = await run_process(
            self.command.executable,
            args,
            prompt=prompt,
            cwd=cwd,
            timeout_seconds=self.timeout_seconds,
            idle_timeout_seconds=self.idle_timeout_seconds,
        )
        return parse_claude_result(result.stdout)
