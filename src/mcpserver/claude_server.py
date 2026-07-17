from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .claude import ClaudeClient
from .models import ConversationResponse

mcp = FastMCP(
    "claude-direct",
    instructions="Direct Claude Code CLI conversations with native resumable session IDs.",
)


def _working_directory(cwd: str | None) -> Path:
    path = Path(cwd).expanduser() if cwd else Path.home()
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Working directory does not exist: {path}")
    return path


def _tools(read_tools: bool) -> tuple[Literal["Read", "Grep", "Glob"], ...]:
    return ("Read", "Grep", "Glob") if read_tools else ()


@mcp.tool(structured_output=True)
async def claude(
    prompt: str,
    cwd: str | None = None,
    model: Literal["fable", "opus", "sonnet", "haiku"] | None = None,
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high",
    read_tools: bool = True,
) -> ConversationResponse:
    """Start a direct Claude CLI conversation and return a resumable session ID."""
    result = await ClaudeClient().start(
        prompt,
        cwd=_working_directory(cwd),
        model=model,
        effort=effort,
        tools=_tools(read_tools),
    )
    return result.as_response()


@mcp.tool(structured_output=True)
async def claude_reply(
    session_id: str,
    prompt: str,
    cwd: str | None = None,
    model: Literal["fable", "opus", "sonnet", "haiku"] | None = None,
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high",
    read_tools: bool = True,
) -> ConversationResponse:
    """Continue a Claude CLI conversation using a prior session ID."""
    result = await ClaudeClient().reply(
        session_id,
        prompt,
        cwd=_working_directory(cwd),
        model=model,
        effort=effort,
        tools=_tools(read_tools),
    )
    return result.as_response()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
