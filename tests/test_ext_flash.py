"""External flash FLM helpers (no probe required)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from etools.core.ext_flash import (
    REGION_NAME,
    ExtFlashError,
    FlmInfo,
    inspect_flm,
    suspended,
)


def test_missing_flm(tmp_path) -> None:
    with pytest.raises(ExtFlashError, match="not found"):
        inspect_flm(tmp_path / "none.FLM")


def test_invalid_flm(tmp_path) -> None:
    bad = tmp_path / "bad.FLM"
    bad.write_bytes(b"not an elf")
    with pytest.raises(ExtFlashError, match="Invalid FLM"):
        inspect_flm(bad)


class _Map:
    def __init__(self, regions) -> None:
        self.regions = list(regions)

    def remove_region(self, region) -> None:
        self.regions.remove(region)

    def add_region(self, region) -> None:
        self.regions.append(region)


def _target_with_flm():
    flm = SimpleNamespace(name=REGION_NAME)
    internal = SimpleNamespace(name="flash")
    mm, core_mm = _Map([internal, flm]), _Map([internal, flm])
    target = SimpleNamespace(memory_map=mm, cores={0: SimpleNamespace(memory_map=core_mm)})
    return target, mm, core_mm, internal, flm


def test_suspended_hides_flm_region_and_restores_it() -> None:
    target, mm, core_mm, internal, flm = _target_with_flm()
    with suspended(target) as hidden:
        assert hidden
        assert mm.regions == [internal] and core_mm.regions == [internal]
    assert flm in mm.regions and flm in core_mm.regions


def test_suspended_restores_after_error() -> None:
    target, mm, _core_mm, _internal, flm = _target_with_flm()
    with pytest.raises(RuntimeError), suspended(target):
        raise RuntimeError("erase failed")
    assert flm in mm.regions


def test_full_chip_erase_skips_external_flash(monkeypatch) -> None:
    from pyocd.flash import eraser

    from etools.core.models import ConnectionState
    from etools.core.pyocd_driver import PyOCDDriver

    target, mm, _core_mm, _internal, flm = _target_with_flm()
    seen: list[list] = []

    class Eraser:
        Mode = eraser.FlashEraser.Mode

        def __init__(self, session, mode) -> None:
            pass

        def erase(self) -> None:
            seen.append(list(mm.regions))

    monkeypatch.setattr(eraser, "FlashEraser", Eraser)
    driver = PyOCDDriver()
    driver._session = SimpleNamespace(target=target)
    driver._set_state(ConnectionState.CONNECTED)
    assert driver.erase(full_chip=True).ok
    assert flm not in seen[0]
    assert flm in mm.regions


def test_summary_text() -> None:
    info = FlmInfo("x.FLM", "W25Q64", 0x9000_0000, 8 << 20, 256, [(0, 4096)])
    text = info.summary()
    assert "0x90000000..0x907FFFFF" in text
    assert "8192 KiB" in text and "4 KiB" in text
