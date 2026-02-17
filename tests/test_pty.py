"""Tests for PTY mode in SandboxedProcess."""

import asyncio
import os

import pytest

from pybubble import Sandbox


@pytest.mark.asyncio
async def test_pty_stream_output(default_rootfs):
    """PTY stream() should yield output from the child process."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "echo hello",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        chunks: list[bytes] = []
        async for chunk in process.stream():
            chunks.append(chunk)

        output = b"".join(chunks)
        assert b"hello" in output
        process.close_pty()


@pytest.mark.asyncio
async def test_pty_stream_decode(default_rootfs):
    """PTY stream(decode=True) should yield decoded strings."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "echo decoded",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        chunks: list[str] = []
        async for chunk in process.stream(decode=True):
            chunks.append(chunk)

        output = "".join(chunks)
        assert "decoded" in output
        process.close_pty()


@pytest.mark.asyncio
async def test_pty_stream_include_stream(default_rootfs):
    """PTY stream(include_stream=True) should always label as 'stdout'."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "echo labelled",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        async for name, chunk in process.stream(include_stream=True):
            assert name == "stdout"
            assert isinstance(chunk, bytes)

        process.close_pty()


@pytest.mark.asyncio
async def test_pty_stream_lines(default_rootfs):
    """PTY stream_lines() should yield individual lines."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "printf 'line1\\nline2\\n'",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        lines: list[str] = []
        async for line in process.stream_lines(decode=True):
            lines.append(line)

        joined = "".join(lines)
        assert "line1" in joined
        assert "line2" in joined
        process.close_pty()


@pytest.mark.asyncio
async def test_pty_send(default_rootfs):
    """send() in PTY mode should write to the master fd."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "cat",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        assert process.master_fd is not None
        await process.send(b"hello from pty\n")

        # Read back — cat will echo via the PTY
        data = os.read(process.master_fd, 4096)
        assert b"hello from pty" in data

        process.kill()
        await process.wait()
        process.close_pty()


@pytest.mark.asyncio
async def test_pty_set_terminal_size(default_rootfs):
    """set_terminal_size() should update the PTY dimensions."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "sleep 0.1",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )

        # Should not raise
        process.set_terminal_size(50, 200)

        await process.wait()
        process.close_pty()


@pytest.mark.asyncio
async def test_pty_set_terminal_size_no_pty():
    """set_terminal_size() should raise when not in PTY mode."""
    with Sandbox() as sandbox:
        process = await sandbox.run("true")
        with pytest.raises(RuntimeError, match="PTY mode is not enabled"):
            process.set_terminal_size(24, 80)
        await process.wait()


@pytest.mark.asyncio
async def test_pty_close_idempotent(default_rootfs):
    """close_pty() should be safe to call multiple times."""
    with Sandbox(rootfs=str(default_rootfs)) as sandbox:
        process = await sandbox.run(
            "true",
            use_pty=True,
            stdin_pipe=False,
            stdout_pipe=False,
            stderr_pipe=False,
        )
        await process.wait()

        process.close_pty()
        assert process.master_fd is None
        # Second call should not raise
        process.close_pty()
        assert process.master_fd is None


@pytest.mark.asyncio
async def test_pty_master_fd_none_without_pty():
    """master_fd should be None when not in PTY mode."""
    with Sandbox() as sandbox:
        process = await sandbox.run("true")
        assert process.master_fd is None
        await process.wait()


@pytest.mark.asyncio
async def test_pty_rejects_pipes():
    """use_pty=True with stdin_pipe=True should raise ValueError."""
    with Sandbox() as sandbox:
        with pytest.raises(ValueError, match="PTY mode cannot be used"):
            await sandbox.run("true", use_pty=True, stdin_pipe=True)
