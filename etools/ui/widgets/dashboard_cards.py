"""Dashboard cards: value, gauge, bar, lamp, plot, multi-plot, and 3D attitude."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from etools.core.attitude import attitude_quat, quat_to_euler
from etools.core.dashboard import DashWidget, lookup
from etools.i18n import tr
from etools.ui.styles import get_theme
from etools.ui.widgets.attitude_view import build_attitude_view
from etools.ui.widgets.variable_monitor import _Waveform

# Drawn in paintEvent. A stylesheet border-radius masks the native dashboard
# window and leaves the straight edges missing, with a second fringe on the left.
_CARD_RADIUS = 10.0


class DashGrip(QWidget):
    """Bottom-right resize handle. Kept in the card layout so a native 3D view cannot cover it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("dashGrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(36, 22)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip(tr("dash.resize_hint"))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(
            self.palette().windowText().color(),
            1.6,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(pen)
        width = self.width()
        height = self.height()
        for offset in (7, 12, 17):
            painter.drawLine(width - offset, height - 4, width - 4, height - offset)


class _Meter(QWidget):
    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._value = 0.0
        self._min = 0.0
        self._max = 100.0
        self.setMinimumHeight(88)

    def set_range(self, minimum: float, maximum: float) -> None:
        self._min = float(minimum)
        self._max = float(maximum) if maximum != minimum else float(minimum) + 1.0
        self.update()

    def set_value(self, value: float) -> None:
        self._value = float(value)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        text = self.palette().text().color()
        dim = self.palette().mid().color()
        accent = text
        rect = self.rect().adjusted(8, 8, -8, -8)
        span = self._max - self._min
        frac = max(0.0, min(1.0, (self._value - self._min) / span))
        if self.kind == "bar":
            painter.setPen(QPen(dim, 1))
            painter.drawRoundedRect(rect, 4, 4)
            fill = rect.adjusted(2, 2, -2, -2)
            fill.setWidth(max(2, int(fill.width() * frac)))
            painter.fillRect(fill, accent)
            return
        if self.kind == "lamp":
            theme = get_theme()
            center = rect.center()
            radius = max(8, min(rect.width(), rect.height()) // 3)
            lit = lamp_lit(self._value)
            if lit:
                glow = QColor(theme.success)
                glow.setAlpha(70)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(center, radius + 6, radius + 6)
                painter.setBrush(QColor(theme.success))
                painter.drawEllipse(center, radius, radius)
            else:
                painter.setPen(QPen(QColor(theme.text_muted), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, radius, radius)
            return
        box = rect.adjusted(6, 4, -6, -4)
        start = 225 * 16
        sweep = int(-270 * 16 * frac)
        painter.setPen(QPen(dim, 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(box, 225 * 16, -270 * 16)
        painter.setPen(QPen(accent, 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(box, start, sweep)
        painter.setPen(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._value:.4g}")


class DashCard(QWidget):
    def __init__(self, spec: DashWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("dashCard")
        lay = QVBoxLayout(self)
        # Inset past the rounded stroke so nothing paints a second edge on top of it.
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self.caption = QLabel(self._caption())
        self.caption.setObjectName("dashCaption")
        self.caption.setMinimumHeight(24)
        lay.addWidget(self.caption)
        self._meter: _Meter | None = None
        self._value = QLabel("—")
        self._plot: _Waveform | None = None
        self._attitude = None
        if spec.type in {"gauge", "bar", "lamp"}:
            self._meter = _Meter(spec.type)
            self._meter.set_range(spec.minimum, spec.maximum)
            lay.addWidget(self._meter, 1)
        elif spec.type in {"plot", "multiplot"}:
            self._plot = _Waveform(title=spec.title or spec.bind, empty="—", min_height=120)
            lay.addWidget(self._plot, 1)
        elif spec.type == "attitude3d":
            self._attitude = build_attitude_view(shape=spec.shape)
            lay.addWidget(self._attitude, 1)
        else:
            font = self._value.font()
            font.setPointSize(max(font.pointSize(), 18))
            self._value.setFont(font)
            lay.addWidget(self._value, 1)
        if spec.type != "value":
            self._value = QLabel("—")
            lay.addWidget(self._value)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        self.grip = DashGrip(self)
        foot.addWidget(self.grip)
        lay.addLayout(foot)

    def _caption(self) -> str:
        unit = f" {self.spec.unit}" if self.spec.unit else ""
        return f"{self.spec.title or self.spec.bind}{unit}"

    def set_selected(self, selected: bool) -> None:
        self.setProperty("dashSelected", "true" if selected else "false")
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        theme = get_theme()
        selected = self.property("dashSelected") == "true"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(theme.accent if selected else theme.border))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(QColor(theme.bg_hover if selected else theme.bg_input))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

    def push(self, frame: dict[str, float]) -> None:
        if self.spec.type == "attitude3d":
            self._push_attitude(frame)
            return
        if self.spec.type == "multiplot":
            batch: dict[str, float] = {}
            texts: list[str] = []
            for bind in self.spec.binds():
                value = lookup(frame, bind)
                if value is None:
                    continue
                batch[bind] = value
                texts.append(f"{bind} {value:.4g}")
            if self._plot is not None and batch:
                self._plot.push_batch(batch)
            if texts:
                self._value.setText("  ".join(texts))
            return
        value = lookup(frame, self.spec.binds()[0] if self.spec.binds() else "1")
        if value is None:
            return
        shown = f"{value:.4g}{(' ' + self.spec.unit) if self.spec.unit else ''}"
        self._value.setText(shown)
        if self._meter is not None:
            self._meter.set_range(self.spec.minimum, self.spec.maximum)
            self._meter.set_value(value)
        if self._plot is not None:
            self._plot.push_batch({self.spec.title or self.spec.bind: value})

    def _push_attitude(self, frame: dict[str, float]) -> None:
        if self._attitude is None:
            return
        values: list[float] = []
        for bind in self.spec.binds():
            value = lookup(frame, bind)
            if value is None:
                return
            values.append(value)
        quat = attitude_quat(self.spec.mode, values)
        if quat is None:
            return
        self._attitude.set_quaternion(quat)
        roll, pitch, yaw = quat_to_euler(*quat)
        self._value.setText(f"roll {roll:+.1f}  pitch {pitch:+.1f}  yaw {yaw:+.1f}")


def lamp_lit(value: float) -> bool:
    """A lamp is on for any finite non-zero reading (a status bit or flag)."""
    return math.isfinite(value) and value != 0.0


def gauge_frac(value: float, minimum: float, maximum: float) -> float:
    span = maximum - minimum
    if span == 0:
        return 0.0
    return max(0.0, min(1.0, (value - minimum) / span))


def arc_point(frac: float) -> tuple[float, float]:
    """Unit vector along the gauge, used by tests. 0 is the start of the sweep."""
    angle = math.radians(225 - 270 * frac)
    return math.cos(angle), math.sin(angle)
