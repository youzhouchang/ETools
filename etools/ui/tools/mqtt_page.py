"""MQTT 3.1.1 client page (QoS 0)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton

from etools.core.frame_hub import frame_hub
from etools.core.mqtt_link import MqttError, MqttLink
from etools.i18n import tr
from etools.ui.runtime import OpRunner
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.traffic_view import TrafficView


class _Relay(QObject):
    message = Signal(str, bytes)
    failed = Signal(str)


class MqttPage(ToolPage):
    tool_id = "mqtt"
    tool_title_key = "tool.mqtt"

    def _build(self) -> None:
        self._link = MqttLink()
        self._runner = OpRunner(self)
        self._relay = _Relay(self)
        self._relay.message.connect(self._on_message)
        self._relay.failed.connect(self._on_error)
        self._link.set_handlers(
            on_message=self._relay.message.emit,
            on_error=self._relay.failed.emit,
        )
        self._opened = False

        self.ctx_box = self.ctx_group(tr("mqtt.title"))
        self.host = QLineEdit("127.0.0.1")
        self.host.setFixedHeight(28)
        self.lbl_host = self.form_row(tr("mqtt.host"), self.host)
        self.port = QLineEdit("1883")
        self.port.setFixedHeight(28)
        self.lbl_port = self.form_row(tr("mqtt.port"), self.port)
        self.client_id = QLineEdit("etools")
        self.client_id.setFixedHeight(28)
        self.lbl_id = self.form_row(tr("mqtt.client_id"), self.client_id)
        self.user = QLineEdit()
        self.user.setFixedHeight(28)
        self.lbl_user = self.form_row(tr("mqtt.user"), self.user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setFixedHeight(28)
        self.lbl_pass = self.form_row(tr("mqtt.password"), self.password)
        self.sub_topic = QLineEdit("device/data")
        self.sub_topic.setFixedHeight(28)
        self.lbl_sub = self.form_row(tr("mqtt.sub"), self.sub_topic)
        self.pub_topic = QLineEdit("device/cmd")
        self.pub_topic.setFixedHeight(28)
        self.lbl_pub = self.form_row(tr("mqtt.pub"), self.pub_topic)

        self.conn_btn = QPushButton()
        self.conn_btn.setObjectName("accent")
        self.conn_btn.setFixedHeight(32)
        self.ctx_action(self.conn_btn)
        self.sub_btn = QPushButton(tr("mqtt.subscribe"))
        self.sub_btn.setObjectName("ghost")
        self.sub_btn.setFixedHeight(28)
        self.sub_btn.setEnabled(False)
        self.ctx_action(self.sub_btn)

        box = self.main_group(tr("tool.mqtt"))
        lay = box.layout()
        self.traffic = TrafficView()
        lay.addWidget(self.traffic, 1)

        row = QHBoxLayout()
        self.payload = QLineEdit()
        self.payload.setFixedHeight(28)
        self.payload.setPlaceholderText(tr("mqtt.payload"))
        self.pub_btn = QPushButton(tr("mqtt.publish"))
        self.pub_btn.setObjectName("accent")
        self.pub_btn.setFixedHeight(28)
        self.pub_btn.setEnabled(False)
        row.addWidget(self.payload, 1)
        row.addWidget(self.pub_btn)
        lay.addLayout(row)

        self.conn_btn.clicked.connect(self._on_toggle)
        self.sub_btn.clicked.connect(self._on_subscribe)
        self.pub_btn.clicked.connect(self._on_publish)
        self.payload.returnPressed.connect(self._on_publish)
        self._load_prefs()
        self.retranslate()

    @property
    def is_open(self) -> bool:
        return self._opened

    def persist_prefs(self) -> None:
        self._persist()

    def link_status(self) -> tuple[str, str]:
        if not self._opened:
            return tr("status.link_idle"), "warn"
        return tr("mqtt.opened", host=self.host.text().strip(), port=self.port.text().strip()), "ok"

    def retranslate(self) -> None:
        self.ctx_box.setTitle(tr("mqtt.title"))
        self.lbl_host.setText(tr("mqtt.host"))
        self.lbl_port.setText(tr("mqtt.port"))
        self.lbl_id.setText(tr("mqtt.client_id"))
        self.lbl_user.setText(tr("mqtt.user"))
        self.lbl_pass.setText(tr("mqtt.password"))
        self.lbl_sub.setText(tr("mqtt.sub"))
        self.lbl_pub.setText(tr("mqtt.pub"))
        self.conn_btn.setText(tr("mqtt.disconnect") if self._opened else tr("mqtt.connect"))
        self.sub_btn.setText(tr("mqtt.subscribe"))
        self.pub_btn.setText(tr("mqtt.publish"))
        self.payload.setPlaceholderText(tr("mqtt.payload"))
        self.traffic.retranslate()
        self.traffic.set_placeholder(tr("mqtt.placeholder"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("connect", "act.connect", "connect", self._on_toggle),
            ToolActionSpec("clear", "act.clear", "clear", self.traffic.clear),
        ]

    def shutdown(self) -> None:
        self.traffic.shutdown()
        self._persist()
        self._runner.shutdown()
        self._link.close()

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        self.host.setText(str(prefs.get("host") or "127.0.0.1"))
        self.port.setText(str(prefs.get("port") or "1883"))
        self.client_id.setText(str(prefs.get("client_id") or "etools"))
        self.user.setText(str(prefs.get("user") or ""))
        self.sub_topic.setText(str(prefs.get("sub") or "device/data"))
        self.pub_topic.setText(str(prefs.get("pub") or "device/cmd"))

    def _persist(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "host": self.host.text().strip(),
                "port": self.port.text().strip(),
                "client_id": self.client_id.text().strip(),
                "user": self.user.text().strip(),
                "sub": self.sub_topic.text().strip(),
                "pub": self.pub_topic.text().strip(),
            },
        )

    def _set_open(self, on: bool) -> None:
        self._opened = on
        self.sub_btn.setEnabled(on)
        self.pub_btn.setEnabled(on)
        self.conn_btn.setText(tr("mqtt.disconnect") if on else tr("mqtt.connect"))
        self.conn_btn.setObjectName("danger" if on else "accent")
        self.conn_btn.style().unpolish(self.conn_btn)
        self.conn_btn.style().polish(self.conn_btn)
        self.notify_state()

    def _on_toggle(self) -> None:
        if self._runner.busy:
            return
        if self._opened:
            self._link.close()
            self._set_open(False)
            self.traffic.append_status(tr("mqtt.closed"))
            self._persist()
            return
        try:
            port = int(self.port.text().strip() or "1883")
        except ValueError:
            self.traffic.append_status(tr("mqtt.err", err="bad port"))
            return
        host = self.host.text().strip()
        if not host:
            self.traffic.append_status(tr("mqtt.err", err="host required"))
            return
        client_id = self.client_id.text().strip() or "etools"
        username = self.user.text().strip()
        password = self.password.text()
        self.conn_btn.setEnabled(False)
        self.traffic.append_status(tr("connection.connecting"))

        def work() -> None:
            self._link.connect(
                host,
                port,
                client_id=client_id,
                username=username,
                password=password,
                timeout=3.0,
            )

        def opened(_result=None) -> None:
            self.conn_btn.setEnabled(True)
            self._set_open(True)
            self.traffic.append_status(tr("mqtt.opened", host=host, port=port))
            self._persist()
            if self.sub_topic.text().strip():
                self._on_subscribe()

        def failed(message: str) -> None:
            self.conn_btn.setEnabled(True)
            self._set_open(False)
            self.traffic.append_status(tr("mqtt.err", err=message))

        self._runner.start(work, opened, failed)

    def _on_subscribe(self) -> None:
        topic = self.sub_topic.text().strip()
        if not topic or not self._opened:
            return
        try:
            self._link.subscribe(topic)
        except MqttError as exc:
            self.traffic.append_status(tr("mqtt.err", err=str(exc)))
            return
        self.traffic.append_status(topic)
        self._persist()

    def _on_publish(self) -> None:
        if not self._opened:
            return
        topic = self.pub_topic.text().strip()
        if not topic:
            return
        text = self.payload.text()
        try:
            self._link.publish(topic, text.encode("utf-8"))
        except MqttError as exc:
            self.traffic.append_status(tr("mqtt.err", err=str(exc)))
            return
        self.traffic.append_tx(text.encode("utf-8"), peer=topic)
        self._persist()

    def _on_message(self, topic: str, payload: bytes) -> None:
        self.traffic.append_rx(payload, peer=topic)
        frame_hub.publish("mqtt", payload)

    def _on_error(self, message: str) -> None:
        self._set_open(False)
        self.traffic.append_status(tr("mqtt.err", err=message))
