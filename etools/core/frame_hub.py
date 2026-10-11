"""Shared parsed frames from serial, network, and MQTT streams."""

from __future__ import annotations

from collections.abc import Callable

from etools.core.studio_frames import StudioFrameParser

Listener = Callable[[str, dict[str, float]], None]


class FrameHub:
    """One parser per source so split frames still reassemble."""

    def __init__(self) -> None:
        self._parsers: dict[str, StudioFrameParser] = {}
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def set_names(self, source: str, text: str) -> None:
        parser = self._parsers.setdefault(source, StudioFrameParser())
        parser.set_names(text)

    def publish(self, source: str, data: bytes) -> None:
        if not data:
            return
        parser = self._parsers.setdefault(source, StudioFrameParser())
        frames = parser.feed(data)
        if not frames:
            return
        listeners = list(self._listeners)
        for frame in frames:
            for listener in listeners:
                listener(source, frame)


frame_hub = FrameHub()
