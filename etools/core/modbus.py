"""Modbus RTU / TCP / ASCII frame builders and response parsers.

- **RTU**: binary PDU + CRC-16/MODBUS (little-endian trailer)
- **TCP**: MBAP header (transaction/protocol/length/unit) + PDU, no CRC
- **ASCII**: ``:`` + uppercase hex(slave+pdu+LRC) + CRLF
"""

from __future__ import annotations

from etools.core.checksum import ALGO_CRC16_MODBUS, append_checksum, verify_checksum

# Function codes
FC_READ_COILS = 0x01
FC_READ_DISCRETE = 0x02
FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_COIL = 0x05
FC_WRITE_REGISTER = 0x06
FC_WRITE_COILS = 0x0F
FC_WRITE_REGISTERS = 0x10

_READ_FUNCS = (FC_READ_COILS, FC_READ_DISCRETE, FC_READ_HOLDING, FC_READ_INPUT)

# Framing modes
MODE_RTU = "rtu"
MODE_TCP = "tcp"
MODE_ASCII = "ascii"
MODES = (MODE_RTU, MODE_TCP, MODE_ASCII)


def _u16(value: int) -> bytes:
    return int(value).to_bytes(2, "big")


# ---------------------------------------------------------------------------
# PDU builders (function code + data — no address / CRC)
# ---------------------------------------------------------------------------


def build_pdu_read(function: int, address: int, count: int) -> bytes:
    if function not in _READ_FUNCS:
        raise ValueError(f"unsupported read function {function}")
    if not 1 <= int(count) <= 125:
        raise ValueError("count must be 1..125")
    return bytes([function & 0xFF]) + _u16(address) + _u16(count)


def build_pdu_write_register(address: int, value: int) -> bytes:
    return bytes([FC_WRITE_REGISTER]) + _u16(address) + _u16(value)


def build_pdu_write_coil(address: int, on: bool) -> bytes:
    value = 0xFF00 if on else 0x0000
    return bytes([FC_WRITE_COIL]) + _u16(address) + _u16(value)


def build_pdu_write_registers(address: int, values: list[int]) -> bytes:
    if not 1 <= len(values) <= 123:
        raise ValueError("values length must be 1..123")
    body = bytearray([FC_WRITE_REGISTERS])
    body += _u16(address)
    body += _u16(len(values))
    body.append(len(values) * 2)
    for v in values:
        body += _u16(v)
    return bytes(body)


# ---------------------------------------------------------------------------
# Checksums / framing
# ---------------------------------------------------------------------------


def compute_lrc(data: bytes) -> int:
    """Modbus ASCII LRC: two's complement of the sum of bytes."""
    return (-sum(data)) & 0xFF


def verify_lrc(frame_body: bytes) -> bool:
    """True when frame_body is slave+pdu+lrc (binary) and LRC matches."""
    if len(frame_body) < 2:
        return False
    return compute_lrc(frame_body[:-1]) == frame_body[-1]


def frame_rtu(slave: int, pdu: bytes) -> bytes:
    """RTU: slave + PDU + CRC16."""
    return append_checksum(bytes([slave & 0xFF]) + bytes(pdu), ALGO_CRC16_MODBUS)


def frame_tcp(
    unit_id: int, pdu: bytes, transaction_id: int = 1, protocol_id: int = 0
) -> bytes:
    """TCP: MBAP header + PDU (no CRC)."""
    payload = bytes([unit_id & 0xFF]) + bytes(pdu)
    mbap = (
        _u16(transaction_id)
        + _u16(protocol_id)
        + _u16(len(payload))
    )
    return mbap + payload


def frame_ascii(slave: int, pdu: bytes) -> bytes:
    """ASCII: ':' + hex(slave+pdu+lrc) + CR LF."""
    body = bytes([slave & 0xFF]) + bytes(pdu)
    body += bytes([compute_lrc(body)])
    return b":" + body.hex().upper().encode("ascii") + b"\r\n"


def frame(mode: str, slave: int, pdu: bytes, **kwargs) -> bytes:
    """Dispatch to the right framing for *mode*."""
    key = (mode or MODE_RTU).lower()
    if key == MODE_RTU:
        return frame_rtu(slave, pdu)
    if key == MODE_TCP:
        return frame_tcp(slave, pdu, **kwargs)
    if key == MODE_ASCII:
        return frame_ascii(slave, pdu)
    raise ValueError(f"unknown modbus mode: {mode}")


# ---------------------------------------------------------------------------
# High-level request builders (legacy RTU helpers kept as thin wrappers)
# ---------------------------------------------------------------------------


def build_read(slave: int, function: int, address: int, count: int, mode: str = MODE_RTU) -> bytes:
    return frame(mode, slave, build_pdu_read(function, address, count))


