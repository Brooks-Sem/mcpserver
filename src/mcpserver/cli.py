from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CliCommand:
    executable: str
    prefix_args: tuple[str, ...] = ()


def _configured_command(env_name: str) -> CliCommand | None:
    configured = os.getenv(env_name, "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    if path.is_file():
        return CliCommand(str(path.resolve()))
    resolved = shutil.which(configured)
    if resolved:
        return CliCommand(resolved)
    raise FileNotFoundError(f"{env_name} points to a missing command: {configured}")


def resolve_codex_command() -> CliCommand:
    configured = _configured_command("CODEX_COMMAND")
    if configured:
        return configured
    launcher = shutil.which("codex.cmd") or shutil.which("codex")
    if launcher is None:
        raise FileNotFoundError("Codex CLI is not installed or not on PATH")
    launcher_path = Path(launcher)
    if launcher_path.suffix.lower() == ".cmd":
        script = launcher_path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node.exe") or shutil.which("node")
        if script.is_file() and node:
            return CliCommand(node, (str(script),))
    return CliCommand(launcher)


def resolve_claude_command() -> CliCommand:
    configured = _configured_command("CLAUDE_COMMAND")
    if configured:
        return configured
    launcher = shutil.which("claude.cmd") or shutil.which("claude")
    if launcher is None:
        raise FileNotFoundError("Claude Code CLI is not installed or not on PATH")
    launcher_path = Path(launcher)
    if launcher_path.suffix.lower() == ".cmd":
        executable = (
            launcher_path.parent
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
        if executable.is_file():
            return CliCommand(str(executable))
    return CliCommand(launcher)
