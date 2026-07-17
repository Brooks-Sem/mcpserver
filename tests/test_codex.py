from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.cli import CliCommand
from mcpserver.codex import CodexClient, CodexProtocolError, parse_codex_events
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


def test_parse_codex_events_surfaces_failure() -> None:
    output = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-1"}',
            '{"type":"turn.failed","error":"upstream failed"}',
        ]
    )
    with pytest.raises(CodexProtocolError, match="upstream failed"):
        parse_codex_events(output)


@pytest.mark.asyncio
async def test_codex_start_enables_live_search_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(executable: str, args: list[str], **kwargs: object) -> ProcessResult:
        captured.update(executable=executable, args=args, **kwargs)
        return ProcessResult(
            stdout="\n".join(
                [
                    '{"type":"thread.started","thread_id":"thread-1"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}',
                ]
            ),
            stderr="",
            return_code=0,
        )

    monkeypatch.setattr("mcpserver.codex.run_process", fake_run_process)
    client = CodexClient(command=CliCommand("codex"))

    await client.start("hello", cwd=Path.cwd(), reasoning_effort="xhigh")

    assert captured["args"][:4] == [
        "--search",
        "-c",
        'model_reasoning_effort="xhigh"',
        "exec",
    ]
    assert "read-only" in captured["args"]
    assert captured["prompt"] == "hello"
