"""Single-field IPv4 address input with regex validation."""

from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator, QValidator
from PySide6.QtWidgets import QLineEdit, QWidget

# Full address: four octets 0–255
IPV4_FULL = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$"
)
# Progressive input: allow incomplete last octet while typing
IPV4_PARTIAL = QRegularExpression(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){0,3}"
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)?$"
)


class _IPv4Validator(QRegularExpressionValidator):
    """Regex + per-octet range (0–255) while typing."""

    def validate(self, input_str: str, pos: int) -> tuple[QValidator.State, str, int]:  # noqa: N802
        text = (input_str or "").strip()
        if not text:
            return QValidator.State.Intermediate, input_str, pos
        # Reject characters that can never be part of an IPv4
        if not re.fullmatch(r"[0-9.]*", text):
            return QValidator.State.Invalid, input_str, pos
        if IPV4_FULL.match(text):
            return QValidator.State.Acceptable, input_str, pos
        if IPV4_PARTIAL.match(text):
            return QValidator.State.Intermediate, input_str, pos
        return QValidator.State.Invalid, input_str, pos


class IPv4Edit(QLineEdit):
    """One line edit for a dotted IPv4 address, with regex validation."""

    def __init__(self, text: str = "0.0.0.0", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setValidator(_IPv4Validator(self))
        self.setMaxLength(15)
        self.setPlaceholderText("0.0.0.0")
        self.setFixedHeight(28)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setText(text or "0.0.0.0")
        self.editingFinished.connect(self._on_finished)
        self.textChanged.connect(lambda _t: self._update_valid_style())

    def isValid(self) -> bool:
        return bool(IPV4_FULL.match(self.text().strip()))

    def _on_finished(self) -> None:
        t = self.text().strip()
        if not t:
            self.setText("0.0.0.0")
            return
        # Normalize: pad incomplete address (10.1 → 10.1.0.0)
        if self.isValid():
            return
        parts = [p for p in t.split(".") if p != ""]
        if not all(p.isdigit() and int(p) <= 255 for p in parts):
            return
        while len(parts) < 4:
            parts.append("0")
        if len(parts) == 4:
            self.setText(".".join(parts))

    def _update_valid_style(self) -> None:
        t = self.text().strip()
        empty = not t
        self.setProperty("ipInvalid", (not empty and not self.isValid()))
        st = self.style()
        st.unpolish(self)
        st.polish(self)
