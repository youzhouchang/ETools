"""Named, portable project settings without credentials or window preferences."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from etools.config import get_config, save_config

PROGRAM_KEYS = ("wire_protocol", "reset_type", "frequency_khz")


def sanitize(value):
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if not any(token in key.lower() for token in ("password", "secret", "token"))
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return copy.deepcopy(value)


def snapshot() -> dict:
    cfg = get_config()
    return sanitize(
        {
            "version": 1,
            "target": cfg.default_target,
            "connect_mode": cfg.default_connect_mode,
            "firmware": cfg.last_firmware,
            "verify": cfg.verify_after_program,
            "program": {key: cfg.extra[key] for key in PROGRAM_KEYS if key in cfg.extra},
            "tools": cfg.extra.get("tools", {}),
            "workflow": cfg.extra.get("workflow", {}),
            "script": cfg.extra.get("project_script", ""),
        }
    )


def validate(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Unsupported project profile")
    for key in ("target", "connect_mode", "firmware", "script"):
        if not isinstance(payload.get(key, ""), str):
            raise ValueError(f"Invalid {key}")
    for key in ("tools", "program", "workflow"):
        if not isinstance(payload.get(key, {}), dict):
            raise ValueError(f"Invalid {key}")
    frequency = payload.get("program", {}).get("frequency_khz", 10000)
    if not isinstance(frequency, int) or not 1 <= frequency <= 100000:
        raise ValueError("Invalid probe frequency")
    timeout = payload.get("workflow", {}).get("timeout", 5000)
    if not isinstance(timeout, int) or not 100 <= timeout <= 600000:
        raise ValueError("Invalid workflow timeout")
    for key in ("startup", "command", "expected"):
        if not isinstance(payload.get("workflow", {}).get(key, ""), str):
            raise ValueError(f"Invalid workflow {key}")
    for name, settings in payload.get("tools", {}).items():
        if not isinstance(settings, dict):
            raise ValueError(f"Invalid tool settings: {name}")
    return sanitize(payload)


def profiles() -> dict:
    return copy.deepcopy(get_config().extra.get("projects", {}))


def save_profile(name: str, payload: dict | None = None) -> None:
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("Invalid project name")
    cfg = get_config()
    entries = profiles()
    entries[name] = validate(payload if payload is not None else snapshot())
    cfg.extra["projects"] = entries
    save_config()


def apply_profile(payload: dict) -> None:
    payload = validate(payload)
    cfg = get_config()
    cfg.default_target = payload.get("target", "cortex_m")
    cfg.default_connect_mode = payload.get("connect_mode", "halt")
    cfg.last_firmware = payload.get("firmware", "")
    cfg.verify_after_program = bool(payload.get("verify", True))
    cfg.extra["tools"] = payload.get("tools", {})
    cfg.extra["workflow"] = payload.get("workflow", {})
    cfg.extra["project_script"] = payload.get("script", "")
    for key in PROGRAM_KEYS:
        cfg.extra.pop(key, None)
    cfg.extra.update(
        {key: value for key, value in payload.get("program", {}).items() if key in PROGRAM_KEYS}
    )
    save_config()


def export_profile(path: str | Path, payload: dict) -> None:
    Path(path).write_text(
        json.dumps(validate(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def import_profile(path: str | Path) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))
