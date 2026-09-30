"""Named Lua script files under the user config directory."""

from __future__ import annotations

import re
import time
from pathlib import Path

from etools import config as config_mod

_SUFFIX = ".lua"
_NAME_RE = re.compile(r"^[\w\-. ]{1,64}$")


def scripts_dir() -> Path:
    path = config_mod.get_config_dir() / "scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    raw = str(name).strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(f"invalid script name: {name!r}")
    name = Path(raw).name
    if not name or not _NAME_RE.match(name):
        raise ValueError(f"invalid script name: {name!r}")
    if not name.endswith(_SUFFIX):
        name += _SUFFIX
    return name


def list_scripts() -> list[str]:
    """Script names without directory, sorted, extension stripped."""
    out: list[str] = []
    for path in sorted(scripts_dir().glob(f"*{_SUFFIX}")):
        if path.is_file():
            out.append(path.stem)
    return out


def script_path(name: str) -> Path:
    return scripts_dir() / _safe_name(name)


def load_script(name: str) -> str:
    return script_path(name).read_text(encoding="utf-8")


def save_script(name: str, source: str) -> Path:
    path = script_path(name)
    path.write_text(str(source), encoding="utf-8")
    return path


def delete_script(name: str) -> bool:
    path = script_path(name)
    if path.is_file():
        trash = scripts_dir() / "trash"
        trash.mkdir(exist_ok=True)
        path.rename(trash / f"{time.time_ns()}-{path.name}")
        return True
    return False


def restore_last_script() -> Path | None:
    trash = scripts_dir() / "trash"
    entries = sorted(trash.glob("*.lua")) if trash.exists() else []
    if not entries:
        return None
    source = entries[-1]
    dest = script_path(source.name.split("-", 1)[1])
    if dest.exists():
        raise FileExistsError(dest.name)
    source.rename(dest)
    return dest


def rename_script(old: str, new: str) -> Path:
    src = script_path(old)
    dst = script_path(new)
    if not src.is_file():
        raise FileNotFoundError(old)
    if src != dst and dst.exists():
        raise FileExistsError(new)
    src.rename(dst)
    return dst
