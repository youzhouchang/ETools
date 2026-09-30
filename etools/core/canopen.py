"""CANopen helpers: NMT, heartbeat, expedited SDO.

Frame layout follows CiA 301. Values are returned as (cob_id, payload) ready
for :class:`etools.core.can_link.CanLink.send`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- NMT (COB-ID 0x000) -------------------------------------------------

NMT_START = 0x01
NMT_STOP = 0x02
NMT_PREOP = 0x80
NMT_RESET_NODE = 0x81
NMT_RESET_COMM = 0x82

NMT_COMMANDS = [
    (NMT_START, "start"),
    (NMT_STOP, "stop"),
    (NMT_PREOP, "preop"),
    (NMT_RESET_NODE, "reset_node"),
    (NMT_RESET_COMM, "reset_comm"),
]

# --- Heartbeat / node state (0x700 + node) ------------------------------

HB_BOOTUP = 0x00
HB_STOPPED = 0x04
HB_OPERATIONAL = 0x05
HB_PREOP = 0x7F

HB_STATES = {
    HB_BOOTUP: "bootup",
    HB_STOPPED: "stopped",
    HB_OPERATIONAL: "operational",
    HB_PREOP: "preop",
}

# --- SDO ----------------------------------------------------------------

SDO_CLIENT_BASE = 0x600  # client → server request
SDO_SERVER_BASE = 0x580  # server → client response

SDO_ABORT = 0x80

# Expedited download command by payload size (n = unused bytes)
_SDO_DOWNLOAD_EXPEDITED = {1: 0x2F, 2: 0x2B, 3: 0x27, 4: 0x23}
# Expedited upload response command by payload size
_SDO_UPLOAD_EXPEDITED = {1: 0x4F, 2: 0x4B, 3: 0x47, 4: 0x43}
_SDO_UPLOAD_SIZES = {0x4F: 1, 0x4B: 2, 0x47: 3, 0x43: 4}

SDO_ABORT_CODES = {
    0x05030000: "toggle bit not alternated",
    0x05040000: "SDO protocol timed out",
    0x05040001: "client/server command specifier invalid",
    0x05040002: "invalid block size",
    0x05040003: "invalid sequence number",
    0x05040004: "CRC error",
    0x05040005: "out of memory",
    0x06010000: "access to this object is not allowed",
    0x06010001: "attempt to read a write-only object",
    0x06010002: "attempt to write a read-only object",
    0x06020000: "object does not exist in the object dictionary",
    0x06040041: "object cannot be mapped to the PDO",
    0x06040042: "number and length of objects exceed PDO size",
    0x06040043: "general parameter incompatibility reason",
    0x06040047: "general internal incompatibility in the device",
    0x06060000: "access failed due to a hardware error",
    0x06070010: "data type does not match / length of service parameter",
    0x06070012: "data type length exceeds",
    0x06070013: "data type length is too short",
    0x06090011: "sub-index does not exist",
    0x06090030: "value range of parameter exceeded",
    0x06090031: "value of parameter written too high",
    0x06090032: "value of parameter written too low",
    0x06090036: "maximum value is less than minimum value",
    0x08000000: "general error",
    0x08000020: "data cannot be transferred or stored to the application",
    0x08000021: "data cannot be transferred or stored due to local control",
    0x08000022: "data cannot be transferred due to present device state",
    0x08000023: "object dictionary dynamic generation fails",
}


@dataclass(frozen=True)
class SdoResult:
    ok: bool
    index: int = 0
    subindex: int = 0
    data: bytes = b""
    abort_code: int = 0
    error: str = ""


def nmt_frame(command: int, node_id: int = 0) -> tuple[int, bytes]:
    """Build an NMT request. ``node_id`` 0 broadcasts to all nodes."""
    if not 0 <= int(node_id) <= 127:
        raise ValueError("node_id must be 0..127")
    if command not in {c for c, _ in NMT_COMMANDS}:
        raise ValueError(f"unknown NMT command 0x{command:02X}")
    return 0x000, bytes([int(command) & 0xFF, int(node_id) & 0x7F])


def heartbeat_cob_id(node_id: int) -> int:
    return 0x700 + (int(node_id) & 0x7F)


def parse_heartbeat(msg: Any) -> tuple[int, int, str] | None:
    """Return (node_id, state, state_name) for a heartbeat/ bootup frame."""
    arb = int(getattr(msg, "arbitration_id", 0))
    if arb < 0x700 or arb > 0x77F:
        return None
    data = bytes(getattr(msg, "data", b"") or b"")
    if not data:
        return None
    node = arb - 0x700
    state = data[0]
    return node, state, HB_STATES.get(state, f"0x{state:02X}")


def is_sdo_response(msg: Any) -> bool:
    arb = int(getattr(msg, "arbitration_id", 0))
    return SDO_SERVER_BASE < arb < SDO_SERVER_BASE + 0x80


def sdo_read_request(node_id: int, index: int, subindex: int = 0) -> tuple[int, bytes]:
    """SDO upload initiate (expedited path)."""
    if not 1 <= int(node_id) <= 127:
        raise ValueError("node_id must be 1..127")
    idx = int(index) & 0xFFFF
    return (
        SDO_CLIENT_BASE + (int(node_id) & 0x7F),
        bytes(
            [
                0x40,
                idx & 0xFF,
                (idx >> 8) & 0xFF,
                int(subindex) & 0xFF,
                0,
                0,
                0,
                0,
            ]
        ),
    )


def sdo_write_request(node_id: int, index: int, subindex: int, value: bytes) -> tuple[int, bytes]:
    """SDO download initiate (expedited, 1–4 bytes)."""
    if not 1 <= int(node_id) <= 127:
        raise ValueError("node_id must be 1..127")
    raw = bytes(value)
    if not 1 <= len(raw) <= 4:
        raise ValueError("expedited SDO write supports 1..4 bytes")
    idx = int(index) & 0xFFFF
    cmd = _SDO_DOWNLOAD_EXPEDITED[len(raw)]
    # n = unused bytes encoded in bits 2-3 (0b11=1 byte … 0b00=4 bytes)
    cmd |= (4 - len(raw)) << 2
    payload = bytearray(8)
    payload[0] = cmd
    payload[1] = idx & 0xFF
    payload[2] = (idx >> 8) & 0xFF
    payload[3] = int(subindex) & 0xFF
    payload[4 : 4 + len(raw)] = raw
    return SDO_CLIENT_BASE + (int(node_id) & 0x7F), bytes(payload)


def parse_sdo_response(data: bytes) -> SdoResult:
    """Decode an SDO response payload (8 bytes typical)."""
    raw = bytes(data or b"")
    if len(raw) < 4:
        return SdoResult(False, error="short SDO response")
    cmd = raw[0]
    index = raw[1] | (raw[2] << 8)
    sub = raw[3]
    if cmd == SDO_ABORT:
        code = int.from_bytes(raw[4:8], "little") if len(raw) >= 8 else 0
        return SdoResult(
            False,
            index=index,
            subindex=sub,
            abort_code=code,
            error=SDO_ABORT_CODES.get(code, f"abort 0x{code:08X}"),
        )
    if cmd in _SDO_UPLOAD_SIZES:
        n = _SDO_UPLOAD_SIZES[cmd]
        return SdoResult(True, index=index, subindex=sub, data=raw[4 : 4 + n])
    # Download success 0x60
    if cmd == 0x60:
        return SdoResult(True, index=index, subindex=sub)
    # Initiate upload with size (0x41/0x42) — segmented transfer, not supported here
    if cmd in (0x41, 0x42):
        return SdoResult(
            False,
            index=index,
            subindex=sub,
            error="segmented SDO not supported (use 1-4 byte expedited)",
        )
    return SdoResult(False, index=index, subindex=sub, error=f"unhandled SDO cmd 0x{cmd:02X}")


def encode_uint(value: int, size: int = 4) -> bytes:
    """Little-endian unsigned integer of *size* bytes (CANopen default)."""
    if size not in (1, 2, 4):
        raise ValueError("size must be 1, 2 or 4")
    return int(value).to_bytes(size, "little", signed=False)


def decode_uint(data: bytes) -> int:
    return int.from_bytes(bytes(data or b""), "little", signed=False)


# --- PDO mapping -------------------------------------------------------

#: PDO comm / mapping object index ranges (CiA 301).
RPDO_COMM_BASE = 0x1400
RPDO_MAP_BASE = 0x1600
TPDO_COMM_BASE = 0x1800
TPDO_MAP_BASE = 0x1A00


def encode_pdo_mapping(index: int, subindex: int, bitlen: int) -> bytes:
    """Pack a PDO mapping entry: bits 0-7 length, 8-15 sub, 16-31 index."""
    value = ((int(index) & 0xFFFF) << 16) | ((int(subindex) & 0xFF) << 8) | (int(bitlen) & 0xFF)
    return encode_uint(value, 4)


def decode_pdo_mapping(raw: bytes) -> tuple[int, int, int]:
    value = decode_uint(raw)
    return (value >> 16) & 0xFFFF, (value >> 8) & 0xFF, value & 0xFF


def pdo_kind(map_index: int) -> str:
    """'rpdo' | 'tpdo' | '' for a mapping object index."""
    i = int(map_index) & 0xFFF0
    if RPDO_MAP_BASE <= map_index < RPDO_MAP_BASE + 0x200:
        return "rpdo"
    if TPDO_MAP_BASE <= map_index < TPDO_MAP_BASE + 0x200:
        return "tpdo"
    _ = i
    return ""


def pdo_number(map_index: int) -> int:
    base = RPDO_MAP_BASE if pdo_kind(map_index) == "rpdo" else TPDO_MAP_BASE
    return (int(map_index) - base) + 1


def comm_index_for_map(map_index: int) -> int:
    """Mapping 0x1A01 → comm 0x1801 (TPDO2)."""
    kind = pdo_kind(map_index)
    n = pdo_number(map_index)
    if kind == "rpdo":
        return RPDO_COMM_BASE + n - 1
    if kind == "tpdo":
        return TPDO_COMM_BASE + n - 1
    return 0

