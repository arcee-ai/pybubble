import pytest
from pathlib import Path
import tempfile
from pybubble import Sandbox
from conftest import ensure_default_exists

@pytest.mark.asyncio
async def test_sandbox(run_collect):
    default_rootfs = ensure_default_exists()
    sandbox = Sandbox(rootfs=str(default_rootfs))
    
    # Test Python and bash functionality
    assert await sandbox.run_python("print('Hello, world!')") == (b"Hello, world!\n", b"")
    assert await run_collect(sandbox, "echo 'hello!'") == (b"hello!\n", b"")
    
    # Test network access
    assert (await run_collect(sandbox, "ping -c 1 google.com", allow_network=True))[1] == b""
    
    # Test cleanup
    work_dir_path = sandbox.work_dir
    del sandbox
    
    # Check that the temporary directory was deleted
    assert not work_dir_path.exists()


@pytest.mark.asyncio
async def test_work_dir_persistence(run_collect):
    """Test that files persist across sandbox instances when work_dir is provided."""
    default_rootfs = ensure_default_exists()
    
    # Create a temporary work directory
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "persistent_work"
        work_dir.mkdir()
        
        # First sandbox: write a file
        sandbox1 = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        await run_collect(sandbox1, "echo 'persistent data' > test_file.txt")
        await run_collect(sandbox1, "echo 'more data' > another_file.txt")
        work_dir1 = sandbox1.work_dir
        
        # Verify files exist in the first sandbox
        stdout, stderr = await run_collect(sandbox1, "cat test_file.txt")
        assert b"persistent data" in stdout, f"Expected 'persistent data' in stdout, got {stdout} with stderr {stderr}"
        
        # Verify files exist on host filesystem directly in work_dir
        test_file_path = work_dir1 / "test_file.txt"
        assert test_file_path.exists()
        assert test_file_path.read_text().strip() == "persistent data"
        
        # Delete the first sandbox
        del sandbox1
        
        # Verify work directory still exists (persistence)
        assert work_dir1.exists()
        assert test_file_path.exists()
        
        # Verify files are still accessible from host filesystem
        assert test_file_path.read_text().strip() == "persistent data"
        another_file_path = work_dir1 / "another_file.txt"
        assert another_file_path.exists()
        assert another_file_path.read_text().strip() == "more data"
        
        # Create a second sandbox with the same work_dir
        sandbox2 = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        
        # Verify second sandbox can read files written by first sandbox
        stdout, stderr = await run_collect(sandbox2, "cat test_file.txt")
        assert b"persistent data" in stdout
        
        stdout, stderr = await run_collect(sandbox2, "cat another_file.txt")
        assert b"more data" in stdout
        
        # Second sandbox writes additional data
        await run_collect(sandbox2, "echo 'from sandbox2' >> test_file.txt")
        
        del sandbox2
        
        # Verify all data persists
        content = test_file_path.read_text()
        assert "persistent data" in content
        assert "from sandbox2" in content
        
        # Verify work_dir persists
        assert work_dir.exists()
        assert work_dir.is_dir()


@pytest.mark.asyncio
async def test_work_dir_python_script_persistence(run_collect):
    """Test that Python scripts and their outputs persist and are accessible from host filesystem."""
    default_rootfs = ensure_default_exists()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "python_work"
        work_dir.mkdir()
        
        # First sandbox: create a Python script and run it
        sandbox1 = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        await sandbox1.run_python("""
with open('data.json', 'w') as f:
    f.write('{"count": 42}')
""")
        
        # Verify the file was created in sandbox
        stdout, _ = await run_collect(sandbox1, "cat data.json")
        assert b'{"count": 42}' in stdout
        
        # Verify the file exists on host filesystem directly in work_dir
        work_dir1 = sandbox1.work_dir
        data_file_path = work_dir1 / "data.json"
        assert data_file_path.exists()
        
        # Verify file content from host filesystem
        import json
        data_content = json.loads(data_file_path.read_text())
        assert data_content["count"] == 42
        
        del sandbox1
        
        # Verify file persists after sandbox deletion
        assert data_file_path.exists()
        data_content = json.loads(data_file_path.read_text())
        assert data_content["count"] == 42
        
        # Verify work directory persists
        assert work_dir1.exists()
        assert work_dir.exists()


