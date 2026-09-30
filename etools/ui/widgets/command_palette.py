"""Ctrl+K command palette — jump to tools and run frequent actions."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr


class CommandPalette(QDialog):
    """Filterable action list; Enter runs the highlighted item."""

    activated = Signal(str)  # command id

    def __init__(
        self,
        commands: list[tuple[str, str, Callable[[], None]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("palette.title"))
        self.setObjectName("CommandPalette")
        self.setModal(True)
        self.setMinimumSize(520, 380)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)

        self._commands = commands  # (id, label, slot)
        self._slots: dict[str, Callable[[], None]] = {cid: slot for cid, _lab, slot in commands}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("palette.ph"))
        self.query.setFixedHeight(36)
        self.query.setObjectName("paletteInput")
        root.addWidget(self.query)

        self.listw = QListWidget()
        self.listw.setObjectName("paletteList")
        self.listw.setAlternatingRowColors(False)
        root.addWidget(self.listw, 1)

        self.hint = QLabel(tr("palette.hint"))
        self.hint.setObjectName("hint")
        root.addWidget(self.hint)

        self.query.textChanged.connect(self._rebuild)
        self.listw.itemActivated.connect(self._run_item)
        self.query.installEventFilter(self)
        self._rebuild("")

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent

        if obj is self.query and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.listw.currentRow()
                count = self.listw.count()
                if count:
                    nxt = row + (1 if event.key() == Qt.Key.Key_Down else -1)
                    self.listw.setCurrentRow(max(0, min(nxt, count - 1)))
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_current()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _rebuild(self, text: str) -> None:
        needle = (text or "").strip().lower()
        self.listw.clear()
        for cid, label, _slot in self._commands:
            if needle and needle not in label.lower() and needle not in cid.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.listw.addItem(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _run_item(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        slot = self._slots.get(cid)
        if slot is not None:
            slot()
        self.activated.emit(str(cid))

    def _run_current(self) -> None:
        item = self.listw.currentItem()
        if item is not None:
            self._run_item(item)
