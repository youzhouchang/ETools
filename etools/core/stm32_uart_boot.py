"""STM32 system-memory bootloader over UART (ST AN3155), no debug probe needed."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from etools.core.fw_image import SparseImage
from etools.logger import get_logger

log = get_logger("uart_boot")

SYNC = 0x7F
ACK = 0x79
NACK = 0x1F

CMD_GET = 0x00
CMD_GET_VERSION = 0x01
CMD_GET_ID = 0x02
CMD_READ = 0x11
CMD_GO = 0x21
CMD_WRITE = 0x31
CMD_ERASE = 0x43
CMD_EXT_ERASE = 0x44
CMD_WP = 0x63
CMD_WUP = 0x73
CMD_RDP = 0x82
CMD_RUP = 0x92

BLOCK = 256
ERASE_TIMEOUT_S = 60.0

BAUD_RATES = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
LINES = ("none", "dtr", "rts")


class BootloaderError(RuntimeError):
    """Bootloader protocol failure (NACK, timeout, unsupported command)."""


def _xor(data: bytes) -> int:
    value = 0
    for b in data:
        value ^= b
    return value


def _addr_frame(address: int) -> bytes:
    raw = int(address).to_bytes(4, "big")
    return raw + bytes([_xor(raw)])


@dataclass
class BootInfo:
    version: int = 0
    commands: list[int] = field(default_factory=list)
    pid: int = 0

    @property
    def extended_erase(self) -> bool:
        return CMD_EXT_ERASE in self.commands

    def version_text(self) -> str:
        return f"{self.version >> 4}.{self.version & 0xF}"


@dataclass
class LineEntry:
    """Drive BOOT0 / NRST from the adapter's DTR / RTS lines.

    "Asserted" means the pyserial line is set True; the invert flags cover
    adapters or transistor stages that flip the logic.
    """

    boot_line: str = "rts"
    reset_line: str = "dtr"
    boot_invert: bool = False
    reset_invert: bool = False
    pulse_s: float = 0.05
    settle_s: float = 0.15

    def _set(self, port: Any, line: str, active: bool, invert: bool) -> None:
        if line == "none":
            return
        level = bool(active) ^ bool(invert)
        try:
            if line == "dtr":
                port.dtr = level
            elif line == "rts":
                port.rts = level
        except (OSError, ValueError) as exc:
            log.warning("cannot drive %s: %s", line, exc)

    def _reset_pulse(self, port: Any) -> None:
        self._set(port, self.reset_line, True, self.reset_invert)
        time.sleep(self.pulse_s)
        self._set(port, self.reset_line, False, self.reset_invert)
        time.sleep(self.settle_s)

    def enter(self, port: Any) -> None:
        self._set(port, self.boot_line, True, self.boot_invert)
        self._reset_pulse(port)

    def leave(self, port: Any) -> None:
        """Release BOOT0 and reset into the application."""
        self._set(port, self.boot_line, False, self.boot_invert)
        self._reset_pulse(port)


def open_serial(port: str, baud: int, timeout: float = 0.5) -> Any:
    import serial

    return serial.Serial(
        port=port,
        baudrate=int(baud),
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        timeout=timeout,
        write_timeout=2.0,
    )


class Stm32UartBoot:
    """AN3155 client over a pyserial-like port (write / read / timeout)."""

    def __init__(self, port: Any, *, timeout: float = 1.0) -> None:
        self.port = port
        self.timeout = timeout
        self.info: BootInfo | None = None

    # -- framing ----------------------------------------------------------

    def _read(self, n: int, timeout: float | None = None) -> bytes:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        buf = bytearray()
        while len(buf) < n:
            chunk = self.port.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
                continue
            if time.monotonic() > deadline:
                break
        return bytes(buf)

    def _ack(self, what: str, timeout: float | None = None) -> None:
        b = self._read(1, timeout)
        if not b:
            raise BootloaderError(f"{what}: no response")
        if b[0] == ACK:
            return
        if b[0] == NACK:
            raise BootloaderError(f"{what}: NACK")
        raise BootloaderError(f"{what}: unexpected byte 0x{b[0]:02X}")

    def _cmd(self, code: int, what: str) -> None:
        self.port.write(bytes([code, code ^ 0xFF]))
        self._ack(what)

    def _require(self, code: int, what: str) -> None:
        if self.info is not None and self.info.commands and code not in self.info.commands:
            raise BootloaderError(f"{what} is not supported by this bootloader")

    # -- commands ---------------------------------------------------------

    def sync(self, attempts: int = 4) -> None:
        reset = getattr(self.port, "reset_input_buffer", None)
        last = "no response"
        for _ in range(max(1, attempts)):
            if callable(reset):
                reset()
            self.port.write(bytes([SYNC]))
            b = self._read(1, self.timeout)
            # NACK after 0x7F means the bootloader was already synchronised.
            if b and b[0] in (ACK, NACK):
                return
            last = f"unexpected 0x{b[0]:02X}" if b else "no response"
            time.sleep(0.05)
        raise BootloaderError(f"Bootloader sync failed ({last}); check BOOT0, wiring and baud")

    def get(self) -> BootInfo:
        self._cmd(CMD_GET, "Get")
        n = self._read(1)
        if not n:
            raise BootloaderError("Get: no length")
        payload = self._read(n[0] + 1)
        if len(payload) != n[0] + 1:
            raise BootloaderError("Get: short reply")
        self._ack("Get end")
        info = self.info or BootInfo()
        info.version = payload[0]
        info.commands = list(payload[1:])
        self.info = info
        return info

    def get_id(self) -> int:
        self._cmd(CMD_GET_ID, "Get ID")
        n = self._read(1)
        if not n:
            raise BootloaderError("Get ID: no length")
        payload = self._read(n[0] + 1)
        self._ack("Get ID end")
        pid = int.from_bytes(payload, "big")
        if self.info is None:
            self.info = BootInfo()
        self.info.pid = pid
        return pid

    def connect(self) -> BootInfo:
        self.sync()
        info = self.get()
        self.get_id()
        return info

    def read_memory(self, address: int, size: int) -> bytes:
        if not 0 < size <= BLOCK:
            raise ValueError("read size must be 1..256")
        self._require(CMD_READ, "Read Memory")
        self._cmd(CMD_READ, "Read Memory (read protection active?)")
        self.port.write(_addr_frame(address))
        self._ack(f"Read address 0x{address:08X}")
        n = size - 1
        self.port.write(bytes([n, n ^ 0xFF]))
        self._ack("Read length")
        data = self._read(size)
        if len(data) != size:
            raise BootloaderError(f"Read 0x{address:08X}: short reply ({len(data)}/{size})")
        return data

    def write_memory(self, address: int, data: bytes) -> None:
        if not 0 < len(data) <= BLOCK:
            raise ValueError("write size must be 1..256")
        if len(data) % 4:
            data = data + b"\xff" * (4 - len(data) % 4)
        self._require(CMD_WRITE, "Write Memory")
        self._cmd(CMD_WRITE, "Write Memory (read protection active?)")
        self.port.write(_addr_frame(address))
        self._ack(f"Write address 0x{address:08X}")
        frame = bytes([len(data) - 1]) + data
        self.port.write(frame + bytes([_xor(frame)]))
        self._ack(f"Write 0x{address:08X}", timeout=max(self.timeout, 2.0))

    def go(self, address: int) -> None:
        self._require(CMD_GO, "Go")
        self._cmd(CMD_GO, "Go")
        self.port.write(_addr_frame(address))
        self._ack(f"Go 0x{address:08X}")

    def mass_erase(self) -> None:
        if self.info is not None and self.info.extended_erase:
            self._cmd(CMD_EXT_ERASE, "Extended Erase")
            self.port.write(b"\xff\xff\x00")
        else:
            self._require(CMD_ERASE, "Erase")
            self._cmd(CMD_ERASE, "Erase")
            self.port.write(b"\xff\x00")
        self._ack("Mass erase", timeout=ERASE_TIMEOUT_S)

    def erase_pages(self, pages: list[int]) -> None:
        if not pages:
            return
        if self.info is not None and self.info.extended_erase:
            self._cmd(CMD_EXT_ERASE, "Extended Erase")
            frame = (len(pages) - 1).to_bytes(2, "big") + b"".join(
                int(p).to_bytes(2, "big") for p in pages
            )
        else:
            if len(pages) > 255 or max(pages) > 255:
                raise BootloaderError("Standard erase supports at most 255 pages < 256")
            self._cmd(CMD_ERASE, "Erase")
            frame = bytes([len(pages) - 1, *pages])
        self.port.write(frame + bytes([_xor(frame)]))
        self._ack("Page erase", timeout=ERASE_TIMEOUT_S)

    def _two_step(self, code: int, what: str) -> None:
        self._require(code, what)
        self._cmd(code, what)
        self._ack(f"{what} done", timeout=ERASE_TIMEOUT_S)

    def readout_protect(self) -> None:
        self._two_step(CMD_RDP, "Readout Protect")

    def readout_unprotect(self) -> None:
        """Remove RDP Level 1. This mass-erases flash; the chip then resets."""
        self._two_step(CMD_RUP, "Readout Unprotect")

    def write_unprotect(self) -> None:
        self._two_step(CMD_WUP, "Write Unprotect")

    # -- high level -------------------------------------------------------

    def program(
        self,
        image: SparseImage,
        *,
        erase: str = "mass",
        verify: bool = True,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> int:
        """Write the image in 256-byte blocks; returns the number of bytes written."""
        if image.empty:
            raise BootloaderError("Image is empty")
        if erase == "mass":
            if progress:
                progress("erase", 0, 1)
            self.mass_erase()
        blocks = sorted(
            {
                b
                for start, data in image.segments()
                for b in range((start // BLOCK) * BLOCK, start + len(data), BLOCK)
            }
        )
        plan: list[tuple[int, bytes]] = []
        for addr in blocks:
            chunk = image.read(addr, BLOCK)
            if erase == "mass" and chunk == b"\xff" * BLOCK:
                continue
            plan.append((addr, chunk))
        total = len(plan) * BLOCK
        for i, (addr, chunk) in enumerate(plan):
            if cancelled is not None and cancelled():
                raise BootloaderError("Cancelled")
            self.write_memory(addr, chunk)
            if progress:
                progress("write", (i + 1) * BLOCK, total)
        if verify:
            for i, (addr, chunk) in enumerate(plan):
                if cancelled is not None and cancelled():
                    raise BootloaderError("Cancelled")
                actual = self.read_memory(addr, BLOCK)
                if actual != chunk:
                    pos = next(j for j in range(BLOCK) if actual[j] != chunk[j])
                    raise BootloaderError(
                        f"Verify mismatch at 0x{addr + pos:08X}: "
                        f"expected 0x{chunk[pos]:02X}, got 0x{actual[pos]:02X}"
                    )
                if progress:
                    progress("verify", (i + 1) * BLOCK, total)
        return total

    def read_range(
        self,
        address: int,
        size: int,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        # AN3155 Read Memory requires a 4-byte-aligned start address. Round the
        # window outward to the alignment and trim the extra bytes afterwards,
        # so callers can pass any address/size without hitting a NACK.
        aligned_addr = address & ~3
        lead = address - aligned_addr
        aligned_size = -(-(lead + size) // 4) * 4  # round up to a multiple of 4
        out = bytearray()
        while len(out) < aligned_size:
            if cancelled is not None and cancelled():
                raise BootloaderError("Cancelled")
            # BLOCK (256) and aligned_size are both multiples of 4, so n stays
            # 4-byte aligned for every chunk, including the last one.
            n = min(BLOCK, aligned_size - len(out))
            out.extend(self.read_memory(aligned_addr + len(out), n))
            if progress:
                progress("read", min(len(out), size), size)
        return bytes(out[lead : lead + size])