def build_read_holding(slave: int, address: int, count: int, mode: str = MODE_RTU) -> bytes:
    return build_read(slave, FC_READ_HOLDING, address, count, mode=mode)


def build_read_input(slave: int, address: int, count: int, mode: str = MODE_RTU) -> bytes:
    return build_read(slave, FC_READ_INPUT, address, count, mode=mode)


def build_read_coils(slave: int, address: int, count: int, mode: str = MODE_RTU) -> bytes:
    return build_read(slave, FC_READ_COILS, address, count, mode=mode)


def build_read_discrete(slave: int, address: int, count: int, mode: str = MODE_RTU) -> bytes:
    return build_read(slave, FC_READ_DISCRETE, address, count, mode=mode)


def build_write_register(slave: int, address: int, value: int, mode: str = MODE_RTU) -> bytes:
    return frame(mode, slave, build_pdu_write_register(address, value))


def build_write_coil(slave: int, address: int, on: bool, mode: str = MODE_RTU) -> bytes:
    return frame(mode, slave, build_pdu_write_coil(address, on))


def build_write_registers(
    slave: int, address: int, values: list[int], mode: str = MODE_RTU
) -> bytes:
    return frame(mode, slave, build_pdu_write_registers(address, values))


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_pdu(unit: int, pdu: bytes, result: dict) -> dict:
    if not pdu:
        raise ValueError("empty PDU")
    function = pdu[0]
    result["slave"] = unit
    result["function"] = function & 0x7F
    if function & 0x80:
        code = pdu[1] if len(pdu) > 1 else 0
        result.update({"exception": code, "error": True})
        return result
    result["error"] = False
    if result["function"] in _READ_FUNCS:
        if len(pdu) < 2:
            raise ValueError("read response too short")
        byte_count = pdu[1]
        data = pdu[2 : 2 + byte_count]
        if len(data) != byte_count:
            raise ValueError("truncated data")
        result.update({"byte_count": byte_count, "data": data})
        return result
    if result["function"] in (FC_WRITE_COIL, FC_WRITE_REGISTER):
        if len(pdu) < 5:
            raise ValueError("write echo too short")
        result.update(
            {
                "address": int.from_bytes(pdu[1:3], "big"),
                "value": int.from_bytes(pdu[3:5], "big"),
            }
        )
        return result
    if result["function"] == FC_WRITE_REGISTERS:
        if len(pdu) < 5:
            raise ValueError("write multi echo too short")
        result.update(
            {
                "address": int.from_bytes(pdu[1:3], "big"),
                "count": int.from_bytes(pdu[3:5], "big"),
            }
        )
        return result
    result["raw"] = pdu
    return result


def _unframe_rtu(raw: bytes) -> tuple[int, bytes]:
    if len(raw) < 4:
        raise ValueError("frame too short")
    if not verify_checksum(raw, ALGO_CRC16_MODBUS):
        raise ValueError("CRC mismatch")
    body = raw[:-2]
    return body[0], body[1:]


def _unframe_tcp(raw: bytes) -> tuple[int, bytes]:
    if len(raw) < 8:
        raise ValueError("TCP frame too short")
    length = int.from_bytes(raw[4:6], "big")
    if len(raw) < 6 + length:
        raise ValueError("TCP frame truncated")
    unit = raw[6]
    pdu = raw[7 : 6 + length]
    return unit, pdu


def _unframe_ascii(raw: bytes) -> tuple[int, bytes]:
    text = raw.strip()
    if text.startswith(b":"):
        text = text[1:]
    if text.endswith(b"\r\n"):
        text = text[:-2]
    elif text.endswith(b"\n") or text.endswith(b"\r"):
        text = text[:-1]
    try:
        binary = bytes.fromhex(text.decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("bad ASCII hex") from exc
    if len(binary) < 2:
        raise ValueError("ASCII frame too short")
    if not verify_lrc(binary):
        raise ValueError("LRC mismatch")
    return binary[0], binary[1:-1]


def parse_response(frame_bytes: bytes, mode: str = MODE_RTU) -> dict:
    """Parse a response in the given framing. Raises ValueError on bad frames."""
    raw = bytes(frame_bytes)
    key = (mode or MODE_RTU).lower()
    if key == MODE_RTU:
        unit, pdu = _unframe_rtu(raw)
    elif key == MODE_TCP:
        unit, pdu = _unframe_tcp(raw)
    elif key == MODE_ASCII:
        unit, pdu = _unframe_ascii(raw)
    else:
        raise ValueError(f"unknown modbus mode: {mode}")
    return _parse_pdu(unit, pdu, {})


def registers_from_response(resp: dict) -> list[int]:
    """Decode holding/input register words from a parse_response() dict."""
    data = resp.get("data") or b""
    if len(data) % 2:
        raise ValueError("odd register payload")
    return [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2)]
