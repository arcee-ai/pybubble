"""Test configuration for the pybubble package."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running tests without installing the package in editable mode.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))
