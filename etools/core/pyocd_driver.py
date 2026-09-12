"""pyOCD backend driver.

Uses pyOCD's Python API to discover probes (ST-Link / J-Link / CMSIS-DAP),
open a debug session, and perform flash program / erase / read / verify.
Emits structured ProgressInfo events for UI progress bars.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from etools.core.models import (
    PROBE_CLASS_MAP,
    STM32_IDCODE_ADDR,
    STM32_UID_CANDIDATES,
    ConnectionState,
    OperationResult,
    ProbeInfo,
    ProbeType,
    ProgressInfo,
    ProgressStage,
    TargetDetails,
    TargetInfo,
)
from etools.core.probe import ProbeDriver
from etools.logger import get_logger

log = get_logger("pyocd")


def _probe_type_from_unique_id(unique_id: str, product_name: str = "") -> ProbeType:
    uid = (unique_id or "").lower()
    product = (product_name or "").lower()
    blob = f"{uid} {product}"
    if "stlink" in blob or "st-link" in blob:
        return ProbeType.STLINK
    if "jlink" in blob or "j-link" in blob:
        return ProbeType.JLINK
    if "cmsis" in blob or "daplink" in blob or "dap-link" in blob:
        return ProbeType.CMSIS_DAP
    return ProbeType.UNKNOWN


def _looks_like_valid_uid(raw: bytes) -> bool:
    """STM32 UID is 12 bytes; reject all-zero / all-FF / clearly empty reads."""
    if len(raw) < 9:
        return False
    if all(b == 0x00 for b in raw) or all(b == 0xFF for b in raw):
        return False
    # At least half the bytes should be non-trivial
    nonzero = sum(1 for b in raw if b not in (0x00, 0xFF))
    return nonzero >= len(raw) // 2


class PyOCDDriver(ProbeDriver):
    """Drive MCU operations through pyOCD sessions."""

    def __init__(self) -> None:
        super().__init__()
        self._session: Any = None
        self._probe: Optional[ProbeInfo] = None
        self._target: Optional[TargetInfo] = None
        self._details: Optional[TargetDetails] = None

    @property
    def session(self) -> Any:
        """Active pyOCD Session or None."""
        return self._session if self.connected else None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[ProbeInfo]:
        """Enumerate connected probes via pyOCD ConnectHelper."""
        try:
            from pyocd.core.helpers import ConnectHelper
        except ImportError as exc:
            self._emit(f"pyOCD not installed: {exc}", True)
            return []

        found: list[ProbeInfo] = []
        try:
            probes = ConnectHelper.get_all_connected_probes(
                blocking=False, print_wait_message=False
            )
        except Exception as exc:
            log.exception("probe scan failed")
            self._emit(f"Probe scan failed: {exc}", True)
            return found

        for p in probes:
            unique_id = str(getattr(p, "unique_id", "") or "")
            product = str(getattr(p, "product_name", "") or "")
            vendor = str(getattr(p, "vendor_name", "") or "")
            board = str(getattr(p, "board_name", "") or "")
            probe_type = ProbeType.UNKNOWN
            class_name = type(p).__name__.lower()
            for key, ptype in PROBE_CLASS_MAP.items():
                if key in class_name:
                    probe_type = ptype
                    break
            if probe_type is ProbeType.UNKNOWN:
                probe_type = _probe_type_from_unique_id(unique_id, product)

            found.append(
                ProbeInfo(
                    probe_type=probe_type,
                    unique_id=unique_id,
                    product_name=product,
                    vendor_name=vendor,
                    board_name=board,
                )
            )

        self._emit(f"Found {len(found)} probe(s)")
        return found

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, probe: ProbeInfo, target: TargetInfo) -> OperationResult:
        if self.connected:
            self.disconnect()

        self._set_state(ConnectionState.CONNECTING)
        self._details = None
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.CONNECT,
                percent=0,
                message=f"Connecting {probe.display_name} → {target.target_override} …",
            )
        )

        try:
            from pyocd.core.helpers import ConnectHelper
        except ImportError as exc:
            self._set_state(ConnectionState.ERROR)
            return OperationResult(ok=False, message=f"pyOCD not available: {exc}")

        options: dict[str, Any] = {
            "target_override": target.target_override,
            "connect_mode": target.connect_mode,
            "resume_on_disconnect": True,
            "hide_programming_progress": True,
            "no_config": True,
        }
        # Optional pyOCD knobs from the probe panel
        if target.frequency_hz and target.frequency_hz > 0:
            options["frequency"] = int(target.frequency_hz)
        protocol = (target.wire_protocol or "auto").lower()
        if protocol in ("swd", "jtag"):
            options["protocol"] = protocol
        reset_type = (target.reset_type or "default").lower()
        if reset_type and reset_type != "default":
            options["reset_type"] = reset_type

        t0 = time.perf_counter()
        try:
            session = ConnectHelper.session_with_chosen_probe(
                blocking=False,
                return_first=True,
                unique_id=probe.unique_id or None,
                auto_open=True,
                options=options,
            )
        except Exception as exc:
            self._set_state(ConnectionState.ERROR)
            msg = f"Connect failed: {exc}"
            log.exception("connect failed")
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=msg)

        if session is None:
            self._set_state(ConnectionState.ERROR)
            msg = "No matching probe found (device unplugged?)"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=msg)

        try:
            if not session.is_open:
                session.open()
        except Exception as exc:
            try:
                session.close()
            except Exception:
                pass
            self._set_state(ConnectionState.ERROR)
            msg = f"Session open failed: {exc}"
            log.exception("session open failed")
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=msg)

        dur = time.perf_counter() - t0
        self._session = session
        self._probe = probe
        self._target = target
        self._set_state(ConnectionState.CONNECTED)

        self.emit_progress(
            ProgressInfo(stage=ProgressStage.CONNECT, percent=50, message="Reading target info …")
        )
        details = self.get_target_details()
        self._details = details

        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Connected ({dur:.2f}s) {details.summary_line()}",
            )
        )
        return OperationResult(
            ok=True,
            message=f"Connected to {target.target_override}",
            duration_s=dur,
            detail=details.summary_line(),
            data=details,
        )

    def disconnect(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                log.exception("session close error")
        self._details = None
        self._set_state(ConnectionState.DISCONNECTED)
        self._emit("Disconnected")

    # ------------------------------------------------------------------
    # Target details
    # ------------------------------------------------------------------

    def get_target_details(self) -> TargetDetails:
        """Read UID / flash map / voltage / IDs from the live session."""
        session = self._require_session()
        details = TargetDetails()

        # --- probe ---
        probe = getattr(session, "probe", None)
        if probe is not None:
            details.probe_name = str(getattr(probe, "product_name", "") or "")
            details.probe_type = type(probe).__name__
            wire = getattr(probe, "wire_protocol", None)
            details.wire_protocol = str(wire) if wire is not None else ""

        # --- target class / CPU ---
        target = session.target
        details.target_name = self._target.target_override if self._target else ""
        details.cpu = str(getattr(target, "core_name", "") or "")
        details.core_name = details.cpu
        vendor = getattr(type(target), "VENDOR", None) or getattr(target, "VENDOR", None)
        if vendor:
            details.vendor = str(vendor)
        part = getattr(target, "product_name", None) or getattr(target, "part_number", None)
        if part:
            details.target_name = str(part)

        # --- memory map ---
        try:
            mm = target.get_memory_map()
            if mm is not None:
                for region in mm.regions:
                    rtype = str(getattr(region, "type", "") or "")
                    # Flash
                    if "FLASH" in rtype.upper() or type(region).__name__ == "FlashRegion":
                        if details.flash_size == 0 or getattr(region, "is_boot_memory", False):
                            details.flash_base = int(region.start)
                            details.flash_size = int(region.length)
                    # RAM (prefer first non-empty RAM in SRAM range)
                    if "RAM" in rtype.upper() and details.ram_size == 0:
                        # skip giant default map placeholders of 512MiB
                        if region.length <= 0x200_0000:
                            details.ram_base = int(region.start)
                            details.ram_size = int(region.length)
        except Exception:
            log.debug("memory map unavailable", exc_info=True)

        # Fallback RAM/flash from our TargetInfo selection
        if self._target:
            if details.flash_base == 0:
                details.flash_base = self._target.flash_base
            if details.flash_size == 0:
                details.flash_size = self._target.flash_size
            if details.ram_base == 0:
                details.ram_base = self._target.ram_base
            if details.ram_size == 0:
                details.ram_size = self._target.ram_size
            if not details.cpu:
                details.cpu = self._target.cpu

        # --- STM32 device ID + UID ---
        details.device_id = self._read_stm32_device_id(target)
        uid = self._read_stm32_uid(target)
        if uid:
            details.uid = uid
            details.uid_ok = True

        # --- voltage (ST-Link) ---
        voltage = self._read_target_voltage(probe)
        if voltage is not None:
            details.voltage = voltage
            details.voltage_ok = True

        return details

    def _read_word(self, target: Any, addr: int) -> Optional[int]:
        try:
            return int(target.read_memory(addr)) & 0xFFFFFFFF
        except Exception:
            return None

    def _read_bytes(self, target: Any, addr: int, n: int) -> Optional[bytes]:
        try:
            return bytes(target.read_memory_block8(addr, n))
        except Exception:
            return None

    def _read_stm32_device_id(self, target: Any) -> str:
        word = self._read_word(target, STM32_IDCODE_ADDR)
        if word is None or word == 0 or word == 0xFFFFFFFF:
            return ""
        dev_id = word & 0xFFF
        rev = (word >> 16) & 0xFFFF
        return f"0x{dev_id:03X} (rev 0x{rev:04X})"

    def _read_stm32_uid(self, target: Any) -> str:
        for addr in STM32_UID_CANDIDATES:
            raw = self._read_bytes(target, addr, 12)
            if raw and _looks_like_valid_uid(raw):
                return raw.hex().upper()
        return ""

    def _read_target_voltage(self, probe: Any) -> Optional[float]:
        """Best-effort target voltage. ST-Link exposes get_target_voltage()."""
        if probe is None:
            return None
        # StlinkProbe wraps an Stlink object as ._link
        link = getattr(probe, "_link", None)
        if link is None:
            return None
        getter = getattr(link, "get_target_voltage", None)
        if not callable(getter):
            return None
        try:
            getter()
            v = getattr(link, "target_voltage", None)
            if v is None:
                return None
            return float(v)
        except Exception:
            log.debug("voltage read failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def erase(self, full_chip: bool = True) -> OperationResult:
        session = self._require_session()
        self.emit_progress(
            ProgressInfo(stage=ProgressStage.ERASE, percent=-1, message="Erasing flash …")
        )
        t0 = time.perf_counter()
        try:
            from pyocd.flash.eraser import FlashEraser

            mode = FlashEraser.Mode.MASS if full_chip else FlashEraser.Mode.SECTOR
            FlashEraser(session, mode).erase()
        except Exception as exc:
            log.exception("erase failed")
            msg = f"Erase failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=str(exc))

        dur = time.perf_counter() - t0
        self.emit_progress(
            ProgressInfo(stage=ProgressStage.DONE, percent=100, message=f"Erase done ({dur:.2f}s)")
        )
        return OperationResult(ok=True, message="Erase complete", duration_s=dur)

    def program(self, firmware_path: str, verify: bool = True) -> OperationResult:
        session = self._require_session()
        path = Path(firmware_path)
        if not path.exists():
            return OperationResult(ok=False, message=f"Firmware not found: {path}")

        size = path.stat().st_size
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.PROGRAM,
                percent=0,
                message=f"Programming {path.name} ({size:,} bytes) …",
                bytes_total=size,
            )
        )
        t0 = time.perf_counter()
        last = {"pct": -1}

        def _progress(value: int | float) -> None:
            # pyOCD FileProgrammer reports 0.0–1.0
            frac = float(value)
            if frac > 1.0:
                frac = frac / 100.0
            pct = max(0, min(100, int(frac * 100)))
            # throttle to 1% steps
            if pct != last["pct"]:
                last["pct"] = pct
                done = int(size * frac)
                self.emit_progress(
                    ProgressInfo(
                        stage=ProgressStage.PROGRAM,
                        percent=pct,
                        message=f"Program {pct}%",
                        bytes_done=done,
                        bytes_total=size,
                    )
                )

        try:
            from pyocd.flash.file_programmer import FileProgrammer

            programmer = FileProgrammer(
                session,
                progress=_progress,
                chip_erase=None,
                smart_flash=True,
                trust_crc=None,
            )
            programmer.program(str(path.resolve()))
        except Exception as exc:
            log.exception("program failed")
            msg = f"Program failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=str(exc))

        dur = time.perf_counter() - t0
        if verify:
            self.emit_progress(
                ProgressInfo(
                    stage=ProgressStage.VERIFY,
                    percent=0,
                    message="Verifying …",
                    bytes_total=size,
                )
            )
            v = self.verify(str(path))
            if not v.ok:
                self.emit_progress(
                    ProgressInfo(
                        stage=ProgressStage.ERROR,
                        percent=0,
                        message=f"Program done but verify failed ({dur:.2f}s)",
                        is_error=True,
                    )
                )
                return OperationResult(
                    ok=False,
                    message=f"Verify failed: {v.message}",
                    duration_s=dur,
                    bytes_processed=size,
                    detail=v.detail,
                )

        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Program done ({dur:.2f}s)",
                bytes_done=size,
                bytes_total=size,
            )
        )
        return OperationResult(
            ok=True,
            message=f"Programmed {path.name}",
            duration_s=dur,
            bytes_processed=size,
        )

    def read_memory_bytes(self, address: int, size: int) -> bytes:
        """Read a memory region into bytes (chunked, with progress)."""
        session = self._require_session()
        if size <= 0 or size > 16 * 1024 * 1024:
            raise ValueError("Invalid read size (1 … 16 MiB)")
        target = session.target
        chunk = 4096
        data = bytearray()
        remaining = size
        addr = address
        last = -1
        while remaining > 0:
            n = min(chunk, remaining)
            data.extend(target.read_memory_block8(addr, n))
            addr += n
            remaining -= n
            pct = int((size - remaining) * 100 / size)
            if pct != last:
                last = pct
                self.emit_progress(
                    ProgressInfo(
                        stage=ProgressStage.READ,
                        percent=pct,
                        message=f"Read {pct}%",
                        bytes_done=size - remaining,
                        bytes_total=size,
                    )
                )
        return bytes(data)

    def read(self, address: int, size: int, out_path: str) -> OperationResult:
        session = self._require_session()
        if size <= 0 or size > 16 * 1024 * 1024:
            return OperationResult(ok=False, message="Invalid read size (1 … 16 MiB)")

        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.READ,
                percent=0,
                message=f"Reading 0x{address:08X} + {size:,} bytes …",
                bytes_total=size,
            )
        )
        t0 = time.perf_counter()
        try:
            data = self.read_memory_bytes(address, size)
            Path(out_path).write_bytes(data)
        except Exception as exc:
            log.exception("read failed")
            msg = f"Read failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=str(exc))

        dur = time.perf_counter() - t0
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Read done ({dur:.2f}s)",
                bytes_done=size,
                bytes_total=size,
            )
        )
        return OperationResult(
            ok=True,
            message=f"Wrote {out_path}",
            duration_s=dur,
            bytes_processed=size,
        )

    def verify(self, firmware_path: str) -> OperationResult:
        session = self._require_session()
        path = Path(firmware_path)
        if not path.exists():
            return OperationResult(ok=False, message=f"Firmware not found: {path}")

        self.emit_progress(
            ProgressInfo(stage=ProgressStage.VERIFY, percent=-1, message=f"Verifying {path.name} …")
        )
        t0 = time.perf_counter()
        try:
            ok, detail = self._verify_image(session, path)
        except Exception as exc:
            log.exception("verify failed")
            msg = f"Verify failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return OperationResult(ok=False, message=str(exc))

        dur = time.perf_counter() - t0
        if ok:
            self.emit_progress(
                ProgressInfo(
                    stage=ProgressStage.DONE, percent=100, message=f"Verify OK ({dur:.2f}s)"
                )
            )
            return OperationResult(ok=True, message="Verify OK", duration_s=dur, detail=detail)
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.ERROR,
                percent=0,
                message=f"Verify mismatch ({dur:.2f}s)",
                is_error=True,
            )
        )
        return OperationResult(
            ok=False, message=detail or "Verify failed", duration_s=dur, detail=detail
        )

    def _verify_image(self, session: Any, path: Path) -> tuple[bool, str]:
        """Compare flash against the file's address/data segments."""
        segments = self._load_image_segments(path)
        if not segments:
            return False, "No loadable segments in image"

        target = session.target
        compared = 0
        total = sum(len(d) for _, d in segments)
        for addr, expected in segments:
            actual = bytes(target.read_memory_block8(addr, len(expected)))
            if actual != expected:
                for i, (a, e) in enumerate(zip(actual, expected)):
                    if a != e:
                        return False, (
                            f"Mismatch at 0x{addr + i:08X}: "
                            f"expected 0x{e:02X}, got 0x{a:02X}"
                        )
                return False, f"Mismatch in segment 0x{addr:08X} (len {len(expected)})"
            compared += len(expected)
            pct = int(compared * 100 / total) if total else 100
            self.emit_progress(
                ProgressInfo(
                    stage=ProgressStage.VERIFY,
                    percent=pct,
                    message=f"Verify {pct}%",
                    bytes_done=compared,
                    bytes_total=total,
                )
            )
        return True, f"Verified {compared} bytes in {len(segments)} segment(s)"

    def _load_image_segments(self, path: Path) -> list[tuple[int, bytes]]:
        """Parse firmware file into (base_address, data) segments."""
        suffix = path.suffix.lower()
        data = path.read_bytes()

        if suffix == ".hex":
            return self._parse_hex(data.decode("ascii", errors="replace"))
        if suffix in (".elf", ".axf"):
            return self._parse_elf(path)
        if suffix == ".srec":
            return self._parse_srec(data.decode("ascii", errors="replace"))
        base = self._target.flash_base if self._target else 0x0800_0000
        return [(base, data)]

    def _parse_hex(self, text: str) -> list[tuple[int, bytes]]:
        segments: list[tuple[int, bytes]] = []
        base = 0
        current_addr: Optional[int] = None
        buf = bytearray()

        def flush() -> None:
            nonlocal current_addr, buf
            if current_addr is not None and buf:
                segments.append((current_addr, bytes(buf)))
            current_addr = None
            buf = bytearray()

        for line in text.splitlines():
            line = line.strip()
            if not line.startswith(":"):
                continue
            raw = bytes.fromhex(line[1:])
            length, addr_hi, addr_lo, rtype = raw[0], raw[1], raw[2], raw[3]
            addr = (addr_hi << 8) | addr_lo
            payload = raw[4 : 4 + length]
            if rtype == 0x00:
                abs_addr = base + addr
                if current_addr is None or abs_addr != current_addr + len(buf):
                    flush()
                    current_addr = abs_addr
                buf.extend(payload)
            elif rtype == 0x04:
                flush()
                base = int.from_bytes(payload, "big") << 16
            elif rtype == 0x02:
                flush()
                base = int.from_bytes(payload, "big") << 4
            elif rtype == 0x01:
                flush()
                break
            else:
                flush()
        flush()
        return segments

    def _parse_srec(self, text: str) -> list[tuple[int, bytes]]:
        segments: list[tuple[int, bytes]] = []
        current_addr: Optional[int] = None
        buf = bytearray()

        def flush() -> None:
            nonlocal current_addr, buf
            if current_addr is not None and buf:
                segments.append((current_addr, bytes(buf)))
            current_addr = None
            buf = bytearray()

        for line in text.splitlines():
            line = line.strip()
            if not line or line[0] != "S":
                continue
            rtype = line[1]
            if rtype == "0":
                continue
            if rtype in ("7", "8", "9"):
                flush()
                break
            if rtype not in ("1", "2", "3"):
                continue
            raw = bytes.fromhex(line[2:])
            count = raw[0]
            if rtype == "1":
                addr = int.from_bytes(raw[1:3], "big")
                payload = raw[3:count]
            elif rtype == "2":
                addr = int.from_bytes(raw[1:4], "big")
                payload = raw[4:count]
            else:
                addr = int.from_bytes(raw[1:5], "big")
                payload = raw[5:count]
            if current_addr is None or addr != current_addr + len(buf):
                flush()
                current_addr = addr
            buf.extend(payload)
        flush()
        return segments

    def _parse_elf(self, path: Path) -> list[tuple[int, bytes]]:
        try:
            from elftools.elf.elffile import ELFFile
        except ImportError as exc:
            raise RuntimeError("pyelftools is required for ELF verify") from exc

        segments: list[tuple[int, bytes]] = []
        with path.open("rb") as f:
            elf = ELFFile(f)
            for seg in elf.iter_segments():
                if seg["p_type"] != "PT_LOAD":
                    continue
                data = seg.data()
                if not data:
                    continue
                segments.append((seg["p_paddr"], data))
        return segments

    def reset(self, halt: bool = False) -> OperationResult:
        session = self._require_session()
        try:
            target = session.target
            if halt:
                target.reset_and_halt()
                self._emit("Reset + halt")
                return OperationResult(ok=True, message="Reset and halted")
            target.reset()
            self._emit("Reset")
            return OperationResult(ok=True, message="Target reset")
        except Exception as exc:
            log.exception("reset failed")
            self._emit(f"Reset failed: {exc}", True)
            return OperationResult(ok=False, message=str(exc))

    def _require_session(self):
        if self._session is None or not self.connected:
            raise RuntimeError("Not connected to a target")
        return self._session
