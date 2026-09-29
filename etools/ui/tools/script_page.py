"""Global Lua scripting workbench (serial / net / terminal / flash)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)

from etools.core import script_store
from etools.core.script_samples import ensure_samples
from etools.i18n import tr
from etools.ui.script_service import script_service
from etools.ui.shell import ToolActionSpec
from etools.ui.tools.base import ToolPage

_TEMPLATES = {
    "blank": "-- ETools Lua\netools.app.log('hello')\n",
    "serial": (
        "-- 串口轮询示例\n"
        "etools.serial.send('AT')\n"
        "if etools.serial.expect('OK', 2000) then\n"
        "  etools.app.log('device ready')\n"
        "else\n"
        "  etools.app.log('timeout')\n"
        "end\n"
    ),
    "checksum": (
        "-- 帧校验示例\n"
        "local body = etools.util.unhex('01 03 00 00 00 01')\n"
        "local frame = etools.util.append_checksum(body, 'crc16_modbus')\n"
        "etools.app.log('frame ' .. etools.util.hex(frame))\n"
        "assert(etools.util.verify_checksum(frame, 'crc16_modbus'))\n"
    ),
    "flash": (
        "-- 自定义烧录流程示例（需先连接探针）\n"
        "if not etools.flash.connected() then\n"
        "  etools.app.log('probe not connected')\n"
        "  return\n"
        "end\n"
        "-- etools.flash.erase_range(0x08000000, 0x1000)\n"
        "-- etools.flash.program('firmware.elf', true)\n"
        "-- etools.flash.reset()\n"
        "etools.app.log('flash steps ready')\n"
    ),
}


class ScriptPage(ToolPage):
    tool_id = "script"
    tool_title_key = "tool.script"

    def _build(self) -> None:
        self.svc = script_service()
        self.svc.log.connect(self._append_log)
        self.svc.done.connect(self._on_script_done)
        self._current_name = ""

        # Left: file management (uses ToolPage ctx + main split like other tools)
        self.ctx_files = self.ctx_group(tr("script.file"))
        self.file_combo = QComboBox()
        self.file_combo.setFixedHeight(28)
        self.file_combo.setToolTip(tr("script.file_tip"))
        self.lbl_file = self.form_row(tr("script.file"), self.file_combo)

        self.template_combo = QComboBox()
        self.template_combo.setFixedHeight(28)
        self.template_combo.addItem(tr("script.tpl.blank"), "blank")
        self.template_combo.addItem(tr("script.tpl.serial"), "serial")
        self.template_combo.addItem(tr("script.tpl.checksum"), "checksum")
        self.template_combo.addItem(tr("script.tpl.flash"), "flash")
        self.lbl_template = self.form_row(tr("script.template"), self.template_combo)

        # 2×2 button grid (full ctx width — do not nest in a form field).
        self.new_btn = QPushButton(tr("script.new"))
        self.new_btn.setObjectName("ghost")
        self.save_btn = QPushButton(tr("script.save"))
        self.save_btn.setObjectName("ghost")
        self.delete_btn = QPushButton(tr("script.delete"))
        self.delete_btn.setObjectName("ghost")
        self.reload_btn = QPushButton(tr("script.reload"))
        self.reload_btn.setObjectName("ghost")
        for b in (self.new_btn, self.save_btn, self.delete_btn, self.reload_btn):
            b.setFixedHeight(28)
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setSpacing(6)
        grid.addWidget(self.new_btn, 0, 0)
        grid.addWidget(self.save_btn, 0, 1)
        grid.addWidget(self.delete_btn, 1, 0)
        grid.addWidget(self.reload_btn, 1, 1)
        self.ctx_layout.addLayout(grid)

        self.run_btn = QPushButton(tr("script.run"))
        self.run_btn.setObjectName("accent")
        self.run_btn.setFixedHeight(32)
        self.stop_btn = QPushButton(tr("script.stop"))
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setFixedHeight(28)
        self.stop_btn.setEnabled(False)
        self.ctx_layout.addWidget(self.run_btn)
        self.ctx_layout.addWidget(self.stop_btn)
        self.ctx_layout.addStretch(1)

        # Main: editor + console
        self.status = QLabel(tr("script.idle"))
        self.status.setObjectName("mutedLabel")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("logView")
        self.editor.setPlaceholderText(tr("script.placeholder"))
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

        console_bar = QHBoxLayout()
        console_bar.addWidget(QLabel(tr("script.console")))
        self.clear_btn = QPushButton(tr("mon.clear"))
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setFixedHeight(24)
        console_bar.addStretch(1)
        console_bar.addWidget(self.clear_btn)

        self.console = QPlainTextEdit()
        self.console.setObjectName("logView")
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(160)
        self.console.setPlaceholderText(tr("script.console_ph"))
        self.console.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

        self.main_layout.addWidget(self.status)
        self.main_layout.addWidget(self.editor, 3)
        self.main_layout.addLayout(console_bar)
        self.main_layout.addWidget(self.console, 1)

        self.template_combo.currentIndexChanged.connect(self._on_template)
        self.file_combo.currentIndexChanged.connect(self._on_file_selected)
        self.new_btn.clicked.connect(self._on_new)
        self.save_btn.clicked.connect(self._on_save)
        self.delete_btn.clicked.connect(self._on_delete)
        self.reload_btn.clicked.connect(self.reload_files)
        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn.clicked.connect(self._on_stop)
        self.clear_btn.clicked.connect(self.console.clear)
        ensure_samples()
        self.reload_files()
        if self.file_combo.count() > 1:
            self.file_combo.setCurrentIndex(1)

    # -- file management -----------------------------------------------

    def reload_files(self, select: str | None = None) -> None:
        names = script_store.list_scripts()
        current = select or self._current_name
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        self.file_combo.addItem(tr("script.unsaved"), "")
        for name in names:
            self.file_combo.addItem(name, name)
        idx = self.file_combo.findData(current) if current else 0
        self.file_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.file_combo.blockSignals(False)
        self._current_name = str(self.file_combo.currentData() or "")

    def _on_file_selected(self, _index: int = 0) -> None:
        name = str(self.file_combo.currentData() or "")
        self._current_name = name
        if not name:
            return
        try:
            self.editor.setPlainText(script_store.load_script(name))
        except OSError as exc:
            self.console.appendPlainText(str(exc))

    def _on_new(self) -> None:
        self._current_name = ""
        self.file_combo.setCurrentIndex(0)
        self.editor.setPlainText(_TEMPLATES["blank"])

    def _on_save(self) -> None:
        name = self._current_name
        if not name:
            text, ok = QInputDialog.getText(
                self, tr("script.save_as"), tr("script.name_label")
            )
            if not ok or not text.strip():
                return
            name = text.strip()
        try:
            script_store.save_script(name, self.editor.toPlainText())
        except (OSError, ValueError) as exc:
            self.console.appendPlainText(str(exc))
            return
        self._current_name = name
        self.reload_files(select=name)
        self.console.appendPlainText(tr("script.saved", name=name))

    def _on_delete(self) -> None:
        name = self._current_name
        if not name:
            return
        try:
            script_store.delete_script(name)
        except OSError as exc:
            self.console.appendPlainText(str(exc))
            return
        self._current_name = ""
        self.reload_files()
        self.console.appendPlainText(tr("script.deleted", name=name))

    # -- tool API ------------------------------------------------------

    def bind_flash(self, service) -> None:
        from etools.ui.tools.script_bridges import FlashLuaBridge, _QueueBridge

        if not hasattr(self, "_pump"):
            self._pump = _QueueBridge()
            self._pump.install(self)
        self.svc.set_bridge("flash", FlashLuaBridge(service, self._pump))

    def bind_serial(self, page) -> None:
        from etools.ui.tools.script_bridges import SerialLuaBridge, _QueueBridge

        if not hasattr(self, "_pump"):
            self._pump = _QueueBridge()
            self._pump.install(self)
        self.svc.set_bridge("serial", SerialLuaBridge(page, self._pump))

    def bind_net(self, page) -> None:
        from etools.ui.tools.script_bridges import NetLuaBridge, _QueueBridge

        if not hasattr(self, "_pump"):
            self._pump = _QueueBridge()
            self._pump.install(self)
        self.svc.set_bridge("net", NetLuaBridge(page, self._pump))

    def bind_term(self, page) -> None:
        from etools.ui.tools.script_bridges import TermLuaBridge, _QueueBridge

        if not hasattr(self, "_pump"):
            self._pump = _QueueBridge()
            self._pump.install(self)
        self.svc.set_bridge("term", TermLuaBridge(page, self._pump))

    def run_named(self, name: str) -> bool:
        """Run a saved script from another tool page's toolbar."""
        if not self.svc.available():
            self.console.appendPlainText(tr("script.need_lupa"))
            return False
        try:
            self.svc.run_named(name)
        except Exception as exc:  # noqa: BLE001
            self.console.appendPlainText(str(exc))
            return False
        self.status.setText(tr("script.running"))
        return True

    def retranslate(self) -> None:
        self.ctx_files.setTitle(tr("script.file"))
        self.lbl_file.setText(tr("script.file"))
        self.lbl_template.setText(tr("script.template"))
        self.file_combo.setToolTip(tr("script.file_tip"))
        self.new_btn.setText(tr("script.new"))
        self.save_btn.setText(tr("script.save"))
        self.delete_btn.setText(tr("script.delete"))
        self.reload_btn.setText(tr("script.reload"))
        self.template_combo.setItemText(0, tr("script.tpl.blank"))
        self.template_combo.setItemText(1, tr("script.tpl.serial"))
        self.template_combo.setItemText(2, tr("script.tpl.checksum"))
        self.template_combo.setItemText(3, tr("script.tpl.flash"))
        self.run_btn.setText(tr("script.run"))
        self.stop_btn.setText(tr("script.stop"))
        self.clear_btn.setText(tr("mon.clear"))
        if not self.svc.running:
            self.status.setText(tr("script.idle"))
        self.editor.setPlaceholderText(tr("script.placeholder"))
        self.console.setPlaceholderText(tr("script.console_ph"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("run", "script.run", "program", self._on_run),
            ToolActionSpec("stop", "script.stop", "stop", self._on_stop),
            ToolActionSpec("save", "script.save", "save", self._on_save),
        ]

    def shutdown(self) -> None:
        self.svc.stop()

    # -- internals -----------------------------------------------------

    def _on_template(self, _index: int = 0) -> None:
        key = str(self.template_combo.currentData() or "blank")
        self.editor.setPlainText(_TEMPLATES.get(key, _TEMPLATES["blank"]))

    def _append_log(self, message: str) -> None:
        self.console.appendPlainText(message)

    def _on_script_done(self, ok: bool, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status.setText(tr("script.done") if ok else tr("script.failed"))
        self.console.appendPlainText(message)

    def _on_run(self) -> None:
        if not self.svc.available():
            self.console.appendPlainText(tr("script.need_lupa"))
            return
        self.console.clear()
        source = self.editor.toPlainText()
        try:
            self.svc.run_source(source)
        except Exception as exc:  # noqa: BLE001
            self.console.appendPlainText(str(exc))
            return
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText(tr("script.running"))

    def _on_stop(self) -> None:
        self.svc.stop()
        self.status.setText(tr("script.stopped"))
