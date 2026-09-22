"""Main application window — shell + flash service orchestration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from etools import __app_name__, __version__
from etools.config import get_config, save_config
from etools.core.models import ProbeInfo, ProgressInfo, ProgressStage, TargetInfo
from etools.core.operations import FlashService
from etools.core.pyocd_driver import PyOCDDriver
from etools.i18n import LANG_EN, LANG_ZH, set_language, tr
from etools.logger import get_logger
from etools.ui.icons import app_icon, refresh_icons, set_action_icon
from etools.ui.runtime import OpRunner, SignalRelay, TaskManager
from etools.ui.shell import ToolShell
from etools.ui.styles import apply_combo_style, build_stylesheet, get_theme
from etools.ui.tools import (
    EthernetPage,
    ProgramPage,
    SerialPage,
    TerminalPage,
)

log = get_logger("ui.main")


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
        self.setWindowTitle(f"{__app_name__}  v{__version__}")

        self.driver = PyOCDDriver()
        self.service = FlashService(self.driver)

        self._relay = SignalRelay(self)
        self._relay.progressed.connect(
            self._on_progress_info, Qt.ConnectionType.QueuedConnection
        )
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
        self._log(tr("app.ready"))

        self._probe_timer.start()
        self._start_scan(silent=True)
        self._schedule_startup_update_check()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.resize(1180, 820)
        self.setMinimumSize(1080, 720)
        self.setWindowIcon(app_icon())
        self._build_menu()

        self.program_page = ProgramPage()
        self.serial_page = SerialPage()
        self.ethernet_page = EthernetPage()
        self.terminal_page = TerminalPage()
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
            "terminal": self.terminal_page,
        }
        providers = {
            "program": program_actions,
            "serial": lambda: self.serial_page.toolbar_actions(),
            "ethernet": lambda: self.ethernet_page.toolbar_actions(),
            "terminal": terminal_actions,
        }
        self.shell = ToolShell(pages, providers, parent=self)
        self.setCentralWidget(self.shell)

        self.conn_badge = QLabel(tr("status.disconnected"))
        self.conn_badge.setObjectName("statusWarn")
        self.statusBar().addWidget(self.conn_badge)
        self.task_badge = QLabel()
        self.task_badge.setObjectName("statusTask")
        self.statusBar().addPermanentWidget(self.task_badge)
        self._refresh_task_summary()
        self.statusBar().setSizeGripEnabled(True)

        self.apply_theme(get_config().theme or "dark")

    def _refresh_task_summary(self, *_args) -> None:
        running = sum(1 for info in self.task_manager._tasks.values() if info.runner.busy)
        self.task_badge.setText(tr("task.running", n=running) if running else tr("task.none"))

    def _build_menu(self) -> None:
        """Application menu bar only — tool actions live on each tool toolbar."""
        from PySide6.QtGui import QAction, QActionGroup

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
        a_quit = act(tr("act.quit"), "quit", "Ctrl+Q")
        m_file.addAction(a_open)
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

        m_view = mb.addMenu(tr("menu.view"))
        m_theme = m_view.addMenu(tr("menu.theme"))
        current_theme_name = (get_config().theme or "dark").lower()
        a_theme_dark = act(tr("act.theme_dark"), "theme-dark", "")
        a_theme_light = act(tr("act.theme_light"), "theme-light", "")
        a_theme_dark.setCheckable(True)
        a_theme_light.setCheckable(True)
        a_theme_dark.setChecked(current_theme_name == "dark")
        a_theme_light.setChecked(current_theme_name == "light")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        theme_group.addAction(a_theme_dark)
        theme_group.addAction(a_theme_light)
        m_theme.addAction(a_theme_dark)
        m_theme.addAction(a_theme_light)
        m_view.addSeparator()
        a_hex = act(tr("act.hex"), "hex", "Ctrl+H")
        m_view.addAction(a_hex)
        m_view.addSeparator()
        m_lang = m_view.addMenu(tr("menu.language"))
        a_lang_zh = act(tr("act.lang_zh"), "language", "")
        a_lang_en = act(tr("act.lang_en"), "language", "")
        a_lang_zh.setCheckable(True)
        a_lang_en.setCheckable(True)
        from etools.i18n import current_language

        cur_lang = current_language()
        a_lang_zh.setChecked(cur_lang == LANG_ZH)
        a_lang_en.setChecked(cur_lang == LANG_EN)
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        lang_group.addAction(a_lang_zh)
        lang_group.addAction(a_lang_en)
        m_lang.addAction(a_lang_zh)
        m_lang.addAction(a_lang_en)

        m_help = mb.addMenu(tr("menu.help"))
        a_check_update = act(tr("act.check_update"), "refresh", "")
        a_about = act(tr("act.about"), "info", "")
        m_help.addAction(a_check_update)
        m_help.addSeparator()
        m_help.addAction(a_about)

        a_open.triggered.connect(self._toolbar_open_firmware)
        a_quit.triggered.connect(self.close)
        a_prog.triggered.connect(self._toolbar_program)
        a_erase.triggered.connect(self._toolbar_erase)
        a_verify.triggered.connect(self._toolbar_verify)
        a_reset.triggered.connect(self._toolbar_reset)
        a_read_chip.triggered.connect(self._toolbar_read_chip)
        a_theme_dark.triggered.connect(lambda: self._set_theme("dark"))
        a_theme_light.triggered.connect(lambda: self._set_theme("light"))
        a_hex.triggered.connect(lambda: self._goto_tab("Hex"))
        a_lang_zh.triggered.connect(lambda: self._switch_language(LANG_ZH))
        a_lang_en.triggered.connect(lambda: self._switch_language(LANG_EN))
        a_about.triggered.connect(self._show_about)
        a_check_update.triggered.connect(lambda: self._check_updates(silent=False))

    def _schedule_startup_update_check(self) -> None:
        QTimer.singleShot(1500, self._startup_update_check)

    def _startup_update_check(self) -> None:
        self._check_updates(silent=True)

    def _check_updates(self, silent: bool = False) -> None:
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
            self.terminal_page,
        ):
            if hasattr(page, "retranslate"):
                page.retranslate()
        connected = self.service.connected
        self.conn_badge.setText(
            tr("status.connected") if connected else tr("status.disconnected")
        )
        self._refresh_task_summary()
        self._log(tr("log.lang_switched"))

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

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("act.about"))
        box.setText(tr("about.text", ver=__version__, github=REPO_URL))
        box.setTextFormat(Qt.TextFormat.PlainText)
        open_btn = box.addButton(tr("about.github"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(REPO_URL))

    def _toolbar_open_firmware(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from etools.core.models import FIRMWARE_EXTENSIONS

        path, _ = QFileDialog.getOpenFileName(self, tr("act.open"), "", FIRMWARE_EXTENSIONS)
        if not path:
            return
        self.flash_panel.fw_edit.setText(path)
        self.hex_preview.load_file(path)
        self._goto_tab("Hex")
        self._log(tr("log.firmware_opened", name=Path(path).name))

    def _toolbar_program(self) -> None:
        path = self.flash_panel.firmware_path()
        if not path:
            self._toolbar_open_firmware()
            path = self.flash_panel.firmware_path()
            if not path:
                return
        self._start_program(path, self.flash_panel.verify_check.isChecked())

    def _toolbar_erase(self) -> None:
        ret = QMessageBox.warning(
            self,
            tr("confirm.erase_all_title"),
            tr("confirm.erase_all_text"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ret == QMessageBox.StandardButton.Ok:
            self._start_erase()

    def _toolbar_verify(self) -> None:
        path = self.flash_panel.firmware_path()
        if path:
            self._start_verify(path)

    def _toolbar_reset(self) -> None:
        self._start_reset()

    def _toolbar_read_chip(self) -> None:
        self._goto_tab("Hex")
        addr = int(self.hex_preview.addr_spin.value())
        size = self.hex_preview._read_size_bytes()
        self._start_read_chip(addr, size)

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
        self.probe_panel.connect_requested.connect(self._start_connect)
        self.probe_panel.disconnect_requested.connect(self._do_disconnect)

        self.flash_panel.program_requested.connect(self._start_program)
        self.flash_panel.erase_requested.connect(self._start_erase)
        self.flash_panel.erase_range_requested.connect(self._start_erase_range)
        self.flash_panel.read_requested.connect(self._start_read)
        self.flash_panel.verify_requested.connect(self._start_verify)
        self.flash_panel.reset_requested.connect(self._start_reset)

        self.target_info_panel.refresh_btn.clicked.connect(self._start_refresh_info)

        self.hex_preview.read_chip_requested.connect(self._start_read_chip)
        self.hex_preview.fill_requested.connect(self._start_fill_ram)
        self.flash_panel.fw_edit.textChanged.connect(self._on_firmware_path_changed)
        self.device_manager.catalog_changed.connect(self._on_catalog_changed)

    def _hotplug_tick(self) -> None:
        if self._runner.busy:
            return
        self._start_scan(silent=True)

    # ------------------------------------------------------------------
    # Progress / logging (UI thread)
    # ------------------------------------------------------------------

    def _on_progress_info(self, info: ProgressInfo) -> None:
        text = info.message or info.stage.value
        extra = info.format_bytes
        if extra:
            text = f"{text}  ({extra})"
        if info.stage != ProgressStage.IDLE or info.is_error:
            self._log(text, info.is_error)

        flash_stages = (
            ProgressStage.PROGRAM,
            ProgressStage.ERASE,
            ProgressStage.READ,
            ProgressStage.VERIFY,
            ProgressStage.CONNECT,
        )
        if info.stage == ProgressStage.DONE:
            self._show_progress(100, text)
        elif info.is_error or info.stage == ProgressStage.ERROR:
            self._hide_progress()
        elif info.stage in flash_stages:
            if info.indeterminate:
                self.progress.setRange(0, 0)
                self.progress_label.setText(text)
                self.progress_label.show()
                self.progress.show()
            else:
                self._show_progress(info.percent, text)

    def _show_progress(self, percent: int, label: str = "") -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percent)))
        self.progress.show()
        if label:
            self.progress_label.setText(label)
            self.progress_label.show()
        else:
            self.progress_label.hide()

    def _hide_progress(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_label.hide()
        self.progress.show()

    def _log(self, message: str, is_error: bool = False) -> None:
        self.log_panel.append(message, is_error)
        if is_error:
            log.error(message)
        else:
            log.info(message)

    def _set_status(self, text: str, kind: str = "warn") -> None:
        obj = {"ok": "statusOk", "err": "statusErr", "warn": "statusWarn"}.get(
            kind, "statusWarn"
        )
        self.conn_badge.setText(text)
        self.conn_badge.setObjectName(obj)
        st = self.conn_badge.style()
        st.unpolish(self.conn_badge)
        st.polish(self.conn_badge)

    def _run_async(self, fn, on_ok, on_err=None, *, quiet_busy: bool = False) -> bool:
        def ok(result) -> None:
            self._set_busy(False)
            on_ok(result)

        def err(msg: str) -> None:
            self._set_busy(False)
            if not quiet_busy:
                self._log(msg, True)
            self._hide_progress()
            if on_err:
                on_err(msg)

        if not self._runner.start(fn, ok, err):
            return False
        if not quiet_busy:
            self._set_busy(True)
        return True

    def _set_busy(self, busy: bool) -> None:
        self.flash_panel.set_busy(busy)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _start_scan(self, silent: bool = False) -> None:
        if self._runner.busy:
            return
        if not silent:
            self._log(tr("log.scan_probes"))
            self.probe_panel.set_scanning_hint(True)

        def on_ok(probes) -> None:
            probes = probes or []
            ids = tuple(p.unique_id for p in probes)
            if ids != self._last_probe_ids:
                self._last_probe_ids = ids
                if probes:
                    self._log(tr("log.probe_list", n=len(probes)))
                else:
                    if not silent:
                        self._log(tr("log.probe_none"), True)
            self.probe_panel.set_probes(probes)

        def on_err(_msg: str) -> None:
            self.probe_panel.set_probes([])

        self._run_async(self.service.scan_probes, on_ok, on_err, quiet_busy=silent)

    def _start_connect(self, probe: ProbeInfo, target: TargetInfo) -> None:
        self._log(
            tr(
                "log.connecting",
                probe=probe.display_name,
                target=target.target_override,
            )
        )
        self.probe_panel.set_connecting()
        self._set_status(tr("status.probe_connecting"), "warn")
        self._show_progress(0, tr("status.probe_connecting"))

        def on_ok(result) -> None:
            if result.ok:
                self.probe_panel.set_connected(True, result.detail or result.message)
                self.flash_panel.set_ops_enabled(True)
                self.hex_preview.set_chip_read_enabled(True)
                self.rtt_panel.set_connected(True)
                self.swo_panel.set_connected(True)
                details_for_flash = getattr(result, "data", None)
                if details_for_flash is not None and getattr(
                    details_for_flash, "flash_size", 0
                ):
                    self.hex_preview._flash_size_hint = int(details_for_flash.flash_size)
                else:
                    self.hex_preview._flash_size_hint = 0
                self._set_status(tr("log.connected", target=target.target_override), "ok")
                self._log(result.message)
                details = getattr(result, "data", None)
                if details is not None:
                    self.target_info_panel.apply(details)
                else:
                    self._start_refresh_info()
                self._auto_preview_chip(details)
            else:
                self.probe_panel.set_error(result.message)
                self.flash_panel.set_ops_enabled(False)
                self.hex_preview.set_chip_read_enabled(False)
                self.target_info_panel.clear()
                self._set_status(tr("status.failed"), "err")
                self._log(result.message, True)
                self._hide_progress()

        def on_err(msg: str) -> None:
            self.probe_panel.set_error(msg)
            self.flash_panel.set_ops_enabled(False)
            self.hex_preview.set_chip_read_enabled(False)
            self.target_info_panel.clear()
            self._set_status(tr("status.failed"), "err")

        self._run_async(lambda: self.service.connect(probe, target), on_ok, on_err)

    def _auto_preview_chip(self, details: object | None) -> None:
        addr = 0x0800_0000
        size = 0x1000
        if details is not None:
            base = int(getattr(details, "flash_base", 0) or 0)
            flash_size = int(getattr(details, "flash_size", 0) or 0)
            if base:
                addr = base
            if flash_size:
                size = min(0x1000, flash_size)
        try:
            self.hex_preview.addr_spin.setValue(addr)
            self.hex_preview.size_spin.setValue(size)
        except Exception:
            log.debug("sync hex spins failed", exc_info=True)
        self._log(tr("log.hex_loading", addr=f"{addr:08X}", size=f"{size:,}"))
        self._start_read_chip(addr, size)

    def _do_disconnect(self) -> None:
        try:
            self.service.disconnect()
        except Exception as exc:
            self._log(tr("log.disconnect_err", err=str(exc)), True)
        self.probe_panel.set_connected(False)
        self.flash_panel.set_ops_enabled(False)
        self.hex_preview.set_chip_read_enabled(False)
        self.rtt_panel.set_connected(False)
        self.swo_panel.set_connected(False)
        self.target_info_panel.clear()
        self._set_status(tr("status.disconnected"), "warn")
        self._hide_progress()
        self._log(tr("log.disconnected"))

    def _on_catalog_changed(self) -> None:
        self.probe_panel.reload_targets()
        self._log(tr("log.devices_updated"))

    def _on_firmware_path_changed(self, path: str) -> None:
        path = path.strip()
        if not path or not Path(path).is_file():
            return
        try:
            self.hex_preview.load_file(path)
            self._log(tr("log.hex_loaded", name=Path(path).name))
        except Exception:
            log.exception("hex preview load")

    def _start_read_chip(self, addr: int, size: int) -> None:
        self._show_progress(0, tr("log.chip_read", addr=f"0x{addr:08X}"))

        def work():
            data = self.service.read_memory_bytes(addr, size)
            return addr, data

        def on_ok(result) -> None:
            a, data = result
            self.hex_preview.load_bytes(a, data, source=None)
            self._show_progress(100, tr("log.chip_read_done", size=f"{len(data):,}"))

        def on_err(msg: str) -> None:
            self._log(msg, True)
            self._hide_progress()

        self._run_async(work, on_ok, on_err)

    def _start_program(self, path: str, verify: bool = True) -> None:
        self._show_progress(0, tr("log.programming"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            if result.ok:
                self._show_progress(100, result.message or "OK")
            else:
                self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        if not self._run_async(
            lambda: self.service.program_file(path, verify=verify), on_ok, on_err
        ):
            self._log(tr("log.busy"), True)

    def _start_erase(self) -> None:
        self._show_progress(0, tr("log.erasing"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(self.service.erase_all, on_ok, on_err)

    def _start_erase_range(self, address: int, size: int) -> None:
        self._show_progress(0, tr("log.erasing_range"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(lambda: self.service.erase_range(address, size), on_ok, on_err)

    def _start_read(self, address: int, size: int, out_path: str) -> None:
        self._show_progress(0, tr("log.reading"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(
            lambda: self.service.read_flash(address, size, out_path), on_ok, on_err
        )

    def _start_verify(self, path: str) -> None:
        self._show_progress(0, tr("log.verifying"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(lambda: self.service.verify_file(path), on_ok, on_err)

    def _start_reset(self) -> None:
        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)

        self._run_async(lambda: self.service.reset_target(halt=False), on_ok, on_err)

    def _start_refresh_info(self) -> None:
        def on_ok(details) -> None:
            self.target_info_panel.apply(details)

        def on_err(msg: str) -> None:
            self._log(msg, True)

        self._run_async(self.service.target_details, on_ok, on_err, quiet_busy=True)

    def _start_fill_ram(self, addr: int, size: int, value: int) -> None:
        self._show_progress(0, tr("log.filling"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(
            lambda: self.service.fill_memory(addr, size, value), on_ok, on_err
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if hasattr(self, "shell"):
                self.shell.shutdown()
            self.rtt_panel.shutdown()
            self.swo_panel.shutdown()
            self._runner.shutdown()
        except Exception:
            log.exception("shutdown error")
        super().closeEvent(event)
