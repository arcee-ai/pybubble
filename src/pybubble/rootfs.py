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
    """Extract tar contents while preventing path traversal.

    Works in a single pass so it is compatible with streaming tarfiles
    (e.g. ``tarfile.open(fileobj=..., mode="r|")``) where you cannot
    seek back after reading members.
    """
    for member in tar:
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise RuntimeError(f"Unsafe path in tarball: {member.name}")
        tar.extract(member, path, filter="fully_trusted")


def _open_tarball(tarball_path: Path) -> tarfile.TarFile:
    """Open a tarball, transparently handling gzip, xz, bzip2, and zstd."""
    name = tarball_path.name
    if name.endswith(".tar.zst") or name.endswith(".zst"):
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        fh = open(tarball_path, "rb")
        stream = dctx.stream_reader(fh)
        return tarfile.open(fileobj=stream, mode="r|")
    return tarfile.open(tarball_path, "r:*")


def setup_rootfs(rootfs: str, rootfs_path: Path | None = None) -> Path:
    """Sets up a reusable rootfs from a specified image tarball (local file only).
    
    Args:
        rootfs: Path to rootfs tarball (local file). Supports .tar.zst, .tgz,
            .tar.gz, .tar.bz2, and .tar.xz.
        rootfs_path: Optional specific path to extract rootfs. If None, uses cache based on tarball hash.
    
    Returns:
        Path to the extracted rootfs directory.
    """
    tarball_path = Path(rootfs)
    if not tarball_path.exists():
        raise FileNotFoundError(f"Rootfs tarball not found: {rootfs}")
    
    if rootfs_path is None:
        tarball_hash = _compute_tarball_hash(tarball_path)
        rootfs_dir = _get_cache_dir() / tarball_hash
    else:
        rootfs_dir = Path(rootfs_path)
    
    if rootfs_dir.exists():
        return rootfs_dir
    
    try:
        rootfs_dir.mkdir(parents=True, exist_ok=True)
        with _open_tarball(tarball_path) as tar:
            _safe_extractall(tar, rootfs_dir)
    except Exception as e:
        raise RuntimeError(f"Failed to extract rootfs tarball: {e}") from e
    
    return rootfs_dir


def generate_rootfs(dockerfile: Path, output_file: Path, compress_level: int = 19) -> None:
    """Generates a rootfs from a Dockerfile. Docker must be installed for this to work.

    The output is a zstd-compressed tarball (.tar.zst).
    """
    subprocess.run(["docker", "rm", "-f", "pybubble_rootfs"], check=False)
    subprocess.run(["docker", "build", "-t", "pybubble_rootfs", "-f", dockerfile, "."], check=True)
    subprocess.run(["docker", "create", "--name", "pybubble_rootfs", "pybubble_rootfs"], check=True)
    subprocess.run(
        ["bash", "-c", f"docker export pybubble_rootfs | zstd -{compress_level} -o {output_file}"],
        check=True,
    )
