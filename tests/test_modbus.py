"""Modbus RTU / TCP / ASCII frame builders."""

from __future__ import annotations

import pytest

from etools.core.checksum import verify_checksum
from etools.core.modbus import (
    MODE_ASCII,
    MODE_RTU,
    MODE_TCP,
    build_pdu_read,
    build_read_holding,
    build_write_register,
    build_write_registers,
    compute_lrc,
    frame_ascii,
    frame_tcp,
    parse_response,
    registers_from_response,
)


def test_read_holding_rtu_frame_and_crc():
    frame = build_read_holding(1, 0x0000, 1, mode=MODE_RTU)
    assert frame[:4] == bytes([0x01, 0x03, 0x00, 0x00])
    assert verify_checksum(frame, "crc16_modbus")


def test_write_register_rtu():
    frame = build_write_register(1, 0x0010, 0x1234, mode=MODE_RTU)
    assert frame[:6] == bytes([0x01, 0x06, 0x00, 0x10, 0x12, 0x34])
    assert verify_checksum(frame, "crc16_modbus")


def test_tcp_mbap_frame():
    pdu = build_pdu_read(0x03, 0, 1)
    frame = frame_tcp(1, pdu, transaction_id=1)
    # trans=1, proto=0, length=unit+pdu=6, unit=1
    assert frame[:6] == bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x06])
    assert frame[6] == 0x01
    assert frame[7] == 0x03
    # TCP has no CRC trailer
    assert len(frame) == 6 + 6


def test_ascii_frame_and_lrc():
    pdu = build_pdu_read(0x03, 0, 1)
    frame = frame_ascii(1, pdu)
    assert frame.startswith(b":")
    assert frame.endswith(b"\r\n")
    text = frame[1:-2].decode("ascii")
    binary = bytes.fromhex(text)
    assert binary[0] == 0x01
    assert binary[-1] == compute_lrc(binary[:-1])


def test_parse_rtu_read_response():
    from etools.core.checksum import append_checksum

    body = bytes([0x01, 0x03, 0x04, 0x00, 0x0A, 0x00, 0x0B])
    frame = append_checksum(body, "crc16_modbus")
    resp = parse_response(frame, MODE_RTU)
    assert resp["error"] is False
    assert registers_from_response(resp) == [10, 11]


def test_parse_tcp_read_response():
    pdu = bytes([0x03, 0x04, 0x00, 0x0A, 0x00, 0x0B])
    frame = frame_tcp(1, pdu, transaction_id=7)
    resp = parse_response(frame, MODE_TCP)
    assert resp["slave"] == 1
    assert registers_from_response(resp) == [10, 11]


def test_parse_ascii_read_response():
    pdu = bytes([0x03, 0x04, 0x00, 0x0A, 0x00, 0x0B])
    frame = frame_ascii(1, pdu)
    resp = parse_response(frame, MODE_ASCII)
    assert resp["error"] is False
    assert registers_from_response(resp) == [10, 11]


def test_parse_exception_rtu():
    from etools.core.checksum import append_checksum

    body = bytes([0x01, 0x83, 0x02])
    frame = append_checksum(body, "crc16_modbus")
    resp = parse_response(frame, MODE_RTU)
    assert resp["error"] is True
    assert resp["exception"] == 2


def test_write_registers_count():
    frame = build_write_registers(2, 0, [1, 2, 3], mode=MODE_RTU)
    assert frame[0] == 2
    assert frame[1] == 0x10
    assert frame[6] == 6
    assert verify_checksum(frame, "crc16_modbus")


def test_invalid_count_raises():
    with pytest.raises(ValueError):
        build_read_holding(1, 0, 0)


def test_bad_ascii_lrc_raises():
    with pytest.raises(ValueError):
        parse_response(b":01030000000100\r\n", MODE_ASCII)  # wrong LRC on purpose
