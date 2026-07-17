from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from .cli import CliCommand, resolve_codex_command
from .models import ConversationResult
from .process import run_process

SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]


class CodexProtocolError(RuntimeError):
    pass


def parse_codex_events(output: str) -> ConversationResult:
    thread_id: str | None = None
    messages: list[str] = []
    usage: dict[str, Any] = {}
    protocol_errors: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        elif event_type == "turn.completed":
            usage = event.get("usage") or {}
        elif event_type in {"error", "turn.failed"}:
            protocol_errors.append(str(event.get("message") or event.get("error") or event))
    if protocol_errors:
        raise CodexProtocolError("; ".join(protocol_errors))
    if not thread_id:
        raise CodexProtocolError("Codex JSONL did not contain thread.started")
    if not messages:
        raise CodexProtocolError("Codex JSONL did not contain an agent_message")
    return ConversationResult(
        result=messages[-1],
        session_id=thread_id,
        metadata={"usage": usage},
    )


class CodexClient:
    def __init__(
        self,
        command: CliCommand | None = None,
        timeout_seconds: float | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self.command = command or resolve_codex_command()
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
        model: str | None = None,
        sandbox: SandboxMode = "read-only",
        reasoning_effort: ReasoningEffort | None = None,
        web_search: bool = True,
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
        result = await run_process(
            self.command.executable,
            args,
            prompt=prompt,
            cwd=cwd,
            timeout_seconds=self.timeout_seconds,
            idle_timeout_seconds=self.idle_timeout_seconds,
        )
        return parse_codex_events(result.stdout)

    async def reply(
        self,
        session_id: str,
        prompt: str,
        *,
        cwd: Path,
        model: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        web_search: bool = True,
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
        result = await run_process(
            self.command.executable,
            args,
            prompt=prompt,
            cwd=cwd,
            timeout_seconds=self.timeout_seconds,
            idle_timeout_seconds=self.idle_timeout_seconds,
        )
        return parse_codex_events(result.stdout)
