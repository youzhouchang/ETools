"""Bottom log console — loads log_panel.ui."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QWidget

from etools.ui.icons import set_button_icon
from etools.ui.ui_loader import embed_form


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._form = embed_form(self, "log_panel")
        self.view: QPlainTextEdit = self._form.findChild(QPlainTextEdit, "logView")
        self.clear_btn: QPushButton = self._form.findChild(QPushButton, "clearBtn")
        if self.view is None or self.clear_btn is None:
            raise RuntimeError("log_panel.ui missing logView/clearBtn")
        self.view.setObjectName("logView")
        self.clear_btn.setObjectName("ghost")
        set_button_icon(self.clear_btn, "clear", 16)
        self.clear_btn.clicked.connect(self.clear)

    def append(self, message: str, is_error: bool = False) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = "ERR" if is_error else "INF"
        self.view.appendPlainText(f"[{ts}] {prefix}  {message}")
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)

    def clear(self) -> None:
        self.view.clear()
