"""Programming and serial acceptance workflow with an exportable step report."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from etools.config import get_config, save_config
from etools.i18n import tr


class WorkflowDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(tr("workflow.title"))
        self.resize(640, 480)
        self.running = False
        self.stopping = False
        self.report = []
        self._rx = bytearray()
        self._wait_kind = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.firmware = QLineEdit(window.flash_panel.firmware_path())
        self.browse = QPushButton(tr("act.open"))
        self.browse.clicked.connect(self._browse)
        firmware_row = QHBoxLayout()
        firmware_row.addWidget(self.firmware, 1)
        firmware_row.addWidget(self.browse)
        form.addRow(tr("workflow.firmware"), firmware_row)
        self.verify = QCheckBox(tr("act.verify"))
        self.verify.setChecked(True)
        form.addRow(self.verify)
        saved = get_config().extra.get("workflow", {})
        self.startup = QLineEdit(saved.get("startup", ""))
        self.command = QLineEdit(saved.get("command", ""))
        self.expected = QLineEdit(saved.get("expected", "OK"))
        self.timeout = QSpinBox()
        self.timeout.setRange(100, 600000)
        self.timeout.setSuffix(" ms")
        self.timeout.setValue(int(saved.get("timeout", 5000)))
        form.addRow(tr("workflow.startup"), self.startup)
        form.addRow(tr("workflow.command"), self.command)
        form.addRow(tr("workflow.expected"), self.expected)
        form.addRow(tr("workflow.wait"), self.timeout)
        root.addLayout(form)
        self.results = QListWidget()
        root.addWidget(self.results, 1)
        row = QHBoxLayout()
        self.run_btn = QPushButton(tr("workflow.run"))
        self.run_btn.setObjectName("accent")
        self.stop_btn = QPushButton(tr("script.stop"))
        self.stop_btn.setEnabled(False)
        self.export_btn = QPushButton(tr("workflow.export"))
        self.export_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)
        self.stop_btn.clicked.connect(self._stop)
        self.export_btn.clicked.connect(self._export)
        for button in (self.run_btn, self.stop_btn, self.export_btn):
            row.addWidget(button)
        root.addLayout(row)
        window.serial_page._relay.received.connect(self._receive)

    def load_settings(self):
        if self.running:
            return
        saved = get_config().extra.get("workflow", {})
        self.firmware.setText(self.window.flash_panel.firmware_path())
        self.startup.setText(saved.get("startup", ""))
        self.command.setText(saved.get("command", ""))
        self.expected.setText(saved.get("expected", "OK"))
        self.timeout.setValue(int(saved.get("timeout", 5000)))

    def _browse(self):
        from etools.core.models import FIRMWARE_EXTENSIONS

        path, _ = QFileDialog.getOpenFileName(self, tr("act.open"), "", FIRMWARE_EXTENSIONS)
        if path:
            self.firmware.setText(path)

    def _record(self, step, ok, detail=""):
        self.report.append(
            {"time": datetime.now().isoformat(), "step": step, "ok": ok, "detail": detail}
        )
        self.results.addItem(f"{step}: {'OK' if ok else 'FAIL'} {detail}")

    def _run(self):
        window = self.window
        if self.running:
            return
        if (
            window.runner.busy
            or window.script_page.svc.running
            or not window.service.connected
            or not window.serial_page.is_open
        ):
            QMessageBox.warning(self, tr("workflow.title"), tr("workflow.preflight"))
            return
        if not Path(self.firmware.text()).is_file() or not self.expected.text():
            QMessageBox.warning(self, tr("workflow.title"), tr("workflow.invalid"))
            return
        get_config().extra["workflow"] = {
            "startup": self.startup.text(),
            "command": self.command.text(),
            "expected": self.expected.text(),
            "timeout": self.timeout.value(),
        }
        save_config()
        self.report = []
        self.results.clear()
        self._rx.clear()
        self.running = True
        self.stopping = False
        window.workflow_active = True
        window.set_busy(True)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        for widget in (
            self.firmware,
            self.browse,
            self.verify,
            self.startup,
            self.command,
            self.expected,
            self.timeout,
        ):
            widget.setEnabled(False)
        path, verify = self.firmware.text(), self.verify.isChecked()
        self._run_firmware = path
        self._run_settings = dict(get_config().extra["workflow"], verify=verify)
        self._operation(
            tr("act.program"), lambda: window.service.program_file(path, verify=verify), self._reset
        )

    def _operation(self, step, fn, next_step):
        self.results.addItem(step + " ...")

        def ok(result):
            success = bool(getattr(result, "ok", False))
            self._record(step, success, getattr(result, "message", ""))
            if self.stopping:
                self._finish(False, tr("script.stopped"))
            elif success:
                next_step()
            else:
                self._finish(False, getattr(result, "message", ""))

        def fail(message):
            self._record(step, False, message)
            self._finish(False, message)

        if not self.window.runner.start(fn, ok, fail):
            fail(tr("workflow.preflight"))

    def _reset(self):
        self._rx.clear()
        self._operation(tr("act.reset"), self.window.service.reset_target, self._wait_startup)

    def _wait_startup(self):
        if self.startup.text():
            self._wait_kind = "startup"
            self._timer.start(self.timeout.value())
            self._check_rx()
        else:
            self._send()

    def _send(self):
        command = self.command.text()
        if command:
            self._rx.clear()
        if command and not self.window.serial_page._send_payload(command):
            self._finish(False, tr("workflow.send_failed"))
            return
        self._record(tr("workflow.command"), True, command)
        self._wait_kind = "expected"
        self._timer.start(self.timeout.value())
        self._check_rx()

    def _timed_out(self):
        self._record(tr("workflow." + self._wait_kind), False, tr("workflow.timeout"))
        self._finish(False, tr("workflow.timeout"))

    def _receive(self, data):
        if self.running:
            self._rx.extend(data)
            del self._rx[:-65536]
            self._check_rx()

    def _check_rx(self):
        if not self._wait_kind:
            return
        target = self.startup.text() if self._wait_kind == "startup" else self.expected.text()
        needle = target.encode(self.window.serial_page._encoding_name())
        if needle not in self._rx:
            return
        kind = self._wait_kind
        self._wait_kind = ""
        self._timer.stop()
        self._record(tr("workflow." + kind), True, target)
        if kind == "startup":
            self._send()
        else:
            self._finish(True)

    def _finish(self, ok, detail=""):
        self._timer.stop()
        self._wait_kind = ""
        self.running = False
        self.window.workflow_active = False
        self.window.set_busy(False)
        self._record(tr("workflow.result"), ok, detail)
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(True)
        for widget in (
            self.firmware,
            self.browse,
            self.verify,
            self.startup,
            self.command,
            self.expected,
            self.timeout,
        ):
            widget.setEnabled(True)

    def _stop(self):
        self.stopping = True
        self.stop_btn.setEnabled(False)
        if not self.window.runner.busy:
            self._finish(False, tr("script.stopped"))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("workflow.export"), "workflow.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        {
                            "firmware": self._run_firmware,
                            "settings": self._run_settings,
                            "steps": self.report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                QMessageBox.warning(self, tr("workflow.title"), str(exc))

    def reject(self):
        if self.running:
            self._stop()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.running:
            self._stop()
            event.ignore()
        else:
            super().closeEvent(event)
