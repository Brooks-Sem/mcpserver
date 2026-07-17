from __future__ import annotations

import json

import pytest

from mcpserver.claude import ClaudeProtocolError, parse_claude_result


def test_parse_claude_result() -> None:
    output = json.dumps(
        {
            "is_error": False,
            "result": "OK",
            "session_id": "session-1",
            "total_cost_usd": 0.1,
            "usage": {"input_tokens": 2},
            "modelUsage": {"claude-sonnet-5": {}},
        }
    )

    result = parse_claude_result(output)

    assert result.result == "OK"
    assert result.session_id == "session-1"
    assert result.model == "claude-sonnet-5"
    assert result.metadata == {
        "models": ["claude-sonnet-5"],
        "costUsd": 0.1,
        "usage": {"input_tokens": 2},
    }


def test_parse_claude_result_rejects_error() -> None:
    with pytest.raises(ClaudeProtocolError, match="upstream failed"):
        parse_claude_result(json.dumps({"is_error": True, "result": "upstream failed"}))


def test_parse_claude_result_rejects_invalid_json() -> None:
    with pytest.raises(ClaudeProtocolError, match="invalid JSON"):
        parse_claude_result("not-json")
