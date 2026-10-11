"""DBC signal decode."""

from etools.core.dbc import parse_dbc

_TEXT = """
BO_ 256 Engine: 8 Vector__XXX
 SG_ RPM : 0|16@1+ (0.1,0) [0|8000] "rpm" Vector__XXX
 SG_ Temp : 7|16@0- (1,-40) [0|0] "C" Vector__XXX
 SG_ Mode M : 16|2@1+ (1,0) [0|3] "" Vector__XXX
 SG_ Extra m1 : 24|8@1+ (1,0) [0|0] "" Vector__XXX
"""


def test_intel_motorola_and_mux():
    db = parse_dbc(_TEXT)
    # RPM little-endian bytes 34 12 -> 0x1234 * 0.1
    # Temp motorola reads those same bytes as 0x3412, then applies offset -40
    # Mode = 1 so Extra is included
    data = bytes([0x34, 0x12, 0x01, 0x07])
    decoded = {item.name: item.value for item in db.decode(256, data)}
    assert decoded["RPM"] == 466.0
    assert decoded["Temp"] == 0x3412 - 40
    assert decoded["Mode"] == 1
    assert decoded["Extra"] == 7

    hidden = {item.name for item in db.decode(256, bytes([0x00, 0x00, 0x00, 0x09]))}
    assert "Extra" not in hidden
    assert "Mode" in hidden


def test_extended_id_flag_is_normalized():
    db = parse_dbc(
        'BO_ 2147483939 Extended: 1 Node\n'
        ' SG_ Value : 0|8@1+ (1,0) [0|255] "" Node\n'
    )
    assert db.decode(0x123, b"\x2a") == []
    decoded = db.decode(0x123, b"\x2a", is_extended=True)
    assert decoded[0].value == 42


def test_short_frames_and_oversized_signals_are_ignored():
    db = parse_dbc(
        "BO_ 1 Short: 8 Node\n"
        ' SG_ TooFar : 60|16@1+ (1,0) [0|0] "" Node\n'
        ' SG_ TooWide : 0|65@1+ (1,0) [0|0] "" Node\n'
    )
    assert db.decode(1, b"\x00") == []
