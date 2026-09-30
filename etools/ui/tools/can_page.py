"""CAN / CANopen debug assistant page (python-can)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.can_link import (
    COMMON_BITRATES,
    KNOWN_ENDPOINTS,
    CanLink,
    python_can_available,
)
from etools.core.can_trace import TraceFrame, TraceWriter, read_trace
from etools.core.canopen import (
    HB_STATES,
    NMT_COMMANDS,
    NMT_PREOP,
    NMT_RESET_COMM,
    NMT_RESET_NODE,
    NMT_START,
    NMT_STOP,
    encode_uint,
    is_sdo_response,
    nmt_frame,
    parse_heartbeat,
    parse_sdo_response,
    sdo_read_request,
    sdo_write_request,
)
from etools.core.eds import EdsFile, parse_eds
from etools.i18n import tr
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.traffic_view import TrafficView, parse_hex_input


class _RxRelay(QObject):
    received = Signal(object)  # can.Message
    failed = Signal(str)


class CanPage(ToolPage):
    tool_id = "can"
    tool_title_key = "tool.can"

    def _build(self) -> None:
        self._link = CanLink()
        self._relay = _RxRelay(self)
        self._relay.received.connect(self._on_rx)
        self._relay.failed.connect(self._on_error)
        self._link.set_handlers(
            on_rx=self._relay.received.emit,
            on_error=self._relay.failed.emit,
        )
        self._opened = False
        self._hb_nodes: dict[int, tuple[int, float]] = {}  # node -> (state, last_monotonic)
        self._lua_frames: list[dict[str, Any]] = []
        self._eds: EdsFile | None = None
        self._trace_writer: TraceWriter | None = None
        self._play_timer: QTimer | None = None
        self._play_queue: list[TraceFrame] = []

        # ---- left: bus connection ------------------------------------
        self.ctx_bus = self.ctx_group(tr("can.bus"))

        self.iface = QComboBox()
        self.iface.setFixedHeight(28)
        for ep in KNOWN_ENDPOINTS:
            self.iface.addItem(ep.label, (ep.interface, ep.channel))
        self.lbl_iface = self.form_row(tr("can.interface"), self.iface)

        self.channel = QLineEdit("")
        self.channel.setFixedHeight(28)
        self.channel.setPlaceholderText("0 / can0 / PCAN_USBBUS1 …")
        self.lbl_channel = self.form_row(tr("can.channel"), self.channel)

        self.bitrate = QComboBox()
        self.bitrate.setEditable(True)
        self.bitrate.setFixedHeight(28)
        for b in COMMON_BITRATES:
            self.bitrate.addItem(str(b))
        self.bitrate.setCurrentText("500000")
        self.lbl_bitrate = self.form_row(tr("can.bitrate"), self.bitrate)

        self.fd_check = QCheckBox(tr("can.fd"))
        self.fd_check.setFixedHeight(24)
        self.lbl_fd = self.form_row(tr("can.fd"), self.fd_check)

        self.data_bitrate = QComboBox()
        self.data_bitrate.setEditable(True)
        self.data_bitrate.setFixedHeight(28)
        for b in COMMON_BITRATES:
            self.data_bitrate.addItem(str(b))
        self.data_bitrate.setCurrentText("2000000")
        self.lbl_data_bitrate = self.form_row(tr("can.data_bitrate"), self.data_bitrate)

        # Trace lives with the bus (not CANopen) so the left column balances.
        self.rec_btn = QPushButton(tr("can.rec_start"))
        self.rec_btn.setObjectName("ghost")
        self.rec_btn.setFixedHeight(28)
        self.play_btn = QPushButton(tr("can.play"))
        self.play_btn.setObjectName("ghost")
        self.play_btn.setFixedHeight(28)
        trace_row = QHBoxLayout()
        trace_row.setContentsMargins(0, 0, 0, 0)
        trace_row.setSpacing(6)
        trace_row.addWidget(self.rec_btn, 1)
        trace_row.addWidget(self.play_btn, 1)
        trace_host = QWidget()
        trace_host.setLayout(trace_row)
        self.lbl_trace = self.form_row(tr("can.trace"), trace_host)

        self.conn_btn = QPushButton()
        self.conn_btn.setObjectName("accent")
        self.conn_btn.setFixedHeight(32)
        self.ctx_action(self.conn_btn)

        # ---- left: CANopen -------------------------------------------
        self.ctx_open = self.ctx_group(tr("can.canopen"))

        self.node_spin = QSpinBox()
        self.node_spin.setRange(1, 127)
        self.node_spin.setValue(1)
        self.node_spin.setFixedHeight(28)
        self.lbl_node = self.form_row(tr("can.node_id"), self.node_spin)

        # NMT: 2×2 grid so labels are never crushed into one skinny row.
        self.nmt_start = QPushButton(tr("can.nmt_start"))
        self.nmt_stop = QPushButton(tr("can.nmt_stop"))
        self.nmt_preop = QPushButton(tr("can.nmt_preop"))
        self.nmt_reset = QPushButton(tr("can.nmt_reset"))
        for b in (self.nmt_start, self.nmt_stop, self.nmt_preop, self.nmt_reset):
            b.setObjectName("ghost")
            b.setFixedHeight(28)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        nmt_grid = QGridLayout()
        nmt_grid.setContentsMargins(0, 0, 0, 0)
        nmt_grid.setHorizontalSpacing(6)
        nmt_grid.setVerticalSpacing(6)
        nmt_grid.addWidget(self.nmt_start, 0, 0)
        nmt_grid.addWidget(self.nmt_stop, 0, 1)
        nmt_grid.addWidget(self.nmt_preop, 1, 0)
        nmt_grid.addWidget(self.nmt_reset, 1, 1)
        nmt_host = QWidget()
        nmt_host.setLayout(nmt_grid)
        self.lbl_nmt = self.form_row(tr("can.nmt"), nmt_host)

        self.sdo_index = QLineEdit("0x1000")
        self.sdo_index.setFixedHeight(28)
        self.lbl_sdo_index = self.form_row(tr("can.sdo_index"), self.sdo_index)

        self.sdo_sub = QSpinBox()
        self.sdo_sub.setRange(0, 255)
        self.sdo_sub.setFixedHeight(28)
        self.lbl_sdo_sub = self.form_row(tr("can.sdo_sub"), self.sdo_sub)

        self.sdo_value = QLineEdit("0")
        self.sdo_value.setFixedHeight(28)
        self.sdo_value.setPlaceholderText("0 | 0x1234 | DE AD BE EF")
        self.lbl_sdo_value = self.form_row(tr("can.sdo_value"), self.sdo_value)

        sdo_row = QHBoxLayout()
        sdo_row.setContentsMargins(0, 0, 0, 0)
        sdo_row.setSpacing(6)
        self.sdo_read_btn = QPushButton(tr("can.sdo_read"))
        self.sdo_write_btn = QPushButton(tr("can.sdo_write"))
        for b in (self.sdo_read_btn, self.sdo_write_btn):
            b.setObjectName("ghost")
            b.setFixedHeight(28)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            sdo_row.addWidget(b, 1)
        sdo_host = QWidget()
        sdo_host.setLayout(sdo_row)
        self.lbl_sdo = self.form_row(tr("can.sdo"), sdo_host)

        # EDS / PDO
        self.eds_path = QLineEdit()
        self.eds_path.setFixedHeight(28)
        self.eds_path.setPlaceholderText("device.eds")
        self.eds_browse = QPushButton(tr("can.eds_load"))
        self.eds_browse.setObjectName("ghost")
        self.eds_browse.setFixedHeight(28)
        self.eds_browse.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        eds_row = QHBoxLayout()
        eds_row.setContentsMargins(0, 0, 0, 0)
        eds_row.setSpacing(4)
        eds_row.addWidget(self.eds_path, 1)
        eds_row.addWidget(self.eds_browse)
        eds_host = QWidget()
        eds_host.setLayout(eds_row)
        self.lbl_eds = self.form_row(tr("can.eds"), eds_host)

        # ---- main: monitor + send + open nodes ------------------------
        mon_box = self.main_group(tr("can.monitor"))
        mon_lay = mon_box.layout()
        self.traffic = TrafficView()
        self.view = self.traffic.view
        mon_lay.addWidget(self.traffic, 1)

        send_box = QGroupBox(tr("can.send_frame"))
        send_box.setObjectName("mainGroup")
        send_lay = QHBoxLayout(send_box)
        send_lay.setContentsMargins(8, 8, 8, 8)
        send_lay.setSpacing(8)

        self.frame_id = QLineEdit("0x123")
        self.frame_id.setFixedHeight(28)
        self.frame_id.setFixedWidth(100)
        self.frame_id.setPlaceholderText("ID")
        self.ext_check = QCheckBox(tr("can.ext_id"))
        self.ext_check.setFixedHeight(28)
        self.rtr_check = QCheckBox(tr("can.rtr"))
        self.rtr_check.setFixedHeight(28)
        self.frame_data = QLineEdit("01 02 03 04")
        self.frame_data.setFixedHeight(28)
        self.frame_data.setPlaceholderText("DE AD BE EF …")
        self.send_btn = QPushButton(tr("can.send"))
        self.send_btn.setObjectName("accent")
        self.send_btn.setFixedHeight(28)

        send_lay.addWidget(QLabel(tr("can.frame_id")))
        send_lay.addWidget(self.frame_id)
        send_lay.addWidget(self.ext_check)
        send_lay.addWidget(self.rtr_check)
        send_lay.addWidget(QLabel(tr("can.data")))
        send_lay.addWidget(self.frame_data, 1)
        send_lay.addWidget(self.send_btn)
        mon_lay.addWidget(send_box)

        hb_box = QGroupBox(tr("can.heartbeat"))
        hb_box.setObjectName("mainGroup")
        hb_lay = QVBoxLayout(hb_box)
        hb_lay.setContentsMargins(8, 8, 8, 8)
        self.hb_table = QTableWidget(0, 3)
        self.hb_table.setHorizontalHeaderLabels(
            [tr("can.node_id"), tr("can.hb_state"), tr("can.hb_age")]
        )
        self.hb_table.horizontalHeader().setStretchLastSection(True)
        self.hb_table.verticalHeader().setVisible(False)
        self.hb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hb_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.hb_table.setMinimumHeight(110)
        hb_lay.addWidget(self.hb_table)
        mon_lay.addWidget(hb_box)

        # PDO map table
        pdo_box = QGroupBox(tr("can.pdo"))
        pdo_box.setObjectName("mainGroup")
        pdo_lay = QVBoxLayout(pdo_box)
        pdo_lay.setContentsMargins(8, 8, 8, 8)
        self.pdo_table = QTableWidget(0, 4)
        self.pdo_table.setHorizontalHeaderLabels(
            ["PDO", tr("can.pdo_dir"), "Index/Sub", tr("can.pdo_name")]
        )
        self.pdo_table.horizontalHeader().setStretchLastSection(True)
        self.pdo_table.verticalHeader().setVisible(False)
        self.pdo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pdo_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.pdo_table.setMinimumHeight(120)
        pdo_lay.addWidget(self.pdo_table)
        mon_lay.addWidget(pdo_box)

        # ---- wiring ---------------------------------------------------
        self.conn_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.frame_data.returnPressed.connect(self._on_send)
        self.iface.currentIndexChanged.connect(self._on_iface_changed)
        self.nmt_start.clicked.connect(lambda: self._send_nmt(NMT_START))
        self.nmt_stop.clicked.connect(lambda: self._send_nmt(NMT_STOP))
        self.nmt_preop.clicked.connect(lambda: self._send_nmt(NMT_PREOP))
        self.nmt_reset.clicked.connect(lambda: self._send_nmt(NMT_RESET_NODE))
        self.sdo_read_btn.clicked.connect(self._on_sdo_read)
        self.sdo_write_btn.clicked.connect(self._on_sdo_write)
        self.eds_browse.clicked.connect(self._on_load_eds)
        self.rec_btn.clicked.connect(self._on_toggle_record)
        self.play_btn.clicked.connect(self._on_play_trace)

        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(500)
        self._hb_timer.timeout.connect(self._refresh_hb_table)
        self._hb_timer.start()

        self._on_iface_changed()
        self._load_prefs()
        self._repaint_btn()
        self.retranslate()

    # -- prefs / chrome -------------------------------------------------

    def retranslate(self) -> None:
        self.ctx_bus.setTitle(tr("can.bus"))
        self.ctx_open.setTitle(tr("can.canopen"))
        self.lbl_iface.setText(tr("can.interface"))
        self.lbl_channel.setText(tr("can.channel"))
        self.lbl_bitrate.setText(tr("can.bitrate"))
        self.lbl_fd.setText(tr("can.fd"))
        self.lbl_data_bitrate.setText(tr("can.data_bitrate"))
        self.lbl_node.setText(tr("can.node_id"))
        self.lbl_nmt.setText(tr("can.nmt"))
        self.lbl_sdo_index.setText(tr("can.sdo_index"))
        self.lbl_sdo_sub.setText(tr("can.sdo_sub"))
        self.lbl_sdo_value.setText(tr("can.sdo_value"))
        self.lbl_sdo.setText(tr("can.sdo"))
        self.fd_check.setText(tr("can.fd"))
        self.ext_check.setText(tr("can.ext_id"))
        self.rtr_check.setText(tr("can.rtr"))
        self.send_btn.setText(tr("can.send"))
        self.nmt_start.setText(tr("can.nmt_start"))
        self.nmt_stop.setText(tr("can.nmt_stop"))
        self.nmt_preop.setText(tr("can.nmt_preop"))
        self.nmt_reset.setText(tr("can.nmt_reset"))
        self.sdo_read_btn.setText(tr("can.sdo_read"))
        self.sdo_write_btn.setText(tr("can.sdo_write"))
        self.conn_btn.setText(tr("can.close") if self._opened else tr("can.open"))
        self.traffic.retranslate()
        self.traffic.set_placeholder(tr("can.placeholder"))
        self.hb_table.setHorizontalHeaderLabels(
            [tr("can.node_id"), tr("can.hb_state"), tr("can.hb_age")]
        )
        self.lbl_eds.setText(tr("can.eds"))
        self.eds_browse.setText(tr("can.eds_load"))
        self.lbl_trace.setText(tr("can.trace"))
        self.rec_btn.setText(
            tr("can.rec_stop") if self._trace_writer else tr("can.rec_start")
        )
        self.play_btn.setText(tr("can.play"))
        self.pdo_table.setHorizontalHeaderLabels(
            ["PDO", tr("can.pdo_dir"), "Index/Sub", tr("can.pdo_name")]
        )

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("connect", "act.connect", "connect", self.toggle_connection),
            ToolActionSpec("clear", "act.clear", "clear", self.clear_view),
        ]

    def toggle_connection(self) -> None:
        self._on_toggle()

    def clear_view(self) -> None:
        self.traffic.clear()
        self._hb_nodes.clear()
        self._refresh_hb_table()

    @property
    def is_open(self) -> bool:
        return self._opened

    def link_status(self) -> tuple[str, str]:
        if not self._opened:
            return tr("status.link_idle"), "warn"
        iface = str(self.iface.currentData()[0] if self.iface.currentData() else "?")
        return tr("status.link_can", iface=iface), "ok"

    def shutdown(self) -> None:
        self._stop_record()
        self._stop_play()
        self._link.close()

    # -- Lua bridge helpers --------------------------------------------

    def lua_opened(self) -> bool:
        return self._opened

    def lua_send_frame(
        self, arb_id: int, data: str = "", ext: bool = False, rtr: bool = False
    ) -> bool:
        if not self._opened:
            return False
        try:
            payload = parse_hex_input(data) if data and not rtr else b""
        except ValueError:
            return False
        try:
            self._link.send(
                int(arb_id),
                payload,
                is_extended=bool(ext),
                is_rtr=bool(rtr),
                is_fd=self.fd_check.isChecked(),
            )
        except Exception:  # noqa: BLE001
            return False
        peer = f"{int(arb_id):08X}" if ext else f"{int(arb_id):03X}"
        self.traffic.append_tx(payload, peer=peer)
        self._trace_tx(arb_id, payload, ext=ext, rtr=rtr)
        return True

    def lua_nmt(self, command: str, node: int = 0) -> bool:
        key = str(command or "").strip().lower()
        mapping = {
            "start": NMT_START,
            "stop": NMT_STOP,
            "preop": NMT_PREOP,
            "pre-op": NMT_PREOP,
            "reset": NMT_RESET_NODE,
            "reset_node": NMT_RESET_NODE,
            "reset_comm": NMT_RESET_COMM,
        }
        cmd = mapping.get(key)
        if cmd is None:
            try:
                cmd = int(key, 0)
            except ValueError:
                return False
        if not self._opened:
            return False
        try:
            cob, payload = nmt_frame(cmd, int(node))
            self._link.send(cob, payload)
        except Exception:  # noqa: BLE001
            return False
        return True

    def lua_sdo_read(self, node: int, index: int, subindex: int = 0) -> str:
        if not self._opened:
            return ""
        try:
            cob, payload = sdo_read_request(int(node), int(index), int(subindex))
            self._link.send(cob, payload)
        except Exception:  # noqa: BLE001
            return ""
        return ""

    def lua_sdo_write(
        self, node: int, index: int, subindex: int, value: str
    ) -> bool:
        if not self._opened:
            return False
        text = str(value or "").strip()
        try:
            if text.lower().startswith("0x"):
                raw = encode_uint(int(text, 16), 4)
            elif " " in text:
                raw = parse_hex_input(text)
            else:
                raw = encode_uint(int(text, 0), 4)
            cob, payload = sdo_write_request(int(node), int(index), int(subindex), raw)
            self._link.send(cob, payload)
        except Exception:  # noqa: BLE001
            return False
        return True

    def lua_take_frames(self, max_frames: int = 16) -> list[dict[str, Any]]:
        n = max(0, int(max_frames))
        out = self._lua_frames[:n]
        del self._lua_frames[:n]
        return out

    def _push_lua_frame(
        self, arb_id: int, data: bytes, *, ext: bool = False, rtr: bool = False
    ) -> None:
        self._lua_frames.append(
            {
                "id": int(arb_id),
                "data": bytes(data).hex(" ").upper(),
                "ext": bool(ext),
                "rtr": bool(rtr),
            }
        )
        if len(self._lua_frames) > 256:
            del self._lua_frames[:-256]

    # -- EDS / PDO / trace ---------------------------------------------

    def _on_load_eds(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, tr("can.eds_load"), self.eds_path.text().strip(), "EDS (*.eds *.dcf);;All (*.*)"
        )
        if not path:
            return
        self.load_eds_file(path)

    def load_eds_file(self, path: str) -> None:
        try:
            eds = parse_eds(path)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        self._eds = eds
        self.eds_path.setText(path)
        self._refresh_pdo_table()
        self.traffic.append_status(
            tr("can.eds_loaded", name=eds.product_name or path, n=len(eds.entries))
        )

    def _refresh_pdo_table(self) -> None:
        self.pdo_table.setRowCount(0)
        if not self._eds:
            return
        rows = self._eds.mapping_labels()
        flat: list[tuple[str, str, str, str]] = []
        for pdo_index, _pdo_name, items in rows:
            kind = "TPDO" if pdo_index >= 0x1A00 else "RPDO"
            label = f"{kind}{(pdo_index & 0xFF) + 1}"
            for obj_index, obj_sub, bitlen, name in items:
                flat.append(
                    (
                        label,
                        kind,
                        f"0x{obj_index:04X}/{obj_sub} ({bitlen}b)",
                        name or f"0x{obj_index:04X}",
                    )
                )
        self.pdo_table.setRowCount(len(flat))
        for r, (a, b, c, d) in enumerate(flat):
            self.pdo_table.setItem(r, 0, QTableWidgetItem(a))
            self.pdo_table.setItem(r, 1, QTableWidgetItem(b))
            self.pdo_table.setItem(r, 2, QTableWidgetItem(c))
            self.pdo_table.setItem(r, 3, QTableWidgetItem(d))

    def _on_toggle_record(self) -> None:
        if self._trace_writer:
            self._stop_record()
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, tr("can.rec_start"), "can_trace.csv", "CSV (*.csv);;All (*.*)"
        )
        if not path:
            return
        try:
            self._trace_writer = TraceWriter(path)
        except OSError as exc:
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        self.rec_btn.setText(tr("can.rec_stop"))
        self.traffic.append_status(tr("can.rec_started", path=path))

    def _stop_record(self) -> None:
        w, self._trace_writer = self._trace_writer, None
        if w is None:
            return
        n = w.count
        w.close()
        self.rec_btn.setText(tr("can.rec_start"))
        self.traffic.append_status(tr("can.rec_stopped", n=n))

    def _trace_rx(self, arb_id: int, data: bytes, *, ext: bool = False, rtr: bool = False) -> None:
        if self._trace_writer is None:
            return
        self._trace_writer.write(
            TraceFrame(
                t=self._trace_writer.elapsed(),
                direction="rx",
                arbitration_id=int(arb_id),
                is_extended=bool(ext),
                is_rtr=bool(rtr),
                data=bytes(data),
            )
        )

    def _trace_tx(self, arb_id: int, data: bytes, *, ext: bool = False, rtr: bool = False) -> None:
        if self._trace_writer is None:
            return
        self._trace_writer.write(
            TraceFrame(
                t=self._trace_writer.elapsed(),
                direction="tx",
                arbitration_id=int(arb_id),
                is_extended=bool(ext),
                is_rtr=bool(rtr),
                data=bytes(data),
            )
        )

    def _on_play_trace(self) -> None:
        if self._play_timer is not None:
            self._stop_play()
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, tr("can.play"), "", "CSV (*.csv);;All (*.*)"
        )
        if not path:
            return
        try:
            frames = read_trace(path)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        if not frames:
            self.traffic.append_status(tr("can.play_empty"))
            return
        if not self._opened:
            self.traffic.append_status(tr("can.need_open"))
            return
        self._play_queue = list(frames)  # type: ignore[assignment]
        self._play_timer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.timeout.connect(self._play_step)
        self.play_btn.setText(tr("can.play_stop"))
        self.traffic.append_status(tr("can.play_started", n=len(frames)))
        self._play_step()

    def _stop_play(self) -> None:
        t, self._play_timer = self._play_timer, None
        if t is not None:
            t.stop()
            t.deleteLater()
        self._play_queue = []
        self.play_btn.setText(tr("can.play"))

    def _play_step(self) -> None:
        queue = getattr(self, "_play_queue", [])
        if not queue or self._play_timer is None:
            self._stop_play()
            self.traffic.append_status(tr("can.play_done"))
            return
        frame = queue.pop(0)
        try:
            self._link.send(
                frame.arbitration_id,
                frame.data,
                is_extended=frame.is_extended,
                is_rtr=frame.is_rtr,
                is_fd=frame.is_fd,
            )
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            self._stop_play()
            return
        peer = f"{frame.arbitration_id:08X}" if frame.is_extended else f"{frame.arbitration_id:03X}"
        self.traffic.append_tx(frame.data, peer=peer)
        if not queue:
            self._stop_play()
            self.traffic.append_status(tr("can.play_done"))
            return
        nxt = queue[0]
        delay = max(1, int((nxt.t - frame.t) * 1000))
        self._play_timer.start(min(delay, 2000))

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        if prefs.get("iface") is not None:
            idx = self.iface.findData(prefs["iface"])
            if idx >= 0:
                self.iface.setCurrentIndex(idx)
        if prefs.get("channel"):
            self.channel.setText(str(prefs["channel"]))
        if prefs.get("bitrate"):
            self.bitrate.setCurrentText(str(prefs["bitrate"]))
        if prefs.get("fd") is not None:
            self.fd_check.setChecked(bool(prefs["fd"]))
        if prefs.get("data_bitrate"):
            self.data_bitrate.setCurrentText(str(prefs["data_bitrate"]))
        if prefs.get("node_id"):
            try:
                self.node_spin.setValue(int(prefs["node_id"]))
            except (TypeError, ValueError):
                pass
        if prefs.get("frame_id"):
            self.frame_id.setText(str(prefs["frame_id"]))
        if prefs.get("frame_data"):
            self.frame_data.setText(str(prefs["frame_data"]))
        if prefs.get("ext_id") is not None:
            self.ext_check.setChecked(bool(prefs["ext_id"]))

    def _persist_prefs(self) -> None:
        data = self.iface.currentData()
        save_tool_prefs(
            self.tool_id,
            {
                "iface": list(data) if isinstance(data, tuple) else data,
                "channel": self.channel.text().strip(),
                "bitrate": self.bitrate.currentText().strip(),
                "fd": self.fd_check.isChecked(),
                "data_bitrate": self.data_bitrate.currentText().strip(),
                "node_id": int(self.node_spin.value()),
                "frame_id": self.frame_id.text().strip(),
                "frame_data": self.frame_data.text().strip(),
                "ext_id": self.ext_check.isChecked(),
            },
        )

    # -- bus -----------------------------------------------------------

    def _on_iface_changed(self, *_args) -> None:
        data = self.iface.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            self.channel.setText(str(data[1]))
        self._persist_prefs()

    def _repaint_btn(self) -> None:
        self.conn_btn.setObjectName("danger" if self._opened else "accent")
        st = self.conn_btn.style()
        st.unpolish(self.conn_btn)
        st.polish(self.conn_btn)

    def _set_connected_ui(self, on: bool) -> None:
        self.iface.setEnabled(not on)
        self.channel.setEnabled(not on)
        self.bitrate.setEnabled(not on)
        self.fd_check.setEnabled(not on)
        self.data_bitrate.setEnabled(not on)
        self.conn_btn.setText(tr("can.close") if on else tr("can.open"))
        self._repaint_btn()
        self.send_btn.setEnabled(on)
        for b in (
            self.nmt_start,
            self.nmt_stop,
            self.nmt_preop,
            self.nmt_reset,
            self.sdo_read_btn,
            self.sdo_write_btn,
        ):
            b.setEnabled(on)

    def _on_toggle(self) -> None:
        if self._opened:
            self._link.close()
            self._opened = False
            self._set_connected_ui(False)
            self.traffic.append_status(tr("can.closed"))
            self._persist_prefs()
            return
        if not python_can_available():
            self.traffic.append_status(tr("can.need_dep"))
            return
        data = self.iface.currentData()
        interface = data[0] if isinstance(data, tuple) else str(data or "")
        channel = self.channel.text().strip() or (data[1] if isinstance(data, tuple) else "")
        try:
            bitrate = int(self.bitrate.currentText().strip() or "500000")
        except ValueError:
            self.traffic.append_status(tr("can.err", err="bad bitrate"))
            return
        try:
            data_br = int(self.data_bitrate.currentText().strip() or "2000000")
        except ValueError:
            data_br = 2000000
        try:
            self._link.open(
                interface,
                channel,
                bitrate,
                fd=self.fd_check.isChecked(),
                data_bitrate=data_br,
            )
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        self._opened = True
        self._set_connected_ui(True)
        self.traffic.append_status(
            tr("can.opened", iface=interface, channel=channel, bitrate=bitrate)
        )
        self._persist_prefs()

    # -- send ----------------------------------------------------------

    def _parse_frame_id(self) -> int | None:
        text = self.frame_id.text().strip().lower().replace("0x", "")
        try:
            return int(text, 16) if text else None
        except ValueError:
            return None

    def _on_send(self) -> None:
        if not self._opened:
            self.traffic.append_status(tr("can.need_open"))
            return
        arb = self._parse_frame_id()
        if arb is None:
            self.traffic.append_status(tr("can.err", err="bad id"))
            return
        try:
            data = (
                parse_hex_input(self.frame_data.text())
                if not self.rtr_check.isChecked()
                else b""
            )
        except ValueError:
            self.traffic.append_status(tr("can.err", err="bad hex"))
            return
        try:
            self._link.send(
                arb,
                data,
                is_extended=self.ext_check.isChecked(),
                is_rtr=self.rtr_check.isChecked(),
                is_fd=self.fd_check.isChecked(),
            )
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        peer = f"{arb:08X}" if self.ext_check.isChecked() else f"{arb:03X}"
        if self.rtr_check.isChecked():
            self.traffic.append_status(f"TX [{peer}] RTR")
        else:
            self.traffic.append_tx(data, peer=peer)
        self._trace_tx(
            arb,
            data,
            ext=self.ext_check.isChecked(),
            rtr=self.rtr_check.isChecked(),
        )

    def _send_nmt(self, command: int) -> None:
        if not self._opened:
            self.traffic.append_status(tr("can.need_open"))
            return
        node = int(self.node_spin.value())
        try:
            # 0 broadcasts; UI node spin is 1..127 so also offer broadcast via 0 check
            cob, payload = nmt_frame(command, node)
            self._link.send(cob, payload)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        name = dict(NMT_COMMANDS).get(command, "?")
        self.traffic.append_status(tr("can.nmt_sent", cmd=name, node=node))

    def _sdo_index_value(self) -> int | None:
        text = self.sdo_index.text().strip().lower()
        try:
            return int(text, 16) if text.startswith("0x") else int(text, 0)
        except ValueError:
            return None

    def _on_sdo_read(self) -> None:
        if not self._opened:
            self.traffic.append_status(tr("can.need_open"))
            return
        node = int(self.node_spin.value())
        index = self._sdo_index_value()
        if index is None:
            self.traffic.append_status(tr("can.err", err="bad index"))
            return
        sub = int(self.sdo_sub.value())
        try:
            cob, payload = sdo_read_request(node, index, sub)
            self._link.send(cob, payload)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        self.traffic.append_status(
            tr("can.sdo_req", op="read", index=f"0x{index:04X}", sub=sub, node=node)
        )

    def _on_sdo_write(self) -> None:
        if not self._opened:
            self.traffic.append_status(tr("can.need_open"))
            return
        node = int(self.node_spin.value())
        index = self._sdo_index_value()
        if index is None:
            self.traffic.append_status(tr("can.err", err="bad index"))
            return
        sub = int(self.sdo_sub.value())
        text = self.sdo_value.text().strip()
        try:
            if text.lower().startswith("0x"):
                value = encode_uint(int(text, 16), 4)
            elif " " in text or ":" in text:
                value = parse_hex_input(text.replace(":", " "))
            else:
                value = encode_uint(int(text, 0), 4)
        except ValueError:
            self.traffic.append_status(tr("can.err", err="bad value"))
            return
        try:
            cob, payload = sdo_write_request(node, index, sub, value)
            self._link.send(cob, payload)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("can.err", err=str(exc)))
            return
        self.traffic.append_status(
            tr("can.sdo_req", op="write", index=f"0x{index:04X}", sub=sub, node=node)
        )

    # -- rx ------------------------------------------------------------

    @staticmethod
    def _peer_of(msg: Any) -> str:
        arb = int(getattr(msg, "arbitration_id", 0))
        if getattr(msg, "is_extended_id", False):
            return f"{arb:08X}"
        return f"{arb:03X}"

    def _on_rx(self, msg: Any) -> None:
        peer = self._peer_of(msg)
        data = bytes(getattr(msg, "data", b"") or b"")
        arb = int(getattr(msg, "arbitration_id", 0))
        ext = bool(getattr(msg, "is_extended_id", False))
        rtr = bool(getattr(msg, "is_remote_frame", False))
        if rtr:
            self.traffic.append_status(f"RX [{peer}] RTR")
        else:
            self.traffic.append_rx(data, peer=peer)
        self._push_lua_frame(arb, data, ext=ext, rtr=rtr)
        self._trace_rx(arb, data, ext=ext, rtr=rtr)
        hb = parse_heartbeat(msg)
        if hb is not None:
            node, state, _name = hb
            import time

            self._hb_nodes[node] = (state, time.monotonic())
        if is_sdo_response(msg):
            result = parse_sdo_response(bytes(getattr(msg, "data", b"") or b""))
            if result.ok:
                pretty = result.data.hex(" ").upper() if result.data else "OK"
                self.traffic.append_status(
                    tr(
                        "can.sdo_resp",
                        index=f"0x{result.index:04X}",
                        sub=result.subindex,
                        value=pretty,
                    )
                )
            else:
                self.traffic.append_status(
                    tr("can.sdo_err", err=result.error or "SDO error")
                )

    def _on_error(self, message: str) -> None:
        self.traffic.append_status(tr("can.err", err=message))
        self._opened = False
        self._set_connected_ui(False)

    def _refresh_hb_table(self) -> None:
        if not self._hb_nodes:
            if self.hb_table.rowCount() != 0:
                self.hb_table.setRowCount(0)
            return
        import time

        now = time.monotonic()
        items = sorted(self._hb_nodes.items())
        self.hb_table.setRowCount(len(items))
        for row, (node, (state, ts)) in enumerate(items):
            age = max(0.0, now - ts)
            state_name = HB_STATES.get(state, f"0x{state:02X}")
            self.hb_table.setItem(row, 0, QTableWidgetItem(str(node)))
            self.hb_table.setItem(row, 1, QTableWidgetItem(tr(f"can.hb.{state_name}")))
            self.hb_table.setItem(row, 2, QTableWidgetItem(f"{age:.1f}s"))
