"""Serial port debug assistant page (pyserial + hotplug)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.core.checksum import ALGORITHMS, compute_checksum
from etools.core.serial_link import (
    PORT_BUSY,
    PORT_ERROR,
    PORT_OK,
    SerialLink,
    list_serial_ports,
)
from etools.core.trigger_reply import TriggerEngine
from etools.i18n import tr
from etools.ui.runtime import OpRunner
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import LinkToolPage
from etools.ui.tools.serial_quicksend import SerialQuickSendMixin
from etools.ui.tools.serial_transfer import SerialTransferMixin
from etools.ui.tools.serial_worktabs import SerialWorkTabsMixin
from etools.ui.widgets.send_edit import SendEdit
from etools.ui.widgets.traffic_view import ENCODINGS, TrafficView, decode_payload, parse_hex_input

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
    "1000000",
    "1500000",
    "2000000",
    "3000000",
]

#: How many ad-hoc baud rates to remember beyond the fixed presets.
_CUSTOM_BAUD_MAX = 8

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


class SerialPage(
    SerialTransferMixin,
    SerialQuickSendMixin,
    SerialWorkTabsMixin,
    LinkToolPage,
):
    tool_id = "serial"
    tool_title_key = "tool.serial"

    def _build(self) -> None:
        self._link = SerialLink()
        self._open_runner = OpRunner(self)
        self._scan_runner = OpRunner(self)
        self._scan_pending = False
        self._relay = _RxRelay(self)
        self._relay.received.connect(self._on_rx)
        self._relay.failed.connect(self._on_link_error)
        self._link.set_handlers(
            on_rx=self._relay.received.emit,
            on_error=self._relay.failed.emit,
        )
        self._opened = False
        self._user_closed = True
        self._known_ports: tuple[str, ...] = ()
        self._history: list[str] = []
        self._history_idx = -1
        self._custom_bauds: list[str] = []
        self._only_free = True
        self._xfer_cancel = False
        self._reconnect_delay_ms = 500
        self._resume_cyclic = False
        self._trigger = TriggerEngine()
        self._reconfig_timer = QTimer(self)
        self._reconfig_timer.setSingleShot(True)
        self._reconfig_timer.setInterval(300)
        self._reconfig_timer.timeout.connect(self._apply_live_params)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

        self.ctx_params = self.ctx_group(tr("serial.params"))
        self.port_combo = _PortCombo()
        self.port_combo.setFixedHeight(28)
        self.port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lbl_port = self.form_row(tr("serial.port"), self.port_combo)
        # Port names are filled later and are often long.
        self.expand_field(self.port_combo)

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

        self.encoding = QComboBox()
        for value, label in ENCODINGS:
            self.encoding.addItem(label, value)
        self.encoding.setFixedHeight(28)
        self.lbl_encoding = self.form_row(tr("mon.encoding"), self.encoding)

        self.auto_reconnect = QCheckBox(tr("serial.auto_reconnect"))
        self.auto_reconnect.setToolTip(tr("serial.auto_reconnect_tip"))
        self.auto_reconnect.setChecked(True)
        self.lbl_reconnect = self.form_row("", self.auto_reconnect)

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
        self.lbl_mode = QLabel(tr("serial.send_mode"))
        self.rx_mode = QComboBox()
        self.rx_mode.addItem(tr("serial.mode.ascii"), "ascii")
        self.rx_mode.addItem(tr("serial.mode.hex"), "hex")
        self.rx_mode.setFixedHeight(28)
        self.lbl_rx_mode = QLabel(tr("serial.receive_mode"))
        self.ending = QComboBox()
        self.ending.addItem(tr("serial.ending.crlf"), "crlf")
        self.ending.addItem(tr("serial.ending.lf"), "lf")
        self.ending.addItem(tr("serial.ending.cr"), "cr")
        self.ending.addItem(tr("serial.ending.none"), "none")
        self.ending.setFixedHeight(28)
        self.lbl_ending = QLabel(tr("serial.ending"))
        self.checksum = QComboBox()
        for algo in ALGORITHMS:
            self.checksum.addItem(tr(f"serial.checksum.{algo}"), algo)
        self.checksum.setFixedHeight(28)
        self.lbl_checksum = QLabel(tr("serial.checksum"))
        self.checksum_preview = QLabel("")
        self.checksum_preview.setObjectName("mutedLabel")
        self.rx_verify = QCheckBox(tr("serial.rx_verify"))
        self.rx_verify.setChecked(True)
        self.history_btn = QPushButton(tr("serial.history"))
        self.history_btn.setObjectName("ghost")
        self.history_btn.setFixedHeight(28)
        self.history_btn.setFixedWidth(80)
        self._build_transfer_controls()
        self.send_edit = SendEdit()
        self.send_edit.setPlaceholderText(tr("serial.send_ph"))
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("accent")
        self.send_btn.setFixedHeight(30)
        self.send_btn.setEnabled(False)
        self.preset_import_btn = QPushButton(tr("serial.presets_import"))
        self.preset_import_btn.setObjectName("ghost")
        self.preset_import_btn.setFixedHeight(28)
        self.preset_import_btn.setFixedWidth(80)
        self.preset_export_btn = QPushButton(tr("serial.presets_export"))
        self.preset_export_btn.setObjectName("ghost")
        self.preset_export_btn.setFixedHeight(28)
        self.preset_export_btn.setFixedWidth(80)

        self._build_presets()
        self._build_triggers()
        self._build_cyclic()

        # The text box and Send stay on their own row. Format controls share
        # the folded option rows.
        option_row = QHBoxLayout()
        option_row.setSpacing(6)
        for lbl_w, field in (
            (self.lbl_mode, self.mode_combo),
            (self.lbl_ending, self.ending),
            (self.lbl_rx_mode, self.rx_mode),
            (self.lbl_checksum, self.checksum),
        ):
            self.align_combo(field)
            option_row.addWidget(lbl_w)
            option_row.addWidget(field)
        option_row.addWidget(self.rx_verify)
        option_row.addWidget(self.checksum_preview)
        option_row.addWidget(self.history_btn)
        option_row.addStretch(1)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)
        self.preset_import_btn.setToolTip(tr("serial.presets_io"))
        self.preset_export_btn.setToolTip(tr("serial.presets_io"))
        self.align_combo(self.xfer_proto)
        self.align_combo(self.xmode_combo)
        for widget in (
            self.cyclic_check,
            self.lbl_interval,
            self.cyclic_interval,
            self.xfer_proto,
            self.xmode_combo,
            self.ymodem_btn,
            self.ymodem_recv_btn,
            self.preset_import_btn,
            self.preset_export_btn,
        ):
            tool_row.addWidget(widget)
        tool_row.addStretch(1)

        self.send_more_toggle = QCheckBox(tr("serial.send_options"))
        self.send_more_toggle.setChecked(False)
        self.send_more = QWidget()
        self.send_more.setVisible(False)
        self.send_more_toggle.toggled.connect(self.send_more.setVisible)
        more_lay = QVBoxLayout(self.send_more)
        more_lay.setContentsMargins(0, 0, 0, 0)
        more_lay.setSpacing(4)
        more_lay.addLayout(option_row)
        more_lay.addLayout(tool_row)

        send_row.setSpacing(6)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        xfer_row = QHBoxLayout()
        xfer_row.setSpacing(6)
        xfer_row.addWidget(self.xfer_progress, 1)
        xfer_row.addWidget(self.xfer_cancel_btn)
        meta_wrap = QVBoxLayout()
        meta_wrap.setSpacing(4)
        meta_wrap.addLayout(send_row)
        meta_wrap.addWidget(self.send_more_toggle)
        meta_wrap.addWidget(self.send_more)
        meta_wrap.addLayout(xfer_row)
        self.install_send_preview(meta_wrap)
        mon_lay.addWidget(self.traffic, 1)
        from etools.ui.widgets.section_tabs import SectionTabs
        from etools.ui.widgets.studio_plot import StudioPlotPanel

        self.studio = StudioPlotPanel()
        self.section_tabs = SectionTabs()
        self.section_tabs.add_page(tr("serial.plot"), self.studio, tr("serial.plot_tip"))
        self.section_tabs.add_page(
            tr("serial.presets"), self.preset_content, tr("serial.presets_toggle_tip")
        )
        self.section_tabs.add_page(
            tr("serial.trigger"), self.trigger_content, tr("serial.trigger_tip")
        )
        mon_lay.addWidget(self.section_tabs)
        mon_lay.addLayout(meta_wrap)
        self.work_tabs.addTab(mon_box, tr("serial.monitor"))

        self._build_terminal_tab()

        self._build_script_tab()

        self.open_btn.clicked.connect(self._on_toggle)
        self.send_btn.clicked.connect(self._on_send)
        self.send_edit.submitted.connect(self._on_send)
        self.send_edit.installEventFilter(self)
        self.history_btn.clicked.connect(self._show_history)
        self.ymodem_btn.clicked.connect(self._on_ymodem_send)
        self.ymodem_recv_btn.clicked.connect(self._on_ymodem_recv)
        self.xfer_cancel_btn.clicked.connect(self._cancel_transfer)
        self.terminal_view.send_bytes.connect(self._terminal_send)
        self.terminal_break.clicked.connect(self._send_break)
        self.terminal_clear.clicked.connect(self.terminal_view.clear)
        self.port_combo.about_to_show.connect(lambda: self._refresh_ports(probe=True))
        self.cyclic_check.toggled.connect(self._on_cyclic_toggled)
        self.cyclic_interval.valueChanged.connect(self._on_interval_changed)
        self.script_run.clicked.connect(self._on_script_run)
        self.script_stop.clicked.connect(self._on_script_stop)
        self.preset_import_btn.clicked.connect(self._import_presets)
        self.preset_export_btn.clicked.connect(self._export_presets)
        self.auto_reconnect.toggled.connect(lambda _c: self.persist_prefs())
        self.preset_shortcuts.toggled.connect(self._on_preset_shortcuts_toggled)
        for widget in (self.baud, self.data, self.parity, self.stop, self.flow):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._schedule_live_reconfig)
                if widget.isEditable():
                    widget.editTextChanged.connect(self._schedule_live_reconfig)

        self._hotplug = QTimer(self)
        self._hotplug.setInterval(2000)
        self._hotplug.timeout.connect(self._hotplug_tick)
        self._hotplug.start()

        self.retranslate()
        self._refresh_ports()
        self._load_prefs()
        for combo in (
            self.baud,
            self.data,
            self.parity,
            self.stop,
            self.flow,
            self.ending,
            self.mode_combo,
            self.encoding,
        ):
            combo.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.encoding.currentIndexChanged.connect(self._on_encoding_changed)
        self.rx_mode.currentIndexChanged.connect(self._on_rx_mode_changed)
        self.rx_mode.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.baud.currentTextChanged.connect(lambda _t: self.persist_prefs())
        self.port_combo.currentIndexChanged.connect(lambda _i: self.persist_prefs())
        self.dtr.toggled.connect(lambda _c: self._apply_modem())
        self.rts.toggled.connect(lambda _c: self._apply_modem())
        self.checksum.currentIndexChanged.connect(self._on_checksum_changed)
        self.send_edit.textChanged.connect(self._refresh_checksum_preview)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._refresh_checksum_preview())

    def _on_checksum_changed(self, _index: int = 0) -> None:
        self._refresh_checksum_preview()
        self.persist_prefs()

    def _refresh_checksum_preview(self, *_args) -> None:
        algo = str(self.checksum.currentData() or "none")
        text = self.send_edit.text()
        if algo == "none" or not text:
            self.checksum_preview.setText("")
            return
        try:
            if self.mode_combo.currentData() == "hex":
                body = parse_hex_input(text)
            else:
                body = text.encode(self._encoding_name())
        except ValueError:
            self.checksum_preview.setText("")
            return
        field = compute_checksum(body, algo)
        self.checksum_preview.setText(field.hex(" ").upper() if field else "")

    def _encoding_name(self) -> str:
        return str(self.encoding.currentData() or "utf-8")

    def _on_encoding_changed(self) -> None:
        name = self._encoding_name()
        self.traffic.set_encoding(name)
        self.persist_prefs()

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
        self.lbl_encoding.setText(tr("mon.encoding"))
        self.dtr.setText(tr("serial.dtr"))
        self.rts.setText(tr("serial.rts"))
        self.auto_reconnect.setText(tr("serial.auto_reconnect"))
        self.auto_reconnect.setToolTip(tr("serial.auto_reconnect_tip"))
        self.open_btn.setText(tr("serial.close") if self._opened else tr("serial.open"))
        self.send_more_toggle.setText(tr("serial.send_options"))
        self.mon_box.setTitle(tr("serial.monitor"))
        self.work_tabs.setTabText(0, tr("serial.monitor"))
        self.work_tabs.setTabText(1, tr("serial.terminal"))
        self.local_echo.setText(tr("serial.terminal.local_echo"))
        self.terminal_break.setText(tr("serial.terminal.break"))
        self.terminal_clear.setText(tr("mon.clear"))
        self.traffic.retranslate()
        self.studio.retranslate()
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
        self.lbl_checksum.setText(tr("serial.checksum"))
        self.rx_verify.setText(tr("serial.rx_verify"))
        for i, algo in enumerate(ALGORITHMS):
            self.checksum.setItemText(i, tr(f"serial.checksum.{algo}"))
        self.history_btn.setText(tr("serial.history"))
        self._relabel_xfer_buttons()
        self.xmode_combo.setItemText(0, tr("serial.xmode_crc"))
        self.xmode_combo.setItemText(1, tr("serial.xmode_checksum"))
        self.xmode_combo.setToolTip(tr("serial.xmode_tip"))
        self.xfer_cancel_btn.setText(tr("serial.xfer_cancel"))
        self.section_tabs.set_title(0, tr("serial.plot"), tr("serial.plot_tip"))
        self.section_tabs.set_title(1, tr("serial.presets"), tr("serial.presets_toggle_tip"))
        self.section_tabs.set_title(2, tr("serial.trigger"), tr("serial.trigger_tip"))
        self.preset_shortcuts.setText(tr("serial.preset_shortcuts"))
        self.preset_shortcuts.setToolTip(tr("serial.preset_shortcuts_tip"))
        self.cyclic_check.setToolTip(tr("serial.cyclic_tip"))
        self.preset_import_btn.setToolTip(tr("serial.presets_io"))
        self.preset_export_btn.setToolTip(tr("serial.presets_io"))
        for i, edit in enumerate(self._preset_edits):
            edit.setPlaceholderText(tr("serial.presets_ph", n=i + 1))
        for check in self._preset_checks:
            check.setToolTip(tr("serial.cycle_pick"))
        for btn in self._preset_btns:
            btn.setText(tr("serial.send"))
        self.cyclic_check.setText(tr("serial.cyclic"))
        self.lbl_interval.setText(tr("serial.cyclic_interval"))
        self.preset_import_btn.setText(tr("serial.presets_import"))
        self.preset_export_btn.setText(tr("serial.presets_export"))
        for mode in self._trigger_modes:
            mode.setItemText(0, tr("serial.trigger_mode.text"))
            mode.setItemText(1, tr("serial.trigger_mode.hex"))
            mode.setItemText(2, tr("serial.trigger_mode.regex"))
        for enable in self._trigger_enables:
            enable.setToolTip(tr("serial.trigger_enable"))
        for pattern in self._trigger_patterns:
            pattern.setPlaceholderText(tr("serial.trigger_pattern_ph"))
        for reply in self._trigger_replies:
            reply.setPlaceholderText(tr("serial.trigger_reply_ph"))
        for hex_check in self._trigger_hex:
            hex_check.setText(tr("serial.mode.hex"))
        for once in self._trigger_onces:
            once.setText(tr("serial.trigger_once"))
        self.work_tabs.setTabText(2, tr("serial.script"))
        self.script_run.setText(tr("serial.script.run"))
        self.script_stop.setText(tr("serial.script.stop"))
        if not self._script_running:
            self.script_status.setText(tr("serial.script.idle"))
        self.script_edit.setPlaceholderText(tr("serial.script.placeholder"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("toggle", "serial.open", "connect", self.toggle_connection),
            ToolActionSpec("send", "serial.send", "program", self.send),
            ToolActionSpec("run_script", "script.run_menu", "hex", self._run_script_menu),
            ToolActionSpec("modbus", "modbus.title", "compare", self._open_modbus),
            ToolActionSpec("clear", "mon.clear", "clear", self.clear_view, separator_before=True),
        ]

    def _open_modbus(self) -> None:
        from etools.ui.widgets.modbus_dialog import ModbusDialog

        def send(frame: bytes) -> None:
            if not self._opened:
                self.traffic.append_status(tr("serial.cyclic_need_open"))
                return
            try:
                self._link.write(frame)
            except Exception as exc:  # noqa: BLE001
                self.traffic.append_status(tr("serial.err", err=str(exc)))
                return
            self.traffic.append_tx(frame)

        ModbusDialog(send, self).exec()

    def _run_script_menu(self) -> None:
        from etools.ui.tools.script_menu import exec_script_menu

        exec_script_menu(self)

    @property
    def is_open(self) -> bool:
        return self._opened

    def link_status(self) -> tuple[str, str]:
        if not self._opened:
            return tr("status.link_idle"), "warn"
        return tr("status.link_serial", port=self._selected_port() or "?"), "ok"

    def toggle_connection(self) -> None:
        self._on_toggle()

    def clear_view(self) -> None:
        self.traffic.clear()

    def _load_prefs(self) -> None:
        self._loading_prefs = True
        prefs = load_tool_prefs(self.tool_id)
        custom = prefs.get("custom_bauds")
        if isinstance(custom, list):
            self._custom_bauds = [str(x) for x in custom if str(x).strip()][:_CUSTOM_BAUD_MAX]
            self._apply_baud_presets()
        if prefs.get("baud"):
            self.baud.setCurrentText(str(prefs["baud"]))
        if prefs.get("only_free") is not None:
            self._only_free = bool(prefs["only_free"])
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
        if prefs.get("checksum"):
            idx = self.checksum.findData(str(prefs["checksum"]))
            if idx >= 0:
                self.checksum.setCurrentIndex(idx)
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
        if prefs.get("encoding"):
            idx = self.encoding.findData(str(prefs["encoding"]))
            if idx >= 0:
                self.encoding.setCurrentIndex(idx)
        if prefs.get("auto_reconnect") is not None:
            self.auto_reconnect.setChecked(bool(prefs["auto_reconnect"]))
        if prefs.get("preset_shortcuts") is not None:
            self.preset_shortcuts.setChecked(bool(prefs["preset_shortcuts"]))
        if prefs.get("triggers") is not None:
            self._trigger.load_rules(prefs.get("triggers"))
            self._apply_trigger_rules_to_ui()
        self._on_preset_shortcuts_toggled(self.preset_shortcuts.isChecked())
        self.traffic.set_encoding(self._encoding_name())
        self._loading_prefs = False

    def persist_prefs(self) -> None:
        if getattr(self, "_loading_prefs", False):
            return
        self._sync_trigger_rules(persist=False)
        save_tool_prefs(
            self.tool_id,
            {
                "port": self._selected_port(),
                "baud": self.baud.currentText(),
                "custom_bauds": list(self._custom_bauds),
                "only_free": self._only_free,
                "databits": self.data.currentText(),
                "parity": self.parity.currentText(),
                "stopbits": self.stop.currentText(),
                "flow": self.flow.currentData(),
                "ending": self.ending.currentData(),
                "checksum": self.checksum.currentData(),
                "send_mode": self.mode_combo.currentData(),
                "receive_mode": self.rx_mode.currentData(),
                "dtr": self.dtr.isChecked(),
                "rts": self.rts.isChecked(),
                "presets": [e.text() for e in self._preset_edits],
                "preset_cycle": [c.isChecked() for c in self._preset_checks],
                "cyclic_interval": int(self.cyclic_interval.value()),
                "encoding": self._encoding_name(),
                "auto_reconnect": self.auto_reconnect.isChecked(),
                "preset_shortcuts": self.preset_shortcuts.isChecked(),
                "triggers": self._trigger.dump_rules(),
            },
        )

    def _hotplug_tick(self) -> None:
        devices = tuple(e.device for e in list_serial_ports())
        if devices != self._known_ports:
            vanished = self._opened and self._selected_port() not in devices
            self._known_ports = devices
            self._refresh_ports_async()
            if vanished:
                self._handle_unexpected_disconnect(tr("serial.port_lost"))
        elif (
            not self._opened
            and not self._user_closed
            and self.auto_reconnect.isChecked()
            and self._selected_port()
            and self._selected_port() in devices
            and not self._reconnect_timer.isActive()
        ):
            self._schedule_reconnect(immediate=True)

    @property
    def only_free(self) -> bool:
        return self._only_free

    def set_only_free(self, on: bool) -> None:
        """Toggle 「仅显示可用串口」 from the View menu (not the param form)."""
        if self._only_free == bool(on):
            return
        self._only_free = bool(on)
        self.persist_prefs()
        self._refresh_ports_async()

    def _remember_baud(self, text: str) -> None:
        """Keep ad-hoc baud rates in the preset list across sessions."""
        value = (text or "").strip()
        if not value or value in _BAUDS:
            return
        if value in self._custom_bauds:
            return
        self._custom_bauds.insert(0, value)
        del self._custom_bauds[_CUSTOM_BAUD_MAX:]
        self.baud.blockSignals(True)
        if self.baud.findText(value) < 0:
            self.baud.addItem(value)
        self.baud.blockSignals(False)

    def _apply_baud_presets(self) -> None:
        """Rebuild the baud combo: fixed presets + remembered custom values."""
        current = self.baud.currentText()
        self.baud.blockSignals(True)
        self.baud.clear()
        self.baud.addItems(_BAUDS)
        for value in self._custom_bauds:
            if value not in _BAUDS and self.baud.findText(value) < 0:
                self.baud.addItem(value)
        if current:
            self.baud.setCurrentText(current)
        self.baud.blockSignals(False)

    def _set_params_enabled(self, enabled: bool) -> None:
        """Port selection stays locked while open; line settings remain editable."""
        self.port_combo.setEnabled(enabled)
        for w in (self.baud, self.data, self.parity, self.stop, self.flow):
            w.setEnabled(True)

    def _refresh_ports(self, *, probe: bool = True) -> None:
        self._apply_port_list(list_serial_ports(probe=probe or self._only_free))

    def _refresh_ports_async(self) -> None:
        """Probe ports on a worker: probing opens each port and can take seconds."""
        if self._scan_runner.busy:
            self._scan_pending = True
            return
        self._scan_pending = False

        def done(ports) -> None:
            self._apply_port_list(ports)
            if self._scan_pending:
                self._refresh_ports_async()

        def fail(_message: str) -> None:
            self._refresh_ports(probe=False)

        self._scan_runner.start(lambda: list_serial_ports(probe=True), done, fail)

    def _apply_port_list(self, ports) -> None:
        only_free = self._only_free
        self._known_ports = tuple(e.device for e in ports)
        current_data = self.port_combo.currentData()
        current_text = self.port_combo.currentText()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        active = self._selected_port() if self._opened else ""
        rows: list[tuple[str, str]] = []
        for entry in ports:
            if entry.device == active:
                status = tr("serial.port_self")
            elif entry.status == PORT_OK:
                status = tr("serial.port_ok")
            elif entry.status == PORT_BUSY:
                status = tr("serial.port_busy")
            elif entry.status == PORT_ERROR:
                status = tr("serial.port_error")
            else:
                status = ""
            if only_free and entry.device != active and entry.status != PORT_OK:
                continue
            label = entry.label if not status else f"{entry.label}  [{status}]"
            rows.append((label, entry.device))
        if not rows:
            self.port_combo.addItem("—")
        else:
            for label, device in rows:
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
        self.ymodem_btn.setEnabled(enabled)
        self.ymodem_recv_btn.setEnabled(enabled)
        for btn in self._preset_btns:
            btn.setEnabled(enabled)
        self.send_btn.setObjectName("accent" if enabled else "ghost")
        st = self.send_btn.style()
        st.unpolish(self.send_btn)
        st.polish(self.send_btn)

    def _on_toggle(self) -> None:
        if self._open_runner.busy:
            return
        if self._opened:
            self._user_closed = True
            self._resume_cyclic = False
            self._cancel_reconnect()
            self._mark_closed(status=tr("serial.closed"))
            return
        self._user_closed = False
        self._cancel_reconnect()
        self._reconnect_delay_ms = 500
        self._open_selected_port()

    def _open_selected_port(
        self, *, quiet: bool = False, on_done: Callable[[bool], None] | None = None
    ) -> bool:
        """Open the selected port on a worker thread. Returns False if not started."""
        port = self._selected_port()
        if not port:
            if not quiet:
                self.traffic.append_status(tr("serial.open_no_port"))
            return False
        if self._open_runner.busy:
            return False
        link = self._link
        params = dict(
            port=port,
            baudrate=int(self.baud.currentText() or 115200),
            bytesize=int(self.data.currentText() or 8),
            parity=self.parity.currentText() or "N",
            stopbits=float(self.stop.currentText() or 1),
            flow_control=str(self.flow.currentData() or "none"),
        )
        dtr, rts = self.dtr.isChecked(), self.rts.isChecked()

        def work():
            # Bluetooth / USB-CDC drivers can block for seconds inside open().
            link.open(**params)
            link.set_dtr(dtr)
            link.set_rts(rts)

        def ok(_result) -> None:
            self.open_btn.setEnabled(True)
            if self._user_closed:
                link.close()
                self.open_btn.setText(tr("serial.open"))
                if on_done:
                    on_done(False)
                return
            self._on_port_opened(port)
            if on_done:
                on_done(True)

        def fail(message: str) -> None:
            link.close()
            self.open_btn.setEnabled(True)
            self.open_btn.setText(tr("serial.open"))
            if not quiet:
                self.traffic.append_status(tr("serial.err", err=message))
            if on_done:
                on_done(False)

        self.open_btn.setEnabled(False)
        self.open_btn.setText(tr("status.connecting"))
        return self._open_runner.start(work, ok, fail)

    def _on_port_opened(self, port: str) -> None:
        self._opened = True
        self._user_closed = False
        self._reconnect_delay_ms = 500
        self._trigger.reset_runtime()
        self._set_send_enabled(True)
        self._set_params_enabled(False)
        self._remember_baud(self.baud.currentText())
        self.open_btn.setText(tr("serial.close"))
        self._repaint_btn()
        self.traffic.append_status(tr("serial.opened", port=port))
        self.notify_state()
        if self._resume_cyclic:
            self._resume_cyclic = False
            self.cyclic_check.blockSignals(True)
            self.cyclic_check.setChecked(True)
            self.cyclic_check.blockSignals(False)
            self._on_cyclic_toggled(True)

    def _mark_closed(self, *, status: str | None = None, keep_cyclic: bool = False) -> None:
        self._reconfig_timer.stop()
        if keep_cyclic and self.cyclic_check.isChecked():
            self._resume_cyclic = True
        self._stop_cyclic()
        if self._script_running:
            self._on_script_stop()
        self._link.close()
        self._opened = False
        self._set_send_enabled(False)
        self._set_params_enabled(True)
        self.open_btn.setText(tr("serial.open"))
        self._repaint_btn()
        if status:
            self.traffic.append_status(status)

    def _handle_unexpected_disconnect(self, reason: str) -> None:
        self._user_closed = False
        self._mark_closed(status=reason, keep_cyclic=True)
        if self.auto_reconnect.isChecked():
            self.traffic.append_status(tr("serial.reconnect_pending"))
            self._schedule_reconnect()

    def _cancel_reconnect(self) -> None:
        self._reconnect_timer.stop()

    def _schedule_reconnect(self, *, immediate: bool = False) -> None:
        if self._user_closed or not self.auto_reconnect.isChecked() or self._opened:
            return
        delay = 0 if immediate else max(100, int(self._reconnect_delay_ms))
        self._reconnect_timer.start(delay)

    def _try_reconnect(self) -> None:
        if (
            self._user_closed
            or not self.auto_reconnect.isChecked()
            or self._opened
            or self._open_runner.busy
        ):
            return
        port = self._selected_port()
        if not port:
            return
        devices = {e.device for e in list_serial_ports()}
        if port not in devices:
            self._schedule_reconnect()
            return
        self.traffic.append_status(tr("serial.reconnect_try", port=port))

        def finished(ok: bool) -> None:
            if ok:
                self.traffic.append_status(tr("serial.reconnect_ok", port=port))
                return
            self._reconnect_delay_ms = min(8000, max(500, self._reconnect_delay_ms * 2))
            self.traffic.append_status(
                tr("serial.reconnect_wait", ms=self._reconnect_delay_ms)
            )
            self._schedule_reconnect()

        self._open_selected_port(quiet=True, on_done=finished)

    def _schedule_live_reconfig(self, *_args) -> None:
        if not self._opened:
            return
        self._reconfig_timer.start()

    def _apply_live_params(self) -> None:
        if not self._opened:
            return
        try:
            self._link.reconfigure(
                baudrate=int(self.baud.currentText() or 115200),
                bytesize=int(self.data.currentText() or 8),
                parity=self.parity.currentText() or "N",
                stopbits=float(self.stop.currentText() or 1),
                flow_control=str(self.flow.currentData() or "none"),
            )
            self._link.set_dtr(self.dtr.isChecked())
            self._link.set_rts(self.rts.isChecked())
            self._remember_baud(self.baud.currentText())
            self.traffic.append_status(
                tr(
                    "serial.reconfigured",
                    baud=self.baud.currentText(),
                    data=self.data.currentText(),
                    parity=self.parity.currentText(),
                    stop=self.stop.currentText(),
                )
            )
            self.persist_prefs()
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            self._handle_unexpected_disconnect(tr("serial.reconfigure_failed"))

    def _encode_payload(self, text: str, *, force_hex: bool = False) -> bytes | None:
        mode = "hex" if force_hex or self.mode_combo.currentData() == "hex" else "ascii"
        try:
            return self.link.encode_payload(
                text,
                mode=mode,
                encoding=self._encoding_name(),
                ending=str(self.ending.currentData() or "crlf"),
                checksum=str(self.checksum.currentData() or "none"),
            )
        except ValueError:
            self.traffic.append_status(tr("serial.err", err="bad hex"))
            return None

    def _send_payload(
        self, text: str, *, record_history: bool = False, force_hex: bool = False
    ) -> bool:
        if not text or not self._opened:
            return False
        data = self._encode_payload(text, force_hex=force_hex)
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

    def _on_rx(self, data: bytes) -> None:
        self._script_rx.extend(data)
        if len(self._script_rx) > 65536:
            del self._script_rx[:-65536]
        self._maybe_verify_rx(data)
        self.traffic.append_rx(data)
        frames: list[dict[str, float]] = []
        if hasattr(self, "studio"):
            frames = self.studio.feed(data)
            from etools.core.frame_hub import frame_hub

            frame_hub.configure(
                "serial",
                self.studio.parse_mode_name(),
                self.studio.names.text(),
                self.studio.hex_template_text(),
            )
            if frames:
                frame_hub.publish_frames("serial", frames)
        for hit in self._trigger.feed(data, encoding=self._encoding_name()):
            ok = self._send_payload(
                hit.rule.reply,
                record_history=False,
                force_hex=bool(hit.rule.reply_hex),
            )
            self.traffic.append_status(
                tr(
                    "serial.trigger_fired",
                    n=hit.index + 1,
                    ok=tr("serial.trigger_sent") if ok else tr("serial.trigger_send_fail"),
                )
            )
        self._terminal_write(decode_payload(data, self._encoding_name()))

    # -- Lua / bridge helpers ------------------------------------------

    def lua_opened(self) -> bool:
        return bool(self._opened)

    def lua_send_text(self, text: str, force_hex: bool = False) -> bool:
        return self._send_payload(text, record_history=True, force_hex=force_hex)

    def lua_write(self, raw: bytes) -> bool:
        if not self._opened:
            return False
        try:
            self._link.write(bytes(raw))
            self.traffic.append_tx(bytes(raw))
            return True
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.err", err=str(exc)))
            return False

    def _reveal_plot(self) -> None:
        """Open the plot the first time a script draws. Later frames stay put."""
        tabs = getattr(self, "section_tabs", None)
        already = (
            tabs is not None
            and tabs._buttons
            and tabs._buttons[0].isChecked()
            and (not hasattr(self, "work_tabs") or self.work_tabs.currentIndex() == 0)
        )
        if already:
            return
        if hasattr(self, "work_tabs"):
            self.work_tabs.setCurrentIndex(0)
        if tabs is not None:
            tabs.show_page(0)
        parent = self.parent()
        while parent is not None:
            show = getattr(parent, "set_current_tool", None)
            if callable(show):
                show(self.tool_id)
                break
            parent = parent.parent()

    def lua_plot(self, kind: str, payload) -> int:
        if not hasattr(self, "studio"):
            return 0
        self._reveal_plot()
        frames = self.studio.accept_script(kind, payload)
        if frames:
            from etools.core.frame_hub import frame_hub

            frame_hub.publish_frames("serial", frames)
        return len(frames)

    def lua_take_rx(self, max_bytes: int = 4096) -> bytes:
        n = max(0, int(max_bytes))
        data = bytes(self._script_rx[:n])
        del self._script_rx[:n]
        return data

    def _maybe_verify_rx(self, data: bytes) -> None:
        """Heuristic RX frame check: chunk ends with a matching checksum trailer."""
        from etools.core.checksum import checksum_width, compute_checksum, verify_checksum

        if not self.rx_verify.isChecked():
            return
        algo = str(self.checksum.currentData() or "none")
        width = checksum_width(algo)
        if algo == "none" or len(data) <= width:
            return
        if verify_checksum(data, algo):
            self.traffic.append_status(tr("serial.rx_crc_ok"))
        else:
            want = compute_checksum(data[:-width], algo).hex(" ").upper()
            self.traffic.append_status(tr("serial.rx_crc_bad", want=want))

    def _on_rx_mode_changed(self, _index: int = 0) -> None:
        self.traffic.set_display_mode(str(self.rx_mode.currentData() or "ascii"))

    def _on_link_error(self, message: str) -> None:
        self._handle_unexpected_disconnect(tr("serial.err", err=message))

    def shutdown(self) -> None:
        self.traffic.shutdown()
        self._hotplug.stop()
        self._cancel_reconnect()
        self._reconfig_timer.stop()
        self._cyclic_timer.stop()
        self._script_timer.stop()
        self._script_running = False
        self._xfer_cancel = True
        self._user_closed = True
        runner = getattr(self, "_runner", None)
        if runner is not None:
            runner.cancel()
            runner.shutdown()
        self._open_runner.shutdown()
        self._scan_runner.shutdown()
        self.persist_prefs()
        self._link.close()
