"""Global Lua automation host for ETools.

Bridges one Lua runtime to every tool surface (serial / net / terminal /
flash) so scripts are not locked to a single page.  ``lupa`` is optional —
when missing, :meth:`LuaHost.available` is False and the UI shows a hint.

Host tables exposed to Lua:

    app.log(msg) / app.sleep(ms) / app.version
    util.hex(data) / util.unhex(s) / util.checksum(data, algo)
    util.append_checksum(data, algo) / util.verify_checksum(frame, algo)
    serial.send(text) / serial.send_hex(hexstr) / serial.write(bytes_str)
    serial.recv(max_bytes) / serial.expect(needle, timeout_ms)
    net.send(text) / net.recv(max_bytes)
    term.send(text)
    flash.erase_all() / flash.erase_range(addr, size)
    flash.program(path[, verify]) / flash.read_mem(addr, size) -> hex
    flash.reset([halt]) / flash.connected
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from etools.core.checksum import (
    ALGORITHMS,
    append_checksum,
    compute_checksum,
    verify_checksum,
)

try:
    import lupa  # type: ignore

    _LUPA = True
except Exception:  # noqa: BLE001
    lupa = None  # type: ignore
    _LUPA = False


class LuaError(RuntimeError):
    """Lua compile or runtime failure."""


class LuaHost:
    """Owns one Lua VM and thread-safe tool bridges.

    Bridges are plain Python callables registered by the UI; scripts run on a
    worker thread so blocking waits never freeze Qt.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._bridges: dict[str, Any] = {}
        self._log_hook: Callable[[str], None] | None = None
        self._done_hook: Callable[[bool, str], None] | None = None

    # -- capability ----------------------------------------------------

    @staticmethod
    def available() -> bool:
        return _LUPA

    @property
    def running(self) -> bool:
        return self._running

    def set_log_hook(self, hook: Callable[[str], None] | None) -> None:
        self._log_hook = hook

    def set_done_hook(self, hook: Callable[[bool, str], None] | None) -> None:
        self._done_hook = hook

    def set_bridge(self, name: str, bridge: Any) -> None:
        """Register a tool bridge: ``serial``, ``net``, ``term``, ``flash``."""
        self._bridges[name] = bridge

    def clear_bridge(self, name: str) -> None:
        self._bridges.pop(name, None)

    def _emit_log(self, message: str) -> None:
        if self._log_hook:
            self._log_hook(str(message))

    # -- script execution ----------------------------------------------

    def run_script(self, source: str) -> None:
        """Start `source` on a worker thread. Raises LuaError if unavailable."""
        if not _LUPA:
            raise LuaError("lupa is not installed")
        if self._running:
            raise LuaError("script already running")
        self._stop_flag.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_body, args=(source,), name="etools-lua", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    def _run_body(self, source: str) -> None:
        ok = False
        message = "ok"
        try:
            self._execute(source)
            ok = True
            message = "done"
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self._emit_log(f"error: {message}")
        finally:
            self._running = False
            if self._done_hook:
                self._done_hook(ok, message)

    def _execute(self, source: str) -> None:
        from lupa import LuaRuntime  # type: ignore

        lua = LuaRuntime(unpack_returned_tuples=True)
        host = lua.eval("{}")
        self._install_app(lua, host)
        self._install_util(lua, host)
        self._install_serial(lua, host)
        self._install_net(lua, host)
        self._install_term(lua, host)
        self._install_flash(lua, host)
        lua.globals()["etools"] = host
        lua.globals()["dofile"] = self._blocked("dofile")
        lua.globals()["loadfile"] = self._blocked("loadfile")
        # Drop dangerous stdlib bits for a lighter sandbox (not a hard jail).
        g = lua.globals()
        for name in ("os", "io", "debug", "package", "require"):
            g[name] = None
        try:
            lua.execute(source)
        except Exception as exc:  # noqa: BLE001
            raise LuaError(str(exc)) from exc

    def _blocked(self, name: str):
        def _fn(*_a, **_k):
            raise LuaError(f"{name} is disabled in ETools scripts")

        return _fn

    def _check_stop(self) -> None:
        if self._stop_flag.is_set():
            raise LuaError("script stopped")

    # -- tables --------------------------------------------------------

    def _install_app(self, lua, host) -> None:
        def log(msg) -> None:
            self._emit_log("" if msg is None else str(msg))

        def sleep(ms) -> None:
            ms = int(ms or 0)
            end = time.monotonic() + max(0, ms) / 1000.0
            while time.monotonic() < end:
                self._check_stop()
                time.sleep(min(0.05, max(0.0, end - time.monotonic())))

        app = lua.eval("{}")
        app["log"] = log
        app["sleep"] = sleep
        app["version"] = "1"
        app["stopped"] = lambda: self._stop_flag.is_set()
        host["app"] = app

    def _install_util(self, lua, host) -> None:
        def hex_of(data) -> str:
            raw = self._to_bytes(data)
            return " ".join(f"{b:02X}" for b in raw)

        def unhex(text) -> str:
            from etools.ui.widgets.traffic_view import parse_hex_input

            return self._to_bytes(parse_hex_input(str(text))).decode("latin-1")

        def checksum(data, algo) -> str:
            return self._to_bytes(compute_checksum(self._to_bytes(data), str(algo))).hex()

        def append_check(data, algo) -> str:
            raw = append_checksum(self._to_bytes(data), str(algo))
            return raw.decode("latin-1")

        def verify_check(frame, algo) -> bool:
            return verify_checksum(self._to_bytes(frame), str(algo))

        util = lua.eval("{}")
        util["hex"] = hex_of
        util["unhex"] = unhex
        util["checksum"] = checksum
        util["append_checksum"] = append_check
        util["verify_checksum"] = verify_check
        util["algorithms"] = lua.table_from(list(ALGORITHMS))
        host["util"] = util

    def _bridge_call(self, name: str, method: str, *args):
        self._check_stop()
        bridge = self._bridges.get(name)
        if bridge is None:
            raise LuaError(f"{name} bridge is not available")
        fn = getattr(bridge, method, None)
        if fn is None:
            raise LuaError(f"{name}.{method} is not available")
        return fn(*args)

    def _install_serial(self, lua, host) -> None:
        serial = lua.eval("{}")
        serial["send"] = lambda text: self._bridge_call("serial", "send", str(text))
        serial["send_hex"] = lambda text: self._bridge_call(
            "serial", "send_hex", str(text)
        )
        serial["write"] = lambda raw: self._bridge_call("serial", "write", self._to_bytes(raw))
        serial["recv"] = lambda n=4096: self._bridge_call("serial", "recv", int(n))
        serial["expect"] = lambda needle, timeout=2000: self._bridge_call(
            "serial", "expect", str(needle), int(timeout)
        )
        host["serial"] = serial

    def _install_net(self, lua, host) -> None:
        net = lua.eval("{}")
        net["send"] = lambda text: self._bridge_call("net", "send", str(text))
        net["recv"] = lambda n=4096: self._bridge_call("net", "recv", int(n))
        host["net"] = net

    def _install_term(self, lua, host) -> None:
        term = lua.eval("{}")
        term["send"] = lambda text: self._bridge_call("term", "send", str(text))
        host["term"] = term

    def _install_flash(self, lua, host) -> None:
        flash = lua.eval("{}")
        flash["erase_all"] = lambda: self._bridge_call("flash", "erase_all")
        flash["erase_range"] = lambda addr, size: self._bridge_call(
            "flash", "erase_range", int(addr), int(size)
        )
        flash["program"] = lambda path, verify=True: self._bridge_call(
            "flash", "program", str(path), bool(verify)
        )
        flash["read_mem"] = lambda addr, size: self._bridge_call(
            "flash", "read_mem", int(addr), int(size)
        )
        flash["reset"] = lambda halt=False: self._bridge_call("flash", "reset", bool(halt))

        def _connected() -> bool:
            return bool(self._bridges.get("flash") and self._bridge_call("flash", "connected"))

        flash["connected"] = _connected
        host["flash"] = flash

    @staticmethod
    def _to_bytes(data) -> bytes:
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("latin-1", errors="replace")
        return bytes(data)
