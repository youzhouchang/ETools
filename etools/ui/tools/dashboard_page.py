"""Dashboard shared by serial, network, and MQTT frames.

The field list and the live dashboard are two views of one JSON project.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from etools.core.dashboard import (
    ATTITUDE_MODES,
    ATTITUDE_SHAPES,
    WIDGET_TYPES,
    DashWidget,
    ensure_layout,
    lookup,
    new_widget,
    project_from_json,
    project_to_json,
)
from etools.core.frame_hub import LUA_SOURCE, frame_hub
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.dash_canvas import DashCanvas, DashPalette


class _Relay(QObject):
    frame = Signal(str, object)


_TYPE_KEYS = {
    "value": "dash.type.value",
    "gauge": "dash.type.gauge",
    "bar": "dash.type.bar",
    "lamp": "dash.type.lamp",
    "plot": "dash.type.plot",
    "multiplot": "dash.type.multi",
    "attitude3d": "dash.type.attitude3d",
}
_ATTITUDE_MODE_KEYS = {
    "euler": "dash.attitude_mode.euler",
    "quat": "dash.attitude_mode.quat",
}
_ATTITUDE_SHAPE_KEYS = {
    "aircraft": "dash.shape.aircraft",
    "quad": "dash.shape.quad",
    "cube": "dash.shape.cube",
    "horizon": "dash.shape.horizon",
}
_ATTITUDE_DEFAULT_BIND = {
    "euler": "roll,pitch,yaw",
    "quat": "qw,qx,qy,qz",
}


class DashboardPage(ToolPage):
    tool_id = "dash"
    tool_title_key = "tool.dash"

    def _build(self) -> None:
        self._items: list[DashWidget] = []
        self._last_frame: dict[str, float] = {}
        self._relay = _Relay(self)
        self._relay.frame.connect(self._on_frame)
        self._listener = lambda source, frame: self._relay.frame.emit(source, frame)
        frame_hub.subscribe(self._listener)
        self.destroyed.connect(lambda: frame_hub.unsubscribe(self._listener))

        self.ctx_box = self.ctx_group(tr("dash.title"))
        self.source = QComboBox()
        self.source.setFixedHeight(28)
        self.lbl_source = self.form_row(tr("dash.source"), self.source)
        self.kind = QComboBox()
        self.kind.setFixedHeight(28)
        self.lbl_kind = self.form_row(tr("dash.type"), self.kind)
        self.title_edit = QLineEdit()
        self.title_edit.setFixedHeight(28)
        self.lbl_title = self.form_row(tr("dash.name"), self.title_edit)
        self.attitude_mode = QComboBox()
        self.attitude_mode.setFixedHeight(28)
        self.lbl_attitude_mode = self.form_row(tr("dash.attitude_mode"), self.attitude_mode)
        self.attitude_shape = QComboBox()
        self.attitude_shape.setFixedHeight(28)
        self.lbl_attitude_shape = self.form_row(tr("dash.shape"), self.attitude_shape)
        self.bind_edit = QLineEdit("1")
        self.bind_edit.setFixedHeight(28)
        self.bind_edit.setPlaceholderText(tr("dash.bind_ph"))
        self.lbl_bind = self.form_row(tr("dash.bind"), self.bind_edit)
        self.unit_edit = QLineEdit()
        self.unit_edit.setFixedHeight(28)
        self.lbl_unit = self.form_row(tr("dash.unit"), self.unit_edit)
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(-1_000_000, 1_000_000)
        self.min_spin.setDecimals(3)
        self.min_spin.setFixedHeight(28)
        self.lbl_min = self.form_row(tr("dash.min"), self.min_spin)
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(-1_000_000, 1_000_000)
        self.max_spin.setDecimals(3)
        self.max_spin.setValue(100)
        self.max_spin.setFixedHeight(28)
        self.lbl_max = self.form_row(tr("dash.max"), self.max_spin)

        row = QHBoxLayout()
        self.add_btn = QPushButton(tr("dash.add"))
        self.apply_btn = QPushButton(tr("dash.apply"))
        self.remove_btn = QPushButton(tr("dash.remove"))
        for btn in (self.add_btn, self.apply_btn, self.remove_btn):
            btn.setObjectName("ghost")
            btn.setFixedHeight(28)
            row.addWidget(btn)
        host = QWidget()
        host.setLayout(row)
        self.ctx_layout.addWidget(host)
        self.lbl_palette = QLabel(tr("dash.palette"))
        self.palette = DashPalette(self._palette_entries())
        self.palette.setToolTip(tr("dash.drag_hint"))
        outer = self.ctx_box.layout()
        outer.insertWidget(0, self.palette)
        outer.insertWidget(0, self.lbl_palette)
        self.save_btn = QPushButton(tr("dash.save"))
        self.load_btn = QPushButton(tr("dash.load"))
        for btn in (self.save_btn, self.load_btn):
            btn.setObjectName("ghost")
            btn.setFixedHeight(28)
            self.ctx_action(btn)

        box = self.main_group(tr("tool.dash"))
        lay = box.layout()
        switch = QHBoxLayout()
        self.view_btn = QPushButton(tr("dash.view"))
        self.fields_btn = QPushButton(tr("dash.fields"))
        for btn in (self.view_btn, self.fields_btn):
            btn.setObjectName("ghost")
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            switch.addWidget(btn)
        switch.addStretch(1)
        lay.addLayout(switch)

        self.stack = QStackedWidget()
        self.canvas = DashCanvas()
        self.empty = self.canvas.notice
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.canvas)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.stack.addWidget(scroll)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)

        self.view_btn.clicked.connect(lambda: self._show(0))
        self.fields_btn.clicked.connect(lambda: self._show(1))
        self.add_btn.clicked.connect(self._add)
        self.apply_btn.clicked.connect(self._apply)
        self.remove_btn.clicked.connect(self._remove)
        self.save_btn.clicked.connect(self._save_file)
        self.load_btn.clicked.connect(self._load_file)
        self.table.itemSelectionChanged.connect(self._load_row)
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        self.attitude_mode.currentIndexChanged.connect(lambda _=0: self._on_kind_changed())
        self.palette.add_requested.connect(self.canvas.add_widget)
        self.canvas.changed.connect(self._on_canvas_changed)
        self.canvas.selected.connect(self._on_canvas_selected)
        self._fill_sources()
        self._fill_attitude_modes()
        self._fill_attitude_shapes()
        self._load_prefs()
        self._show(0)
        self.retranslate()

    def retranslate(self) -> None:
        self.ctx_box.setTitle(tr("dash.title"))
        self.lbl_source.setText(tr("dash.source"))
        self.lbl_kind.setText(tr("dash.type"))
        self.lbl_title.setText(tr("dash.name"))
        self.lbl_attitude_mode.setText(tr("dash.attitude_mode"))
        self.lbl_attitude_shape.setText(tr("dash.shape"))
        self.lbl_palette.setText(tr("dash.palette"))
        self.palette.retranslate()
        self.lbl_bind.setText(tr("dash.bind"))
        self.lbl_unit.setText(tr("dash.unit"))
        self.lbl_min.setText(tr("dash.min"))
        self.lbl_max.setText(tr("dash.max"))
        self.bind_edit.setPlaceholderText(tr("dash.bind_ph"))
        self.add_btn.setText(tr("dash.add"))
        self.apply_btn.setText(tr("dash.apply"))
        self.remove_btn.setText(tr("dash.remove"))
        self.save_btn.setText(tr("dash.save"))
        self.load_btn.setText(tr("dash.load"))
        self.view_btn.setText(tr("dash.view"))
        self.fields_btn.setText(tr("dash.fields"))
        self.empty.setText(tr("dash.empty"))
        self.table.setHorizontalHeaderLabels(
            [
                tr("dash.type"),
                tr("dash.name"),
                tr("dash.bind"),
                tr("dash.unit"),
                tr("dash.min"),
                tr("dash.max"),
            ]
        )
        current_kind = self.kind.currentData()
        current_source = self.source.currentData()
        self._fill_sources()
        self.kind.clear()
        for kind in WIDGET_TYPES:
            self.kind.addItem(tr(_TYPE_KEYS[kind]), kind)
        index = self.kind.findData(current_kind)
        if index >= 0:
            self.kind.setCurrentIndex(index)
        index = self.source.findData(current_source)
        if index >= 0:
            self.source.setCurrentIndex(index)
        current_mode = self.attitude_mode.currentData()
        self._fill_attitude_modes()
        index = self.attitude_mode.findData(current_mode)
        if index >= 0:
            self.attitude_mode.setCurrentIndex(index)
        current_shape = self.attitude_shape.currentData()
        self._fill_attitude_shapes()
        index = self.attitude_shape.findData(current_shape)
        if index >= 0:
            self.attitude_shape.setCurrentIndex(index)
        self._on_kind_changed()
        self._fill_table()

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("save", "dash.save", "save", self._save_file),
            ToolActionSpec("open", "dash.load", "open", self._load_file),
        ]

    def persist_prefs(self) -> None:
        self._persist()

    def shutdown(self) -> None:
        self._persist()
        frame_hub.unsubscribe(self._listener)

    def _fill_sources(self) -> None:
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(tr("dash.source.any"), "any")
        self.source.addItem(tr("tool.serial"), "serial")
        self.source.addItem(tr("tool.ethernet"), "ethernet")
        self.source.addItem(tr("tool.mqtt"), "mqtt")
        self.source.addItem(tr("dash.source.lua"), LUA_SOURCE)
        self.source.blockSignals(False)

    def _palette_entries(self) -> list[tuple[str, str, str]]:
        rows = [
            (kind, "", key) for kind, key in _TYPE_KEYS.items() if kind != "attitude3d"
        ]
        rows.extend(("attitude3d", shape, key) for shape, key in _ATTITUDE_SHAPE_KEYS.items())
        return rows

    def _fill_attitude_modes(self) -> None:
        self.attitude_mode.blockSignals(True)
        self.attitude_mode.clear()
        for mode in ATTITUDE_MODES:
            self.attitude_mode.addItem(tr(_ATTITUDE_MODE_KEYS[mode]), mode)
        self.attitude_mode.blockSignals(False)

    def _fill_attitude_shapes(self) -> None:
        self.attitude_shape.blockSignals(True)
        self.attitude_shape.clear()
        for shape in ATTITUDE_SHAPES:
            self.attitude_shape.addItem(tr(_ATTITUDE_SHAPE_KEYS[shape]), shape)
        self.attitude_shape.blockSignals(False)

    def _on_kind_changed(self, _index: int = 0) -> None:
        kind = str(self.kind.currentData() or "value")
        is_attitude = kind == "attitude3d"
        self.lbl_attitude_mode.setVisible(is_attitude)
        self.attitude_mode.setVisible(is_attitude)
        self.lbl_attitude_shape.setVisible(is_attitude)
        self.attitude_shape.setVisible(is_attitude)
        mode = str(self.attitude_mode.currentData() or "euler")
        if not is_attitude:
            self.bind_edit.setPlaceholderText(tr("dash.bind_ph"))
            return
        default_bind = _ATTITUDE_DEFAULT_BIND.get(mode, "roll,pitch,yaw")
        self.bind_edit.setPlaceholderText(default_bind)
        if self.bind_edit.text().strip() in ("", "1"):
            self.bind_edit.setText(default_bind)

    def _show(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.view_btn.setChecked(index == 0)
        self.fields_btn.setChecked(index == 1)

    def _form_spec(self) -> DashWidget:
        return DashWidget(
            type=str(self.kind.currentData() or "value"),
            title=self.title_edit.text().strip(),
            unit=self.unit_edit.text().strip(),
            minimum=float(self.min_spin.value()),
            maximum=float(self.max_spin.value()),
            bind=self.bind_edit.text().strip() or "1",
            mode=str(self.attitude_mode.currentData() or "euler"),
            shape=str(self.attitude_shape.currentData() or "aircraft"),
        )

    def _add(self) -> None:
        spec = self._form_spec()
        fresh = new_widget(spec.type, spec.shape)
        spec.row_span = fresh.row_span
        spec.col_span = fresh.col_span
        self._items.append(spec)
        self._rebuild()
        self._persist()

    def _apply(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        previous = self._items[row]
        spec = self._form_spec()
        spec.row = previous.row
        spec.col = previous.col
        spec.row_span = previous.row_span
        spec.col_span = previous.col_span
        self._items[row] = spec
        self._rebuild()
        self._persist()

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        del self._items[row]
        self._rebuild()
        self._persist()

    def _load_row(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        spec = self._items[row]
        self.canvas.highlight(row)
        index = self.kind.findData(spec.type)
        if index >= 0:
            self.kind.setCurrentIndex(index)
        mode_index = self.attitude_mode.findData(spec.mode)
        if mode_index >= 0:
            self.attitude_mode.setCurrentIndex(mode_index)
        shape_index = self.attitude_shape.findData(spec.shape)
        if shape_index >= 0:
            self.attitude_shape.setCurrentIndex(shape_index)
        self.title_edit.setText(spec.title)
        self.bind_edit.setText(spec.bind)
        self.unit_edit.setText(spec.unit)
        self.min_spin.setValue(spec.minimum)
        self.max_spin.setValue(spec.maximum)

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self._items))
        for row, spec in enumerate(self._items):
            values = [
                tr(_TYPE_KEYS.get(spec.type, "dash.type.value")),
                spec.title,
                spec.bind,
                spec.unit,
                f"{spec.minimum:g}",
                f"{spec.maximum:g}",
            ]
            for col, text in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _rebuild(self) -> None:
        ensure_layout(self._items)
        self.canvas.set_items(self._items)
        self._fill_table()

    def _on_canvas_changed(self) -> None:
        self._fill_table()
        self._persist()

    def _on_canvas_selected(self, index: int) -> None:
        if index < 0 or index >= self.table.rowCount():
            self.table.clearSelection()
            return
        self.table.selectRow(index)

    def _on_frame(self, source: str, frame: object) -> None:
        if not isinstance(frame, dict):
            return
        wanted = str(self.source.currentData() or "any")
        if wanted != "any" and source != wanted:
            return
        self._show_frame(frame)

    def _show_frame(self, frame: dict) -> None:
        self._last_frame = dict(frame)
        for card in self.canvas.cards:
            card.push(frame)

    # -- Lua bridge helpers --------------------------------------------

    def lua_widgets(self) -> list[dict]:
        return [
            {
                "index": index + 1,
                "type": spec.type,
                "title": spec.title,
                "bind": spec.bind,
                "unit": spec.unit,
                "min": spec.minimum,
                "max": spec.maximum,
            }
            for index, spec in enumerate(self._items)
        ]

    def lua_values(self) -> list[dict]:
        """Value(s) each widget shows for the last frame it received."""
        rows = []
        for index, spec in enumerate(self._items):
            values = [lookup(self._last_frame, bind) for bind in spec.binds()]
            row = {"index": index + 1, "title": spec.title, "bind": spec.bind}
            if len(values) == 1:
                if values[0] is not None:
                    row["value"] = values[0]
            else:
                row["values"] = [v for v in values if v is not None]
            rows.append(row)
        return rows

    def lua_source(self, name: str | None = None) -> str:
        if name is not None:
            index = self.source.findData(str(name))
            if index < 0:
                raise ValueError(f"unknown dashboard source: {name}")
            self.source.setCurrentIndex(index)
            self._persist()
        return str(self.source.currentData() or "any")

    def lua_push(self, fields: dict[str, float]) -> None:
        """Show *fields* on the dashboard only (not forwarded to the map)."""
        self._show_frame(fields)

    def lua_add(self, spec: dict) -> int:
        kind = str(spec.get("type") or "value")
        if kind not in WIDGET_TYPES:
            raise ValueError(f"unknown widget type: {kind}")
        shape = str(spec.get("shape") or "aircraft")
        item = new_widget(kind, shape)
        item.title = str(spec.get("title") or "")
        item.bind = str(spec.get("bind") or item.bind or "1")
        item.unit = str(spec.get("unit") or "")
        if spec.get("min") is not None:
            item.minimum = float(spec["min"])
        if spec.get("max") is not None:
            item.maximum = float(spec["max"])
        if kind == "attitude3d":
            item.mode = str(spec.get("mode") or "euler")
            item.shape = shape
        self._items.append(item)
        self._rebuild()
        self._persist()
        return len(self._items)

    def lua_remove(self, index: int) -> bool:
        row = int(index) - 1
        if not 0 <= row < len(self._items):
            return False
        del self._items[row]
        self._rebuild()
        self._persist()
        return True

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dash.save"), "dashboard.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(project_to_json(self._items))
        except OSError as exc:
            self.empty.setText(str(exc))
            return
        self._persist()

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("dash.load"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self._items = project_from_json(text)
        except (OSError, ValueError, TypeError) as exc:
            self.empty.setText(str(exc))
            return
        self._rebuild()
        self._persist()

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        raw = prefs.get("project")
        if isinstance(raw, str) and raw.strip():
            try:
                self._items = project_from_json(raw)
            except (ValueError, TypeError):
                self._items = []
        source = str(prefs.get("source") or "any")
        index = self.source.findData(source)
        if index >= 0:
            self.source.setCurrentIndex(index)
        self._rebuild()

    def _persist(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "source": str(self.source.currentData() or "any"),
                "project": project_to_json(self._items),
            },
        )
