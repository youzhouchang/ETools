"""File-transfer facade tests (no hardware)."""

from etools.core.file_xfer import (
    PROTO_RAW,
    PROTO_XMODEM,
    PROTO_YMODEM,
    PROTO_ZMODEM,
    ZmodemSender,
    send_file,
)
from etools.core.ymodem import crc16_xmodem


def test_send_raw():
    out = []

    def write(b):
        out.append(bytes(b))

    r = send_file(write, lambda t: b"", "a.bin", b"\x01\x02", protocol=PROTO_RAW)
    assert r.ok
    assert out == [b"\x01\x02"]


def test_zmodem_header_and_escape():
    # hex header starts with ** ZDLE ZHEX
    h = ZmodemSender._data_subpacket(b"\x18\x00")
    assert h[0] == 0x18  # escaped ZDLE
    assert 0x18 in h
    # crc path used by protocol facade
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_proto_ids_stable():
    assert PROTO_YMODEM == "ymodem"
    assert PROTO_XMODEM == "xmodem"
    assert PROTO_ZMODEM == "zmodem"
