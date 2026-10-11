"""Collapsible Serial Studio-style plot for text frames on a byte stream."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

from etools.core.studio_frames import StudioFrameParser
from etools.i18n import tr
from etools.ui.widgets.variable_monitor import _Waveform


class StudioPlotPanel(QWidget):
    """Checkbox, optional field names, and a waveform.

    Frames look like ``/*1.2,3.4*/`` or ``{"temp": 21.5}``. The panel stays
    collapsed until the user asks for it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parser = StudioFrameParser()
        self.toggle = QCheckBox(tr("serial.plot"))
        self.toggle.setToolTip(tr("serial.plot_tip"))
        self.toggle.setChecked(False)
        self.names = QLineEdit()
        self.names.setFixedHeight(28)
        self.names.setPlaceholderText(tr("serial.plot_names_ph"))
        self.plot = _Waveform(
            title=tr("serial.plot"),
            empty=tr("serial.plot_empty"),
            min_height=160,
        )
        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(4)
        body_lay.addWidget(self.names)
        body_lay.addWidget(self.plot)
        self.body.setVisible(False)
        self.toggle.toggled.connect(self.body.setVisible)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)

    def feed(self, data: bytes) -> None:
        if not self.toggle.isChecked() or not data:
            return
        self._parser.set_names(self.names.text())
        for frame in self._parser.feed(data):
            self.plot.push_batch(frame)

    def retranslate(self) -> None:
        self.toggle.setText(tr("serial.plot"))
        self.toggle.setToolTip(tr("serial.plot_tip"))
        self.names.setPlaceholderText(tr("serial.plot_names_ph"))
        self.plot.set_caption(tr("serial.plot"), tr("serial.plot_empty"))
