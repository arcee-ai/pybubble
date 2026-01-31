import pytest

from pybubble import Sandbox


@pytest.mark.asyncio
async def test_process_streams_stdout_stderr(default_rootfs):
    sandbox = Sandbox(rootfs=str(default_rootfs))
    process = await sandbox.run("bash -c 'printf out; printf err 1>&2'")

    stdout_chunks = []
    stderr_chunks = []
    async for stream_name, chunk in process.stream(include_stream=True):
        if stream_name == "stdout":
            stdout_chunks.append(chunk)
        else:
            stderr_chunks.append(chunk)

    await process.wait(check=True)
    assert b"".join(stdout_chunks) == b"out"
    assert b"".join(stderr_chunks) == b"err"


@pytest.mark.asyncio
async def test_process_send_text_stdin(default_rootfs):
    sandbox = Sandbox(rootfs=str(default_rootfs))
    process = await sandbox.run("cat")

    await process.send_text("hello\n")
    process.close_stdin()

    stdout, stderr = await process.communicate()
    assert stdout == b"hello\n"
    assert stderr == b""


@pytest.mark.asyncio
async def test_process_streams_lines(default_rootfs):
    sandbox = Sandbox(rootfs=str(default_rootfs))
    process = await sandbox.run("bash -c 'printf \"line1\\nline2\\n\"'")

    lines = []
    async for line in process.stream_lines():
        lines.append(line)

    await process.wait(check=True)

    assert lines == ["line1\n", "line2\n"]
