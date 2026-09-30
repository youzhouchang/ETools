"""Stream-friendly traffic monitor shared by Serial / Ethernet pages."""

from __future__ import annotations

from datetime import datetime
from typing import IO

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr

MAX_VIEW_CHARS = 400_000
#: Coalesce UI text updates so high-baud streams do not freeze the view.
FLUSH_INTERVAL_MS = 40

#: Display / send encodings offered by the traffic monitor and tool pages.
ENCODINGS: list[tuple[str, str]] = [
    ("utf-8", "UTF-8"),
    ("gbk", "GBK"),
    ("latin-1", "Latin-1"),
]

#: Timestamp formats for record prefixes.
TS_OFF = "off"
TS_TIME = "time"
TS_TIME_MS = "time_ms"
TS_FULL = "full"


def decode_payload(data: bytes, encoding: str = "utf-8") -> str:
    """Decode *data* for display; fall back to UTF-8 replacement on failure."""
    try:
        return data.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def format_hex(data: bytes, base_offset: int = 0) -> str:
    """Classic 16-byte hex dump lines."""
    lines: list[str] = []
    for off in range(0, len(data), 16):
        chunk = data[off : off + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base_offset + off:08X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def parse_hex_input(text: str) -> bytes:
    """Parse 'DE AD BE' / 'DEADBE' / '0xde 0xad' into bytes."""
    cleaned = []
    for tok in text.replace(",", " ").replace(";", " ").split():
        tok = tok.strip().lower()
        if tok.startswith("0x"):
            tok = tok[2:]
        if not tok:
            continue
        if len(tok) % 2:
            tok = "0" + tok
        cleaned.append(tok)
    raw = "".join(cleaned)
    return bytes.fromhex(raw)


def format_timestamp(mode: str, now: datetime | None = None) -> str:
    """Format a record prefix timestamp for *mode* (see TS_* constants)."""
    if mode == TS_OFF:
        return ""
    dt = now or datetime.now()
    if mode == TS_TIME:
        return dt.strftime("%H:%M:%S") + "  "
    if mode == TS_FULL:
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "  "
    # TS_TIME_MS (default)
    return dt.strftime("%H:%M:%S.%f")[:-3] + "  "


class TrafficView(QWidget):
    """RX/TX monitor with hex mode, timestamps, pause, save, filter, stats."""

    stats_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hex_mode = False
        self._records: list[tuple[str, bytes, str, str]] = []
        self._ascii_carry = bytearray()
        self._show_ts = True
        self._ts_mode = TS_TIME_MS
        self._paused = False
        self._autoscroll = True
        self._offset = 0
        self._pending: list[str] = []
        self._notes: list[str] = []
        self._encoding = "utf-8"
        self._filter = ""
        self._dir_filter = "all"
        self._merge_ms = 0
        self._last_stream_key: tuple[str, str] | None = None
        self._last_stream_at = 0.0
        self._auto_log_path: str | None = None
        self._auto_log_fh: IO[str] | None = None
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._rx_pkts = 0
        self._tx_pkts = 0
        self._stats_dirty = False
        self._needs_render = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        from etools.ui.kit import H_TOOL, ghost_button

        # Row 1 — always-visible essentials
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(H_TOOL)
        self.mode_combo.addItem(tr("mon.ascii"), "ascii")
        self.mode_combo.addItem(tr("mon.hex"), "hex")
        bar.addWidget(QLabel(tr("mon.ascii")))
        self._lbl_mode = bar.itemAt(bar.count() - 1).widget()
        bar.addWidget(self.mode_combo)

        self.ts_check = QCheckBox(tr("mon.ts"))
        self.ts_check.setChecked(True)
        self.scroll_check = QCheckBox(tr("mon.autoscroll"))
        self.scroll_check.setChecked(True)
        self.pause_check = QCheckBox(tr("mon.pause"))
        bar.addWidget(self.ts_check)
        bar.addWidget(self.scroll_check)
        bar.addWidget(self.pause_check)

        self.more_check = QCheckBox(tr("mon.more"))
        self.more_check.setToolTip(tr("mon.more_tip"))
        bar.addWidget(self.more_check)
        bar.addStretch(1)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statsLabel")
        bar.addWidget(self.stats_label)
        self.clear_btn = ghost_button(tr("mon.clear"), height=H_TOOL)
        self.save_btn = ghost_button(tr("mon.save"), height=H_TOOL)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        # Row 2 — search (always on, it's the primary discovery affordance)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.filter_edit = QLineEdit()
        self.filter_edit.setFixedHeight(H_TOOL)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setPlaceholderText(tr("mon.filter_ph"))
        self.filter_hint = QLabel(tr("mon.filter"))
        self.dir_combo = QComboBox()
        self.dir_combo.setFixedHeight(H_TOOL)
        self.dir_combo.addItem(tr("mon.dir.all"), "all")
        self.dir_combo.addItem(tr("mon.dir.rx"), "rx")
        self.dir_combo.addItem(tr("mon.dir.tx"), "tx")
        self.copy_btn = ghost_button(tr("mon.copy"), height=H_TOOL)
        filter_row.addWidget(self.filter_hint)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.dir_combo)
        filter_row.addWidget(self.copy_btn)
        root.addLayout(filter_row)

        # Row 3 — advanced options, collapsed by default (less chrome)
        self.advanced_host = QWidget()
        advanced_row = QHBoxLayout(self.advanced_host)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setSpacing(6)
        self.ts_combo = QComboBox()
        self.ts_combo.setFixedHeight(H_TOOL)
        self.ts_combo.addItem(tr("mon.ts.time_ms"), TS_TIME_MS)
        self.ts_combo.addItem(tr("mon.ts.time"), TS_TIME)
        self.ts_combo.addItem(tr("mon.ts.full"), TS_FULL)
        self.ts_combo.addItem(tr("mon.ts.off"), TS_OFF)
        self.wrap_check = QCheckBox(tr("mon.wrap"))
        self.wrap_check.setChecked(True)
        self.merge_spin = QSpinBox()
        self.merge_spin.setRange(0, 5000)
        self.merge_spin.setSuffix(" ms")
        self.merge_spin.setFixedWidth(90)
        self.merge_spin.setFixedHeight(H_TOOL)
        self.merge_spin.setToolTip(tr("mon.merge_tip"))
        self.lbl_merge = QLabel(tr("mon.merge"))
        self.auto_log_check = QCheckBox(tr("mon.auto_log"))
        self.auto_log_check.setToolTip(tr("mon.auto_log_tip"))
        self.eye_care_check = QCheckBox(tr("mon.eye_care"))
        self.eye_care_check.setToolTip(tr("mon.eye_care_tip"))
        self.export_csv_btn = ghost_button(tr("mon.export_csv"), height=H_TOOL)
        self.inspect_btn = ghost_button(tr("inspector.title"), height=H_TOOL)
        self.stats_reset_btn = ghost_button(tr("mon.reset_stats"), height=H_TOOL)
        advanced_row.addWidget(self.ts_combo)
        advanced_row.addWidget(self.wrap_check)
        advanced_row.addWidget(self.lbl_merge)
        advanced_row.addWidget(self.merge_spin)
        advanced_row.addWidget(self.eye_care_check)
        advanced_row.addWidget(self.auto_log_check)
        advanced_row.addWidget(self.export_csv_btn)
        advanced_row.addWidget(self.inspect_btn)
        advanced_row.addWidget(self.stats_reset_btn)
        advanced_row.addStretch(1)
        self.advanced_host.setVisible(False)
        root.addWidget(self.advanced_host)
        self.more_check.toggled.connect(self.advanced_host.setVisible)
        self.eye_care_check.toggled.connect(self._on_eye_care_toggled)

        self.view = QPlainTextEdit()
        self.view.setUndoRedoEnabled(False)
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText(tr("serial.placeholder"))
        root.addWidget(self.view, 1)
        self._apply_eye_care(self._load_eye_care())
        # Ctrl+S saves the log; Ctrl+F focuses the filter box.
        from PySide6.QtGui import QKeySequence, QShortcut

        self._save_sc = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_sc.activated.connect(self.save_as)
        self._filter_sc = QShortcut(QKeySequence.StandardKey.Find, self)
        self._filter_sc.activated.connect(self.filter_edit.setFocus)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.ts_check.toggled.connect(self._on_flags)
        self.ts_combo.currentIndexChanged.connect(self._on_ts_mode)
        self.scroll_check.toggled.connect(self._on_flags)
        self.pause_check.toggled.connect(self._on_pause)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        self.dir_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.wrap_check.toggled.connect(self._on_wrap_toggled)
        self.merge_spin.valueChanged.connect(self._on_merge_changed)
        self.copy_btn.clicked.connect(self._copy_all)
        self.stats_reset_btn.clicked.connect(self.reset_stats)
        self.auto_log_check.toggled.connect(self._on_auto_log_toggled)
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.inspect_btn.clicked.connect(self._open_inspector)
        self.save_btn.clicked.connect(self.save_as)
        self.clear_btn.clicked.connect(self.clear)
        self.view.setLineWrapMode(self.view.LineWrapMode.WidgetWidth)
        self._refresh_stats()

    def retranslate(self) -> None:
        self._lbl_mode.setText(tr("mon.ascii"))
        self.mode_combo.setItemText(0, tr("mon.ascii"))
        self.mode_combo.setItemText(1, tr("mon.hex"))
        self.ts_check.setText(tr("mon.ts"))
        self.ts_combo.setItemText(0, tr("mon.ts.time_ms"))
        self.ts_combo.setItemText(1, tr("mon.ts.time"))
        self.ts_combo.setItemText(2, tr("mon.ts.full"))
        self.ts_combo.setItemText(3, tr("mon.ts.off"))
        self.scroll_check.setText(tr("mon.autoscroll"))
        self.pause_check.setText(tr("mon.pause"))
        self.more_check.setText(tr("mon.more"))
        self.more_check.setToolTip(tr("mon.more_tip"))
        self.eye_care_check.setText(tr("mon.eye_care"))
        self.eye_care_check.setToolTip(tr("mon.eye_care_tip"))
        self.filter_hint.setText(tr("mon.filter"))
        self.filter_edit.setPlaceholderText(tr("mon.filter_ph"))
        self.dir_combo.setItemText(0, tr("mon.dir.all"))
        self.dir_combo.setItemText(1, tr("mon.dir.rx"))
        self.dir_combo.setItemText(2, tr("mon.dir.tx"))
        self.wrap_check.setText(tr("mon.wrap"))
        self.lbl_merge.setText(tr("mon.merge"))
        self.merge_spin.setToolTip(tr("mon.merge_tip"))
        self.copy_btn.setText(tr("mon.copy"))
        self.stats_reset_btn.setText(tr("mon.reset_stats"))
        self.auto_log_check.setText(tr("mon.auto_log"))
        self.auto_log_check.setToolTip(tr("mon.auto_log_tip"))
        self.export_csv_btn.setText(tr("mon.export_csv"))
        self.inspect_btn.setText(tr("inspector.title"))
        self.save_btn.setText(tr("mon.save"))
        self.clear_btn.setText(tr("mon.clear"))
        self._refresh_stats()

    def set_placeholder(self, text: str) -> None:
        self.view.setPlaceholderText(text)

    def set_encoding(self, encoding: str) -> None:
        self._encoding = encoding or "utf-8"
        if self._records:
            self._render_records()

    @property
    def encoding(self) -> str:
        return self._encoding

    def stats(self) -> tuple[int, int, int, int]:
        """Return (rx_bytes, tx_bytes, rx_packets, tx_packets)."""
        return self._rx_bytes, self._tx_bytes, self._rx_pkts, self._tx_pkts

    def reset_stats(self) -> None:
        self._rx_bytes = self._tx_bytes = self._rx_pkts = self._tx_pkts = 0
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        self._stats_dirty = False
        self.stats_label.setText(
            tr(
                "mon.stats",
                rx=self._rx_bytes,
                tx=self._tx_bytes,
                rxp=self._rx_pkts,
                txp=self._tx_pkts,
            )
        )
        self.stats_changed.emit()

    def _on_mode_changed(self) -> None:
        self._hex_mode = self.mode_combo.currentData() == "hex"
        self._render_records()

    def _on_flags(self) -> None:
        self._show_ts = self.ts_check.isChecked() and self.ts_combo.currentData() != TS_OFF
        self._autoscroll = self.scroll_check.isChecked()
        if self._records:
            self._render_records()

    def _on_ts_mode(self) -> None:
        self._ts_mode = str(self.ts_combo.currentData() or TS_TIME_MS)
        self._show_ts = self.ts_check.isChecked() and self._ts_mode != TS_OFF
        if self._records:
            self._render_records()

    def _on_pause(self) -> None:
        self._paused = self.pause_check.isChecked()

    def _on_filter_changed(self, *_args) -> None:
        self._filter = (self.filter_edit.text() or "").strip()
        self._dir_filter = str(self.dir_combo.currentData() or "all")
        self._render_records()

    def _on_wrap_toggled(self, on: bool) -> None:
        mode = (
            self.view.LineWrapMode.WidgetWidth
            if on
            else self.view.LineWrapMode.NoWrap
        )
        self.view.setLineWrapMode(mode)

    def _on_merge_changed(self, value: int) -> None:
        self._merge_ms = int(value)

    def set_merge_ms(self, value: int) -> None:
        self.merge_spin.setValue(max(0, int(value)))
        self._merge_ms = self.merge_spin.value()

    @staticmethod
    def _load_eye_care() -> bool:
        from etools.config import get_config

        return bool((get_config().extra or {}).get("eye_care_log"))

    def _on_eye_care_toggled(self, on: bool) -> None:
        from etools.config import get_config, save_config

        cfg = get_config()
        extra = dict(cfg.extra or {})
        extra["eye_care_log"] = bool(on)
        cfg.extra = extra
        try:
            save_config()
        except OSError:
            pass
        self._apply_eye_care(on)

    def _apply_eye_care(self, on: bool) -> None:
        """Soft green receive pane (qtSerial-style) for long monitoring sessions."""
        self.eye_care_check.blockSignals(True)
        self.eye_care_check.setChecked(bool(on))
        self.eye_care_check.blockSignals(False)
        if on:
            self.view.setStyleSheet(
                "QPlainTextEdit#logView {"
                " background: #CCE8CF;"
                " color: #1F3D24;"
                " border: 1px solid #9BBF9F;"
                " border-radius: 6px;"
                " font-family: \"Cascadia Code\", \"Consolas\", \"JetBrains Mono\", monospace;"
                " font-size: 11px;"
                " padding: 6px;"
                " selection-background-color: #3B9EFF;"
                " selection-color: #0B1220;"
                "}"
            )
        else:
            self.view.setStyleSheet("")

    def _on_auto_log_toggled(self, on: bool) -> None:
        self._close_auto_log()
        if not on:
            self._auto_log_path = None
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.save_title"), "traffic_auto.log", tr("mon.log_filter")
        )
        if not path:
            self.auto_log_check.blockSignals(True)
            self.auto_log_check.setChecked(False)
            self.auto_log_check.blockSignals(False)
            return
        self._auto_log_path = path
        try:
            self._auto_log_fh = open(  # noqa: SIM115 — kept open for the session
                path, "a", encoding="utf-8", errors="replace"
            )
        except OSError:
            self._auto_log_path = None
            self.auto_log_check.blockSignals(True)
            self.auto_log_check.setChecked(False)
            self.auto_log_check.blockSignals(False)
            return
        self.append_status(path)

    def _close_auto_log(self) -> None:
        fh, self._auto_log_fh = self._auto_log_fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def _auto_log_line(self, line: str) -> None:
        if not self._auto_log_path or self._auto_log_fh is None:
            return
        try:
            self._auto_log_fh.write(line + "\n")
            self._auto_log_fh.flush()
        except OSError:
            self._close_auto_log()
            self._auto_log_path = None
            self.auto_log_check.blockSignals(True)
            self.auto_log_check.setChecked(False)
            self.auto_log_check.blockSignals(False)

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self.to_plain_text()
        if text:
            QApplication.clipboard().setText(text)
            self.append_status(tr("mon.copied"))

    def _stamp(self) -> str:
        if not self._show_ts:
            return ""
        return format_timestamp(self._ts_mode)

    def append_status(self, text: str) -> None:
        line = f"{self._stamp()}{text}"
        self._notes.append(line)
        self._auto_log_line(line)
        self._schedule_flush()

    def append_rx(self, data: bytes, peer: str = "") -> None:
        if data:
            self._rx_bytes += len(data)
            self._rx_pkts += 1
            self._stats_dirty = True
            self._auto_log_line(f"{self._stamp()}{tr('mon.rx')} {data.hex(' ').upper()}")
        self._append_stream(tr("mon.rx"), data, peer)

    def append_tx(self, data: bytes | str, peer: str = "") -> None:
        if isinstance(data, str):
            raw = data.encode("utf-8", errors="replace")
        else:
            raw = data
        if raw:
            self._tx_bytes += len(raw)
            self._tx_pkts += 1
            self._stats_dirty = True
            self._auto_log_line(f"{self._stamp()}{tr('mon.tx')} {raw.hex(' ').upper()}")
        self._append_stream(tr("mon.tx"), raw, peer)

    def _format_record(self, tag: str, data: bytes, peer: str, stamp: str) -> str:
        prefix = f"{stamp}{tag}"
        if peer:
            prefix += f" [{peer}]"
        if self._hex_mode:
            return f"{prefix}\n{format_hex(data, self._offset)}"
        return f"{prefix}  {decode_payload(data, self._encoding)}"

    def _append_stream(self, tag: str, data: bytes, peer: str = "") -> None:
        if self._paused or not data:
            return
        import time

        now = time.monotonic()
        key = (tag, peer)
        if (
            self._merge_ms > 0
            and self._records
            and self._last_stream_key == key
            and (now - self._last_stream_at) * 1000.0 <= self._merge_ms
        ):
            # Coalesce consecutive chunks of the same direction/peer into one record.
            old_tag, old_data, old_peer, stamp = self._records[-1]
            self._records[-1] = (old_tag, old_data + bytes(data), old_peer, stamp)
            self._offset += len(data)
            # Merged line rewrites the previous display row — rebuild on flush.
            self._needs_render = True
        else:
            record = (tag, bytes(data), peer, self._stamp())
            self._records.append(record)
            if self._matches_filter(tag, peer, record[1]):
                self._pending.append(self._format_record(tag, record[1], peer, record[3]))
            self._offset += len(record[1])
        self._last_stream_key = key
        self._last_stream_at = now
        if len(self._records) > 5000:
            del self._records[: len(self._records) - 5000]
            self._needs_render = True
        self._schedule_flush()

    def set_display_mode(self, mode: str) -> None:
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def _matches_filter(self, tag: str, peer: str, data: bytes) -> bool:
        rx_tag = tr("mon.rx")
        tx_tag = tr("mon.tx")
        if self._dir_filter == "rx" and tag != rx_tag:
            return False
        if self._dir_filter == "tx" and tag != tx_tag:
            return False
        if not self._filter:
            return True
        needle = self._filter.lower()
        if needle in tag.lower() or (peer and needle in peer.lower()):
            return True
        if self._hex_mode:
            body = format_hex(data).lower()
        else:
            body = decode_payload(data, self._encoding).lower()
        return needle in body

    def _render_records(self) -> None:
        self._pending.clear()
        self._needs_render = False
        self._offset = 0
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        for tag, data, peer, stamp in self._records:
            if not self._matches_filter(tag, peer, data):
                self._offset += len(data)
                continue
            self._pending.append(self._format_record(tag, data, peer, stamp))
            self._offset += len(data)
        self._paint_pending()
        self.view.setUpdatesEnabled(True)

    def _schedule_flush(self) -> None:
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _paint_pending(self) -> None:
        lines = self._notes + self._pending
        self._notes.clear()
        self._pending.clear()
        if not lines:
            return
        chunk = "\n".join(lines)
        self.view.appendPlainText(chunk)
        doc = self.view.document()
        if doc.characterCount() > MAX_VIEW_CHARS:
            cursor = self.view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Down,
                cursor.MoveMode.KeepAnchor,
                200,
            )
            cursor.removeSelectedText()
        if self._filter:
            self._highlight_filter()
        if self._autoscroll:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _flush(self) -> None:
        self._flush_timer.stop()
        if self._needs_render:
            self._render_records()
        else:
            self._paint_pending()
        if self._stats_dirty:
            self._refresh_stats()

    def _highlight_filter(self) -> None:
        """Highlight keyword matches using ExtraSelections (non-destructive)."""
        from PySide6.QtGui import QColor, QTextCursor
        from PySide6.QtWidgets import QTextEdit

        needle = self._filter
        if not needle:
            self.view.setExtraSelections([])
            return
        color = QColor(245, 166, 35, 80)
        text = self.view.toPlainText()
        low_text = text.lower()
        low_needle = needle.lower()
        extras: list[QTextEdit.ExtraSelection] = []
        pos = 0
        while True:
            idx = low_text.find(low_needle, pos)
            if idx < 0:
                break
            sel = QTextEdit.ExtraSelection()
            cursor = self.view.textCursor()
            cursor.setPosition(idx)
            cursor.setPosition(idx + len(needle), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            sel.format.setBackground(color)
            extras.append(sel)
            pos = idx + max(1, len(needle))
            if len(extras) > 200:
                break
        self.view.setExtraSelections(extras)

    def clear(self) -> None:
        self._pending.clear()
        self._notes.clear()
        self._records.clear()
        self._ascii_carry.clear()
        self._offset = 0
        self._needs_render = False
        self.view.setExtraSelections([])
        self.view.clear()

    def to_plain_text(self) -> str:
        self._flush()
        return self.view.toPlainText()

    def _open_inspector(self) -> None:
        from etools.ui.widgets.hex_inspector import HexInspectorDialog

        seed = self.view.textCursor().selectedText().strip()
        if not seed:
            # Fall back to last RX/TX hex-ish content.
            for _tag, data, _peer, _stamp in reversed(self._records):
                if data:
                    seed = data.hex(" ")
                    break
        HexInspectorDialog(seed, self).exec()

    def export_csv(self) -> None:
        """Export records as CSV: time,direction,peer,hex,text."""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.export_csv"), "traffic.csv", "CSV (*.csv);;All (*.*)"
        )
        if not path:
            return
        import csv

        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["stamp", "direction", "peer", "hex", "text"])
            for tag, data, peer, stamp in self._records:
                writer.writerow(
                    [
                        stamp.strip(),
                        tag,
                        peer,
                        data.hex(" ").upper(),
                        decode_payload(data, self._encoding),
                    ]
                )
        self.append_status(path)

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.save_title"), "traffic.log", tr("mon.log_filter")
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(self.to_plain_text())
        self.append_status(path)
