"""Dashboard cards: value, gauge, bar, plot, and multi-plot."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from etools.core.dashboard import DashWidget, lookup
from etools.ui.widgets.variable_monitor import _Waveform


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
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        self.caption = QLabel(self._caption())
        self.caption.setObjectName("statusTask")
        lay.addWidget(self.caption)
        self._meter: _Meter | None = None
        self._value = QLabel("—")
        self._plot: _Waveform | None = None
        if spec.type in {"gauge", "bar"}:
            self._meter = _Meter(spec.type)
            self._meter.set_range(spec.minimum, spec.maximum)
            lay.addWidget(self._meter)
        elif spec.type in {"plot", "multiplot"}:
            self._plot = _Waveform(title=spec.title or spec.bind, empty="—", min_height=120)
            lay.addWidget(self._plot)
        else:
            font = self._value.font()
            font.setPointSize(max(font.pointSize(), 18))
            self._value.setFont(font)
            lay.addWidget(self._value)
        if spec.type != "value":
            self._value = QLabel("—")
            lay.addWidget(self._value)

    def _caption(self) -> str:
        unit = f" {self.spec.unit}" if self.spec.unit else ""
        return f"{self.spec.title or self.spec.bind}{unit}"

    def push(self, frame: dict[str, float]) -> None:
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


def gauge_frac(value: float, minimum: float, maximum: float) -> float:
    span = maximum - minimum
    if span == 0:
        return 0.0
    return max(0.0, min(1.0, (value - minimum) / span))


def arc_point(frac: float) -> tuple[float, float]:
    """Unit vector along the gauge, used by tests. 0 is the start of the sweep."""
    angle = math.radians(225 - 270 * frac)
    return math.cos(angle), math.sin(angle)
