"""Core functionality for the pybubble package."""

from __future__ import annotations

from importlib import metadata

__all__ = ["__version__"]


try:  # pragma: no cover - exercised when installed
    __version__ = metadata.version("pybubble")
except metadata.PackageNotFoundError:  # pragma: no cover - local fallback
    __version__ = "0.0.0"
