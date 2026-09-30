"""UI kit and command palette smoke tests (offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_kit_helpers(qapp):
    from etools.ui import kit

    assert kit.H_ROW == 28
    assert kit.ghost_button("x").objectName() == "ghost"
    assert kit.accent_button("y").objectName() == "accent"
    assert kit.danger_button("z").objectName() == "danger"
    combo = kit.compact_combo(width=80)
    assert combo.width() == 80 or combo.minimumWidth() == 80 or combo.maximumWidth() == 80


def test_command_palette_filters_and_runs(qapp):
    from etools.ui.widgets.command_palette import CommandPalette

    ran: list[str] = []
    cmds = [
        ("a", "烧录工具", lambda: ran.append("a")),
        ("b", "串口助手", lambda: ran.append("b")),
    ]
    pal = CommandPalette(cmds)
    pal._rebuild("串口")
    assert pal.listw.count() == 1
    pal._run_current()
    assert ran == ["b"]


def test_main_window_has_palette(qapp, monkeypatch, tmp_path):
    from etools import config as config_mod

    monkeypatch.setattr(config_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config_mod, "_config", config_mod.AppConfig())
    from etools.ui.main_window import MainWindow

    w = MainWindow()
    assert w.objectName() == "MainWindow"
    assert callable(w._open_command_palette)
    assert callable(w._install_command_palette)
    w.close()
