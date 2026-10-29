"""Serial page: terminal tab and send/expect automation tab."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.ui.widgets.terminal_view import TerminalView
from etools.ui.widgets.traffic_view import decode_payload


class SerialWorkTabsMixin:
    """Terminal and automation-script tabs for SerialPage."""

    def _build_terminal_tab(self) -> None:
        """Interactive terminal tab."""
        self.terminal_box = QWidget()
        terminal_lay = QVBoxLayout(self.terminal_box)
        terminal_lay.setContentsMargins(8, 8, 8, 8)
        terminal_lay.setSpacing(6)
        terminal_bar = QHBoxLayout()
        self.local_echo = QCheckBox(tr("serial.terminal.local_echo"))
        self.local_echo.setChecked(True)
        self.terminal_break = QPushButton(tr("serial.terminal.break"))
        self.terminal_break.setObjectName("ghost")
        self.terminal_break.setEnabled(False)
        self.terminal_clear = QPushButton(tr("mon.clear"))
        self.terminal_clear.setObjectName("ghost")
        terminal_bar.addWidget(self.local_echo)
        terminal_bar.addStretch(1)
        terminal_bar.addWidget(self.terminal_break)
        terminal_bar.addWidget(self.terminal_clear)
        self.terminal_view = TerminalView(interactive=True)
        self.terminal_view.setPlaceholderText(tr("serial.terminal.placeholder"))
        self.terminal_view.document().setMaximumBlockCount(10000)
        terminal_lay.addLayout(terminal_bar)
        terminal_lay.addWidget(self.terminal_view, 1)
        self.work_tabs.addTab(self.terminal_box, tr("serial.terminal"))

    def _build_script_tab(self) -> None:
        """Send / wait / expect automation tab."""
        self.script_box = QWidget()
        script_lay = QVBoxLayout(self.script_box)
        script_lay.setContentsMargins(8, 8, 8, 8)
        script_lay.setSpacing(6)
        script_bar = QHBoxLayout()
        self.script_run = QPushButton(tr("serial.script.run"))
        self.script_run.setObjectName("accent")
        self.script_stop = QPushButton(tr("serial.script.stop"))
        self.script_stop.setObjectName("ghost")
        self.script_stop.setEnabled(False)
        self.script_status = QLabel(tr("serial.script.idle"))
        self.script_status.setObjectName("mutedLabel")
        script_bar.addWidget(self.script_run)
        script_bar.addWidget(self.script_stop)
        script_bar.addWidget(self.script_status, 1)
        self.script_edit = QPlainTextEdit()
        self.script_edit.setObjectName("logView")
        self.script_edit.setPlaceholderText(tr("serial.script.placeholder"))
        self.script_edit.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        script_lay.addLayout(script_bar)
        script_lay.addWidget(self.script_edit, 1)
        self.work_tabs.addTab(self.script_box, tr("serial.script"))
        self._script_cmds: list = []
        self._script_index = 0
        self._script_rx = bytearray()
        self._script_timer = QTimer(self)
        self._script_timer.setSingleShot(True)
        self._script_timer.timeout.connect(self._script_step)
        self._script_running = False
        self._script_expect: str | None = None
        self._script_deadline: float = 0.0

    def _on_script_run(self) -> None:
        from etools.core.serial_script import ScriptError, parse_script

        try:
            cmds = parse_script(self.script_edit.toPlainText())
        except ScriptError as exc:
            self.script_status.setText(str(exc))
            self.traffic.append_status(tr("serial.script.err", err=str(exc)))
            return
        if not cmds:
            self.script_status.setText(tr("serial.script.empty"))
            return
        if not self._opened:
            self.traffic.append_status(tr("serial.cyclic_need_open"))
            self.script_status.setText(tr("serial.cyclic_need_open"))
            return
        self._script_cmds = cmds
        self._script_index = 0
        self._script_expect = None
        self._script_rx.clear()
        self._script_running = True
        self.script_run.setEnabled(False)
        self.script_stop.setEnabled(True)
        self.script_status.setText(tr("serial.script.running"))
        self.traffic.append_status(tr("serial.script.running"))
        self._script_timer.start(0)

    def _on_script_stop(self) -> None:
        self._script_running = False
        self._script_timer.stop()
        self._script_expect = None
        self.script_run.setEnabled(True)
        self.script_stop.setEnabled(False)
        self.script_status.setText(tr("serial.script.stopped"))
        self.traffic.append_status(tr("serial.script.stopped"))

    def _finish_script(self, message_key: str) -> None:
        self._script_running = False
        self._script_timer.stop()
        self._script_expect = None
        self.script_run.setEnabled(True)
        self.script_stop.setEnabled(False)
        self.script_status.setText(tr(message_key))
        self.traffic.append_status(tr(message_key))

    def _script_step(self) -> None:
        import time

        if not self._script_running:
            return
        if not self._opened:
            self._finish_script("serial.script.disconnected")
            return

        expect_text = self._script_expect
        if expect_text is not None:
            buf = self._script_rx.decode("utf-8", errors="replace")
            if expect_text in buf:
                self._script_expect = None
                self._script_timer.start(0)
                return
            if time.monotonic() >= self._script_deadline:
                self.traffic.append_status(
                    tr("serial.script.err", err=f"expect timeout: {expect_text!r}")
                )
                self._finish_script("serial.script.timeout")
                return
            self._script_timer.start(20)
            return

        if self._script_index >= len(self._script_cmds):
            self._finish_script("serial.script.done")
            return

        cmd = self._script_cmds[self._script_index]
        self._script_index += 1
        try:
            if cmd.op == "send":
                if not self._send_payload(cmd.text, record_history=True):
                    self._finish_script("serial.script.err_send")
                    return
            elif cmd.op == "send_hex":
                if not self._send_payload(cmd.text, record_history=True, force_hex=True):
                    self._finish_script("serial.script.err_send")
                    return
            elif cmd.op == "log":
                self.traffic.append_status(cmd.text)
            elif cmd.op == "wait":
                self._script_timer.start(max(0, int(cmd.value)))
                return
            elif cmd.op == "expect":
                self._script_deadline = time.monotonic() + max(1, int(cmd.value)) / 1000.0
                self._script_expect = cmd.text
                self._script_timer.start(20)
                return
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.script.err", err=str(exc)))
            self._finish_script("serial.script.failed")
            return
        self._script_timer.start(0)

    def _terminal_write(self, text: str) -> None:
        """Render serial stream without adding a newline per read chunk."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.terminal_view.append_text(text)

    def _terminal_send(self, data: bytes) -> None:
        if not self._opened:
            return
        try:
            self._link.write(data)
            self.traffic.append_tx(data)
            if self.local_echo.isChecked():
                self._terminal_write(decode_payload(data, self._encoding_name()))
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))

    def _send_break(self) -> None:
        try:
            self._link.send_break()
            self.traffic.append_status(tr("serial.terminal.break_sent"))
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
