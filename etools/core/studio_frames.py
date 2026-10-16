"""Serial Studio quick-plot frames carried in a text or binary byte stream.

Supported modes:

* ``studio`` — ``/*1.2,3.4,-5*/`` and numeric JSON objects
* ``kv`` — newline-delimited ``key=value`` pairs (space/comma separated)
* ``hex`` — sliding match against a structure template such as
  ``AA 55 u16be:v f32le:x``
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass

PARSE_MODES = ("studio", "kv", "hex")

_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]{2}$")
_FIELD_TOKEN = re.compile(
    r"^(?P<type>u8|i8|u16|i16|u32|i32|f32|f64)(?P<endian>le|be)?:(?P<name>[A-Za-z_][A-Za-z0-9_]*)$",
    re.IGNORECASE,
)


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


def _parse_kv_line(line: str) -> dict[str, float]:
    result: dict[str, float] = {}
    # Accept "a=1 b=2", "a=1,b=2", and "a:1".
    for match in re.finditer(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        line,
    ):
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        if math.isfinite(value):
            result[match.group(1)] = value
    return result


@dataclass(frozen=True)
class _HexField:
    name: str
    fmt: str
    size: int


@dataclass(frozen=True)
class HexStructTemplate:
    header: bytes
    fields: tuple[_HexField, ...]
    size: int

    @classmethod
    def parse(cls, text: str) -> HexStructTemplate:
        header = bytearray()
        fields: list[_HexField] = []
        seen_field = False
        for raw in str(text or "").replace(",", " ").split():
            token = raw.strip()
            if not token:
                continue
            if _HEX_TOKEN.match(token):
                if seen_field:
                    raise ValueError("header bytes must come before typed fields")
                header.append(int(token, 16))
                continue
            match = _FIELD_TOKEN.match(token)
            if not match:
                raise ValueError(f"bad hex template token: {token}")
            seen_field = True
            kind = match.group("type").lower()
            endian = (match.group("endian") or "be").lower()
            name = match.group("name")
            prefix = "<" if endian == "le" else ">"
            table = {
                "u8": ("B", 1),
                "i8": ("b", 1),
                "u16": ("H", 2),
                "i16": ("h", 2),
                "u32": ("I", 4),
                "i32": ("i", 4),
                "f32": ("f", 4),
                "f64": ("d", 8),
            }
            code, size = table[kind]
            fields.append(_HexField(name=name, fmt=prefix + code, size=size))
        if not fields:
            raise ValueError("hex template needs at least one typed field")
        total = len(header) + sum(field.size for field in fields)
        return cls(header=bytes(header), fields=tuple(fields), size=total)

    def decode_at(self, data: bytes, offset: int) -> dict[str, float] | None:
        if offset < 0 or offset + self.size > len(data):
            return None
        if self.header and data[offset : offset + len(self.header)] != self.header:
            return None
        cursor = offset + len(self.header)
        values: dict[str, float] = {}
        for field in self.fields:
            chunk = data[cursor : cursor + field.size]
            if len(chunk) != field.size:
                return None
            try:
                raw = struct.unpack(field.fmt, chunk)[0]
            except struct.error:
                return None
            value = float(raw)
            if not math.isfinite(value):
                return None
            values[field.name] = value
            cursor += field.size
        return values


class StudioFrameParser:
    """Incremental parser. Incomplete frames stay in the buffer."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.names: list[str] = []
        self.mode: str = "studio"
        self._hex_template: HexStructTemplate | None = None
        self._hex_template_text = ""

    def set_names(self, text: str) -> None:
        self.names = [part.strip() for part in str(text or "").split(",") if part.strip()]

    def set_mode(self, mode: str) -> None:
        value = str(mode or "studio").lower()
        self.mode = value if value in PARSE_MODES else "studio"

    def set_hex_template(self, text: str) -> None:
        text = str(text or "").strip()
        if text == self._hex_template_text:
            return
        self._hex_template_text = text
        if not text:
            self._hex_template = None
            return
        try:
            self._hex_template = HexStructTemplate.parse(text)
        except ValueError:
            self._hex_template = None

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[dict[str, float]]:
        if data:
            self._buffer.extend(data)
        if len(self._buffer) > 65536:
            del self._buffer[:-4096]
        if self.mode == "kv":
            return self._feed_kv()
        if self.mode == "hex":
            return self._feed_hex()
        return self._feed_studio()

    def _feed_studio(self) -> list[dict[str, float]]:
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

    def _feed_kv(self) -> list[dict[str, float]]:
        text = bytes(self._buffer).decode("utf-8", errors="surrogateescape")
        frames: list[dict[str, float]] = []
        consumed = 0
        start = 0
        while True:
            nl = text.find("\n", start)
            if nl < 0:
                break
            line = text[start:nl].rstrip("\r")
            start = nl + 1
            consumed = start
            parsed = _parse_kv_line(line)
            if parsed:
                frames.append(parsed)
        if consumed:
            self._buffer = bytearray(
                text[consumed:].encode("utf-8", errors="surrogateescape")
            )
        return frames

    def _feed_hex(self) -> list[dict[str, float]]:
        template = self._hex_template
        if template is None or len(self._buffer) < template.size:
            return []
        frames: list[dict[str, float]] = []
        data = bytes(self._buffer)
        index = 0
        last_keep = 0
        while index + template.size <= len(data):
            if template.header:
                pos = data.find(template.header, index)
                if pos < 0:
                    # Keep a short suffix in case header is split.
                    keep = max(0, len(data) - max(1, len(template.header) - 1))
                    del self._buffer[:keep]
                    return frames
                index = pos
            decoded = template.decode_at(data, index)
            if decoded is None:
                index += 1
                continue
            frames.append(decoded)
            index += template.size
            last_keep = index
        if last_keep:
            del self._buffer[:last_keep]
        elif len(self._buffer) > template.size * 4:
            # Avoid unbounded growth when header never matches.
            del self._buffer[: len(self._buffer) - template.size]
        return frames

    def _named(self, values: list[float]) -> dict[str, float]:
        named: dict[str, float] = {}
        for index, value in enumerate(values):
            if index < len(self.names):
                named[self.names[index]] = value
            else:
                named[f"f{index + 1}"] = value
        return named
