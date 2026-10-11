"""Serial Studio quick-plot frame parser."""

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
