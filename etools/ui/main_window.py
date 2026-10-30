"""Main application window — shell + flash service orchestration."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWidget,
)

from etools import __app_name__, __version__
from etools.config import get_config, save_config, take_load_warning
from etools.core.models import ProbeInfo, ProgressInfo, TargetInfo
from etools.core.operations import FlashService
from etools.core.pyocd_driver import PyOCDDriver
from etools.i18n import set_language, tr
from etools.logger import get_logger
from etools.ui.icons import app_icon, refresh_icons, set_action_icon
from etools.ui.runtime import OpRunner, SignalRelay, TaskManager
from etools.ui.shell import ToolShell
from etools.ui.styles import apply_combo_style, build_stylesheet, get_theme
from etools.ui.tools import (
    CanPage,
    DashboardPage,
    EthernetPage,
    MapPage,
    MqttPage,
    ProgramPage,
    ScriptPage,
    SerialPage,
    TerminalPage,
)
from etools.ui.tools.program_controller import ProgramController

log = get_logger("ui.main")


class _TrafficBadge(QWidget):
    """Status-bar RX/TX counter with an inline clear — one visual unit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trafficBadge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stats = QLabel("")
        self.stats.setObjectName("trafficBadgeText")
        self.clear_btn = QPushButton("")
        self.clear_btn.setObjectName("trafficBadgeClear")
        self.clear_btn.setFlat(True)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.stats)
        lay.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_stats_text(self, text: str) -> None:
        self.stats.setText(text)

    def set_clear_text(self, text: str) -> None:
        self.clear_btn.setText(text)

    def set_tip(self, text: str) -> None:
        self.setToolTip(text)
        self.stats.setToolTip(text)
        self.clear_btn.setToolTip(text)


