"""GitHub Releases update check & download (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import tempfile
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


def _is_deb_install_path(path: str) -> bool:
    """Return whether ``path`` is the Linux deb binary or its /opt install tree."""
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("/opt/etools/") or normalized == "/usr/bin/etools"


def preferred_asset_kind() -> str:
    """Return the package type used by the running application."""
    if not is_frozen():
        return "source"
    platform = detect_platform()
    if platform == "linux":
        if os.environ.get("APPIMAGE"):
            return "appimage"
        directory = app_dir()
        marker = directory / ".etools-package-kind" if directory is not None else None
        if marker is not None:
            try:
                marked_kind = marker.read_text(encoding="utf-8").strip().lower()
            except OSError:
                marked_kind = ""
            if marked_kind in {"appimage", "deb", "portable"}:
                return marked_kind
        # Keep the original path. On Windows, Path.resolve() anchors a POSIX
        # absolute path to a drive, so the deb prefix would no longer match.
        if _is_deb_install_path(sys.executable) or _is_deb_install_path(
            str(Path(sys.executable).resolve())
        ):
            return "deb"
        return "portable"
    d = app_dir()
    if d is None:
        return "source"
    path = str(d).lower().replace("/", "\\")
    if platform == "win" and "program files" in path:
        return "setup"
    if platform == "win":
        return "portable"
    return "source"


def pick_best_asset(
    assets: list[dict], plat: str | None = None, kind: str | None = None
) -> dict | None:
    """Choose the preferred installer/package for the current OS/runtime.

    The selected asset must match the package type currently in use. This
    prevents a deb install from being replaced with an AppImage, or an
    installed Windows build from being replaced with a portable archive.
    """
    if not assets:
        return None
    p = plat or detect_platform()
    k = kind or preferred_asset_kind()

    def score(name: str) -> int:
        n = name.lower()
        if p == "win":
            if k in {"setup", "source"} and n.endswith(".exe") and "setup" in n:
                return 0
            if k == "portable" and "portable" in n and n.endswith(".zip"):
                return 0
            return 100
        if p == "linux":
            if k == "appimage" and n.endswith(".appimage"):
                return 0
            if k == "portable" and (n.endswith(".tar.gz") or n.endswith(".tgz")):
                return 0
            if k == "deb" and n.endswith(".deb"):
                return 0
            if k == "source" and n.endswith(".deb"):
                return 0
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
    return best if best_score < 100 else None


def default_save_name(asset: dict) -> str:
    name = _asset_name(asset)
    if name:
        return Path(name).name
    return "etools-update.bin"


class ChecksumMismatch(RuntimeError):
    """Downloaded package does not match the published SHA-256."""


_SHA256_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+\*?(\S+)\s*$")


def expected_sha256(asset: dict, release_body: str = "") -> str:
    """Published SHA-256 for *asset*, from the API ``digest`` or the release notes."""
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        value = digest.split(":", 1)[1].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    name = Path(_asset_name(asset)).name
    for line in (release_body or "").splitlines():
        m = _SHA256_RE.match(line)
        if m and Path(m.group(2)).name == name:
            return m.group(1).lower()
    return ""


def download_file(
    url: str,
    dest: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    timeout: float = 60.0,
    chunk: int = _CHUNK,
    sha256: str = "",
) -> Path:
    """Download *url* to *dest*. Calls progress(received, total) while running.

    total may be 0 when the server omits Content-Length. When *sha256* is
    given the file is only kept if its digest matches.
    """
    import hashlib

    hasher = hashlib.sha256()
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
                    hasher.update(buf)
                    received += len(buf)
                    if progress:
                        progress(received, total)
        if sha256 and hasher.hexdigest() != sha256.lower():
            raise ChecksumMismatch(
                f"SHA-256 mismatch: expected {sha256.lower()}, got {hasher.hexdigest()}"
            )
        if not sha256:
            log.warning("no published SHA-256 for %s; integrity not verified", url)
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
        return preferred_asset_kind() in {"setup", "portable", "appimage", "deb"}
    n = p.name.lower()
    plat = detect_platform()
    if plat == "win":
        kind = preferred_asset_kind()
        return (kind == "setup" and n.endswith(".exe")) or (
            kind == "portable" and n.endswith(".zip")
        )
    if plat == "linux":
        kind = preferred_asset_kind()
        if kind == "appimage":
            return n.endswith(".appimage")
        if kind == "portable":
            return n.endswith(".tar.gz") or n.endswith(".tgz")
        if kind == "deb":
            return n.endswith(".deb") and bool(
                shutil.which("pkexec") and shutil.which("apt-get")
            )
    return False


def apply_update(package: Path) -> str:
    """Launch auto-upgrade for a downloaded package. Caller should quit the app.

    Returns a short kind: "installer" | "portable" | "appimage" | "deb".
    Raises OSError/RuntimeError on failure.
    """
    package = Path(package)
    if not package.is_file():
        raise FileNotFoundError(str(package))
    plat = detect_platform()
    name = package.name.lower()
    kind = preferred_asset_kind()

    if plat == "win" and kind == "setup" and name.endswith(".exe"):
        return _apply_windows_installer(package)
    if plat == "win" and kind == "portable" and name.endswith(".zip"):
        return _apply_windows_portable_zip(package)
    if plat == "linux" and kind == "appimage" and name.endswith(".appimage"):
        return _apply_linux_appimage(package)
    if plat == "linux" and kind == "deb" and name.endswith(".deb"):
        return _apply_linux_deb(package)
    if plat == "linux" and kind == "portable" and (
        name.endswith(".tar.gz") or name.endswith(".tgz")
    ):
        return _apply_linux_portable(package)
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

    current_path = os.environ.get("APPIMAGE", "")
    if not current_path:
        raise RuntimeError("current binary is not an AppImage")
    current = Path(current_path).expanduser().resolve()
    if not current.is_file():
        raise RuntimeError("current AppImage does not exist")
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


def _spawn_linux_upgrade(script_body: str) -> None:
    import subprocess

    work = Path(tempfile.mkdtemp(prefix="ETools_upd_"))
    script = work / "upgrade.sh"
    script.write_text(script_body, encoding="utf-8")
    script.chmod(0o700)
    subprocess.Popen(
        ["/bin/sh", str(script)],
        cwd=str(work),
        start_new_session=True,
        close_fds=True,
    )


def _apply_linux_deb(package: Path) -> str:
    """Install a deb with PolicyKit after this process exits, then relaunch."""
    pkexec = shutil.which("pkexec")
    apt_get = shutil.which("apt-get")
    if not pkexec or not apt_get:
        raise RuntimeError("pkexec or apt-get is not available")
    pid = os.getpid()
    package_q = shlex.quote(str(package.resolve()))
    pkexec_q = shlex.quote(pkexec)
    apt_get_q = shlex.quote(apt_get)
    _spawn_linux_upgrade(
        f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 1; done
if {pkexec_q} {apt_get_q} install -y {package_q}; then
  nohup /usr/bin/etools >/dev/null 2>&1 &
fi
rm -rf -- "$(dirname -- "$0")"
"""
    )
    return "deb"


def _apply_linux_portable(package: Path) -> str:
    """Replace a portable onedir from its matching tar archive and relaunch."""
    target = app_dir()
    if target is None:
        raise RuntimeError("not a frozen app")
    if not os.access(target, os.W_OK):
        raise RuntimeError(f"application directory is not writable: {target}")
    pid = os.getpid()
    exe_name = Path(sys.executable).name
    package_q = shlex.quote(str(package.resolve()))
    target_q = shlex.quote(str(target))
    exe_q = shlex.quote(exe_name)
    _spawn_linux_upgrade(
        f"""#!/bin/sh
set -eu
WORK="$(dirname -- "$0")"
while kill -0 {pid} 2>/dev/null; do sleep 1; done
mkdir -p "$WORK/x"
tar -xzf {package_q} -C "$WORK/x"
SRC="$WORK/x/ETools"
test -x "$SRC/{exe_q}"
find {target_q} -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} +
cp -a "$SRC/." {target_q}/
nohup {target_q}/{exe_q} >/dev/null 2>&1 &
rm -rf -- "$WORK"
"""
    )
    return "portable"
