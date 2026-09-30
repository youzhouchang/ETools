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


def test_traffic_view_csv_export(tmp_path, qapp, monkeypatch):
    from etools.ui.widgets import traffic_view as tv_mod

    view = tv_mod.TrafficView()
    view.append_rx(b"AA", peer="1.2.3.4:1")
    view.append_tx(b"BB")
    out = tmp_path / "t.csv"
    monkeypatch.setattr(
        tv_mod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")),
    )
    view.export_csv()
    text = out.read_text(encoding="utf-8")
    assert "stamp,direction,peer,hex,text" in text
    assert "AA" in text.upper() or "41 41" in text.upper()
    assert "BB" in text.upper() or "42 42" in text.upper()


def test_interpret_bytes():
    from etools.ui.widgets.hex_inspector import interpret_bytes

    text = interpret_bytes(bytes.fromhex("01020304"), little_endian=True)
    assert "u16 = [513, 1027]" in text
    assert "u32 = [67305985]" in text
    assert "u8  = [1, 2, 3, 4]" in text


def test_filter_highlight_selections(qapp):
    from etools.ui.widgets.traffic_view import TrafficView

    view = TrafficView()
    view.append_rx(b"hello world")
    view.append_rx(b"hello again")
    view.filter_edit.setText("hello")
    assert len(view.view.extraSelections()) >= 1
    view.filter_edit.setText("")
    assert view.view.extraSelections() == []
