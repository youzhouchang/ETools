"""Collapsible Serial Studio-style plot for text/binary frames on a byte stream."""

from __future__ import annotations

import math

from PySide6.QtWidgets import (
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
    """Parse mode, view mode, optional field names, and a waveform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parser = StudioFrameParser()
        self._script_parser = StudioFrameParser()
        self._section_open = False

        self.parse_mode = QComboBox()
        self.parse_mode.setFixedHeight(28)
        self.parse_mode.setFixedWidth(100)
        for mode in PARSE_MODES:
            self.parse_mode.addItem(tr(f"serial.plot_mode.{mode}"), mode)

        self.view_mode = QComboBox()
        self.view_mode.setFixedHeight(28)
        self.view_mode.setFixedWidth(100)
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
        self.parse_mode.currentIndexChanged.connect(self._on_parse_mode_changed)
        self.view_mode.currentIndexChanged.connect(self._on_view_mode_changed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
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
        if self._section_open:
            for frame in frames:
                self.plot.push_batch(frame)
        return frames

    def accept_script(self, kind: str, payload) -> list[dict[str, float]]:
        """Draw frames pushed by a script. Text uses a parser of its own."""
        if kind == "map":
            frames = [_finite_numbers(payload)]
        elif kind == "list":
            frames = [self._named_values(payload)]
        else:
            self.configure_parser(self._script_parser)
            if kind == "bytes":
                raw = bytes(payload)
            else:
                raw = str(payload).encode("utf-8")
                if raw and not raw.endswith((b"\n", b"\r")):
                    raw += b"\n"
            frames = self._script_parser.feed(raw)
        shown: list[dict[str, float]] = []
        for frame in frames:
            clean = _finite_numbers(frame)
            if not clean:
                continue
            self.plot.push_batch(clean)
            shown.append(clean)
        return shown

    def _named_values(self, values) -> dict[str, float]:
        names = [part.strip() for part in self.names.text().split(",") if part.strip()]
        named: dict[str, float] = {}
        for index, value in enumerate(values):
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            key = names[index] if index < len(names) else f"f{index + 1}"
            named[key] = number
        return named

    def _on_parse_mode_changed(self, _index: int = 0) -> None:
        mode = self.parse_mode_name()
        self.hex_template.setVisible(mode == "hex")
        self.names.setVisible(mode == "studio")
        self._parser.reset()
        self._script_parser.reset()
        self.configure_parser(self._parser)

    def _on_view_mode_changed(self, _index: int = 0) -> None:
        self.plot.set_view_mode(str(self.view_mode.currentData() or "time"))

    def set_section_open(self, open_: bool) -> None:
        self._section_open = bool(open_)

    def retranslate(self) -> None:
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


def _finite_numbers(values) -> dict[str, float]:
    named: dict[str, float] = {}
    for key, value in dict(values).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            named[str(key)] = number
    return named
