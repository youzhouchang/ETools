"""Compact icon-only tool button for the left activity rail."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import QToolButton


class IconToolButton(QToolButton):
    """Narrow square button — large icon, label only as tooltip.

    Always paints Normal-mode icons so selected/hover never grays them out.
    Host should swap the icon color for checked state (on-accent).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("toolRailBtn")
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(28, 28))
        self.setFixedSize(48, 48)
        self._checked_bg = None
        self._hover_bg = None

    def set_backgrounds(self, checked: str | None, hover: str | None) -> None:
        self._checked_bg = checked
        self._hover_bg = hover

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(48, 48)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        inner = rect.adjusted(3, 3, -3, -3)

        if self.isChecked() and self._checked_bg:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._checked_bg))
            painter.drawRoundedRect(inner, 10, 10)
        elif self.underMouse() and self._hover_bg:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._hover_bg))
            painter.drawRoundedRect(inner, 10, 10)

        icon = self.icon()
        if not icon.isNull():
            s = self.iconSize()
            ix = (rect.width() - s.width()) // 2
            iy = (rect.height() - s.height()) // 2
            # Never use Selected/Disabled mode — icon is already color-tinted
            icon.paint(
                painter,
                QRect(ix, iy, s.width(), s.height()),
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal,
            )
        painter.end()
