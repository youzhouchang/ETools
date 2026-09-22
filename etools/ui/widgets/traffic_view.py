"""Stream-friendly traffic monitor shared by Serial / Ethernet pages."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr

MAX_VIEW_CHARS = 400_000


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


class TrafficView(QWidget):
    """RX/TX monitor with hex mode, timestamps, pause, save, auto-scroll."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hex_mode = False
        self._show_ts = False
        self._paused = False
        self._autoscroll = True
        self._offset = 0
        self._pending: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(26)
        self.mode_combo.addItem(tr("mon.ascii"), "ascii")
        self.mode_combo.addItem(tr("mon.hex"), "hex")
        bar.addWidget(QLabel(tr("mon.ascii")))
        self._lbl_mode = bar.itemAt(bar.count() - 1).widget()
        bar.addWidget(self.mode_combo)

        self.ts_check = QCheckBox(tr("mon.ts"))
        self.scroll_check = QCheckBox(tr("mon.autoscroll"))
        self.scroll_check.setChecked(True)
        self.pause_check = QCheckBox(tr("mon.pause"))
        bar.addWidget(self.ts_check)
        bar.addWidget(self.scroll_check)
        bar.addWidget(self.pause_check)
        bar.addStretch(1)

        self.save_btn = QPushButton(tr("mon.save"))
        self.save_btn.setObjectName("ghost")
        self.clear_btn = QPushButton(tr("mon.clear"))
        self.clear_btn.setObjectName("ghost")
        bar.addWidget(self.save_btn)
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText(tr("serial.placeholder"))
        root.addWidget(self.view, 1)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.ts_check.toggled.connect(self._on_flags)
        self.scroll_check.toggled.connect(self._on_flags)
        self.pause_check.toggled.connect(self._on_pause)
        self.save_btn.clicked.connect(self.save_as)
        self.clear_btn.clicked.connect(self.clear)

    def retranslate(self) -> None:
        self._lbl_mode.setText(tr("mon.ascii"))
        self.mode_combo.setItemText(0, tr("mon.ascii"))
        self.mode_combo.setItemText(1, tr("mon.hex"))
        self.ts_check.setText(tr("mon.ts"))
        self.scroll_check.setText(tr("mon.autoscroll"))
        self.pause_check.setText(tr("mon.pause"))
        self.save_btn.setText(tr("mon.save"))
        self.clear_btn.setText(tr("mon.clear"))

    def set_placeholder(self, text: str) -> None:
        self.view.setPlaceholderText(text)

    def _on_mode_changed(self) -> None:
        self._hex_mode = self.mode_combo.currentData() == "hex"

    def _on_flags(self) -> None:
        self._show_ts = self.ts_check.isChecked()
        self._autoscroll = self.scroll_check.isChecked()

    def _on_pause(self) -> None:
        self._paused = self.pause_check.isChecked()

    def _stamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3] + "  " if self._show_ts else ""

    def append_status(self, text: str) -> None:
        self._pending.append(f"{self._stamp()}{text}")
        self._flush()

    def append_rx(self, data: bytes, peer: str = "") -> None:
        self._append_stream(tr("mon.rx"), data, peer)

    def append_tx(self, data: bytes | str) -> None:
        if isinstance(data, str):
            raw = data.encode("utf-8", errors="replace")
        else:
            raw = data
        self._append_stream(tr("mon.tx"), raw)

    def _append_stream(self, tag: str, data: bytes, peer: str = "") -> None:
        if self._paused or not data:
            return
        prefix = f"{self._stamp()}{tag}"
        if peer:
            prefix += f" [{peer}]"
        if self._hex_mode:
            body = format_hex(data, self._offset)
            self._offset += len(data)
            self._pending.append(f"{prefix}\n{body}")
        else:
            text = data.decode("utf-8", errors="replace")
            self._pending.append(f"{prefix}  {text}")
        self._flush()

    def _flush(self) -> None:
        if not self._pending:
            return
        chunk = "\n".join(self._pending)
        self._pending.clear()
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
        if self._autoscroll:
            sb = self.view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def clear(self) -> None:
        self._pending.clear()
        self._offset = 0
        self.view.clear()

    def to_plain_text(self) -> str:
        self._flush()
        return self.view.toPlainText()

    def save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("mon.save_title"), "traffic.log", tr("mon.log_filter")
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(self.to_plain_text())
        self.append_status(path)
