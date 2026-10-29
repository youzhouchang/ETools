"""Map page. Latitude and longitude come from the shared frame hub."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QComboBox, QLineEdit, QPushButton

from etools.core.dashboard import lookup
from etools.core.frame_hub import LUA_SOURCE, frame_hub
from etools.core.map_basemap import BASEMAPS, DEFAULT_BASEMAP
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.map_canvas import DEFAULT_TRACK, MapCanvas


def _saved_basemap(prefs: dict) -> str:
    saved = str(prefs.get("basemap") or "")
    if saved in BASEMAPS:
        return saved
    if prefs.get("tiles") is False:
        return "none"
    return DEFAULT_BASEMAP


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
        self.basemap = QComboBox()
        self.basemap.setFixedHeight(28)
        self.lbl_basemap = self.form_row(tr("map.tiles"), self.basemap)
        self.color_btn = QPushButton()
        self.color_btn.setObjectName("trackColor")
        self.color_btn.setFixedHeight(28)
        self.lbl_track = self.form_row(tr("map.track"), self.color_btn)
        self.clear_btn = QPushButton(tr("map.clear"))
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setFixedHeight(28)
        self.ctx_action(self.clear_btn)

        box = self.main_group(tr("tool.map"))
        self.canvas = MapCanvas()
        box.layout().addWidget(self.canvas, 1)

        self.clear_btn.clicked.connect(self.canvas.clear)
        self.basemap.currentIndexChanged.connect(self._on_basemap)
        self.color_btn.clicked.connect(self._pick_track_color)
        self._fill_sources()
        self._fill_basemaps()
        self._load_prefs()
        self.retranslate()

    def retranslate(self) -> None:
        self.ctx_box.setTitle(tr("map.title"))
        self.lbl_source.setText(tr("map.source"))
        self.lbl_lat.setText(tr("map.lat"))
        self.lbl_lon.setText(tr("map.lon"))
        self.lbl_basemap.setText(tr("map.tiles"))
        self.lbl_track.setText(tr("map.track"))
        self._sync_color_btn()
        self.lat_bind.setPlaceholderText(tr("map.bind_ph"))
        self.lon_bind.setPlaceholderText(tr("map.bind_ph"))
        self.clear_btn.setText(tr("map.clear"))
        current = self.source.currentData()
        self._fill_sources()
        index = self.source.findData(current)
        if index >= 0:
            self.source.setCurrentIndex(index)
        current_base = self.basemap.currentData()
        self._fill_basemaps()
        index = self.basemap.findData(current_base)
        if index >= 0:
            self.basemap.setCurrentIndex(index)

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
        self.source.addItem(tr("dash.source.lua"), LUA_SOURCE)
        self.source.blockSignals(False)

    def _fill_basemaps(self) -> None:
        current = self.basemap.currentData()
        self.basemap.blockSignals(True)
        self.basemap.clear()
        for key in BASEMAPS:
            self.basemap.addItem(tr(f"map.basemap.{key}"), key)
        index = self.basemap.findData(current if current in BASEMAPS else DEFAULT_BASEMAP)
        self.basemap.setCurrentIndex(max(index, 0))
        self.basemap.blockSignals(False)

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        self.lat_bind.setText(str(prefs.get("lat") or "lat"))
        self.lon_bind.setText(str(prefs.get("lon") or "lon"))
        source = str(prefs.get("source") or "any")
        index = self.source.findData(source)
        if index >= 0:
            self.source.setCurrentIndex(index)
        basemap = _saved_basemap(prefs)
        index = self.basemap.findData(basemap)
        self.basemap.blockSignals(True)
        if index >= 0:
            self.basemap.setCurrentIndex(index)
        self.basemap.blockSignals(False)
        self.canvas.set_basemap(basemap)
        color = QColor(str(prefs.get("track") or DEFAULT_TRACK))
        if color.isValid():
            self.canvas.set_track_color(color)
        self._sync_color_btn()

    def _persist(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "lat": self.lat_bind.text().strip(),
                "lon": self.lon_bind.text().strip(),
                "source": str(self.source.currentData() or "any"),
                "basemap": str(self.basemap.currentData() or DEFAULT_BASEMAP),
                "track": self.canvas.track_color.name().upper(),
            },
        )

    def _pick_track_color(self) -> None:
        picked = QColorDialog.getColor(self.canvas.track_color, self, tr("map.track"))
        if not picked.isValid():
            return
        self.canvas.set_track_color(picked)
        self._sync_color_btn()
        self._persist()

    def _sync_color_btn(self) -> None:
        color = self.canvas.track_color
        luma = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        ink = "#111111" if luma >= 170 else "#FFFFFF"
        self.color_btn.setText(color.name().upper())
        self.color_btn.setStyleSheet(
            "QPushButton#trackColor {"
            f"background-color: {color.name()}; color: {ink}; border: 1px solid #5B6B7C;"
            "}"
        )

    def _on_basemap(self, _index: int = 0) -> None:
        self.canvas.set_basemap(str(self.basemap.currentData() or DEFAULT_BASEMAP))
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

    # -- Lua bridge helpers --------------------------------------------

    def lua_points(self, n: int = 0) -> list[dict]:
        points = self.canvas.points()
        if n > 0:
            points = points[-n:]
        return [{"lat": lat, "lon": lon} for lat, lon in points]

    def lua_add_point(self, lat: float, lon: float) -> bool:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False
        self.canvas.add_point(lat, lon)
        return True

    def lua_clear(self) -> None:
        self.canvas.clear()

    def lua_source(self, name: str | None = None) -> str:
        if name is not None:
            index = self.source.findData(str(name))
            if index < 0:
                raise ValueError(f"unknown map source: {name}")
            self.source.setCurrentIndex(index)
            self._persist()
        return str(self.source.currentData() or "any")

    def lua_bind(self, lat_field: str, lon_field: str) -> None:
        self.lat_bind.setText(lat_field.strip())
        self.lon_bind.setText(lon_field.strip())
        self._persist()
