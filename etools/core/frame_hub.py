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

    def _parser(self, source: str) -> StudioFrameParser:
        return self._parsers.setdefault(source, StudioFrameParser())

    def set_names(self, source: str, text: str) -> None:
        self._parser(source).set_names(text)

    def set_mode(self, source: str, mode: str) -> None:
        self._parser(source).set_mode(mode)

    def set_hex_template(self, source: str, text: str) -> None:
        self._parser(source).set_hex_template(text)

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


frame_hub = FrameHub()
