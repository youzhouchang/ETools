"""YMODEM / XMODEM file transfer for IAP-style firmware downloads.

Supports send + receive for YMODEM (128/1K) and XMODEM-128, with either
CRC-16 or classic 8-bit checksum. Transport is a pair of callables so the
same core works over serial, TCP, or a test double.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18
CRC_REQUEST = 0x43  # 'C'
NAK_CHECKSUM = 0x15

PKT_128 = 128
PKT_1024 = 1024

MODE_CRC = "crc"
MODE_CHECKSUM = "checksum"


def crc16_xmodem(data: bytes) -> int:
    """XMODEM/YMODEM CRC-16 (poly 0x1021, init 0)."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def checksum8(data: bytes) -> int:
    """XMODEM 8-bit additive checksum."""
    return sum(data) & 0xFF


def make_packet(
    seq: int, payload: bytes, *, one_k: bool = False, mode: str = MODE_CRC
) -> bytes:
    """Build one XMODEM/YMODEM data packet (header + body + check)."""
    size = PKT_1024 if one_k else PKT_128
    body = bytes(payload)
    if len(body) > size:
        raise ValueError("payload exceeds packet size")
    body = body + b"\x1a" * (size - len(body))
    header = bytes([STX if one_k else SOH, seq & 0xFF, (~seq) & 0xFF])
    if mode == MODE_CHECKSUM:
        return header + body + bytes([checksum8(body)])
    crc = crc16_xmodem(body)
    return header + body + bytes([(crc >> 8) & 0xFF, crc & 0xFF])


def ymodem_header_block(filename: str, size: int) -> bytes:
    """YMODEM block 0 payload: ``name\\0size\\0``."""
    name = Path(filename).name.encode("utf-8", errors="replace")[:127]
    meta = f"{int(size)}".encode("ascii")
    data = name + b"\x00" + meta + b"\x00"
    return data.ljust(PKT_128, b"\x00")


def parse_ymodem_header(payload: bytes) -> tuple[str, int]:
    """Extract ``(filename, size)`` from a YMODEM block-0 payload."""
    raw = bytes(payload or b"")
    name_part, _, rest = raw.partition(b"\x00")
    size_part = rest.split(b"\x00", 1)[0]
    name = name_part.decode("utf-8", errors="replace").strip() or "ymodem.bin"
    # Keep only the basename — peers sometimes send paths.
    name = Path(name.replace("\\", "/")).name or "ymodem.bin"
    try:
        size = int(size_part.decode("ascii", errors="ignore").strip() or "0")
    except ValueError:
        size = 0
    return name, max(0, size)


def parse_data_packet(
    packet: bytes, *, mode: str = MODE_CRC
) -> tuple[int, bytes] | None:
    """Validate one packet. Returns ``(seq, payload)`` or None if corrupt."""
    raw = bytes(packet or b"")
    if not raw or raw[0] not in (SOH, STX):
        return None
    body_len = PKT_1024 if raw[0] == STX else PKT_128
    need = 3 + body_len + (1 if mode == MODE_CHECKSUM else 2)
    if len(raw) < need:
        return None
    seq = raw[1]
    if (raw[2] & 0xFF) != ((~seq) & 0xFF):
        return None
    body = raw[3 : 3 + body_len]
    if mode == MODE_CHECKSUM:
        if checksum8(body) != raw[3 + body_len]:
            return None
    else:
        expect = ((raw[3 + body_len] << 8) | raw[3 + body_len + 1]) & 0xFFFF
        if crc16_xmodem(body) != expect:
            return None
    return seq, body


@dataclass
class TransferResult:
    ok: bool
    bytes_sent: int = 0
    packets: int = 0
    message: str = ""
    filename: str = ""
    data: bytes = b""


@dataclass
class _ByteSink:
    """Accumulate read bytes with a short-term buffer for packet assembly."""

    buf: bytearray = field(default_factory=bytearray)

    def feed(self, chunk: bytes) -> None:
        self.buf.extend(chunk)

    def take(self, n: int) -> bytes:
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def __len__(self) -> int:
        return len(self.buf)


