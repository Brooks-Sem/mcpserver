from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpserver.claude import (
    ClaudeClient,
    ClaudeProtocolError,
    claude_event_status,
    parse_claude_result,
    parse_claude_stream,
)
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
    with pytest.raises(ClaudeProtocolError, match="upstream error"):
        parse_claude_result(json.dumps({"is_error": True, "result": "upstream failed"}))


def test_parse_claude_result_rejects_invalid_json() -> None:
    with pytest.raises(ClaudeProtocolError, match="invalid JSON"):
        parse_claude_result("not-json")


def test_parse_claude_stream_uses_final_result_event() -> None:
    output = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init", "session_id": "session-1"}),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {"type": "content_block_delta", "delta": {"text": "partial"}},
                }
            ),
            "not-json",
            json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "result": "OK",
                    "session_id": "session-1",
                    "total_cost_usd": 0.2,
                    "usage": {"input_tokens": 4},
                    "modelUsage": {"claude-sonnet-5": {}},
                }
            ),
        ]
    )

    result = parse_claude_stream(output)

    assert result.result == "OK"
    assert result.session_id == "session-1"
    assert result.model == "claude-sonnet-5"
    assert result.metadata["costUsd"] == 0.2


def test_parse_claude_stream_rejects_missing_result() -> None:
    with pytest.raises(ClaudeProtocolError, match="did not contain a result event"):
        parse_claude_stream('{"type":"system","subtype":"init"}')


def test_parse_claude_stream_surfaces_result_error() -> None:
    output = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "result": "upstream failed",
            "session_id": "session-1",
        }
    )
    with pytest.raises(ClaudeProtocolError, match="upstream error"):
        parse_claude_stream(output)


def test_claude_event_status_does_not_expose_event_content() -> None:
    secret = "PRIVATE_MODEL_TEXT"
    status = claude_event_status(
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": secret},
                },
            }
        )
    )

    assert status == "Claude is composing a response"
    assert secret not in status
    assert claude_event_status("not-json") is None


@pytest.mark.asyncio
async def test_claude_start_allows_read_and_web_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    progress_messages: list[str] = []

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        observer = kwargs["output_observer"]
        observer("stdout", '{"type":"system","subtype":"init"}')
        observer(
            "stdout",
            '{"type":"stream_event","event":{"type":"message_start"}}',
        )
        result_line = json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "OK",
                "session_id": "session-1",
                "modelUsage": {"claude-fable-5": {}},
            }
        )
        observer("stdout", result_line)
        return ProcessResult(stdout=result_line, stderr="", return_code=0)

    monkeypatch.setattr("mcpserver.claude.run_process", fake_run_process)
    client = ClaudeClient(command=CliCommand("claude"))

    async def on_progress(message: str) -> None:
        progress_messages.append(message)

    await client.start(
        "hello",
        cwd=Path.cwd(),
        tools=("Read", "Grep", "Glob", "WebSearch", "WebFetch"),
        progress_callback=on_progress,
    )

    args = captured["args"]
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch"
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in args
    assert "--include-partial-messages" in args
    assert captured["prompt"] == "hello"
    assert captured["idle_timeout_seconds"] == 300
    assert "timeout_seconds" not in captured
    assert progress_messages


@pytest.mark.asyncio
async def test_claude_reply_passes_resume_and_stream_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        result_line = json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "OK",
                "session_id": "session-1",
            }
        )
        kwargs["output_observer"]("stdout", result_line)
        return ProcessResult(stdout=result_line, stderr="", return_code=0)

    monkeypatch.setattr("mcpserver.claude.run_process", fake_run_process)

    await ClaudeClient(command=CliCommand("claude")).reply(
        "session-1",
        "again",
        cwd=Path.cwd(),
    )

    args = captured["args"]
    assert args[args.index("--resume") + 1] == "session-1"
    assert callable(captured["output_observer"])
