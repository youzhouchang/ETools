"""Multi-tool pages — Program + Serial / Ethernet / CAN / Terminal / Script shell."""

from __future__ import annotations

from etools.ui.tools.base import ToolPage
from etools.ui.tools.can_page import CanPage
from etools.ui.tools.ethernet_page import EthernetPage
from etools.ui.tools.program_page import ProgramPage
from etools.ui.tools.script_page import ScriptPage
from etools.ui.tools.serial_page import SerialPage
from etools.ui.tools.sftp_panel import SftpPanel
from etools.ui.tools.terminal_page import TerminalPage

__all__ = [
    "ToolPage",
    "ProgramPage",
    "SerialPage",
    "EthernetPage",
    "CanPage",
    "TerminalPage",
    "ScriptPage",
    "SftpPanel",
]
