from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONDA = os.getenv("CONDA_EXE") or shutil.which("conda.exe") or shutil.which("conda")
ROOT = Path(__file__).resolve().parents[1]

@asynccontextmanager
async def session_for(
    entrypoint: str,
    *,
    source: str | None = None,
    env: dict[str, str] | None = None,
):
    if source:
        command = shutil.which("uvx.exe") or shutil.which("uvx")
        if command is None:
            raise RuntimeError("uvx is not installed or not on PATH")
        args = ["--from", source, entrypoint]
    else:
        if CONDA is None:
            raise RuntimeError("Conda is not installed or not on PATH; set CONDA_EXE explicitly")
        command = CONDA
        args = ["run", "-n", "mcpserver", "--no-capture-output", entrypoint]
    parameters = StdioServerParameters(
        command=command,
        args=args,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


async def list_server_tools(entrypoint: str, source: str | None) -> list[str]:
    async with session_for(entrypoint, source=source) as session:
        result = await session.list_tools()
        return [tool.name for tool in result.tools]


async def live_codex(source: str | None) -> None:
    async with session_for("mcp-codex", source=source) as session:
        first = await session.call_tool(
            "codex",
            {
                "prompt": "Reply with exactly CODEX_MCP_LIVE_FIRST_OK.",
                "cwd": str(ROOT),
            },
        )
        session_id = first.structuredContent["sessionId"]
        second = await session.call_tool(
            "codex_reply",
            {
                "session_id": session_id,
                "prompt": "Reply with exactly CODEX_MCP_LIVE_SECOND_OK.",
                "cwd": str(ROOT),
            },
        )
        print(first.structuredContent)
        print(second.structuredContent)


async def live_claude(source: str | None) -> None:
    async with session_for("mcp-claude", source=source) as session:
        first = await session.call_tool(
            "claude",
            {
                "prompt": "Reply with exactly CLAUDE_MCP_LIVE_FIRST_OK.",
                "cwd": str(ROOT),
                "effort": "low",
                "read_tools": False,
            },
        )
        session_id = first.structuredContent["sessionId"]
        second = await session.call_tool(
            "claude_reply",
            {
                "session_id": session_id,
                "prompt": "Reply with exactly CLAUDE_MCP_LIVE_SECOND_OK.",
                "cwd": str(ROOT),
                "effort": "low",
                "read_tools": False,
            },
        )
        print(first.structuredContent)
        print(second.structuredContent)


async def main(live: bool, source: str | None) -> None:
    expected = {
        "mcp-codex": ["codex", "codex_reply"],
        "mcp-claude": ["claude", "claude_reply"],
        "mcp-grok": [
            "grok",
            "grok_reply",
            "grok_models",
            "grok_config",
            "grok_delete_session",
        ],
    }
    for entrypoint, expected_tools in expected.items():
        tools = await list_server_tools(entrypoint, source)
        if tools != expected_tools:
            raise RuntimeError(f"{entrypoint}: expected {expected_tools}, got {tools}")
        print(f"{entrypoint}: {','.join(tools)}")
    if live:
        await live_codex(source)
        await live_claude(source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call real Codex and Claude APIs")
    parser.add_argument(
        "--source",
        help="Install and run each entrypoint with uvx --from SOURCE instead of Conda",
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.live, arguments.source))