class _Session:
    def __init__(
        self,
        write: Callable[[bytes], None],
        read: Callable[[float], bytes],
        *,
        mode: str = MODE_CRC,
        one_k: bool = False,
        max_retries: int = 20,
        packet_timeout: float = 10.0,
    ) -> None:
        self._write = write
        self._read = read
        self.mode = MODE_CHECKSUM if mode == MODE_CHECKSUM else MODE_CRC
        self.one_k = bool(one_k)
        self.max_retries = max(1, int(max_retries))
        self.packet_timeout = float(packet_timeout)
        self._rx = _ByteSink()

    def write(self, data: bytes) -> None:
        self._write(data)

    def pump(self, timeout: float = 0.25) -> bytes:
        chunk = self._read(timeout)
        if chunk:
            self._rx.feed(chunk)
        return chunk

    def read_byte(self, deadline: float) -> int | None:
        while time.monotonic() < deadline:
            if self._rx:
                return self._rx.take(1)[0]
            self.pump(0.2)
        return None

    def read_exact(self, n: int, deadline: float) -> bytes | None:
        while len(self._rx) < n and time.monotonic() < deadline:
            self.pump(0.2)
        if len(self._rx) < n:
            return None
        return self._rx.take(n)

    def handshake_byte(self, cancel) -> int:
        deadline = time.monotonic() + max(self.packet_timeout, 30.0)
        while time.monotonic() < deadline:
            if cancel and cancel():
                raise YmodemError("cancelled")
            self.pump(0.5)
            if self._rx:
                b = self._rx.take(1)[0]
                if b in (CRC_REQUEST, NAK_CHECKSUM):
                    return b
                if b == CAN:
                    raise YmodemError("cancelled by peer")
        raise YmodemError("timeout waiting for handshake")

    def await_reply(self, deadline: float | None = None) -> int:
        deadline = deadline or (time.monotonic() + self.packet_timeout)
        b = self.read_byte(deadline)
        return NAK if b is None else b

    def cancel(self) -> None:
        try:
            self._write(bytes([CAN, CAN]))
        except Exception:  # noqa: BLE001
            pass


