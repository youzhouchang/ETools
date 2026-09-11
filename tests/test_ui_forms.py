"""Smoke tests for UI forms loading (offscreen)."""

from __future__ import annotations

import os

import pytest

# Force offscreen before Qt import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_forms_exist():
    from etools.ui.ui_loader import FORMS_DIR

    for name in ("main_window", "probe_panel", "flash_panel", "target_info_panel", "log_panel"):
        assert (FORMS_DIR / f"{name}.ui").exists(), name


def test_load_probe_panel(qapp):
    from etools.ui.widgets.probe_panel import ProbePanel

    p = ProbePanel()
    assert p.probe_combo is not None
    assert p.connect_btn is not None
    assert p.target_combo.count() > 0


def test_load_flash_panel(qapp):
    from etools.ui.widgets.flash_panel import FlashPanel

    f = FlashPanel()
    assert f.program_btn is not None
    assert f.addr_edit.text() == "0x08000000"


def test_load_target_info_panel(qapp):
    from etools.ui.widgets.target_info_panel import TargetInfoPanel

    t = TargetInfoPanel()
    t.clear()
    assert t.val_uid.text() == "—"


def test_main_window_builds(qapp):
    from etools.ui.main_window import MainWindow

    w = MainWindow()
    assert w.probe_panel is not None
    assert w.flash_panel is not None
    assert w.target_info_panel is not None
    assert w.log_panel is not None
    w.close()
