from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    return_code: int


class ProcessExecutionError(RuntimeError):
    def __init__(self, command: str, result: ProcessResult) -> None:
        message = result.stderr.strip() or result.stdout.strip() or "no process output"
        super().__init__(f"{command} exited with code {result.return_code}: {message}")
        self.result = result


def resolve_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"Required command is not installed or not on PATH: {command}")
    return resolved


async def run_process(
    executable: str,
    args: Sequence[str],
    *,
    prompt: str,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 600.0,
) -> ProcessResult:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        cwd=str(cwd),
        env=process_env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(prompt.encode("utf-8")), timeout=timeout_seconds
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError(f"Process timed out after {timeout_seconds:.0f}s") from None

    result = ProcessResult(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        return_code=process.returncode or 0,
    )
    if result.return_code != 0:
        raise ProcessExecutionError(Path(executable).name, result)
    return result
