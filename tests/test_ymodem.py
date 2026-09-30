"""YMODEM / XMODEM framing tests (no hardware)."""

from __future__ import annotations

from etools.core.ymodem import (
    ACK,
    CRC_REQUEST,
    EOT,
    MODE_CHECKSUM,
    PKT_128,
    SOH,
    YmodemReceiver,
    YmodemSender,
    checksum8,
    crc16_xmodem,
    make_packet,
    parse_data_packet,
    parse_ymodem_header,
    ymodem_header_block,
)


def test_crc16_xmodem_known_value():
    # "123456789" CRC-16/XMODEM = 0x31C3
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_make_packet_layout():
    pkt = make_packet(1, b"\x01\x02", one_k=False)
    assert pkt[0] == SOH
    assert pkt[1] == 1
    assert pkt[2] == 0xFE
    assert len(pkt) == 3 + PKT_128 + 2
    assert pkt[3:5] == b"\x01\x02"
    assert pkt[3 + PKT_128 - 1] == 0x1A  # padding


def test_ymodem_header_block():
    body = ymodem_header_block("app.bin", 2048)
    assert body.startswith(b"app.bin\x002048\x00")
    assert len(body) == PKT_128


def test_ymodem_sender_full_session():
    sent: list[bytes] = []
    replies = bytearray()

    def write(data: bytes) -> None:
        sent.append(bytes(data))
        # Acknowledge everything; first byte of session is handshake 'C'
        if not replies:
            replies.append(CRC_REQUEST)
        # After each write, queue ACK for the next read
        replies.extend([ACK] * 4)

    def read(timeout: float) -> bytes:
        if replies:
            out = bytes(replies[:1])
            del replies[:1]
            return out
        return b""

    # Preload handshake
    replies.append(CRC_REQUEST)
    sender = YmodemSender(write=write, read=read, packet_timeout=1.0)
    payload = b"firmware-bytes" * 10
    result = sender.send("app.bin", payload)
    assert result.ok, result.message
    assert result.bytes_sent == len(payload)
    # at least: header packet + data packets + EOT + empty header
    kinds = [p[0] for p in sent if p]
    assert SOH in kinds
    assert EOT in kinds


def test_checksum_mode_packet():
    pkt = make_packet(3, b"AB", one_k=False, mode=MODE_CHECKSUM)
    body = pkt[3 : 3 + PKT_128]
    assert pkt[3 + PKT_128] == checksum8(body)
    parsed = parse_data_packet(pkt, mode=MODE_CHECKSUM)
    assert parsed is not None
    seq, payload = parsed
    assert seq == 3
    assert payload.startswith(b"AB")


def test_parse_ymodem_header():
    name, size = parse_ymodem_header(ymodem_header_block("/tmp/app.bin", 42))
    assert name == "app.bin"
    assert size == 42


def test_ymodem_receiver_roundtrip():
    """Drive a fake sender into YmodemReceiver using a queue pipe."""
    import queue

    to_rx: queue.Queue = queue.Queue()
    to_tx: queue.Queue = queue.Queue()

    def sender_write(data: bytes) -> None:
        to_rx.put(bytes(data))

    def sender_read(timeout: float) -> bytes:
        try:
            return to_tx.get(timeout=timeout)
        except Exception:
            return b""

    def receiver_write(data: bytes) -> None:
        to_tx.put(bytes(data))

    def receiver_read(timeout: float) -> bytes:
        try:
            return to_rx.get(timeout=timeout)
        except Exception:
            return b""

    payload = b"hello-firmware" * 5
    sender = YmodemSender(write=sender_write, read=sender_read, packet_timeout=1.0)
    receiver = YmodemReceiver(write=receiver_write, read=receiver_read, packet_timeout=1.0)

    import threading

    result_box: dict = {}

    def run_tx():
        result_box["tx"] = sender.send("app.bin", payload)

    def run_rx():
        result_box["rx"] = receiver.receive(ymodem=True, timeout=5.0)

    t1 = threading.Thread(target=run_tx)
    t2 = threading.Thread(target=run_rx)
    t2.start()
    t1.start()
    t1.join(timeout=6)
    t2.join(timeout=6)
    rx = result_box.get("rx")
    tx = result_box.get("tx")
    assert tx and tx.ok, tx
    assert rx and rx.ok, rx
    assert rx.filename == "app.bin"
    assert rx.data.startswith(b"hello-firmware")
    assert len(rx.data) >= len(payload)