class YmodemSender(_Session):
    """Send a file using YMODEM over a byte pipe."""

    def __init__(
        self,
        write: Callable[[bytes], None],
        read: Callable[[float], bytes],
        *,
        one_k: bool = False,
        max_retries: int = 20,
        packet_timeout: float = 10.0,
        mode: str = MODE_CRC,
    ) -> None:
        super().__init__(
            write,
            read,
            mode=mode,
            one_k=one_k,
            max_retries=max_retries,
            packet_timeout=packet_timeout,
        )

    def send(
        self,
        filename: str,
        data: bytes,
        *,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> TransferResult:
        total = len(data)
        try:
            self.handshake_byte(cancel)
            self._send_packet(0, ymodem_header_block(filename, total), one_k=False, cancel=cancel)
            seq = 1
            sent = 0
            size = PKT_1024 if self.one_k else PKT_128
            while sent < total or (total == 0 and seq == 1):
                if cancel and cancel():
                    self.cancel()
                    return TransferResult(False, sent, seq - 1, "cancelled")
                chunk = data[sent : sent + size]
                self._send_packet(seq, chunk, one_k=self.one_k, cancel=cancel)
                sent += len(chunk)
                if on_progress:
                    on_progress(sent, total)
                seq = (seq + 1) & 0xFF
                if total == 0:
                    break
            self._send_eot(cancel)
            self._send_packet(0, b"\x00" * PKT_128, one_k=False, cancel=cancel, final=True)
            return TransferResult(True, sent, seq - 1, "ok", filename=Path(filename).name)
        except YmodemError as exc:
            self.cancel()
            return TransferResult(False, total if total else 0, 0, str(exc))

    def _send_packet(
        self, seq: int, payload: bytes, *, one_k: bool, cancel=None, final: bool = False
    ) -> None:
        packet = make_packet(seq, payload, one_k=one_k, mode=self.mode)
        retries = 0
        while retries < self.max_retries:
            if cancel and cancel():
                raise YmodemError("cancelled")
            self.write(packet)
            reply = self.await_reply()
            if reply == ACK:
                return
            if reply == CAN:
                raise YmodemError("cancelled by peer")
            retries += 1
        raise YmodemError(f"packet {seq} failed after {self.max_retries} retries")

    def _send_eot(self, cancel=None) -> None:
        retries = 0
        while retries < self.max_retries:
            if cancel and cancel():
                raise YmodemError("cancelled")
            self.write(bytes([EOT]))
            reply = self.await_reply()
            if reply == ACK:
                return
            if reply == CAN:
                raise YmodemError("cancelled by peer")
            retries += 1
        raise YmodemError("EOT not acknowledged")


class XmodemSender(YmodemSender):
    """XMODEM-128 without the YMODEM filename header (legacy bootloaders)."""

    def send(
        self,
        filename: str,
        data: bytes,
        *,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> TransferResult:
        try:
            self.handshake_byte(cancel)
            seq = 1
            sent = 0
            while sent < len(data) or (not data and seq == 1):
                if cancel and cancel():
                    self.cancel()
                    return TransferResult(False, sent, seq - 1, "cancelled")
                chunk = data[sent : sent + PKT_128]
                self._send_packet(seq, chunk, one_k=False, cancel=cancel)
                sent += len(chunk)
                if on_progress:
                    on_progress(sent, len(data))
                seq = (seq + 1) & 0xFF
                if not data:
                    break
            self._send_eot(cancel)
            return TransferResult(True, sent, seq - 1, "ok", filename=Path(filename).name)
        except YmodemError as exc:
            self.cancel()
            return TransferResult(False, 0, 0, str(exc))


class YmodemReceiver(_Session):
    """Receive a file sent by a YMODEM/XMODEM sender.

    We start the handshake (send ``C`` or NAK) and pull packets until EOT.
    For YMODEM the first packet is the filename header (block 0).
    """

    def __init__(
        self,
        write: Callable[[bytes], None],
        read: Callable[[float], bytes],
        *,
        one_k: bool = False,
        max_retries: int = 20,
        packet_timeout: float = 10.0,
        mode: str = MODE_CRC,
    ) -> None:
        super().__init__(
            write,
            read,
            mode=mode,
            one_k=one_k,
            max_retries=max_retries,
            packet_timeout=packet_timeout,
        )

    def receive(
        self,
        *,
        ymodem: bool = True,
        timeout: float = 60.0,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> TransferResult:
        deadline_all = time.monotonic() + max(1.0, float(timeout))
        try:
            self._request_start(ymodem=ymodem)
            filename = "xmodem.bin"
            expected = 0
            payload = bytearray()
            packets = 0
            expect_seq = 1 if not ymodem else 0
            while True:
                if cancel and cancel():
                    self.cancel()
                    return TransferResult(False, len(payload), packets, "cancelled")
                if time.monotonic() > deadline_all:
                    raise YmodemError("receive timeout")
                kind, seq, body = self._read_one_packet(deadline_all)
                if kind == "eot":
                    self.write(bytes([ACK]))
                    if ymodem:
                        # Sender closes with an empty block 0 after EOT/ACK.
                        self._read_one_packet(deadline_all, allow_empty=True)
                        self.write(bytes([ACK]))
                    return TransferResult(
                        True,
                        len(payload),
                        packets,
                        "ok",
                        filename=filename,
                        data=bytes(payload),
                    )
                if kind == "cancel":
                    raise YmodemError("cancelled by peer")
                if kind is None:
                    # Garbage / timeout — nudge the sender.
                    self.write(bytes([NAK]))
                    continue
                if ymodem and expect_seq == 0:
                    filename, expected = parse_ymodem_header(body)
                    self.write(bytes([ACK]))
                    expect_seq = 1
                    # Ask for data with CRC after header
                    if self.mode != MODE_CHECKSUM:
                        self.write(bytes([CRC_REQUEST]))
                    continue
                if seq != (expect_seq & 0xFF):
                    self.write(bytes([NAK]))
                    continue
                payload.extend(body)
                packets += 1
                expect_seq = (expect_seq + 1) & 0xFF
                self.write(bytes([ACK]))
                if on_progress:
                    # YMODEM size is a hint; clamp display progress.
                    done = len(payload)
                    total = expected if expected else max(done, 1)
                    on_progress(min(done, total) if expected else done, total)
        except YmodemError as exc:
            self.cancel()
            return TransferResult(False, 0, 0, str(exc))

    def _request_start(self, *, ymodem: bool) -> None:
        # YMODEM / CRC XMODEM start with 'C'; checksum XMODEM starts with NAK.
        if self.mode == MODE_CHECKSUM and not ymodem:
            self.write(bytes([NAK]))
        else:
            self.write(bytes([CRC_REQUEST]))

    def _read_one_packet(
        self, deadline_all: float, *, allow_empty: bool = False
    ) -> tuple[str | None, int, bytes]:
        """Return (kind, seq, body). kind: 'data' | 'eot' | 'cancel' | None."""
        # Sync to SOH/STX/EOT/CAN
        start = time.monotonic()
        while time.monotonic() < min(deadline_all, start + self.packet_timeout):
            if self._rx:
                b = self._rx.take(1)[0]
                if b == CAN:
                    return "cancel", 0, b""
                if b == EOT:
                    return "eot", 0, b""
                if b in (SOH, STX):
                    body_len = PKT_1024 if b == STX else PKT_128
                    check_len = 1 if self.mode == MODE_CHECKSUM else 2
                    rest = self.read_exact(2 + body_len + check_len, deadline_all)
                    if rest is None:
                        return None, 0, b""
                    packet = bytes([b]) + rest
                    parsed = parse_data_packet(packet, mode=self.mode)
                    if parsed is None:
                        return None, 0, b""
                    seq, body = parsed
                    if allow_empty and not any(body):
                        return "data", seq, body
                    return "data", seq, body
            else:
                self.pump(0.2)
        return None, 0, b""


class YmodemError(RuntimeError):
    """Transfer failed or cancelled."""
