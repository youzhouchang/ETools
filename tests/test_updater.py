"""Update checker unit tests (no network)."""

from __future__ import annotations

from pathlib import Path

from etools.core.updater import (
    can_auto_install,
    default_save_name,
    is_frozen,
    is_newer,
    parse_version,
    pick_best_asset,
)
from etools.ui.markdown import markdown_to_html


def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("2.0") == (2, 0, 0)
    assert parse_version("garbage") == (0, 0, 0)


def test_is_newer():
    assert is_newer("0.2.0", "0.1.0")
    assert is_newer("v0.1.1", "0.1.0")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.0.9", "0.1.0")


def _assets(*names: str) -> list[dict]:
    return [
        {"name": n, "browser_download_url": f"https://example.com/{n}"} for n in names
    ]


def test_pick_best_asset_windows():
    assets = _assets(
        "ETools-portable-0.2.0-win64.zip",
        "ETools-setup-0.2.0-win64.exe",
        "ETools-0.2.0-x86_64.AppImage",
    )
    best = pick_best_asset(assets, plat="win", kind="setup")
    assert best is not None
    assert best["name"] == "ETools-setup-0.2.0-win64.exe"
    portable = pick_best_asset(assets, plat="win", kind="portable")
    assert portable is not None
    assert portable["name"] == "ETools-portable-0.2.0-win64.zip"


def test_can_auto_install_source_run():
    # Unit tests always run from source — auto-install must be off.
    assert not is_frozen()
    assert not can_auto_install()


def test_pick_best_asset_linux():
    assets = _assets(
        "ETools-portable-0.2.0-linux-x86_64.tar.gz",
        "etools_0.2.0_amd64.deb",
        "ETools-0.2.0-x86_64.AppImage",
    )
    best = pick_best_asset(assets, plat="linux")
    assert best is not None
    assert best["name"].endswith(".AppImage")


def test_pick_best_asset_empty():
    assert pick_best_asset([], plat="win") is None


def test_default_save_name():
    asset = {"name": "ETools-setup-0.2.0-win64.exe", "browser_download_url": "x"}
    assert default_save_name(asset) == "ETools-setup-0.2.0-win64.exe"
    assert Path(default_save_name({})).name  # non-empty fallback


def test_markdown_to_html_basic():
    md = """## Downloads
- Windows portable ZIP
- **Bold** item with `code`

See [releases](https://github.com/youzhouchang/ETools/releases).

```
sha256 abc
```
"""
    html = markdown_to_html(md)
    assert "<h2>Downloads</h2>" in html
    assert "<ul>" in html
    assert "<strong>Bold</strong>" in html
    assert "<code>code</code>" in html
    assert 'href="https://github.com/youzhouchang/ETools/releases"' in html
    assert "<pre><code>" in html
    assert "sha256 abc" in html
