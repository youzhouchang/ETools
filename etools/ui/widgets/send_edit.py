"""Multi-line send box that still behaves like a one-shot command line."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QSizePolicy,
    QWidget,
)

_MAX_LINES = 4


class SendEdit(QPlainTextEdit):
    """One line by default. Extra lines grow the box, then it scrolls."""

    submitted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fitting = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setPlaceholderText("")
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        self.setPlainText(value or "")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self) -> None:
        if self._fitting:
            return
        self._fitting = True
        try:
            line = max(self.fontMetrics().lineSpacing(), 16)
            frame = self.frameWidth() * 2 + 8
            cap = line * _MAX_LINES + frame
            width = max(1, self.viewport().width())
            self.document().setTextWidth(width)
            # QPlainTextDocumentLayout reports height as a line count, not pixels.
            lines = max(1, int(self.document().size().height()))
            height = min(cap, line * lines + frame)
            if self.height() != height:
                self.setFixedHeight(height)
        finally:
            self._fitting = False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)
