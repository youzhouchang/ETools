"""Serial Studio quick-plot frame parser."""

import struct

from etools.core.studio_frames import StudioFrameParser


def test_quick_plot_frame_and_names():
    parser = StudioFrameParser()
    parser.set_names("ax, ay")
    assert parser.feed(b"noise /*1.5, -2, 3*/ tail") == [{"ax": 1.5, "ay": -2.0, "f3": 3.0}]
    assert parser.feed(b"") == []


def test_quick_plot_split_across_chunks():
    parser = StudioFrameParser()
    assert parser.feed(b"/*1.25,") == []
    assert parser.feed(b"4*/") == [{"f1": 1.25, "f2": 4.0}]


def test_json_numeric_object():
    parser = StudioFrameParser()
    frames = parser.feed(b'pre {"temp": 21.5, "ok": true, "name": "x"} post')
    assert frames == [{"temp": 21.5}]


def test_non_finite_values_are_rejected():
    parser = StudioFrameParser()
    assert parser.feed(b"/*nan,1*/") == []
    parser.reset()
    assert parser.feed(b'{"temp":1e999}') == []


def test_split_utf8_json_key_is_preserved():
    parser = StudioFrameParser()
    raw = '{"温度":21}'.encode()
    split = raw.index("温".encode()) + 1
    assert parser.feed(raw[:split]) == []
    assert parser.feed(raw[split:]) == [{"温度": 21.0}]


def test_key_value_lines_split_across_chunks():
    parser = StudioFrameParser()
    parser.set_mode("kv")
    assert parser.feed(b"temp=21.5 hum=") == []
    assert parser.feed(b"40\n") == [{"temp": 21.5, "hum": 40.0}]


def test_hex_struct_template_and_split_header():
    parser = StudioFrameParser()
    parser.set_mode("hex")
    parser.set_hex_template("AA 55 u16be:v f32le:x")
    payload = bytes.fromhex("AA 55 00 0A") + struct.pack("<f", 1.5)
    assert parser.feed(payload[:3]) == []
    assert parser.feed(payload[3:]) == [{"v": 10.0, "x": 1.5}]
