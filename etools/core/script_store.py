"""Named Lua script files under the user config directory."""

from __future__ import annotations

import re
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
        path.unlink()
        return True
    return False


def rename_script(old: str, new: str) -> Path:
    src = script_path(old)
    dst = script_path(new)
    if not src.is_file():
        raise FileNotFoundError(old)
    if src != dst and dst.exists():
        raise FileExistsError(new)
    src.rename(dst)
    return dst
