"""HardFault decode, RTOS plugin selection, and the diagnosis page."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from etools.core.diagnosis import (  # noqa: E402
    BFAR,
    CFSR,
    DFSR,
    HFSR,
    MMFAR,
    address_valid,
    capture,
    decode_flags,
    frame_from_words,
    frame_stack_name,
    inspect_rtos,
    is_exc_return,
)

_DIVBYZERO = 1 << (16 + 9)
_FORCED = 1 << 30
_FRAME = (1, 2, 3, 4, 12, 0xFFFFFFF9, 0x08000100, 0x01000000)


class _Core:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.halted = 0
        self.resumed = 0
        self.regs = {
            "pc": 0x08001234,
            "lr": 0xFFFFFFFD,
            "xpsr": 3,
            "msp": 0x20001000,
            "psp": 0x20002000,
        }
        self.mem = {
            CFSR: _DIVBYZERO,
            HFSR: _FORCED,
            DFSR: 1,
            MMFAR: 0,
            BFAR: 0x20000010,
        }

    def is_running(self) -> bool:
        return self.running

    def halt(self) -> None:
        self.halted += 1
        self.running = False

    def resume(self) -> None:
        self.resumed += 1
        self.running = True

    def read_core_register(self, name: str) -> int:
        return self.regs[name]

    def read32(self, addr: int) -> int:
        return self.mem.get(addr, 0)

    def read_memory_block8(self, addr: int, size: int) -> bytes:
        if addr != self.regs["psp"]:
            return bytes(size)
        raw = b"".join(word.to_bytes(4, "little") for word in _FRAME)
        return raw[:size]


class _Symbols:
    def get_symbol_value(self, name: str) -> int | None:
        if name == "pxCurrentTCB":
            return 0x20000000
        return None


class _Thread:
    name = "idle"
    description = "Ready"
    STATE_NAMES = {1: "Ready"}
    state = 1
    priority = 0
    unique_id = 0x20001000
    is_current = True


class _Plugin:
    def __init__(self, _target: object) -> None:
        self.read_from_target = False
        self.updated = False

    def init(self, symbols: _Symbols) -> bool:
        return symbols.get_symbol_value("pxCurrentTCB") is not None

    def update_threads(self) -> None:
        self.updated = True

    def get_threads(self) -> list[_Thread]:
        return [_Thread()]


class _Miss:
    def __init__(self, _target: object) -> None:
        self.read_from_target = False

    def init(self, _symbols: _Symbols) -> bool:
        return False

    def get_threads(self) -> list[_Thread]:
        raise AssertionError("a plugin that missed its symbols must not be read")


def test_decode_div_by_zero_and_forced_fault() -> None:
    flags = decode_flags(_DIVBYZERO, _FORCED, 1)
    names = {(flag.group, flag.name) for flag in flags}
    assert ("UFSR", "DIVBYZERO") in names
    assert ("HFSR", "FORCED") in names
    assert ("DFSR", "HALTED") in names
    assert address_valid(_DIVBYZERO) == (False, False)
    assert address_valid(0x80 | (1 << 15)) == (True, True)


def test_exception_frame_uses_psp_when_exc_return_says_so() -> None:
    assert is_exc_return(0xFFFFFFFD)
    assert not is_exc_return(0x08000100)
    assert frame_stack_name(0xFFFFFFFD) == "PSP"
    assert frame_stack_name(0xFFFFFFF9) == "MSP"
    assert frame_stack_name(0x08000100) == ""
    frame = dict(frame_from_words(_FRAME))
    assert frame["pc"] == 0x08000100
    assert frame["lr"] == 0xFFFFFFF9


def test_first_matching_rtos_plugin_is_used() -> None:
    snap = inspect_rtos(object(), _Symbols(), {"none": _Miss, "freertos": _Plugin})
    assert snap.ok
    assert snap.plugin == "freertos"
    assert snap.threads[0].name == "idle"
    assert snap.threads[0].state == "Ready"
    assert snap.threads[0].current


def test_capture_leaves_a_running_core_alone_by_default() -> None:
    core = _Core(running=True)
    session = SimpleNamespace(target=SimpleNamespace(selected_core=core))
    fault, rtos = capture(session, "")
    assert core.halted == 0
    assert fault.ok
    assert fault.running
    assert fault.pc is None
    assert not fault.frame
    assert any(flag.name == "DIVBYZERO" for flag in fault.flags)
    assert rtos.error == "running"


def test_capture_holds_the_probe_lock() -> None:
    import threading

    lock = threading.RLock()
    seen: list[bool] = []

    class _LockedCore(_Core):
        def read32(self, addr: int) -> int:
            seen.append(lock._is_owned())
            return super().read32(addr)

    session = SimpleNamespace(target=SimpleNamespace(selected_core=_LockedCore()))
    capture(session, "", lock=lock)
    assert seen and all(seen)


def test_capture_resumes_a_running_core_when_halt_is_on() -> None:
    core = _Core(running=True)
    session = SimpleNamespace(target=SimpleNamespace(selected_core=core))
    fault, rtos = capture(session, "", halt=True)
    assert core.halted == 1
    assert core.resumed == 1
    assert fault.ok
    assert fault.resumed
    assert fault.frame_stack == "PSP"
    assert dict(fault.frame)["pc"] == 0x08000100
    assert any(flag.name == "DIVBYZERO" for flag in fault.flags)
    assert rtos.error == "no_elf"
    assert capture(None, "")[0].error == "not_connected"


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_diagnosis_page_refreshes_from_the_session(qapp) -> None:
    from etools.i18n import tr
    from etools.ui.tools.program_page import ProgramPage

    page = ProgramPage()
    page.goto_tab("diag")
    assert page.main_tabs.tabText(page.main_tabs.currentIndex()) == tr("tab.diag")
    page.diag_panel.refresh()
    assert tr("diag.not_connected") in page.diag_panel.fault_summary.text()

    core = _Core()
    session = SimpleNamespace(target=SimpleNamespace(selected_core=core))
    page.set_session_getter(lambda: session)
    page.set_connected(True)
    page.diag_panel.elf_edit.setText("firmware.hex")
    page.diag_panel.refresh()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        qapp.processEvents()
        if "DIVBYZERO" in _table_text(page.diag_panel.flag_table):
            break
        time.sleep(0.02)
    assert "DIVBYZERO" in _table_text(page.diag_panel.flag_table)
    assert "PSP" in page.diag_panel.frame_title.text()
    assert tr("diag.rtos_not_elf") in page.diag_panel.rtos_summary.text()

    page.diag_panel.refresh()
    page.shutdown()
    assert page.diag_panel._job is None
    page.close()


def _table_text(table) -> str:
    parts: list[str] = []
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is not None:
                parts.append(item.text())
    return " ".join(parts)