class _UpdateChecker(QObject):
    """Background GitHub Releases lookup."""

    finished = Signal(object)  # UpdateInfo | None

    def run(self) -> None:
        from etools.core.updater import check_for_update

        try:
            self.finished.emit(check_for_update())
        except Exception:
            log.exception("update check crashed")
            self.finished.emit(None)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle(f"{__app_name__}")

        self.driver = PyOCDDriver()
        self.service = FlashService(self.driver)

        self._relay = SignalRelay(self)
        self._relay.progressed.connect(self._on_progress_info, Qt.ConnectionType.QueuedConnection)
        self.driver.set_progress_callback(self._relay.push)

        self._runner = OpRunner(self)
        self.task_manager = TaskManager(self)
        self.task_manager.task_started.connect(self._refresh_task_summary)
        self.task_manager.task_finished.connect(lambda *_: self._refresh_task_summary())
        self.task_manager.task_failed.connect(lambda *_: self._refresh_task_summary())
        self.task_manager.task_cancelled.connect(self._refresh_task_summary)
        self._last_probe_ids: tuple[str, ...] = ()
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(2500)
        self._probe_timer.timeout.connect(self._hotplug_tick)
        self._update_thread: QThread | None = None
        self._update_worker: _UpdateChecker | None = None
        self._update_silent = True

        self._build_ui()
        self._wire()
        self._install_command_palette()
        self._log(tr("app.ready"))
        corrupt = take_load_warning()
        if corrupt:
            self._log(tr("settings.config_corrupt", path=corrupt))
            self.statusBar().showMessage(tr("settings.config_corrupt", path=corrupt), 15000)

        self._probe_timer.start()
        if get_config().auto_probe_scan:
            self._start_scan(silent=True)
        self._schedule_startup_update_check()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.resize(1180, 820)
        self.setMinimumSize(1080, 720)
        self.setWindowIcon(app_icon())
        self._restore_window_geometry()
        self._build_menu()

        self.program_page = ProgramPage()
        self.serial_page = SerialPage()
        self.ethernet_page = EthernetPage()
        self.mqtt_page = MqttPage()
        self.map_page = MapPage()
        self.dashboard_page = DashboardPage()
        self.can_page = CanPage()
        self.terminal_page = TerminalPage()
        self.script_page = ScriptPage()
        # SFTP lives inside the Terminal page (bottom group).
        self.sftp_panel = self.terminal_page.sftp_panel

        # Aliases used by flash wiring / tests
        self.probe_panel = self.program_page.probe_panel
        self.flash_panel = self.program_page.flash_panel
        self.target_info_panel = self.program_page.target_info_panel
        self.hex_preview = self.program_page.hex_preview
        self.device_manager = self.program_page.device_manager
        self.rtt_panel = self.program_page.rtt_panel
        self.swo_panel = self.program_page.swo_panel
        self.variable_monitor = self.program_page.variable_monitor
        self.log_panel = self.program_page.log_panel
        self.progress = self.program_page.progress
        self.progress_label = self.program_page.progress_label
        self.main_tabs = self.program_page.main_tabs

        def _sess():
            return getattr(self.driver, "session", None)

        self.program_page.set_session_getter(_sess)

        self.program_page.set_handlers(
            {
                "open": self._toolbar_open_firmware,
                "program": self._toolbar_program,
                "erase": self._toolbar_erase,
                "verify": self._toolbar_verify,
                "reset": self._toolbar_reset,
                "read": self._toolbar_read_chip,
                "hex": lambda: self._goto_tab("Hex"),
            }
        )

        def program_actions():
            return self.program_page.toolbar_actions()

        def terminal_actions():
            # SFTP actions are already owned by TerminalPage.toolbar_actions()
            return self.terminal_page.toolbar_actions()

        pages = {
            "program": self.program_page,
            "serial": self.serial_page,
            "ethernet": self.ethernet_page,
            "mqtt": self.mqtt_page,
            "map": self.map_page,
            "dash": self.dashboard_page,
            "can": self.can_page,
            "terminal": self.terminal_page,
            "script": self.script_page,
        }
        providers = {
            "program": program_actions,
            "serial": lambda: self.serial_page.toolbar_actions(),
            "ethernet": lambda: self.ethernet_page.toolbar_actions(),
            "mqtt": lambda: self.mqtt_page.toolbar_actions(),
            "map": lambda: self.map_page.toolbar_actions(),
            "dash": lambda: self.dashboard_page.toolbar_actions(),
            "can": lambda: self.can_page.toolbar_actions(),
            "terminal": terminal_actions,
            "script": lambda: self.script_page.toolbar_actions(),
        }
        self.shell = ToolShell(pages, providers, parent=self)
        # Global Lua bridges: scripts can drive any connected tool surface.
        self.script_page.bind_flash(self.service)
        self.script_page.bind_serial(self.serial_page)
        self.script_page.bind_net(self.ethernet_page)
        self.script_page.bind_can(self.can_page)
        self.script_page.bind_term(self.terminal_page)
        self.script_page.bind_frames()
        self.script_page.bind_dash(self.dashboard_page)
        self.script_page.bind_map(self.map_page)
        self.setCentralWidget(self.shell)
        self._restore_tool_widths()

        self.conn_badge = QLabel(tr("status.disconnected"))
        self.conn_badge.setObjectName("statusWarn")
        self.statusBar().addWidget(self.conn_badge)
        self.tool_badge = QLabel(tr("tool.program"))
        self.tool_badge.setObjectName("toolBadge")
        self.statusBar().addWidget(self.tool_badge)
        self.link_badge = QLabel(tr("status.link_idle"))
        self.link_badge.setObjectName("statusWarn")
        self.statusBar().addPermanentWidget(self.link_badge)
        self.traffic_badge = _TrafficBadge()
        self.traffic_badge.set_stats_text(tr("status.traffic_idle"))
        self.traffic_badge.set_clear_text(tr("status.clear_stats"))
        self.traffic_badge.set_tip(tr("status.stats_tip"))
        self.traffic_badge.clear_btn.clicked.connect(self._clear_traffic_stats)
        self.statusBar().addPermanentWidget(self.traffic_badge)
        self.task_badge = QLabel()
        self.task_badge.setObjectName("statusTask")
        self.statusBar().addPermanentWidget(self.task_badge)
        self._refresh_task_summary()
        self.statusBar().setSizeGripEnabled(True)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(400)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start()
        self._refresh_status_bar()
        if hasattr(self.shell, "tool_changed"):
            self.shell.tool_changed.connect(self._on_tool_changed)

        self.apply_theme(get_config().theme or "dark")
        self.program = ProgramController(self)
        self.program_page.bind_tools_host(self.program)

    def _active_page(self):
        tool = self.shell.current_tool
        return {
            "serial": self.serial_page,
            "ethernet": self.ethernet_page,
            "mqtt": self.mqtt_page,
            "can": self.can_page,
            "terminal": self.terminal_page,
        }.get(tool)

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n >= 1_048_576:
            return f"{n / 1_048_576:.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} B"

    def _refresh_status_bar(self) -> None:
        for key, action in getattr(self, "_flash_menu_actions", {}).items():
            control = getattr(self.flash_panel, key + "_btn", None)
            if control is not None:
                action.setEnabled(control.isEnabled())
        page = self._active_page()
        text, kind = tr("status.link_idle"), "warn"
        if page is not None:
            try:
                text, kind = page.link_status()
            except Exception:  # noqa: BLE001 — status bar must never crash
                pass
        self._set_link_badge(text, kind)
        tv = getattr(page, "traffic", None) if page is not None else None
        if tv is not None:
            rx, tx, rxp, txp = tv.stats()
            self.traffic_badge.set_stats_text(
                tr(
                    "status.traffic",
                    rx=self._fmt_bytes(rx),
                    tx=self._fmt_bytes(tx),
                    rxp=rxp,
                    txp=txp,
                )
            )
        else:
            self.traffic_badge.set_stats_text(tr("status.traffic_idle"))

    def _set_link_badge(self, text: str, kind: str = "warn") -> None:
        obj = {"ok": "statusOk", "err": "statusErr", "warn": "statusWarn"}.get(kind, "statusWarn")
        if self.link_badge.text() == text and self.link_badge.objectName() == obj:
            return
        self.link_badge.setText(text)
        self.link_badge.setObjectName(obj)
        st = self.link_badge.style()
        st.unpolish(self.link_badge)
        st.polish(self.link_badge)

    def _clear_traffic_stats(self) -> None:
        page = self._active_page()
        tv = getattr(page, "traffic", None) if page is not None else None
        if tv is not None:
            tv.reset_stats()
        self._refresh_status_bar()

    def _refresh_task_summary(self, *_args) -> None:
        running = sum(1 for info in self.task_manager._tasks.values() if info.runner.busy)
        self.task_badge.setText(tr("task.running", n=running) if running else tr("task.none"))

    def _on_tool_changed(self, tool_id: str) -> None:
        key = f"tool.{tool_id}"
        label = tr(key) if key else tool_id
        self.tool_badge.setText(label)
        self.setWindowTitle(f"{__app_name__}  ·  {label}")

    def _build_menu(self) -> None:
        """Application menu bar only — tool actions live on each tool toolbar."""
        from PySide6.QtGui import QAction

        def act(text: str, icon_name: str | None = None, shortcut: str = "") -> QAction:
            a = QAction(text, self)
            if icon_name:
                set_action_icon(a, icon_name, size=18)
            if shortcut:
                a.setShortcut(shortcut)
            return a

        mb = self.menuBar()
        mb.setNativeMenuBar(False)
        mb.clear()

        m_file = mb.addMenu(tr("menu.file"))
        a_open = act(tr("act.open"), "open", "Ctrl+O")
        a_settings = act(tr("act.settings"), "devices", "Ctrl+Shift+S")
        a_quit = act(tr("act.quit"), "quit", "Ctrl+Q")
        m_file.addAction(a_open)
        a_batch = act(tr("batch.title"), "program", "")
        m_file.addAction(a_batch)
        m_file.addAction(tr("project.title"), self._show_projects)
        m_file.addAction(tr("workflow.title"), self._show_workflow)
        m_file.addSeparator()
        m_file.addAction(a_settings)
        m_file.addSeparator()
        m_file.addAction(a_quit)

        m_fw = mb.addMenu(tr("menu.firmware"))
        a_prog = act(tr("act.program"), "program", "F5")
        a_erase = act(tr("act.erase"), "erase", "")
        a_verify = act(tr("act.verify"), "verify", "")
        a_reset = act(tr("act.reset"), "reset", "F6")
        a_read_chip = act(tr("act.read_chip"), "read", "")
        for a in (a_prog, a_erase, a_verify, a_reset, a_read_chip):
            m_fw.addAction(a)
        self._flash_menu_actions = dict(
            program=a_prog, erase=a_erase, verify=a_verify, reset=a_reset, read=a_read_chip
        )

        m_view = mb.addMenu(tr("menu.view"))
        a_hex = act(tr("act.hex"), "hex", "Ctrl+H")
        from etools.ui.widgets.traffic_view import TrafficView

        a_eye = act(tr("mon.eye_care"))
        a_eye.setCheckable(True)
        a_eye.setChecked(TrafficView._load_eye_care())
        a_eye.setToolTip(tr("mon.eye_care_tip"))
        m_view.addAction(a_hex)
        m_view.addAction(a_eye)
        a_eye.toggled.connect(TrafficView.set_eye_care)

        m_help = mb.addMenu(tr("menu.help"))
        a_check_update = act(tr("act.check_update"), "refresh", "")
        a_guide = act(tr("act.guide"), "info", "")
        a_shortcuts = act(tr("act.shortcuts"), "info", "F1")
        a_about = act(tr("act.about"), "info", "")
        m_help.addAction(a_check_update)
        m_help.addSeparator()
        m_help.addAction(a_guide)
        m_help.addAction(a_shortcuts)
        m_help.addAction(a_about)

        a_open.triggered.connect(self._toolbar_open_firmware)
        a_quit.triggered.connect(self.close)
        a_prog.triggered.connect(self._toolbar_program)
        a_erase.triggered.connect(self._toolbar_erase)
        a_verify.triggered.connect(self._toolbar_verify)
        a_reset.triggered.connect(self._toolbar_reset)
        a_read_chip.triggered.connect(self._toolbar_read_chip)
        a_hex.triggered.connect(lambda: self._goto_tab("Hex"))
        a_about.triggered.connect(self._show_about)
        a_guide.triggered.connect(self._show_guide)
        a_check_update.triggered.connect(lambda: self._check_updates(silent=False))
        a_settings.triggered.connect(self._show_settings)
        a_shortcuts.triggered.connect(self._show_shortcuts)
        a_batch.triggered.connect(self._show_batch_program)

    def _schedule_startup_update_check(self) -> None:
        QTimer.singleShot(1500, self._startup_update_check)

    def _startup_update_check(self) -> None:
        if getattr(self, "_close_approved", False):
            return
        extra = get_config().extra or {}
        if extra.get("auto_check_update", True) is False:
            return
        self._check_updates(silent=True)

    def _check_updates(self, silent: bool = False) -> None:
        if getattr(self, "_close_approved", False):
            return
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        if not silent:
            self._log(tr("update.checking"))

        thread = QThread(self)
        worker = _UpdateChecker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_update_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_update_thread)
        self._update_thread = thread
        self._update_worker = worker
        self._update_silent = silent
        thread.start()

    def _clear_update_thread(self) -> None:
        self._update_thread = None
        self._update_worker = None

    def _on_update_result(self, info) -> None:
        if getattr(self, "_close_approved", False):
            return
        silent = getattr(self, "_update_silent", True)
        if info is None:
            if not silent:
                self._log(tr("update.failed"))
                QMessageBox.information(self, tr("update.title"), tr("update.failed"))
            return

        if not info.is_newer:
            if not silent:
                self._log(tr("update.latest", current=info.current))
                QMessageBox.information(
                    self,
                    tr("update.title"),
                    tr("update.latest", current=info.current),
                )
            return

        self._log(tr("log.update_available", latest=info.latest))
        from etools.ui.widgets.update_dialog import UpdateAvailableDialog

        dlg = UpdateAvailableDialog(info, parent=self)
        dlg.exec()
        if dlg.install_started:
            self._log(tr("log.update_installing"))
        elif dlg.downloaded_path:
            self._log(tr("log.update_downloaded", path=dlg.downloaded_path))

    def _switch_language(self, lang: str) -> None:
        set_language(lang)
        self._build_menu()
        if hasattr(self, "shell"):
            self.shell.apply_language()
        self.program_page.retranslate()
        for page in (
            self.serial_page,
            self.ethernet_page,
            self.mqtt_page,
            self.map_page,
            self.dashboard_page,
            self.can_page,
            self.terminal_page,
            self.script_page,
        ):
            if hasattr(page, "retranslate"):
                page.retranslate()
        connected = self.service.connected
        self.conn_badge.setText(tr("status.connected") if connected else tr("status.disconnected"))
        self.traffic_badge.set_clear_text(tr("status.clear_stats"))
        self.traffic_badge.set_tip(tr("status.stats_tip"))
        self._refresh_status_bar()
        self._refresh_task_summary()
        self._log(tr("log.lang_switched"))

    def _on_only_free_toggled(self, on: bool) -> None:
        page = getattr(self, "serial_page", None)
        if page is not None:
            page.set_only_free(on)

    def _set_theme(self, name: str) -> None:
        self.apply_theme(name)
        cfg = get_config()
        if cfg.theme != name:
            cfg.theme = name
            save_config()
            self._log(tr("log.theme_dark") if name == "dark" else tr("log.theme_light"))

    def _goto_tab(self, keyword: str) -> None:
        self.program_page.goto_tab(keyword)

    def _show_about(self) -> None:
        from etools.core.updater import REPO_URL

        deps = []
        for mod_name, label in (
            ("PySide6", "PySide6"),
            ("serial", "pyserial"),
            ("paramiko", "paramiko"),
            ("pyocd", "pyOCD"),
            ("elftools", "pyelftools"),
            ("lupa", "lupa"),
        ):
            try:
                mod = __import__(mod_name)
                ver = getattr(mod, "__version__", "?")
                deps.append(f"{label} {ver}")
            except Exception:  # noqa: BLE001
                deps.append(f"{label} —")
        try:
            import sys

            py_ver = sys.version.split()[0]
        except Exception:  # noqa: BLE001
            py_ver = "?"
        text = (
            tr("about.text", ver=__version__, github=REPO_URL)
            + "\n\n"
            + tr("about.deps")
            + f":\nPython {py_ver} · "
            + " · ".join(deps)
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("act.about"))
        box.setText(text)
        box.setTextFormat(Qt.TextFormat.PlainText)
        open_btn = box.addButton(tr("about.github"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(REPO_URL))

    def _show_settings(self) -> None:
        from etools.i18n import current_language
        from etools.ui.widgets.settings_dialog import SettingsDialog

        prev_theme = get_config().theme or "dark"
        prev_lang = current_language()
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._toggle_rail_labels(dlg.rail_labels_checked())
            page = getattr(self, "serial_page", None)
            if page is not None:
                page.set_only_free(dlg.only_free_checked())
            theme = dlg.selected_theme()
            lang = dlg.selected_language()
            if theme != prev_theme:
                self._set_theme(theme)
            if lang != prev_lang:
                self._switch_language(lang)
            self._log(tr("settings.applied"))

    def _show_shortcuts(self) -> None:
        from etools.ui.widgets.shortcuts_dialog import ShortcutsDialog

        ShortcutsDialog(self).exec()

    def _show_guide(self) -> None:
        from etools.ui.widgets.guide_dialog import GuideDialog

        dlg = getattr(self, "_guide_dialog", None)
        if dlg is None:
            dlg = GuideDialog(self)
            self._guide_dialog = dlg
            dlg.finished.connect(lambda: setattr(self, "_guide_dialog", None))
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _install_command_palette(self) -> None:
        """Ctrl+K opens a filterable command list (tools + frequent actions)."""
        from PySide6.QtGui import QKeySequence, QShortcut

        sc = QShortcut(QKeySequence("Ctrl+K"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self._open_command_palette)

    def _open_command_palette(self) -> None:
        from etools.ui.widgets.command_palette import CommandPalette

        def go_tool(key: str):
            return lambda: self.shell.set_current_tool(key)

        commands: list[tuple[str, str, object]] = [
            ("tool.program", tr("tool.program"), go_tool("program")),
            ("tool.serial", tr("tool.serial"), go_tool("serial")),
            ("tool.ethernet", tr("tool.ethernet"), go_tool("ethernet")),
            ("tool.mqtt", tr("tool.mqtt"), go_tool("mqtt")),
            ("tool.map", tr("tool.map"), go_tool("map")),
            ("tool.dash", tr("tool.dash"), go_tool("dash")),
            ("tool.can", tr("tool.can"), go_tool("can")),
            ("tool.terminal", tr("tool.terminal"), go_tool("terminal")),
            ("tool.script", tr("tool.script"), go_tool("script")),
            ("act.open", tr("act.open"), self._toolbar_open_firmware),
            ("act.program", tr("act.program"), self._toolbar_program),
            ("act.erase", tr("act.erase"), self._toolbar_erase),
            ("act.verify", tr("act.verify"), self._toolbar_verify),
            ("act.reset", tr("act.reset"), self._toolbar_reset),
            ("act.hex", tr("act.hex"), lambda: self._goto_tab("Hex")),
            ("act.settings", tr("act.settings"), self._show_settings),
            ("act.shortcuts", tr("act.shortcuts"), self._show_shortcuts),
            ("act.guide", tr("act.guide"), self._show_guide),
            ("act.check_update", tr("act.check_update"), lambda: self._check_updates(False)),
            ("act.about", tr("act.about"), self._show_about),
            ("batch.title", tr("batch.title"), self._show_batch_program),
            ("diag.title", tr("diag.title"), self._show_diag),
            ("project.title", tr("project.title"), self._show_projects),
            ("workflow.title", tr("workflow.title"), self._show_workflow),
        ]
        CommandPalette(commands, self).exec()

    def _show_diag(self) -> None:
        from etools.ui.widgets.net_diag_dialog import NetDiagDialog

        NetDiagDialog(self).exec()

    def _toggle_rail_labels(self, checked):
        get_config().extra["rail_labels"] = bool(checked)
        save_config()
        if hasattr(self, "shell"):
            self.shell.set_labels_visible(checked)

    def _show_projects(self):
        from etools.core import project_profiles
        from etools.ui.widgets.project_dialog import ProjectDialog

        def capture():
            for page in (
                self.serial_page,
                self.ethernet_page,
                self.mqtt_page,
                self.map_page,
                self.dashboard_page,
                self.can_page,
                self.terminal_page,
                self.sftp_panel,
            ):
                page.persist_prefs()
            cfg = get_config()
            cfg.default_target = str(self.probe_panel.target_combo.currentData() or "cortex_m")
            cfg.default_connect_mode = str(self.probe_panel.mode_combo.currentData() or "halt")
            cfg.last_firmware = self.flash_panel.firmware_path()
            cfg.verify_after_program = self.flash_panel.verify_check.isChecked()
            cfg.extra["project_script"] = self.script_page.current_script_name
            cfg.extra.update(
                frequency_khz=self.probe_panel.freq_spin.value(),
                wire_protocol=self.probe_panel.protocol_combo.currentData(),
                reset_type=self.probe_panel.reset_combo.currentData(),
            )
            return project_profiles.snapshot()

        def apply(payload):
            if (
                self.service.connected
                or self._runner.busy
                or self.script_page.svc.running
                or any(
                    page.is_open
                    for page in (
                        self.serial_page,
                        self.ethernet_page,
                        self.mqtt_page,
                        self.can_page,
                        self.terminal_page,
                    )
                )
                or self.ethernet_page._runner.busy
                or self.mqtt_page._runner.busy
                or self.terminal_page._runner.busy
            ):
                raise RuntimeError(tr("project.disconnect"))
            if not self.script_page.can_close():
                raise RuntimeError(tr("script.unsaved"))
            blockers = [QSignalBlocker(child) for child in self.findChildren(QWidget)]
            project_profiles.apply_profile(payload)
            cfg = get_config()
            self.flash_panel.fw_edit.setText(cfg.last_firmware)
            self.flash_panel.verify_check.setChecked(cfg.verify_after_program)
            for combo, value in (
                (self.probe_panel.target_combo, cfg.default_target),
                (self.probe_panel.mode_combo, cfg.default_connect_mode),
                (self.probe_panel.protocol_combo, cfg.extra.get("wire_protocol", "swd")),
                (self.probe_panel.reset_combo, cfg.extra.get("reset_type", "default")),
            ):
                idx = combo.findData(value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self.probe_panel.freq_spin.setValue(int(cfg.extra.get("frequency_khz", 10000)))
            for page in (
                self.serial_page,
                self.ethernet_page,
                self.mqtt_page,
                self.map_page,
                self.dashboard_page,
                self.can_page,
                self.terminal_page,
                self.sftp_panel,
            ):
                page._load_prefs()
            del blockers
            if hasattr(self, "_workflow_dialog"):
                self._workflow_dialog.load_settings()
            self.serial_page._update_send_preview()
            self.ethernet_page._update_send_preview()
            name = cfg.extra.get("project_script", "")
            idx = self.script_page.file_combo.findData(name)
            if name and idx >= 0:
                self.script_page.file_combo.setCurrentIndex(idx)
            self.statusBar().showMessage(tr("project.applied"), 5000)

        ProjectDialog(capture, apply, self).exec()

    def _show_workflow(self):
        from etools.ui.widgets.workflow_dialog import WorkflowDialog

        if not hasattr(self, "_workflow_dialog"):
            self._workflow_dialog = WorkflowDialog(self)
        self._workflow_dialog.exec()

    def _show_batch_program(self) -> None:
        from etools.ui.widgets.batch_program_dialog import BatchProgramDialog

        def program_fn(path: str, ok, fail) -> None:
            if not self.service.connected:
                fail(tr("batch.need_connect"))
                return

            def work():
                return self.service.program_file(
                    path, verify=self.flash_panel.verify_check.isChecked()
                )

            def on_ok(result) -> None:
                if getattr(result, "ok", False):
                    self._log(result.message)
                    ok(result)
                else:
                    fail(getattr(result, "message", "program failed"))

            def on_err(msg: str) -> None:
                fail(msg)

            if not self._runner.start(work, on_ok, on_err):
                fail(tr("workflow.preflight"))

        BatchProgramDialog(program_fn, self).exec()

    def _toolbar_open_firmware(self) -> None:
        return self.program._toolbar_open_firmware()

    def _toolbar_program(self) -> None:
        return self.program._toolbar_program()

    def _toolbar_erase(self) -> None:
        return self.program._toolbar_erase()

    def _toolbar_verify(self) -> None:
        return self.program._toolbar_verify()

    def _toolbar_reset(self) -> None:
        return self.program._toolbar_reset()

    def _toolbar_read_chip(self) -> None:
        return self.program._toolbar_read_chip()

    def apply_theme(self, name: str) -> None:
        theme = get_theme(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(theme))
        self._refresh_combo_popups(theme)
        refresh_icons(self, theme)
        if hasattr(self, "shell"):
            self.shell.refresh_rail_icons(theme)

    def _refresh_combo_popups(self, theme) -> None:
        from PySide6.QtWidgets import QComboBox

        for combo in self.findChildren(QComboBox):
            apply_combo_style(combo, theme)

    def _wire(self) -> None:
        return self.program._wire()

    def _hotplug_tick(self) -> None:
        return self.program._hotplug_tick()

    # ------------------------------------------------------------------
    # Progress / logging (UI thread)
    # ------------------------------------------------------------------

    def _on_progress_info(self, info: ProgressInfo) -> None:
        return self.program._on_progress_info(info)

    def _show_progress(self, percent: int, label: str = "") -> None:
        return self.program._show_progress(percent, label)

    def _hide_progress(self) -> None:
        return self.program._hide_progress()

    def _log(self, message: str, is_error: bool = False) -> None:
        return self.program._log(message, is_error)

    def _set_status(self, text: str, kind: str = "warn") -> None:
        return self.program._set_status(text, kind)

    @property
    def runner(self):
        """Primary UI background runner (public for dialogs/workflows)."""
        return self._runner

    @property
    def workflow_active(self) -> bool:
        return bool(getattr(self, "_workflow_active", False))

    @workflow_active.setter
    def workflow_active(self, value: bool) -> None:
        self._workflow_active = bool(value)

    def set_busy(self, busy: bool) -> None:
        """Reflect flash-panel busy state (public for dialogs/workflows)."""
        self._set_busy(busy)

    def _run_async(self, fn, on_ok, on_err=None, *, quiet_busy: bool = False) -> bool:
        return self.program._run_async(fn, on_ok, on_err, quiet_busy=quiet_busy)

    def _set_busy(self, busy: bool) -> None:
        return self.program._set_busy(busy)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _start_scan(self, silent: bool = False) -> None:
        return self.program._start_scan(silent)

    def _start_connect(self, probe: ProbeInfo, target: TargetInfo) -> None:
        return self.program._start_connect(probe, target)

    def _auto_preview_chip(self, details: object | None) -> None:
        return self.program._auto_preview_chip(details)

    def _do_disconnect(self) -> None:
        return self.program._do_disconnect()

    def _on_catalog_changed(self) -> None:
        return self.program._on_catalog_changed()

    def _on_firmware_path_changed(self, path: str) -> None:
        return self.program._on_firmware_path_changed(path)

    def _start_read_chip(self, addr: int, size: int) -> None:
        return self.program._start_read_chip(addr, size)

    def _start_program(self, path: str, verify: bool = True) -> None:
        return self.program._start_program(path, verify)

    def _start_erase(self) -> None:
        return self.program._start_erase()

    def _start_erase_range(self, address: int, size: int) -> None:
        return self.program._start_erase_range(address, size)

    def _start_read(self, address: int, size: int, out_path: str) -> None:
        return self.program._start_read(address, size, out_path)

    def _start_verify(self, path: str) -> None:
        return self.program._start_verify(path)

    def _start_reset(self) -> None:
        return self.program._start_reset()

    def _start_refresh_info(self) -> None:
        return self.program._start_refresh_info()

    def _start_fill_ram(self, addr: int, size: int, value: int) -> None:
        return self.program._start_fill_ram(addr, size, value)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.workflow_active:
            self._workflow_dialog._stop()
            event.ignore()
            return
        if not getattr(self, "_close_approved", False) and not self.script_page.can_close():
            event.ignore()
            return
        self._close_approved = True
        self._probe_timer.stop()
        runners = [
            self._runner,
            self.ethernet_page._runner,
            self.mqtt_page._runner,
            self.can_page._runner,
            self.serial_page._open_runner,
            self.terminal_page._runner,
            self.sftp_panel._runner,
        ]
        serial_runner = getattr(self.serial_page, "_runner", None)
        if serial_runner is not None:
            runners.append(serial_runner)
        update_running = self._update_thread is not None and self._update_thread.isRunning()
        tasks_running = self.task_manager.any_running()
        if any(runner.busy for runner in runners) or update_running or tasks_running:
            self.setEnabled(False)
            for runner in runners:
                runner.cancel()
            self.task_manager.cancel_all()
            self.terminal_page._ssh.close()
            self.ethernet_page._connect_cancel.set()
            self.statusBar().showMessage(tr("connection.closing"))
            event.ignore()
            QTimer.singleShot(150, self.close)
            return
        try:
            self._status_timer.stop()
            self._save_geometry()
            # The shell owns every tool page, so each page's shutdown runs once.
            self.task_manager.shutdown()
            if hasattr(self, "shell"):
                self.shell.shutdown()
            self._runner.shutdown()
        except Exception:
            log.exception("shutdown error")
        super().closeEvent(event)

    def _restore_window_geometry(self) -> None:
        from PySide6.QtCore import QByteArray

        extra = get_config().extra or {}
        raw = extra.get("window_geometry")
        if isinstance(raw, str) and raw:
            try:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
            except Exception:  # noqa: BLE001
                pass

    def _restore_tool_widths(self) -> None:
        widths = (get_config().extra or {}).get("tool_left_widths") or {}
        if not isinstance(widths, dict):
            return
        pages = {
            "program": getattr(self, "program_page", None),
            "serial": getattr(self, "serial_page", None),
            "ethernet": getattr(self, "ethernet_page", None),
            "mqtt": getattr(self, "mqtt_page", None),
            "map": getattr(self, "map_page", None),
            "dash": getattr(self, "dashboard_page", None),
            "can": getattr(self, "can_page", None),
            "terminal": getattr(self, "terminal_page", None),
            "script": getattr(self, "script_page", None),
        }
        for key, page in pages.items():
            w = widths.get(key)
            if page is not None and isinstance(w, int) and w > 0:
                page.set_left_width(w)

    def _save_geometry(self) -> None:
        import base64

        cfg = get_config()
        extra = dict(cfg.extra or {})
        extra["window_geometry"] = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        widths = {}
        for key, page in (
            ("program", getattr(self, "program_page", None)),
            ("serial", getattr(self, "serial_page", None)),
            ("ethernet", getattr(self, "ethernet_page", None)),
            ("mqtt", getattr(self, "mqtt_page", None)),
            ("map", getattr(self, "map_page", None)),
            ("dash", getattr(self, "dashboard_page", None)),
            ("can", getattr(self, "can_page", None)),
            ("terminal", getattr(self, "terminal_page", None)),
            ("script", getattr(self, "script_page", None)),
        ):
            if page is not None and hasattr(page, "left_width"):
                widths[key] = int(page.left_width)
        extra["tool_left_widths"] = widths
        cfg.extra = extra
        save_config()
