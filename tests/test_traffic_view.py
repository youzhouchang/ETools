"""Traffic monitor helpers and widget behaviour (offscreen)."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from etools.ui.widgets.traffic_view import (  # noqa: E402
    TS_FULL,
    TS_OFF,
    TS_TIME,
    TS_TIME_MS,
    decode_payload,
    format_hex,
    format_timestamp,
    parse_hex_input,
)

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_parse_hex_input_variants():
    assert parse_hex_input("DE AD BE") == bytes.fromhex("DEADBE")
    assert parse_hex_input("0xde,0xad") == bytes.fromhex("DEAD")
    assert parse_hex_input("a") == bytes.fromhex("0A")


def test_format_hex_lines():
    text = format_hex(b"\x00\x41\xFF", 0)
    assert "00 41 FF" in text
    assert text.splitlines()[0].startswith("00000000")


def test_take_complete_lines_keeps_a_trailing_carriage_return():
    from etools.ui.widgets.traffic_view import take_complete_lines

    buf = bytearray(b"internal,1,4,16\r")
    assert take_complete_lines(buf) == []
    assert bytes(buf) == b"internal,1,4,16\r"
    buf.extend(b"\nnext\n")
    assert take_complete_lines(buf) == [b"internal,1,4,16", b"next"]
    assert buf == bytearray()


def test_decode_payload_fallback():
    assert decode_payload("中文".encode(), "utf-8") == "中文"
    assert decode_payload("中文".encode("gbk"), "gbk") == "中文"
    # unknown codec falls back without raising
    assert decode_payload(b"abc", "not-a-codec") == "abc"


def test_format_timestamp_modes():
    now = datetime(2026, 1, 2, 3, 4, 5, 678000)
    assert format_timestamp(TS_OFF, now) == ""
    assert format_timestamp(TS_TIME, now) == "03:04:05  "
    assert format_timestamp(TS_TIME_MS, now) == "03:04:05.678  "
    assert format_timestamp(TS_FULL, now).startswith("2026-01-02 03:04:05.678")


def test_traffic_view_stats_and_filter(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"hello", peer="1.2.3.4:10")
    view.append_tx(b"world")
    rx, tx, rxp, txp = view.stats()
    assert rx == 5 and tx == 5
    assert rxp == 1 and txp == 1

    view.filter_edit.setText("hello")
    text = view.to_plain_text()
    assert "hello" in text
    assert "world" not in text

    view.filter_edit.setText("")
    assert "world" in view.to_plain_text()

    view.set_encoding("gbk")
    view.append_rx("中文".encode("gbk"))
    assert "中文" in view.to_plain_text()

    view.clear()
    assert view.to_plain_text() == ""
    assert view.stats() == (9, 5, 2, 1)  # clear() keeps counters; GBK 中文 is 4 B
    view.reset_stats()
    assert view.stats() == (0, 0, 0, 0)


def test_traffic_view_direction_filter_and_wrap(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"alpha")
    view.append_tx(b"beta")
    view.dir_combo.setCurrentIndex(1)  # RX only
    text = view.to_plain_text()
    assert "alpha" in text
    assert "beta" not in text
    view.dir_combo.setCurrentIndex(2)  # TX only
    text = view.to_plain_text()
    assert "alpha" not in text
    assert "beta" in text
    view.dir_combo.setCurrentIndex(0)
    assert "alpha" in view.to_plain_text() and "beta" in view.to_plain_text()

    view.wrap_check.setChecked(False)
    from PySide6.QtWidgets import QPlainTextEdit

    assert view.view.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    view.wrap_check.setChecked(True)
    assert view.view.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth


def test_traffic_view_joins_split_text_lines(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    for chunk in (b"i", b"n", b"ternal,1,4,16\n", b"i", b"nternal,2,4,16\r\n"):
        view.append_rx(chunk)
    assert [record[1] for record in view._records] == [
        b"internal,1,4,16",
        b"internal,2,4,16",
    ]
    text = view.to_plain_text()
    assert text.count("RX") == 2
    assert "internal,1,4,16" in text
    assert "internal,2,4,16" in text


def test_hex_mode_joins_split_lines(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.set_display_mode("hex")
    view.append_rx(b"i")
    view.append_rx(b"nternal\n")
    assert [record[1] for record in view._records] == [b"internal"]
    assert "69" in view.to_plain_text()


def test_timestamp_checkbox_hides_the_prefix(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"hello\n", peer="1.2.3.4:9")
    assert view.ts_check.isChecked()
    stamped = view.to_plain_text()
    assert "RX" in stamped
    assert "1.2.3.4:9" in stamped
    view.ts_check.setChecked(False)
    plain = view.to_plain_text()
    assert "hello" in plain
    assert "RX" not in plain
    assert "1.2.3.4:9" not in plain
    assert stamped.split("RX", 1)[0].strip() != ""


def test_send_edit_starts_at_one_line_and_grows(qapp):
    from etools.ui.widgets.send_edit import SendEdit

    edit = SendEdit()
    edit.resize(240, edit.height())
    qapp.processEvents()
    one = edit.height()
    edit.setText("a\nb\nc")
    qapp.processEvents()
    assert edit.height() > one
    edit.setText("a\n" * 12)
    qapp.processEvents()
    assert edit.height() < one * 8


def test_merge_window_splits_a_gap_without_a_newline(qapp, monkeypatch):
    from etools.ui.widgets import traffic_view as tv_mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(tv_mod.time, "monotonic", lambda: clock["t"])
    view = tv_mod.TrafficView()
    view.set_merge_ms(50)
    view.append_rx(b"AA")
    clock["t"] += 0.08
    view.append_rx(b"BB")
    assert [record[1] for record in view._records] == [b"AA", b"BB"]


def test_newline_splits_inside_the_merge_window(qapp, monkeypatch):
    from etools.ui.widgets import traffic_view as tv_mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(tv_mod.time, "monotonic", lambda: clock["t"])
    view = tv_mod.TrafficView()
    view.set_merge_ms(500)
    view.append_rx(b"one\n")
    clock["t"] += 0.01
    view.append_rx(b"two\n")
    assert [record[1] for record in view._records] == [b"one", b"two"]


def test_merge_off_keeps_a_slow_split_line(qapp, monkeypatch):
    from etools.ui.widgets import traffic_view as tv_mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(tv_mod.time, "monotonic", lambda: clock["t"])
    view = tv_mod.TrafficView()
    view.set_merge_ms(0)
    view.append_rx(b"i")
    clock["t"] += 1.0
    view.append_rx(b"nternal\n")
    assert [record[1] for record in view._records] == [b"internal"]


def test_traffic_view_merge_frames(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.set_merge_ms(50)
    view.append_rx(b"AA")
    view.append_rx(b"BB")
    # both should coalesce into one record
    assert len(view._records) == 1
    assert view._records[0][1] == b"AABB"
    view.append_tx(b"CC")
    assert len(view._records) == 2


def test_traffic_view_text_export(tmp_path, qapp, monkeypatch):
    from etools.ui.widgets import traffic_view as tv_mod

    view = tv_mod.TrafficView()
    view.append_rx(b"AA", peer="1.2.3.4:1")
    view.append_tx(b"BB")
    out = tmp_path / "t.txt"
    monkeypatch.setattr(
        tv_mod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "Log (*.txt)")),
    )
    view.export_text()
    text = out.read_text(encoding="utf-8")
    assert "RX" in text
    assert "1.2.3.4:1" in text
    assert "41 41" in text
    assert "42 42" in text
    assert "stamp,direction" not in text


def test_interpret_bytes():
    from etools.ui.widgets.hex_inspector import interpret_bytes

    text = interpret_bytes(bytes.fromhex("01020304"), little_endian=True)
    assert "u16 = [513, 1027]" in text
    assert "u32 = [67305985]" in text
    assert "u8  = [1, 2, 3, 4]" in text


def test_traffic_more_panel_stays_above_the_log(qapp):
    from etools.ui.styles import build_stylesheet
    from etools.ui.widgets.traffic_view import TrafficView

    previous = qapp.styleSheet()
    qapp.setStyleSheet(build_stylesheet("light"))
    try:
        view = TrafficView()
        view.resize(800, 480)
        view.show()
        qapp.processEvents()
        view.more_toggle.setChecked(True)
        qapp.processEvents()
        button_bottom = view.save_btn.mapTo(view, view.save_btn.rect().bottomLeft()).y()
        assert view.view.geometry().top() - button_bottom >= 12
    finally:
        qapp.setStyleSheet(previous)


def test_filter_highlight_selections(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"hello world")
    view.append_rx(b"hello again")
    view.filter_edit.setText("hello")
    assert len(view.view.extraSelections()) >= 1
    view.filter_edit.setText("")
    assert view.view.extraSelections() == []


def _count_renders(monkeypatch, view):
    calls = []
    original = view._render_records

    def wrapped():
        calls.append(1)
        original()

    monkeypatch.setattr(view, "_render_records", wrapped)
    return calls


def test_partial_line_is_patched_in_place(qapp, monkeypatch):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"temp=1")
    view._flush()
    renders = _count_renders(monkeypatch, view)
    for chunk in (b"2", b".5", b" ok"):
        view.append_rx(chunk)
        view._flush()
    assert renders == []
    lines = view.view.toPlainText().splitlines()
    assert len(lines) == 1 and lines[0].endswith("temp=12.5 ok")
    view.append_status("note")
    view.append_rx(b"\n")
    view.append_rx(b"next\n")
    view._flush()
    text = view.view.toPlainText()
    assert "temp=12.5 ok" in text and text.rstrip().endswith("next")
    view.shutdown()


def test_full_buffer_does_not_rebuild_view(qapp, monkeypatch):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    for i in range(5005):
        view.append_rx(f"line {i}\n".encode())
    view._flush()
    renders = _count_renders(monkeypatch, view)
    for i in range(50):
        view.append_rx(f"more {i}\n".encode())
        view._flush()
    assert renders == []
    assert view.view.toPlainText().rstrip().endswith("more 49")
    view.shutdown()


def test_filter_highlight_prefers_newest_matches(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view._filter = "hit"
    for i in range(400):
        view.append_rx(f"hit {i}\n".encode())
    view._flush()
    extras = view.view.extraSelections()
    assert 0 < len(extras) <= 201
    newest = max(extras, key=lambda sel: sel.cursor.selectionStart())
    assert newest.cursor.block().text().endswith("hit 399")
    view.shutdown()
