"""Network debug assistant page (socket TCP/UDP)."""

from __future__ import annotations

import socket

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from etools.core.net_link import NetLink
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.ip_edit import IPv4Edit
from etools.ui.widgets.traffic_view import TrafficView, parse_hex_input

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


def _local_ipv4() -> str:
    """Best-effort outbound-facing IPv4 of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


class _RxRelay(QObject):
    received = Signal(bytes, str)
    failed = Signal(str)
    peer = Signal(str, str)  # kind, peer


class EthernetPage(ToolPage):
    tool_id = "ethernet"
    tool_title_key = "tool.ethernet"

    def _build(self) -> None:
        self._link = NetLink()
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

        self.ctx_conn = self.ctx_group(tr("net.title"))

        self.proto = QComboBox()
        self.proto.addItems(["TCP Client", "TCP Server", "UDP"])
        self.proto.setFixedHeight(28)
        self.lbl_proto = self.form_row(tr("net.proto"), self.proto)

        self.host = IPv4Edit("192.168.1.100")
        self.lbl_host = self.form_row(tr("net.remote_host"), self.host)

        self.port = QLineEdit("8080")
        self.port.setFixedHeight(28)
        self.lbl_port = self.form_row(tr("net.remote_port"), self.port)

        self.local_port = QLineEdit("8080")
        self.local_port.setFixedHeight(28)
        self.lbl_local_port = self.form_row(tr("net.local_port"), self.local_port)

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
        self.ending = QComboBox()
        self.ending.addItem(tr("serial.ending.crlf"), "crlf")
        self.ending.addItem(tr("serial.ending.lf"), "lf")
        self.ending.addItem(tr("serial.ending.cr"), "cr")
        self.ending.addItem(tr("serial.ending.none"), "none")
        self.ending.setFixedHeight(28)
        self.ending.setFixedWidth(88)
        self.lbl_ending = QLabel(tr("net.ending"))
        self.send_edit = QLineEdit()
        self.send_edit.setFixedHeight(30)
        self.send_edit.setPlaceholderText(tr("net.send_ph"))
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("ghost")
        self.send_btn.setEnabled(False)
        send_row.addWidget(self.lbl_mode)
        send_row.addWidget(self.mode_combo)
        send_row.addWidget(self.lbl_ending)
        send_row.addWidget(self.ending)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.send_btn)
        sess_lay.addLayout(send_row)

        self.conn_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.send_edit.returnPressed.connect(self._on_send)
        self.proto.currentIndexChanged.connect(self._on_proto_changed)
        self.retranslate()
        self._load_prefs()
        self._on_proto_changed()
        self.proto.currentIndexChanged.connect(lambda _i: self._persist_prefs())
        self.port.editingFinished.connect(self._persist_prefs)
        self.local_port.editingFinished.connect(self._persist_prefs)
        self.host.editingFinished.connect(self._persist_prefs)
        self.ending.currentIndexChanged.connect(lambda _i: self._persist_prefs())
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._persist_prefs())

    def _on_proto_changed(self) -> None:
        mode = self.proto.currentIndex()
        is_server = mode == _PROTO_SERVER
        is_udp = mode == _PROTO_UDP
        # Server binds locally; UDP needs both local bind and remote peer.
        self.lbl_host.setText(tr("net.host") if is_server else tr("net.remote_host"))
        self.lbl_port.setText(tr("net.port") if is_server else tr("net.remote_port"))
        self.local_port.setVisible(is_udp)
        self.lbl_local_port.setVisible(is_udp)
        if is_server:
            self.host.setText("0.0.0.0")
            self.conn_btn.setText(tr("net.listen"))
        elif is_udp:
            self.lbl_host.setText(tr("net.remote_host"))
            self.lbl_port.setText(tr("net.remote_port"))
            self.conn_btn.setText(tr("net.connect"))
        else:
            self.conn_btn.setText(tr("net.connect"))
        if not self._opened:
            self.conn_btn.setText(tr("net.listen") if is_server else tr("net.connect"))

    def retranslate(self) -> None:
        self.ctx_conn.setTitle(tr("net.title"))
        self.lbl_proto.setText(tr("net.proto"))
        mode = self.proto.currentIndex()
        self.lbl_host.setText(tr("net.host") if mode == _PROTO_SERVER else tr("net.remote_host"))
        self.lbl_port.setText(tr("net.port") if mode == _PROTO_SERVER else tr("net.remote_port"))
        self.lbl_local_port.setText(tr("net.local_port"))
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
        self.mode_combo.setItemText(0, tr("net.mode.ascii"))
        self.mode_combo.setItemText(1, tr("net.mode.hex"))
        self.lbl_ending.setText(tr("net.ending"))
        self.ending.setItemText(0, tr("serial.ending.crlf"))
        self.ending.setItemText(1, tr("serial.ending.lf"))
        self.ending.setItemText(2, tr("serial.ending.cr"))
        self.ending.setItemText(3, tr("serial.ending.none"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("toggle", "net.connect", "connect", self.toggle_connection),
            ToolActionSpec("send", "net.send", "program", self.send),
            ToolActionSpec(
                "clear", "mon.clear", "clear", self.clear_view, separator_before=True
            ),
        ]

    def toggle_connection(self) -> None:
        self._on_toggle()

    def send(self) -> None:
        self._on_send()

    def clear_view(self) -> None:
        self.traffic.clear()

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        if prefs.get("proto_index") is not None:
            idx = int(prefs["proto_index"])
            if 0 <= idx < self.proto.count():
                self.proto.setCurrentIndex(idx)
        if prefs.get("host"):
            self.host.setText(str(prefs["host"]))
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

    def _persist_prefs(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "proto_index": self.proto.currentIndex(),
                "host": self.host.text().strip(),
                "port": self.port.text().strip(),
                "local_port": self.local_port.text().strip(),
                "ending": self.ending.currentData(),
                "send_mode": self.mode_combo.currentData(),
            },
        )

    def _repaint_btn(self) -> None:
        self.conn_btn.setObjectName("danger" if self._opened else "accent")
        st = self.conn_btn.style()
        st.unpolish(self.conn_btn)
        st.polish(self.conn_btn)

    def _on_toggle(self) -> None:
        if self._opened:
            self._link.close()
            self._opened = False
            self.send_btn.setEnabled(False)
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
        try:
            if mode == _PROTO_CLIENT:
                self._link.connect_tcp_client(host, port)
                opened = tr("net.opened", host=host, port=port)
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
        self.send_btn.setEnabled(True)
        self.conn_btn.setText(tr("net.disconnect"))
        self._repaint_btn()
        self.traffic.append_status(opened)

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
            self.traffic.append_status(tr("net.err", err="bad hex"))
            return
        try:
            self._link.send(data)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("net.err", err=str(exc)))
            return
        self.traffic.append_tx(data)
        self.send_edit.clear()

    def _on_rx(self, data: bytes, peer: str) -> None:
        self.traffic.append_rx(data, peer=peer)

    def _on_peer(self, kind: str, peer: str) -> None:
        if kind == "on":
            self.traffic.append_status(tr("net.peer_on", peer=peer))
        else:
            self.traffic.append_status(tr("net.peer_off", peer=peer))

    def _on_error(self, message: str) -> None:
        self.traffic.append_status(tr("net.err", err=message))
        self._opened = False
        self.send_btn.setEnabled(False)
        self._on_proto_changed()
        self._repaint_btn()

    def shutdown(self) -> None:
        self._persist_prefs()
        self._link.close()
