"""Serial port debug assistant page (pyserial + hotplug)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.core.serial_link import SerialLink, list_serial_ports
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.traffic_view import TrafficView, parse_hex_input

_BAUDS = [
    "1200",
    "2400",
    "4800",
    "9600",
    "19200",
    "38400",
    "57600",
    "115200",
    "230400",
    "460800",
    "921600",
]

_ENDINGS = {
    "none": b"",
    "lf": b"\n",
    "cr": b"\r",
    "crlf": b"\r\n",
}

_HISTORY_MAX = 30
_PRESET_COUNT = 5


class _RxRelay(QObject):
    received = Signal(bytes)
    failed = Signal(str)


class _PortCombo(QComboBox):
    """Refresh port list just before the popup opens."""

    about_to_show = Signal()

    def showPopup(self) -> None:  # noqa: N802
        self.about_to_show.emit()
        super().showPopup()


class _SerialTerminal(QPlainTextEdit):
    """Raw serial console which forwards terminal key sequences immediately."""

    send_bytes = Signal(bytes)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("logView")
        self.setUndoRedoEnabled(False)
        self.setPlaceholderText(tr("serial.terminal.placeholder"))
        self.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import Qt

        key = event.key()
        special = {
            Qt.Key.Key_Return: b"\r", Qt.Key.Key_Enter: b"\r",
            Qt.Key.Key_Backspace: b"\x7f", Qt.Key.Key_Tab: b"\t",
            Qt.Key.Key_Escape: b"\x1b", Qt.Key.Key_Up: b"\x1b[A",
            Qt.Key.Key_Down: b"\x1b[B", Qt.Key.Key_Right: b"\x1b[C",
            Qt.Key.Key_Left: b"\x1b[D", Qt.Key.Key_Home: b"\x1b[H",
            Qt.Key.Key_End: b"\x1b[F", Qt.Key.Key_Delete: b"\x1b[3~",
        }
        if key in special:
            data = special[key]
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            char = event.text().upper()
            if len(char) == 1 and 1 <= ord(char) <= 26:
                data = bytes([ord(char)])
            else:
                data = bytes([ord(char) - 64]) if len(char) == 1 and "@" <= char <= "_" else b""
        else:
            data = event.text().encode("utf-8", errors="replace")
        if data:
            self.send_bytes.emit(data)
            event.accept()
            return
        super().keyPressEvent(event)


class SerialPage(ToolPage):
    tool_id = "serial"
    tool_title_key = "tool.serial"

    def _build(self) -> None:
        self._link = SerialLink()
        self._relay = _RxRelay(self)
        self._relay.received.connect(self._on_rx)
        self._relay.failed.connect(self._on_link_error)
        self._link.set_handlers(
            on_rx=self._relay.received.emit,
            on_error=self._relay.failed.emit,
        )
        self._opened = False
        self._known_ports: tuple[str, ...] = ()
        self._history: list[str] = []
        self._history_idx = -1

        self.ctx_params = self.ctx_group(tr("serial.params"))
        self.port_combo = _PortCombo()
        self.port_combo.setFixedHeight(28)
        self.port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lbl_port = self.form_row(tr("serial.port"), self.port_combo)

        self.baud = QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(_BAUDS)
        self.baud.setCurrentText("115200")
        self.baud.setFixedHeight(28)
        self.lbl_baud = self.form_row(tr("serial.baud"), self.baud)

        self.data = QComboBox()
        self.data.addItems(["8", "7", "6", "5"])
        self.data.setFixedHeight(28)
        self.lbl_data = self.form_row(tr("serial.databits"), self.data)

        self.parity = QComboBox()
        self.parity.addItems(["N", "E", "O"])
        self.parity.setFixedHeight(28)
        self.lbl_parity = self.form_row(tr("serial.parity"), self.parity)

        self.stop = QComboBox()
        self.stop.addItems(["1", "2"])
        self.stop.setFixedHeight(28)
        self.lbl_stop = self.form_row(tr("serial.stopbits"), self.stop)

        self.dtr = QCheckBox(tr("serial.dtr"))
        self.rts = QCheckBox(tr("serial.rts"))
        self.dtr.setChecked(True)
        self.rts.setChecked(True)
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addWidget(self.dtr)
        ctrl.addWidget(self.rts)
        ctrl.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(ctrl)
        self.lbl_ctrl = self.form_row(tr("serial.flow"), wrap)

        self.flow = QComboBox()
        self.flow.addItem(tr("serial.flow.none"), "none")
        self.flow.addItem(tr("serial.flow.software"), "software")
        self.flow.addItem(tr("serial.flow.hardware"), "hardware")
        self.flow.setFixedHeight(28)
        self.lbl_flow = self.form_row(tr("serial.flow_mode"), self.flow)

        self.open_btn = QPushButton()
        self.open_btn.setObjectName("accent")
        self.open_btn.setFixedHeight(32)
        self.ctx_action(self.open_btn)

        self.work_tabs = QTabWidget()
        self.main_layout.addWidget(self.work_tabs, 1)
        mon_box = QGroupBox(tr("serial.monitor"))
        mon_box.setObjectName("mainGroup")
        mon_box.setLayout(QVBoxLayout())
        mon_box.layout().setContentsMargins(8, 10, 8, 8)
        mon_box.layout().setSpacing(6)
        self.mon_box = mon_box
        mon_lay = mon_box.layout()
        self.traffic = TrafficView()
        self.view = self.traffic.view  # compatibility alias

        send_row = QHBoxLayout()
        send_row.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("serial.mode.ascii"), "ascii")
        self.mode_combo.addItem(tr("serial.mode.hex"), "hex")
        self.mode_combo.setFixedHeight(28)
        self.mode_combo.setFixedWidth(88)
        self.lbl_mode = QLabel(tr("serial.send_mode"))
        self.rx_mode = QComboBox()
        self.rx_mode.addItem(tr("serial.mode.ascii"), "ascii")
        self.rx_mode.addItem(tr("serial.mode.hex"), "hex")
        self.rx_mode.setFixedHeight(28)
        self.rx_mode.setFixedWidth(88)
        self.lbl_rx_mode = QLabel(tr("serial.receive_mode"))
        self.ending = QComboBox()
        self.ending.addItem(tr("serial.ending.crlf"), "crlf")
        self.ending.addItem(tr("serial.ending.lf"), "lf")
        self.ending.addItem(tr("serial.ending.cr"), "cr")
        self.ending.addItem(tr("serial.ending.none"), "none")
        self.ending.setFixedHeight(28)
        self.ending.setFixedWidth(88)
        self.lbl_ending = QLabel(tr("serial.ending"))
        self.history_btn = QPushButton(tr("serial.history"))
        self.history_btn.setObjectName("ghost")
        self.history_btn.setFixedHeight(28)
        self.send_edit = QLineEdit()
        self.send_edit.setFixedHeight(30)
        self.send_edit.setPlaceholderText(tr("serial.send_ph"))
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("ghost")
        self.send_btn.setEnabled(False)

        # Quick-send presets: editable command slots + optional cycle membership.
        self.preset_box = QGroupBox(tr("serial.presets"))
        self.preset_box.setObjectName("mainGroup")
        preset_lay = QVBoxLayout(self.preset_box)
        preset_lay.setContentsMargins(8, 10, 8, 8)
        preset_lay.setSpacing(4)
        self._preset_checks: list[QCheckBox] = []
        self._preset_edits: list[QLineEdit] = []
        self._preset_btns: list[QPushButton] = []
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
            edit.editingFinished.connect(self._persist_prefs)
            check.toggled.connect(lambda _c: self._persist_prefs())

        cyclic_row = QHBoxLayout()
        cyclic_row.setSpacing(8)
        self.cyclic_check = QCheckBox(tr("serial.cyclic"))
        self.lbl_interval = QLabel(tr("serial.cyclic_interval"))
        self.cyclic_interval = QSpinBox()
        self.cyclic_interval.setRange(1, 600_000)
        self.cyclic_interval.setSingleStep(10)
        self.cyclic_interval.setValue(1000)
        self.cyclic_interval.setSuffix(" ms")
        self.cyclic_interval.setFixedHeight(28)
        self.cyclic_interval.setFixedWidth(100)
        cyclic_row.addWidget(self.cyclic_check)
        cyclic_row.addWidget(self.lbl_interval)
        cyclic_row.addWidget(self.cyclic_interval)
        cyclic_row.addStretch(1)
        preset_lay.addLayout(cyclic_row)
        self._cyclic_timer = QTimer(self)
        self._cyclic_timer.timeout.connect(self._on_cyclic_tick)
        self._cyclic_index = 0

        top_meta = QHBoxLayout()
        top_meta.setSpacing(8)
        top_meta.addWidget(self.lbl_mode)
        top_meta.addWidget(self.mode_combo)
        top_meta.addWidget(self.lbl_rx_mode)
        top_meta.addWidget(self.rx_mode)
        top_meta.addWidget(self.lbl_ending)
        top_meta.addWidget(self.ending)
        top_meta.addWidget(self.history_btn)
        top_meta.addStretch(1)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.send_btn)
        meta_wrap = QVBoxLayout()
        meta_wrap.setSpacing(4)
        meta_wrap.addLayout(top_meta)
        meta_wrap.addLayout(send_row)
        mon_lay.addWidget(self.traffic, 1)
        mon_lay.addWidget(self.preset_box, 0)
        mon_lay.addLayout(meta_wrap)
        self.work_tabs.addTab(mon_box, tr("serial.monitor"))

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
        self.terminal_view = _SerialTerminal()
        self.terminal_view.document().setMaximumBlockCount(10000)
        terminal_lay.addLayout(terminal_bar)
        terminal_lay.addWidget(self.terminal_view, 1)
        self.work_tabs.addTab(self.terminal_box, tr("serial.terminal"))

        self.open_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.send_edit.returnPressed.connect(self._on_send)
        self.send_edit.installEventFilter(self)
        self.history_btn.clicked.connect(self._show_history)
        self.terminal_view.send_bytes.connect(self._terminal_send)
        self.terminal_break.clicked.connect(self._send_break)
        self.terminal_clear.clicked.connect(self.terminal_view.clear)
        self.port_combo.about_to_show.connect(self._refresh_ports)
        self.cyclic_check.toggled.connect(self._on_cyclic_toggled)
        self.cyclic_interval.valueChanged.connect(self._on_interval_changed)

        self._hotplug = QTimer(self)
        self._hotplug.setInterval(2000)
        self._hotplug.timeout.connect(self._hotplug_tick)
        self._hotplug.start()

        self.retranslate()
        self._refresh_ports()
        self._load_prefs()
        for combo in (
            self.baud, self.data, self.parity, self.stop, self.flow,
            self.ending, self.mode_combo,
        ):
            combo.currentIndexChanged.connect(lambda _i: self._persist_prefs())
        self.rx_mode.currentIndexChanged.connect(self._on_rx_mode_changed)
        self.rx_mode.currentIndexChanged.connect(lambda _i: self._persist_prefs())
        self.baud.currentTextChanged.connect(lambda _t: self._persist_prefs())
        self.port_combo.currentIndexChanged.connect(lambda _i: self._persist_prefs())
        self.dtr.toggled.connect(lambda _c: self._apply_modem())
        self.rts.toggled.connect(lambda _c: self._apply_modem())

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent, Qt

        if obj is self.send_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._browse_history(event.key() == Qt.Key.Key_Up)
                return True
        return super().eventFilter(obj, event)

    def _browse_history(self, up: bool) -> None:
        if not self._history:
            return
        if up:
            self._history_idx = min(self._history_idx + 1, len(self._history) - 1)
        else:
            self._history_idx = max(self._history_idx - 1, -1)
        if self._history_idx < 0:
            self.send_edit.clear()
        else:
            self.send_edit.setText(self._history[-(self._history_idx + 1)])

    def _show_history(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        if not self._history:
            menu.addAction("—")
        else:
            for item in reversed(self._history[-_HISTORY_MAX:]):
                menu.addAction(item, lambda t=item: self.send_edit.setText(t))
        menu.exec(self.history_btn.mapToGlobal(self.history_btn.rect().bottomLeft()))

    def retranslate(self) -> None:
        self.ctx_params.setTitle(tr("serial.params"))
        self.lbl_port.setText(tr("serial.port"))
        self.lbl_baud.setText(tr("serial.baud"))
        self.lbl_data.setText(tr("serial.databits"))
        self.lbl_parity.setText(tr("serial.parity"))
        self.lbl_stop.setText(tr("serial.stopbits"))
        self.lbl_ctrl.setText(tr("serial.flow"))
        self.lbl_flow.setText(tr("serial.flow_mode"))
        self.flow.setItemText(0, tr("serial.flow.none"))
        self.flow.setItemText(1, tr("serial.flow.software"))
        self.flow.setItemText(2, tr("serial.flow.hardware"))
        self.dtr.setText(tr("serial.dtr"))
        self.rts.setText(tr("serial.rts"))
        self.open_btn.setText(tr("serial.close") if self._opened else tr("serial.open"))
        self.mon_box.setTitle(tr("serial.monitor"))
        self.work_tabs.setTabText(0, tr("serial.monitor"))
        self.work_tabs.setTabText(1, tr("serial.terminal"))
        self.local_echo.setText(tr("serial.terminal.local_echo"))
        self.terminal_break.setText(tr("serial.terminal.break"))
        self.terminal_clear.setText(tr("mon.clear"))
        self.traffic.retranslate()
        self.traffic.set_placeholder(tr("serial.placeholder"))
        self.send_edit.setPlaceholderText(tr("serial.send_ph"))
        self.send_btn.setText(tr("serial.send"))
        self.lbl_mode.setText(tr("serial.send_mode"))
        self.lbl_rx_mode.setText(tr("serial.receive_mode"))
        self.mode_combo.setItemText(0, tr("serial.mode.ascii"))
        self.mode_combo.setItemText(1, tr("serial.mode.hex"))
        self.lbl_ending.setText(tr("serial.ending"))
        self.ending.setItemText(0, tr("serial.ending.crlf"))
        self.ending.setItemText(1, tr("serial.ending.lf"))
        self.ending.setItemText(2, tr("serial.ending.cr"))
        self.ending.setItemText(3, tr("serial.ending.none"))
        self.history_btn.setText(tr("serial.history"))
        self.preset_box.setTitle(tr("serial.presets"))
        for i, edit in enumerate(self._preset_edits):
            edit.setPlaceholderText(tr("serial.presets_ph", n=i + 1))
        for check in self._preset_checks:
            check.setToolTip(tr("serial.cycle_pick"))
        for btn in self._preset_btns:
            btn.setText(tr("serial.send"))
        self.cyclic_check.setText(tr("serial.cyclic"))
        self.lbl_interval.setText(tr("serial.cyclic_interval"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("toggle", "serial.open", "connect", self.toggle_connection),
            ToolActionSpec("send", "serial.send", "program", self.send),
            ToolActionSpec("clear", "mon.clear", "clear", self.clear_view, separator_before=True),
        ]

    def toggle_connection(self) -> None:
        self._on_toggle()

    def send(self) -> None:
        self._on_send()

    def clear_view(self) -> None:
        self.traffic.clear()

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        if prefs.get("baud"):
            self.baud.setCurrentText(str(prefs["baud"]))
        if prefs.get("databits"):
            self.data.setCurrentText(str(prefs["databits"]))
        if prefs.get("parity"):
            self.parity.setCurrentText(str(prefs["parity"]))
        if prefs.get("stopbits"):
            self.stop.setCurrentText(str(prefs["stopbits"]))
        if prefs.get("flow"):
            idx = self.flow.findData(str(prefs["flow"]))
            if idx >= 0:
                self.flow.setCurrentIndex(idx)
        if prefs.get("ending"):
            idx = self.ending.findData(str(prefs["ending"]))
            if idx >= 0:
                self.ending.setCurrentIndex(idx)
        if prefs.get("send_mode"):
            idx = self.mode_combo.findData(str(prefs["send_mode"]))
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        if prefs.get("receive_mode"):
            idx = self.rx_mode.findData(str(prefs["receive_mode"]))
            if idx >= 0:
                self.rx_mode.setCurrentIndex(idx)
        if prefs.get("dtr") is not None:
            self.dtr.setChecked(bool(prefs["dtr"]))
        if prefs.get("rts") is not None:
            self.rts.setChecked(bool(prefs["rts"]))
        port = prefs.get("port")
        if port:
            idx = self.port_combo.findData(port)
            if idx < 0:
                idx = self.port_combo.findText(str(port))
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        presets = prefs.get("presets")
        if isinstance(presets, list):
            for i, edit in enumerate(self._preset_edits):
                if i < len(presets) and isinstance(presets[i], str):
                    edit.setText(presets[i])
        cycle = prefs.get("preset_cycle")
        if isinstance(cycle, list):
            for i, check in enumerate(self._preset_checks):
                if i < len(cycle):
                    check.setChecked(bool(cycle[i]))
        if prefs.get("cyclic_interval"):
            try:
                self.cyclic_interval.setValue(int(prefs["cyclic_interval"]))
            except (TypeError, ValueError):
                pass

    def _persist_prefs(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "port": self._selected_port(),
                "baud": self.baud.currentText(),
                "databits": self.data.currentText(),
                "parity": self.parity.currentText(),
                "stopbits": self.stop.currentText(),
                "flow": self.flow.currentData(),
                "ending": self.ending.currentData(),
                "send_mode": self.mode_combo.currentData(),
                "receive_mode": self.rx_mode.currentData(),
                "dtr": self.dtr.isChecked(),
                "rts": self.rts.isChecked(),
                "presets": [e.text() for e in self._preset_edits],
                "preset_cycle": [c.isChecked() for c in self._preset_checks],
                "cyclic_interval": int(self.cyclic_interval.value()),
            },
        )

    def _hotplug_tick(self) -> None:
        devices = tuple(d for d, _ in list_serial_ports())
        if devices != self._known_ports:
            vanished = self._opened and self._selected_port() not in devices
            self._known_ports = devices
            self._refresh_ports()
            if vanished:
                self._on_toggle()
                self.traffic.append_status(tr("serial.port_lost"))

    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self._known_ports = tuple(d for d, _ in ports)
        current_data = self.port_combo.currentData()
        current_text = self.port_combo.currentText()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        if not ports:
            self.port_combo.addItem("—")
        else:
            for device, label in ports:
                self.port_combo.addItem(label, device)
        if current_data:
            idx = self.port_combo.findData(current_data)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        elif current_text:
            idx = self.port_combo.findText(current_text)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        self.port_combo.blockSignals(False)

    def _selected_port(self) -> str:
        data = self.port_combo.currentData()
        return str(data or "").strip()

    def _repaint_btn(self) -> None:
        self.open_btn.setObjectName("danger" if self._opened else "accent")
        st = self.open_btn.style()
        st.unpolish(self.open_btn)
        st.polish(self.open_btn)

    def _apply_modem(self) -> None:
        if not self._opened:
            return
        try:
            self._link.set_dtr(self.dtr.isChecked())
            self._link.set_rts(self.rts.isChecked())
        except Exception:
            pass

    def _set_send_enabled(self, enabled: bool) -> None:
        self.send_btn.setEnabled(enabled)
        self.terminal_break.setEnabled(enabled)
        for btn in self._preset_btns:
            btn.setEnabled(enabled)

    def _on_toggle(self) -> None:
        if self._opened:
            self._stop_cyclic()
            self._link.close()
            self._opened = False
            self._set_send_enabled(False)
            self.open_btn.setText(tr("serial.open"))
            self._repaint_btn()
            self.traffic.append_status(tr("serial.closed"))
            return
        port = self._selected_port()
        if not port:
            self.traffic.append_status(tr("serial.open_no_port"))
            return
        try:
            self._link.open(
                port=port,
                baudrate=int(self.baud.currentText() or 115200),
                bytesize=int(self.data.currentText() or 8),
                parity=self.parity.currentText() or "N",
                stopbits=float(self.stop.currentText() or 1),
                flow_control=str(self.flow.currentData() or "none"),
            )
            self._link.set_dtr(self.dtr.isChecked())
            self._link.set_rts(self.rts.isChecked())
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            return
        self._opened = True
        self._set_send_enabled(True)
        self.open_btn.setText(tr("serial.close"))
        self._repaint_btn()
        self.traffic.append_status(tr("serial.opened", port=port))

    def _encode_payload(self, text: str) -> bytes | None:
        ending = _ENDINGS.get(str(self.ending.currentData() or "crlf"), b"\r\n")
        try:
            if self.mode_combo.currentData() == "hex":
                return parse_hex_input(text) + ending
            return text.encode("utf-8") + ending
        except ValueError:
            self.traffic.append_status(tr("serial.err", err="bad hex"))
            return None

    def _send_payload(self, text: str, *, record_history: bool = False) -> bool:
        if not text or not self._opened:
            return False
        data = self._encode_payload(text)
        if data is None:
            return False
        try:
            self._link.write(data)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            return False
        self.traffic.append_tx(data)
        if record_history:
            if text not in self._history:
                self._history.append(text)
                del self._history[:-_HISTORY_MAX]
            self._history_idx = -1
        return True

    def _on_send(self) -> None:
        text = self.send_edit.text()
        if not text:
            return
        if self._send_payload(text, record_history=True):
            self.send_edit.clear()

    def _on_preset_send(self, index: int) -> None:
        if not (0 <= index < len(self._preset_edits)):
            return
        text = self._preset_edits[index].text().strip()
        if not text:
            return
        self._send_payload(text, record_history=True)

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
        self._persist_prefs()

    def _on_interval_changed(self, value: int) -> None:
        if self._cyclic_timer.isActive():
            self._cyclic_timer.setInterval(max(1, int(value)))
        self._persist_prefs()

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

    def _on_rx(self, data: bytes) -> None:
        self.traffic.append_rx(data)
        self._terminal_write(data.decode("utf-8", errors="replace"))

    def _terminal_write(self, text: str) -> None:
        """Render serial stream without adding a newline per read chunk."""
        from PySide6.QtGui import QTextCursor

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        cursor = self.terminal_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.terminal_view.setTextCursor(cursor)
        self.terminal_view.ensureCursorVisible()

    def _terminal_send(self, data: bytes) -> None:
        if not self._opened:
            return
        try:
            self._link.write(data)
            self.traffic.append_tx(data)
            if self.local_echo.isChecked():
                self._terminal_write(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))

    def _send_break(self) -> None:
        try:
            self._link.send_break()
            self.traffic.append_status(tr("serial.terminal.break_sent"))
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))

    def _on_rx_mode_changed(self, _index: int = 0) -> None:
        self.traffic.set_display_mode(str(self.rx_mode.currentData() or "ascii"))

    def _on_link_error(self, message: str) -> None:
        self.traffic.append_status(tr("serial.err", err=message))
        self._opened = False
        self._stop_cyclic()
        self._set_send_enabled(False)
        self.open_btn.setText(tr("serial.open"))
        self._repaint_btn()

    def shutdown(self) -> None:
        self._hotplug.stop()
        self._cyclic_timer.stop()
        self._persist_prefs()
        self._link.close()
