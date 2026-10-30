"""Shared helpers for the flash tool panels (option bytes, production, …)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit, QMessageBox, QPushButton, QWidget

from etools.ui.icons import set_button_icon

_INT_RE = QRegularExpression(r"^\s*(0[xX][0-9a-fA-F_]*|[0-9_]*)\s*$")


class ToolsHost(Protocol):
    """What the panels need from the program controller."""

    service: Any
    connected: bool

    def run_job(self, fn: Callable[[], Any], on_ok, on_err=None) -> bool: ...

    def log(self, message: str, is_error: bool = False) -> None: ...

    def progress(self, percent: int, label: str = "") -> None: ...

    def firmware_path(self) -> str: ...

    def refresh_target(self) -> None: ...

    def mark_disconnected(self) -> None: ...

    def stop_debug_views(self) -> None: ...


def parse_int(text: str, default: int | None = None) -> int:
    """Parse ``0x1234`` / ``4660`` / ``0x0800_0000``; raise ValueError when invalid."""
    raw = (text or "").strip().replace("_", "")
    if not raw:
        if default is None:
            raise ValueError("empty number")
        return default
    return int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)


def int_edit(value: int | None = None, *, width: int = 120, digits: int = 8) -> QLineEdit:
    edit = QLineEdit()
    edit.setValidator(QRegularExpressionValidator(_INT_RE, edit))
    edit.setFixedWidth(width)
    if value is not None:
        edit.setText(f"0x{value:0{digits}X}")
    return edit


def tool_button(icon: str = "", *, kind: str = "ghost") -> QPushButton:
    btn = QPushButton()
    btn.setObjectName(kind)
    btn.setFixedHeight(28)
    if icon:
        set_button_icon(btn, icon, 16)
    return btn


def confirm(parent: QWidget, title: str, text: str, *, danger: bool = False) -> bool:
    box = QMessageBox.warning if danger else QMessageBox.question
    ret = box(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return ret == QMessageBox.StandardButton.Ok
