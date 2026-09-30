"""Network debug assistant page (socket TCP/UDP)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from etools.core.net_addr import local_ipv4, suggest_remote_ipv4
from etools.core.net_link import NetLink
from etools.i18n import tr
from etools.ui.runtime import OpRunner
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.ip_edit import IPv4Edit
from etools.ui.widgets.traffic_view import ENCODINGS, TrafficView, parse_hex_input

_ENDINGS = {
    "none": b"",
    "lf": b"\n",
    "cr": b"\r",
    "crlf": b"\r\n",
}

# 0 = TCP Client, 1 = TCP Server, 2 = UDP
_PROTO_CLIENT = 0
_PROTO_SERVER = 1
_PROTO_UDP = 2

_PRESET_COUNT = 6
_HISTORY_MAX = 30


def _local_ipv4() -> str:
    return local_ipv4()


class _RxRelay(QObject):
    received = Signal(bytes, str)
    failed = Signal(str)
    peer = Signal(str, str)  # kind, peer


class EthernetPage(ToolPage):
    tool_id = "ethernet"
    tool_title_key = "tool.ethernet"

    def _build(self) -> None:
        self._link = NetLink()
        self._runner = OpRunner(self)
        self._connect_cancel = threading.Event()
        self._relay = _RxRelay(self)
        self._relay.received.connect(self._on_rx)
        self._relay.failed.connect(self._on_error)
        self._relay.peer.connect(self._on_peer)
        self._link.set_handlers(
            on_rx=self._relay.received.emit,
            on_error=self._relay.failed.emit,
            on_peer=self._relay.peer.emit,
        )
        self._opened = False
        self._peer_connected = False
        self._history: list[str] = []
        self._history_idx = -1

        self.ctx_conn = self.ctx_group(tr("net.title"))

        self.proto = QComboBox()
        self.proto.addItems(["TCP Client", "TCP Server", "UDP"])
        self.proto.setFixedHeight(28)
        self.lbl_proto = self.form_row(tr("net.proto"), self.proto)

        self.host = IPv4Edit(suggest_remote_ipv4())
        self.lbl_host = self.form_row(tr("net.remote_host"), self.host)

        self.port = QLineEdit("8080")
        self.port.setFixedHeight(28)
        self.lbl_port = self.form_row(tr("net.remote_port"), self.port)

        self.local_port = QLineEdit("8080")
        self.local_port.setFixedHeight(28)
        self.lbl_local_port = self.form_row(tr("net.local_port"), self.local_port)

        self.peer_combo = QComboBox()
        self.peer_combo.setFixedHeight(28)
        self.peer_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lbl_peer = self.form_row(tr("net.peer"), self.peer_combo)

        self.conn_btn = QPushButton()
        self.conn_btn.setObjectName("accent")
        self.conn_btn.setFixedHeight(32)
        self.ctx_action(self.conn_btn)

        sess_box = self.main_group(tr("net.session"))
        self.sess_box = sess_box
        sess_lay = sess_box.layout()
        self.traffic = TrafficView()
        self.view = self.traffic.view
        sess_lay.addWidget(self.traffic, 1)

        send_row = QHBoxLayout()
        send_row.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("net.mode.ascii"), "ascii")
        self.mode_combo.addItem(tr("net.mode.hex"), "hex")
        self.mode_combo.setFixedHeight(28)
        self.mode_combo.setFixedWidth(88)
        self.lbl_mode = QLabel(tr("serial.send_mode"))
        self.rx_mode = QComboBox()
        self.rx_mode.addItem(tr("net.mode.ascii"), "ascii")
        self.rx_mode.addItem(tr("net.mode.hex"), "hex")
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
        self.lbl_ending = QLabel(tr("net.ending"))
        self.encoding = QComboBox()
        for value, label in ENCODINGS:
            self.encoding.addItem(label, value)
        self.encoding.setFixedHeight(28)
        self.encoding.setFixedWidth(88)
        self.lbl_encoding = QLabel(tr("mon.encoding"))
        self.send_edit = QLineEdit()
        self.send_edit.setFixedHeight(30)
        self.send_edit.setPlaceholderText(tr("net.send_ph"))
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("ghost")
        self.send_btn.setEnabled(False)
        self.history_btn = QPushButton(tr("serial.history"))
        self.history_btn.setObjectName("ghost")
        self.history_btn.setFixedHeight(28)
        send_options = QGridLayout()
        send_options.setHorizontalSpacing(10)
        send_options.setVerticalSpacing(8)
        pairs = (
            (self.lbl_mode, self.mode_combo),
            (self.lbl_rx_mode, self.rx_mode),
            (self.lbl_ending, self.ending),
            (self.lbl_encoding, self.encoding),
        )
        for index, (lbl, field) in enumerate(pairs):
            r, c = divmod(index, 2)
            send_options.addWidget(lbl, r, c * 2)
            send_options.addWidget(field, r, c * 2 + 1)
        send_options.setColumnStretch(3, 1)
        self.send_btn.setFixedHeight(30)
        send_row.setSpacing(8)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.history_btn)
        send_row.addWidget(self.send_btn)

        preset_box = QGroupBox(tr("serial.presets"))
        preset_box.setObjectName("mainGroup")
        preset_box.setCheckable(True)
        preset_box.setChecked(False)
        preset_outer = QVBoxLayout(preset_box)
        preset_content = QWidget()
        preset_outer.addWidget(preset_content)
        preset_content.setVisible(False)
        preset_box.toggled.connect(preset_content.setVisible)
        preset_lay = QVBoxLayout(preset_content)
        preset_lay.setContentsMargins(8, 10, 8, 8)
        preset_lay.setSpacing(4)
        self._preset_edits: list[QLineEdit] = []
        self._preset_btns: list[QPushButton] = []
        for i in range(_PRESET_COUNT):
            row = QHBoxLayout()
            row.setSpacing(6)
            edit = QLineEdit()
            edit.setFixedHeight(28)
            edit.setPlaceholderText(tr("serial.presets_ph", n=i + 1))
            btn = QPushButton(tr("net.send"))
            btn.setObjectName("ghost")
            btn.setFixedHeight(28)
            btn.setFixedWidth(56)
            btn.setEnabled(False)
            row.addWidget(edit, 1)
            row.addWidget(btn)
            preset_lay.addLayout(row)
            self._preset_edits.append(edit)
            self._preset_btns.append(btn)
            btn.clicked.connect(lambda _c=False, idx=i: self._on_preset_send(idx))
            edit.editingFinished.connect(self.persist_prefs)
        sess_lay.addWidget(preset_box, 0)
        sess_lay.addLayout(send_options)
        sess_lay.addLayout(send_row)
        self.install_send_preview(sess_lay)

        self.conn_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.send_edit.returnPressed.connect(self._on_send)
        self.history_btn.clicked.connect(self._show_history)
        self.send_edit.installEventFilter(self)
        self.proto.currentIndexChanged.connect(self._on_proto_changed)
        self.retranslate()
        self._load_prefs()
        self._on_proto_changed()
        self.proto.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.port.editingFinished.connect(self.persist_prefs)
        self.local_port.editingFinished.connect(self.persist_prefs)
        self.host.editingFinished.connect(self.persist_prefs)
        self.ending.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.mode_combo.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.encoding.currentIndexChanged.connect(self._on_encoding_changed)
        self.rx_mode.currentIndexChanged.connect(self._on_rx_mode_changed)
        self.rx_mode.currentIndexChanged.connect(lambda _i: self.persist_prefs())

    def _on_proto_changed(self) -> None:
        mode = self.proto.currentIndex()
        is_server = mode == _PROTO_SERVER
        is_udp = mode == _PROTO_UDP
        # Save the host that belonged to the *previous* mode, then restore the new one.
        prev = getattr(self, "_last_mode", self._mode_key())
        prev_host = self.host.text().strip()
        if prev_host:
            by_mode = self._host_by_mode()
            by_mode[prev] = prev_host
            save_tool_prefs(self.tool_id, {"host_by_mode": by_mode})
        self._last_mode = self._mode_key()
        self.lbl_host.setText(tr("net.host") if is_server else tr("net.remote_host"))
        self.lbl_port.setText(tr("net.port") if is_server else tr("net.remote_port"))
        self.local_port.setVisible(is_udp)
        self.lbl_local_port.setVisible(is_udp)
        self.peer_combo.setVisible(is_server)
        self.lbl_peer.setVisible(is_server)
        self._restore_host_for_mode()
        if is_server:
            self.conn_btn.setText(tr("net.listen"))
        elif is_udp:
            self.lbl_host.setText(tr("net.remote_host"))
            self.lbl_port.setText(tr("net.remote_port"))
            self.conn_btn.setText(tr("net.connect"))
        else:
            self.conn_btn.setText(tr("net.connect"))
        if not self._opened:
            self.conn_btn.setText(tr("net.listen") if is_server else tr("net.connect"))
        self._refresh_peers()

    def retranslate(self) -> None:
        self.ctx_conn.setTitle(tr("net.title"))
        self.lbl_proto.setText(tr("net.proto"))
        mode = self.proto.currentIndex()
        self.lbl_host.setText(tr("net.host") if mode == _PROTO_SERVER else tr("net.remote_host"))
        self.lbl_port.setText(tr("net.port") if mode == _PROTO_SERVER else tr("net.remote_port"))
        self.lbl_local_port.setText(tr("net.local_port"))
        self.lbl_peer.setText(tr("net.peer"))
        self.history_btn.setText(tr("serial.history"))
        for i, edit in enumerate(self._preset_edits):
            edit.setPlaceholderText(tr("serial.presets_ph", n=i + 1))
        for btn in self._preset_btns:
            btn.setText(tr("net.send"))
        if self._opened:
            self.conn_btn.setText(tr("net.disconnect"))
        else:
            self.conn_btn.setText(tr("net.listen") if mode == _PROTO_SERVER else tr("net.connect"))
        self.sess_box.setTitle(tr("net.session"))
        self.traffic.retranslate()
        self.traffic.set_placeholder(tr("net.placeholder"))
        self.send_edit.setPlaceholderText(tr("net.send_ph"))
        self.send_btn.setText(tr("net.send"))
        self.lbl_mode.setText(tr("serial.send_mode"))
        self.lbl_rx_mode.setText(tr("serial.receive_mode"))
        self.mode_combo.setItemText(0, tr("net.mode.ascii"))
        self.mode_combo.setItemText(1, tr("net.mode.hex"))
        self.lbl_ending.setText(tr("net.ending"))
        self.ending.setItemText(0, tr("serial.ending.crlf"))
        self.ending.setItemText(1, tr("serial.ending.lf"))
        self.ending.setItemText(2, tr("serial.ending.cr"))
        self.ending.setItemText(3, tr("serial.ending.none"))
        self.lbl_encoding.setText(tr("mon.encoding"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("toggle", "net.connect", "connect", self.toggle_connection),
            ToolActionSpec("send", "net.send", "program", self.send),
            ToolActionSpec("run_script", "script.run_menu", "hex", self._run_script_menu),
            ToolActionSpec("diag", "diag.title", "compare", self._open_diag),
            ToolActionSpec("modbus", "modbus.title", "hex", self._open_modbus),
            ToolActionSpec("clear", "mon.clear", "clear", self.clear_view, separator_before=True),
        ]

    def _open_diag(self) -> None:
        from etools.ui.widgets.net_diag_dialog import NetDiagDialog

        NetDiagDialog(self, host=self.host.text().strip() or "127.0.0.1").exec()

    def _open_modbus(self) -> None:
        from etools.core import modbus
        from etools.ui.widgets.modbus_dialog import ModbusDialog

        def send(frame: bytes) -> None:
            if not self._opened:
                self.traffic.append_status(tr("net.closed"))
                return
            try:
                self._link.send(frame, peer=self._selected_peer())
            except Exception as exc:  # noqa: BLE001
                self.traffic.append_status(tr("net.err", err=str(exc)))
                return
            self.traffic.append_tx(frame)

        ModbusDialog(send, self, mode=modbus.MODE_TCP).exec()

    def _run_script_menu(self) -> None:
        from etools.ui.tools.script_menu import exec_script_menu

        exec_script_menu(self)

    @property
    def is_open(self) -> bool:
        return self._opened

    def link_status(self) -> tuple[str, str]:
        if not self._opened:
            return tr("status.link_idle"), "warn"
        host = self.host.text().strip() or "0.0.0.0"
        port = self.port.text().strip() or "?"
        return tr("status.link_net", host=host, port=port), "ok"

    def toggle_connection(self) -> None:
        self._on_toggle()

    def send(self) -> None:
        self._on_send()

    def clear_view(self) -> None:
        self.traffic.clear()

    # -- Lua bridge helpers --------------------------------------------

    def lua_send_text(self, text: str) -> bool:
        from etools.ui.widgets.traffic_view import parse_hex_input

        if not self._opened:
            return False
        end_key = self.ending.currentData() or "crlf"
        end_map = {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}
        ending_bytes = end_map.get(str(end_key), b"\r\n")
        try:
            if self.mode_combo.currentData() == "hex":
                data = parse_hex_input(text) + ending_bytes
            else:
                data = text.encode(self._encoding_name()) + ending_bytes
        except ValueError:
            self.traffic.append_status(tr("net.err", err="bad hex"))
            return False
        try:
            self._link.send(data, peer=self._selected_peer())
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("net.err", err=str(exc)))
            return False
        self.traffic.append_tx(data)
        return True

    def lua_take_rx(self, max_bytes: int = 4096) -> bytes:
        buf = getattr(self, "_lua_rx", None)
        if buf is None:
            self._lua_rx = bytearray()
            buf = self._lua_rx
        n = max(0, int(max_bytes))
        data = bytes(buf[:n])
        del buf[:n]
        return data

    def _mode_key(self) -> str:
        return {0: "client", 1: "server", 2: "udp"}.get(self.proto.currentIndex(), "client")

    def _host_by_mode(self) -> dict[str, str]:
        raw = load_tool_prefs(self.tool_id).get("host_by_mode")
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items() if v}
        return {}

    def _restore_host_for_mode(self) -> None:
        """Fill host from this mode's last value, else subnet guess / 0.0.0.0."""
        mode = self._mode_key()
        saved = self._host_by_mode().get(mode) or load_tool_prefs(self.tool_id).get("host")
        if mode == "server":
            self.host.setText(str(saved or "0.0.0.0"))
            return
        self.host.setText(str(saved or suggest_remote_ipv4()))

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        if prefs.get("proto_index") is not None:
            idx = int(prefs["proto_index"])
            if 0 <= idx < self.proto.count():
                self.proto.blockSignals(True)
                self.proto.setCurrentIndex(idx)
                self.proto.blockSignals(False)
        self._last_mode = self._mode_key()
        self._restore_host_for_mode()
        if prefs.get("port"):
            self.port.setText(str(prefs["port"]))
        if prefs.get("local_port"):
            self.local_port.setText(str(prefs["local_port"]))
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
        if prefs.get("encoding"):
            idx = self.encoding.findData(str(prefs["encoding"]))
            if idx >= 0:
                self.encoding.setCurrentIndex(idx)
        self.traffic.set_encoding(self._encoding_name())
        presets = prefs.get("presets")
        if isinstance(presets, list):
            for i, edit in enumerate(self._preset_edits):
                if i < len(presets) and isinstance(presets[i], str):
                    edit.setText(presets[i])

    def persist_prefs(self) -> None:
        host = self.host.text().strip()
        by_mode = self._host_by_mode()
        if host:
            by_mode[self._mode_key()] = host
        save_tool_prefs(
            self.tool_id,
            {
                "proto_index": self.proto.currentIndex(),
                "host": host,
                "host_by_mode": by_mode,
                "port": self.port.text().strip(),
                "local_port": self.local_port.text().strip(),
                "ending": self.ending.currentData(),
                "send_mode": self.mode_combo.currentData(),
                "receive_mode": self.rx_mode.currentData(),
                "encoding": self._encoding_name(),
                "presets": [e.text() for e in self._preset_edits],
            },
        )

    def _repaint_btn(self) -> None:
        self.conn_btn.setObjectName("danger" if self._opened else "accent")
        st = self.conn_btn.style()
        st.unpolish(self.conn_btn)
        st.polish(self.conn_btn)

    def _on_toggle(self) -> None:
        if self._runner.busy:
            self._connect_cancel.set()
            self.conn_btn.setEnabled(False)
            return
        if self._opened:
            self._link.close()
            self._opened = False
            self._peer_connected = False
            self._set_send_enabled(False)
            self._refresh_peers()
            self._on_proto_changed()
            self._repaint_btn()
            self.traffic.append_status(tr("net.closed"))
            return
        host = self.host.text().strip() or "0.0.0.0"
        try:
            port = int(self.port.text().strip() or "0")
        except ValueError:
            self.traffic.append_status(tr("net.err", err="bad port"))
            return
        mode = self.proto.currentIndex()
        if not 0 <= port <= 65535 or (mode == _PROTO_CLIENT and port == 0):
            self.port.setToolTip(tr("connection.bad_port"))
            self.port.setFocus()
            self.traffic.append_status(tr("connection.bad_port"))
            return
        try:
            if mode == _PROTO_CLIENT:
                opened = tr("net.opened", host=host, port=port)
                self._connect_cancel = threading.Event()
                self.conn_btn.setText(tr("connection.cancel"))
                self.proto.setEnabled(False)
                self.host.setEnabled(False)
                self.port.setEnabled(False)

                def work():
                    self._link.connect_tcp_client(host, port)

                def done(_result=None):
                    if self._connect_cancel.is_set():
                        self._link.close()
                        self._connect_finished()
                        return
                    self._opened = True
                    self._peer_connected = True
                    self._set_send_enabled(True)
                    self._connect_finished()
                    self.traffic.append_status(opened)
                    self.persist_prefs()

                def fail(message):
                    self._connect_finished()
                    self.traffic.append_status(tr("net.err", err=message))

                self._runner.start(work, done, fail)
                return
            elif mode == _PROTO_SERVER:
                self._link.listen_tcp_server(host, port)
                opened = tr("net.listening", host=host, port=port)
            else:
                try:
                    local_port = int(self.local_port.text().strip() or "0") or port
                except ValueError:
                    self.traffic.append_status(tr("net.err", err="bad local port"))
                    return
                self._link.open_udp(host, port, local_port=local_port)
                opened = tr("net.opened", host=f"{host}:{port}", port=local_port)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("net.err", err=str(exc)))
            return
        self._opened = True
        self._peer_connected = mode != _PROTO_SERVER
        self._set_send_enabled(self._peer_connected)
        self.conn_btn.setText(tr("net.disconnect"))
        self._repaint_btn()
        self._refresh_peers()
        self.traffic.append_status(opened)
        self.persist_prefs()

    def _connect_finished(self) -> None:
        self.conn_btn.setEnabled(True)
        self.proto.setEnabled(not self._opened)
        self.host.setEnabled(not self._opened)
        self.port.setEnabled(not self._opened)
        self.conn_btn.setText(tr("net.disconnect") if self._opened else tr("net.connect"))
        self._repaint_btn()
        self._refresh_peers()

    def _set_send_enabled(self, enabled: bool) -> None:
        self.send_btn.setEnabled(enabled)
        for btn in self._preset_btns:
            btn.setEnabled(enabled)

    def _selected_peer(self) -> str | None:
        data = self.peer_combo.currentData()
        if data in (None, "", "*"):
            return None
        return str(data)

    def _refresh_peers(self) -> None:
        peers = self._link.peers() if self._opened else []
        current = self.peer_combo.currentData()
        self.peer_combo.blockSignals(True)
        self.peer_combo.clear()
        if self.proto.currentIndex() == _PROTO_SERVER:
            self.peer_combo.addItem(tr("net.peer_all"), "*")
            for p in peers:
                self.peer_combo.addItem(p, p)
        else:
            self.peer_combo.addItem(tr("net.peer_auto"), "")
        if current is not None:
            idx = self.peer_combo.findData(current)
            if idx >= 0:
                self.peer_combo.setCurrentIndex(idx)
        self.peer_combo.blockSignals(False)

    def _on_send(self) -> None:
        if not self._opened or not self._peer_connected:
            return
        text = self.send_edit.text()
        if not text:
            return
        ending = _ENDINGS.get(str(self.ending.currentData() or "crlf"), b"\r\n")
        try:
            if self.mode_combo.currentData() == "hex":
                data = parse_hex_input(text) + ending
            else:
                data = text.encode(self._encoding_name()) + ending
        except ValueError:
            self.traffic.append_status(tr("net.err", err="bad hex"))
            return
        try:
            self._link.send(data, peer=self._selected_peer())
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("net.err", err=str(exc)))
            return
        self.traffic.append_tx(data, peer=self._selected_peer() or tr("net.peer_all"))
        if text not in self._history:
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._history_idx = -1
        self.send_edit.clear()

    def _on_preset_send(self, index: int) -> None:
        if not (0 <= index < len(self._preset_edits)):
            return
        text = self._preset_edits[index].text().strip()
        if not text:
            return
        ending = _ENDINGS.get(str(self.ending.currentData() or "crlf"), b"\r\n")
        try:
            if self.mode_combo.currentData() == "hex":
                data = parse_hex_input(text) + ending
            else:
                data = text.encode(self._encoding_name()) + ending
        except ValueError:
            self.traffic.append_status(tr("net.err", err="bad hex"))
            return
        try:
            self._link.send(data, peer=self._selected_peer())
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("net.err", err=str(exc)))
            return
        self.traffic.append_tx(data, peer=self._selected_peer() or tr("net.peer_all"))

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

    def _on_rx(self, data: bytes, peer: str) -> None:
        if not hasattr(self, "_lua_rx"):
            self._lua_rx = bytearray()
        self._lua_rx.extend(data)
        if len(self._lua_rx) > 65536:
            del self._lua_rx[:-65536]
        self.traffic.append_rx(data, peer=peer)

    def _on_rx_mode_changed(self, _index: int = 0) -> None:
        self.traffic.set_display_mode(str(self.rx_mode.currentData() or "ascii"))

    def _encoding_name(self) -> str:
        return str(self.encoding.currentData() or "utf-8")

    def _on_encoding_changed(self) -> None:
        self.traffic.set_encoding(self._encoding_name())
        self.persist_prefs()

    def _on_peer(self, kind: str, peer: str) -> None:
        if kind == "on":
            self._peer_connected = True
            self._set_send_enabled(True)
            self._refresh_peers()
            if self.proto.currentIndex() == _PROTO_SERVER and self.peer_combo.currentData() in (
                None,
                "",
                "*",
            ):
                idx = self.peer_combo.findData(peer)
                if idx >= 0:
                    self.peer_combo.setCurrentIndex(idx)
            self.traffic.append_status(tr("net.peer_on", peer=peer))
        else:
            self._refresh_peers()
            if self.proto.currentIndex() == _PROTO_SERVER:
                self._peer_connected = bool(self._link.peers())
                self._set_send_enabled(self._peer_connected)
            else:
                self._peer_connected = False
                self._set_send_enabled(False)
            self.traffic.append_status(tr("net.peer_off", peer=peer))

    def _on_error(self, message: str) -> None:
        self.traffic.append_status(tr("net.err", err=message))
        self._opened = False
        self._peer_connected = False
        self._set_send_enabled(False)
        self._refresh_peers()
        self._on_proto_changed()
        self._repaint_btn()

    def shutdown(self) -> None:
        self.persist_prefs()
        self._connect_cancel.set()
        self._runner.shutdown()
        self.traffic.stop_replay()
        self.traffic._close_auto_log()
        self._link.close()
