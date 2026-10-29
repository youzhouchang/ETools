"""Locate the user guide shipped with the app and the source tree."""

from __future__ import annotations

import sys
from pathlib import Path

_GUIDE_NAME = "guide.md"


def guide_candidates() -> list[Path]:
    """Search order: frozen bundle, source checkout, directory of the executable."""
    found: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        found.append(Path(meipass) / "docs" / _GUIDE_NAME)
    # etools/ui/guide_doc.py -> repository root is parents[2].
    found.append(Path(__file__).resolve().parents[2] / "docs" / _GUIDE_NAME)
    found.append(Path(sys.executable).resolve().parent / "docs" / _GUIDE_NAME)
    return found


def guide_path() -> Path:
    """Return the first guide that exists, otherwise the first candidate."""
    candidates = guide_candidates()
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_guide() -> str:
    path = guide_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")
