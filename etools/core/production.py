"""Production programming: one-click flow, serial number / UID injection, CSV log."""

from __future__ import annotations

import csv
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from etools.core.fw_image import SparseImage
from etools.logger import get_logger

log = get_logger("production")

SERIAL_FORMATS = ("u32le", "u32be", "u16le", "u64le", "ascii_dec", "ascii_hex", "bcd")
ERASE_MODES = ("sector", "chip")
CSV_FIELDS = (
    "time",
    "result",
    "serial",
    "uid",
    "firmware",
    "crc32",
    "duration_s",
    "steps",
    "error",
)


class ProductionError(RuntimeError):
    """A production step failed."""


@dataclass
class SerialSpec:
    enabled: bool = False
    address: int = 0
    fmt: str = "u32le"
    width: int = 8  # digits for ascii / bcd formats
    prefix: str = ""
    start: int = 1
    step: int = 1

    def render(self, number: int) -> bytes:
        if number < 0:
            raise ProductionError("Serial number must not be negative")
        fmt = self.fmt
        if fmt == "u32le":
            return number.to_bytes(4, "little")
        if fmt == "u32be":
            return number.to_bytes(4, "big")
        if fmt == "u16le":
            return number.to_bytes(2, "little")
        if fmt == "u64le":
            return number.to_bytes(8, "little")
        if fmt in ("ascii_dec", "ascii_hex"):
            spec = "d" if fmt == "ascii_dec" else "X"
            digits = f"{number:0{self.width}{spec}}"
            if len(digits) > self.width:
                raise ProductionError(f"Serial {number} does not fit {self.width} characters")
            return (self.prefix + digits).encode("ascii")
        if fmt == "bcd":
            digits = f"{number:0{self.width}d}"
            if len(digits) > self.width:
                raise ProductionError(f"Serial {number} does not fit {self.width} BCD digits")
            if len(digits) % 2:
                digits = "0" + digits
            return bytes(int(digits[i]) << 4 | int(digits[i + 1]) for i in range(0, len(digits), 2))
        raise ProductionError(f"Unknown serial format: {fmt}")

    def text(self, number: int) -> str:
        if self.fmt == "ascii_hex":
            return f"{self.prefix}{number:0{self.width}X}"
        if self.fmt in ("ascii_dec", "bcd"):
            return f"{self.prefix}{number:0{self.width}d}"
        return str(number)

    @property
    def length(self) -> int:
        return len(self.render(0))


@dataclass
class UidSpec:
    enabled: bool = False
    address: int = 0


@dataclass
class ProductionPlan:
    firmware: str = ""
    bin_base: int = 0x0800_0000
    erase: str = "sector"
    incremental: bool = False
    verify: bool = True
    protect: bool = False
    run_after: bool = True
    serial: SerialSpec = field(default_factory=SerialSpec)
    uid: UidSpec = field(default_factory=UidSpec)
    log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductionPlan:
        data = dict(data or {})
        serial = SerialSpec(**_known(SerialSpec, data.pop("serial", {}) or {}))
        uid = UidSpec(**_known(UidSpec, data.pop("uid", {}) or {}))
        return cls(serial=serial, uid=uid, **_known(cls, data))

    def validate(self, image: SparseImage) -> None:
        if self.erase not in ERASE_MODES:
            raise ProductionError(f"Unknown erase mode: {self.erase}")
        if self.incremental and self.erase == "chip":
            raise ProductionError("Incremental programming needs sector erase")
        if self.serial.enabled:
            if self.serial.fmt not in SERIAL_FORMATS:
                raise ProductionError(f"Unknown serial format: {self.serial.fmt}")
            if self.serial.step == 0:
                raise ProductionError("Serial step must not be 0")
        spans: list[tuple[str, int, int]] = []
        if self.serial.enabled:
            spans.append(("serial", self.serial.address, self.serial.length))
        if self.uid.enabled:
            spans.append(("uid", self.uid.address, 12))
        if len(spans) == 2:
            (_, a, la), (_, b, lb) = spans
            if a < b + lb and b < a + la:
                raise ProductionError("Serial number and UID areas overlap")
        if image.empty:
            raise ProductionError("Firmware image is empty")


