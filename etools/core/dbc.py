"""Minimal DBC loader and signal decoder.

Covers ``BO_`` / ``SG_`` lines used by typical automotive databases:
Intel (@1) and Motorola (@0) bit layouts, signedness, factor and offset.
Multiplexed signals are decoded only when the multiplexer matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)")
_SG = re.compile(
    r"^\s*SG_\s+(\w+)\s*(M|m\d+)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(\s*([^,\s]+)\s*,\s*([^)\s]+)\s*\)\s*"
    r"\[\s*([^|]*)\|([^\]]*)\]\s*\"([^\"]*)\""
)


@dataclass
class DbcSignal:
    name: str
    start: int
    length: int
    little_endian: bool
    signed: bool
    factor: float
    offset: float
    unit: str
    mux: str = ""


@dataclass
class DbcMessage:
    frame_id: int
    name: str
    length: int
    extended: bool = False
    signals: list[DbcSignal] = field(default_factory=list)


@dataclass(frozen=True)
class DecodedSignal:
    message: str
    name: str
    value: float
    unit: str
    frame_id: int
    extended: bool


@dataclass
class DbcDatabase:
    messages: dict[tuple[int, bool], DbcMessage]

    def decode(
        self, frame_id: int, data: bytes, *, is_extended: bool = False
    ) -> list[DecodedSignal]:
        message = self.messages.get((int(frame_id) & 0x1FFFFFFF, bool(is_extended)))
        if message is None or not data:
            return []
        raw = bytes(data)
        mux_value = _mux_value(message, raw)
        decoded: list[DecodedSignal] = []
        for signal in message.signals:
            if signal.mux.startswith("m") and signal.mux != f"m{mux_value}":
                continue
            try:
                value = _physical(signal, raw)
            except ValueError:
                continue
            decoded.append(
                DecodedSignal(
                    message.name,
                    signal.name,
                    value,
                    signal.unit,
                    message.frame_id,
                    message.extended,
                )
            )
        return decoded


def load_dbc(path: str | Path) -> DbcDatabase:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_dbc(text)


def parse_dbc(text: str) -> DbcDatabase:
    messages: dict[tuple[int, bool], DbcMessage] = {}
    current: DbcMessage | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("//", 1)[0].rstrip()
        if not line.strip():
            continue
        matched = _BO.match(line)
        if matched:
            dbc_id = int(matched.group(1))
            extended = bool(dbc_id & 0x80000000)
            frame_id = dbc_id & 0x1FFFFFFF
            current = DbcMessage(
                frame_id,
                matched.group(2),
                int(matched.group(3)),
                extended=extended,
            )
            messages[(frame_id, extended)] = current
            continue
        matched = _SG.match(line)
        if matched and current is not None:
            length = int(matched.group(4))
            if not 1 <= length <= 64:
                continue
            current.signals.append(
                DbcSignal(
                    name=matched.group(1),
                    start=int(matched.group(3)),
                    length=length,
                    little_endian=matched.group(5) == "1",
                    signed=matched.group(6) == "-",
                    factor=float(matched.group(7)),
                    offset=float(matched.group(8)),
                    unit=matched.group(11),
                    mux=matched.group(2) or "",
                )
            )
    return DbcDatabase(messages)


def _mux_value(message: DbcMessage, data: bytes) -> int | None:
    for signal in message.signals:
        if signal.mux == "M":
            try:
                return _raw_value(signal, data)
            except ValueError:
                return None
    return None


def _physical(signal: DbcSignal, data: bytes) -> float:
    raw = _raw_value(signal, data)
    if signal.signed and signal.length > 0 and raw >= (1 << (signal.length - 1)):
        raw -= 1 << signal.length
    return raw * signal.factor + signal.offset


def _raw_value(signal: DbcSignal, data: bytes) -> int:
    if signal.length <= 0:
        raise ValueError("invalid signal length")
    if signal.little_endian:
        if signal.start < 0 or signal.start + signal.length > len(data) * 8:
            raise ValueError("signal exceeds frame")
        value = int.from_bytes(data, "little")
        return (value >> signal.start) & ((1 << signal.length) - 1)
    if not _motorola_fits(len(data), signal.start, signal.length):
        raise ValueError("signal exceeds frame")
    return _extract_motorola(data, signal.start, signal.length)


def _motorola_fits(byte_count: int, start: int, length: int) -> bool:
    if start < 0 or start // 8 >= byte_count:
        return False
    byte_index = start // 8
    bit_in_byte = start % 8
    bits_left = length
    while bits_left > 0 and byte_index < byte_count:
        take = min(bits_left, bit_in_byte + 1)
        bits_left -= take
        byte_index += 1
        bit_in_byte = 7
    return bits_left == 0


def _extract_motorola(data: bytes, start: int, length: int) -> int:
    """start is the MSB position in DBC Motorola numbering (7..0, 15..8, ...)."""
    value = 0
    bits_left = length
    byte_index = start // 8
    bit_in_byte = start % 8
    while bits_left > 0 and byte_index < len(data):
        take = min(bits_left, bit_in_byte + 1)
        shift = bit_in_byte + 1 - take
        mask = (1 << take) - 1
        value = (value << take) | ((data[byte_index] >> shift) & mask)
        bits_left -= take
        byte_index += 1
        bit_in_byte = 7
    return value
