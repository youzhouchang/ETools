"""Option bytes / RDP / write protection editor."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.option_bytes import ObField, ObSnapshot
from etools.i18n import tr
from etools.ui.widgets.flash_tools_common import confirm, int_edit, parse_int, tool_button

_CHANGED = QColor(255, 170, 0, 60)


def field_desc_key(key: str) -> str:
    if key.startswith("WRP") and key[3:].isdigit():
        return "ob.f.WRPx"
    return f"ob.f.{key}"


def choice_text(label: str) -> str:
    return tr(label) if label.startswith("ob.") else label


class OptionBytesPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host: Any = None
        self._snap: ObSnapshot | None = None
        self._editors: list[tuple[ObField, QWidget]] = []
        self._connected = False
        self._build()

    def bind(self, host: Any) -> None:
        self._host = host

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.read_btn = tool_button("read")
        self.write_btn = tool_button("program", kind="accent")
        self.factory_btn = tool_button("refresh")
        self.protect_btn = tool_button("warning")
        self.unprotect_btn = tool_button("erase", kind="danger")
        for btn in (
            self.read_btn,
            self.write_btn,
            self.factory_btn,
            self.protect_btn,
            self.unprotect_btn,
        ):
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 200)
        root.addWidget(self.table, 1)

        self.read_btn.clicked.connect(self.read)
        self.write_btn.clicked.connect(self._write_clicked)
        self.factory_btn.clicked.connect(self._factory_clicked)
        self.protect_btn.clicked.connect(lambda: self._rdp_clicked(1))
        self.unprotect_btn.clicked.connect(lambda: self._rdp_clicked(0))
        self.retranslate()
        self._apply_enabled()

    def retranslate(self) -> None:
        self.read_btn.setText(tr("ob.read"))
        self.write_btn.setText(tr("ob.write"))
        self.factory_btn.setText(tr("ob.factory"))
        self.protect_btn.setText(tr("ob.protect"))
        self.unprotect_btn.setText(tr("ob.unprotect"))
        self.table.setHorizontalHeaderLabels(
            [tr("ob.col.field"), tr("ob.col.current"), tr("ob.col.new"), tr("ob.col.desc")]
        )
        if self._snap is not None:
            self._show(self._snap)
        else:
            self.status.setText(tr("ob.hint"))

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._snap = None
            self.table.setRowCount(0)
            self._editors = []
            self.status.setText(tr("ob.hint"))
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        loaded = self._connected and self._snap is not None
        self.read_btn.setEnabled(self._connected)
        for btn in (self.write_btn, self.factory_btn, self.protect_btn, self.unprotect_btn):
            btn.setEnabled(loaded)
        if loaded:
            level = self._snap.rdp_level
            self.protect_btn.setEnabled(level == 0)
            self.unprotect_btn.setEnabled(level == 1)
            self.write_btn.setEnabled(level != 2)
            self.factory_btn.setEnabled(level != 2)

    # -- read -------------------------------------------------------------

    def read(self) -> None:
        if self._host is None:
            return

        def on_ok(snap: ObSnapshot) -> None:
            self._snap = snap
            self._show(snap)
            self._apply_enabled()
            self._host.log(tr("ob.read_ok", family=snap.family.title, level=snap.rdp_level))

        def on_err(msg: str) -> None:
            self.status.setText(tr("ob.read_fail", err=msg))

        self._host.run_job(self._host.service.read_option_bytes, on_ok, on_err)

    def _show(self, snap: ObSnapshot) -> None:
        self.status.setText(
            tr(
                "ob.status",
                family=snap.family.title,
                dev=f"0x{snap.dev_id:03X}",
                level=snap.rdp_level,
                reload=tr(f"ob.reload.{snap.family.reload}"),
            )
        )
        fields = snap.family.fields
        self.table.setRowCount(len(fields))
        self._editors = []
        for row, f in enumerate(fields):
            name = ("⚠ " if f.danger else "") + f.key
            item = QTableWidgetItem(name)
            item.setToolTip(f"{f.reg}[{f.shift + f.width - 1}:{f.shift}]")
            self.table.setItem(row, 0, item)
            value = snap.values[f.key]
            self.table.setItem(row, 1, QTableWidgetItem(self._value_text(snap, f, value)))
            editor = self._editor(snap, f, value)
            self.table.setCellWidget(row, 2, editor)
            self._editors.append((f, editor))
            desc = tr(field_desc_key(f.key))
            if f.readonly:
                desc = f"{desc} ({tr('ob.readonly')})"
            self.table.setItem(row, 3, QTableWidgetItem(desc))
        self._mark_changes()

    def _value_text(self, snap: ObSnapshot, f: ObField, value: int) -> str:
        if f.kind == "rdp":
            return f"Level {snap.family.rdp_level(value)} (0x{value:02X})"
        if f.kind == "hex":
            return f"0x{value:0{(f.width + 3) // 4}X}"
        for v, label in f.choices:
            if v == value:
                return f"{value}: {choice_text(label)}"
        return str(value)

    def _editor(self, snap: ObSnapshot, f: ObField, value: int) -> QWidget:
        if f.kind == "hex":
            edit = int_edit(value, width=160, digits=(f.width + 3) // 4)
            edit.setEnabled(not f.readonly)
            edit.textChanged.connect(self._mark_changes)
            return edit
        combo = QComboBox()
        choices = list(f.choices)
        if f.kind == "rdp" and snap.family.rdp_level(value) == 1 and value != snap.family.rdp_l1:
            # Keep the chip's own Level 1 byte selectable so a no-op stays a no-op.
            choices.append((value, "ob.v.rdp1"))
        known = {v for v, _ in choices}
        if value not in known:
            choices.append((value, f"0x{value:X}"))
        for v, label in choices:
            text = choice_text(label)
            combo.addItem(f"{text} (0x{v:X})" if f.kind == "rdp" else f"{v}: {text}", v)
        combo.setCurrentIndex(combo.findData(value))
        combo.setEnabled(not f.readonly and not (f.kind == "rdp" and value == 0xCC))
        combo.currentIndexChanged.connect(self._mark_changes)
        return combo

    def _editor_value(self, f: ObField, editor: QWidget) -> int:
        if isinstance(editor, QLineEdit):
            return parse_int(editor.text())
        assert isinstance(editor, QComboBox)
        return int(editor.currentData())

    def pending_values(self) -> dict[str, int]:
        """Edited values that differ from the chip (raises ValueError on bad input)."""
        if self._snap is None:
            return {}
        out: dict[str, int] = {}
        for f, editor in self._editors:
            if f.readonly:
                continue
            value = self._editor_value(f, editor)
            if not 0 <= value <= f.max_value:
                raise ValueError(tr("ob.bad_value", field=f.key, max=f"0x{f.max_value:X}"))
            if value != self._snap.values[f.key]:
                out[f.key] = value
        return out

    def _mark_changes(self, *_args) -> None:
        if self._snap is None:
            return
        for row, (f, editor) in enumerate(self._editors):
            try:
                changed = self._editor_value(f, editor) != self._snap.values[f.key]
            except ValueError:
                changed = True
            for col in (0, 1, 3):
                item = self.table.item(row, col)
                if item is not None:
                    item.setBackground(_CHANGED if changed else QColor(0, 0, 0, 0))

    # -- write ------------------------------------------------------------

    def _factory_clicked(self) -> None:
        if self._snap is None:
            return
        for f, editor in self._editors:
            if f.key not in self._snap.factory:
                continue
            value = self._snap.factory[f.key]
            if isinstance(editor, QLineEdit):
                editor.setText(f"0x{value:0{(f.width + 3) // 4}X}")
            elif isinstance(editor, QComboBox):
                idx = editor.findData(value)
                if idx >= 0:
                    editor.setCurrentIndex(idx)
        self._host.log(tr("ob.factory_loaded"))

    def _rdp_clicked(self, level: int) -> None:
        if self._snap is None:
            return
        fam = self._snap.family
        self._write({"RDP": fam.rdp_l1 if level == 1 else fam.rdp_l0})

    def _write_clicked(self) -> None:
        try:
            values = self.pending_values()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if not values:
            self._host.log(tr("ob.no_change"))
            self.status.setText(tr("ob.no_change"))
            return
        self._write(values)

    def _write(self, values: dict[str, int]) -> None:
        snap = self._snap
        if snap is None or self._host is None:
            return
        fam = snap.family
        lines = [
            f"{key}: 0x{snap.values[key]:X} → 0x{value:X}" for key, value in values.items()
        ]
        warn: list[str] = []
        if "RDP" in values:
            new_level = fam.rdp_level(values["RDP"])
            if new_level == 2:
                self.status.setText(tr("ob.level2_refused"))
                return
            if new_level > snap.rdp_level:
                warn.append(tr("ob.warn_protect"))
            elif new_level < snap.rdp_level:
                warn.append(tr("ob.warn_unprotect"))
        if any(fam.get_field(k).danger for k in values):
            warn.append(tr("ob.warn_danger"))
        warn.append(tr(f"ob.reload_note.{fam.reload}"))
        text = tr("ob.confirm_text", changes="\n".join(lines), warn="\n\n".join(warn))
        if not confirm(self, tr("ob.confirm_title"), text, danger=True):
            return
        if "RDP" in values and fam.rdp_level(values["RDP"]) < snap.rdp_level:
            if not confirm(self, tr("ob.confirm_title"), tr("ob.confirm_erase"), danger=True):
                return

        service = self._host.service

        def work():
            result = service.write_option_bytes(values)
            fresh = None
            if result.ok:
                try:
                    fresh = service.read_option_bytes()
                except Exception:
                    fresh = None
            return result, fresh

        def on_ok(pair) -> None:
            result, fresh = pair
            self._host.log(result.message, not result.ok)
            outcome = getattr(result, "data", None)
            self.status.setText(result.message)
            if not result.ok:
                if outcome is not None and outcome.reload == "obl":
                    self._host.mark_disconnected()
                return
            if fresh is not None:
                self._snap = fresh
                self._show(fresh)
                self.status.setText(f"{result.message}\n{self.status.text()}")
            self._apply_enabled()
            if outcome is not None and outcome.reload in ("obl", "reset"):
                self._host.refresh_target()

        def on_err(msg: str) -> None:
            self.status.setText(tr("ob.write_fail", err=msg))

        self._host.log(tr("ob.writing", changes=", ".join(lines)))
        self._host.run_job(work, on_ok, on_err)
