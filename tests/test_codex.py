from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.cli import CliCommand
from mcpserver.codex import (
    CodexClient,
    CodexProtocolError,
    codex_event_status,
    parse_codex_events,
)
from mcpserver.process import ProcessResult


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


def test_parse_codex_events_rejects_truncated_turn() -> None:
    output = "\n".join(
        [
            "[]",
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}',
        ]
    )
    with pytest.raises(CodexProtocolError, match="turn.completed"):
        parse_codex_events(output)


def test_parse_codex_events_surfaces_failure() -> None:
    output = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"turn.failed","error":"upstream failed"}',
        ]
    )
    with pytest.raises(CodexProtocolError, match="upstream error"):
        parse_codex_events(output)


def test_codex_event_status_does_not_expose_event_content() -> None:
    secret = "PRIVATE_AGENT_TEXT"

    assert codex_event_status('{"type":"thread.started","thread_id":"private-id"}') == (
        "Codex session started"
    )
    status = codex_event_status(
        '{"type":"item.completed","item":{"type":"agent_message","text":"'
        + secret
        + '"}}'
    )

    assert status == "Codex prepared a response"
    assert secret not in status
    assert codex_event_status("not-json") is None


@pytest.mark.asyncio
async def test_codex_start_enables_live_search_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    progress_messages: list[str] = []

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        observer = kwargs["output_observer"]
        lines = [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}',
            '{"type":"turn.completed","usage":{}}',
        ]
        for line in lines:
            observer("stdout", line)
        return ProcessResult(stdout="\n".join(lines), stderr="", return_code=0)

    monkeypatch.setattr("mcpserver.codex.run_process", fake_run_process)
    client = CodexClient(command=CliCommand("codex"))

    async def on_progress(message: str) -> None:
        progress_messages.append(message)

    await client.start(
        "hello",
        cwd=Path.cwd(),
        reasoning_effort="xhigh",
        progress_callback=on_progress,
    )

    assert captured["args"][:4] == [
        "--search",
        "-c",
        'model_reasoning_effort="xhigh"',
        "exec",
    ]
    assert "read-only" in captured["args"]
    assert captured["prompt"] == "hello"
    assert captured["idle_timeout_seconds"] == 300
    assert "timeout_seconds" not in captured
    assert progress_messages


@pytest.mark.asyncio
async def test_codex_reply_forwards_progress_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        lines = [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}',
            '{"type":"turn.completed","usage":{}}',
        ]
        for line in lines:
            kwargs["output_observer"]("stdout", line)
        return ProcessResult(stdout="\n".join(lines), stderr="", return_code=0)

    monkeypatch.setattr("mcpserver.codex.run_process", fake_run_process)
    progress_messages: list[str] = []

    async def callback(message: str) -> None:
        progress_messages.append(message)

    await CodexClient(command=CliCommand("codex")).reply(
        "thread-1",
        "hello",
        cwd=Path.cwd(),
        progress_callback=callback,
    )

    assert callable(captured["output_observer"])
    assert captured["args"][-2:] == ["thread-1", "-"]
    assert progress_messages
