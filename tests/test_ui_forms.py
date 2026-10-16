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


def test_hex_read_button_fits_longest_action(qapp):
    from etools.ui.widgets.hex_preview import HexPreviewPanel

    panel = HexPreviewPanel()
    metrics = panel.read_btn.fontMetrics()
    longest = max(metrics.horizontalAdvance(action.text()) for action in panel._menu_actions)
    assert panel.read_btn.minimumWidth() >= longest + 72
    menu = panel.read_btn.menu()
    assert menu is not None
    assert menu.minimumWidth() >= longest + 72
    panel.close()


def test_load_flash_panel(qapp):
    from etools.ui.widgets.flash_panel import FlashPanel

    f = FlashPanel()
    assert f.program_btn is not None
    assert f.addr_edit.value() == 0x08000000


def test_hex_firmware_tab_opens_once(qapp, tmp_path):
    from etools.ui.widgets.hex_preview import HexPreviewPanel

    panel = HexPreviewPanel()
    path = tmp_path / "boot.hex"
    path.write_text(":00000001FF\n", encoding="ascii")
    assert panel.load_file(path)
    assert panel.load_file(str(path))
    titles = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert titles.count("boot.hex") == 1
    assert panel.current_firmware_path() == str(path.resolve())
    panel.tabs.setCurrentWidget(panel.mem_view)
    assert panel.current_firmware_path() == ""
    panel.close()


def test_load_target_info_panel(qapp):
    from PySide6.QtWidgets import QLabel

    from etools.ui.widgets.target_info_panel import TargetInfoPanel

    t = TargetInfoPanel()
    t.clear()
    assert t.val_uid.text() == "—"
    # STM32 does not expose a reliable Device ID or RAM-size register.
    assert t._form.findChild(QLabel, "valDevId") is None
    assert t._form.findChild(QLabel, "valRam") is None


def test_main_window_builds(qapp):
    from etools.ui.main_window import MainWindow
    from etools.ui.shell import ToolShell

    w = MainWindow()
    assert w.probe_panel is not None
    assert w.flash_panel is not None
    assert w.target_info_panel is not None
    assert w.log_panel is not None
    assert isinstance(w.shell, ToolShell)
    assert w.program_page is not None
    w.close()
