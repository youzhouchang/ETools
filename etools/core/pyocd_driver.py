"""pyOCD backend driver.

Uses pyOCD's Python API to discover probes (ST-Link / J-Link / CMSIS-DAP),
open a debug session, and perform flash program / erase / read / verify.
Emits structured ProgressInfo events for UI progress bars.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from etools.core.hexdump import parse_elf, parse_srec
from etools.core.models import (
    PROBE_CLASS_MAP,
    STM32_FLASHSIZE_CANDIDATES,
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
from etools.core.probe_errors import (
    ProbeDisconnected,
    ProbeOperationError,
    ProbeTargetAbsent,
    classify_probe_error,
    target_is_absent,
)
from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("pyocd")


def _direct_probe_backends() -> list[type[Any]]:
    """Return built-in pyOCD probe backends without relying on entry points."""
    backends: list[type[Any]] = []
    candidates = (
        ("pyocd.probe.stlink_probe", "StlinkProbe"),
        ("pyocd.probe.cmsis_dap_probe", "CMSISDAPProbe"),
        ("pyocd.probe.jlink_probe", "JLinkProbe"),
        ("pyocd.probe.picoprobe", "Picoprobe"),
    )
    for module_name, class_name in candidates:
        try:
            module = __import__(module_name, fromlist=[class_name])
            backends.append(getattr(module, class_name))
        except Exception:
            log.debug("probe backend unavailable: %s", module_name, exc_info=True)
    return backends


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
        self._probe: ProbeInfo | None = None
        self._target: TargetInfo | None = None
        self._details: TargetDetails | None = None
        # Optional CMSIS FLM attached as an extra flash region after connect.
        self.ext_flm_path: str = ""
        self.ext_flash_info: Any = None

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
            probes = list(
                ConnectHelper.get_all_connected_probes(
                    blocking=False, print_wait_message=False
                )
            )
        except Exception as exc:
            log.exception("probe scan failed")
            probes = []
            self._emit(f"Primary probe scan failed: {exc}", True)

        # Frozen builds can lose distribution entry points used by pyOCD to
        # register probe plugins. Scan every built-in USB backend directly.
        if not probes:
            seen: set[tuple[type[Any], str]] = set()
            for backend in _direct_probe_backends():
                try:
                    candidates = backend.get_all_connected_probes()
                except Exception:
                    log.debug(
                        "fallback scan failed for %s",
                        backend.__name__,
                        exc_info=True,
                    )
                    continue
                for probe in candidates:
                    key = (type(probe), str(getattr(probe, "unique_id", "") or id(probe)))
                    if key not in seen:
                        seen.add(key)
                        probes.append(probe)

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
            return self._fail(f"pyOCD not available: {exc}", exc)

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
            return self._fail(msg, exc)

        if session is None:
            self._set_state(ConnectionState.ERROR)
            msg = "No matching probe found (device unplugged?)"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(msg)

        try:
            if not session.is_open:
                session.open()
        except Exception as exc:
            try:
                session.close()
            except Exception:
                pass
            self._set_state(ConnectionState.ERROR)
            if target_is_absent(exc):
                msg = tr("probe.no_mcu")
                log.warning("target did not answer: %s", exc)
                self.emit_progress(
                    ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
                )
                return self._fail(msg, ProbeTargetAbsent(str(exc)))
            msg = f"Session open failed: {exc}"
            log.exception("session open failed")
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(msg, exc)

        dur = time.perf_counter() - t0
        self._session = session
        self._probe = probe
        self._target = target
        self._set_state(ConnectionState.CONNECTED)
        self._attach_ext_flash(session)

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

    def _attach_ext_flash(self, session: Any) -> None:
        self.ext_flash_info = None
        if not self.ext_flm_path:
            return
        from etools.core.ext_flash import attach_flm

        try:
            self.ext_flash_info = attach_flm(session.target, self.ext_flm_path)
            self._emit(f"External flash: {self.ext_flash_info.summary()}")
        except Exception as exc:
            log.warning("FLM attach failed: %s", exc)
            self._emit(f"External flash algorithm not attached: {exc}", True)

    def set_external_flm(self, path: str) -> Any:
        """Remember the FLM path; attach (or detach) it on the live session."""
        from etools.core.ext_flash import detach_flm

        self.ext_flm_path = str(path or "")
        session = self.session
        if session is None:
            if self.ext_flm_path:
                from etools.core.ext_flash import inspect_flm

                return inspect_flm(self.ext_flm_path)
            return None
        if not self.ext_flm_path:
            detach_flm(session.target)
            self.ext_flash_info = None
            return None
        from etools.core.ext_flash import attach_flm

        self.ext_flash_info = attach_flm(session.target, self.ext_flm_path)
        return self.ext_flash_info

    def reconnect(self, attempts: int = 6, delay: float = 0.5) -> OperationResult:
        """Re-open the last probe/target pair (e.g. after an option-byte reload)."""
        probe, target = self._probe, self._target
        if probe is None or target is None:
            return self._fail("Nothing to reconnect")
        self.disconnect()
        result = self._fail("Reconnect failed")
        for _ in range(max(1, attempts)):
            time.sleep(delay)
            result = self.connect(probe, target)
            if result.ok:
                return result
        return result

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
                    length = int(getattr(region, "length", 0) or 0)
                    # Skip empty and giant default Cortex-M placeholders (512 MiB)
                    if length <= 0 or length > 0x1000_0000:
                        continue
                    is_flash = bool(getattr(region, "is_flash", False)) or (
                        type(region).__name__ == "FlashRegion"
                    )
                    is_ram = bool(getattr(region, "is_ram", False)) or (
                        type(region).__name__ == "RamRegion"
                    )
                    if is_flash:
                        boot = bool(getattr(region, "is_boot_memory", False))
                        if details.flash_size == 0 or boot:
                            details.flash_base = int(region.start)
                            details.flash_size = length
                    elif is_ram:
                        if details.ram_size == 0 or length > details.ram_size:
                            details.ram_base = int(region.start)
                            details.ram_size = length
        except Exception:
            log.debug("memory map unavailable", exc_info=True)

        # Fallback sizes from the pyOCD built-in target class MEMORY_MAP
        if details.flash_size == 0 or details.ram_size == 0:
            self._fill_sizes_from_builtin_map(details)

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

        # STM32 has no single readable Device ID or RAM-size register.
        # UID and the flash-size register are the chip values we can trust.
        uid = self._read_stm32_uid(target)
        if uid:
            details.uid = uid
            details.uid_ok = True

        # Chip-side flash size (works even with generic/default memory maps)
        if details.flash_size == 0:
            chip_flash = self._read_stm32_flash_size(target)
            if chip_flash:
                details.flash_size = chip_flash
                if details.flash_base == 0:
                    details.flash_base = 0x0800_0000

        # --- voltage (ST-Link) ---
        voltage = self._read_target_voltage(probe)
        if voltage is not None:
            details.voltage = voltage
            details.voltage_ok = True

        return details

    def _read_bytes(self, target: Any, addr: int, n: int) -> bytes | None:
        try:
            return bytes(target.read_memory_block8(addr, n))
        except Exception:
            return None

    def _read_stm32_uid(self, target: Any) -> str:
        for addr in STM32_UID_CANDIDATES:
            raw = self._read_bytes(target, addr, 12)
            if raw and _looks_like_valid_uid(raw):
                return raw.hex().upper()
        return ""

    def _fill_sizes_from_builtin_map(self, details: TargetDetails) -> None:
        """Fill missing flash/RAM sizes from the pyOCD built-in target definition."""
        name = (self._target.target_override if self._target else "") or ""
        if not name:
            return
        try:
            from pyocd.target.builtin import BUILTIN_TARGETS

            cls = BUILTIN_TARGETS.get(name)
            mm = getattr(cls, "MEMORY_MAP", None) if cls is not None else None
            if mm is None:
                return
            for region in mm.regions:
                length = int(getattr(region, "length", 0) or 0)
                if length <= 0 or length > 0x1000_0000:
                    continue
                is_flash = bool(getattr(region, "is_flash", False))
                is_ram = bool(getattr(region, "is_ram", False))
                if is_flash and details.flash_size == 0:
                    details.flash_base = int(region.start)
                    details.flash_size = length
                elif is_ram and (details.ram_size == 0 or length > details.ram_size):
                    details.ram_base = int(region.start)
                    details.ram_size = length
        except Exception:
            log.debug("builtin memory map fallback failed", exc_info=True)

    def _read_stm32_flash_size(self, target: Any) -> int:
        """Read STM32 flash-size system register (16-bit, size in KB). Returns bytes."""
        for addr in STM32_FLASHSIZE_CANDIDATES:
            raw = self._read_bytes(target, addr, 2)
            if not raw or len(raw) < 2:
                continue
            kb = int.from_bytes(raw[:2], "little")
            if 4 <= kb <= 4096:  # 4 KiB .. 4 MiB
                return kb * 1024
        return 0

    def _read_target_voltage(self, probe: Any) -> float | None:
        """Best-effort target voltage. ST-Link exposes get_target_voltage()."""
        if probe is None:
            return None
        # StlinkProbe wraps an Stlink object as ._link; also try the probe itself
        for obj in (getattr(probe, "_link", None), probe):
            if obj is None:
                continue
            getter = getattr(obj, "get_target_voltage", None)
            if not callable(getter):
                continue
            try:
                v = getter()
                if v is None:
                    v = getattr(obj, "target_voltage", None)
                if v is None:
                    continue
                v = float(v)
                # pyOCD ST-Link reports volts; guard against mV-scale values
                if v > 20:
                    v = v / 1000.0
                if 0.5 <= v <= 6.0:
                    return v
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

            from etools.core.ext_flash import suspended

            mode = FlashEraser.Mode.MASS if full_chip else FlashEraser.Mode.SECTOR
            with suspended(session.target):
                FlashEraser(session, mode).erase()
        except Exception as exc:
            log.exception("erase failed")
            msg = f"Erase failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(str(exc), exc)

        dur = time.perf_counter() - t0
        self.emit_progress(
            ProgressInfo(stage=ProgressStage.DONE, percent=100, message=f"Erase done ({dur:.2f}s)")
        )
        return OperationResult(ok=True, message="Erase complete", duration_s=dur)

    def erase_range(self, address: int, size: int) -> OperationResult:
        """Erase flash blocks covering [address, address+size)."""
        session = self._require_session()
        if size <= 0:
            return self._fail("Invalid erase range")
        start = int(address)
        end = start + int(size)
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.ERASE,
                percent=-1,
                message=f"Erasing 0x{start:08X}+{size} …",
            )
        )
        t0 = time.perf_counter()
        try:
            target = session.target
            flash = target.flash
            flash.init()
            try:
                # Align to erase blocks (page/sector) via the flash builder API.
                flash.erase_block(start, end)
            finally:
                flash.cleanup()
        except Exception as exc:
            log.exception("range erase failed")
            self.emit_progress(
                ProgressInfo(
                    stage=ProgressStage.ERROR, percent=0, message=str(exc), is_error=True
                )
            )
            return self._fail(str(exc), exc)
        dur = time.perf_counter() - t0
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Range erase done ({dur:.2f}s)",
            )
        )
        return OperationResult(
            ok=True,
            message=f"Range erase complete (0x{start:08X}+{size})",
            duration_s=dur,
        )

    def _progress_reporter(self, stage: ProgressStage, size: int, label: str):
        last = {"pct": -1}

        def _progress(value: int | float) -> None:
            # pyOCD loaders report 0.0–1.0
            frac = float(value)
            if frac > 1.0:
                frac = frac / 100.0
            pct = max(0, min(100, int(frac * 100)))
            if pct != last["pct"]:
                last["pct"] = pct
                self.emit_progress(
                    ProgressInfo(
                        stage=stage,
                        percent=pct,
                        message=f"{label} {pct}%",
                        bytes_done=int(size * frac),
                        bytes_total=size,
                    )
                )

        return _progress

    def program(
        self, firmware_path: str, verify: bool = True, incremental: bool = False
    ) -> OperationResult:
        session = self._require_session()
        path = Path(firmware_path)
        if not path.exists():
            return self._fail(f"Firmware not found: {path}")

        size = path.stat().st_size
        mode = " (incremental)" if incremental else ""
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.PROGRAM,
                percent=0,
                message=f"Programming {path.name}{mode} ({size:,} bytes) …",
                bytes_total=size,
            )
        )
        t0 = time.perf_counter()
        try:
            from pyocd.flash.file_programmer import FileProgrammer

            if incremental:
                # Smart flash compares against what it reads back; make sure
                # that read hits the device and not pyOCD's memory cache.
                self._prepare_fresh_flash_read(session)
            programmer = FileProgrammer(
                session,
                progress=self._progress_reporter(ProgressStage.PROGRAM, size, "Program"),
                chip_erase="sector" if incremental else None,
                smart_flash=bool(incremental),
                trust_crc=False,
            )
            programmer.program(str(path.resolve()))
        except Exception as exc:
            log.exception("program failed")
            msg = f"Program failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(str(exc), exc)

        dur = time.perf_counter() - t0
        if verify:
            failed = self._verify_after_program(lambda: self.verify(str(path)), dur, size)
            if failed is not None:
                return failed
        return self._program_done(f"Programmed {path.name}{mode}", dur, size)

    def program_segments(
        self,
        segments: list[tuple[int, bytes]],
        *,
        verify: bool = True,
        erase: str = "sector",
        incremental: bool = False,
        label: str = "image",
    ) -> OperationResult:
        """Program in-memory (address, data) segments through pyOCD's MemoryLoader."""
        session = self._require_session()
        segments = [(int(a), bytes(d)) for a, d in segments if d]
        if not segments:
            return self._fail("Image has no data")
        size = sum(len(d) for _, d in segments)
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.PROGRAM,
                percent=0,
                message=f"Programming {label} ({size:,} bytes, {erase} erase) …",
                bytes_total=size,
            )
        )
        t0 = time.perf_counter()
        try:
            from pyocd.flash.loader import MemoryLoader

            if incremental:
                self._prepare_fresh_flash_read(session)
            loader = MemoryLoader(
                session,
                progress=self._progress_reporter(ProgressStage.PROGRAM, size, "Program"),
                chip_erase="chip" if erase == "chip" else "sector",
                smart_flash=bool(incremental),
                trust_crc=False,
            )
            for addr, data in segments:
                loader.add_data(addr, data)
            loader.commit()
        except Exception as exc:
            log.exception("program segments failed")
            msg = f"Program failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(str(exc), exc)

        dur = time.perf_counter() - t0
        if verify:
            failed = self._verify_after_program(
                lambda: self.verify_segments(segments), dur, size
            )
            if failed is not None:
                return failed
        return self._program_done(f"Programmed {label}", dur, size)

    def _verify_after_program(self, run, dur: float, size: int) -> OperationResult | None:
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.VERIFY, percent=0, message="Verifying …", bytes_total=size
            )
        )
        v = run()
        if v.ok:
            return None
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

    def _program_done(self, message: str, dur: float, size: int) -> OperationResult:
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Program done ({dur:.2f}s)",
                bytes_done=size,
                bytes_total=size,
            )
        )
        return OperationResult(ok=True, message=message, duration_s=dur, bytes_processed=size)

    def verify_segments(self, segments: list[tuple[int, bytes]]) -> OperationResult:
        session = self._require_session()
        t0 = time.perf_counter()
        try:
            ok, detail = self._verify_segments(session, segments)
        except Exception as exc:
            log.exception("verify failed")
            return self._fail(f"Verify failed: {exc}", exc)
        dur = time.perf_counter() - t0
        if ok:
            return OperationResult(ok=True, message="Verify OK", duration_s=dur, detail=detail)
        return self._fail(detail or "Verify failed", duration_s=dur, detail=detail)

    def read_uid_bytes(self) -> bytes:
        """Raw 96-bit STM32 unique ID (empty when not available)."""
        target = self._require_session().target
        for addr in STM32_UID_CANDIDATES:
            raw = self._read_bytes(target, addr, 12)
            if raw and _looks_like_valid_uid(raw):
                return raw
        return b""

    def option_bytes(self) -> Any:
        from etools.core.option_bytes import OptionBytes

        return OptionBytes.detect(self._require_session().target)

    def after_option_write(self, reload: str) -> OperationResult:
        """Make new option bytes effective and refresh the session."""
        session = self._require_session()
        if reload == "obl":
            return self.reconnect()
        if reload == "reset":
            try:
                session.target.reset_and_halt()
            except Exception as exc:
                log.debug("reset after option write failed, reconnecting", exc_info=True)
                self._emit(f"Reset failed ({exc}); reconnecting", True)
                return self.reconnect()
        self._invalidate_memory_cache(session.target)
        return OperationResult(ok=True, message="Option bytes applied")

    def _invalidate_memory_cache(self, target: Any) -> None:
        """Drop pyOCD's cached memory so the next read hits the device."""
        cores: list[Any] = []
        selected = getattr(target, "selected_core_or_raise", None)
        if callable(selected):
            try:
                cores.append(selected())
            except Exception:
                log.debug("selected core unavailable", exc_info=True)
        for core in cores:
            context_getter = getattr(core, "get_target_context", None)
            if not callable(context_getter):
                continue
            try:
                context = context_getter()
            except Exception:
                log.debug("target context unavailable", exc_info=True)
                continue
            invalidate = getattr(context, "invalidate", None)
            if callable(invalidate):
                try:
                    invalidate()
                except Exception:
                    log.debug("memory cache invalidate failed", exc_info=True)

    def _prepare_fresh_flash_read(self, session: Any) -> None:
        """Reset and drop cached flash before a verify or post-erase read.

        The flash algorithm writes the device without updating pyOCD's memory
        cache. Some STM32 flash accelerators also keep returning the previous
        contents until the core is reset.
        """
        target = session.target
        try:
            target.reset_and_halt()
        except Exception:
            log.debug("reset before flash read failed", exc_info=True)
        self._invalidate_memory_cache(target)

    def read_memory_bytes(self, address: int, size: int, *, fresh: bool = False) -> bytes:
        """Read a memory region into bytes (chunked, with progress)."""
        session = self._require_session()
        if size <= 0 or size > 16 * 1024 * 1024:
            raise ValueError("Invalid read size (1 … 16 MiB)")
        if fresh:
            self._prepare_fresh_flash_read(session)
        else:
            self._invalidate_memory_cache(session.target)
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

    def fill_memory(self, address: int, size: int, value: int = 0xFF) -> OperationResult:
        """Fill a RAM region with a repeated byte (debugger write).

        Flash is intentionally rejected — programming flash needs erase+program.
        """
        session = self._require_session()
        if size <= 0 or size > 256 * 1024:
            return self._fail("Invalid fill size (1 … 256 KiB)")
        value = int(value) & 0xFF
        target = session.target
        if not self._region_is_ram(target, address, size):
            return self._fail(
                f"0x{address:08X}+{size:,} 不在 RAM 区域；"
                "填充仅支持 RAM，Flash 请用烧录流程"
            )

        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.PROGRAM,
                percent=0,
                message=f"Filling RAM 0x{address:08X} with 0x{value:02X} …",
                bytes_total=size,
            )
        )
        t0 = time.perf_counter()
        try:
            chunk = 4096
            block = bytes([value]) * chunk
            addr = address
            remaining = size
            last = -1
            while remaining > 0:
                n = min(chunk, remaining)
                target.write_memory_block8(addr, block[:n])
                addr += n
                remaining -= n
                pct = int((size - remaining) * 100 / size)
                if pct != last:
                    last = pct
                    self.emit_progress(
                        ProgressInfo(
                            stage=ProgressStage.PROGRAM,
                            percent=pct,
                            message=f"Fill {pct}%",
                            bytes_done=size - remaining,
                            bytes_total=size,
                        )
                    )
        except Exception as exc:
            log.exception("fill memory failed")
            msg = f"Fill failed: {exc}"
            self.emit_progress(
                ProgressInfo(stage=ProgressStage.ERROR, percent=0, message=msg, is_error=True)
            )
            return self._fail(str(exc), exc)

        dur = time.perf_counter() - t0
        self.emit_progress(
            ProgressInfo(
                stage=ProgressStage.DONE,
                percent=100,
                message=f"Filled {size:,} bytes with 0x{value:02X}",
                bytes_done=size,
                bytes_total=size,
            )
        )
        return OperationResult(
            ok=True,
            message=f"RAM 0x{address:08X} 已填充 {size:,} 字节（0x{value:02X}）",
            duration_s=dur,
            bytes_processed=size,
        )

    @staticmethod
    def _region_is_ram(target: Any, address: int, size: int) -> bool:
        mem_map = getattr(target, "memory_map", None)
        if mem_map is None:
            return False
        end = address + size
        try:
            regions = list(mem_map)
        except TypeError:
            return False
        for region in regions:
            try:
                is_ram = bool(getattr(region, "is_ram", False))
                start = int(region.start)
                stop = int(region.start + region.length)
            except Exception:
                continue
            if is_ram and address >= start and end <= stop:
                return True
        return False

    def read(self, address: int, size: int, out_path: str) -> OperationResult:
        self._require_session()
        if size <= 0 or size > 16 * 1024 * 1024:
            return self._fail("Invalid read size (1 … 16 MiB)")

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
            return self._fail(str(exc), exc)

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
            return self._fail(f"Firmware not found: {path}")

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
            return self._fail(str(exc), exc)

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
        return self._fail(detail or "Verify failed", duration_s=dur, detail=detail)

    def _verify_image(self, session: Any, path: Path) -> tuple[bool, str]:
        """Compare flash against the file's address/data segments."""
        return self._verify_segments(session, self._load_image_segments(path))

    def _verify_segments(
        self, session: Any, segments: list[tuple[int, bytes]]
    ) -> tuple[bool, str]:
        if not segments:
            return False, "No loadable segments in image"

        self._prepare_fresh_flash_read(session)
        target = session.target
        compared = 0
        total = sum(len(d) for _, d in segments)
        for addr, expected in segments:
            actual = bytes(target.read_memory_block8(addr, len(expected)))
            if actual != expected:
                for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
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
        if suffix in (".elf", ".axf", ".alf"):
            return self._parse_elf(path)
        if suffix == ".srec":
            return self._parse_srec(data.decode("ascii", errors="replace"))
        base = self._target.flash_base if self._target else 0x0800_0000
        return [(base, data)]

    def _parse_hex(self, text: str) -> list[tuple[int, bytes]]:
        # Same parser pyOCD uses when it programs the file.
        from io import StringIO

        from intelhex import IntelHex

        image = IntelHex(StringIO(text))
        segments: list[tuple[int, bytes]] = []
        for start, end in image.segments():
            data = bytes(image.tobinarray(start=start, size=end - start))
            if data:
                segments.append((start, data))
        return segments

    def _parse_srec(self, text: str) -> list[tuple[int, bytes]]:
        return parse_srec(text)

    def _parse_elf(self, path: Path) -> list[tuple[int, bytes]]:
        try:
            return parse_elf(path)
        except RuntimeError as exc:
            if "pyelftools" in str(exc):
                raise RuntimeError("pyelftools is required for ELF verify") from exc
            raise

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
            return self._fail(str(exc), exc)

    def _fail(self, message: str, exc: BaseException | None = None, **extra) -> OperationResult:
        """Attach a typed probe error without changing the user-visible message."""
        if exc is not None:
            error = classify_probe_error(exc, message)
        elif any(
            marker in message.lower()
            for marker in ("unplugged", "not connected", "no matching probe")
        ):
            error = ProbeDisconnected(message)
        else:
            error = ProbeOperationError(message)
        return OperationResult(ok=False, message=message, error=error, **extra)

    def _require_session(self):
        if self._session is None or not self.connected:
            raise ProbeDisconnected("Not connected to a target")
        return self._session
