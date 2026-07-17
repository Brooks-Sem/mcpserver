from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .codex import CodexClient
from .models import ConversationResponse

mcp = FastMCP(
    "codex-direct",
    instructions="Direct Codex CLI conversations with native resumable thread IDs.",
)


def _working_directory(cwd: str | None) -> Path:
    path = Path(cwd).expanduser() if cwd else Path.home()
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Working directory does not exist: {path}")
    return path


@mcp.tool(structured_output=True)
async def codex(
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "read-only",
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None,
    web_search: bool = True,
) -> ConversationResponse:
    """Start a direct Codex CLI conversation and return a resumable thread ID."""
    result = await CodexClient().start(
        prompt,
        cwd=_working_directory(cwd),
        model=model,
        sandbox=sandbox,
        reasoning_effort=reasoning_effort,
        web_search=web_search,
    )
    return result.as_response()


@mcp.tool(structured_output=True)
async def codex_reply(
    session_id: str,
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None,
    web_search: bool = True,
) -> ConversationResponse:
    """Continue a Codex CLI conversation using a prior thread ID."""
    result = await CodexClient().reply(
        session_id,
        prompt,
        cwd=_working_directory(cwd),
        model=model,
        reasoning_effort=reasoning_effort,
        web_search=web_search,
    )
    return result.as_response()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
