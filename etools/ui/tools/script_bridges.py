"""Thread-safe tool bridges used by the global Lua host."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any


class _QueueBridge:
    """Push work onto the Qt thread and wait for the result.

    The Lua worker must never touch Qt widgets directly; it posts callables
    via `submit` and blocks until the main thread runs them.
    """

    def __init__(self) -> None:
        self._jobs: queue.Queue[tuple[Callable[[], Any], threading.Event, list]] = queue.Queue()
        self._armed = False

    def install(self, qt_parent) -> None:
        from PySide6.QtCore import QObject, QTimer

        class _Pump(QObject):
            def __init__(self, owner: _QueueBridge) -> None:
                super().__init__(qt_parent)
                self._owner = owner

        self._pump = _Pump(self)
        self._timer = QTimer(self._pump)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._drain)
        self._timer.start()
        self._armed = True

    def _drain(self) -> None:
        while True:
            try:
                fn, event, box = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                box.append(fn())
                box.append(None)
            except Exception as exc:  # noqa: BLE001
                box.append(None)
                box.append(exc)
            event.set()

    #: Beyond this many queued jobs, ``post`` waits so a fast script cannot flood the UI.
    POST_BACKLOG = 256

    def post(self, fn: Callable[[], Any], timeout: float = 30.0) -> None:
        """Run *fn* on the Qt thread without waiting, unless the queue is backed up."""
        if self._jobs.qsize() >= self.POST_BACKLOG:
            self.submit(fn, timeout)
            return
        if not self._armed:
            raise RuntimeError("bridge not installed")
        self._jobs.put((fn, threading.Event(), []))

    def submit(self, fn: Callable[[], Any], timeout: float = 30.0) -> Any:
        if not self._armed:
            raise RuntimeError("bridge not installed")
        event = threading.Event()
        box: list[Any] = []
        self._jobs.put((fn, event, box))
        if not event.wait(timeout):
            raise TimeoutError("tool call timed out")
        result, err = box[0], box[1]
        if err is not None:
            raise err
        return result


class SerialLuaBridge:
    """Lua ``serial.*`` backed by the SerialPage."""

    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def opened(self) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_opened()))

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))

    def send_hex(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text, force_hex=True))

    def write(self, raw: bytes) -> bool:
        return self._pump.submit(lambda: self._page.lua_write(raw))

    def recv(self, max_bytes: int = 4096) -> str:
        data = self._pump.submit(lambda: self._page.lua_take_rx(int(max_bytes)))
        return bytes(data or b"").decode("latin-1", errors="replace")

    def plot(self, kind: str, payload) -> int:
        return int(self._pump.submit(lambda: self._page.lua_plot(kind, payload)))

    def expect(self, needle: str, timeout_ms: int = 2000) -> bool:
        deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
        needle_b = needle.encode("utf-8", errors="replace")
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._pump.submit(lambda: self._page.lua_take_rx(4096), timeout=5.0)
            buf.extend(chunk or b"")
            if needle_b in buf:
                return True
            time.sleep(0.03)
        return False


class NetLuaBridge:
    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def opened(self) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_opened()))

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))

    def recv(self, max_bytes: int = 4096) -> str:
        data = self._pump.submit(lambda: self._page.lua_take_rx(int(max_bytes)))
        return bytes(data or b"").decode("latin-1", errors="replace")

    def plot(self, kind: str, payload) -> int:
        return int(self._pump.submit(lambda: self._page.lua_plot(kind, payload)))

    def expect(self, needle: str, timeout_ms: int = 2000) -> bool:
        deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
        needle_b = needle.encode("utf-8", errors="replace")
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._pump.submit(lambda: self._page.lua_take_rx(4096), timeout=5.0)
            buf.extend(chunk or b"")
            if needle_b in buf:
                return True
            time.sleep(0.03)
        return False


class TermLuaBridge:
    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def opened(self) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_opened()))

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))

    def recv(self, max_bytes: int = 4096) -> str:
        data = self._pump.submit(lambda: self._page.lua_take_rx(int(max_bytes)))
        return bytes(data or b"").decode("utf-8", errors="replace")


class CanLuaBridge:
    """Lua ``can.*`` backed by the CanPage."""

    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def opened(self) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_opened()))

    def send(self, arb_id: int, data: str = "", ext: bool = False, rtr: bool = False) -> bool:
        return self._pump.submit(
            lambda: self._page.lua_send_frame(int(arb_id), str(data), bool(ext), bool(rtr))
        )

    def nmt(self, command: str, node: int = 0) -> bool:
        return self._pump.submit(lambda: self._page.lua_nmt(str(command), int(node)))

    def sdo_read(self, node: int, index: int, subindex: int = 0) -> str:
        """Send an expedited read and return the response value as hex."""
        sent = self._pump.submit(
            lambda: self._page.lua_sdo_read(int(node), int(index), int(subindex))
        )
        if not sent:
            return ""
        from etools.core.canopen import parse_sdo_response
        from etools.core.hextext import parse_hex_input

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            frame = self._pump.submit(
                lambda: self._page.lua_take_sdo(int(node), int(index), int(subindex)),
                timeout=5.0,
            )
            if frame:
                try:
                    raw = parse_hex_input(str(frame.get("data") or ""))
                except ValueError:
                    return ""
                result = parse_sdo_response(raw)
                if not result.ok:
                    return ""
                return bytes(result.data).hex(" ").upper()
            time.sleep(0.03)
        return ""

    def sdo_write(self, node: int, index: int, subindex: int, value: str) -> bool:
        return self._pump.submit(
            lambda: self._page.lua_sdo_write(int(node), int(index), int(subindex), str(value))
        )

    def recv(self, max_frames: int = 16) -> list:
        frames = self._pump.submit(lambda: self._page.lua_take_frames(int(max_frames)))
        return list(frames or [])

    def expect_id(self, arb_id: int, timeout_ms: int = 2000) -> dict | None:
        deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
        want = int(arb_id)
        while time.monotonic() < deadline:
            frames = self._pump.submit(lambda: self._page.lua_take_frames(32), timeout=5.0)
            for fr in frames or []:
                if int(fr.get("id", -1)) == want:
                    return fr
            time.sleep(0.03)
        return None


class FlashLuaBridge:
    """Lua ``flash.*`` backed by FlashService / the pyOCD driver.

    Calls run on the Lua thread. ``FlashService`` serializes them with the
    UI worker, and progress is queued back to the interface, so a long
    program or erase does not freeze the window.
    """

    def __init__(self, service, pump: _QueueBridge) -> None:
        self._service = service
        self._pump = pump

    def connected(self) -> bool:
        return bool(self._service.connected)

    def erase_all(self) -> bool:
        return bool(getattr(self._service.erase_all(), "ok", False))

    def erase_range(self, address: int, size: int) -> bool:
        result = self._service.erase_range(int(address), int(size))
        return bool(getattr(result, "ok", False))

    def program(self, path: str, verify: bool = True) -> bool:
        result = self._service.program_file(path, verify=bool(verify))
        return bool(getattr(result, "ok", False))

    def read_mem(self, address: int, size: int) -> str:
        try:
            raw = self._service.read_memory_bytes(int(address), int(size))
        except Exception:  # noqa: BLE001
            return ""
        return " ".join(f"{b:02X}" for b in bytes(raw or b""))

    def reset(self, halt: bool = False) -> bool:
        result = self._service.reset_target(halt=bool(halt))
        return bool(getattr(result, "ok", False))


class FramesLuaBridge:
    """Lua ``frames.*``: read parsed frames from the hub and publish results back."""

    def __init__(self, pump: _QueueBridge, hub=None) -> None:
        from etools.core.frame_hub import FrameTap, frame_hub

        self._pump = pump
        self._hub = hub or frame_hub
        self._tap = FrameTap(self._hub)
        self._tap.start()

    def script_started(self) -> None:
        # Each run starts with fresh input instead of frames queued while idle.
        self._tap.clear()

    def shutdown(self) -> None:
        self._tap.stop()

    def recv(self, max_frames: int = 32, source: str = "") -> list[dict]:
        return self._tap.take(max(1, int(max_frames)), source)

    def wait(self, timeout_ms: int = 1000, source: str = "", stop=None) -> dict | None:
        return self._tap.wait(max(0, int(timeout_ms)) / 1000.0, source, stop)

    def latest(self, source: str = "") -> dict[str, float]:
        return self._tap.latest(source)

    def clear(self) -> bool:
        self._tap.clear()
        return True

    def publish(self, fields: dict[str, float]) -> bool:
        from etools.core.frame_hub import LUA_SOURCE

        frame = dict(fields)
        self._pump.post(lambda: self._hub.publish_frames(LUA_SOURCE, [frame]))
        return True


class DashLuaBridge:
    """Lua ``dash.*`` backed by the DashboardPage."""

    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def widgets(self) -> list[dict]:
        return self._pump.submit(self._page.lua_widgets)

    def values(self) -> list[dict]:
        return self._pump.submit(self._page.lua_values)

    def source(self, name: str | None = None) -> str:
        return self._pump.submit(lambda: self._page.lua_source(name))

    def push(self, fields: dict[str, float]) -> bool:
        frame = dict(fields)
        self._pump.post(lambda: self._page.lua_push(frame))
        return True

    def add(self, spec: dict) -> int:
        return int(self._pump.submit(lambda: self._page.lua_add(dict(spec))))

    def remove(self, index: int) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_remove(int(index))))


class MapLuaBridge:
    """Lua ``map.*`` backed by the MapPage."""

    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def points(self, n: int = 0) -> list[dict]:
        return self._pump.submit(lambda: self._page.lua_points(int(n)))

    def last(self) -> dict | None:
        points = self.points(1)
        return points[-1] if points else None

    def add(self, lat: float, lon: float) -> bool:
        return bool(self._pump.submit(lambda: self._page.lua_add_point(float(lat), float(lon))))

    def clear(self) -> bool:
        self._pump.submit(self._page.lua_clear)
        return True

    def source(self, name: str | None = None) -> str:
        return self._pump.submit(lambda: self._page.lua_source(name))

    def bind(self, lat_field: str, lon_field: str) -> bool:
        self._pump.submit(lambda: self._page.lua_bind(str(lat_field), str(lon_field)))
        return True
