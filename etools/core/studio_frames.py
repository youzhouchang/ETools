"""Serial Studio quick-plot frames carried in a text byte stream.

Two shapes are recognized:

* ``/*1.2,3.4,-5*/`` — comma-separated numbers, field names optional
* ``{"temp":21.5,"hum":40}`` — a JSON object whose values are numbers
"""

from __future__ import annotations

import json
import math


def _numbers(body: str) -> list[float]:
    values: list[float] = []
    for part in body.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            return []
        if not math.isfinite(value):
            return []
        values.append(value)
    return values


class StudioFrameParser:
    """Incremental parser. Incomplete frames stay in the buffer."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.names: list[str] = []

    def set_names(self, text: str) -> None:
        self.names = [part.strip() for part in str(text or "").split(",") if part.strip()]

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[dict[str, float]]:
        if data:
            self._buffer.extend(data)
        if len(self._buffer) > 65536:
            del self._buffer[:-4096]
        # surrogateescape preserves incomplete UTF-8 bytes across feed calls.
        text = bytes(self._buffer).decode("utf-8", errors="surrogateescape")
        frames: list[dict[str, float]] = []
        consumed = 0
        index = 0
        while index < len(text):
            quick = text.find("/*", index)
            blob = text.find("{", index)
            if quick < 0 and blob < 0:
                break
            if blob < 0 or (quick >= 0 and quick <= blob):
                end = text.find("*/", quick + 2)
                if end < 0:
                    index = quick
                    break
                values = _numbers(text[quick + 2 : end])
                if values:
                    frames.append(self._named(values))
                index = end + 2
                consumed = index
                continue
            if text.find("}", blob) < 0:
                index = blob
                break
            try:
                obj, offset = json.JSONDecoder().raw_decode(text, blob)
            except json.JSONDecodeError:
                index = blob + 1
                continue
            if isinstance(obj, dict):
                numeric = {
                    str(key): float(value)
                    for key, value in obj.items()
                    if isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                }
                if numeric:
                    frames.append(numeric)
            index = offset
            consumed = index
        if consumed:
            self._buffer = bytearray(
                text[consumed:].encode("utf-8", errors="surrogateescape")
            )
        return frames

    def _named(self, values: list[float]) -> dict[str, float]:
        named: dict[str, float] = {}
        for index, value in enumerate(values):
            if index < len(self.names):
                named[self.names[index]] = value
            else:
                named[f"f{index + 1}"] = value
        return named
