"""Serial Studio quick-plot frame parser."""

from __future__ import annotations

import os
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from etools.core.studio_frames import StudioFrameParser  # noqa: E402

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


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


def test_script_plot_opens_the_serial_plot(qapp):
    from etools.ui.tools.serial_page import SerialPage

    page = SerialPage()
    assert not page.section_tabs._stack.isVisible()
    assert page.lua_plot("list", [1, 2, 3]) == 1
    assert page.section_tabs._buttons[0].isChecked()
    assert not page.section_tabs._stack.isHidden()
    assert page.work_tabs.currentIndex() == 0
    assert list(page.studio.plot._series["f1"]) == [1.0]


def test_script_frames_draw_without_opening_the_section(qapp):
    from etools.ui.widgets.studio_plot import StudioPlotPanel

    panel = StudioPlotPanel()
    panel.names.setText("a,b,c")
    assert panel.accept_script("map", {"a": 5, "b": 4, "note": "x"}) == [{"a": 5.0, "b": 4.0}]
    assert list(panel.plot._series["a"]) == [5.0]
    assert panel.accept_script("list", [6, 4, 16]) == [{"a": 6.0, "b": 4.0, "c": 16.0}]
    assert panel.accept_script("text", "/*7,4,16*/") == [{"a": 7.0, "b": 4.0, "c": 16.0}]
    panel.parse_mode.setCurrentIndex(panel.parse_mode.findData("kv"))
    assert panel.accept_script("text", "a=8,b=4") == [{"a": 8.0, "b": 4.0}]
