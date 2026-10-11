"""Dashboard project: widget specs bound to a frame index or a JSON key."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

WIDGET_TYPES = ("value", "gauge", "bar", "plot", "multiplot")


@dataclass
class DashWidget:
    type: str = "value"
    title: str = ""
    unit: str = ""
    minimum: float = 0.0
    maximum: float = 100.0
    bind: str = "1"

    def binds(self) -> list[str]:
        return [part.strip() for part in self.bind.split(",") if part.strip()]


def lookup(frame: dict[str, float], bind: str) -> float | None:
    """Digit binds are 1-based positions. Anything else is a JSON key."""
    text = str(bind or "").strip()
    if not text or not frame:
        return None
    if text.isdigit():
        index = int(text) - 1
        values = list(frame.values())
        if 0 <= index < len(values):
            value = float(values[index])
            return value if math.isfinite(value) else None
        return None
    if text in frame:
        value = float(frame[text])
        return value if math.isfinite(value) else None
    return None


def project_to_json(widgets: list[DashWidget]) -> str:
    payload = {"version": 1, "widgets": [asdict(item) for item in widgets]}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_from_json(text: str) -> list[DashWidget]:
    raw = json.loads(text or "{}")
    items = raw.get("widgets", []) if isinstance(raw, dict) else []
    widgets: list[DashWidget] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "value")
        if kind not in WIDGET_TYPES:
            kind = "value"
        minimum_raw = item.get("minimum", 0)
        maximum_raw = item.get("maximum", 100)
        minimum = float(0 if minimum_raw is None else minimum_raw)
        maximum = float(100 if maximum_raw is None else maximum_raw)
        if not math.isfinite(minimum) or not math.isfinite(maximum):
            raise ValueError("widget range must be finite")
        widgets.append(
            DashWidget(
                type=kind,
                title=str(item.get("title") or ""),
                unit=str(item.get("unit") or ""),
                minimum=minimum,
                maximum=maximum,
                bind=str(item.get("bind") or "1"),
            )
        )
    return widgets
