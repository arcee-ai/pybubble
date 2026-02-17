"""Pytest configuration and shared fixtures."""

from pathlib import Path
import pytest

from pybubble.rootfs import generate_rootfs
from pybubble.sandbox import _BUNDLED_ROOTFS


def ensure_default_exists() -> Path:
    """
    Return a path to a usable default rootfs tarball.

    Prefers the bundled ``data/default.tar.zst`` that ships inside the wheel.
    Falls back to ``default.tar.zst`` in the project root (building it from
    ``default-rootfs.dockerfile`` if necessary).

    When running from a source checkout, symlinks the project-root tarball
    into the ``data/`` directory so that ``Sandbox()`` (no arguments) works.
    """
    if _BUNDLED_ROOTFS.exists():
        return _BUNDLED_ROOTFS

    project_root = Path(__file__).parent.parent
    default_archive = project_root / "default.tar.zst"
    dockerfile = project_root / "default-rootfs.dockerfile"

    if not default_archive.exists():
        if not dockerfile.exists():
            raise FileNotFoundError(
                f"default-rootfs.dockerfile not found at {dockerfile}. "
                "Cannot build default.tar.zst."
            )
        generate_rootfs(dockerfile, default_archive)

    # Symlink into the data/ directory so Sandbox() finds it without args
    _BUNDLED_ROOTFS.parent.mkdir(parents=True, exist_ok=True)
    if not _BUNDLED_ROOTFS.exists():
        _BUNDLED_ROOTFS.symlink_to(default_archive.resolve())

    return _BUNDLED_ROOTFS


@pytest.fixture
def default_rootfs():
    """Fixture that ensures the default rootfs exists and returns its path."""
    return ensure_default_exists()


@pytest.fixture
def run_collect():
    """Run a sandbox command and collect stdout/stderr."""
    async def _run(sandbox, command: str, **kwargs):
        process = await sandbox.run(command, **kwargs)
        return await process.communicate()

    return _run
