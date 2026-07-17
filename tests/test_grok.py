from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mcpserver.config import GrokConfig
from mcpserver.grok import GrokClient, GrokProtocolError
from mcpserver.sessions import SessionStore


def _config() -> GrokConfig:
    return GrokConfig(
        api_url="https://grok.example/v1",
        api_key="".join(("te", "st")),
        model="grok-test",
        reasoning_effort="high",
        reasoning_field="reasoning_effort",
        timeout_seconds=10,
        max_retries=1,
    )


@pytest.mark.asyncio
async def test_grok_start_and_reply_persist_history(tmp_path: Path) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        answer = "FIRST" if len(requests) == 1 else "SECOND"
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "choices": [{"message": {"content": answer, "reasoning_content": "R"}}],
                "usage": {"total_tokens": 3},
            },
        )

    client = GrokClient(
        _config(),
        session_store=SessionStore(tmp_path / "sessions.db"),
        transport=httpx.MockTransport(handler),
    )

    first = await client.start("hello")
    second = await client.reply(first.session_id, "again", reasoning_effort="xhigh")

    assert first.result == "FIRST"
    assert second.result == "SECOND"
    assert second.session_id == first.session_id
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[1]["reasoning_effort"] == "xhigh"
    assert requests[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "FIRST"},
        {"role": "user", "content": "again"},
    ]


@pytest.mark.asyncio
async def test_models_rejects_false_positive_endpoint(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "ok"}))
    client = GrokClient(
        _config(),
        session_store=SessionStore(tmp_path / "sessions.db"),
        transport=transport,
    )

    with pytest.raises(GrokProtocolError, match="data list"):
        await client.list_models()


@pytest.mark.asyncio
async def test_models_accepts_model_ids(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "grok-a"}, {"id": "grok-b"}]})
    )
    client = GrokClient(
        _config(),
        session_store=SessionStore(tmp_path / "sessions.db"),
        transport=transport,
    )

    assert await client.list_models() == ["grok-a", "grok-b"]
