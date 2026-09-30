"""Keyboard shortcut reference dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("shortcuts.title"))
        self.setMinimumSize(480, 420)

        rows = [
            ("Ctrl+1 … Ctrl+5", "shortcuts.tools"),
            ("Ctrl+K", "palette.title"),
            ("Ctrl+O", "act.open"),
            ("Ctrl+Q", "act.quit"),
            ("F5", "act.program"),
            ("F6", "act.reset"),
            ("Ctrl+H", "act.hex"),
            ("F1", "shortcuts.title"),
            ("Ctrl+Shift+S", "settings.title"),
            ("↑ / ↓", "serial.history"),
            ("Enter", "shortcuts.enter_send"),
        ]

        root = QVBoxLayout(self)
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels([tr("shortcuts.key"), tr("shortcuts.action")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, (key, action_key) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(key))
            table.setItem(i, 1, QTableWidgetItem(tr(action_key)))
        root.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
