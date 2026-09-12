"""Hex dump / preview helpers."""

from __future__ import annotations

from pathlib import Path

from etools.core.hexdump import (
    format_hex_lines,
    load_image_segments,
    merge_segments,
    parse_ihex,
    segments_summary,
)


def test_parse_ihex_and_format():
    def rec(length, addr, rtype, payload: bytes) -> str:
        body = bytes([length, (addr >> 8) & 0xFF, addr & 0xFF, rtype]) + payload
        csum = (~sum(body) + 1) & 0xFF
        return ":" + body.hex().upper() + f"{csum:02X}"

    ela = rec(2, 0, 0x04, bytes([0x08, 0x00]))
    data = rec(16, 0, 0x00, bytes(range(16)))
    eof = rec(0, 0, 0x01, b"")
    segs = parse_ihex("\n".join([ela, data, eof]))
    assert segs[0][0] == 0x0800_0000
    assert segs[0][1] == bytes(range(16))
    rows = format_hex_lines(segs[0][0], segs[0][1])
    assert rows[0][0] == "0x08000000"
    assert "00 01 02" in rows[0][1]
    assert rows[0][2].startswith(".")


def test_load_bin(tmp_path: Path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"\xAB" * 32)
    segs = load_image_segments(p)
    assert segs[0][0] == 0x0800_0000
    assert len(segs[0][1]) == 32


def test_merge_segments():
    a = merge_segments([(0x100, b"AA"), (0x102, b"BB"), (0x200, b"CC")])
    assert a[0] == (0x100, b"AABB")
    assert a[1] == (0x200, b"CC")
    assert "2 段" in segments_summary(a)
