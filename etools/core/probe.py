"""Probe abstraction layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from etools.core.models import (
    ConnectionState,
    OperationResult,
    ProbeInfo,
    ProgressInfo,
    ProgressStage,
    TargetDetails,
    TargetInfo,
)
from etools.logger import get_logger

log = get_logger("probe")

# Callback signature: (ProgressInfo,)
ProgressCallback = Callable[[ProgressInfo], None]


class ProbeDriver(ABC):
    """Abstract debug-probe backend.

    Long-running methods must emit ProgressInfo via the callback so the UI
    thread stays responsive and can drive a progress bar.
    """

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._on_progress: ProgressCallback | None = None

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    def set_progress_callback(self, cb: ProgressCallback | None) -> None:
        self._on_progress = cb

    def _emit(self, message: str, is_error: bool = False) -> None:
        """Convenience: text-only progress (indeterminate)."""
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.ERROR if is_error else ProgressStage.IDLE,
                percent=-1,
                message=message,
                is_error=is_error,
            )
        )

    def emit_progress(self, info: ProgressInfo) -> None:
        log.debug(
            "progress %s %s%%%s",
            info.stage.value,
            info.percent,
            f" {info.message}" if info.message else "",
        )
        if self._on_progress:
            self._on_progress(info)

    def _set_state(self, state: ConnectionState) -> None:
        self._state = state

    @abstractmethod
    def discover(self) -> list[ProbeInfo]:
        """Enumerate available probes on the host."""

    @abstractmethod
    def connect(self, probe: ProbeInfo, target: TargetInfo) -> OperationResult:
        """Attach to target through the given probe."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release probe and target."""

    @abstractmethod
    def erase(self, full_chip: bool = True) -> OperationResult:
        """Mass-erase or erase selected sectors."""

    @abstractmethod
    def program(self, firmware_path: str, verify: bool = True) -> OperationResult:
        """Write firmware to flash and optionally verify."""

    @abstractmethod
    def read(self, address: int, size: int, out_path: str) -> OperationResult:
        """Read memory/flash region into a file."""

    @abstractmethod
    def verify(self, firmware_path: str) -> OperationResult:
        """Compare flash contents against a firmware image."""

    @abstractmethod
    def reset(self, halt: bool = False) -> OperationResult:
        """Reset the target MCU."""

    @abstractmethod
    def get_target_details(self) -> TargetDetails:
        """Read live target inventory (UID / flash / voltage / …)."""
