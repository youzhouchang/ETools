"""Shared parsed frames from serial, network, and MQTT streams."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from etools.core.studio_frames import StudioFrameParser

Listener = Callable[[str, dict[str, float]], None]


class FrameHub:
    """One parser per source so split frames still reassemble."""

    def __init__(self) -> None:
        self._parsers: dict[str, StudioFrameParser] = {}
        self._listeners: list[Listener] = []
        self._configs: dict[str, tuple[str, str, str]] = {}

    def subscribe(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def _parser(self, source: str) -> StudioFrameParser:
        return self._parsers.setdefault(source, StudioFrameParser())

    def set_names(self, source: str, text: str) -> None:
        self._parser(source).set_names(text)

    def set_mode(self, source: str, mode: str) -> None:
        self._parser(source).set_mode(mode)

    def set_hex_template(self, source: str, text: str) -> None:
        self._parser(source).set_hex_template(text)

    def configure(self, source: str, mode: str, names: str, hex_template: str) -> None:
        """Apply parser settings only when they changed (called per RX chunk)."""
        config = (mode, names, hex_template)
        if self._configs.get(source) == config:
            return
        self._configs[source] = config
        parser = self._parser(source)
        parser.set_mode(mode)
        parser.set_names(names)
        parser.set_hex_template(hex_template)

    def publish(self, source: str, data: bytes) -> None:
        if not data:
            return
        frames = self._parser(source).feed(data)
        self.publish_frames(source, frames)

    def publish_frames(self, source: str, frames: list[dict[str, float]]) -> None:
        if not frames:
            return
        listeners = list(self._listeners)
        for frame in frames:
            for listener in listeners:
                listener(source, frame)


#: Source name used for frames that Lua scripts publish back to the hub.
LUA_SOURCE = "lua"


class FrameTap:
    """Thread-safe frame queue fed by a hub, read by a script worker.

    Frames from ``exclude`` sources (by default the script's own output)
    are kept out of the queue so a script that republishes cannot loop.
    """

    def __init__(
        self, hub: FrameHub, *, maxlen: int = 2048, exclude: tuple[str, ...] = (LUA_SOURCE,)
    ) -> None:
        self._hub = hub
        self._queue: deque[tuple[str, dict[str, float], float]] = deque(maxlen=maxlen)
        self._latest: dict[str, dict[str, float]] = {}
        self._exclude = set(exclude)
        self._cond = threading.Condition()
        self._active = False

    def start(self) -> None:
        if not self._active:
            self._hub.subscribe(self._on_frame)
            self._active = True

    def stop(self) -> None:
        if self._active:
            self._hub.unsubscribe(self._on_frame)
            self._active = False

    def clear(self) -> None:
        with self._cond:
            self._queue.clear()

    def _on_frame(self, source: str, frame: dict[str, float]) -> None:
        if not isinstance(frame, dict):
            return
        snapshot = dict(frame)
        with self._cond:
            self._latest.setdefault(source, {}).update(snapshot)
            if source in self._exclude:
                return
            self._queue.append((source, snapshot, time.time()))
            self._cond.notify_all()

    def take(self, max_frames: int = 32, source: str = "") -> list[dict]:
        """Pop up to *max_frames* queued frames (optionally one source only)."""
        out: list[dict] = []
        with self._cond:
            keep: deque = deque(maxlen=self._queue.maxlen)
            while self._queue:
                item = self._queue.popleft()
                if len(out) < max_frames and (not source or item[0] == source):
                    out.append(_frame_item(item))
                else:
                    keep.append(item)
            self._queue.extend(keep)
        return out

    def wait(self, timeout: float, source: str = "", stop=None) -> dict | None:
        """Block until one frame arrives or *timeout* seconds pass."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                for index, item in enumerate(self._queue):
                    if not source or item[0] == source:
                        del self._queue[index]
                        return _frame_item(item)
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (stop is not None and stop()):
                    return None
                self._cond.wait(min(remaining, 0.05))

    def latest(self, source: str = "") -> dict[str, float]:
        """Most recent value of every field, merged across frames."""
        with self._cond:
            if source:
                return dict(self._latest.get(source, {}))
            merged: dict[str, float] = {}
            for fields in self._latest.values():
                merged.update(fields)
            return merged


def _frame_item(item: tuple[str, dict[str, float], float]) -> dict:
    source, fields, stamp = item
    return {"source": source, "fields": dict(fields), "time": stamp}


frame_hub = FrameHub()
