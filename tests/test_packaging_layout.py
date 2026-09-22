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
