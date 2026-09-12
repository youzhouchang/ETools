"""GitHub Releases update check (stdlib only)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from etools import __version__
from etools.logger import get_logger

log = get_logger("updater")

GITHUB_OWNER = "youzhouchang"
GITHUB_REPO = "ETools"
LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"ETools/{__version__} (+{RELEASES_PAGE})"
_TIMEOUT_S = 8


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
        return [str(a.get("browser_download_url") or "") for a in self.assets if a.get("browser_download_url")]


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
