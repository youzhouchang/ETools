"""Dashboard shared by serial, network, and MQTT frames.

The field list and the live dashboard are two views of one JSON project.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from etools.core.dashboard import (
    WIDGET_TYPES,
    DashWidget,
    project_from_json,
    project_to_json,
)
from etools.core.frame_hub import frame_hub
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.dashboard_cards import DashCard


class _Relay(QObject):
    frame = Signal(str, object)


_TYPE_KEYS = {
    "value": "dash.type.value",
    "gauge": "dash.type.gauge",
    "bar": "dash.type.bar",
    "plot": "dash.type.plot",
    "multiplot": "dash.type.multi",
}


class DashboardPage(ToolPage):
    tool_id = "dash"
    tool_title_key = "tool.dash"

    def _build(self) -> None:
        self._items: list[DashWidget] = []
        self._cards: list[DashCard] = []
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
        self.board = QWidget()
        self.grid = QGridLayout(self.board)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.empty = QLabel(tr("dash.empty"))
        self.grid.addWidget(self.empty, 0, 0)
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.stack.addWidget(self.board)
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
        self._fill_sources()
        self._load_prefs()
        self._show(0)
        self.retranslate()

    def retranslate(self) -> None:
        self.ctx_box.setTitle(tr("dash.title"))
        self.lbl_source.setText(tr("dash.source"))
        self.lbl_kind.setText(tr("dash.type"))
        self.lbl_title.setText(tr("dash.name"))
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
        self.source.blockSignals(False)

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
        )

    def _add(self) -> None:
        self._items.append(self._form_spec())
        self._rebuild()
        self._persist()

    def _apply(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        self._items[row] = self._form_spec()
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
        index = self.kind.findData(spec.type)
        if index >= 0:
            self.kind.setCurrentIndex(index)
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
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = []
        if not self._items:
            self.empty.show()
            if self.grid.indexOf(self.empty) < 0:
                self.grid.addWidget(self.empty, 0, 0)
        else:
            self.empty.hide()
            for index, spec in enumerate(self._items):
                card = DashCard(spec)
                self._cards.append(card)
                self.grid.addWidget(card, index // 2, index % 2)
        self._fill_table()

    def _on_frame(self, source: str, frame: object) -> None:
        if not isinstance(frame, dict):
            return
        wanted = str(self.source.currentData() or "any")
        if wanted != "any" and source != wanted:
            return
        for card in self._cards:
            card.push(frame)

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
