"""Tests for pyOCD probe discovery and frozen-package configuration."""

from __future__ import annotations

from pathlib import Path

from pyocd.core.helpers import ConnectHelper

import etools.core.pyocd_driver as driver_module
from etools.core.models import ConnectionState, ProbeType
from etools.core.pyocd_driver import PyOCDDriver


class _FakeStlinkProbe:
    unique_id = "STLINK-TEST-001"
    product_name = "STLINK-V3"
    vendor_name = "STMicroelectronics"
    board_name = ""


def test_discover_falls_back_to_direct_stlink_scan(monkeypatch) -> None:
    monkeypatch.setattr(
        ConnectHelper,
        "get_all_connected_probes",
        lambda **_kwargs: [],
    )

    class StlinkProbe(_FakeStlinkProbe):
        @staticmethod
        def get_all_connected_probes():
            return [StlinkProbe()]

    monkeypatch.setattr(driver_module, "_direct_probe_backends", lambda: [StlinkProbe])

    probes = PyOCDDriver().discover()

    assert len(probes) == 1
    assert probes[0].probe_type is ProbeType.STLINK
    assert probes[0].unique_id == "STLINK-TEST-001"


def test_direct_probe_scan_isolates_backends_and_deduplicates(monkeypatch) -> None:
    monkeypatch.setattr(
        ConnectHelper,
        "get_all_connected_probes",
        lambda **_kwargs: [],
    )

    class BrokenBackend:
        @staticmethod
        def get_all_connected_probes():
            raise RuntimeError("backend unavailable")

    class StlinkProbe(_FakeStlinkProbe):
        @staticmethod
        def get_all_connected_probes():
            return [StlinkProbe(), StlinkProbe()]

    monkeypatch.setattr(
        driver_module,
        "_direct_probe_backends",
        lambda: [BrokenBackend, StlinkProbe],
    )

    probes = PyOCDDriver().discover()

    assert [probe.unique_id for probe in probes] == ["STLINK-TEST-001"]


def _ihex_record(length: int, addr: int, rtype: int, payload: bytes) -> str:
    body = bytes([length, (addr >> 8) & 0xFF, addr & 0xFF, rtype]) + payload
    checksum = (~sum(body) + 1) & 0xFF
    return ":" + body.hex().upper() + f"{checksum:02X}"


def test_hex_parser_uses_programmed_addresses() -> None:
    text = "\n".join(
        [
            _ihex_record(2, 0, 0x04, bytes([0x08, 0x00])),
            _ihex_record(1, 0x408, 0x00, bytes([0x94])),
            _ihex_record(0, 0, 0x01, b""),
        ]
    )
    assert PyOCDDriver()._parse_hex(text) == [(0x08000408, b"\x94")]


def test_fresh_flash_read_resets_and_drops_cache() -> None:
    calls: list[str] = []

    class Context:
        def invalidate(self) -> None:
            calls.append("invalidate")

    class Core:
        def get_target_context(self) -> Context:
            return Context()

    class Target:
        def reset_and_halt(self) -> None:
            calls.append("reset")

        def selected_core_or_raise(self) -> Core:
            return Core()

    class Session:
        target = Target()

    PyOCDDriver()._prepare_fresh_flash_read(Session())
    assert calls == ["reset", "invalidate"]


