"""Map page. Latitude and longitude come from the shared frame hub."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton

from etools.core.dashboard import lookup
from etools.core.frame_hub import frame_hub
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.map_canvas import MapCanvas


class _Relay(QObject):
    frame = Signal(str, object)


class MapPage(ToolPage):
    tool_id = "map"
    tool_title_key = "tool.map"

    def _build(self) -> None:
        self._relay = _Relay(self)
        self._relay.frame.connect(self._on_frame)
        self._listener = lambda source, frame: self._relay.frame.emit(source, frame)
        frame_hub.subscribe(self._listener)
        self.destroyed.connect(lambda: frame_hub.unsubscribe(self._listener))

        self.ctx_box = self.ctx_group(tr("map.title"))
        self.source = QComboBox()
        self.source.setFixedHeight(28)
        self.lbl_source = self.form_row(tr("map.source"), self.source)
        self.lat_bind = QLineEdit("lat")
        self.lat_bind.setFixedHeight(28)
        self.lat_bind.setPlaceholderText(tr("map.bind_ph"))
        self.lbl_lat = self.form_row(tr("map.lat"), self.lat_bind)
        self.lon_bind = QLineEdit("lon")
        self.lon_bind.setFixedHeight(28)
        self.lon_bind.setPlaceholderText(tr("map.bind_ph"))
        self.lbl_lon = self.form_row(tr("map.lon"), self.lon_bind)
        self.tiles = QCheckBox(tr("map.tiles"))
        self.tiles.setChecked(True)
        self.ctx_layout.addWidget(self.tiles)
        self.clear_btn = QPushButton(tr("map.clear"))
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setFixedHeight(28)
        self.ctx_action(self.clear_btn)

        box = self.main_group(tr("tool.map"))
        self.canvas = MapCanvas()
        box.layout().addWidget(self.canvas, 1)

        self.clear_btn.clicked.connect(self.canvas.clear)
        self.tiles.toggled.connect(self._on_tiles)
        self._fill_sources()
        self._load_prefs()
        self.retranslate()

    def retranslate(self) -> None:
        self.ctx_box.setTitle(tr("map.title"))
        self.lbl_source.setText(tr("map.source"))
        self.lbl_lat.setText(tr("map.lat"))
        self.lbl_lon.setText(tr("map.lon"))
        self.lat_bind.setPlaceholderText(tr("map.bind_ph"))
        self.lon_bind.setPlaceholderText(tr("map.bind_ph"))
        self.tiles.setText(tr("map.tiles"))
        self.clear_btn.setText(tr("map.clear"))
        current = self.source.currentData()
        self._fill_sources()
        index = self.source.findData(current)
        if index >= 0:
            self.source.setCurrentIndex(index)

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [ToolActionSpec("clear", "map.clear", "clear", self.canvas.clear)]

    def persist_prefs(self) -> None:
        self._persist()

    def shutdown(self) -> None:
        self._persist()
        frame_hub.unsubscribe(self._listener)
        self.canvas.shutdown()

    def _fill_sources(self) -> None:
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(tr("dash.source.any"), "any")
        self.source.addItem(tr("tool.serial"), "serial")
        self.source.addItem(tr("tool.ethernet"), "ethernet")
        self.source.addItem(tr("tool.mqtt"), "mqtt")
        self.source.blockSignals(False)

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        self.lat_bind.setText(str(prefs.get("lat") or "lat"))
        self.lon_bind.setText(str(prefs.get("lon") or "lon"))
        source = str(prefs.get("source") or "any")
        index = self.source.findData(source)
        if index >= 0:
            self.source.setCurrentIndex(index)
        self.tiles.setChecked(bool(prefs.get("tiles", True)))
        self.canvas.tiles_enabled = self.tiles.isChecked()

    def _persist(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "lat": self.lat_bind.text().strip(),
                "lon": self.lon_bind.text().strip(),
                "source": str(self.source.currentData() or "any"),
                "tiles": self.tiles.isChecked(),
            },
        )

    def _on_tiles(self, on: bool) -> None:
        self.canvas.tiles_enabled = bool(on)
        self.canvas.update()
        self._persist()

    def _on_frame(self, source: str, frame: object) -> None:
        if not isinstance(frame, dict):
            return
        wanted = str(self.source.currentData() or "any")
        if wanted != "any" and source != wanted:
            return
        lat = lookup(frame, self.lat_bind.text())
        lon = lookup(frame, self.lon_bind.text())
        if lat is None or lon is None:
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        self.canvas.add_point(lat, lon)
