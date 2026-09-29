import struct

from etools.core.trace_stream import (
    TYPE_FLOAT32,
    TYPE_SIGNED,
    TYPE_UNSIGNED,
    TraceFrameParser,
    TraceSample,
    encode_frame,
)


def test_trace_parser_handles_transport_chunk_boundaries() -> None:
    frame = encode_frame(
        [
            TraceSample(0x20000000, TYPE_UNSIGNED, (123).to_bytes(4, "little")),
            TraceSample(0x20000004, TYPE_SIGNED, (-7).to_bytes(2, "little", signed=True)),
            TraceSample(0x20000008, TYPE_FLOAT32, struct.pack("<f", 1.25)),
        ]
    )
    parser = TraceFrameParser()
    assert parser.feed(b"log" + frame[:5]) == []
    samples = parser.feed(frame[5:])
    assert [(s.address, s.value_type, s.raw) for s in samples] == [
        (0x20000000, TYPE_UNSIGNED, b"{\x00\x00\x00"),
        (0x20000004, TYPE_SIGNED, b"\xf9\xff"),
        (0x20000008, TYPE_FLOAT32, struct.pack("<f", 1.25)),
    ]
    assert parser.frames == 1


def test_trace_parser_discards_invalid_header_and_recovers() -> None:
    parser = TraceFrameParser()
    valid = encode_frame([TraceSample(0x10, TYPE_UNSIGNED, b"\x01")])
    bad = b"EVM1" + bytes((99, 0, 0, 0))
    samples = parser.feed(bad + valid)
    assert len(samples) == 1
    assert parser.bad_frames >= 1
