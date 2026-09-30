"""Hex payload interpreter dialog (endianness + integer/float/ASCII views)."""

from __future__ import annotations

import struct

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.ui.widgets.traffic_view import decode_payload, parse_hex_input


def interpret_bytes(data: bytes, little_endian: bool = True) -> str:
    """Human-readable multi-format dump of *data*."""
    if not data:
        return ""
    endian = "<" if little_endian else ">"
    lines: list[str] = []
    lines.append(f"len = {len(data)}")
    lines.append("hex = " + data.hex(" ").upper())
    lines.append("ascii = " + decode_payload(data, "latin-1"))
    if len(data) >= 1:
        lines.append(f"u8  = {list(data)}")
    if len(data) >= 2:
        words = [
            int.from_bytes(data[i : i + 2], "little" if little_endian else "big")
            for i in range(0, len(data) - 1, 2)
        ]
        lines.append(f"u16 = {words}")
    if len(data) >= 4:
        dwords = [
            int.from_bytes(data[i : i + 4], "little" if little_endian else "big")
            for i in range(0, len(data) - 3, 4)
        ]
        lines.append(f"u32 = {dwords}")
        try:
            floats = [
                struct.unpack(endian + "f", data[i : i + 4])[0]
                for i in range(0, len(data) - 3, 4)
            ]
            lines.append(f"f32 = {floats}")
        except struct.error:
            pass
    return "\n".join(lines)


class HexInspectorDialog(QDialog):
    def __init__(self, hex_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("inspector.title"))
        self.setMinimumSize(480, 360)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.input = QLineEdit(hex_text)
        self.input.setPlaceholderText("01 02 03 04")
        form.addRow(tr("inspector.input"), self.input)
        root.addLayout(form)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("logView")
        root.addWidget(self.output, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.input.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.output.setPlainText("")
            return
        try:
            data = parse_hex_input(text)
        except ValueError:
            self.output.setPlainText(tr("inspector.bad_hex"))
            return
        self.output.setPlainText(interpret_bytes(data, little_endian=True))
