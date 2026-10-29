"""YMODEM / XMODEM framing tests (no hardware)."""

from __future__ import annotations

from etools.core.ymodem import (
    ACK,
    CRC_REQUEST,
    EOT,
    MODE_CHECKSUM,
    NAK,
    PKT_128,
    SOH,
    XmodemSender,
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
    """Received data equals the sent file exactly (no 0x1A padding)."""
    _run_pair(b"hello-firmware" * 5, one_k=False)


def _run_pair(payload: bytes, *, one_k: bool, mode: str = "crc", xmodem: bool = False):
    import queue
    import threading

    to_rx: queue.Queue = queue.Queue()
    to_tx: queue.Queue = queue.Queue()

    def pipe_read(q):
        def _read(timeout: float) -> bytes:
            try:
                return q.get(timeout=timeout)
            except queue.Empty:
                return b""

        return _read

    sender_cls = XmodemSender if xmodem else YmodemSender
    sender = sender_cls(
        write=to_rx.put, read=pipe_read(to_tx), packet_timeout=1.0, one_k=one_k
    )
    receiver = YmodemReceiver(
        write=to_tx.put, read=pipe_read(to_rx), packet_timeout=1.0, mode=mode
    )
    box: dict = {}
    t1 = threading.Thread(target=lambda: box.update(tx=sender.send("app.bin", payload)))
    t2 = threading.Thread(
        target=lambda: box.update(rx=receiver.receive(ymodem=not xmodem, timeout=8.0))
    )
    t2.start()
    t1.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    tx, rx = box.get("tx"), box.get("rx")
    assert tx and tx.ok, tx
    assert rx and rx.ok, rx
    if xmodem:
        assert rx.data.rstrip(b"\x1a") == payload
    else:
        assert rx.filename == "app.bin"
        assert rx.data == payload
    return tx, rx


def test_ymodem_receiver_strips_padding_1k():
    payload = bytes(range(256)) * 5 + b"tail"
    _run_pair(payload, one_k=True)


def test_ymodem_checksum_mode_follows_receiver():
    payload = b"checksum-mode" * 20
    _run_pair(payload, one_k=False, mode=MODE_CHECKSUM)


def test_xmodem_checksum_handshake():
    _run_pair(b"legacy-boot" * 30, one_k=False, mode=MODE_CHECKSUM, xmodem=True)


def test_receiver_acks_duplicate_without_appending():
    sent: list[bytes] = []
    pkt0 = make_packet(0, ymodem_header_block("a.bin", 3))
    pkt1 = make_packet(1, b"abc")
    inbox = bytearray(pkt0 + pkt1 + pkt1 + bytes([EOT]) + make_packet(0, b"\x00" * PKT_128))

    def read(timeout: float) -> bytes:
        if not inbox:
            return b""
        out = bytes(inbox[:64])
        del inbox[:64]
        return out

    rx = YmodemReceiver(write=sent.append, read=read, packet_timeout=0.5)
    result = rx.receive(ymodem=True, timeout=3.0)
    assert result.ok, result.message
    assert result.data == b"abc"


def _feed(inbox: bytearray):
    def read(timeout: float) -> bytes:
        if not inbox:
            return b""
        out = bytes(inbox[:64])
        del inbox[:64]
        return out

    return read


def test_empty_file_has_no_padding():
    _run_pair(b"", one_k=False)


def test_header_size_with_mtime_and_mode():
    name, size = parse_ymodem_header(b"fw.bin\x00" + b"300 14727044460 100644 0\x00")
    assert (name, size) == ("fw.bin", 300)


def test_checksum_header_requests_first_block_with_nak():
    sent: list[bytes] = []
    pkt0 = make_packet(0, ymodem_header_block("a.bin", 3), mode=MODE_CHECKSUM)
    pkt1 = make_packet(1, b"abc", mode=MODE_CHECKSUM)
    tail = bytes([EOT]) + make_packet(0, b"\x00" * PKT_128, mode=MODE_CHECKSUM)
    inbox = bytearray(pkt0 + pkt1 + tail)
    rx = YmodemReceiver(write=sent.append, read=_feed(inbox), packet_timeout=0.5,
                        mode=MODE_CHECKSUM)
    result = rx.receive(ymodem=True, timeout=3.0)
    assert result.ok and result.data == b"abc"
    # NAK to start, ACK the header, then NAK (not 'C') for the first data block.
    assert b"".join(sent)[:3] == bytes([NAK, ACK, NAK])


def test_retransmitted_header_is_acked():
    sent: list[bytes] = []
    pkt0 = make_packet(0, ymodem_header_block("a.bin", 3))
    pkt1 = make_packet(1, b"abc")
    inbox = bytearray(pkt0 + pkt0 + pkt1 + bytes([EOT]) + make_packet(0, b"\x00" * PKT_128))
    rx = YmodemReceiver(write=sent.append, read=_feed(inbox), packet_timeout=0.5)
    result = rx.receive(ymodem=True, timeout=3.0)
    assert result.ok, result.message
    assert result.data == b"abc"
