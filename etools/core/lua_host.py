"""Global Lua automation host for ETools.

Bridges one Lua runtime to every tool surface (serial / net / terminal /
flash) so scripts are not locked to a single page.  ``lupa`` is optional —
when missing, :meth:`LuaHost.available` is False and the UI shows a hint.

Host tables exposed to Lua:

    app.log(msg) / app.sleep(ms) / app.version
    util.hex(data) / util.unhex(s) / util.checksum(data, algo)
    util.append_checksum(data, algo) / util.verify_checksum(frame, algo)
    serial.opened() / serial.send(text) / serial.send_hex(hexstr) / serial.write(bytes_str)
    serial.recv(max_bytes) / serial.expect(needle, timeout_ms)
    serial.plot(frame) / net.plot(frame)
        frame is a numeric table ``{a=5, b=4}`` or ``{5, 4, 16}``,
        or a string parsed by the open plot mode (``/*1,2*/``, JSON, key=value, HEX)
    net.opened() / net.send(text) / net.recv(max_bytes) / net.expect(needle, timeout_ms)
    term.opened() / term.send(text) / term.recv(max_bytes)
    frames.recv([max[, source]]) / frames.wait([timeout_ms[, source]]) / frames.latest([source])
    frames.publish(fields) / frames.clear()
        parsed frames shared by serial / net / MQTT; publish uses source "lua"
    dash.widgets() / dash.values() / dash.source([name]) / dash.push(fields)
    dash.add(spec) / dash.remove(index)
    map.points([n]) / map.last() / map.add(lat, lon) / map.clear()
    map.source([name]) / map.bind(lat_field, lon_field)
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


# Binary chunks can corrupt the VM, and string.dump only exists to produce them.
_HARDEN_LUA = """
local raw_load = load
load = function(chunk, name, _mode, env)
  return raw_load(chunk, name, "t", env)
