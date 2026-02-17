"""Custom build backend that wraps hatchling and builds the default rootfs."""
import os
import sys
from pathlib import Path
from hatchling.build import build_sdist as _build_sdist
from hatchling.build import build_wheel as _build_wheel
try:
    from hatchling.build import build_editable as _build_editable
except ImportError:
    _build_editable = None

# Import the rootfs generation function from the source
sys.path.insert(0, str(Path(__file__).parent / "src"))
from pybubble.rootfs import generate_rootfs

# Location inside the package tree where the rootfs will be bundled
_DATA_DIR = Path(__file__).parent / "src" / "pybubble" / "data"
_DEFAULT_TGZ = _DATA_DIR / "default.tgz"


def _ensure_default_rootfs() -> None:
    """Generate the default rootfs tarball into the package data directory."""
    project_root = Path(__file__).parent.absolute()
    dockerfile = project_root / "default-rootfs.dockerfile"

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    if _DEFAULT_TGZ.exists():
        print(f"Removing existing {_DEFAULT_TGZ}", flush=True)
        _DEFAULT_TGZ.unlink()

    print(f"Building default rootfs from {dockerfile}...", flush=True)

    original_cwd = os.getcwd()
    os.chdir(project_root)
    try:
        generate_rootfs(dockerfile, _DEFAULT_TGZ, compress_level=9)
        print(f"Default rootfs built successfully at {_DEFAULT_TGZ}!", flush=True)
    finally:
        os.chdir(original_cwd)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """Generate the default rootfs, then build a wheel that includes it."""
    try:
        _ensure_default_rootfs()
    except Exception as e:
        print(f"Warning: Failed to build default rootfs: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()

    return _build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    """Build an sdist. The rootfs will be built when build_wheel is called."""
    return _build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    """Build an editable wheel. Don't build rootfs for editable installs."""
    if _build_editable is None:
        raise NotImplementedError("Editable installs are not supported by this version of hatchling")
    return _build_editable(wheel_directory, config_settings, metadata_directory)


# Expose the required hooks for the build backend
__all__ = ['build_wheel', 'build_sdist', 'build_editable']
