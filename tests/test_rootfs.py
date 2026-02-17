"""Tests for the rootfs module."""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pybubble.rootfs import generate_rootfs, setup_rootfs


@pytest.fixture
def temp_work_dir():
    """Create a temporary work directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_tarball(temp_work_dir):
    """Create a sample tarball for testing."""
    tarball_path = temp_work_dir / "test_rootfs.tar.gz"
    
    # Create temporary files to add to the tarball
    test_file = temp_work_dir / "temp_test_file.txt"
    test_file.write_text("test content")
    
    etc_dir = temp_work_dir / "temp_etc"
    etc_dir.mkdir()
    hostname_file = etc_dir / "hostname"
    hostname_file.write_text("test-hostname")
    
    # Create a tarball with test files
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(test_file, arcname="test_file.txt")
        tar.add(hostname_file, arcname="etc/hostname")
    
    # Clean up temporary files
    test_file.unlink()
    hostname_file.unlink()
    etc_dir.rmdir()
    
    return tarball_path


def test_setup_rootfs_local_file(temp_work_dir, sample_tarball):
    """Test setup_rootfs with a local file path and specific rootfs_path."""
    rootfs_dir = temp_work_dir / "rootfs"
    result_dir = setup_rootfs(str(sample_tarball), rootfs_dir)
    
    # Verify rootfs directory was created
    assert result_dir.exists()
    assert result_dir.is_dir()
    assert result_dir == rootfs_dir
    
    # Verify files were extracted
    assert (result_dir / "test_file.txt").exists()
    assert (result_dir / "etc" / "hostname").exists()
    
    # Verify file contents
    assert (result_dir / "test_file.txt").read_text() == "test content"
    assert (result_dir / "etc" / "hostname").read_text() == "test-hostname"


def test_setup_rootfs_local_file_not_found(temp_work_dir):
    """Test setup_rootfs raises FileNotFoundError for non-existent local file."""
    non_existent_path = temp_work_dir / "nonexistent.tar.gz"
    rootfs_dir = temp_work_dir / "rootfs"
    
    with pytest.raises(FileNotFoundError, match="Rootfs tarball not found"):
        setup_rootfs(str(non_existent_path), rootfs_dir)


def test_setup_rootfs_extraction_failure(temp_work_dir):
    """Test setup_rootfs raises RuntimeError when extraction fails."""
    # Create an invalid tarball (just a text file)
    invalid_tarball = temp_work_dir / "invalid.tar.gz"
    invalid_tarball.write_text("not a tarball")
    rootfs_dir = temp_work_dir / "rootfs"
    
    with pytest.raises(RuntimeError, match="Failed to extract rootfs tarball"):
        setup_rootfs(str(invalid_tarball), rootfs_dir)


def test_setup_rootfs_creates_parent_directories(temp_work_dir, sample_tarball):
    """Test that setup_rootfs creates parent directories if they don't exist."""
    nested_rootfs_dir = temp_work_dir / "nested" / "deep" / "path" / "rootfs"
    
    result_dir = setup_rootfs(str(sample_tarball), nested_rootfs_dir)
    
    # Verify nested directories were created
    assert nested_rootfs_dir.exists()
    assert result_dir.exists()
    assert result_dir == nested_rootfs_dir


def test_setup_rootfs_returns_correct_path(temp_work_dir, sample_tarball):
    """Test that setup_rootfs returns the correct path."""
    rootfs_dir = temp_work_dir / "rootfs"
    result_dir = setup_rootfs(str(sample_tarball), rootfs_dir)
    
    assert result_dir == rootfs_dir
    assert result_dir.is_absolute() == rootfs_dir.is_absolute()


