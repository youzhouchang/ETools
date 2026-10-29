"""Artificial horizon for the attitude card.

A flat sky/ground instrument is easier to read than a model when the question
is only "how far is the vehicle banked and pitched". Roll and pitch follow
the same aerospace quaternion as the 3D models; yaw stays in the caption.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from etools.core.attitude import Quat, quat_to_euler

_SKY = QColor("#2F6FED")
_GROUND = QColor("#8D6A32")
_LINE = QColor("#F4F7FB")
_MARK = QColor("#FFB020")


class HorizonView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._roll = 0.0
        self._pitch = 0.0
        self.setMinimumHeight(140)

    def set_quaternion(self, quat: Quat) -> None:
        self._roll, self._pitch, _yaw = quat_to_euler(*quat)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.setClipRect(rect)
        center_x = rect.center().x()
        center_y = rect.center().y()
        # Positive pitch lifts the nose, so the horizon drops in the window.
        # QPainter rotates clockwise, but positive roll drops the right wing,
        # which turns the horizon counter-clockwise in the window.
        pitch_px = (self._pitch / 45.0) * (rect.height() * 0.35)
        span = float(max(rect.width(), rect.height()) * 2)
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(-self._roll)
        painter.fillRect(QRectF(-span, -span, span * 2, span + pitch_px), _SKY)
        painter.fillRect(QRectF(-span, pitch_px, span * 2, span), _GROUND)
        painter.setPen(QPen(_LINE, 2))
        painter.drawLine(QPointF(-span, pitch_px), QPointF(span, pitch_px))
        painter.setPen(QPen(QColor(255, 255, 255, 190), 1.4))
        for degrees in (-30, -20, -10, 10, 20, 30):
            y = pitch_px - (degrees / 45.0) * (rect.height() * 0.35)
            half = 28.0 if abs(degrees) == 10 else 18.0
            painter.drawLine(QPointF(-half, y), QPointF(half, y))
        painter.restore()
        painter.setPen(QPen(_MARK, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(center_x - 46, center_y, center_x - 14, center_y)
        painter.drawLine(center_x + 14, center_y, center_x + 46, center_y)
        painter.drawLine(center_x, center_y, center_x, center_y + 10)
        painter.setBrush(_MARK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(center_x, center_y), 3.5, 3.5)


__all__ = ["HorizonView"]
