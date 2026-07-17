from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .windows_job import WindowsProcessJob


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
    idle_timeout_seconds: float | None = None,
) -> ProcessResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    idle_timeout = idle_timeout_seconds or timeout_seconds
    if idle_timeout <= 0:
        raise ValueError("idle_timeout_seconds must be positive")
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
    process_job = WindowsProcessJob.attach(process)
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    activity: asyncio.Queue[None] = asyncio.Queue()

    async def read_stream(stream: asyncio.StreamReader, chunks: list[bytes]) -> None:
        while chunk := await stream.read(64 * 1024):
            chunks.append(chunk)
            activity.put_nowait(None)

    async def terminate() -> None:
        if process_job:
            process_job.close()
        if process.returncode is None:
            process.kill()
        await process.wait()

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_chunks))
    stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_chunks))
    wait_task = asyncio.create_task(process.wait())
    loop = asyncio.get_running_loop()
    total_deadline = loop.time() + timeout_seconds
    try:
        process.stdin.write(prompt.encode("utf-8"))
        await asyncio.wait_for(process.stdin.drain(), timeout=timeout_seconds)
        process.stdin.close()
        last_activity = loop.time()
        while not wait_task.done():
            now = loop.time()
            remaining_total = total_deadline - now
            remaining_idle = idle_timeout - (now - last_activity)
            waiting_for_total_timeout = remaining_total <= remaining_idle
            wait_seconds = min(remaining_total, remaining_idle)
            if wait_seconds <= 0:
                if remaining_total <= 0:
                    raise TimeoutError(f"Process exceeded total timeout of {timeout_seconds:g}s")
                raise TimeoutError(f"Process produced no output for {idle_timeout:g}s")
            activity_task = asyncio.create_task(activity.get())
            done, _ = await asyncio.wait(
                (wait_task, activity_task),
                timeout=wait_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if activity_task not in done:
                activity_task.cancel()
            await asyncio.gather(activity_task, return_exceptions=True)
            if wait_task in done:
                break
            if activity_task in done:
                last_activity = loop.time()
                continue
            if waiting_for_total_timeout:
                raise TimeoutError(f"Process exceeded total timeout of {timeout_seconds:g}s")
            raise TimeoutError(f"Process produced no output for {idle_timeout:g}s")
    except (TimeoutError, asyncio.CancelledError):
        await terminate()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise

    if process_job:
        process_job.close()
    await asyncio.gather(stdout_task, stderr_task)

    result = ProcessResult(
        stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
        stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        return_code=process.returncode or 0,
    )
    if result.return_code != 0:
        raise ProcessExecutionError(Path(executable).name, result)
    return result
