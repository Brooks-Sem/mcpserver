from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpserver.claude import ClaudeClient, ClaudeProtocolError, parse_claude_result
from mcpserver.cli import CliCommand
from mcpserver.process import ProcessResult


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


@pytest.mark.asyncio
async def test_claude_start_allows_read_and_web_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        return ProcessResult(
            stdout=json.dumps(
                {
                    "is_error": False,
                    "result": "OK",
                    "session_id": "session-1",
                    "modelUsage": {"claude-fable-5": {}},
                }
            ),
            stderr="",
            return_code=0,
        )

    monkeypatch.setattr("mcpserver.claude.run_process", fake_run_process)
    client = ClaudeClient(command=CliCommand("claude"))

    await client.start(
        "hello",
        cwd=Path.cwd(),
        tools=("Read", "Grep", "Glob", "WebSearch", "WebFetch"),
    )

    args = captured["args"]
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch"
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert captured["prompt"] == "hello"
