from __future__ import annotations

import asyncio
import fcntl
import os
import struct
import termios as _termios_mod
from collections.abc import AsyncIterator, Awaitable
from typing import Literal


StreamName = Literal["stdout", "stderr"]


class SandboxedProcess:
    """Wrapper around an asyncio subprocess with streaming helpers."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        default_timeout: float | None = None,
        master_fd: int | None = None,
    ):
        self._process = process
        self._default_timeout = default_timeout
        self._master_fd = master_fd

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

    @property
    def master_fd(self) -> int | None:
        """The PTY master file descriptor, or None if not in PTY mode."""
        return self._master_fd

    def set_terminal_size(self, rows: int, cols: int) -> None:
        """Set the PTY terminal dimensions (rows x cols)."""
        if self._master_fd is None:
            raise RuntimeError("PTY mode is not enabled")
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, _termios_mod.TIOCSWINSZ, size)

    def close_pty(self) -> None:
        """Close the PTY master fd.  Safe to call multiple times."""
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    async def send(self, data: bytes) -> None:
        """Send raw bytes to stdin (or the PTY master when in PTY mode)."""
        if self._master_fd is not None:
            os.write(self._master_fd, data)
            return
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
        check: bool = False,
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

    def _format_chunk(
        self,
        name: StreamName,
        data: bytes,
        decode: bool | str,
        include_stream: bool,
    ) -> bytes | str | tuple[StreamName, bytes] | tuple[StreamName, str]:
        if decode:
            enc = decode if isinstance(decode, str) else "utf-8"
            payload: bytes | str = data.decode(enc, errors="replace")
        else:
            payload = data
        return (name, payload) if include_stream else payload

    async def _pty_chunks(self, chunk_size: int) -> AsyncIterator[bytes]:
        """Yield raw byte chunks from the PTY master fd."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        os.set_blocking(self._master_fd, False)

        def _on_readable() -> None:
            try:
                data = os.read(self._master_fd, chunk_size)
                queue.put_nowait(data if data else None)
            except OSError:
                queue.put_nowait(None)

        loop.add_reader(self._master_fd, _on_readable)
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            loop.remove_reader(self._master_fd)

    async def stream(
        self,
        *,
        include_stream: bool = False,
        decode: bool | str = False,
        chunk_size: int = 4096,
    ) -> AsyncIterator[bytes | str | tuple[StreamName, bytes] | tuple[StreamName, str]]:
        """Yield interleaved output from stdout/stderr (or the PTY).

        If include_stream is True, yields (stream_name, chunk).
        If decode is True or a string, decodes bytes with the given encoding.
        In PTY mode the stream name is always ``"stdout"``.
        """
        if self._master_fd is not None:
            async for chunk in self._pty_chunks(chunk_size):
                yield self._format_chunk("stdout", chunk, decode, include_stream)
            return

        stdout = self._process.stdout
        stderr = self._process.stderr
        if stdout is None and stderr is None:
            return

        queue: asyncio.Queue[tuple[StreamName, bytes | None]] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _reader(stream_obj: asyncio.StreamReader, name: StreamName) -> None:
            while True:
                data = await stream_obj.read(chunk_size)
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
                yield self._format_chunk(name, data, decode, include_stream)
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
        """Yield interleaved lines from stdout/stderr (or the PTY).

        Lines include trailing newlines when present.
        If include_stream is True, yields (stream_name, line).
        If decode is True or a string, decodes bytes with the given encoding.
        In PTY mode the stream name is always ``"stdout"``.
        """
        if self._master_fd is not None:
            buf = b""
            async for chunk in self._pty_chunks(4096):
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    yield self._format_chunk("stdout", line + b"\n", decode, include_stream)
            if buf:
                yield self._format_chunk("stdout", buf, decode, include_stream)
            return

        stdout = self._process.stdout
        stderr = self._process.stderr
        if stdout is None and stderr is None:
            return

        queue: asyncio.Queue[tuple[StreamName, bytes | None]] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _reader(stream_obj: asyncio.StreamReader, name: StreamName) -> None:
            while True:
                line = await stream_obj.readline()
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
                yield self._format_chunk(name, data, decode, include_stream)
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