end
string.dump = nil
"""


def _to_lua(lua, value):
    """Convert bridge results (lists / dicts) to Lua tables so ipairs/pairs work."""
    if isinstance(value, dict):
        return lua.table_from({str(k): _to_lua(lua, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return lua.table_from([_to_lua(lua, v) for v in value])
    return value


def _lua_dict(table) -> dict:
    """Flat Lua table with string keys -> dict (non-table input gives {})."""
    items = getattr(table, "items", None)
    if not callable(items):
        return {}
    return {str(k): v for k, v in list(items()) if not isinstance(k, bool)}


def _attribute_filter(_obj, name, _is_setting):
    """Block dunder/private attribute access on Python objects seen from Lua."""
    if not isinstance(name, str) or name.startswith("_"):
        raise AttributeError(f"access to '{name}' is not allowed")
    return name


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
        """Register a tool bridge: ``serial``, ``net``, ``term``, ``can``, ``flash``."""
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
        for bridge in list(self._bridges.values()):
            hook = getattr(bridge, "script_started", None)
            if callable(hook):
                hook()
        self._stop_flag.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_body, args=(source,), name="etools-lua", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the current script finishes. Returns False on timeout."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

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

        lua = LuaRuntime(
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            attribute_filter=_attribute_filter,
        )
        host = lua.eval("{}")
        self._install_app(lua, host)
        self._install_util(lua, host)
        self._install_serial(lua, host)
        self._install_net(lua, host)
        self._install_term(lua, host)
        self._install_can(lua, host)
        self._install_flash(lua, host)
        self._install_frames(lua, host)
        self._install_dash(lua, host)
        self._install_map(lua, host)
        lua.globals()["etools"] = host
        lua.globals()["dofile"] = self._blocked("dofile")
        lua.globals()["loadfile"] = self._blocked("loadfile")
        g = lua.globals()
        for name in ("os", "io", "debug", "package", "require", "python"):
            g[name] = None
        lua.execute(_HARDEN_LUA)
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
            from etools.core.hextext import parse_hex_input

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
        serial["opened"] = lambda: self._flag("serial", "opened")
        serial["plot"] = lambda frame: self._bridge_call("serial", "plot", *self._plot_args(frame))
        host["serial"] = serial

    def _install_net(self, lua, host) -> None:
        net = lua.eval("{}")
        net["send"] = lambda text: self._bridge_call("net", "send", str(text))
        net["recv"] = lambda n=4096: self._bridge_call("net", "recv", int(n))
        net["expect"] = lambda needle, timeout=2000: self._bridge_call(
            "net", "expect", str(needle), int(timeout)
        )
        net["opened"] = lambda: self._flag("net", "opened")
        net["plot"] = lambda frame: self._bridge_call("net", "plot", *self._plot_args(frame))
        host["net"] = net

    def _install_term(self, lua, host) -> None:
        term = lua.eval("{}")
        term["send"] = lambda text: self._bridge_call("term", "send", str(text))
        term["recv"] = lambda n=4096: self._bridge_call("term", "recv", int(n))
        term["opened"] = lambda: self._flag("term", "opened")
        host["term"] = term

    def _flag(self, name: str, method: str) -> bool:
        bridge = self._bridges.get(name)
        fn = getattr(bridge, method, None) if bridge is not None else None
        if fn is None:
            return False
        return bool(fn())

    def _install_can(self, lua, host) -> None:
        can = lua.eval("{}")
        can["send"] = lambda arb_id, data="", ext=False, rtr=False: self._bridge_call(
            "can", "send", int(arb_id), str(data), bool(ext), bool(rtr)
        )
        can["nmt"] = lambda command, node=0: self._bridge_call(
            "can", "nmt", str(command), int(node)
        )
        can["sdo_read"] = lambda node, index, subindex=0: self._bridge_call(
            "can", "sdo_read", int(node), int(index), int(subindex)
        )
        can["sdo_write"] = lambda node, index, subindex, value: self._bridge_call(
            "can", "sdo_write", int(node), int(index), int(subindex), str(value)
        )
        can["recv"] = lambda max_frames=16: _to_lua(
            lua, self._bridge_call("can", "recv", int(max_frames))
        )
        can["expect_id"] = lambda arb_id, timeout=2000: _to_lua(
            lua, self._bridge_call("can", "expect_id", int(arb_id), int(timeout))
        )

        def _opened():
            return bool(self._bridges.get("can") and self._bridge_call("can", "opened"))

        can["opened"] = _opened
        host["can"] = can

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

    def _install_frames(self, lua, host) -> None:
        frames = lua.eval("{}")
        frames["recv"] = lambda max_frames=32, source="": _to_lua(
            lua, self._bridge_call("frames", "recv", int(max_frames), str(source or ""))
        )

        def wait(timeout=1000, source=""):
            return _to_lua(
                lua,
                self._bridge_call(
                    "frames", "wait", int(timeout), str(source or ""), self._stop_flag.is_set
                ),
            )

        frames["wait"] = wait
        frames["latest"] = lambda source="": _to_lua(
            lua, self._bridge_call("frames", "latest", str(source or ""))
        )
        frames["publish"] = lambda fields: self._bridge_call(
            "frames", "publish", self._fields(fields)
        )
        frames["clear"] = lambda: self._bridge_call("frames", "clear")
        host["frames"] = frames

    def _install_dash(self, lua, host) -> None:
        dash = lua.eval("{}")
        dash["widgets"] = lambda: _to_lua(lua, self._bridge_call("dash", "widgets"))
        dash["values"] = lambda: _to_lua(lua, self._bridge_call("dash", "values"))
        dash["source"] = lambda name=None: self._bridge_call(
            "dash", "source", None if name is None else str(name)
        )
        dash["push"] = lambda fields: self._bridge_call("dash", "push", self._fields(fields))
        dash["add"] = lambda spec: self._bridge_call("dash", "add", _lua_dict(spec))
        dash["remove"] = lambda index: self._bridge_call("dash", "remove", int(index))
        host["dash"] = dash

    def _install_map(self, lua, host) -> None:
        map_ = lua.eval("{}")
        map_["points"] = lambda n=0: _to_lua(lua, self._bridge_call("map", "points", int(n)))
        map_["last"] = lambda: _to_lua(lua, self._bridge_call("map", "last"))
        map_["add"] = lambda lat, lon: self._bridge_call("map", "add", float(lat), float(lon))
        map_["clear"] = lambda: self._bridge_call("map", "clear")
        map_["source"] = lambda name=None: self._bridge_call(
            "map", "source", None if name is None else str(name)
        )
        map_["bind"] = lambda lat, lon: self._bridge_call("map", "bind", str(lat), str(lon))
        host["map"] = map_

    def _fields(self, frame) -> dict[str, float]:
        """Lua numeric table -> named fields (list entries become f1, f2, …)."""
        kind, payload = self._plot_args(frame)
        if kind == "list":
            return {f"f{i + 1}": float(v) for i, v in enumerate(payload)}
        if kind == "map":
            return dict(payload)
        raise LuaError("expected a numeric table such as {speed = 3.2} or {1, 2, 3}")

    def _plot_args(self, frame) -> tuple[str, object]:
        """Turn a Lua table or frame string into a bridge payload."""
        if isinstance(frame, (bytes, bytearray)):
            return ("bytes", bytes(frame))
        if isinstance(frame, str):
            return ("text", frame)
        items = getattr(frame, "items", None)
        if not callable(items):
            raise LuaError("plot expects a table or a frame string")
        named: dict[str, float] = {}
        numbered: list[tuple[int, float]] = []
        for key, value in list(items()):
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if isinstance(key, bool):
                continue
            if isinstance(key, (int, float)) and float(key).is_integer():
                numbered.append((int(key), number))
            else:
                named[str(key)] = number
        if numbered and not named:
            return ("list", [value for _index, value in sorted(numbered)])
        for index, value in numbered:
            named.setdefault(f"f{index}", value)
        if not named:
            raise LuaError("plot table has no numeric fields")
        return ("map", named)

    @staticmethod
    def _to_bytes(data) -> bytes:
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            return data.encode("latin-1", errors="replace")
        return bytes(data)
