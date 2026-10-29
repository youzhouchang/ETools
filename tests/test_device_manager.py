"""Device manager pack install and list stay off the GUI thread."""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _wait_until(qapp, predicate, seconds: float = 3) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_pack_install_runs_off_the_gui_thread(qapp, monkeypatch) -> None:
    from etools.i18n import tr
    from etools.ui.widgets import device_manager as dm

    gui = threading.get_ident()
    started = threading.Event()
    release = threading.Event()
    seen: dict[str, int] = {}

    def slow_install(pack_id: str) -> tuple[bool, str]:
        seen["thread"] = threading.get_ident()
        started.set()
        release.wait(2)
        return True, f"done {pack_id}"

    monkeypatch.setattr(dm, "install_pack", slow_install)
    panel = dm.DeviceManagerPanel()
    panel.pack_edit.setText("Vendor::Part")
    panel._on_install_pack()

    assert panel.install_pack_btn.isEnabled() is False
    assert started.wait(2)
    assert seen["thread"] != gui
    qapp.processEvents()
    assert tr("devices.pack_installing", pack="Vendor::Part") in panel.hint.text()

    release.set()
    assert _wait_until(qapp, lambda: panel.install_pack_btn.isEnabled())
    assert tr("devices.pack_ok", msg="done Vendor::Part") in panel.hint.text()
    panel.shutdown()
    panel.close()


def test_pack_list_runs_off_the_gui_thread(qapp, monkeypatch) -> None:
    from etools.i18n import tr
    from etools.ui.widgets import device_manager as dm

    gui = threading.get_ident()
    seen: dict[str, int] = {}

    def slow_list() -> list[str]:
        seen["thread"] = threading.get_ident()
        return ["Keil.STM32F1xx_DFP.2.4.0"]

    monkeypatch.setattr(dm, "list_installed_packs", slow_list)
    panel = dm.DeviceManagerPanel()
    panel._on_list_packs()
    assert _wait_until(qapp, lambda: panel.install_pack_btn.isEnabled())
    assert seen["thread"] != gui
    assert panel.device_tree.topLevelItemCount() == 1
    assert "STM32F1" in panel.device_tree.topLevelItem(0).text(1)
    assert tr("devices.pack_count", n=1) in panel.hint.text()
    panel.shutdown()
    panel.close()


def test_shutdown_drops_a_pack_result_after_close(qapp, monkeypatch) -> None:
    from etools.ui.widgets import device_manager as dm

    release = threading.Event()

    def slow_install(_pack_id: str) -> tuple[bool, str]:
        assert release.wait(2)
        return False, "late"

    monkeypatch.setattr(dm, "install_pack", slow_install)
    panel = dm.DeviceManagerPanel()
    panel.pack_edit.setText("Vendor::Part")
    panel._on_install_pack()
    panel.shutdown()
    panel.close()
    release.set()
    assert _wait_until(qapp, lambda: not dm._LIVE_JOBS)
