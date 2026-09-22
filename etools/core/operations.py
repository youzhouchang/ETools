"""High-level flash operations orchestrating the probe driver."""

from __future__ import annotations

from pathlib import Path

from etools.core.models import (
    FirmwareImage,
    OperationResult,
    ProbeInfo,
    TargetDetails,
    TargetInfo,
)
from etools.core.probe import ProbeDriver
from etools.logger import get_logger

log = get_logger("operations")


class FlashService:
    """Facade the UI calls; owns the active driver instance."""

    def __init__(self, driver: ProbeDriver) -> None:
        self.driver = driver

    def scan_probes(self) -> list[ProbeInfo]:
        return self.driver.discover()

    def connect(self, probe: ProbeInfo, target: TargetInfo) -> OperationResult:
        return self.driver.connect(probe, target)

    def disconnect(self) -> None:
        self.driver.disconnect()

    def target_details(self) -> TargetDetails:
        return self.driver.get_target_details()

    def erase_all(self) -> OperationResult:
        return self.driver.erase(full_chip=True)

    def erase_sector(self) -> OperationResult:
        return self.driver.erase(full_chip=False)

    def erase_range(self, address: int, size: int) -> OperationResult:
        """Erase flash blocks covering [address, address+size)."""
        eraser = getattr(self.driver, "erase_range", None)
        if eraser is None:
            raise RuntimeError("Driver does not support erase_range")
        return eraser(int(address), int(size))

    def program_file(self, path: str | Path, verify: bool = True) -> OperationResult:
        img = FirmwareImage(path=Path(path))
        if not img.exists:
            return OperationResult(ok=False, message=f"File not found: {img.path}")
        log.info("Programming %s (%d bytes, %s)", img.display_name, img.size, img.format)
        return self.driver.program(str(img.path), verify=verify)

    def read_flash(self, address: int, size: int, out_path: str | Path) -> OperationResult:
        return self.driver.read(address, size, str(out_path))

    def read_memory_bytes(self, address: int, size: int) -> bytes:
        """Read target memory without writing a file (for Hex preview)."""
        reader = getattr(self.driver, "read_memory_bytes", None)
        if reader is None:
            raise RuntimeError("Driver does not support in-memory read")
        return reader(address, size)

    def fill_memory(self, address: int, size: int, value: int = 0xFF) -> OperationResult:
        """Fill RAM with a repeated byte (Flash is rejected by the driver)."""
        filler = getattr(self.driver, "fill_memory", None)
        if filler is None:
            raise RuntimeError("Driver does not support fill_memory")
        return filler(address, size, value)

    def flash_size_hint(self) -> int | None:
        """Best-effort flash size from the live session (or None)."""
        try:
            details = self.driver.get_target_details()
            return int(details.flash_size) if details.flash_size else None
        except Exception:
            return None

    def verify_file(self, path: str | Path) -> OperationResult:
        return self.driver.verify(str(path))

    def reset_target(self, halt: bool = False) -> OperationResult:
        return self.driver.reset(halt=halt)

    @property
    def connected(self) -> bool:
        return self.driver.connected
