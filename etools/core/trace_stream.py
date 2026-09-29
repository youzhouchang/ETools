"""Binary variable trace frames transported over RTT or SWO.

The target firmware writes the same byte protocol to either transport.  A
record identifies a variable by its linked address, so the host can resolve
it against the loaded ELF without doing SWD memory reads.

Frame format (little endian)::

    magic[4] = b"EVM1"
    version  = u8 (1)
    flags    = u8 (reserved)
    length   = u16 (payload bytes)
    payload  = repeated: address u32, type u8, size u8, value[size]

Types are 1=signed integer, 2=unsigned integer, 3=float32, 4=float64.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"EVM1"
VERSION = 1
MAX_PAYLOAD = 4096
TYPE_SIGNED = 1
TYPE_UNSIGNED = 2
TYPE_FLOAT32 = 3
TYPE_FLOAT64 = 4


@dataclass(frozen=True)
class TraceSample:
    address: int
    value_type: int
    raw: bytes


class TraceFrameParser:
    """Incremental parser that tolerates arbitrary RTT/SWO chunk boundaries."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.frames = 0
        self.bad_frames = 0

    def reset(self) -> None:
        self._buffer.clear()
        self.frames = 0
        self.bad_frames = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[TraceSample]:
        if data:
            self._buffer.extend(bytes(data))
        samples: list[TraceSample] = []
        while True:
            start = self._buffer.find(MAGIC)
            if start < 0:
                # Keep a partial magic suffix for the next transport chunk.
                del self._buffer[: max(0, len(self._buffer) - len(MAGIC) + 1)]
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 8:
                break
            version = self._buffer[4]
            payload_len = int.from_bytes(self._buffer[6:8], "little")
            if version != VERSION or payload_len > MAX_PAYLOAD:
                del self._buffer[0]
                self.bad_frames += 1
                continue
            frame_len = 8 + payload_len
            if len(self._buffer) < frame_len:
                break
            payload = bytes(self._buffer[8:frame_len])
            del self._buffer[:frame_len]
            self.frames += 1
            samples.extend(self._parse_payload(payload))
        return samples

    def _parse_payload(self, payload: bytes) -> list[TraceSample]:
        result: list[TraceSample] = []
        offset = 0
        while offset + 6 <= len(payload):
            address = int.from_bytes(payload[offset : offset + 4], "little")
            value_type = payload[offset + 4]
            size = payload[offset + 5]
            offset += 6
            if size == 0 or size > 8 or offset + size > len(payload):
                self.bad_frames += 1
                break
            if value_type not in {TYPE_SIGNED, TYPE_UNSIGNED, TYPE_FLOAT32, TYPE_FLOAT64}:
                self.bad_frames += 1
                offset += size
                continue
            if value_type == TYPE_FLOAT32 and size != 4:
                self.bad_frames += 1
                offset += size
                continue
            if value_type == TYPE_FLOAT64 and size != 8:
                self.bad_frames += 1
                offset += size
                continue
            result.append(TraceSample(address, value_type, payload[offset : offset + size]))
            offset += size
        if offset != len(payload):
            self.bad_frames += 1
        return result


def encode_frame(records: list[TraceSample], flags: int = 0) -> bytes:
    """Build a frame for tests and host-side protocol examples."""
    payload = bytearray()
    for record in records:
        raw = bytes(record.raw)
        if not 1 <= len(raw) <= 8:
            raise ValueError("trace record value must be 1..8 bytes")
        payload.extend(int(record.address).to_bytes(4, "little"))
        payload.extend((int(record.value_type) & 0xFF, len(raw)))
        payload.extend(raw)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("trace frame payload is too large")
    return MAGIC + bytes((VERSION, flags & 0xFF)) + len(payload).to_bytes(2, "little") + payload


__all__ = [
    "MAGIC",
    "MAX_PAYLOAD",
    "TYPE_FLOAT32",
    "TYPE_FLOAT64",
    "TYPE_SIGNED",
    "TYPE_UNSIGNED",
    "TraceFrameParser",
    "TraceSample",
    "encode_frame",
]
