"""Guard packaging layout so nested packages are not silently dropped.

Regression: root `.gitignore` had `tools/` which swallowed `etools/ui/tools/`.
CI installed a wheel without that package → ModuleNotFoundError on import.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TOOL_MODULES = (
    "__init__.py",
    "base.py",
    "program_page.py",
    "serial_page.py",
    "ethernet_page.py",
    "mqtt_page.py",
    "map_page.py",
    "dashboard_page.py",
    "can_page.py",
    "terminal_page.py",
    "sftp_panel.py",
)


def test_ui_tools_sources_present():
    tools_dir = ROOT / "etools" / "ui" / "tools"
    assert tools_dir.is_dir(), "etools/ui/tools missing from tree"
    for name in EXPECTED_TOOL_MODULES:
        assert (tools_dir / name).is_file(), f"missing {name}"


def test_ui_tools_importable():
    import etools.ui.tools as tools

    for name in (
        "ToolPage",
        "ProgramPage",
        "SerialPage",
        "EthernetPage",
        "MqttPage",
        "MapPage",
        "DashboardPage",
        "CanPage",
        "TerminalPage",
        "SftpPanel",
    ):
        assert hasattr(tools, name), name


def test_setuptools_finds_all_packages():
    from setuptools import find_packages

    found = set(find_packages(include=["etools*"]))
    for pkg in (
        "etools",
        "etools.core",
        "etools.ui",
        "etools.ui.tools",
        "etools.ui.widgets",
        "etools.ui.forms",
    ):
        assert pkg in found, f"setuptools missing package: {pkg}"


def test_packaging_installs_project_dependencies():
    linux = (ROOT / "packaging" / "package_linux.sh").read_text(encoding="utf-8")
    windows = (ROOT / "packaging" / "package_windows.bat").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "etools.spec").read_text(encoding="utf-8")
    assert '.[packaging]' in linux
    assert '.[packaging]' in windows
    assert 'collect_submodules("can")' in spec
    assert 'collect_submodules("lupa")' in spec


def test_pyproject_version_matches_app_version():
    import re
    from pathlib import Path

    from etools import __version__

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match and match.group(1) == __version__
