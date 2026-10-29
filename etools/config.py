"""Application configuration."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("etools.config")


def _app_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "ETools"
    return Path.home() / ".config" / "etools"


def get_config_dir() -> Path:
    return _app_data_dir()


def get_log_dir() -> Path:
    return _app_data_dir() / "logs"


@dataclass
class AppConfig:
    """Persistent user preferences."""

    default_target: str = "cortex_m"
    default_connect_mode: str = "halt"
    last_firmware: str = ""
    last_probe_uid: str = ""
    auto_probe_scan: bool = True
    verify_after_program: bool = True
    log_level: str = "INFO"
    theme: str = "dark"
    language: str = "zh"  # zh | en
    # User-defined MCU targets: [{"name": "...", "label": "...", "vendor": "..."}]
    custom_targets: list = field(default_factory=list)
    # Built-in target names hidden from the UI catalog
    hidden_targets: list = field(default_factory=list)
    # Vendor names hidden from catalog (e.g. "ST", "NXP")
    hidden_vendors: list = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def config_file(self) -> Path:
        return get_config_dir() / "config.json"

    def load(self) -> AppConfig:
        global _load_warning
        path = self.config_file
        if not path.exists():
            return self
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("config root must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            backup = path.with_name(f"config.corrupt-{time.strftime('%Y%m%d-%H%M%S')}.json")
            try:
                os.replace(path, backup)
            except OSError:
                backup = path
            log.warning("config %s is unreadable (%s); defaults in use, kept %s", path, exc, backup)
            _load_warning = str(backup)
            return self
        except OSError as exc:
            log.warning("cannot read config %s: %s", path, exc)
            return self
        _apply_fields(self, data)
        if self._migrate():
            try:
                self.save()
            except OSError as exc:
                log.warning("cannot save migrated config: %s", exc)
        return self

    def _migrate(self) -> bool:
        """Upgrade stale prefs from older builds. Returns True if something changed."""
        extra = dict(self.extra or {})
        changed = False
        # Pre-0.1.4 defaulted clock to 1000 kHz; ship 10000 kHz going forward.
        if int(extra.get("frequency_khz", 0) or 0) == 1000:
            extra["frequency_khz"] = 10000
            changed = True
        if changed:
            self.extra = extra
        return changed

    def save(self) -> None:
        payload = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        _atomic_write(self.config_file, payload)


def _atomic_write(path: Path, payload: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _apply_fields(cfg: AppConfig, data: dict) -> list[str]:
    """Copy known keys whose JSON type matches the field default; return the rejected keys."""
    rejected: list[str] = []
    for key, value in data.items():
        if key not in AppConfig.__dataclass_fields__:
            continue
        current = getattr(cfg, key)
        if isinstance(current, bool) != isinstance(value, bool) or not isinstance(
            value, type(current)
        ):
            log.warning("config field %r has wrong type %s; ignored", key, type(value).__name__)
            rejected.append(key)
            continue
        setattr(cfg, key, value)
    return rejected


_config: AppConfig | None = None
_load_warning = ""


def take_load_warning() -> str:
    """Path of a corrupt config moved aside during load (once), else empty."""
    global _load_warning
    text, _load_warning = _load_warning, ""
    return text


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig().load()
    return _config


def save_config() -> None:
    if _config is not None:
        try:
            _config.save()
        except OSError:
            # Preferences are best-effort; a read-only profile must not break UI actions.
            return


def export_config(dest_path: str | Path) -> None:
    """Write a JSON snapshot of the current config to *dest_path*."""
    cfg = get_config()
    _atomic_write(Path(dest_path), json.dumps(asdict(cfg), indent=2, ensure_ascii=False))


def import_config(src_path: str | Path) -> None:
    """Replace config contents from a JSON snapshot and persist.

    Raises ValueError when the file is not a valid config; the current
    config is left untouched in that case.
    """
    global _config
    try:
        data = json.loads(Path(src_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    cfg = AppConfig()
    rejected = _apply_fields(cfg, data)
    if rejected:
        raise ValueError("wrong value type for: " + ", ".join(rejected))
    cfg.save()
    _config = cfg
