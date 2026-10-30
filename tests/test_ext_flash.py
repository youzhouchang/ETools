"""External flash FLM helpers (no probe required)."""

from __future__ import annotations

import pytest

from etools.core.ext_flash import ExtFlashError, FlmInfo, inspect_flm


def test_missing_flm(tmp_path) -> None:
    with pytest.raises(ExtFlashError, match="not found"):
        inspect_flm(tmp_path / "none.FLM")


def test_invalid_flm(tmp_path) -> None:
    bad = tmp_path / "bad.FLM"
    bad.write_bytes(b"not an elf")
    with pytest.raises(ExtFlashError, match="Invalid FLM"):
        inspect_flm(bad)


def test_summary_text() -> None:
    info = FlmInfo("x.FLM", "W25Q64", 0x9000_0000, 8 << 20, 256, [(0, 4096)])
    text = info.summary()
    assert "0x90000000..0x907FFFFF" in text
    assert "8192 KiB" in text and "4 KiB" in text
