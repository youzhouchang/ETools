"""Persist per-tool UI preferences into AppConfig.extra["tools"]."""

from __future__ import annotations

from typing import Any

from etools.config import get_config, save_config


def load_tool_prefs(tool_id: str) -> dict[str, Any]:
    cfg = get_config()
    tools = cfg.extra.get("tools")
    if not isinstance(tools, dict):
        return {}
    data = tools.get(tool_id)
    return dict(data) if isinstance(data, dict) else {}


def save_tool_prefs(tool_id: str, data: dict[str, Any]) -> None:
    """Merge `data` into the tool's saved prefs. Never stores secrets."""
    cfg = get_config()
    tools = dict(cfg.extra.get("tools") or {})
    current = dict(tools.get(tool_id) or {})
    for key, value in data.items():
        if value is None:
            continue
        if key.lower() in {"password", "passwd", "secret", "token"}:
            continue
        current[key] = value
    tools[tool_id] = current
    cfg.extra["tools"] = tools
    save_config()
