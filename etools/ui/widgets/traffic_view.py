"""Stream-friendly traffic monitor shared by Serial / Ethernet pages."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import IO

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr

MAX_VIEW_CHARS = 400_000
MAX_RECORD_BYTES = 64 * 1024
MAX_BUFFER_BYTES = 4 * 1024 * 1024
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
        self._records: deque[tuple[str, bytes, str, str]] = deque()
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
        self._auto_log_dirty = False
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._rx_pkts = 0
        self._tx_pkts = 0
        self._stats_dirty = False
        self._needs_render = False
        self._buffer_bytes = 0
        self._replay_records = []
        self._replay_index = 0
        self._replay_timer = QTimer(self)
        self._replay_timer.setSingleShot(True)
        self._replay_timer.timeout.connect(self._replay_next)
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        from etools.ui.kit import H_TOOL, ghost_button

        # Row 1 — always-visible essentials
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(H_TOOL)
        self.mode_combo.addItem(tr("mon.ascii"), "ascii")
        self.mode_combo.addItem(tr("mon.hex"), "hex")
        bar.addWidget(QLabel(tr("mon.display")))
        self._lbl_mode = bar.itemAt(bar.count() - 1).widget()
        bar.addWidget(self.mode_combo)

        self.ts_check = QCheckBox(tr("mon.ts"))
        self.ts_check.setChecked(True)
        self.scroll_check = QCheckBox(tr("mon.autoscroll"))
        self.scroll_check.setChecked(True)
        self.pause_check = QCheckBox(tr("mon.pause"))
        self.pause_check.setToolTip(tr("mon.pause_tip"))
        bar.addWidget(self.ts_check)
        bar.addWidget(self.scroll_check)
        bar.addWidget(self.pause_check)

        bar.addStretch(1)

        # RX/TX counters live in the global status bar (one place, with Clear).
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

        # Additional monitor controls remain directly accessible.
        self.advanced_host = QWidget()
        advanced_row = QGridLayout(self.advanced_host)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setHorizontalSpacing(10)
        advanced_row.setVerticalSpacing(8)
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
        self.capture_btn = ghost_button(tr("mon.capture"), height=H_TOOL)
        self.replay_btn = ghost_button(tr("mon.replay"), height=H_TOOL)
        self.replay_stop_btn = ghost_button(tr("script.stop"), height=H_TOOL)
        self.replay_stop_btn.setEnabled(False)
        self.capture_btn.clicked.connect(self.export_capture)
        self.replay_btn.clicked.connect(self.replay_capture)
        self.replay_stop_btn.clicked.connect(self.stop_replay)

        # Compact left-aligned rows — buttons must not stretch across the pane.
        for btn in (
            self.export_csv_btn,
            self.inspect_btn,
            self.capture_btn,
            self.replay_btn,
            self.replay_stop_btn,
        ):
            btn.setFixedHeight(H_TOOL)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Two compact rows (not three): options, then actions.
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self.ts_combo)
        row1.addWidget(self.wrap_check)
        row1.addWidget(self.lbl_merge)
        row1.addWidget(self.merge_spin)
        row1.addSpacing(12)
        row1.addWidget(self.eye_care_check)
        row1.addWidget(self.auto_log_check)
        row1.addStretch(1)
        advanced_row.addLayout(row1, 0, 0)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self.export_csv_btn)
        row2.addWidget(self.inspect_btn)
        row2.addSpacing(8)
        row2.addWidget(self.capture_btn)
        row2.addWidget(self.replay_btn)
        row2.addWidget(self.replay_stop_btn)
        row2.addStretch(1)
        advanced_row.addLayout(row2, 1, 0)
        advanced_row.setVerticalSpacing(6)
        advanced_row.setColumnStretch(0, 1)
        self.replay_btn.setToolTip(tr("mon.replay_tip"))
        # Fixed height so option buttons never paint over the log pane.
        self.advanced_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.advanced_host.setContentsMargins(0, 0, 0, 2)
        # Two tool-height rows + row gap — keep the log pane from sliding under.
        self.advanced_host.setFixedHeight(H_TOOL * 2 + 6 + 4)
        root.addWidget(self.advanced_host, 0)
        root.addSpacing(6)
        self.eye_care_check.toggled.connect(self._on_eye_care_toggled)

        self.view = QPlainTextEdit()
        self.view.setUndoRedoEnabled(False)
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText(tr("serial.placeholder"))
        self.view.setMinimumHeight(80)
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
        self.eye_care_check.toggled.connect(self._on_eye_care_toggled)
        self.auto_log_check.toggled.connect(self._on_auto_log_toggled)
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.inspect_btn.clicked.connect(self._open_inspector)
        self.save_btn.clicked.connect(self.save_as)
        self.clear_btn.clicked.connect(self.clear)
        self.view.setLineWrapMode(self.view.LineWrapMode.WidgetWidth)
        self._refresh_stats()

    def retranslate(self) -> None:
        self.capture_btn.setText(tr("mon.capture"))
        self.replay_btn.setText(tr("mon.replay"))
        self.replay_stop_btn.setText(tr("script.stop"))
        self.pause_check.setToolTip(tr("mon.pause_tip"))
        self._lbl_mode.setText(tr("mon.display"))
        self.mode_combo.setItemText(0, tr("mon.ascii"))
        self.mode_combo.setItemText(1, tr("mon.hex"))
        self.ts_check.setText(tr("mon.ts"))
        self.ts_combo.setItemText(0, tr("mon.ts.time_ms"))
        self.ts_combo.setItemText(1, tr("mon.ts.time"))
        self.ts_combo.setItemText(2, tr("mon.ts.full"))
        self.ts_combo.setItemText(3, tr("mon.ts.off"))
        self.scroll_check.setText(tr("mon.autoscroll"))
        self.pause_check.setText(tr("mon.pause"))
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
        """Counters are shown in the global status bar (stats_changed)."""
        self._stats_dirty = False
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
        if not self._paused:
            self._render_records()

    def _on_filter_changed(self, *_args) -> None:
        self._filter = (self.filter_edit.text() or "").strip()
        self._dir_filter = str(self.dir_combo.currentData() or "all")
        self._render_records()

    def _on_wrap_toggled(self, on: bool) -> None:
        mode = self.view.LineWrapMode.WidgetWidth if on else self.view.LineWrapMode.NoWrap
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
                ' font-family: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;'
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
        except OSError as exc:
            self._auto_log_path = None
            self.auto_log_check.blockSignals(True)
            self.auto_log_check.setChecked(False)
            self.auto_log_check.blockSignals(False)
            self.append_status(str(exc))
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
            self._auto_log_dirty = True
            self._schedule_flush()
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
            self._auto_log_line(f"{datetime.now().isoformat()} RX [{peer}] {data.hex(' ').upper()}")
        self._append_stream("rx", data, peer)

    def append_tx(self, data: bytes | str, peer: str = "") -> None:
        if isinstance(data, str):
            raw = data.encode("utf-8", errors="replace")
        else:
            raw = data
        if raw:
            self._tx_bytes += len(raw)
            self._tx_pkts += 1
            self._stats_dirty = True
            self._auto_log_line(f"{datetime.now().isoformat()} TX [{peer}] {raw.hex(' ').upper()}")
        self._append_stream("tx", raw, peer)

    def _format_record(self, tag: str, data: bytes, peer: str, stamp: str) -> str:
        shown_stamp = ""
        if self._show_ts:
            shown_stamp = format_timestamp(self._ts_mode, datetime.fromisoformat(stamp))
        prefix = f"{shown_stamp}{tr('mon.' + tag)}"
        if peer:
            prefix += f" [{peer}]"
        if self._hex_mode:
            return f"{prefix}\n{format_hex(data, self._offset)}"
        return f"{prefix}  {decode_payload(data, self._encoding)}"

    def _append_stream(self, tag: str, data: bytes, peer: str = "") -> None:
        if not data:
            return
        for start in range(0, len(data), MAX_RECORD_BYTES):
            self._append_chunk(tag, data[start : start + MAX_RECORD_BYTES], peer)

    def _append_chunk(
        self, tag: str, data: bytes, peer: str = "", timestamp: str | None = None
    ) -> None:
        import time

        now = time.monotonic()
        key = (tag, peer)
        if (
            self._merge_ms > 0
            and self._records
            and self._last_stream_key == key
            and (now - self._last_stream_at) * 1000.0 <= self._merge_ms
            and len(self._records[-1][1]) + len(data) <= MAX_RECORD_BYTES
            and timestamp is None
        ):
            # Coalesce consecutive chunks of the same direction/peer into one record.
            old_tag, old_data, old_peer, stamp = self._records[-1]
            self._records[-1] = (old_tag, old_data + bytes(data), old_peer, stamp)
            self._offset += len(data)
            # Merged line rewrites the previous display row — rebuild on flush.
            self._needs_render = True
        else:
            record = (tag, bytes(data), peer, timestamp or datetime.now().isoformat())
            self._records.append(record)
            if not self._paused and self._matches_filter(tag, peer, record[1]):
                self._pending.append(self._format_record(tag, record[1], peer, record[3]))
            self._offset += len(record[1])
        self._last_stream_key = key
        self._last_stream_at = now
        self._buffer_bytes += len(data)
        while len(self._records) > 5000 or self._buffer_bytes > MAX_BUFFER_BYTES:
            self._buffer_bytes -= len(self._records.popleft()[1])
            self._needs_render = True
        self._schedule_flush()

    def set_display_mode(self, mode: str) -> None:
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def _matches_filter(self, tag: str, peer: str, data: bytes) -> bool:
        rx_tag = "rx"
        tx_tag = "tx"
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
        if self._paused:
            self._needs_render = True
            return
        self._pending.clear()
        self._needs_render = False
        self._offset = self._buffer_bytes
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        rendered = []
        chars = 0
        for tag, data, peer, stamp in reversed(self._records):
            self._offset -= len(data)
            if not self._matches_filter(tag, peer, data):
                continue
            line = self._format_record(tag, data, peer, stamp)
            rendered.append(line)
            chars += len(line)
            if chars >= MAX_VIEW_CHARS:
                break
        self._pending.extend(reversed(rendered))
        self._offset = self._buffer_bytes
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
            cursor.setPosition(doc.characterCount() - MAX_VIEW_CHARS, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        if self._filter:
            self._highlight_filter()
        if self._autoscroll:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _flush(self) -> None:
        self._flush_timer.stop()
        if self._auto_log_fh is not None and self._auto_log_dirty:
            try:
                self._auto_log_fh.flush()
                self._auto_log_dirty = False
            except OSError as exc:
                self._close_auto_log()
                self._auto_log_path = None
                self.auto_log_check.blockSignals(True)
                self.auto_log_check.setChecked(False)
                self.auto_log_check.blockSignals(False)
                self.append_status(str(exc))
        if self._paused:
            # Keep status/error notes visible while the stream pane is frozen.
            self._paint_notes()
            if self._stats_dirty:
                self._refresh_stats()
            return
        if self._needs_render:
            self._render_records()
        else:
            self._paint_pending()
        if self._stats_dirty:
            self._refresh_stats()

    def _paint_notes(self) -> None:
        if not self._notes:
            return
        chunk = "\n".join(self._notes)
        self._notes.clear()
        self.view.appendPlainText(chunk)
        if self._autoscroll:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

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
        self._buffer_bytes = 0
        self._last_stream_key = None
        self._needs_render = False
        self.view.setExtraSelections([])
        self.view.clear()

    def export_capture(self) -> None:
        from etools.core.capture import CaptureRecord, save_capture

        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.capture"), "traffic.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            save_capture(
                path,
                [
                    CaptureRecord(stamp, tag, peer, data.hex())
                    for tag, data, peer, stamp in self._records
                ],
            )
        except (OSError, ValueError) as exc:
            self.append_status(str(exc))

    def replay_capture(self) -> None:
        from etools.core.capture import load_capture

        path, _ = QFileDialog.getOpenFileName(self, tr("mon.replay"), "", "JSON (*.json)")
        if not path:
            return
        try:
            records = load_capture(path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.append_status(str(exc))
            return
        self.stop_replay()
        self.clear()
        self.pause_check.setChecked(False)
        self._replay_records = records
        self._replay_index = 0
        self.replay_stop_btn.setEnabled(bool(records))
        self._replay_next()

    def _replay_next(self) -> None:
        if self._replay_index >= len(self._replay_records):
            self.stop_replay()
            return
        record = self._replay_records[self._replay_index]
        self._append_chunk(record.direction, record.data, record.peer, record.timestamp)
        self._replay_index += 1
        if self._replay_index < len(self._replay_records):
            next_record = self._replay_records[self._replay_index]
            delta = (
                datetime.fromisoformat(next_record.timestamp)
                - datetime.fromisoformat(record.timestamp)
            ).total_seconds()
            self._replay_timer.start(max(1, min(2_000_000_000, int(delta * 1000))))
        else:
            self.stop_replay()

    def stop_replay(self) -> None:
        self._replay_timer.stop()
        self._replay_records = []
        self.replay_stop_btn.setEnabled(False)

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

        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["stamp", "direction", "peer", "hex", "text"])
                for tag, data, peer, stamp in self._records:
                    writer.writerow(
                        [
                            stamp,
                            tag,
                            peer,
                            data.hex(" ").upper(),
                            decode_payload(data, self._encoding),
                        ]
                    )
        except OSError as exc:
            self.append_status(str(exc))
            return
        self.append_status(path)

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.save_title"), "traffic.log", tr("mon.log_filter")
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(self.to_plain_text())
        except OSError as exc:
            self.append_status(str(exc))
            return
        self.append_status(path)
