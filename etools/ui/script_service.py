"""Process-wide Lua runner shared by the Script page and other tools."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from etools.core import script_store
from etools.core.lua_host import LuaHost


class ScriptService(QObject):
    """One Lua host so any tool page can run saved scripts."""

    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.host = LuaHost()
        self.host.set_log_hook(self.log.emit)
        self.host.set_done_hook(self.done.emit)

    def available(self) -> bool:
        return self.host.available()

    @property
    def running(self) -> bool:
        return self.host.running

    def set_bridge(self, name: str, bridge) -> None:
        self.host.set_bridge(name, bridge)

    def run_source(self, source: str) -> None:
        self.host.run_script(source)

    def run_named(self, name: str) -> None:
        self.host.run_script(script_store.load_script(name))

    def stop(self) -> None:
        self.host.stop()


_service: ScriptService | None = None


def script_service() -> ScriptService:
    global _service
    if _service is None:
        _service = ScriptService()
    return _service
