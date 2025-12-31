from pathlib import Path
import hashlib
import os
import subprocess
import tarfile

tarball_hash_cache: dict[Path, str] = {}

def _compute_tarball_hash(tarball_path: Path) -> str:
    """Compute SHA256 hash of tarball content."""
    if tarball_path in tarball_hash_cache:
        return tarball_hash_cache[tarball_path]

    sha256 = hashlib.sha256()
    with open(tarball_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    
    tarball_hash_cache[tarball_path] = sha256.hexdigest()
    return tarball_hash_cache[tarball_path]


def _get_cache_dir() -> Path:
    """Get the cache directory for rootfs files."""
    home = os.getenv("HOME")
    if home is None:
        home = str(Path.home())
    cache_base = Path(home) / ".cache" / "pybubble" / "rootfs"
    return cache_base


def _safe_extractall(tar: tarfile.TarFile, path: Path) -> None:
    """Extract tar contents while preventing path traversal."""
    for member in tar.getmembers():
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"Unsafe path in tarball: {member.name}")
    tar.extractall(path)


def setup_rootfs(rootfs: str, rootfs_path: Path | None = None) -> Path:
    """Sets up a reusable rootfs from a specified image tarball (local file only).
    
    Args:
        rootfs: Path to rootfs tarball (local file)
        rootfs_path: Optional specific path to extract rootfs. If None, uses cache based on tarball hash.
    
    Returns:
        Path to the extracted rootfs directory.
    """
    # Local file path
    tarball_path = Path(rootfs)
    if not tarball_path.exists():
        raise FileNotFoundError(f"Rootfs tarball not found: {rootfs}")
    
    # Determine if we should use cache or specific path
    if rootfs_path is None:
        # Use cache based on tarball hash
        tarball_hash = _compute_tarball_hash(tarball_path)
        # Use hash-based cache directory
        rootfs_dir = _get_cache_dir() / tarball_hash
    else:
        # Use specific path provided by user
        rootfs_dir = Path(rootfs_path)
    
    # Check if rootfs directory already exists (cached)
    if rootfs_dir.exists():
        return rootfs_dir
    
    # Extract the tarball to the rootfs directory
    try:
        # Create rootfs directory if it doesn't exist
        rootfs_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract the tarball
        with tarfile.open(tarball_path, "r:*") as tar:
            _safe_extractall(tar, rootfs_dir)
    except Exception as e:
        raise RuntimeError(f"Failed to extract rootfs tarball: {e}") from e
    
    return rootfs_dir

def generate_rootfs(dockerfile: Path, output_file: Path, compress_level: int = 6) -> None:
    """Generates a rootfs from a Dockerfile. Docker must be installed for this to work."""
    subprocess.run(["docker", "rm", "-f", "pybubble_rootfs"], check=False)
    subprocess.run(["docker", "build", "-t", "pybubble_rootfs", "-f", dockerfile, "."], check=True)
    subprocess.run(["docker", "create", "--name", "pybubble_rootfs", "pybubble_rootfs"], check=True)
    subprocess.run(["bash", "-c", f"docker export pybubble_rootfs | gzip -{compress_level} > {output_file}"], check=True)
