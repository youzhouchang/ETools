"""Pytest configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable when running `pytest` from anywhere
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_ui_hardware(request, monkeypatch):
    if not {"qapp", "app"}.intersection(request.fixturenames):
        return
    from etools.core.pyocd_driver import PyOCDDriver
    from etools.ui.main_window import MainWindow

    monkeypatch.setattr(PyOCDDriver, "discover", lambda self: [])
    monkeypatch.setattr(MainWindow, "_start_scan", lambda self, silent=False: None)
    monkeypatch.setattr(MainWindow, "_schedule_startup_update_check", lambda self: None)