@pytest.mark.asyncio
async def test_work_dir_multiple_sandboxes_same_work_dir(run_collect):
    """Test that multiple sandboxes can share the same work_dir and see each other's files."""
    default_rootfs = ensure_default_exists()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "shared_work"
        work_dir.mkdir()
        
        # Create two sandboxes simultaneously with the same work_dir
        sandbox1 = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        sandbox2 = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        
        # First sandbox writes a file
        await run_collect(sandbox1, "echo 'from sandbox1' > shared_file.txt")
        
        # Second sandbox can read the file written by first sandbox
        stdout2, _ = await run_collect(sandbox2, "cat shared_file.txt")
        assert b"from sandbox1" in stdout2
        
        # Second sandbox writes to the same file
        await run_collect(sandbox2, "echo 'from sandbox2' >> shared_file.txt")
        
        # First sandbox can read the updated file
        stdout1, _ = await run_collect(sandbox1, "cat shared_file.txt")
        assert b"from sandbox1" in stdout1
        assert b"from sandbox2" in stdout1
        
        # Verify work directories are the same
        work_dir1 = sandbox1.work_dir
        work_dir2 = sandbox2.work_dir
        assert work_dir1 == work_dir2 == work_dir
        
        # Verify file exists on host filesystem
        shared_file_path = work_dir / "shared_file.txt"
        assert shared_file_path.exists()
        
        del sandbox1
        del sandbox2
        
        # Verify work directory and files persist
        assert work_dir.exists()
        assert shared_file_path.exists()
        content = shared_file_path.read_text()
        assert "from sandbox1" in content
        assert "from sandbox2" in content


@pytest.mark.asyncio
async def test_work_dir_host_filesystem_access(run_collect):
    """Test that files can be accessed from host filesystem and persist after sandbox deletion."""
    default_rootfs = ensure_default_exists()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir) / "host_access_work"
        work_dir.mkdir()
        
        sandbox = Sandbox(work_dir=str(work_dir), rootfs=str(default_rootfs))
        work_dir_path = sandbox.work_dir
        
        # Write a file from within the sandbox
        await run_collect(sandbox, "echo 'sandbox content' > sandbox_file.txt")
        
        # Verify file exists on host filesystem directly in work_dir
        sandbox_file_path = work_dir_path / "sandbox_file.txt"
        assert sandbox_file_path.exists()
        assert sandbox_file_path.read_text().strip() == "sandbox content"
        
        # Write a file from host filesystem to work_dir
        host_file_path = work_dir_path / "host_file.txt"
        host_file_path.write_text("host content")
        
        # Verify sandbox can read the file written from host
        stdout, _ = await run_collect(sandbox, "cat host_file.txt")
        assert b"host content" in stdout
        
        # Delete sandbox
        del sandbox
        
        # Verify both files persist after sandbox deletion
        assert sandbox_file_path.exists()
        assert host_file_path.exists()
        assert sandbox_file_path.read_text().strip() == "sandbox content"
        assert host_file_path.read_text().strip() == "host content"
        
        # Verify work directory persists
        assert work_dir_path.exists()
        assert work_dir.exists()


@pytest.mark.asyncio
async def test_dev_null_writable(run_collect):
    """Test that /dev/null is writable and discards data."""
    default_rootfs = ensure_default_exists()
    sandbox = Sandbox(rootfs=str(default_rootfs))
    
    # Test writing to /dev/null - should succeed without error
    stdout, stderr = await run_collect(sandbox, "echo 'test data' > /dev/null")
    assert stdout == b""
    assert stderr == b""
    
    # Test redirecting stdout to /dev/null
    stdout, stderr = await run_collect(sandbox, "echo 'visible' && echo 'hidden' > /dev/null")
    assert b"visible" in stdout
    assert b"hidden" not in stdout
    
    # Test Python writing to /dev/null
    stdout, stderr = await sandbox.run_python("""
with open('/dev/null', 'w') as f:
    f.write('this should be discarded')
print('success')
""")
    assert b"success" in stdout
    assert stderr == b""


@pytest.mark.asyncio
async def test_tmp_writable(run_collect):
    """Test that /tmp is writable and files persist within the same sandbox session."""
    default_rootfs = ensure_default_exists()
    sandbox = Sandbox(rootfs=str(default_rootfs))
    
    # Test writing to /tmp
    stdout, stderr = await run_collect(sandbox, "echo 'test content' > /tmp/test_file.txt")
    assert stdout == b""
    assert stderr == b""
    
    # Test reading from /tmp
    stdout, stderr = await run_collect(sandbox, "cat /tmp/test_file.txt")
    assert b"test content" in stdout, f"Expected 'test content' in stdout, got {stdout} with stderr {stderr}"
    assert stderr == b""
    
    # Test Python writing to /tmp
    stdout, stderr = await sandbox.run_python("""
with open('/tmp/python_test.txt', 'w') as f:
    f.write('python content')
""")
    assert stdout == b""
    assert stderr == b""
    
    # Test Python reading from /tmp
    stdout, stderr = await sandbox.run_python("""
with open('/tmp/python_test.txt', 'r') as f:
    content = f.read()
    print(content.strip())
""")
    assert b"python content" in stdout
    assert stderr == b""
    
    # Test multiple files in /tmp
    stdout, stderr = await run_collect(sandbox, "echo 'file1' > /tmp/file1.txt && echo 'file2' > /tmp/file2.txt")
    assert stdout == b""
    assert stderr == b""
    
    stdout, stderr = await run_collect(sandbox, "cat /tmp/file1.txt /tmp/file2.txt")
    assert b"file1" in stdout
    assert b"file2" in stdout
