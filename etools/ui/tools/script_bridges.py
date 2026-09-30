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

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))

    def send_hex(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text, force_hex=True))

    def write(self, raw: bytes) -> bool:
        return self._pump.submit(lambda: self._page.lua_write(raw))

    def recv(self, max_bytes: int = 4096) -> str:
        data = self._pump.submit(lambda: self._page.lua_take_rx(int(max_bytes)))
        return bytes(data or b"").decode("latin-1", errors="replace")

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

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))

    def recv(self, max_bytes: int = 4096) -> str:
        data = self._pump.submit(lambda: self._page.lua_take_rx(int(max_bytes)))
        return bytes(data or b"").decode("latin-1", errors="replace")


class TermLuaBridge:
    def __init__(self, page, pump: _QueueBridge) -> None:
        self._page = page
        self._pump = pump

    def send(self, text: str) -> bool:
        return self._pump.submit(lambda: self._page.lua_send_text(text))


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
        return self._pump.submit(
            lambda: self._page.lua_sdo_read(int(node), int(index), int(subindex))
        )

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
    """Lua ``flash.*`` backed by FlashService / PyOCD driver."""

    def __init__(self, service, pump: _QueueBridge) -> None:
        self._service = service
        self._pump = pump

    def connected(self) -> bool:
        return bool(self._pump.submit(lambda: self._service.connected))

    def erase_all(self) -> bool:
        result = self._pump.submit(lambda: self._service.erase_all())
        return bool(getattr(result, "ok", False))

    def erase_range(self, address: int, size: int) -> bool:
        result = self._pump.submit(lambda: self._service.erase_range(int(address), int(size)))
        return bool(getattr(result, "ok", False))

    def program(self, path: str, verify: bool = True) -> bool:
        result = self._pump.submit(lambda: self._service.program_file(path, verify=bool(verify)))
        return bool(getattr(result, "ok", False))

    def read_mem(self, address: int, size: int) -> str:
        raw = self._pump.submit(lambda: self._service.read_memory_bytes(int(address), int(size)))
        return " ".join(f"{b:02X}" for b in bytes(raw or b""))

    def reset(self, halt: bool = False) -> bool:
        result = self._pump.submit(lambda: self._service.reset_target(halt=bool(halt)))
        return bool(getattr(result, "ok", False))
