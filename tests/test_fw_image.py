"""Sparse firmware image editing and export."""

from __future__ import annotations

import zlib

import pytest

from etools.core.fw_image import ImageError, SparseImage, to_ihex, to_srec
from etools.core.hexdump import parse_ihex, parse_srec


def test_write_coalesces_adjacent_and_overlapping() -> None:
    img = SparseImage([(0x100, b"\x01\x02"), (0x102, b"\x03")])
    assert img.segments() == [(0x100, b"\x01\x02\x03")]
    img.write(0x101, b"\xaa\xbb\xcc")
    assert img.segments() == [(0x100, b"\x01\xaa\xbb\xcc")]
    img.write(0x200, b"\x55")
    img.write(0x0FF, b"\x00" * 0x102)
    assert img.segments() == [(0x0FF, b"\x00" * 0x102)]


def test_merge_conflicts_are_detected() -> None:
    a = SparseImage([(0x0, b"\x01\x02\x03\x04")])
    b = SparseImage([(0x2, b"\x03\x04\x05")])
    c = SparseImage([(0x2, b"\xff")])
    assert a.overlaps(b) == [(2, 4)]
    assert a.conflicts(b) == []
    assert a.conflicts(c) == [(2, 3)]
    a.merge(b)
    assert a.segments() == [(0, b"\x01\x02\x03\x04\x05")]
    with pytest.raises(ImageError):
        a.merge(c)
    a.merge(c, overwrite=True)
    assert a.read(0, 5) == b"\x01\x02\xff\x04\x05"


def test_delete_crop_relocate_fill() -> None:
    img = SparseImage([(0x1000, bytes(range(16)))])
    img.delete(0x1004, 0x1008)
    assert img.segments() == [(0x1000, bytes(range(4))), (0x1008, bytes(range(8, 16)))]
    assert img.fill_gaps(0xEE) == 4
    assert img.read(0x1004, 4) == b"\xee" * 4
    img.crop(0x1002, 0x100A)
    assert img.start == 0x1002 and img.end == 0x100A
    img.rebase(0x0800_0000)
    assert img.start == 0x0800_0000
    with pytest.raises(ImageError):
        img.relocate(-0x0900_0000)
    img.pad_to(16)
    assert img.end % 16 == 0


def test_bin_crc_sha() -> None:
    img = SparseImage([(0x10, b"\x01"), (0x13, b"\x02")])
    base, data = img.to_bin(fill=0x00)
    assert base == 0x10 and data == b"\x01\x00\x00\x02"
    assert img.crc32(fill=0x00) == zlib.crc32(data)
    assert len(img.sha256()) == 64


def test_ihex_and_srec_roundtrip_across_64k_boundary() -> None:
    img = SparseImage([(0x0800_FFF0, bytes(range(40))), (0x0802_0000, b"\x99" * 3)])
    assert sorted(parse_ihex(to_ihex(img))) == [
        (0x0800_FFF0, bytes(range(16))),
        (0x0801_0000, bytes(range(16, 40))),
        (0x0802_0000, b"\x99" * 3),
    ]
    merged = SparseImage(parse_srec(to_srec(img)))
    assert merged.segments() == img.segments()


def test_load_and_save_files(tmp_path) -> None:
    img = SparseImage([(0x0800_0000, b"\x10\x20"), (0x0800_0100, b"\x30")])
    for name, fmt in (("a.hex", "hex"), ("a.srec", "srec"), ("a.bin", "bin")):
        path = tmp_path / name
        assert img.save(path) == fmt
        loaded = SparseImage.from_file(path, bin_base=0x0800_0000)
        if fmt == "bin":
            assert loaded.read(0x0800_0000, 0x101) == img.read(0x0800_0000, 0x101)
        else:
            assert loaded.segments() == img.segments()


def test_empty_image() -> None:
    img = SparseImage()
    assert img.empty and len(img) == 0
    assert img.to_bin() == (0, b"")
    assert img.summary() == "empty"
