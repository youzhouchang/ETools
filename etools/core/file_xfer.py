"""File-transfer protocol facade for IAP / bootloader downloads.

Builds on YMODEM/XMODEM (see :mod:`etools.core.ymodem`) and adds a compact
ZMODEM sender plus a raw stream path. UI code talks only to :func:`send_file`
/ :func:`receive_file` so new protocols can be plugged in without layout churn.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from etools.core.ymodem import (
    MODE_CRC,
    TransferResult,
    XmodemSender,
    YmodemError,
    YmodemReceiver,
    YmodemSender,
    crc16_xmodem,
)

# Protocol ids used by the UI combo
PROTO_YMODEM = "ymodem"
PROTO_XMODEM = "xmodem"
PROTO_ZMODEM = "zmodem"
PROTO_RAW = "raw"

PROTOCOLS = (
    (PROTO_YMODEM, "YMODEM"),
    (PROTO_XMODEM, "XMODEM"),
    (PROTO_ZMODEM, "ZMODEM"),
    (PROTO_RAW, "Raw"),
)

# --- ZMODEM constants (CiA / Chuck Forsberg) ---------------------------
ZDLE = 0x18
ZPAD = 0x2A
ZBIN = 0x41  # 'A' binary header
ZHEX = 0x42  # 'B' hex header
ZBIN32 = 0x43
ZCRCE = 0x68
ZCRCG = 0x69
ZCRCQ = 0x6A
ZCRCW = 0x6B
ZRQINIT = 0x00
ZRINIT = 0x01
ZSINIT = 0x02
ZACK = 0x03
ZFILE = 0x04
ZSKIP = 0x05
ZNAK = 0x06
ZABORT = 0x07
ZFIN = 0x08
ZRPOS = 0x09
ZDATA = 0x0A
ZEOF = 0x0B
ZFERR = 0x0C
ZCRC = 0x0D
ZCHALLENGE = 0x0E
ZCOMPL = 0x0F
ZCAN = 0x10
ZFREECNT = 0x11
ZCOMMAND = 0x12

# ZRINIT capability bits (subset)
ZCANFDX = 0x00000004
ZCANOVIO = 0x00000002
ZCANFC32 = 0x00000020


def _z_crc16(data: bytes) -> int:
    return crc16_xmodem(data)


def _z_hex_header(frame_type: int, flags: int = 0) -> bytes:
    """Hex-encoded binary header (most peers accept this after ZRQINIT)."""
    payload = bytes(
        [
            frame_type,
            flags & 0xFF,
            (flags >> 8) & 0xFF,
            (flags >> 16) & 0xFF,
            (flags >> 24) & 0xFF,
        ]
    )
    crc = _z_crc16(payload)
    body = payload + bytes([(crc >> 8) & 0xFF, crc & 0xFF])
    hx = body.hex().upper().encode("ascii")
    # ZPAD ZPAD ZDLE ZHEX + hex + CR LF (and XON for hex headers)
    return bytes([ZPAD, ZPAD, ZDLE, ZHEX]) + hx + b"\r\n\x11"


class ZmodemSender:
    """Minimal ZMODEM-128 sender (hex headers + ZDATA/ZEOF/ZFIN).

    Covers the common IAP case where the peer runs ``rz`` and pulls a file.
    Not a full ZMODEM-8k/windowing implementation.
    """

    def __init__(
        self,
        write: Callable[[bytes], None],
        read: Callable[[float], bytes],
        *,
        packet_timeout: float = 10.0,
    ) -> None:
        self._write = write
        self._read = read
        self._timeout = float(packet_timeout)
        self._buf = bytearray()

    def _feed(self, chunk: bytes) -> None:
        if chunk:
            self._buf.extend(chunk)

    def _wait_for(self, predicate: Callable[[int], bool], deadline: float) -> int | None:
        while time.monotonic() < deadline:
            if self._buf:
                b = self._buf.pop(0)
                if predicate(b):
                    return b
            else:
                self._feed(self._read(0.2))
        return None

    def send(
        self,
        filename: str,
        data: bytes,
        *,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> TransferResult:
        name = Path(filename).name
        total = len(data)
        try:
            # Peer (rz) usually emits "rz\r" then ZRINIT hex header.
            self._write(b"rz\r")
            deadline = time.monotonic() + max(self._timeout, 30.0)
            # Wait until we see ZDLE (start of a ZMODEM header) or give up.
            got = self._wait_for(lambda b: b == ZDLE, deadline)
            if got is None:
                raise YmodemError("timeout waiting for ZMODEM ZRINIT")
            # Drain a little of the peer header.
            self._feed(self._read(0.3))

            # ZFILE with name + size + mode in the data subpacket (simplified).
            meta = f"{name}\x00{total} 0 0 0 {total} {int(time.time())} 0\x00".encode(
                "utf-8", errors="replace"
            )
            self._write(_z_hex_header(ZFILE))
            self._write(self._data_subpacket(meta, end=ZCRCW))

            # ZDATA at offset 0
            self._write(_z_hex_header(ZDATA, 0))
            block = 128
            sent = 0
            while sent < total or total == 0:
                if cancel and cancel():
                    self._write(_z_hex_header(ZABORT))
                    return TransferResult(False, sent, sent // block, "cancelled")
                chunk = data[sent : sent + block]
                end = ZCRCW if sent + block >= total or total == 0 else ZCRCG
                self._write(self._data_subpacket(chunk, end=end))
                sent += len(chunk)
                if on_progress:
                    on_progress(sent, total)
                if total == 0 or sent >= total:
                    break
            self._write(_z_hex_header(ZEOF, total))
            self._write(_z_hex_header(ZFIN))
            self._write(b"OO")  # classic ZMODEM hangup
            return TransferResult(True, sent, max(1, sent // block), "ok", filename=name)
        except YmodemError as exc:
            return TransferResult(False, 0, 0, str(exc))

    @staticmethod
    def _data_subpacket(data: bytes, *, end: int = ZCRCW) -> bytes:
        """ZDLE-escaped data + trailing frame type + CRC-16."""
        out = bytearray()
        for b in data:
            if b in (ZDLE, 0x11, 0x13, 0x0D):
                out.append(ZDLE)
                out.append(b ^ 0x40)
            else:
                out.append(b)
        crc = _z_crc16(data)
        out.append(ZDLE)
        out.append(end)
        out.append((crc >> 8) & 0xFF)
        out.append(crc & 0xFF)
        return bytes(out)


@dataclass
class TransferSpec:
    protocol: str = PROTO_YMODEM
    mode: str = MODE_CRC  # for YMODEM/XMODEM check field
    one_k: bool = False


def send_file(
    write: Callable[[bytes], None],
    read: Callable[[float], bytes],
    filename: str,
    data: bytes,
    *,
    protocol: str = PROTO_YMODEM,
    mode: str = MODE_CRC,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> TransferResult:
    proto = (protocol or PROTO_YMODEM).lower()
    if proto == PROTO_RAW:
        try:
            write(data)
            if on_progress:
                on_progress(len(data), len(data))
            return TransferResult(True, len(data), 1, "ok", filename=Path(filename).name)
        except Exception as exc:  # noqa: BLE001
            return TransferResult(False, 0, 0, str(exc))
    if proto == PROTO_XMODEM:
        sender = XmodemSender(write=write, read=read, mode=mode, one_k=False)
        return sender.send(filename, data, on_progress=on_progress, cancel=cancel)
    if proto == PROTO_ZMODEM:
        sender = ZmodemSender(write=write, read=read)
        return sender.send(filename, data, on_progress=on_progress, cancel=cancel)
    # default YMODEM
    sender = YmodemSender(write=write, read=read, mode=mode, one_k=False)
    return sender.send(filename, data, on_progress=on_progress, cancel=cancel)


def receive_file(
    write: Callable[[bytes], None],
    read: Callable[[float], bytes],
    *,
    protocol: str = PROTO_YMODEM,
    mode: str = MODE_CRC,
    timeout: float = 90.0,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> TransferResult:
    proto = (protocol or PROTO_YMODEM).lower()
    if proto == PROTO_ZMODEM:
        return TransferResult(False, 0, 0, "ZMODEM receive not implemented yet")
    if proto == PROTO_RAW:
        return TransferResult(False, 0, 0, "Raw mode has no receive framing")
    receiver = YmodemReceiver(write=write, read=read, mode=mode)
    return receiver.receive(
        ymodem=proto != PROTO_XMODEM,
        timeout=timeout,
        on_progress=on_progress,
        cancel=cancel,
    )