def _known(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    names = set(cls.__dataclass_fields__)
    return {k: v for k, v in data.items() if k in names}


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class ProductionResult:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    serial: int | None = None
    serial_text: str = ""
    uid_hex: str = ""
    crc32: int = 0
    started: str = ""
    duration_s: float = 0.0
    error: str = ""
    # The serial number reached the chip (programming succeeded), so it must
    # not be reused even if a later step (protect / run) failed.
    serial_consumed: bool = False

    def steps_text(self) -> str:
        return " ".join(f"{s.name}:{'ok' if s.ok else 'fail'}" for s in self.steps)


def build_image(
    base: SparseImage,
    plan: ProductionPlan,
    serial_no: int | None,
    uid: bytes,
) -> SparseImage:
    """Return a copy of the firmware with serial number / UID patched in."""
    image = base.copy()
    if plan.serial.enabled and serial_no is not None:
        image.write(plan.serial.address, plan.serial.render(serial_no))
    if plan.uid.enabled:
        if len(uid) != 12:
            raise ProductionError("Chip UID unavailable")
        image.write(plan.uid.address, uid)
    return image


class ProductionRunner:
    """Run the production steps against a FlashService-like object."""

    def __init__(
        self, service: Any, plan: ProductionPlan, image: SparseImage | None = None
    ) -> None:
        self.service = service
        self.plan = plan
        self.image = image if image is not None else SparseImage.from_file(
            plan.firmware, bin_base=plan.bin_base
        )
        plan.validate(self.image)

    def run(
        self,
        serial_no: int | None = None,
        *,
        cancelled: Callable[[], bool] | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> ProductionResult:
        plan = self.plan
        result = ProductionResult(ok=False, started=datetime.now().isoformat(timespec="seconds"))
        if plan.serial.enabled and serial_no is not None:
            result.serial = serial_no
            result.serial_text = plan.serial.text(serial_no)
        t_all = time.perf_counter()

        def step(name: str, fn: Callable[[], str]) -> None:
            if cancelled is not None and cancelled():
                raise ProductionError("Cancelled")
            if on_step is not None:
                on_step(name)
            t0 = time.perf_counter()
            try:
                detail = fn() or ""
            except Exception as exc:
                result.steps.append(StepResult(name, False, str(exc), time.perf_counter() - t0))
                raise
            result.steps.append(StepResult(name, True, detail, time.perf_counter() - t0))

        state: dict[str, Any] = {}

        def read_uid() -> str:
            uid = bytes(self.service.read_uid() or b"")
            state["uid"] = uid
            result.uid_hex = uid.hex().upper()
            if plan.uid.enabled and len(uid) != 12:
                raise ProductionError("Chip UID unavailable")
            return result.uid_hex

        def prepare() -> str:
            image = build_image(self.image, plan, serial_no, state.get("uid", b""))
            state["image"] = image
            result.crc32 = image.crc32()
            return f"{len(image)} bytes, CRC32 {result.crc32:08X}"

        def program() -> str:
            image: SparseImage = state["image"]
            res = self.service.program_segments(
                image.segments(),
                verify=plan.verify,
                erase=plan.erase,
                incremental=plan.incremental,
                label=Path(plan.firmware).name or "image",
            )
            if not res.ok:
                raise ProductionError(res.message)
            result.serial_consumed = result.serial is not None
            return res.message

        def protect() -> str:
            snap = self.service.read_option_bytes()
            if snap.rdp_level >= 1:
                return "already protected"
            res = self.service.write_option_bytes({"RDP": snap.family.rdp_l1})
            if not res.ok:
                raise ProductionError(res.message)
            return res.message

        def run_target() -> str:
            res = self.service.reset_target(halt=False)
            if not res.ok:
                raise ProductionError(res.message)
            return res.message

        try:
            step("uid", read_uid)
            step("prepare", prepare)
            step("program", program)
            if plan.protect:
                step("protect", protect)
            if plan.run_after:
                step("run", run_target)
            result.ok = True
        except Exception as exc:
            result.error = str(exc)
            log.warning("production failed: %s", exc)
        result.duration_s = time.perf_counter() - t_all
        if plan.log_path:
            try:
                append_csv(plan.log_path, plan, result)
            except OSError as exc:
                log.warning("production log write failed: %s", exc)
                if result.ok:
                    result.error = f"log not written: {exc}"
        return result


def append_csv(path: str | Path, plan: ProductionPlan, result: ProductionResult) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.exists() or p.stat().st_size == 0
    with p.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "time": result.started,
                "result": "PASS" if result.ok else "FAIL",
                "serial": result.serial_text,
                "uid": result.uid_hex,
                "firmware": Path(plan.firmware).name,
                "crc32": f"{result.crc32:08X}" if result.crc32 else "",
                "duration_s": f"{result.duration_s:.2f}",
                "steps": result.steps_text(),
                "error": result.error,
            }
        )
