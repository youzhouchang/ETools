"""Regression coverage for task acceptance, capture retention and guided workflows."""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    from etools import config

    monkeypatch.setattr(config, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "_config", config.AppConfig(auto_probe_scan=False))
    return QApplication.instance() or QApplication([])


def test_paused_capture_retains_data_and_timestamp(app):
    from etools.ui.widgets.traffic_view import TS_FULL, TrafficView

    view = TrafficView()
    view.append_rx(b"before")
    view._flush()
    view.pause_check.setChecked(True)
    view.append_rx(b"during")
    assert len(view._records) == 2
    assert "during" not in view.to_plain_text()
    view.append_status("note-while-paused")
    view._flush()
    assert "note-while-paused" in view.to_plain_text()
    view.pause_check.setChecked(False)
    assert "during" in view.to_plain_text()
    original_stamp = view._records[0][3]
    view.ts_combo.setCurrentIndex(view.ts_combo.findData(TS_FULL))
    assert original_stamp[:10] in view.to_plain_text()
    view.close()


def test_capture_buffer_bounded_with_continuous_merging(app, monkeypatch):
    from etools.ui.widgets import traffic_view as module

    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 32)
    monkeypatch.setattr(module, "MAX_BUFFER_BYTES", 128)
    view = module.TrafficView()
    view.set_merge_ms(5000)
    for _ in range(100):
        view.append_rx(b"x" * 24)
    assert sum(len(record[1]) for record in view._records) <= 128
    assert all(len(record[1]) <= 32 for record in view._records)
    assert view.stats()[0] == 2400
    view.close()


def test_capture_roundtrip_and_invalid_direction(tmp_path):
    from etools.core.capture import CaptureRecord, load_capture, save_capture

    records = [CaptureRecord("2026-09-30T10:00:00.123456", "rx", "COM3", "00ff")]
    path = tmp_path / "capture.json"
    save_capture(path, records)
    assert load_capture(path) == records
    save_capture(path, [CaptureRecord(records[0].timestamp, "invalid", "", "00")])
    with pytest.raises(ValueError):
        load_capture(path)


def test_batch_locks_queue_and_stops_after_current_item(app):
    from etools.ui.widgets.batch_program_dialog import BatchProgramDialog

    pending = []
    dialog = BatchProgramDialog(lambda path, ok, fail: pending.append((path, ok, fail)))
    dialog._queue = ["a.elf", "b.elf"]
    dialog.listw.addItems(dialog._queue)
    dialog._start()
    dialog._refresh()
    assert not dialog.start_btn.isEnabled()
    assert not dialog.add_btn.isEnabled()
    dialog._remove()
    dialog._start()
    assert len(pending) == 1 and len(dialog._queue) == 2
    dialog._stop()
    pending[0][1]()
    assert len(pending) == 1 and not dialog._running
    assert dialog.start_btn.isEnabled()


def test_terminal_busy_preserves_command(app):
    from etools.ui.tools.terminal_page import TerminalPage

    page = TerminalPage()
    page._opened = True
    real_runner = page._runner
    page._runner = SimpleNamespace(busy=True)
    page.cmd.setText("echo second")
    page._on_exec()
    assert page.cmd.text() == "echo second"
    page._runner = real_runner
    page._opened = False
    page.shutdown()


def test_script_cancel_switch_preserves_draft_and_restore(app, monkeypatch):
    from etools.core import script_store
    from etools.ui.tools.script_page import ScriptPage

    script_store.save_script("first", "-- first")
    script_store.save_script("second", "-- second")
    page = ScriptPage()
    page.file_combo.setCurrentIndex(page.file_combo.findData("first"))
    page.editor.insertPlainText("draft")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    page.file_combo.setCurrentIndex(page.file_combo.findData("second"))
    assert page._current_name == "first"
    assert "draft" in page.editor.toPlainText()
    assert page.file_combo.currentData() == "first"
    script_store.delete_script("second")
    assert "second" not in script_store.list_scripts()
    assert script_store.restore_last_script().stem == "second"
    page.shutdown()


def test_script_save_on_switch_selects_destination(app, monkeypatch):
    from etools.core import script_store
    from etools.ui.tools.script_page import ScriptPage

    script_store.save_script("first", "-- first")
    script_store.save_script("second", "-- second")
    page = ScriptPage()
    page.file_combo.setCurrentIndex(page.file_combo.findData("first"))
    page.editor.insertPlainText("draft")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Save)
    page.file_combo.setCurrentIndex(page.file_combo.findData("second"))
    assert "draft" in script_store.load_script("first")
    assert page._current_name == "second"
    assert page.file_combo.currentData() == "second"
    assert page.editor.toPlainText() == "-- second"
    page.shutdown()


def test_runner_shutdown_retains_unfinished_thread(app):
    from etools.ui.runtime import OpRunner

    deleted = []
    runner = OpRunner()
    thread = SimpleNamespace(
        isRunning=lambda: True,
        quit=lambda: None,
        wait=lambda ms: False,
        deleteLater=lambda: deleted.append("thread"),
    )
    worker = SimpleNamespace(
        cancel_event=threading.Event(), deleteLater=lambda: deleted.append("worker")
    )
    runner._thread, runner._worker = thread, worker
    assert runner.shutdown() is False
    assert runner._thread is thread and runner._worker is worker
    assert worker.cancel_event.is_set() and not deleted
    runner._thread = runner._worker = None


