"""Flash tools tab: option bytes, production, image tools, UART bootloader."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from etools.i18n import tr
from etools.ui.icons import set_tab_icon
from etools.ui.widgets.image_tools_panel import ImageToolsPanel
from etools.ui.widgets.option_bytes_panel import OptionBytesPanel
from etools.ui.widgets.production_panel import ProductionPanel
from etools.ui.widgets.uart_boot_panel import UartBootPanel

# attribute, icon, i18n key
_SUB_TABS = (
    ("option_bytes", "chip", "tools.tab.ob"),
    ("production", "program", "tools.tab.prod"),
    ("image_tools", "hex", "tools.tab.image"),
    ("uart_boot", "tool-serial", "tools.tab.uart"),
)


class FlashToolsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.option_bytes = OptionBytesPanel()
        self.production = ProductionPanel()
        self.image_tools = ImageToolsPanel()
        self.uart_boot = UartBootPanel()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("flashToolsTabs")
        for attr, _icon, _key in _SUB_TABS:
            self.tabs.addTab(getattr(self, attr), "")
        lay.addWidget(self.tabs)
        self.retranslate()

    def panels(self) -> list[Any]:
        return [getattr(self, attr) for attr, _i, _k in _SUB_TABS]

    def bind(self, host: Any) -> None:
        for panel in self.panels():
            panel.bind(host)

    def retranslate(self) -> None:
        for i, (attr, icon_name, key) in enumerate(_SUB_TABS):
            self.tabs.setTabText(i, tr(key))
            set_tab_icon(self.tabs, i, icon_name)
            getattr(self, attr).retranslate()

    def set_connected(self, connected: bool) -> None:
        for panel in self.panels():
            panel.set_connected(connected)

    def goto(self, attr: str) -> None:
        for i, (name, _icon, _key) in enumerate(_SUB_TABS):
            if name == attr:
                self.tabs.setCurrentIndex(i)
