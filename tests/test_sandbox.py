import pytest
from pathlib import Path
import tempfile
from pybubble import Sandbox
from conftest import ensure_default_exists


@pytest.mark.asyncio
async def test_sandbox(run_collect):
    """Basic sandbox test: Python and bash work, cleanup deletes work_dir."""
    with Sandbox() as sandbox:
        proc = await sandbox.run_script("print('Hello, world!')")
        assert await proc.communicate() == (b"Hello, world!\n", b"")
        assert await run_collect(sandbox, "echo 'hello!'") == (b"hello!\n", b"")

        work_dir_path = sandbox.work_dir

    # Context manager exit should trigger cleanup
    assert not work_dir_path.exists()


@pytest.mark.asyncio
async def test_default_rootfs():
    """Sandbox() with no rootfs argument should use the bundled default."""
    with Sandbox() as sandbox:
        process = await sandbox.run("echo works")
        stdout, _ = await process.communicate()
        assert b"works" in stdout


@pytest.mark.asyncio
async def test_explicit_rootfs(run_collect):
    """Sandbox with an explicit rootfs path should use that tarball."""
    rootfs = ensure_default_exists()
    with Sandbox(rootfs=str(rootfs)) as sandbox:
        stdout, stderr = await run_collect(sandbox, "echo explicit")
        assert b"explicit" in stdout


@pytest.mark.asyncio
async def test_work_dir_persistence(run_collect):
    """Files persist across sandbox instances when work_dir is provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "persistent_work"
        work_dir.mkdir()

        with Sandbox(work_dir=str(work_dir)) as sandbox1:
            await run_collect(sandbox1, "echo 'persistent data' > test_file.txt")
            await run_collect(sandbox1, "echo 'more data' > another_file.txt")
            work_dir1 = sandbox1.work_dir

            stdout, stderr = await run_collect(sandbox1, "cat test_file.txt")
            assert b"persistent data" in stdout

            test_file_path = work_dir1 / "test_file.txt"
            assert test_file_path.exists()
            assert test_file_path.read_text().strip() == "persistent data"

        # Work dir should persist because it was explicitly provided
        assert work_dir1.exists()
        assert test_file_path.exists()

        with Sandbox(work_dir=str(work_dir)) as sandbox2:
            stdout, _ = await run_collect(sandbox2, "cat test_file.txt")
            assert b"persistent data" in stdout

            stdout, _ = await run_collect(sandbox2, "cat another_file.txt")
            assert b"more data" in stdout


@pytest.mark.asyncio
async def test_work_dir_python_script_persistence(run_collect):
    """Python scripts and their outputs persist and are accessible from the host."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "python_work"
        work_dir.mkdir()

        with Sandbox(work_dir=str(work_dir)) as sandbox1:
            proc = await sandbox1.run_script("""
with open('data.json', 'w') as f:
    f.write('{"count": 42}')
""")
            await proc.communicate()
            stdout, _ = await run_collect(sandbox1, "cat data.json")
            assert b'{"count": 42}' in stdout

            import json
            data_file_path = sandbox1.work_dir / "data.json"
            assert data_file_path.exists()
            data_content = json.loads(data_file_path.read_text())
            assert data_content["count"] == 42

        assert data_file_path.exists()


@pytest.mark.asyncio
async def test_work_dir_host_filesystem_access(run_collect):
    """Files can be placed by the host and read inside the sandbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "host_access_work"
        work_dir.mkdir()

        with Sandbox(work_dir=str(work_dir)) as sandbox:
            await run_collect(sandbox, "echo 'sandbox content' > sandbox_file.txt")

            sandbox_file_path = sandbox.work_dir / "sandbox_file.txt"
            assert sandbox_file_path.exists()
            assert sandbox_file_path.read_text().strip() == "sandbox content"

            host_file_path = sandbox.work_dir / "host_file.txt"
            host_file_path.write_text("host content")

            stdout, _ = await run_collect(sandbox, "cat host_file.txt")
            assert b"host content" in stdout


@pytest.mark.asyncio
async def test_dev_null_writable(run_collect):
    """/dev/null should be writable and discard data."""
    with Sandbox() as sandbox:
        stdout, stderr = await run_collect(sandbox, "echo 'test data' > /dev/null")
        assert stdout == b""
        assert stderr == b""

        stdout, stderr = await run_collect(sandbox, "echo 'visible' && echo 'hidden' > /dev/null")
        assert b"visible" in stdout
        assert b"hidden" not in stdout

        proc = await sandbox.run_script("""
with open('/dev/null', 'w') as f:
    f.write('this should be discarded')
print('success')
""")
        stdout, stderr = await proc.communicate()
        assert b"success" in stdout
        assert stderr == b""


@pytest.mark.asyncio
async def test_tmp_writable(run_collect):
    """/tmp should be writable and files should persist within the same sandbox."""
    with Sandbox() as sandbox:
        stdout, stderr = await run_collect(sandbox, "echo 'test content' > /tmp/test_file.txt")
        assert stderr == b""

        stdout, stderr = await run_collect(sandbox, "cat /tmp/test_file.txt")
        assert b"test content" in stdout

        proc = await sandbox.run_script("""
with open('/tmp/python_test.txt', 'w') as f:
    f.write('python content')
""")
        await proc.communicate()
        proc = await sandbox.run_script("""
with open('/tmp/python_test.txt', 'r') as f:
    print(f.read().strip())
""")
        stdout, _ = await proc.communicate()
        assert b"python content" in stdout


@pytest.mark.asyncio
async def test_hostname_is_sandbox(run_collect):
    """The sandbox hostname should be 'sandbox', not the host hostname."""
    with Sandbox() as sandbox:
        stdout, stderr = await run_collect(sandbox, "hostname")
        assert stdout.strip() == b"sandbox"
        assert stderr == b""


@pytest.mark.asyncio
async def test_context_manager_close():
    """Exiting the context manager should call close() and be re-entrant."""
    sandbox = Sandbox()
    sandbox.__enter__()
    sandbox.__exit__(None, None, None)
    # Second close should not raise
    sandbox.close()


@pytest.mark.asyncio
async def test_sandbox_overlay(run_collect):
    """Overlay filesystem should allow writes to the rootfs."""
    pytest.importorskip("subprocess")  # always available, but guards fuse check
    from pybubble.sandbox import system_supports_overlayfs
    if not system_supports_overlayfs():
        pytest.skip("fuse-overlayfs not installed")

    with Sandbox(rootfs_overlay=True) as sandbox:
        # The overlay should let us write to system directories
        stdout, stderr = await run_collect(sandbox, "touch /opt/test_overlay_file && echo ok")
        assert b"ok" in stdout


@pytest.mark.asyncio
async def test_sandbox_overlay_persist(run_collect):
    """Persisted overlay should leave the mount intact after close()."""
    from pybubble.sandbox import system_supports_overlayfs
    if not system_supports_overlayfs():
        pytest.skip("fuse-overlayfs not installed")

    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        overlay_path = Path(tmpdir) / "overlay"
        overlay_path.mkdir()

        with Sandbox(
            rootfs_overlay=True,
            rootfs_overlay_path=str(overlay_path),
            persist_overlayfs=True,
        ) as sandbox:
            await run_collect(sandbox, "touch /opt/persisted && echo done")
            mount_dir = sandbox.rootfs_dir

        # The mount should still exist after close
        assert mount_dir.exists()
        assert (mount_dir / "opt" / "persisted").exists()

        # Manually unmount
        subprocess.run(
            ["fusermount", "-u", str(mount_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
