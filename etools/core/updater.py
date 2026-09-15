"""GitHub Releases update check & download (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from etools import __version__
from etools.logger import get_logger

log = get_logger("updater")

GITHUB_OWNER = "youzhouchang"
GITHUB_REPO = "ETools"
REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"{REPO_URL}/releases/latest"
USER_AGENT = f"ETools/{__version__} (+{RELEASES_PAGE})"
_TIMEOUT_S = 8
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class UpdateInfo:
    """Result of a successful remote check (may or may not be newer)."""

    current: str
    latest: str
    is_newer: bool
    html_url: str = RELEASES_PAGE
    body: str = ""
    assets: list[dict] = field(default_factory=list)

    @property
    def download_urls(self) -> list[str]:
        urls = []
        for a in self.assets:
            u = a.get("browser_download_url")
            if u:
                urls.append(str(u))
        return urls


def parse_version(text: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' / '1.2.3-rc1' into comparable ints (pre-release ignored)."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest_release(timeout: float = _TIMEOUT_S) -> dict:
    req = urllib.request.Request(
        LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def check_for_update(current: str | None = None) -> UpdateInfo | None:
    """Return UpdateInfo if GitHub responded; None on network/API failure."""
    cur = current or __version__
    try:
        data = fetch_latest_release()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.info("update check failed: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never break the app on update check
        log.info("update check unexpected error: %s", exc)
        return None

    tag = str(data.get("tag_name") or data.get("name") or "")
    if not tag:
        return None
    return UpdateInfo(
        current=cur,
        latest=tag.lstrip("vV"),
        is_newer=is_newer(tag, cur),
        html_url=str(data.get("html_url") or RELEASES_PAGE),
        body=str(data.get("body") or "").strip(),
        assets=list(data.get("assets") or []),
    )


def _asset_name(asset: dict) -> str:
    return str(asset.get("name") or asset.get("browser_download_url") or "")


def detect_platform() -> str:
    """Return a short platform key: win / linux / mac / other."""
    s = sys.platform
    if s.startswith("win"):
        return "win"
    if s.startswith("linux"):
        return "linux"
    if s == "darwin":
        return "mac"
    return "other"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path | None:
    """Directory of the running app when frozen; None for source runs."""
    if not is_frozen():
        return None
    return Path(sys.executable).resolve().parent


def preferred_asset_kind() -> str:
    """setup | portable — pick the package that matches how this build runs."""
    if not is_frozen():
        return "setup"
    d = app_dir()
    if d is None:
        return "setup"
    path = str(d).lower().replace("/", "\\")
    if "program files" in path:
        return "setup"
    # Portable onedir sits anywhere else next to ETools.exe/_internal
    return "portable"


def pick_best_asset(
    assets: list[dict], plat: str | None = None, kind: str | None = None
) -> dict | None:
    """Choose the preferred installer/package for the current OS/runtime.

    Windows installed: setup EXE; Windows portable: portable ZIP
    Linux: AppImage > tar.gz > deb
    macOS: dmg > zip
    """
    if not assets:
        return None
    p = plat or detect_platform()
    k = kind or preferred_asset_kind()

    def score(name: str) -> int:
        n = name.lower()
        if p == "win":
            if n.endswith(".exe") and "setup" in n:
                return 0 if k != "portable" else 2
            if "portable" in n and n.endswith(".zip"):
                return 0 if k == "portable" else 1
            if n.endswith(".exe") or n.endswith(".msi"):
                return 3
            if n.endswith(".zip"):
                return 4
            return 100
        if p == "linux":
            if n.endswith(".appimage"):
                return 0
            if n.endswith(".tar.gz") or n.endswith(".tgz"):
                return 1
            if n.endswith(".deb") or n.endswith(".rpm"):
                return 2
            return 100
        if p == "mac":
            if n.endswith(".dmg"):
                return 0
            if n.endswith(".zip") or n.endswith(".pkg"):
                return 1
            return 100
        return 50

    best: dict | None = None
    best_score = 1000
    for a in assets:
        s = score(_asset_name(a))
        if s < best_score:
            best, best_score = a, s
    if best_score >= 100:
        # No OS-matched asset — fall back to the first one with a URL.
        for a in assets:
            if a.get("browser_download_url"):
                return a
        return assets[0] if assets else None
    return best


def default_save_name(asset: dict) -> str:
    name = _asset_name(asset)
    if name:
        return Path(name).name
    return "etools-update.bin"


def download_file(
    url: str,
    dest: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
    chunk: int = _CHUNK,
) -> Path:
    """Download *url* to *dest*. Calls progress(received, total) while running.

    total may be 0 when the server omits Content-Length.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    received = 0
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_len = resp.headers.get("Content-Length")
            try:
                total = int(raw_len) if raw_len else 0
            except ValueError:
                total = 0
            if progress:
                progress(0, total)
            with open(tmp, "wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    received += len(buf)
                    if progress:
                        progress(received, total)
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return dest


def can_auto_install(path: Path | str | None = None) -> bool:
    """True when *path* (or the preferred asset) can be applied without a browser."""
    if not is_frozen():
        return False
    p = Path(path) if path else None
    if p is None:
        # Any preferred package for this runtime can usually auto-apply.
        return detect_platform() in ("win", "linux")
    n = p.name.lower()
    plat = detect_platform()
    if plat == "win":
        return n.endswith(".exe") or n.endswith(".zip")
    if plat == "linux":
        return n.endswith(".appimage")
    return False


def apply_update(package: Path) -> str:
    """Launch auto-upgrade for a downloaded package. Caller should quit the app.

    Returns a short kind: "installer" | "portable" | "appimage".
    Raises OSError/RuntimeError on failure.
    """
    package = Path(package)
    if not package.is_file():
        raise FileNotFoundError(str(package))
    plat = detect_platform()
    name = package.name.lower()

    if plat == "win" and name.endswith(".exe"):
        return _apply_windows_installer(package)
    if plat == "win" and name.endswith(".zip"):
        return _apply_windows_portable_zip(package)
    if plat == "linux" and name.endswith(".appimage"):
        return _apply_linux_appimage(package)
    raise RuntimeError(f"unsupported package: {package.name}")


def _apply_windows_installer(installer: Path) -> str:
    import subprocess

    args = [
        str(installer),
        # /SILENT: auto-run without wizard, but keep the progress window visible
        "/SILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/RESTARTAPPLICATIONS",
    ]
    # Inno Setup: unattended install, close running app, do not reboot the machine.
    subprocess.Popen(args, cwd=str(installer.parent), shell=False)
    return "installer"


def _apply_windows_portable_zip(zip_path: Path) -> str:
    """Extract zip to temp, wait for this process to exit, mirror into app dir, relaunch."""
    import subprocess
    import tempfile

    target = app_dir()
    if target is None:
        raise RuntimeError("not a frozen app")
    exe_name = Path(sys.executable).name
    pid = os.getpid()
    work = Path(tempfile.mkdtemp(prefix="ETools_upd_"))
    script = work / "upgrade.cmd"
    # CMD script: wait → extract → robocopy mirror → start → cleanup
    script_body = f"""@echo off
setlocal EnableExtensions
set "APP_DIR={target}"
set "ZIP={zip_path}"
set "WORK={work}"
set "EXE={exe_name}"
set "PID={pid}"

:wait
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul 2>&1
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%WORK%\\x' -Force"
if not exist "%WORK%\\x" exit /b 1

set "SRC=%WORK%\\x"
if exist "%WORK%\\x\\ETools\\%EXE%" set "SRC=%WORK%\\x\\ETools"

robocopy "%SRC%" "%APP_DIR%" /E /PURGE /R:2 /W:1 /NFL /NDL /NJH /NJS >nul
start "" "%APP_DIR%\\%EXE%"

ping -n 3 127.0.0.1 >nul
rd /s /q "%WORK%" >nul 2>&1
exit /b 0
"""
    script.write_text(script_body, encoding="utf-8")
    # CreateNoWindow / DETACHED so it survives app exit
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        cwd=str(work),
        creationflags=creationflags,
        close_fds=True,
    )
    return "portable"


def _apply_linux_appimage(new_image: Path) -> str:
    """Replace the running AppImage in place and relaunch."""
    import subprocess

    current = Path(sys.executable).resolve()
    if not current.name.endswith(".AppImage") and "appimage" not in str(current).lower():
        raise RuntimeError("current binary is not an AppImage")
    target = current
    bak = current.with_suffix(current.suffix + ".bak")
    try:
        if bak.exists():
            bak.unlink()
        current.rename(bak)
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    try:
        shutil.copy2(new_image, target)
        os.chmod(target, os.stat(target).st_mode | 0o111)
    except OSError as exc:
        try:
            if target.exists():
                target.unlink()
            bak.rename(current)
        except OSError:
            pass
        raise RuntimeError(str(exc)) from exc
    subprocess.Popen([str(target)], cwd=str(target.parent), start_new_session=True)
    try:
        bak.unlink()
    except OSError:
        pass
    return "appimage"
