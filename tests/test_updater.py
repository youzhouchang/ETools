"""Update checker unit tests (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from etools.core.updater import (
    apply_update,
    can_auto_install,
    default_save_name,
    is_frozen,
    is_newer,
    parse_version,
    pick_best_asset,
    preferred_asset_kind,
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
    source = pick_best_asset(assets, plat="win", kind="source")
    assert source is not None
    assert source["name"] == "ETools-setup-0.2.0-win64.exe"


def test_can_auto_install_source_run():
    # Unit tests always run from source — auto-install must be off.
    assert not is_frozen()
    assert not can_auto_install()


def test_pick_best_asset_linux_matches_install_kind():
    assets = _assets(
        "ETools-portable-0.2.0-linux-x86_64.tar.gz",
        "ETools-0.2.0-amd64.deb",
        "ETools-0.2.0-x86_64.AppImage",
    )
    expected = {
        "appimage": ".AppImage",
        "deb": ".deb",
        "portable": ".tar.gz",
    }
    for kind, suffix in expected.items():
        best = pick_best_asset(assets, plat="linux", kind=kind)
        assert best is not None
        assert best["name"].endswith(suffix)


def test_pick_best_asset_does_not_fall_back_to_another_package_type():
    assets = _assets("ETools-0.2.0-x86_64.AppImage")
    assert pick_best_asset(assets, plat="linux", kind="deb") is None
    assert pick_best_asset(assets, plat="linux", kind="portable") is None


def test_preferred_linux_asset_kind(tmp_path, monkeypatch):
    import etools.core.updater as updater

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", "/tmp/ETools.AppImage")
    assert preferred_asset_kind() == "appimage"

    monkeypatch.delenv("APPIMAGE")
    marker = tmp_path / ".etools-package-kind"
    marker.write_text("deb", encoding="utf-8")
    monkeypatch.setattr(updater, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(updater.sys, "executable", "/home/user/ETools/ETools")
    assert preferred_asset_kind() == "deb"

    marker.unlink()
    monkeypatch.setattr(updater.sys, "executable", "/opt/etools/ETools")
    assert preferred_asset_kind() == "deb"

    monkeypatch.setattr(updater.sys, "executable", "/home/user/ETools/ETools")
    assert preferred_asset_kind() == "portable"


def test_apply_update_rejects_cross_package_type(tmp_path, monkeypatch):
    import etools.core.updater as updater

    package = tmp_path / "ETools.AppImage"
    package.write_bytes(b"image")
    monkeypatch.setattr(updater, "detect_platform", lambda: "linux")
    monkeypatch.setattr(updater, "preferred_asset_kind", lambda: "deb")
    with pytest.raises(RuntimeError, match="unsupported package"):
        apply_update(package)


def test_deb_auto_install_requires_matching_runtime_and_helpers(monkeypatch):
    import etools.core.updater as updater

    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "detect_platform", lambda: "linux")
    monkeypatch.setattr(updater, "preferred_asset_kind", lambda: "deb")
    monkeypatch.setattr(updater.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert can_auto_install("ETools-0.6.1-amd64.deb")
    assert not can_auto_install("ETools-0.6.1-x86_64.AppImage")


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


def test_markdown_to_html_table():
    md = """## Downloads

| Asset | Platform |
|-------|----------|
| `ETools-0.2.0-amd64.deb` | Linux |
| `ETools-setup-0.2.0-win64.exe` | Windows |
"""
    html = markdown_to_html(md)
    assert "<table>" in html
    assert "<th>Asset</th>" in html
    assert "<th>Platform</th>" in html
    assert "<code>ETools-0.2.0-amd64.deb</code>" in html
    assert "<td>Linux</td>" in html
    assert "<td>Windows</td>" in html
    # Table rows should not be dumped as paragraphs
    assert "<p>|" not in html
