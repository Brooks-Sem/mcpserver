from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from mcpserver.process import ProcessExecutionError, run_process


@pytest.mark.asyncio
async def test_run_process_kills_silent_process_after_idle_timeout(tmp_path: Path) -> None:
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="produced no output"):
        await run_process(
            sys.executable,
            ["-c", "import time; time.sleep(10)"],
            prompt="",
            cwd=tmp_path,
            idle_timeout_seconds=1,
        )

    assert time.monotonic() - started < 8


@pytest.mark.asyncio
async def test_run_process_resets_idle_timeout_when_output_arrives(tmp_path: Path) -> None:
    result = await run_process(
        sys.executable,
        [
            "-u",
            "-c",
            (
                "import time; "
                "print('first'); time.sleep(0.2); "
                "print('second'); time.sleep(0.2); print('third')"
            ),
        ],
        prompt="",
        cwd=tmp_path,
        idle_timeout_seconds=1.5,
    )

    assert result.stdout.splitlines() == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_run_process_has_no_total_timeout_while_output_continues(tmp_path: Path) -> None:
    started = time.monotonic()
    result = await run_process(
        sys.executable,
        [
            "-u",
            "-c",
            "import time\nfor i in range(8):\n print(i, flush=True)\n time.sleep(0.12)",
        ],
        prompt="",
        cwd=tmp_path,
        idle_timeout_seconds=0.3,
    )

    assert time.monotonic() - started > 0.8
    assert result.stdout.splitlines() == [str(index) for index in range(8)]


@pytest.mark.asyncio
async def test_run_process_treats_stderr_as_activity(tmp_path: Path) -> None:
    result = await run_process(
        sys.executable,
        [
            "-u",
            "-c",
            (
                "import sys, time\n"
                "for i in range(5):\n"
                " print(f'err-{i}', file=sys.stderr, flush=True)\n"
                " time.sleep(0.12)"
            ),
        ],
        prompt="",
        cwd=tmp_path,
        idle_timeout_seconds=0.3,
    )

    assert result.stderr.splitlines() == [f"err-{index}" for index in range(5)]


@pytest.mark.asyncio
async def test_run_process_observes_complete_lines_before_exit(tmp_path: Path) -> None:
    observed: list[tuple[str, str, float]] = []
    started = time.monotonic()

    result = await run_process(
        sys.executable,
        [
            "-u",
            "-c",
            (
                "import sys, time\n"
                "sys.stdout.write('split')\n"
                "sys.stdout.flush()\n"
                "time.sleep(0.1)\n"
                "print('-line', flush=True)\n"
                "print('tail', end='', flush=True)\n"
                "time.sleep(0.25)"
            ),
        ],
        prompt="",
        cwd=tmp_path,
        idle_timeout_seconds=0.5,
        output_observer=lambda stream, line: observed.append(
            (stream, line, time.monotonic() - started)
        ),
    )

    assert result.stdout.splitlines() == ["split-line", "tail"]
    assert [(stream, line) for stream, line, _ in observed] == [
        ("stdout", "split-line"),
        ("stdout", "tail"),
    ]
    assert observed[0][2] < 1.0


@pytest.mark.asyncio
async def test_run_process_bounds_captured_output_without_truncating_observer(
    tmp_path: Path,
) -> None:
    observed: list[str] = []
    result = await run_process(
        sys.executable,
        ["-u", "-c", "print('a' * 200); print('FINAL')"],
        prompt="",
        cwd=tmp_path,
        idle_timeout_seconds=2,
        capture_output_limit_bytes=32,
        output_observer=lambda stream, line: observed.append(line) if stream == "stdout" else None,
    )

    assert len(result.stdout.encode()) <= 32
    assert observed[-1] == "FINAL"


@pytest.mark.asyncio
async def test_process_execution_error_does_not_expose_output(tmp_path: Path) -> None:
    secret = "PRIVATE_COMMAND_OUTPUT"
    with pytest.raises(ProcessExecutionError) as captured:
        await run_process(
            sys.executable,
            ["-c", f"import sys; print({secret!r}); sys.exit(2)"],
            prompt="",
            cwd=tmp_path,
            idle_timeout_seconds=2,
        )

    assert secret in captured.value.result.stdout
    assert secret not in str(captured.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree regression")
@pytest.mark.asyncio
async def test_run_process_kills_child_processes_on_windows(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived.txt"
    child_code = (
        "import pathlib, time; "
        "time.sleep(1); "
        f"pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(10)"
    )

    with pytest.raises(TimeoutError, match="produced no output"):
        await run_process(
            sys.executable,
            ["-c", parent_code],
            prompt="",
            cwd=tmp_path,
            idle_timeout_seconds=0.3,
        )

    await asyncio.sleep(1.1)
    assert not marker.exists()