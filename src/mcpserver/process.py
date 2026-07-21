from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .windows_job import WindowsProcessJob


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    return_code: int


class ProcessExecutionError(RuntimeError):
    def __init__(self, command: str, result: ProcessResult) -> None:
        streams = []
        if result.stderr:
            streams.append(f"stderr captured ({len(result.stderr)} chars)")
        if result.stdout:
            streams.append(f"stdout captured ({len(result.stdout)} chars)")
        detail = ", ".join(streams) or "no process output"
        super().__init__(f"{command} exited with code {result.return_code}: {detail}")
        self.result = result


OutputStream = Literal["stdout", "stderr"]
OutputObserver = Callable[[OutputStream, str], None]
ProgressCallback = Callable[[str], Awaitable[None]]


class ProgressReporter:
    """Coalesce progress updates without blocking subprocess pipe readers."""

    def __init__(
        self,
        callback: ProgressCallback | None,
        *,
        minimum_interval_seconds: float = 0.5,
    ) -> None:
        self.callback = callback
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_message: str | None = None
        self._last_sent_at = float("-inf")
        self._pending_message: str | None = None
        self._task: asyncio.Task[None] | None = None

    def publish(self, message: str) -> None:
        if self.callback is None or message in {self._last_message, self._pending_message}:
            return
        self._pending_message = message
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while self._pending_message is not None:
            remaining = self.minimum_interval_seconds - (loop.time() - self._last_sent_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            message = self._pending_message
            self._pending_message = None
            try:
                assert self.callback is not None
                await self.callback(message)
            except Exception:
                pass
            self._last_message = message
            self._last_sent_at = loop.time()

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        message = self._pending_message
        self._pending_message = None
        if self.callback is None or message is None or message == self._last_message:
            return
        with suppress(Exception):
            await asyncio.wait_for(self.callback(message), timeout=1.0)
        self._last_message = message


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
    idle_timeout_seconds: float = 300.0,
    output_observer: OutputObserver | None = None,
    capture_output_limit_bytes: int = 1024 * 1024,
) -> ProcessResult:
    if idle_timeout_seconds <= 0:
        raise ValueError("idle_timeout_seconds must be positive")
    if capture_output_limit_bytes < 0:
        raise ValueError("capture_output_limit_bytes must not be negative")
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
    process_job: WindowsProcessJob | None = None
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    activity: asyncio.Queue[None] = asyncio.Queue(maxsize=1)

    def capture(buffer: bytearray, chunk: bytes) -> None:
        if capture_output_limit_bytes == 0:
            return
        buffer.extend(chunk)
        overflow = len(buffer) - capture_output_limit_bytes
        if overflow > 0:
            del buffer[:overflow]

    async def read_stream(
        name: OutputStream,
        stream: asyncio.StreamReader,
        buffer: bytearray,
    ) -> None:
        pending = bytearray()
        while chunk := await stream.read(64 * 1024):
            capture(buffer, chunk)
            if activity.empty():
                activity.put_nowait(None)
            if output_observer is None:
                continue
            pending.extend(chunk)
            while (newline := pending.find(b"\n")) >= 0:
                raw_line = bytes(pending[:newline])
                del pending[: newline + 1]
                with suppress(Exception):
                    output_observer(name, raw_line.rstrip(b"\r").decode("utf-8", errors="replace"))
        if output_observer is not None and pending:
            with suppress(Exception):
                output_observer(name, bytes(pending).decode("utf-8", errors="replace"))

    async def cleanup(tasks: list[asyncio.Task[object]]) -> None:
        if process_job:
            process_job.close()
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        with suppress(Exception):
            await process.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    tasks: list[asyncio.Task[object]] = []
    try:
        process_job = WindowsProcessJob.attach(process)
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(read_stream("stdout", process.stdout, stdout_buffer))
        stderr_task = asyncio.create_task(read_stream("stderr", process.stderr, stderr_buffer))
        wait_task = asyncio.create_task(process.wait())
        tasks.extend((stdout_task, stderr_task, wait_task))
        loop = asyncio.get_running_loop()
        last_activity = loop.time()

        async def wait_with_idle_timeout(task: asyncio.Task[object]) -> object:
            nonlocal last_activity
            while not task.done():
                remaining_idle = idle_timeout_seconds - (loop.time() - last_activity)
                if remaining_idle <= 0:
                    raise TimeoutError(
                        f"Process produced no output for {idle_timeout_seconds:g}s"
                    )
                activity_task = asyncio.create_task(activity.get())
                done, _ = await asyncio.wait(
                    (task, activity_task),
                    timeout=remaining_idle,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if activity_task not in done:
                    activity_task.cancel()
                await asyncio.gather(activity_task, return_exceptions=True)
                if activity_task in done:
                    last_activity = loop.time()
                    continue
                if task not in done:
                    raise TimeoutError(
                        f"Process produced no output for {idle_timeout_seconds:g}s"
                    )
            return await task

        process.stdin.write(prompt.encode("utf-8"))
        drain_task: asyncio.Task[object] = asyncio.create_task(process.stdin.drain())
        tasks.append(drain_task)
        await wait_with_idle_timeout(drain_task)
        process.stdin.close()
        await wait_with_idle_timeout(wait_task)
        await asyncio.gather(stdout_task, stderr_task)

        result = ProcessResult(
            stdout=stdout_buffer.decode("utf-8", errors="replace"),
            stderr=stderr_buffer.decode("utf-8", errors="replace"),
            return_code=process.returncode or 0,
        )
        if result.return_code != 0:
            raise ProcessExecutionError(Path(executable).name, result)
        return result
    finally:
        await cleanup(tasks)
