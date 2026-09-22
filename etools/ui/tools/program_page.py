"""Program (MCU flash) workspace — same ToolPage shell language as other tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.ui.icons import set_tab_icon
from etools.ui.shell import ToolActionSpec
from etools.ui.tools.base import ToolPage
from etools.ui.widgets.device_manager import DeviceManagerPanel
from etools.ui.widgets.flash_panel import FlashPanel
from etools.ui.widgets.hex_preview import HexPreviewPanel
from etools.ui.widgets.log_panel import LogPanel
from etools.ui.widgets.probe_panel import ProbePanel
from etools.ui.widgets.rtt_panel import RttPanel
from etools.ui.widgets.swo_panel import SwvPanel
from etools.ui.widgets.target_info_panel import TargetInfoPanel

_TAB_KEYS = ("hex", "program", "devices", "rtt", "swv")
_TAB_I18N = ("tab.hex", "tab.flash", "tab.devices", "tab.rtt", "tab.swo")


class ProgramPage(ToolPage):
    """Left probe rail + right flash tabs + bottom progress/log."""

    tool_id = "program"
    tool_title_key = "tool.program"

    def _build(self) -> None:
        self._handlers: dict[str, Callable[[], Any]] = {}

        self.probe_panel = ProbePanel()
        self.flash_panel = FlashPanel()
        self.target_info_panel = TargetInfoPanel()
        self.hex_preview = HexPreviewPanel()
        self.device_manager = DeviceManagerPanel()
        self.rtt_panel = RttPanel()
        self.swo_panel = SwvPanel()
        self.log_panel = LogPanel()

        # Left context: one GroupBox wrapping probe + target info.
        scroll = self.splitter.widget(0)
        left_box = QGroupBox(tr("probe.group"))
        left_box.setObjectName("ctxGroup")
        self.left_box = left_box
        left_lay = QVBoxLayout(left_box)
        left_lay.setContentsMargins(8, 8, 8, 8)
        left_lay.setSpacing(6)
        left_lay.addWidget(self.probe_panel, 0)
        sep = QFrame()
        sep.setObjectName("leftGroupSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedHeight(1)
        left_lay.addWidget(sep)
        left_lay.addWidget(self.target_info_panel, 1)
        for panel in (self.probe_panel, self.target_info_panel):
            title = panel._form.findChild(QLabel, "panelTitle")
            if title is not None:
                title.hide()
            panel._form.setStyleSheet(
                "QWidget#panel { border: none; background: transparent; }"
            )
        if isinstance(scroll, QScrollArea):
            scroll.setWidget(left_box)
        else:
            self.splitter.insertWidget(0, left_box)
        self.set_left_width(260)

        # Right: tabs + progress/log
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("mainTabs")
        tabs_spec = [
            ("tabHex", self.hex_preview),
            ("tabFlash", self.flash_panel),
            ("tabDevices", self.device_manager),
            ("tabRtt", self.rtt_panel),
            ("tabSwo", self.swo_panel),
        ]
        for obj_name, widget in tabs_spec:
            page = QWidget()
            page.setObjectName(obj_name)
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(widget, 1)
            self.main_tabs.addTab(page, "")

        bottom = QWidget()
        bottom.setObjectName("programBottom")
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 6, 0, 0)
        bottom_lay.setSpacing(6)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.hide()
        self.progress = QProgressBar()
        self.progress.setObjectName("progressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        self.progress.show()
        bottom_lay.addWidget(self.progress_label)
        bottom_lay.addWidget(self.progress)
        bottom_lay.addWidget(self.log_panel, 1)
        bottom.setMinimumHeight(150)
        bottom.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.setObjectName("programRightSplit")
        right_split.setChildrenCollapsible(False)
        right_split.addWidget(self.main_tabs)
        right_split.addWidget(bottom)
        right_split.setStretchFactor(0, 2)
        right_split.setStretchFactor(1, 1)
        right_split.setSizes([400, 280])

        self.main_layout.addWidget(right_split, 1)
        self._compact_form_layout(self.flash_panel)
        self._compact_form_layout(self.target_info_panel)
        # Target info should sit right under the separator.
        left_lay.setSpacing(2)
        t_form = self.target_info_panel._form.layout()
        if t_form is not None:
            t_form.setContentsMargins(10, 0, 10, 8)
        self.retranslate()

    @staticmethod
    def _compact_form_layout(panel) -> None:
        form = getattr(panel, "_form", None)
        if form is None:
            return
        lay = form.layout()
        if lay is None:
            return
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        for i in range(lay.count() - 1, -1, -1):
            item = lay.itemAt(i)
            if item is not None and item.spacerItem() is not None:
                lay.takeAt(i)
        form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        host_lay = form.parentWidget().layout() if form.parentWidget() else None
        if host_lay is not None:
            host_lay.setAlignment(form, Qt.AlignmentFlag.AlignTop)

    def set_handlers(self, mapping: dict[str, Callable[[], Any]]) -> None:
        self._handlers.update(mapping)

    def toolbar_actions(self) -> list[ToolActionSpec]:
        h = self._handlers
        return [
            ToolActionSpec("open", "act.open", "open", h.get("open", lambda: None)),
            ToolActionSpec(
                "program",
                "act.program",
                "program",
                h.get("program", lambda: None),
                separator_before=True,
            ),
            ToolActionSpec("erase", "act.erase", "erase", h.get("erase", lambda: None)),
            ToolActionSpec("verify", "act.verify", "verify", h.get("verify", lambda: None)),
            ToolActionSpec("reset", "act.reset", "reset", h.get("reset", lambda: None)),
            ToolActionSpec(
                "read",
                "act.read_chip",
                "read",
                h.get("read", lambda: None),
                separator_before=True,
            ),
            ToolActionSpec("hex", "act.hex", "hex", h.get("hex", lambda: None)),
        ]

    def retranslate(self) -> None:
        self.left_box.setTitle(tr("probe.group"))
        for i, key in enumerate(_TAB_I18N):
            if i < self.main_tabs.count():
                self.main_tabs.setTabText(i, tr(key))
                set_tab_icon(self.main_tabs, i, _TAB_KEYS[i])
        for panel in (
            self.probe_panel,
            self.flash_panel,
            self.target_info_panel,
            self.hex_preview,
            self.rtt_panel,
            self.swo_panel,
        ):
            if hasattr(panel, "retranslate"):
                panel.retranslate()

    def goto_tab(self, keyword: str) -> None:
        mapping = {
            "Hex": (tr("tab.hex"), "Hex"),
            "flash": (tr("tab.flash"),),
            "devices": (tr("tab.devices"),),
            "rtt": (tr("tab.rtt"), "RTT"),
            "swv": (tr("tab.swo"), "SWV"),
            "swo": (tr("tab.swo"), "SWV"),
        }
        needles = mapping.get(keyword, (keyword,))
        for i in range(self.main_tabs.count()):
            text = self.main_tabs.tabText(i)
            if any(n and n in text for n in needles):
                self.main_tabs.setCurrentIndex(i)
                return

    def session_getter(self) -> Callable[[], Any]:
        # Wired by MainWindow after driver creation.
        return getattr(self, "_sess", lambda: None)

    def set_session_getter(self, fn: Callable[[], Any]) -> None:
        self._sess = fn
        self.rtt_panel.set_session_getter(fn)
        self.swo_panel.set_session_getter(fn)
