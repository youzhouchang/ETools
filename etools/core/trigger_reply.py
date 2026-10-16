"""RX-triggered auto-reply rules for serial (and similar byte streams)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

MAX_RULES = 8
_MAX_BUFFER = 4096


@dataclass
class TriggerRule:
    enabled: bool = False
    mode: str = "text"  # text | hex | regex
    pattern: str = ""
    reply: str = ""
    reply_hex: bool = False
    cooldown_ms: int = 200
    once: bool = False
    last_fire: float = field(default=0.0, repr=False)
    fired: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "pattern": self.pattern,
            "reply": self.reply,
            "reply_hex": self.reply_hex,
            "cooldown_ms": int(self.cooldown_ms),
            "once": self.once,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TriggerRule:
        mode = str(data.get("mode") or "text").lower()
        if mode not in {"text", "hex", "regex"}:
            mode = "text"
        try:
            cooldown = int(data.get("cooldown_ms", 200))
        except (TypeError, ValueError):
            cooldown = 200
        return cls(
            enabled=bool(data.get("enabled")),
            mode=mode,
            pattern=str(data.get("pattern") or ""),
            reply=str(data.get("reply") or ""),
            reply_hex=bool(data.get("reply_hex")),
            cooldown_ms=max(0, cooldown),
            once=bool(data.get("once")),
        )


@dataclass
class TriggerHit:
    index: int
    rule: TriggerRule


class TriggerEngine:
    """Accumulate RX bytes and emit matching reply rules."""

    def __init__(self) -> None:
        self.rules: list[TriggerRule] = [TriggerRule() for _ in range(MAX_RULES)]
        self._buf = bytearray()

    def reset_runtime(self) -> None:
        """Clear match buffer and once/cooldown state without dropping rule text."""
        self._buf.clear()
        for rule in self.rules:
            rule.last_fire = 0.0
            rule.fired = False

    def load_rules(self, items: list | None) -> None:
        rules = [TriggerRule() for _ in range(MAX_RULES)]
        if isinstance(items, list):
            for i, item in enumerate(items[:MAX_RULES]):
                if isinstance(item, dict):
                    rules[i] = TriggerRule.from_dict(item)
        self.rules = rules

    def dump_rules(self) -> list[dict]:
        return [rule.to_dict() for rule in self.rules]

    def feed(self, data: bytes, *, encoding: str = "utf-8") -> list[TriggerHit]:
        if not data:
            return []
        self._buf.extend(data)
        if len(self._buf) > _MAX_BUFFER:
            del self._buf[:-_MAX_BUFFER]
        text = bytes(self._buf).decode(encoding, errors="replace")
        now = time.monotonic()
        hits: list[TriggerHit] = []
        for index, rule in enumerate(self.rules):
            if not rule.enabled or not rule.pattern.strip() or not rule.reply:
                continue
            if rule.once and rule.fired:
                continue
            if rule.cooldown_ms > 0 and rule.last_fire:
                if (now - rule.last_fire) * 1000.0 < rule.cooldown_ms:
                    continue
            if not self._matches(rule, text, bytes(self._buf)):
                continue
            rule.last_fire = now
            rule.fired = True
            hits.append(TriggerHit(index=index, rule=rule))
        return hits

    @staticmethod
    def _matches(rule: TriggerRule, text: str, raw: bytes) -> bool:
        pattern = rule.pattern
        if rule.mode == "hex":
            try:
                needle = bytes.fromhex(pattern.replace(" ", "").replace(",", ""))
            except ValueError:
                return False
            return bool(needle) and needle in raw
        if rule.mode == "regex":
            try:
                return re.search(pattern, text) is not None
            except re.error:
                return False
        return pattern in text
