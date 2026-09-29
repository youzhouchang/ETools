"""Checksum algorithm tests for serial frame trailers."""

from __future__ import annotations

from etools.core.checksum import (
    ALGO_CRC8,
    ALGO_CRC16_CCITT,
    ALGO_CRC16_MODBUS,
    ALGO_CRC32,
    ALGO_NONE,
    ALGO_SUM8,
    ALGO_SUM16,
    ALGO_XOR,
    append_checksum,
    checksum_width,
    compute_checksum,
    verify_checksum,
)


def test_xor_sum():
    assert compute_checksum(b"\x01\x02\x03", ALGO_XOR) == b"\x00"
    assert compute_checksum(b"\x01\x02\x03", ALGO_SUM8) == bytes([6])
    assert compute_checksum(b"\x01\x02\x03", ALGO_SUM16) == (6).to_bytes(2, "little")


def test_crc16_modbus_known_vector():
    # Classic Modbus RTU: 01 03 00 00 00 01 → CRC 84 0A (LE)
    frame = bytes.fromhex("01 03 00 00 00 01")
    assert compute_checksum(frame, ALGO_CRC16_MODBUS) == bytes.fromhex("84 0A")


def test_crc16_ccitt_known_vector():
    # CRC-16/CCITT-FALSE of "123456789" is 0x29B1
    assert compute_checksum(b"123456789", ALGO_CRC16_CCITT) == bytes.fromhex("29 B1")


def test_crc8_and_crc32():
    assert len(compute_checksum(b"abc", ALGO_CRC8)) == 1
    # CRC-32 of b"" is 0x00000000 after xorout with all-ones path
    assert len(compute_checksum(b"abc", ALGO_CRC32)) == 4
    # zlib/ISO-HDLC reference for "123456789" is 0xCBF43926 (stored LE)
    assert compute_checksum(b"123456789", ALGO_CRC32) == (0xCBF43926).to_bytes(4, "little")


def test_append_and_verify():
    body = bytes.fromhex("01 03 00 00 00 01")
    framed = append_checksum(body, ALGO_CRC16_MODBUS)
    assert framed == body + bytes.fromhex("84 0A")
    assert verify_checksum(framed, ALGO_CRC16_MODBUS)
    assert not verify_checksum(framed[:-1] + b"\x00", ALGO_CRC16_MODBUS)
    assert verify_checksum(b"anything", ALGO_NONE)
    assert checksum_width(ALGO_SUM16) == 2
    assert checksum_width(ALGO_CRC32) == 4
