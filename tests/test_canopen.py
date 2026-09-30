"""Unit tests for CAN link helpers and CANopen framing (no hardware)."""

from __future__ import annotations

from types import SimpleNamespace

from etools.core.can_link import KNOWN_ENDPOINTS, CanEndpoint, format_can_frame
from etools.core.canopen import (
    HB_OPERATIONAL,
    HB_STOPPED,
    NMT_PREOP,
    NMT_START,
    NMT_STOP,
    decode_uint,
    encode_uint,
    is_sdo_response,
    nmt_frame,
    parse_heartbeat,
    parse_sdo_response,
    sdo_read_request,
    sdo_write_request,
)


def test_known_endpoints_include_virtual():
    assert any(e.interface == "virtual" for e in KNOWN_ENDPOINTS)
    assert all(isinstance(e, CanEndpoint) for e in KNOWN_ENDPOINTS)


def test_nmt_frame_broadcast_and_node():
    cob, data = nmt_frame(NMT_START, 0)
    assert cob == 0x000
    assert data == bytes([NMT_START, 0])
    cob, data = nmt_frame(NMT_STOP, 5)
    assert data == bytes([NMT_STOP, 5])
    cob, data = nmt_frame(NMT_PREOP, 127)
    assert data == bytes([NMT_PREOP, 127])


def test_parse_heartbeat():
    msg = SimpleNamespace(arbitration_id=0x705, data=bytes([HB_OPERATIONAL]))
    hb = parse_heartbeat(msg)
    assert hb is not None
    node, state, name = hb
    assert node == 5
    assert state == HB_OPERATIONAL
    assert name == "operational"

    msg = SimpleNamespace(arbitration_id=0x701, data=bytes([HB_STOPPED]))
    assert parse_heartbeat(msg)[2] == "stopped"
    assert parse_heartbeat(SimpleNamespace(arbitration_id=0x123, data=b"\x01")) is None


def test_sdo_read_request_layout():
    cob, data = sdo_read_request(2, 0x1018, 1)
    assert cob == 0x602
    assert data[0] == 0x40
    assert data[1] == 0x18 and data[2] == 0x10
    assert data[3] == 1


def test_sdo_write_request_expedited():
    cob, data = sdo_write_request(1, 0x2000, 0, encode_uint(0x11223344, 4))
    assert cob == 0x601
    assert data[0] == 0x23  # 4-byte expedited download
    assert data[4:8] == bytes.fromhex("44332211")

    cob, data = sdo_write_request(1, 0x2000, 0, encode_uint(0x12, 1))
    assert data[0] == 0x2F
    assert data[4] == 0x12


def test_parse_sdo_upload_expedited():
    payload = bytes([0x43, 0x00, 0x10, 0x00]) + bytes.fromhex("11223344")
    result = parse_sdo_response(payload)
    assert result.ok
    assert result.index == 0x1000
    assert result.data == bytes.fromhex("11223344")
    assert decode_uint(result.data) == 0x44332211


def test_parse_sdo_abort():
    payload = bytes([0x80, 0x00, 0x10, 0x00]) + (0x06020000).to_bytes(4, "little")
    result = parse_sdo_response(payload)
    assert not result.ok
    assert "does not exist" in result.error


def test_is_sdo_response():
    ok = SimpleNamespace(arbitration_id=0x581, data=b"")
    no = SimpleNamespace(arbitration_id=0x123, data=b"")
    assert is_sdo_response(ok)
    assert not is_sdo_response(no)


def test_format_can_frame():
    msg = SimpleNamespace(
        arbitration_id=0x123,
        data=bytes([1, 2, 3]),
        is_extended_id=False,
        is_remote_frame=False,
        is_error_frame=False,
        is_fd=False,
    )
    text = format_can_frame(msg)
    assert "ID=123" in text
    assert "01 02 03" in text
