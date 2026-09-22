"""Smoke tests for multi-tool shell, prefs, icons, and public action API."""

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


def test_tool_icons_exist():
    from etools.ui.icons import ICON_DIR

    for name in (
        "tool-program",
        "tool-serial",
        "tool-ethernet",
        "tool-terminal",
    ):
        path = ICON_DIR / f"{name}.svg"
        assert path.exists(), name
        text = path.read_text(encoding="utf-8")
        assert "currentColor" in text


def test_tool_prefs_roundtrip(tmp_path, monkeypatch):
    from etools import config as config_mod
    from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs

    monkeypatch.setattr(config_mod, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config_mod, "_config", config_mod.AppConfig())

    save_tool_prefs("serial", {"baud": "921600", "password": "secret"})
    prefs = load_tool_prefs("serial")
    assert prefs["baud"] == "921600"
    assert "password" not in prefs


def test_tool_prefs_readonly_save_is_best_effort(monkeypatch):
    from etools import config as config_mod
    from etools.ui.tool_prefs import save_tool_prefs

    monkeypatch.setattr(config_mod, "_config", config_mod.AppConfig())
    def fail_save(_self):
        raise PermissionError("readonly")

    monkeypatch.setattr(config_mod.AppConfig, "save", fail_save)
    save_tool_prefs("serial", {"baud": "115200"})


def test_tool_pages_public_api(qapp):
    from etools.ui.tools import EthernetPage, ProgramPage, SerialPage, TerminalPage

    for page_cls in (ProgramPage, SerialPage, EthernetPage, TerminalPage):
        page = page_cls()
        actions = page.toolbar_actions()
        assert actions, page_cls.__name__
        for spec in actions:
            assert spec.key
            assert spec.text_key
            assert spec.icon_name
            assert callable(spec.slot)
        page.retranslate()
        page.shutdown()
        page.close()


def test_serial_toolbar_not_private(qapp):
    from etools.ui.tools import SerialPage

    page = SerialPage()
    keys = [s.key for s in page.toolbar_actions()]
    assert "toggle" in keys
    assert "send" in keys
    assert "clear" in keys
    page.shutdown()
    page.close()


def test_terminal_owns_sftp_panel(qapp):
    from etools.ui.tools import TerminalPage

    page = TerminalPage()
    assert page.sftp_panel is not None
    assert page.sftp_panel.parent() is not None
    keys = [s.key for s in page.toolbar_actions()]
    assert "list" in keys and "upload" in keys and "download" in keys
    page.shutdown()
    page.close()


def test_traffic_view_hex_and_parse():
    from etools.ui.widgets.traffic_view import format_hex, parse_hex_input

    assert parse_hex_input("DE AD BE EF") == bytes.fromhex("DEADBEEF")
    assert parse_hex_input("0xde,0xad") == b"\xde\xad"
    dump = format_hex(b"\x00\x41", base_offset=0)
    assert "00000000" in dump and "41" in dump


def test_ssh_host_key_errors():
    from etools.core.ssh_link import HostKeyMismatchError, MissingHostKeyError

    e = MissingHostKeyError("h", 22, "SHA256:x")
    assert e.fingerprint.startswith("SHA256:")
    m = HostKeyMismatchError("h", 2222, "SHA256:y")
    assert m.port == 2222


def test_shell_builds_and_switches(qapp):
    from etools.ui.shell import TOOL_ORDER, ToolShell
    from etools.ui.tools import (
        EthernetPage,
        ProgramPage,
        SerialPage,
        SftpPanel,
        TerminalPage,
    )

    program = ProgramPage()
    serial = SerialPage()
    ethernet = EthernetPage()
    terminal = TerminalPage()
    sftp = SftpPanel()
    terminal.ssh_link_changed.connect(sftp.set_ssh)

    pages = {
        "program": program,
        "serial": serial,
        "ethernet": ethernet,
        "terminal": terminal,
    }
    providers = {
        "program": program.toolbar_actions,
        "serial": serial.toolbar_actions,
        "ethernet": ethernet.toolbar_actions,
        "terminal": lambda: list(terminal.toolbar_actions()) + list(sftp.toolbar_actions()),
    }
    shell = ToolShell(pages, providers)
    assert shell.tool_keys == [k for k, _ in TOOL_ORDER]
    assert set(shell.tool_buttons) == set(shell.tool_keys)
    for key in shell.tool_keys:
        assert key in shell.toolbars
        shell.set_current_tool(key)
        assert shell.current_tool == key
    # rail height scales with tool count (not hardcoded 4)
    n = len(shell.tool_buttons)
    assert shell._rail.maximumHeight() >= n * 48

    shell.shutdown()
    for p in (program, serial, ethernet, terminal, sftp):
        p.close()
    shell.close()


def test_main_window_builds_with_shell(qapp):
    from etools.ui.main_window import MainWindow
    from etools.ui.shell import ToolShell

    w = MainWindow()
    assert isinstance(w.shell, ToolShell)
    assert w.probe_panel is not None
    assert w.flash_panel is not None
    assert w.log_panel is not None
    assert w.serial_page is not None
    assert w.terminal_page is not None
    assert w.program_page is not None
    w.close()


def test_version_single_source():
    from pathlib import Path

    import tomllib

    import etools

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == etools.__version__


def test_task_manager_runs_parallel_tasks(qapp):
    import time

    from etools.ui.runtime import TaskManager

    manager = TaskManager()
    done = []
    manager.task_finished.connect(lambda task_id, result: done.append((task_id, result)))
    assert manager.start("a", lambda: (time.sleep(0.05), "a")[1])
    assert manager.start("b", lambda: (time.sleep(0.05), "b")[1])
    deadline = time.time() + 2
    while len(done) < 2 and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert sorted(done) == [("a", "a"), ("b", "b")]
    manager.shutdown()


def test_worker_invoke_matches_signature():
    """cancel_event is injected only for cancel-like params; never by TypeError-probing."""
    import threading

    from etools.ui.runtime import Worker

    seen = {}

    def no_args():
        return "plain"

    def with_cancel(cancel_event):
        seen["got"] = cancel_event
        return "cancel"

    def business_args(address, size):
        return address, size

    def raises_typeerror():
        raise TypeError("inner business error")

    w = Worker(no_args)
    assert w._invoke() == "plain"
    assert w._invoke() == "plain"  # no double-call retry

    w = Worker(with_cancel)
    assert w._invoke() == "cancel"
    assert isinstance(seen["got"], threading.Event)

    w = Worker(business_args)
    try:
        w._invoke()
    except TypeError as exc:
        assert "address" in str(exc)
    else:
        raise AssertionError("expected missing-arg TypeError, not silent injection")

    w = Worker(raises_typeerror)
    try:
        w._invoke()
    except TypeError as exc:
        assert "inner business error" in str(exc)
    else:
        raise AssertionError("TypeError must propagate")