def test_setup_rootfs_early_return_if_exists(temp_work_dir, sample_tarball):
    """Test that setup_rootfs returns early if rootfs_dir already exists."""
    rootfs_dir = temp_work_dir / "rootfs"
    
    # First call - should extract the tarball
    result_dir1 = setup_rootfs(str(sample_tarball), rootfs_dir)
    assert result_dir1 == rootfs_dir
    assert (result_dir1 / "test_file.txt").exists()
    
    # Remove a file to verify second call doesn't re-extract
    (result_dir1 / "test_file.txt").unlink()
    
    # Second call - should return early without re-extracting
    result_dir2 = setup_rootfs(str(sample_tarball), rootfs_dir)
    assert result_dir2 == rootfs_dir
    # File should still be missing since extraction didn't happen again
    assert not (result_dir2 / "test_file.txt").exists()


def test_setup_rootfs_caching_without_rootfs_path(temp_work_dir, sample_tarball):
    """Test that setup_rootfs caches based on tarball hash when rootfs_path is None."""
    with patch("pybubble.rootfs._get_cache_dir") as mock_cache_dir:
        cache_base = temp_work_dir / "cache"
        mock_cache_dir.return_value = cache_base
        
        # First call - should extract and cache
        result_dir1 = setup_rootfs(str(sample_tarball), None)
        
        # Verify cache directory was created
        assert result_dir1.exists()
        assert result_dir1.is_dir()
        assert result_dir1.parent == cache_base
        assert (result_dir1 / "test_file.txt").exists()
        
        # Remove a file to verify second call uses cache
        (result_dir1 / "test_file.txt").unlink()
        
        # Second call - should use cached version
        result_dir2 = setup_rootfs(str(sample_tarball), None)
        
        # Should return same directory
        assert result_dir2 == result_dir1
        # File should still be missing since it used cached directory
        assert not (result_dir2 / "test_file.txt").exists()


def test_setup_rootfs_different_tarballs_different_cache(temp_work_dir, sample_tarball):
    """Test that different tarballs use different cache directories."""
    with patch("pybubble.rootfs._get_cache_dir") as mock_cache_dir:
        cache_base = temp_work_dir / "cache"
        mock_cache_dir.return_value = cache_base
        
        # Create a different tarball with different content
        different_tarball = temp_work_dir / "different.tar.gz"
        different_file = temp_work_dir / "different_file.txt"
        different_file.write_text("different content")
        
        with tarfile.open(different_tarball, "w:gz") as tar:
            tar.add(different_file, arcname="different_file.txt")
        
        different_file.unlink()
        
        # Setup both tarballs
        result_dir1 = setup_rootfs(str(sample_tarball), None)
        result_dir2 = setup_rootfs(str(different_tarball), None)
        
        # Should be different cache directories
        assert result_dir1 != result_dir2
        assert result_dir1.parent == cache_base
        assert result_dir2.parent == cache_base
        
        # Verify each has correct content
        assert (result_dir1 / "test_file.txt").exists()
        assert (result_dir2 / "different_file.txt").exists()


def test_setup_rootfs_specific_path_bypasses_cache(temp_work_dir, sample_tarball):
    """Test that providing a specific rootfs_path bypasses caching."""
    with patch("pybubble.rootfs._get_cache_dir") as mock_cache_dir:
        cache_base = temp_work_dir / "cache"
        mock_cache_dir.return_value = cache_base
        
        # Call with None to create cache
        cached_dir = setup_rootfs(str(sample_tarball), None)
        assert cached_dir.exists()
        assert cached_dir.parent == cache_base
        
        # Call with specific path - should bypass cache
        specific_dir = temp_work_dir / "specific_rootfs"
        result_dir = setup_rootfs(str(sample_tarball), specific_dir)
        
        # Should use specific directory, not cache
        assert result_dir == specific_dir
        assert result_dir != cached_dir
        assert (result_dir / "test_file.txt").exists()


def test_generate_rootfs():
    """Test that generate_rootfs creates a rootfs from a Dockerfile."""
    dockerfile = Path("tests/test_dockerfile.dockerfile")
    output_file = Path("tests/test_rootfs.tar.zst")
    generate_rootfs(dockerfile, output_file)
    
    assert output_file.exists()
    assert output_file.is_file()
    
    os.remove(output_file)