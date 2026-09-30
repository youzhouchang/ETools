"""Shared UI building blocks — one density, one visual language."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

#: Canonical control heights (px) — keep every form row on the same rhythm.
H_ROW = 28
H_BTN = 28
H_INPUT = 28
H_TOOL = 26

RADIUS = 6
SPACE_XS = 4
SPACE_SM = 6
SPACE_MD = 8
SPACE_LG = 12


def ghost_button(text: str = "", *, height: int = H_BTN) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("ghost")
    btn.setFixedHeight(height)
    return btn


def accent_button(text: str = "", *, height: int = H_BTN) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("accent")
    btn.setFixedHeight(height)
    return btn


def danger_button(text: str = "", *, height: int = H_BTN) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("danger")
    btn.setFixedHeight(height)
    return btn


def compact_combo(*, width: int | None = None, height: int = H_ROW) -> QComboBox:
    combo = QComboBox()
    combo.setFixedHeight(height)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    if width is not None:
        combo.setFixedWidth(width)
    return combo


def line_edit(placeholder: str = "", *, height: int = H_INPUT) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setFixedHeight(height)
    return edit


def spinbox(*, width: int = 100, height: int = H_ROW) -> QSpinBox:
    spin = QSpinBox()
    spin.setFixedHeight(height)
    spin.setFixedWidth(width)
    return spin


def tool_row(*widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(SPACE_SM)
    for w in widgets:
        row.addWidget(w)
    if stretch_last and widgets:
        row.addStretch(1)
    else:
        row.addStretch(1)
    return row


def titled_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("panelTitle")
    return lab


def muted_label(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("mutedLabel")
    return lab


def toast(text: str, *, ms: int = 4000) -> None:
    """Show a short status message on the main window status bar, if any."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    win = app.activeWindow() if app else None
    # Prefer the main window (has statusBar) even if a dialog is focused.
    if app is not None:
        for w in app.topLevelWidgets():
            if w.objectName() == "MainWindow" or w.inherits("QMainWindow"):
                win = w
                break
    if win is not None and hasattr(win, "statusBar"):
        win.statusBar().showMessage(text, ms)


def wire_default_button(btn: QPushButton, slot: Callable[[], None]) -> None:
    btn.clicked.connect(slot)
