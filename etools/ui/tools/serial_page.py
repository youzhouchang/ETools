"""Serial port debug assistant page (pyserial + hotplug)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
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


class _RxRelay(QObject):
    received = Signal(bytes)
    failed = Signal(str)


class _PortCombo(QComboBox):
    """Refresh port list just before the popup opens."""

    about_to_show = Signal()

    def showPopup(self) -> None:  # noqa: N802
        self.about_to_show.emit()
        super().showPopup()


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

        self.open_btn = QPushButton()
        self.open_btn.setObjectName("accent")
        self.open_btn.setFixedHeight(32)
        self.ctx_action(self.open_btn)

        mon_box = self.main_group(tr("serial.monitor"))
        self.mon_box = mon_box
        mon_lay = mon_box.layout()
        self.traffic = TrafficView()
        self.view = self.traffic.view  # compatibility alias
        mon_lay.addWidget(self.traffic, 1)

        send_row = QHBoxLayout()
        send_row.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("serial.mode.ascii"), "ascii")
        self.mode_combo.addItem(tr("serial.mode.hex"), "hex")
        self.mode_combo.setFixedHeight(28)
        self.mode_combo.setFixedWidth(88)
        self.lbl_mode = QLabel(tr("serial.send_mode"))
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

        top_meta = QHBoxLayout()
        top_meta.setSpacing(8)
        top_meta.addWidget(self.lbl_mode)
        top_meta.addWidget(self.mode_combo)
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
        mon_lay.addLayout(meta_wrap)

        self.open_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.send_edit.returnPressed.connect(self._on_send)
        self.send_edit.installEventFilter(self)
        self.history_btn.clicked.connect(self._show_history)
        self.port_combo.about_to_show.connect(self._refresh_ports)

        self._hotplug = QTimer(self)
        self._hotplug.setInterval(2000)
        self._hotplug.timeout.connect(self._hotplug_tick)
        self._hotplug.start()

        self.retranslate()
        self._refresh_ports()
        self._load_prefs()
        for combo in (self.baud, self.data, self.parity, self.stop, self.ending, self.mode_combo):
            combo.currentIndexChanged.connect(lambda _i: self._persist_prefs())
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
        self.dtr.setText(tr("serial.dtr"))
        self.rts.setText(tr("serial.rts"))
        self.open_btn.setText(tr("serial.close") if self._opened else tr("serial.open"))
        self.mon_box.setTitle(tr("serial.monitor"))
        self.traffic.retranslate()
        self.traffic.set_placeholder(tr("serial.placeholder"))
        self.send_edit.setPlaceholderText(tr("serial.send_ph"))
        self.send_btn.setText(tr("serial.send"))
        self.lbl_mode.setText(tr("serial.send_mode"))
        self.mode_combo.setItemText(0, tr("serial.mode.ascii"))
        self.mode_combo.setItemText(1, tr("serial.mode.hex"))
        self.lbl_ending.setText(tr("serial.ending"))
        self.ending.setItemText(0, tr("serial.ending.crlf"))
        self.ending.setItemText(1, tr("serial.ending.lf"))
        self.ending.setItemText(2, tr("serial.ending.cr"))
        self.ending.setItemText(3, tr("serial.ending.none"))
        self.history_btn.setText(tr("serial.history"))

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
        if prefs.get("ending"):
            idx = self.ending.findData(str(prefs["ending"]))
            if idx >= 0:
                self.ending.setCurrentIndex(idx)
        if prefs.get("send_mode"):
            idx = self.mode_combo.findData(str(prefs["send_mode"]))
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
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

    def _persist_prefs(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "port": self._selected_port(),
                "baud": self.baud.currentText(),
                "databits": self.data.currentText(),
                "parity": self.parity.currentText(),
                "stopbits": self.stop.currentText(),
                "ending": self.ending.currentData(),
                "send_mode": self.mode_combo.currentData(),
                "dtr": self.dtr.isChecked(),
                "rts": self.rts.isChecked(),
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

    def _on_toggle(self) -> None:
        if self._opened:
            self._link.close()
            self._opened = False
            self.send_btn.setEnabled(False)
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
            )
            self._link.set_dtr(self.dtr.isChecked())
            self._link.set_rts(self.rts.isChecked())
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            return
        self._opened = True
        self.send_btn.setEnabled(True)
        self.open_btn.setText(tr("serial.close"))
        self._repaint_btn()
        self.traffic.append_status(tr("serial.opened", port=port))

    def _on_send(self) -> None:
        text = self.send_edit.text()
        if not text:
            return
        ending = _ENDINGS.get(str(self.ending.currentData() or "crlf"), b"\r\n")
        try:
            if self.mode_combo.currentData() == "hex":
                data = parse_hex_input(text) + ending
            else:
                data = text.encode("utf-8") + ending
        except ValueError:
            self.traffic.append_status(tr("serial.err", err="bad hex"))
            return
        try:
            self._link.write(data)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            return
        self.traffic.append_tx(data)
        if text not in self._history:
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._history_idx = -1
        self.send_edit.clear()

    def _on_rx(self, data: bytes) -> None:
        self.traffic.append_rx(data)

    def _on_link_error(self, message: str) -> None:
        self.traffic.append_status(tr("serial.err", err=message))
        self._opened = False
        self.send_btn.setEnabled(False)
        self.open_btn.setText(tr("serial.open"))
        self._repaint_btn()

    def shutdown(self) -> None:
        self._hotplug.stop()
        self._persist_prefs()
        self._link.close()
