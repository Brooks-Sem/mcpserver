from __future__ import annotations

import pytest

from mcpserver.codex import CodexProtocolError, parse_codex_events


def test_parse_codex_events() -> None:
    output = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}',
            '{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":1}}',
        ]
    )

    result = parse_codex_events(output)

    assert result.result == "OK"
    assert result.session_id == "thread-1"
    assert result.metadata == {"usage": {"input_tokens": 3, "output_tokens": 1}}


def test_parse_codex_events_rejects_missing_message() -> None:
    with pytest.raises(CodexProtocolError, match="agent_message"):
        parse_codex_events('{"type":"thread.started","thread_id":"thread-1"}')


def test_parse_codex_events_surfaces_failure() -> None:
    output = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"turn.failed","error":"upstream failed"}',
        ]
    )
    with pytest.raises(CodexProtocolError, match="upstream failed"):
        parse_codex_events(output)
