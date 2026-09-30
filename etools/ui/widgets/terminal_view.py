"""Monospace console that stays stable while the window is resized."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class TerminalView(QPlainTextEdit):
    """Read-mostly console used by serial terminal / SSH output.

    Resize behaviour:
    - Uses a real fixed-width font (QSS family alone does not update metrics).
    - Keeps "stick to bottom" when the user has not scrolled up.
    - Forces a layout pass on resize so wrapped lines reflow immediately.
    """

    send_bytes = Signal(bytes)

    def __init__(self, parent: QWidget | None = None, *, interactive: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("logView")
        self.setUndoRedoEnabled(False)
        self.setReadOnly(not interactive)
        self._interactive = bool(interactive)
        self._stick_bottom = True
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        if font.pointSize() <= 0:
            font.setPointSize(10)
        self.setFont(font)
        # NoWrap keeps terminal columns stable; WidgetWidth is available for logs.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setCenterOnScroll(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().setDocumentMargin(6.0)
        if interactive:
            self.setReadOnly(False)

    def set_wrap(self, wrap: bool) -> None:
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def append_text(self, text: str) -> None:
        """Append stream text without forcing the view when scrolled up."""
        if not text:
            return
        bar = self.verticalScrollBar()
        at_bottom = self._stick_bottom and bar.value() >= bar.maximum() - 2
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if at_bottom:
            bar.setValue(bar.maximum())
        self._stick_bottom = at_bottom

    def clear(self) -> None:
        super().clear()
        self._stick_bottom = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # QSS padding + rewrap can leave stale line boxes after a drag-resize.
        doc = self.document()
        doc.markContentsDirty(0, doc.characterCount())
        self.viewport().update()
        if self._stick_bottom:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._interactive:
            super().keyPressEvent(event)
            return
        key = event.key()
        special = {
            Qt.Key.Key_Return: b"\r",
            Qt.Key.Key_Enter: b"\r",
            Qt.Key.Key_Backspace: b"\x7f",
            Qt.Key.Key_Tab: b"\t",
            Qt.Key.Key_Escape: b"\x1b",
            Qt.Key.Key_Up: b"\x1b[A",
            Qt.Key.Key_Down: b"\x1b[B",
            Qt.Key.Key_Right: b"\x1b[C",
            Qt.Key.Key_Left: b"\x1b[D",
            Qt.Key.Key_Home: b"\x1b[H",
            Qt.Key.Key_End: b"\x1b[F",
            Qt.Key.Key_Delete: b"\x1b[3~",
        }
        if key in special:
            self.send_bytes.emit(special[key])
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            char = event.text().upper()
            if len(char) == 1 and 1 <= ord(char) <= 26:
                self.send_bytes.emit(bytes([ord(char)]))
                event.accept()
                return
        text = event.text()
        if text:
            self.send_bytes.emit(text.encode("utf-8", errors="replace"))
            event.accept()
            return
        super().keyPressEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        bar = self.verticalScrollBar()
        self._stick_bottom = bar.value() >= bar.maximum() - 2