def test_program_rewrites_every_page(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Programmer:
        def __init__(self, _session, **kwargs) -> None:
            captured.update(kwargs)

        def program(self, path: str) -> None:
            captured["path"] = path

    import pyocd.flash.file_programmer as file_programmer

    monkeypatch.setattr(file_programmer, "FileProgrammer", Programmer)
    driver = PyOCDDriver()
    driver._session = object()
    driver._set_state(ConnectionState.CONNECTED)
    path = tmp_path / "fw.hex"
    path.write_text(":00000001FF\n", encoding="ascii")

    result = driver.program(str(path), verify=False)

    assert result.ok
    assert captured["smart_flash"] is False
    assert captured["trust_crc"] is False


class _MemTarget:
    """Fake pyOCD target backed by a dict, for loader/verify tests."""

    def __init__(self) -> None:
        self.mem: dict[int, int] = {}
        self.resets = 0

    def read_memory_block8(self, addr: int, n: int) -> list[int]:
        return [self.mem.get(addr + i, 0xFF) for i in range(n)]

    def reset_and_halt(self) -> None:
        self.resets += 1

    def selected_core_or_raise(self):
        raise RuntimeError("no core")


def _connected_driver(target) -> PyOCDDriver:
    class Session:
        pass

    session = Session()
    session.target = target
    driver = PyOCDDriver()
    driver._session = session
    driver._set_state(ConnectionState.CONNECTED)
    return driver


def test_incremental_program_uses_smart_flash(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Programmer:
        def __init__(self, _session, **kwargs) -> None:
            captured.update(kwargs)

        def program(self, path: str) -> None:
            pass

    import pyocd.flash.file_programmer as file_programmer

    monkeypatch.setattr(file_programmer, "FileProgrammer", Programmer)
    target = _MemTarget()
    driver = _connected_driver(target)
    path = tmp_path / "fw.hex"
    path.write_text(":00000001FF\n", encoding="ascii")

    result = driver.program(str(path), verify=False, incremental=True)

    assert result.ok and "incremental" in result.message
    assert captured["smart_flash"] is True
    assert captured["chip_erase"] == "sector"
    assert target.resets == 1  # fresh read before comparing sectors


def test_program_segments_loads_and_verifies(monkeypatch) -> None:
    target = _MemTarget()
    captured: dict[str, object] = {}

    class Loader:
        def __init__(self, _session, **kwargs) -> None:
            captured.update(kwargs)
            self.data: list[tuple[int, bytes]] = []

        def add_data(self, addr: int, data: bytes) -> None:
            self.data.append((addr, data))

        def commit(self) -> None:
            for addr, data in self.data:
                for i, b in enumerate(data):
                    target.mem[addr + i] = b

    import pyocd.flash.loader as loader_module

    monkeypatch.setattr(loader_module, "MemoryLoader", Loader)
    driver = _connected_driver(target)
    segs = [(0x0800_0000, b"\x01\x02"), (0x0800_0100, b"\x03")]

    ok = driver.program_segments(segs, erase="chip", label="prod")
    assert ok.ok and ok.message == "Programmed prod"
    assert captured["chip_erase"] == "chip"
    assert captured["smart_flash"] is False

    target.mem[0x0800_0100] = 0x00
    bad = driver.verify_segments(segs)
    assert not bad.ok and "0x08000100" in bad.message
    assert not driver.program_segments([]).ok


def test_after_option_write_reconnects_on_obl(monkeypatch) -> None:
    from etools.core.models import OperationResult, ProbeInfo, TargetInfo

    driver = _connected_driver(_MemTarget())
    driver._probe = ProbeInfo(ProbeType.STLINK, "X")
    driver._target = TargetInfo()
    calls: list[str] = []
    monkeypatch.setattr(driver, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(
        driver,
        "connect",
        lambda probe, target: calls.append("connect") or OperationResult(ok=True, message="ok"),
    )
    monkeypatch.setattr(driver_module.time, "sleep", lambda s: None)

    assert driver.after_option_write("obl").ok
    assert calls == ["disconnect", "connect"]
    calls.clear()
    assert _connected_driver(_MemTarget()).after_option_write("none").ok


def test_set_external_flm_without_session_only_inspects(tmp_path) -> None:
    import pytest

    from etools.core.ext_flash import ExtFlashError

    driver = PyOCDDriver()
    assert driver.set_external_flm("") is None
    with pytest.raises(ExtFlashError):
        driver.set_external_flm(str(tmp_path / "missing.FLM"))
    assert driver.ext_flm_path.endswith("missing.FLM")


def test_pyinstaller_keeps_pyocd_entry_point_metadata() -> None:
    spec = Path("packaging/etools.spec").read_text(encoding="utf-8")

    assert 'copy_metadata("pyocd")' in spec
