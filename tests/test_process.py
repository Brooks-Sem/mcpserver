from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from mcpserver.process import run_process


@pytest.mark.asyncio
async def test_run_process_kills_silent_process_after_idle_timeout(tmp_path: Path) -> None:
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="produced no output"):
        await run_process(
            sys.executable,
            ["-c", "import time; time.sleep(10)"],
            prompt="",
            cwd=tmp_path,
            timeout_seconds=10,
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
                "print('first'); time.sleep(1.2); "
                "print('second'); time.sleep(1.2); print('third')"
            ),
        ],
        prompt="",
        cwd=tmp_path,
        timeout_seconds=6,
        idle_timeout_seconds=2,
    )

    assert result.stdout.splitlines() == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_run_process_enforces_total_timeout_despite_output(tmp_path: Path) -> None:
    with pytest.raises(TimeoutError, match="total timeout"):
        await run_process(
            sys.executable,
            [
                "-u",
                "-c",
                "import time\nwhile True:\n print('tick', flush=True)\n time.sleep(0.05)",
            ],
            prompt="",
            cwd=tmp_path,
            timeout_seconds=0.3,
            idle_timeout_seconds=2,
        )


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
            timeout_seconds=5,
            idle_timeout_seconds=0.3,
        )

    await asyncio.sleep(1.1)
    assert not marker.exists()