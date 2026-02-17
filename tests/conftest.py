"""Pytest configuration and shared fixtures."""

from pathlib import Path
import pytest

from pybubble.rootfs import generate_rootfs
from pybubble.sandbox import _BUNDLED_ROOTFS


def ensure_default_exists() -> Path:
    """
    Return a path to a usable default rootfs tarball.

    Prefers the bundled ``data/default.tgz`` that ships inside the wheel.
    Falls back to ``default.tgz`` in the project root (building it from
    ``default-rootfs.dockerfile`` if necessary).
    """
    if _BUNDLED_ROOTFS.exists():
        return _BUNDLED_ROOTFS

    project_root = Path(__file__).parent.parent
    default_tgz = project_root / "default.tgz"
    dockerfile = project_root / "default-rootfs.dockerfile"

    if not default_tgz.exists():
        if not dockerfile.exists():
            raise FileNotFoundError(
                f"default-rootfs.dockerfile not found at {dockerfile}. "
                "Cannot build default.tgz."
            )
        generate_rootfs(dockerfile, default_tgz)

    return default_tgz


@pytest.fixture
def default_rootfs():
    """Fixture that ensures default.tgz exists and returns its path."""
    return ensure_default_exists()


@pytest.fixture
def run_collect():
    """Run a sandbox command and collect stdout/stderr."""
    async def _run(sandbox, command: str, **kwargs):
        process = await sandbox.run(command, **kwargs)
        return await process.communicate()

    return _run
