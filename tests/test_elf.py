from pathlib import Path

import pytest

from etools.core.elf import ElfVariable, load_elf
from etools.ui.widgets.variable_monitor import _decode_value


def test_load_elf_missing_file_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_elf(tmp_path / "missing.elf")


def test_decode_integer_and_float_values() -> None:
    unsigned = ElfVariable("u", 0x20000000, 4, byte_size=4)
    signed = ElfVariable("i", 0x20000004, 2, encoding="DW_ATE_signed", byte_size=2)
    floating = ElfVariable("f", 0x20000008, 4, kind="float", byte_size=4)
    assert _decode_value(b"\x78\x56\x34\x12", unsigned) == 0x12345678
    assert _decode_value(b"\xff\xff", signed) == -1
    assert _decode_value(bytes.fromhex("0000803f"), floating) == pytest.approx(1.0)


def test_aggregate_value_is_not_plotted() -> None:
    array = ElfVariable("buf", 0x20000000, 16, kind="array", byte_size=16)
    assert _decode_value(bytes(16), array) is None
