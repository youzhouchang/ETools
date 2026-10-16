"""Collapsible Serial Studio-style plot for text/binary frames on a byte stream."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from etools.core.studio_frames import PARSE_MODES, StudioFrameParser
from etools.i18n import tr
from etools.ui.widgets.variable_monitor import VIEW_MODES, _Waveform


class StudioPlotPanel(QWidget):
    """Checkbox, parse/view mode, optional field names, and a waveform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parser = StudioFrameParser()
        self.toggle = QCheckBox(tr("serial.plot"))
        self.toggle.setToolTip(tr("serial.plot_tip"))
        self.toggle.setChecked(False)

        self.parse_mode = QComboBox()
        self.parse_mode.setFixedHeight(28)
        self.parse_mode.setFixedWidth(110)
        for mode in PARSE_MODES:
            self.parse_mode.addItem(tr(f"serial.plot_mode.{mode}"), mode)

        self.view_mode = QComboBox()
        self.view_mode.setFixedHeight(28)
        self.view_mode.setFixedWidth(90)
        for mode in VIEW_MODES:
            self.view_mode.addItem(tr(f"serial.plot_view.{mode}"), mode)

        self.names = QLineEdit()
        self.names.setFixedHeight(28)
        self.names.setPlaceholderText(tr("serial.plot_names_ph"))

        self.hex_template = QLineEdit()
        self.hex_template.setFixedHeight(28)
        self.hex_template.setPlaceholderText(tr("serial.plot_hex_ph"))
        self.hex_template.setVisible(False)

        self.plot = _Waveform(
            title=tr("serial.plot"),
            empty=tr("serial.plot_empty"),
            min_height=160,
        )
        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(4)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(self.parse_mode)
        mode_row.addWidget(self.view_mode)
        mode_row.addWidget(self.names, 1)
        body_lay.addLayout(mode_row)
        body_lay.addWidget(self.hex_template)
        body_lay.addWidget(self.plot)
        self.body.setVisible(False)
        self.toggle.toggled.connect(self.body.setVisible)
        self.parse_mode.currentIndexChanged.connect(self._on_parse_mode_changed)
        self.view_mode.currentIndexChanged.connect(self._on_view_mode_changed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self._on_parse_mode_changed()
        self._on_view_mode_changed()

    def parse_mode_name(self) -> str:
        return str(self.parse_mode.currentData() or "studio")

    def hex_template_text(self) -> str:
        return self.hex_template.text().strip()

    def configure_parser(self, parser: StudioFrameParser) -> None:
        parser.set_mode(self.parse_mode_name())
        parser.set_names(self.names.text())
        parser.set_hex_template(self.hex_template_text())

    def feed(self, data: bytes) -> list[dict[str, float]]:
        if not data:
            return []
        self.configure_parser(self._parser)
        frames = self._parser.feed(data)
        if self.toggle.isChecked():
            for frame in frames:
                self.plot.push_batch(frame)
        return frames

    def _on_parse_mode_changed(self, _index: int = 0) -> None:
        mode = self.parse_mode_name()
        self.hex_template.setVisible(mode == "hex")
        self.names.setVisible(mode == "studio")
        self._parser.reset()
        self.configure_parser(self._parser)

    def _on_view_mode_changed(self, _index: int = 0) -> None:
        self.plot.set_view_mode(str(self.view_mode.currentData() or "time"))

    def retranslate(self) -> None:
        self.toggle.setText(tr("serial.plot"))
        self.toggle.setToolTip(tr("serial.plot_tip"))
        self.names.setPlaceholderText(tr("serial.plot_names_ph"))
        self.hex_template.setPlaceholderText(tr("serial.plot_hex_ph"))
        self.plot.set_caption(tr("serial.plot"), tr("serial.plot_empty"))
        current_parse = self.parse_mode_name()
        current_view = str(self.view_mode.currentData() or "time")
        self.parse_mode.blockSignals(True)
        self.parse_mode.clear()
        for mode in PARSE_MODES:
            self.parse_mode.addItem(tr(f"serial.plot_mode.{mode}"), mode)
        idx = self.parse_mode.findData(current_parse)
        if idx >= 0:
            self.parse_mode.setCurrentIndex(idx)
        self.parse_mode.blockSignals(False)
        self.view_mode.blockSignals(True)
        self.view_mode.clear()
        for mode in VIEW_MODES:
            self.view_mode.addItem(tr(f"serial.plot_view.{mode}"), mode)
        idx = self.view_mode.findData(current_view)
        if idx >= 0:
            self.view_mode.setCurrentIndex(idx)
        self.view_mode.blockSignals(False)
        self._on_parse_mode_changed()
        self._on_view_mode_changed()
