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
from etools.core.option_bytes import ObSnapshot
from etools.core.probe import ProbeDriver
from etools.core.probe_io import PROBE_LOCK
from etools.logger import get_logger

log = get_logger("operations")


class FlashService:
    """Facade the UI calls; owns the active driver instance."""

    def __init__(self, driver: ProbeDriver) -> None:
        self.driver = driver
        # UI tasks and Lua scripts share this driver. Hold the lock for the
        # whole probe call so they cannot enter pyOCD at the same time.
        self._lock = PROBE_LOCK

    def scan_probes(self) -> list[ProbeInfo]:
        return self.driver.discover()

    def connect(self, probe: ProbeInfo, target: TargetInfo) -> OperationResult:
        with self._lock:
            return self.driver.connect(probe, target)

    def disconnect(self) -> None:
        with self._lock:
            self.driver.disconnect()

    def target_details(self) -> TargetDetails:
        with self._lock:
            return self.driver.get_target_details()

    def erase_all(self) -> OperationResult:
        with self._lock:
            return self.driver.erase(full_chip=True)

    def erase_sector(self) -> OperationResult:
        with self._lock:
            return self.driver.erase(full_chip=False)

    def erase_range(self, address: int, size: int) -> OperationResult:
        """Erase flash blocks covering [address, address+size)."""
        with self._lock:
            eraser = getattr(self.driver, "erase_range", None)
            if eraser is None:
                raise RuntimeError("Driver does not support erase_range")
            return eraser(int(address), int(size))

    def program_file(
        self, path: str | Path, verify: bool = True, *, incremental: bool = False
    ) -> OperationResult:
        img = FirmwareImage(path=Path(path))
        if not img.exists:
            return OperationResult(ok=False, message=f"File not found: {img.path}")
        log.info(
            "Programming %s (%d bytes, %s%s)",
            img.display_name,
            img.size,
            img.format,
            ", incremental" if incremental else "",
        )
        with self._lock:
            if incremental:
                return self.driver.program(str(img.path), verify=verify, incremental=True)
            return self.driver.program(str(img.path), verify=verify)

    def _driver_op(self, name: str):
        op = getattr(self.driver, name, None)
        if op is None:
            raise RuntimeError(f"Driver does not support {name}")
        return op

    def program_segments(
        self,
        segments: list[tuple[int, bytes]],
        *,
        verify: bool = True,
        erase: str = "sector",
        incremental: bool = False,
        label: str = "image",
    ) -> OperationResult:
        with self._lock:
            return self._driver_op("program_segments")(
                segments, verify=verify, erase=erase, incremental=incremental, label=label
            )

    def verify_segments(self, segments: list[tuple[int, bytes]]) -> OperationResult:
        with self._lock:
            return self._driver_op("verify_segments")(segments)

    def read_uid(self) -> bytes:
        with self._lock:
            return self._driver_op("read_uid_bytes")()

    def read_option_bytes(self) -> ObSnapshot:
        with self._lock:
            ob = self._driver_op("option_bytes")()
            return ObSnapshot.capture(ob)

    def write_option_bytes(self, values: dict[str, int]) -> OperationResult:
        """Program option bytes, then reload them (reset / reconnect as needed)."""
        with self._lock:
            ob = self._driver_op("option_bytes")()
            outcome = ob.write(values)
            if not outcome.changes:
                return OperationResult(ok=True, message="Option bytes unchanged", data=outcome)
            applied = self._driver_op("after_option_write")(outcome.reload)
            summary = ", ".join(f"{c.key}={c.new:#x}" for c in outcome.changes)
            if not applied.ok:
                return OperationResult(
                    ok=False,
                    message=f"Option bytes written ({summary}) but {applied.message}",
                    data=outcome,
                )
            return OperationResult(
                ok=True, message=f"Option bytes written: {summary}", data=outcome
            )

    def set_external_flm(self, path: str):
        with self._lock:
            return self._driver_op("set_external_flm")(path)

    def read_flash(self, address: int, size: int, out_path: str | Path) -> OperationResult:
        with self._lock:
            return self.driver.read(address, size, str(out_path))

    def read_memory_bytes(self, address: int, size: int, *, fresh: bool = False) -> bytes:
        """Read target memory without writing a file (for Hex preview)."""
        with self._lock:
            reader = getattr(self.driver, "read_memory_bytes", None)
            if reader is None:
                raise RuntimeError("Driver does not support in-memory read")
            return reader(address, size, fresh=fresh)

    def fill_memory(self, address: int, size: int, value: int = 0xFF) -> OperationResult:
        """Fill RAM with a repeated byte (Flash is rejected by the driver)."""
        with self._lock:
            filler = getattr(self.driver, "fill_memory", None)
            if filler is None:
                raise RuntimeError("Driver does not support fill_memory")
            return filler(address, size, value)

    def flash_size_hint(self) -> int | None:
        """Best-effort flash size from the live session (or None)."""
        try:
            with self._lock:
                details = self.driver.get_target_details()
            return int(details.flash_size) if details.flash_size else None
        except Exception:
            return None

    def verify_file(self, path: str | Path) -> OperationResult:
        with self._lock:
            return self.driver.verify(str(path))

    def reset_target(self, halt: bool = False) -> OperationResult:
        with self._lock:
            return self.driver.reset(halt=halt)

    @property
    def connected(self) -> bool:
        return self.driver.connected
