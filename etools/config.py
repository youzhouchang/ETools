"""Application configuration."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
        path = self.config_file
        if not path.exists():
            return self
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)
        except (json.JSONDecodeError, OSError):
            pass
        if self._migrate():
            try:
                self.save()
            except OSError:
                pass
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
        path = self.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=path.parent)
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


_config: AppConfig | None = None


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
