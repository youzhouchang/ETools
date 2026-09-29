"""Frame checksum helpers for serial TX/RX (XOR / SUM / CRC)."""

from __future__ import annotations

from typing import Final

# Algorithm ids used by UI prefs and the public API.
ALGO_NONE: Final = "none"
ALGO_XOR: Final = "xor"
ALGO_SUM8: Final = "sum8"
ALGO_SUM16: Final = "sum16"
ALGO_CRC8: Final = "crc8"
ALGO_CRC16_MODBUS: Final = "crc16_modbus"
ALGO_CRC16_CCITT: Final = "crc16_ccitt"
ALGO_CRC32: Final = "crc32"

ALGORITHMS: Final[tuple[str, ...]] = (
    ALGO_NONE,
    ALGO_XOR,
    ALGO_SUM8,
    ALGO_SUM16,
    ALGO_CRC8,
    ALGO_CRC16_MODBUS,
    ALGO_CRC16_CCITT,
    ALGO_CRC32,
)

# Byte width of the trailing checksum field (0 = no trailer).
_CHECK_WIDTH: Final[dict[str, int]] = {
    ALGO_NONE: 0,
    ALGO_XOR: 1,
    ALGO_SUM8: 1,
    ALGO_SUM16: 2,
    ALGO_CRC8: 1,
    ALGO_CRC16_MODBUS: 2,
    ALGO_CRC16_CCITT: 2,
    ALGO_CRC32: 4,
}


def checksum_width(algo: str) -> int:
    return _CHECK_WIDTH.get(str(algo or ALGO_NONE).lower(), 0)


def _crc_generic(
    data: bytes,
    *,
    width: int,
    poly: int,
    init: int,
    refin: bool,
    refout: bool,
    xorout: int,
) -> int:
    """Bitwise CRC; `width` in bits, poly/init/xorout unreflected."""
    crc = init
    top = 1 << (width - 1)
    mask = (1 << width) - 1
    for byte in data:
        b = _reflect8(byte) if refin else byte
        if width >= 8:
            crc ^= b << (width - 8)
            for _ in range(8):
                crc = ((crc << 1) ^ poly) if (crc & top) else (crc << 1)
                crc &= mask
        else:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ poly) if (crc & top) else (crc << 1)
                crc &= mask
    if refout:
        crc = _reflect_bits(crc, width)
    return (crc ^ xorout) & mask


def _reflect8(value: int) -> int:
    return _reflect_bits(value, 8)


def _reflect_bits(value: int, width: int) -> int:
    out = 0
    for i in range(width):
        if value & (1 << i):
            out |= 1 << (width - 1 - i)
    return out


def compute_checksum(data: bytes, algo: str) -> bytes:
    """Return the trailing checksum field for `data` (empty when algo=none)."""
    key = str(algo or ALGO_NONE).lower()
    payload = bytes(data)
    if key == ALGO_NONE or key not in _CHECK_WIDTH:
        return b""
    if key == ALGO_XOR:
        acc = 0
        for b in payload:
            acc ^= b
        return bytes([acc & 0xFF])
    if key == ALGO_SUM8:
        return bytes([sum(payload) & 0xFF])
    if key == ALGO_SUM16:
        return (sum(payload) & 0xFFFF).to_bytes(2, "little")
    if key == ALGO_CRC8:
        # CRC-8/ATM: poly=0x07, init=0x00
        crc = _crc_generic(
            payload, width=8, poly=0x07, init=0x00, refin=False, refout=False, xorout=0x00
        )
        return bytes([crc])
    if key == ALGO_CRC16_MODBUS:
        # CRC-16/MODBUS: poly=0x8005 reflected, init=0xFFFF, xorout=0 — wire order LE
        crc = _crc_generic(
            payload, width=16, poly=0x8005, init=0xFFFF, refin=True, refout=True, xorout=0x0000
        )
        return crc.to_bytes(2, "little")
    if key == ALGO_CRC16_CCITT:
        # CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF — wire order BE
        crc = _crc_generic(
            payload, width=16, poly=0x1021, init=0xFFFF, refin=False, refout=False, xorout=0x0000
        )
        return crc.to_bytes(2, "big")
    if key == ALGO_CRC32:
        # CRC-32/ISO-HDLC (zlib / Ethernet), wire order LE
        crc = _crc_generic(
            payload,
            width=32,
            poly=0x04C11DB7,
            init=0xFFFFFFFF,
            refin=True,
            refout=True,
            xorout=0xFFFFFFFF,
        )
        return crc.to_bytes(4, "little")
    return b""


def append_checksum(data: bytes, algo: str) -> bytes:
    """Return `data` with the checksum trailer appended."""
    return bytes(data) + compute_checksum(data, algo)


def verify_checksum(frame: bytes, algo: str) -> bool:
    """True when `frame` already ends with the matching checksum trailer."""
    key = str(algo or ALGO_NONE).lower()
    width = checksum_width(key)
    if width == 0:
        return True
    raw = bytes(frame)
    if len(raw) < width:
        return False
    body, tail = raw[:-width], raw[-width:]
    return compute_checksum(body, key) == tail
