"""Main application window — loads main_window.ui, owns workers & panels."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools import __app_name__, __version__
from etools.config import get_config, save_config
from etools.core.models import ProbeInfo, ProgressInfo, ProgressStage, TargetInfo
from etools.core.operations import FlashService
from etools.core.pyocd_driver import PyOCDDriver
from etools.i18n import LANG_EN, LANG_ZH, set_language, tr
from etools.logger import get_logger
from etools.ui.styles import apply_combo_style, build_stylesheet, get_theme
from etools.ui.ui_loader import load_form
from etools.ui.widgets.device_manager import DeviceManagerPanel
from etools.ui.widgets.flash_panel import FlashPanel
from etools.ui.widgets.hex_preview import HexPreviewPanel
from etools.ui.widgets.log_panel import LogPanel
from etools.ui.widgets.probe_panel import ProbePanel
from etools.ui.widgets.target_info_panel import TargetInfoPanel

log = get_logger("ui.main")


class _Worker(QObject):
    """Runs a callable in a QThread. Emits finished/failed from that thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
            self.finished.emit(result)
        except Exception as exc:
            log.exception("worker error")
            self.failed.emit(str(exc))


class _OpRunner(QObject):
    """Owns one background QThread at a time.

    IMPORTANT: completion handlers must be QObject *slots* living on the
    GUI thread. Connecting QueuedConnection to a bare Python closure is
    unreliable (no receiver thread affinity) and can run cleanup on the
    worker thread → QThread.wait() on itself → crash (0xC0000409).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._on_ok = None
        self._on_err = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, fn, on_ok, on_err=None) -> bool:
        if self.busy:
            return False
        self._on_ok = on_ok
        self._on_err = on_err

        thread = QThread(self)
        worker = _Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # These are bound methods of _OpRunner (GUI thread affinity).
        worker.finished.connect(self._slot_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._slot_failed, Qt.ConnectionType.QueuedConnection)

        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    def _slot_finished(self, result) -> None:
        self._teardown()
        cb, self._on_ok, self._on_err = self._on_ok, None, None
        if cb is not None:
            cb(result)

    def _slot_failed(self, message: str) -> None:
        self._teardown()
        cb, self._on_err, self._on_ok = self._on_err, None, None
        if cb is not None:
            cb(message)

    def _teardown(self) -> None:
        thread, self._thread = self._thread, None
        worker, self._worker = self._worker, None
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                thread.wait(5000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

    def shutdown(self) -> None:
        thread = self._thread
        worker = self._worker
        self._thread = self._worker = None
        self._on_ok = self._on_err = None
        if worker is not None:
            try:
                worker.finished.disconnect(self._slot_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                worker.failed.disconnect(self._slot_failed)
            except (RuntimeError, TypeError):
                pass
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()


class _ProgressRelay(QObject):
    """Marshal driver progress callbacks from worker threads to the UI thread."""

    progressed = Signal(object)

    def push(self, info: ProgressInfo) -> None:
        # Called from worker thread; Signal emission is thread-safe.
        # Receiver is MainWindow slot with QueuedConnection → GUI thread.
        self.progressed.emit(info)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__}  v{__version__}")

        self.driver = PyOCDDriver()
        self.service = FlashService(self.driver)

        self._relay = _ProgressRelay(self)
        self._relay.progressed.connect(
            self._on_progress_info, Qt.ConnectionType.QueuedConnection
        )
        self.driver.set_progress_callback(self._relay.push)

        self._runner = _OpRunner(self)
        self._last_probe_ids: tuple[str, ...] = ()
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(2500)
        self._probe_timer.timeout.connect(self._hotplug_tick)

        self._build_ui()
        self._wire()
        self._log("ETools 已就绪")

        self._probe_timer.start()
        # First scan immediately
        self._start_scan(silent=True)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Root shell from .ui
        form = load_form("main_window", self)
        self.setCentralWidget(form)
        self.resize(980, 680)
        self.setMinimumSize(980, 680)
        self._build_menu_and_toolbar()

        # No brand top-bar — status goes to QMainWindow status bar
        self.conn_badge = QLabel("未连接")
        self.conn_badge.setObjectName("statusWarn")
        self.statusBar().addWidget(self.conn_badge)
        self.statusBar().setSizeGripEnabled(True)

        # Theme from config (switch via 视图 menu)
        self.apply_theme(get_config().theme or "dark")

        # Progress bar always visible (value 0 when idle)
        self.progress_label: QLabel = form.findChild(QLabel, "progressLabel")
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.setText("")
        self.progress_label.hide()
        self.progress: QProgressBar = form.findChild(QProgressBar, "progressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.progress.show()

        # Left: probe panel fills width of splitter pane
        left_container = form.findChild(QWidget, "leftContainer")
        self.probe_panel = ProbePanel()
        left_layout = left_container.layout()
        if left_layout is None:
            left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        # Expand with left pane; no bottom stretch so it tracks width
        left_layout.addWidget(self.probe_panel, 1)
        self.probe_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        left_scroll = form.findChild(QWidget, "leftScroll")
        if left_scroll is not None:
            from PySide6.QtWidgets import QScrollArea

            if isinstance(left_scroll, QScrollArea):
                left_scroll.setHorizontalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                )
                left_scroll.setWidgetResizable(True)
                left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Right tabs: 固件操作 | 目标信息 | Hex 预览 | 设备管理
        self.flash_panel = FlashPanel()
        self.target_info_panel = TargetInfoPanel()
        self.hex_preview = HexPreviewPanel()
        self.device_manager = DeviceManagerPanel()
        tab_flash = form.findChild(QWidget, "tabFlash")
        tab_info = form.findChild(QWidget, "tabInfo")
        tab_hex = form.findChild(QWidget, "tabHex")
        tab_dev = form.findChild(QWidget, "tabDevices")
        lay_f = tab_flash.layout() or QVBoxLayout(tab_flash)
        lay_f.setContentsMargins(0, 0, 0, 0)
        lay_f.addWidget(self.flash_panel)
        lay_f.addStretch(1)  # keep content top-aligned when height grows
        lay_i = tab_info.layout() or QVBoxLayout(tab_info)
        lay_i.setContentsMargins(0, 0, 0, 0)
        lay_i.addWidget(self.target_info_panel)
        lay_i.addStretch(1)
        lay_h = tab_hex.layout() or QVBoxLayout(tab_hex)
        lay_h.setContentsMargins(0, 0, 0, 0)
        lay_h.addWidget(self.hex_preview)  # hex table fills height
        lay_d = tab_dev.layout() or QVBoxLayout(tab_dev)
        lay_d.setContentsMargins(0, 0, 0, 0)
        lay_d.addWidget(self.device_manager)

        # Compact right panels vertically
        self._compact_form_layout(self.flash_panel._form)
        self._compact_form_layout(self.target_info_panel._form)

        # Log host
        log_host = form.findChild(QWidget, "logPanelHost")
        self.log_panel = LogPanel()
        log_lay = log_host.layout()
        if log_lay is None:
            log_lay = QVBoxLayout(log_host)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.addWidget(self.log_panel)

        # Splitter: left ~260, right takes all extra width when maximized
        splitter = form.findChild(QSplitter, "mainSplitter")
        if splitter is not None:
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([260, 720])
            splitter.setChildrenCollapsible(False)
            splitter.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

        root_lay = form.layout()
        if root_lay is not None:
            root_lay.setStretch(0, 1)  # splitter grows with window
            root_lay.setStretch(1, 0)  # progress
            root_lay.setStretch(2, 0)  # log

        for w in (
            self.probe_panel,
            self.flash_panel,
            self.target_info_panel,
            self.hex_preview,
            self.log_panel,
        ):
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Right pane fills available width (no max cap — maximize should expand it)
        right = form.findChild(QWidget, "rightContainer")
        if right is not None:
            right.setMaximumWidth(16777215)
            right.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

        # Ensure every combo uses triangle arrow + rounded popup
        self._refresh_combo_popups(get_theme(get_config().theme))

        # Default page: 目标信息
        tabs = form.findChild(QTabWidget, "mainTabs")
        if tabs is not None:
            tabs.setCurrentIndex(0)

    def _build_menu_and_toolbar(self) -> None:
        """Menu bar + icon toolbar for firmware / flash actions."""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QToolBar

        st = self.style()

        def act(text: str, icon_sp=None, shortcut: str = "") -> QAction:
            a = QAction(text, self)
            if icon_sp is not None:
                a.setIcon(st.standardIcon(icon_sp))
            if shortcut:
                a.setShortcut(shortcut)
            return a

        mb = self.menuBar()
        mb.setNativeMenuBar(False)
        mb.clear()

        m_file = mb.addMenu(tr("menu.file"))
        a_open = act(tr("act.open"), QStyle.StandardPixmap.SP_DialogOpenButton, "Ctrl+O")
        a_quit = act(tr("act.quit"), QStyle.StandardPixmap.SP_DialogCloseButton, "Ctrl+Q")
        m_file.addAction(a_open)
        m_file.addSeparator()
        m_file.addAction(a_quit)

        m_fw = mb.addMenu(tr("menu.firmware"))
        a_prog = act(tr("act.program"), QStyle.StandardPixmap.SP_DialogApplyButton, "F5")
        a_erase = act(tr("act.erase"), QStyle.StandardPixmap.SP_TrashIcon, "")
        a_verify = act(tr("act.verify"), QStyle.StandardPixmap.SP_DialogYesButton, "")
        a_reset = act(tr("act.reset"), QStyle.StandardPixmap.SP_BrowserReload, "F6")
        a_read_chip = act(tr("act.read_chip"), QStyle.StandardPixmap.SP_ArrowDown, "")
        for a in (a_prog, a_erase, a_verify, a_reset, a_read_chip):
            m_fw.addAction(a)

        m_view = mb.addMenu(tr("menu.view"))
        a_theme_dark = act(tr("act.theme_dark"), None, "")
        a_theme_light = act(tr("act.theme_light"), None, "")
        m_view.addAction(a_theme_dark)
        m_view.addAction(a_theme_light)
        m_view.addSeparator()
        a_hex = act(tr("act.hex"), None, "Ctrl+H")
        m_view.addAction(a_hex)
        m_view.addSeparator()
        m_lang = m_view.addMenu(tr("menu.language"))
        a_lang_zh = act(tr("act.lang_zh"), None, "")
        a_lang_en = act(tr("act.lang_en"), None, "")
        m_lang.addAction(a_lang_zh)
        m_lang.addAction(a_lang_en)

        m_help = mb.addMenu(tr("menu.help"))
        a_about = act(tr("act.about"), QStyle.StandardPixmap.SP_MessageBoxInformation, "")
        m_help.addAction(a_about)

        # rebuild toolbar
        for tb in self.findChildren(QToolBar):
            self.removeToolBar(tb)
        tb = QToolBar(tr("tb.main"), self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        tb.addAction(a_open)
        tb.addSeparator()
        tb.addAction(a_prog)
        tb.addAction(a_erase)
        tb.addAction(a_verify)
        tb.addAction(a_reset)
        tb.addSeparator()
        tb.addAction(a_read_chip)
        tb.addAction(a_hex)

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

    def _switch_language(self, lang: str) -> None:
        set_language(lang)
        self._build_menu_and_toolbar()
        self._retranslate_tabs()
        self.hex_preview.retranslate()
        self.conn_badge.setText(tr("status.disconnected") if not self.service.connected else tr("status.connected"))
        self._log(tr("log.lang_switched"))

    def _retranslate_tabs(self) -> None:
        tabs = self.centralWidget().findChild(QTabWidget, "mainTabs")
        if not tabs:
            return
        keys = ["tab.info", "tab.hex", "tab.flash", "tab.devices"]
        # match by current index order
        for i, key in enumerate(keys):
            if i < tabs.count():
                tabs.setTabText(i, tr(key))

    def _set_theme(self, name: str) -> None:
        self.apply_theme(name)
        cfg = get_config()
        if cfg.theme != name:
            cfg.theme = name
            save_config()
            self._log(tr("log.theme_dark") if name == "dark" else tr("log.theme_light"))

    def _goto_tab(self, keyword: str) -> None:
        tabs = self.centralWidget().findChild(QTabWidget, "mainTabs")
        if not tabs:
            return
        mapping = {
            "Hex": (tr("tab.hex"), "Hex"),
            "info": (tr("tab.info"),),
            "flash": (tr("tab.flash"),),
            "devices": (tr("tab.devices"),),
        }
        needles = mapping.get(keyword, (keyword,))
        for i in range(tabs.count()):
            t = tabs.tabText(i)
            if any(n and n in t for n in needles):
                tabs.setCurrentIndex(i)
                return

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            tr("act.about"),
            tr("about.text", ver=__version__),
        )

    def _toolbar_open_firmware(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from etools.core.models import FIRMWARE_EXTENSIONS

        path, _ = QFileDialog.getOpenFileName(self, "打开固件", "", FIRMWARE_EXTENSIONS)
        if not path:
            return
        self.flash_panel.fw_edit.setText(path)
        # also open hex tab
        self.hex_preview.load_file(path)
        self._goto_tab("Hex")
        self._log(f"已打开 {Path(path).name}")

    def _toolbar_program(self) -> None:
        path = self.flash_panel.firmware_path()
        if not path:
            self._toolbar_open_firmware()
            path = self.flash_panel.firmware_path()
            if not path:
                return
        self._start_program(path, self.flash_panel.verify_check.isChecked())

    def _toolbar_erase(self) -> None:
        self._start_erase()

    def _toolbar_verify(self) -> None:
        path = self.flash_panel.firmware_path()
        if path:
            self._start_verify(path)

    def _toolbar_reset(self) -> None:
        self._start_reset()

    def _toolbar_read_chip(self) -> None:
        self._goto_tab("Hex")
        try:
            addr = int(self.hex_preview.addr_edit.text().strip(), 0)
        except Exception:
            addr = 0x08000000
        size = self.hex_preview._read_size_bytes()
        self._start_read_chip(addr, size)

    @staticmethod
    def _compact_form_layout(form: QWidget) -> None:
        """Tighten a panel form so it hugs content (less empty space)."""
        from PySide6.QtWidgets import QSpacerItem

        lay = form.layout()
        if lay is None:
            return
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        for i in range(lay.count() - 1, -1, -1):
            item = lay.itemAt(i)
            if item is None:
                continue
            sp = item.spacerItem()
            if sp is not None:
                lay.takeAt(i)
        form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def apply_theme(self, name: str) -> None:
        theme = get_theme(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(theme))
        self._refresh_combo_popups(theme)

    def _refresh_combo_popups(self, theme) -> None:
        from PySide6.QtWidgets import QComboBox

        for combo in self.findChildren(QComboBox):
            apply_combo_style(combo, theme)

    def _wire(self) -> None:
        self.probe_panel.connect_requested.connect(self._start_connect)
        self.probe_panel.disconnect_requested.connect(self._do_disconnect)

        self.flash_panel.program_requested.connect(self._start_program)
        self.flash_panel.erase_requested.connect(self._start_erase)
        self.flash_panel.read_requested.connect(self._start_read)
        self.flash_panel.verify_requested.connect(self._start_verify)
        self.flash_panel.reset_requested.connect(self._start_reset)

        self.target_info_panel.refresh_btn.clicked.connect(self._start_refresh_info)

        self.hex_preview.read_chip_requested.connect(self._start_read_chip)
        self.flash_panel.fw_edit.textChanged.connect(self._on_firmware_path_changed)
        self.device_manager.catalog_changed.connect(self._on_catalog_changed)

    def _hotplug_tick(self) -> None:
        """Periodic USB/probe refresh. Skips while another op is running."""
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
        # Log everything except pure idle chatter from scan
        if info.stage != ProgressStage.IDLE or info.is_error:
            self._log(text, info.is_error)

        # Progress bar only for real flash/connect operations — not probe scan
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
        # IDLE: log only; bar stays at 0

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
        # Keep the thin bar visible; just clear the label
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

    # ------------------------------------------------------------------
    # Async runner — handlers are invoked on the GUI thread via _OpRunner slots
    # ------------------------------------------------------------------

    def _run_async(self, fn, on_ok, on_err=None, *, quiet_busy: bool = False) -> bool:
        if self._runner.busy:
            if not quiet_busy:
                self._log("已有操作进行中，请稍候", True)
            return False

        def ok(result) -> None:
            self._set_busy(False)
            on_ok(result)

        def err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()
            if on_err:
                on_err(msg)

        if not self._runner.start(fn, ok, err):
            return False
        self._set_busy(True)
        return True

    def _set_busy(self, busy: bool) -> None:
        self.flash_panel.set_busy(busy)
        # Keep hotplug timer; tick itself skips when runner is busy

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _start_scan(self, silent: bool = False) -> None:
        if self._runner.busy:
            return
        if not silent:
            self._log("正在扫描探针 …")
        self.probe_panel.set_scanning_hint(True)

        def on_ok(probes) -> None:
            probes = probes or []
            ids = tuple(p.unique_id for p in probes)
            if ids != self._last_probe_ids:
                self._last_probe_ids = ids
                if probes:
                    self._log(f"探针列表更新：{len(probes)} 个")
                else:
                    if not silent:
                        self._log("未发现探针，请检查 USB 连接", True)
            self.probe_panel.set_probes(probes)

        def on_err(_msg: str) -> None:
            self.probe_panel.set_probes([])

        self._run_async(self.service.scan_probes, on_ok, on_err, quiet_busy=silent)

    def _start_connect(self, probe: ProbeInfo, target: TargetInfo) -> None:
        self._log(f"连接 {probe.display_name} → {target.target_override} …")
        self.probe_panel.set_connecting()
        self._set_status("连接中…", "warn")
        self._show_progress(0, "连接中…")

        def on_ok(result) -> None:
            if result.ok:
                self.probe_panel.set_connected(True, result.detail or result.message)
                self.flash_panel.set_ops_enabled(True)
                self.hex_preview.set_chip_read_enabled(True)
                self._set_status(f"已连接 · {target.target_override}", "ok")
                self._log(result.message)
                details = getattr(result, "data", None)
                if details is not None:
                    self.target_info_panel.apply(details)
                else:
                    self._start_refresh_info()
            else:
                self.probe_panel.set_error(result.message)
                self.flash_panel.set_ops_enabled(False)
                self.hex_preview.set_chip_read_enabled(False)
                self.target_info_panel.clear()
                self._set_status("连接失败", "err")
                self._log(result.message, True)
                self._hide_progress()

        def on_err(msg: str) -> None:
            self.probe_panel.set_error(msg)
            self.flash_panel.set_ops_enabled(False)
            self.hex_preview.set_chip_read_enabled(False)
            self.target_info_panel.clear()
            self._set_status("连接失败", "err")

        self._run_async(lambda: self.service.connect(probe, target), on_ok, on_err)

    def _do_disconnect(self) -> None:
        try:
            self.service.disconnect()
        except Exception as exc:
            self._log(f"断开异常: {exc}", True)
        self.probe_panel.set_connected(False)
        self.flash_panel.set_ops_enabled(False)
        self.hex_preview.set_chip_read_enabled(False)
        self.target_info_panel.clear()
        self._set_status("未连接", "warn")
        self._hide_progress()
        self._log("已断开")

    def _on_catalog_changed(self) -> None:
        self.probe_panel.reload_targets()
        self._log("设备列表已更新")

    def _on_firmware_path_changed(self, path: str) -> None:
        """Auto-load selected firmware into Hex preview (new sub-page)."""
        path = path.strip()
        if not path or not Path(path).is_file():
            return
        try:
            self.hex_preview.load_file(path)
            self._log(f"Hex 预览已打开 {Path(path).name}")
        except Exception:
            log.exception("hex preview load")

    def _start_read_chip(self, addr: int, size: int) -> None:
        self._show_progress(0, f"读取芯片 0x{addr:08X} …")

        def work():
            data = self.service.read_memory_bytes(addr, size)
            return addr, data

        def on_ok(result) -> None:
            a, data = result
            self.hex_preview.load_bytes(a, data, source=f"芯片 0x{a:08X}")
            self._show_progress(100, f"已读取 {len(data):,} 字节")
            self._log(f"芯片内存已加载到 Hex 预览：0x{a:08X} + {len(data):,} 字节")
            # switch to hex tab
            tabs = self.centralWidget().findChild(QTabWidget, "mainTabs")
            if tabs is not None:
                for i in range(tabs.count()):
                    if "Hex" in tabs.tabText(i):
                        tabs.setCurrentIndex(i)
                        break

        self._run_async(work, on_ok)

    def _start_refresh_info(self) -> None:
        def on_ok(details) -> None:
            self.target_info_panel.apply(details)
            self._log(f"目标信息已更新 — {details.summary_line()}")

        self._run_async(self.service.target_details, on_ok)

    def _start_program(self, path: str, verify: bool) -> None:
        self._show_progress(0, f"烧录 {path} …")
        self._log(f"开始烧录 {path} …")

        def on_ok(result) -> None:
            if result.ok:
                self._show_progress(100, result.message)
                self._log(result.message)
                QMessageBox.information(self, "烧录完成", result.message)
            else:
                self._hide_progress()
                self._log(result.message, True)
                QMessageBox.warning(self, "烧录失败", result.message)

        self._run_async(lambda: self.service.program_file(path, verify), on_ok)

    def _start_erase(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认擦除",
            "将对目标芯片执行全片擦除，此操作不可撤销。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._show_progress(0, "擦除中…")

        def on_ok(result) -> None:
            self._log(result.message, not result.ok)
            if result.ok:
                self._show_progress(100, result.message)
                QMessageBox.information(self, "擦除完成", result.message)
            else:
                self._hide_progress()

        self._run_async(self.service.erase_all, on_ok)

    def _start_read(self, addr: int, size: int, out: str) -> None:
        self._show_progress(0, f"读取 0x{addr:08X} …")

        def on_ok(result) -> None:
            self._log(result.message, not result.ok)
            if result.ok:
                self._show_progress(100, result.message)
                QMessageBox.information(self, "读取完成", result.message)
            else:
                self._hide_progress()

        self._run_async(lambda: self.service.read_flash(addr, size, out), on_ok)

    def _start_verify(self, path: str) -> None:
        self._show_progress(0, "校验中…")

        def on_ok(result) -> None:
            self._log(result.message, not result.ok)
            if result.ok:
                self._show_progress(100, result.message)
                QMessageBox.information(self, "校验通过", result.message)
            else:
                self._hide_progress()
                QMessageBox.warning(self, "校验失败", result.message)

        self._run_async(lambda: self.service.verify_file(path), on_ok)

    def _start_reset(self) -> None:
        def on_ok(result) -> None:
            self._log(result.message, not result.ok)

        self._run_async(lambda: self.service.reset_target(False), on_ok)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        try:
            self._runner.shutdown()
            self.service.disconnect()
        except Exception:
            log.exception("close cleanup")
        super().closeEvent(event)
