from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import GrokConfig
from .grok import GrokClient
from .models import (
    ConversationResponse,
    DeleteSessionResponse,
    GrokConfigResponse,
    GrokModelsResponse,
)

mcp = FastMCP(
    "grok-direct",
    instructions=(
        "Direct Grok conversations through an OpenAI-compatible API. "
        "Sessions are persisted locally in SQLite."
    ),
)


def _client() -> GrokClient:
    return GrokClient(GrokConfig.from_env())


@mcp.tool(structured_output=True)
async def grok(
    prompt: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
    system_prompt: str | None = None,
) -> ConversationResponse:
    """Start a Grok conversation using server-configured API credentials."""
    result = await _client().start(
        prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        system_prompt=system_prompt,
    )
    return result.as_response()


@mcp.tool(structured_output=True)
async def grok_reply(
    session_id: str,
    prompt: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> ConversationResponse:
    """Continue a locally persisted Grok conversation."""
    result = await _client().reply(
        session_id,
        prompt,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    return result.as_response()


@mcp.tool(structured_output=True)
async def grok_models() -> GrokModelsResponse:
    """List available model IDs after validating the /models response schema."""
    config = GrokConfig.from_env()
    return GrokModelsResponse(
        models=await GrokClient(config).list_models(),
        config=GrokConfigResponse(**config.masked()),
    )


@mcp.tool(structured_output=True)
def grok_config() -> GrokConfigResponse:
    """Show non-secret Grok server configuration."""
    return GrokConfigResponse(**GrokConfig.from_env().masked())


@mcp.tool(structured_output=True)
def grok_delete_session(session_id: str) -> DeleteSessionResponse:
    """Delete one locally persisted Grok session."""
    deleted = _client().session_store.delete(session_id, "grok")
    return DeleteSessionResponse(sessionId=session_id, deleted=deleted)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
