from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from typing import Literal


StreamName = Literal["stdout", "stderr"]


class SandboxedProcess:
    """Wrapper around an asyncio subprocess with streaming helpers."""

    def __init__(self, process: asyncio.subprocess.Process, default_timeout: float | None = None):
        self._process = process
        self._default_timeout = default_timeout

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    @property
    def stdin(self) -> asyncio.StreamWriter | None:
        return self._process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        return self._process.stdout

    @property
    def stderr(self) -> asyncio.StreamReader | None:
        return self._process.stderr

    @property
    def raw(self) -> asyncio.subprocess.Process:
        return self._process

    async def send(self, data: bytes) -> None:
        """Send raw bytes to stdin."""
        if self._process.stdin is None:
            raise RuntimeError("stdin is not available for this process")
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def send_text(self, text: str, encoding: str = "utf-8") -> None:
        """Send text to stdin."""
        await self.send(text.encode(encoding))

    def close_stdin(self) -> None:
        """Close stdin to signal EOF to the process."""
        if self._process.stdin is not None:
            self._process.stdin.close()

    async def wait(self, timeout: float | None = None, check: bool = False) -> int:
        """Wait for the process to finish."""
        returncode = await self._wait_with_timeout(self._process.wait(), timeout)
        if check and returncode != 0:
            raise RuntimeError(f"Command failed with exit code {returncode}")
        return returncode

    async def communicate(
        self,
        input: bytes | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> tuple[bytes, bytes]:
        """Wait for completion and collect stdout/stderr."""
        if input is not None and self._process.stdin is None:
            raise RuntimeError("stdin is not available for this process")

        stdout, stderr = await self._communicate_with_timeout(input, timeout)

        stdout = stdout or b""
        stderr = stderr or b""
        if check and self._process.returncode != 0:
            raise RuntimeError(
                f"Command failed with exit code {self._process.returncode}",
                stdout,
                stderr,
            )
        return stdout, stderr

    async def stream(
        self,
        *,
        include_stream: bool = False,
        decode: bool | str = False,
        chunk_size: int = 4096,
    ) -> AsyncIterator[bytes | str | tuple[StreamName, bytes] | tuple[StreamName, str]]:
        """Yield interleaved output from stdout/stderr.

        If include_stream is True, yields (stream_name, chunk).
        If decode is True or a string, decodes bytes with the given encoding.
        """
        stdout = self._process.stdout
        stderr = self._process.stderr
        if stdout is None and stderr is None:
            return

        queue: asyncio.Queue[tuple[StreamName, bytes | None]] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _reader(stream: asyncio.StreamReader, name: StreamName) -> None:
            while True:
                data = await stream.read(chunk_size)
                if not data:
                    break
                await queue.put((name, data))
            await queue.put((name, None))

        if stdout is not None:
            tasks.append(asyncio.create_task(_reader(stdout, "stdout")))
        if stderr is not None:
            tasks.append(asyncio.create_task(_reader(stderr, "stderr")))

        finished = 0
        try:
            while finished < len(tasks):
                name, data = await queue.get()
                if data is None:
                    finished += 1
                    continue

                if decode:
                    encoding = decode if isinstance(decode, str) else "utf-8"
                    payload: bytes | str = data.decode(encoding, errors="replace")
                else:
                    payload = data

                if include_stream:
                    yield name, payload
                else:
                    yield payload
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_lines(
        self,
        *,
        include_stream: bool = False,
        decode: bool | str = True,
    ) -> AsyncIterator[bytes | str | tuple[StreamName, bytes] | tuple[StreamName, str]]:
        """Yield interleaved lines from stdout/stderr.

        Lines include trailing newlines when present.
        If include_stream is True, yields (stream_name, line).
        If decode is True or a string, decodes bytes with the given encoding.
        """
        stdout = self._process.stdout
        stderr = self._process.stderr
        if stdout is None and stderr is None:
            return

        queue: asyncio.Queue[tuple[StreamName, bytes | None]] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _reader(stream: asyncio.StreamReader, name: StreamName) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                await queue.put((name, line))
            await queue.put((name, None))

        if stdout is not None:
            tasks.append(asyncio.create_task(_reader(stdout, "stdout")))
        if stderr is not None:
            tasks.append(asyncio.create_task(_reader(stderr, "stderr")))

        finished = 0
        try:
            while finished < len(tasks):
                name, data = await queue.get()
                if data is None:
                    finished += 1
                    continue

                if decode:
                    encoding = decode if isinstance(decode, str) else "utf-8"
                    payload: bytes | str = data.decode(encoding, errors="replace")
                else:
                    payload = data

                if include_stream:
                    yield name, payload
                else:
                    yield payload
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def terminate(self) -> None:
        """Request graceful termination."""
        self._process.terminate()

    def kill(self) -> None:
        """Force kill the process."""
        self._process.kill()

    def _resolve_timeout(self, timeout: float | None) -> float | None:
        return self._default_timeout if timeout is None else timeout

    async def _wait_with_timeout(self, awaitable: Awaitable[int], timeout: float | None) -> int:
        timeout = self._resolve_timeout(timeout)
        if timeout is None:
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()
            raise TimeoutError(f"Command execution exceeded {timeout} seconds")

    async def _communicate_with_timeout(
        self,
        input: bytes | None,
        timeout: float | None,
    ) -> tuple[bytes | None, bytes | None]:
        timeout = self._resolve_timeout(timeout)
        try:
            if timeout is None:
                return await self._process.communicate(input=input)
            return await asyncio.wait_for(
                self._process.communicate(input=input),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()
            raise TimeoutError(f"Command execution exceeded {timeout} seconds")
