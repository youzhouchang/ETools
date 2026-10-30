"""External / extra flash through a CMSIS-Pack FLM algorithm (pyOCD)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etools.logger import get_logger

log = get_logger("ext_flash")

REGION_NAME = "etools_flm"


class ExtFlashError(RuntimeError):
    """The FLM could not be loaded or attached."""


@dataclass
class FlmInfo:
    path: str
    name: str
    start: int
    size: int
    page_size: int
    sectors: list[tuple[int, int]]  # (offset, sector size)
    erased_value: int = 0xFF

    def summary(self) -> str:
        sectors = ", ".join(f"+0x{off:X}: {size // 1024} KiB" for off, size in self.sectors[:4])
        return (
            f"{self.name}  0x{self.start:08X}..0x{self.start + self.size - 1:08X} "
            f"({self.size // 1024} KiB, page {self.page_size} B, sectors {sectors})"
        )


def _load(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file():
        raise ExtFlashError(f"FLM not found: {p}")
    try:
        from pyocd.target.pack.flash_algo import PackFlashAlgo

        return PackFlashAlgo(str(p))
    except Exception as exc:
        raise ExtFlashError(f"Invalid FLM {p.name}: {exc}") from exc


def inspect_flm(path: str | Path) -> FlmInfo:
    algo = _load(path)
    info = algo.flash_info
    name = getattr(info, "name", b"")
    if isinstance(name, bytes):
        name = name.split(b"\0", 1)[0].decode("ascii", "replace")
    return FlmInfo(
        path=str(path),
        name=str(name) or Path(path).stem,
        start=int(algo.flash_start),
        size=int(algo.flash_size),
        page_size=int(algo.page_size),
        sectors=[(int(o), int(s)) for o, s in algo.sector_sizes],
        erased_value=int(getattr(info, "value_empty", 0xFF)) & 0xFF,
    )


def _maps(target: Any) -> list[Any]:
    maps = [target.memory_map]
    for core in getattr(target, "cores", {}).values():
        mm = getattr(core, "memory_map", None)
        if mm is not None and all(mm is not m for m in maps):
            maps.append(mm)
    return maps


def detach_flm(target: Any) -> bool:
    removed = False
    for mm in _maps(target):
        for region in list(mm.regions):
            if region.name == REGION_NAME:
                mm.remove_region(region)
                removed = True
    return removed


def attach_flm(target: Any, path: str | Path) -> FlmInfo:
    """Add a flash region driven by the FLM to the live pyOCD target."""
    from pyocd.core.memory_map import FlashRegion, MemoryType
    from pyocd.flash.flash import Flash
    from pyocd.target.pack.flm_region_builder import FlmFlashRegionBuilder

    info = inspect_flm(path)
    algo = _load(path)
    detach_flm(target)
    mm = target.memory_map
    end = info.start + info.size - 1
    for region in list(mm.get_intersecting_regions(info.start, end)):
        if region.type == MemoryType.FLASH:
            raise ExtFlashError(
                f"FLM range overlaps on-chip flash region '{region.name}' "
                f"(0x{region.start:08X}..0x{region.end:08X})"
            )
        if region.type == MemoryType.RAM:
            raise ExtFlashError(f"FLM range overlaps RAM region '{region.name}'")
        for m in _maps(target):
            if region in m.regions:
                m.remove_region(region)
    region = FlashRegion(
        name=REGION_NAME,
        start=info.start,
        length=info.size,
        flm=algo,
        erased_byte_value=info.erased_value,
        is_boot_memory=False,
    )
    mm.add_region(region)
    if not FlmFlashRegionBuilder(target, mm).finalise_region(region):
        mm.remove_region(region)
        raise ExtFlashError("pyOCD could not build the flash algorithm (RAM too small?)")
    flash = Flash(target, region.algo)
    flash.region = region
    region.flash = flash
    for m in _maps(target)[1:]:
        m.add_region(region)
    log.info("Attached FLM %s", info.summary())
    return info
