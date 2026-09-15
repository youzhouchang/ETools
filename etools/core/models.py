"""Core data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


class ProbeType(Enum):
    """Supported debug probe families."""

    STLINK = "stlink"
    JLINK = "jlink"
    CMSIS_DAP = "cmsisdap"
    UNKNOWN = "unknown"


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class OperationKind(Enum):
    IDLE = "idle"
    CONNECT = "connect"
    ERASE = "erase"
    PROGRAM = "program"
    READ = "read"
    VERIFY = "verify"
    RESET = "reset"
    INFO = "info"


class ProgressStage(Enum):
    """Coarse phase of a long-running operation."""

    IDLE = "idle"
    CONNECT = "connect"
    ERASE = "erase"
    PROGRAM = "program"
    VERIFY = "verify"
    READ = "read"
    RESET = "reset"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class ProgressInfo:
    """Structured progress event emitted from driver → UI."""

    stage: ProgressStage = ProgressStage.IDLE
    percent: int = 0  # 0..100, -1 = indeterminate
    message: str = ""
    bytes_done: int = 0
    bytes_total: int = 0
    is_error: bool = False

    @property
    def indeterminate(self) -> bool:
        return self.percent < 0

    @property
    def format_bytes(self) -> str:
        if self.bytes_total <= 0:
            return ""
        return f"{self.bytes_done:,}/{self.bytes_total:,} B"


@dataclass
class ProbeInfo:
    """A discovered debug probe (pyOCD DebugProbe)."""

    probe_type: ProbeType
    unique_id: str
    product_name: str = ""
    vendor_name: str = ""
    board_name: str = ""
    is_integrated: bool = False

    @property
    def display_name(self) -> str:
        label = self.probe_type.value.upper()
        product = self.product_name or self.vendor_name
        if product and self.unique_id:
            return f"{label} — {product} [{self.unique_id}]"
        if product:
            return f"{label} — {product}"
        if self.unique_id:
            return f"{label} [{self.unique_id}]"
        return label


@dataclass
class TargetInfo:
    """MCU target selection for a pyOCD session."""

    target_override: str = "cortex_m"
    flash_base: int = 0x0800_0000
    flash_size: int = 0
    ram_base: int = 0x2000_0000
    ram_size: int = 0
    cpu: str = "cortex-m"
    device_id: str = ""
    description: str = ""
    connect_mode: str = "halt"  # halt | attach | pre-reset | under-reset
    # pyOCD optional session knobs
    wire_protocol: str = "swd"  # swd | jtag | auto
    frequency_hz: int = 0  # 0 = probe default
    reset_type: str = "default"  # default | hw | sw | hw_under_reset | sw_sysresetreq

    @property
    def display_name(self) -> str:
        if self.description:
            return f"{self.description} ({self.target_override})"
        return self.target_override


@dataclass
class TargetDetails:
    """Live target inventory read after connect."""

    target_name: str = ""
    vendor: str = ""
    cpu: str = ""
    core_name: str = ""
    device_id: str = ""
    uid: str = ""
    uid_ok: bool = False
    flash_base: int = 0
    flash_size: int = 0
    ram_base: int = 0
    ram_size: int = 0
    voltage: float | None = None
    voltage_ok: bool = False
    probe_name: str = ""
    probe_type: str = ""
    wire_protocol: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def flash_size_display(self) -> str:
        return format_size(self.flash_size)

    @property
    def ram_size_display(self) -> str:
        return format_size(self.ram_size)

    @property
    def voltage_display(self) -> str:
        if not self.voltage_ok or self.voltage is None:
            return "N/A"
        return f"{self.voltage:.2f} V"

    def summary_line(self) -> str:
        parts = [self.target_name or self.cpu or "?"]
        if self.flash_size:
            parts.append(f"Flash {self.flash_size_display}")
        if self.voltage_ok:
            parts.append(self.voltage_display)
        return " · ".join(parts)


def format_size(n: int) -> str:
    if n <= 0:
        return "—"
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return f"{n // (1024 * 1024)} MiB"
    if n >= 1024 and n % 1024 == 0:
        return f"{n // 1024} KiB"
    return f"{n} B"


@dataclass
class OperationResult:
    """Outcome of a flash/erase/read/verify operation."""

    ok: bool
    message: str = ""
    duration_s: float = 0.0
    bytes_processed: int = 0
    detail: str = ""
    data: Any = None  # optional payload (e.g. TargetDetails)


@dataclass
class FirmwareImage:
    """A firmware file ready to program."""

    path: Path
    size: int = 0
    format: str = ""  # elf / hex / bin / axf / srec

    def __post_init__(self) -> None:
        p = Path(self.path)
        if self.size == 0 and p.exists():
            self.size = p.stat().st_size
        if not self.format:
            self.format = p.suffix.lstrip(".").lower() or "bin"

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()

    @property
    def display_name(self) -> str:
        return Path(self.path).name


# Compatibility re-export (prefer etools.core.targets)
from etools.core.targets import KNOWN_TARGETS  # noqa: E402,F401

# pyOCD DebugProbe class-name → ProbeType
PROBE_CLASS_MAP: dict[str, ProbeType] = {
    "stlink": ProbeType.STLINK,
    "cmsisdap": ProbeType.CMSIS_DAP,
    "cmsis-dap": ProbeType.CMSIS_DAP,
    "jlink": ProbeType.JLINK,
}

CONNECT_MODES: list[tuple[str, str]] = [
    ("halt", "Halt (default)"),
    ("attach", "Attach (no reset)"),
    ("pre-reset", "Pre-reset"),
    ("under-reset", "Under reset"),
]

# pyOCD DebugProbe wire protocols ("" = let probe decide)
WIRE_PROTOCOLS: list[tuple[str, str]] = [
    ("auto", "自动 (Auto)"),
    ("swd", "SWD"),
    ("jtag", "JTAG"),
]

# pyOCD ResetType names accepted in session options
RESET_TYPES: list[tuple[str, str]] = [
    ("default", "默认 (Default)"),
    ("hw", "硬件复位 (Hardware)"),
    ("sw", "软件复位 (Software)"),
    ("hw_under_reset", "硬件复位下连接 (Under reset)"),
    ("sw_sysresetreq", "SYSRESETREQ"),
]

# Default SWD/JTAG clock in kHz (10 MHz)
DEFAULT_FREQUENCY_KHZ = 10000

FIRMWARE_EXTENSIONS = "Firmware (*.bin *.hex *.elf *.axf *.srec);;All files (*)"

# STM32 96-bit unique ID base addresses by family (first readable wins)
STM32_UID_CANDIDATES: list[int] = [
    0x1FFF7590,  # F0/L0/G0/C0
    0x1FFF7A10,  # F2/F4
    0x1FF0F420,  # F7
    0x1FF1E800,  # H7
    0x1FFF7590,  # L4 sometimes
    0x1FFFF7AC,  # F1/F3
]

# DBGMCU_IDCODE (STM32)
STM32_IDCODE_ADDR = 0xE0042000
