"""Unit tests for hex / srec image segment parsers (no hardware needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from etools.core.pyocd_driver import PyOCDDriver, _looks_like_valid_uid, _probe_type_from_unique_id
from etools.core.models import ProbeType, TargetInfo


@pytest.fixture
def driver() -> PyOCDDriver:
    d = PyOCDDriver()
    d._target = TargetInfo(target_override="stm32f103rc", flash_base=0x0800_0000)
    return d


class TestUidValidation:
    def test_all_zero(self):
        assert not _looks_like_valid_uid(b"\x00" * 12)

    def test_all_ff(self):
        assert not _looks_like_valid_uid(b"\xff" * 12)

    def test_realistic(self):
        raw = bytes.fromhex("323634353330352020202020")
        assert _looks_like_valid_uid(raw)

    def test_too_short(self):
        assert not _looks_like_valid_uid(b"\x01\x02\x03")


class TestProbeTypeHeuristics:
    def test_stlink(self):
        assert _probe_type_from_unique_id("0670FF55", "ST-Link V2") is ProbeType.STLINK

    def test_jlink(self):
        assert _probe_type_from_unique_id("123456", "J-Link") is ProbeType.JLINK

    def test_cmsis(self):
        assert _probe_type_from_unique_id("abc", "CMSIS-DAP") is ProbeType.CMSIS_DAP

    def test_unknown(self):
        assert _probe_type_from_unique_id("xyz", "Foo") is ProbeType.UNKNOWN


class TestHexParser:
    def test_simple(self, driver: PyOCDDriver):
        # :10 0000 00 + 16 data bytes + checksum; then EOF
        data = bytes(range(16))
        # length=0x10, addr=0x0000, type=0x00
        rec = b":10000000" + data.hex().upper().encode() + b"00\n"
        rec += b":00000001FF\n"
        segs = driver._parse_hex(rec.decode())
        assert len(segs) == 1
        addr, payload = segs[0]
        assert addr == 0
        assert payload == data

    def test_extended_linear(self, driver: PyOCDDriver):
        # ELA 0x0800 → base 0x08000000; one data byte at offset 0
        lines = [
            ":020000040800F2",  # ELA 0x0800
            ":04000000DEADBEEF00",  # will need correct checksum — use computed
            ":00000001FF",
        ]
        # Build programmatically with valid checksums
        def rec(length, addr, rtype, payload: bytes) -> str:
            body = bytes([length, (addr >> 8) & 0xFF, addr & 0xFF, rtype]) + payload
            csum = ((~sum(body) + 1) & 0xFF)
            return ":" + body.hex().upper() + f"{csum:02X}"

        ela = rec(2, 0, 0x04, bytes([0x08, 0x00]))
        data = rec(4, 0, 0x00, bytes([0xDE, 0xAD, 0xBE, 0xEF]))
        eof = rec(0, 0, 0x01, b"")
        segs = driver._parse_hex("\n".join([ela, data, eof]))
        assert len(segs) == 1
        addr, payload = segs[0]
        assert addr == 0x0800_0000
        assert payload == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_empty(self, driver: PyOCDDriver):
        assert driver._parse_hex("") == []


class TestSrecParser:
    def test_s1(self, driver: PyOCDDriver):
        # S1: count=0x05, addr=0x0000, data=0x112233, csum
        # count includes addr+data+csum = 2+3+1=6 → 0x06
        # Build properly
        addr = 0x0000
        payload = bytes([0x11, 0x22, 0x33])
        count = 2 + len(payload) + 1
        body = bytes([count]) + addr.to_bytes(2, "big") + payload
        csum = 0xFF - (sum(body) & 0xFF)
        line = "S1" + body.hex().upper() + f"{csum:02X}"
        # S7 terminator
        term_body = bytes([4, 0, 0, 0, 0])
        # simpler: skip accurate term, parser stops on S7
        segs = driver._parse_srec(line + "\nS70500000000FA\n")
        assert len(segs) == 1
        a, p = segs[0]
        assert a == addr
        assert p == payload


class TestBinFallback:
    def test_bin_uses_flash_base(self, driver: PyOCDDriver, tmp_path: Path):
        f = tmp_path / "fw.bin"
        f.write_bytes(b"\x01\x02\x03\x04")
        segs = driver._load_image_segments(f)
        assert segs == [(0x0800_0000, b"\x01\x02\x03\x04")]
