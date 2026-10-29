"""Serial page: quick-send presets, trigger replies, and cyclic send."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from etools.core.trigger_reply import MAX_RULES
from etools.i18n import tr

_PRESET_COUNT = 8


class SerialQuickSendMixin:
    """Presets, auto-reply rules, and cyclic send for SerialPage."""

    def _build_presets(self) -> None:
        """Eight quick-send rows with Alt+1…8 shortcuts."""
        self.preset_content = QWidget()
        preset_lay = QVBoxLayout(self.preset_content)
        preset_lay.setContentsMargins(0, 4, 0, 0)
        preset_lay.setSpacing(4)
        self.preset_shortcuts = QCheckBox(tr("serial.preset_shortcuts"))
        self.preset_shortcuts.setToolTip(tr("serial.preset_shortcuts_tip"))
        self.preset_shortcuts.setChecked(True)
        preset_lay.addWidget(self.preset_shortcuts)
        self._preset_checks: list[QCheckBox] = []
        self._preset_edits: list[QLineEdit] = []
        self._preset_btns: list[QPushButton] = []
        self._preset_shortcut_objs: list[QShortcut] = []
        for i in range(_PRESET_COUNT):
            row = QHBoxLayout()
            row.setSpacing(6)
            check = QCheckBox()
            check.setToolTip(tr("serial.cycle_pick"))
            check.setFixedWidth(20)
            edit = QLineEdit()
            edit.setFixedHeight(28)
            edit.setPlaceholderText(tr("serial.presets_ph", n=i + 1))
            btn = QPushButton(tr("serial.send"))
            btn.setObjectName("ghost")
            btn.setFixedHeight(28)
            btn.setFixedWidth(56)
            btn.setEnabled(False)
            row.addWidget(check)
            row.addWidget(edit, 1)
            row.addWidget(btn)
            preset_lay.addLayout(row)
            self._preset_checks.append(check)
            self._preset_edits.append(edit)
            self._preset_btns.append(btn)
            btn.clicked.connect(lambda _c=False, idx=i: self._on_preset_send(idx))
            edit.editingFinished.connect(self.persist_prefs)
            check.toggled.connect(lambda _c: self.persist_prefs())
            shortcut = QShortcut(QKeySequence(f"Alt+{i + 1}"), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda idx=i: self._on_preset_shortcut(idx))
            self._preset_shortcut_objs.append(shortcut)

    def _build_triggers(self) -> None:
        """Auto-reply rule rows."""
        self.trigger_content = QWidget()
        trigger_lay = QVBoxLayout(self.trigger_content)
        trigger_lay.setContentsMargins(0, 4, 0, 0)
        trigger_lay.setSpacing(4)
        self._trigger_enables: list[QCheckBox] = []
        self._trigger_modes: list[QComboBox] = []
        self._trigger_patterns: list[QLineEdit] = []
        self._trigger_replies: list[QLineEdit] = []
        self._trigger_hex: list[QCheckBox] = []
        self._trigger_cooldowns: list[QSpinBox] = []
        self._trigger_onces: list[QCheckBox] = []
        for _i in range(MAX_RULES):
            row = QHBoxLayout()
            row.setSpacing(4)
            enable = QCheckBox()
            enable.setFixedWidth(20)
            enable.setToolTip(tr("serial.trigger_enable"))
            mode = QComboBox()
            mode.setFixedHeight(26)
            mode.setFixedWidth(78)
            for mid, key in (
                ("text", "serial.trigger_mode.text"),
                ("hex", "serial.trigger_mode.hex"),
                ("regex", "serial.trigger_mode.regex"),
            ):
                mode.addItem(tr(key), mid)
            pattern = QLineEdit()
            pattern.setFixedHeight(26)
            pattern.setPlaceholderText(tr("serial.trigger_pattern_ph"))
            reply = QLineEdit()
            reply.setFixedHeight(26)
            reply.setPlaceholderText(tr("serial.trigger_reply_ph"))
            hex_check = QCheckBox(tr("serial.mode.hex"))
            hex_check.setFixedWidth(48)
            cooldown = QSpinBox()
            cooldown.setRange(0, 600_000)
            cooldown.setValue(200)
            cooldown.setSuffix(" ms")
            cooldown.setFixedHeight(26)
            cooldown.setFixedWidth(90)
            once = QCheckBox(tr("serial.trigger_once"))
            once.setFixedWidth(48)
            row.addWidget(enable)
            row.addWidget(mode)
            row.addWidget(pattern, 2)
            row.addWidget(reply, 2)
            row.addWidget(hex_check)
            row.addWidget(cooldown)
            row.addWidget(once)
            trigger_lay.addLayout(row)
            self._trigger_enables.append(enable)
            self._trigger_modes.append(mode)
            self._trigger_patterns.append(pattern)
            self._trigger_replies.append(reply)
            self._trigger_hex.append(hex_check)
            self._trigger_cooldowns.append(cooldown)
            self._trigger_onces.append(once)
            for widget in (enable, mode, hex_check, once):
                if isinstance(widget, QCheckBox):
                    widget.toggled.connect(lambda _c: self._sync_trigger_rules())
                else:
                    widget.currentIndexChanged.connect(lambda _i: self._sync_trigger_rules())
            for widget in (pattern, reply):
                widget.editingFinished.connect(self._sync_trigger_rules)
            cooldown.valueChanged.connect(lambda _v: self._sync_trigger_rules())

    def _build_cyclic(self) -> None:
        """Cyclic send controls; they live with the send options."""
        self.cyclic_check = QCheckBox(tr("serial.cyclic"))
        self.cyclic_check.setToolTip(tr("serial.cyclic_tip"))
        self.lbl_interval = QLabel(tr("serial.cyclic_interval"))
        self.cyclic_interval = QSpinBox()
        self.cyclic_interval.setRange(1, 600_000)
        self.cyclic_interval.setSingleStep(10)
        self.cyclic_interval.setValue(1000)
        self.cyclic_interval.setSuffix(" ms")
        self.cyclic_interval.setFixedHeight(28)
        self.cyclic_interval.setFixedWidth(96)
        # Lives with send options — never inside the preset list (avoids overlap).
        self._cyclic_timer = QTimer(self)
        self._cyclic_timer.timeout.connect(self._on_cyclic_tick)
        self._cyclic_index = 0

    def _import_presets(self) -> None:
        import json

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, tr("serial.presets_import"), "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            from etools.ui.kit import toast

            toast(tr("serial.presets_import_err"))
            return
        items = data if isinstance(data, list) else data.get("presets")
        if not isinstance(items, list):
            return
        for i, edit in enumerate(self._preset_edits):
            if i < len(items) and isinstance(items[i], str):
                edit.setText(items[i])
        self.persist_prefs()
        from etools.ui.kit import toast

        toast(tr("serial.presets_imported", n=min(len(items), len(self._preset_edits))))

    def _export_presets(self) -> None:
        import json

        from PySide6.QtWidgets import QFileDialog

        from etools.ui.kit import toast

        path, _ = QFileDialog.getSaveFileName(
            self, tr("serial.presets_export"), "etools-presets.json", "JSON (*.json)"
        )
        if not path:
            return
        payload = [e.text() for e in self._preset_edits]
        Path(path).write_text(
            json.dumps({"presets": payload}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        toast(tr("serial.presets_exported"))

    def _on_preset_send(self, index: int) -> None:
        if not (0 <= index < len(self._preset_edits)):
            return
        text = self._preset_edits[index].text().strip()
        if not text:
            return
        self._send_payload(text, record_history=True)

    def _on_preset_shortcut(self, index: int) -> None:
        if not self.preset_shortcuts.isChecked() or not self._opened:
            return
        focus = self.focusWidget()
        if focus in self._preset_edits or focus is self.script_edit:
            return
        if focus in self._trigger_patterns or focus in self._trigger_replies:
            return
        self._on_preset_send(index)

    def _on_preset_shortcuts_toggled(self, on: bool) -> None:
        for shortcut in self._preset_shortcut_objs:
            shortcut.setEnabled(bool(on))
        if getattr(self, "_loading_prefs", False):
            return
        self.persist_prefs()

    def _sync_trigger_rules(self, *_args, persist: bool = True) -> None:
        rules = []
        for i in range(MAX_RULES):
            rules.append(
                {
                    "enabled": self._trigger_enables[i].isChecked(),
                    "mode": self._trigger_modes[i].currentData(),
                    "pattern": self._trigger_patterns[i].text(),
                    "reply": self._trigger_replies[i].text(),
                    "reply_hex": self._trigger_hex[i].isChecked(),
                    "cooldown_ms": int(self._trigger_cooldowns[i].value()),
                    "once": self._trigger_onces[i].isChecked(),
                }
            )
        self._trigger.load_rules(rules)
        if persist and not getattr(self, "_loading_prefs", False):
            self.persist_prefs()

    def _apply_trigger_rules_to_ui(self) -> None:
        for i, rule in enumerate(self._trigger.rules):
            self._trigger_enables[i].blockSignals(True)
            self._trigger_modes[i].blockSignals(True)
            self._trigger_cooldowns[i].blockSignals(True)
            self._trigger_enables[i].setChecked(rule.enabled)
            idx = self._trigger_modes[i].findData(rule.mode)
            if idx >= 0:
                self._trigger_modes[i].setCurrentIndex(idx)
            self._trigger_patterns[i].setText(rule.pattern)
            self._trigger_replies[i].setText(rule.reply)
            self._trigger_hex[i].setChecked(rule.reply_hex)
            self._trigger_cooldowns[i].setValue(int(rule.cooldown_ms))
            self._trigger_onces[i].setChecked(rule.once)
            self._trigger_enables[i].blockSignals(False)
            self._trigger_modes[i].blockSignals(False)
            self._trigger_cooldowns[i].blockSignals(False)

    def _on_cyclic_toggled(self, on: bool) -> None:
        if on:
            if not self._opened:
                self.cyclic_check.blockSignals(True)
                self.cyclic_check.setChecked(False)
                self.cyclic_check.blockSignals(False)
                self.traffic.append_status(tr("serial.cyclic_need_open"))
                return
            self._cyclic_index = 0
            self._cyclic_timer.start(max(1, int(self.cyclic_interval.value())))
            self.traffic.append_status(tr("serial.cyclic_running"))
        else:
            self._cyclic_timer.stop()
        self.persist_prefs()

    def _on_interval_changed(self, value: int) -> None:
        if self._cyclic_timer.isActive():
            self._cyclic_timer.setInterval(max(1, int(value)))
        self.persist_prefs()

    def _stop_cyclic(self) -> None:
        self._cyclic_timer.stop()
        if self.cyclic_check.isChecked():
            self.cyclic_check.blockSignals(True)
            self.cyclic_check.setChecked(False)
            self.cyclic_check.blockSignals(False)

    def _on_cyclic_tick(self) -> None:
        if not self._opened:
            self._stop_cyclic()
            return
        targets = [
            edit.text().strip()
            for check, edit in zip(self._preset_checks, self._preset_edits, strict=True)
            if check.isChecked() and edit.text().strip()
        ]
        if targets:
            text = targets[self._cyclic_index % len(targets)]
            self._cyclic_index += 1
        else:
            text = self.send_edit.text().strip()
        if not text:
            self.traffic.append_status(tr("serial.cyclic_empty"))
            self._stop_cyclic()
            return
        self._send_payload(text)