def test_project_roundtrip_sanitizes_credentials(app, tmp_path):
    from etools.config import get_config
    from etools.core import project_profiles as profiles

    cfg = get_config()
    cfg.extra["tools"] = {"serial": {"baud": "921600"}, "terminal": {"password": "secret"}}
    cfg.default_target = "stm32f103rc"
    profiles.save_profile("board")
    profiles.save_profile("copy", profiles.profiles()["board"])
    path = tmp_path / "project.json"
    profiles.export_profile(path, profiles.profiles()["board"])
    assert "secret" not in path.read_text()
    cfg.default_target = "other"
    profiles.apply_profile(profiles.import_profile(path))
    assert cfg.default_target == "stm32f103rc"
    assert cfg.extra["tools"]["serial"]["baud"] == "921600"
    assert "copy" in profiles.profiles()


def test_send_preview_matches_checksum_and_ending(app):
    from etools.ui.tools.serial_page import SerialPage

    page = SerialPage()
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("hex"))
    page.checksum.setCurrentIndex(page.checksum.findData("crc16_modbus"))
    page.ending.setCurrentIndex(page.ending.findData("crlf"))
    page.send_edit.setText("01 03 00 00 00 01")
    expected = page._encode_payload(page.send_edit.text())
    assert str(len(expected)) in page.send_preview.text()
    assert expected.hex(" ").upper() == page.send_edit.toolTip()
    page.shutdown()


def test_tcp_connect_does_not_block_gui_and_cancel_closes(app, monkeypatch):
    from PySide6.QtTest import QTest

    from etools.ui.tools.ethernet_page import EthernetPage

    page = EthernetPage()
    started, release = threading.Event(), threading.Event()
    closed = []

    def connect(host, port):
        started.set()
        release.wait(2)

    monkeypatch.setattr(page._link, "connect_tcp_client", connect)
    monkeypatch.setattr(page._link, "close", lambda: closed.append(True))
    page._on_toggle()
    assert started.wait(1)
    assert page._runner.busy
    page._on_toggle()
    release.set()
    for _ in range(100):
        app.processEvents()
        if not page._runner.busy:
            break
        QTest.qWait(10)
    assert not page._opened and closed
    page.shutdown()


@pytest.mark.parametrize("outcome", ["success", "timeout", "program_fail", "stop", "early"])
def test_workflow_success_split_response_and_stop(app, tmp_path, outcome):
    from etools.ui.widgets.workflow_dialog import WorkflowDialog

    class Relay(QObject):
        received = Signal(bytes)

    window = QWidget()
    path = tmp_path / "firmware.elf"
    path.write_bytes(b"test")
    pending = []
    window.runner = SimpleNamespace(
        busy=False, start=lambda fn, ok, fail: pending.append((fn, ok)) or True
    )
    result = SimpleNamespace(ok=True, message="OK")
    window.service = SimpleNamespace(
        connected=True, program_file=lambda *a, **k: result, reset_target=lambda: result
    )
    window.serial_page = SimpleNamespace(
        is_open=True,
        _relay=Relay(),
        _encoding_name=lambda: "utf-8",
        _send_payload=lambda text: True,
    )
    window.script_page = SimpleNamespace(svc=SimpleNamespace(running=False))
    window.flash_panel = SimpleNamespace(firmware_path=lambda: str(path))
    window.set_busy = lambda value: None
    dialog = WorkflowDialog(window)
    dialog.command.setText("AT")
    if outcome == "early":
        dialog.command.clear()
    dialog._run()
    if outcome == "program_fail":
        pending[0][1](SimpleNamespace(ok=False, message="program failed"))
        assert not dialog.running and not dialog.report[-1]["ok"]
        assert len(pending) == 1
        return
    if outcome == "stop":
        dialog.stopping = True
        pending[0][1](pending[0][0]())
        assert not dialog.running and len(pending) == 1
        assert not dialog.report[-1]["ok"]
        return
    pending[0][1](pending[0][0]())
    if outcome == "early":
        window.serial_page._relay.received.emit(b"OK")
    pending[1][1](pending[1][0]())
    if outcome == "early":
        assert not dialog.running and dialog.report[-1]["ok"]
        return
    if outcome == "timeout":
        dialog._timed_out()
        assert not dialog.running and not dialog.report[-1]["ok"]
        assert not dialog.report[-2]["ok"]
        return
    window.serial_page._relay.received.emit(b"O")
    assert dialog.running
    window.serial_page._relay.received.emit(b"K")
    assert not dialog.running and dialog.report[-1]["ok"]
    assert not window.workflow_active


def test_project_rejects_invalid_profile_before_mutating(app):
    from etools.config import get_config
    from etools.core import project_profiles as profiles

    cfg = get_config()
    cfg.default_target = "original"
    payload = profiles.snapshot()
    payload["target"] = "replacement"
    payload["program"]["frequency_khz"] = "bad"
    with pytest.raises(ValueError):
        profiles.apply_profile(payload)
    assert cfg.default_target == "original"


def test_main_window_and_new_dialogs_smoke(app, monkeypatch):
    from etools.ui.main_window import MainWindow
    from etools.ui.widgets.project_dialog import ProjectDialog
    from etools.ui.widgets.workflow_dialog import WorkflowDialog

    monkeypatch.setattr(MainWindow, "_schedule_startup_update_check", lambda self: None)
    window = MainWindow()
    window.show()
    window.shell.set_labels_visible(True)
    window.shell.set_current_tool("serial")
    window.shell.refresh_action_states()
    actions = dict((spec.key, action) for spec, action in window.shell._actions["serial"])
    assert not actions["send"].isEnabled()
    assert window.shell.tool_buttons["serial"].text()
    ProjectDialog(lambda: {}, lambda p: None, window)
    WorkflowDialog(window)
    app.processEvents()
    window.close()
