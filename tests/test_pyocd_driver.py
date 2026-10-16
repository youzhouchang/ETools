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


def test_pyinstaller_keeps_pyocd_entry_point_metadata() -> None:
    spec = Path("packaging/etools.spec").read_text(encoding="utf-8")

    assert 'copy_metadata("pyocd")' in spec
