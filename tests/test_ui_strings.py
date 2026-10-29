"""UI text must come from the i18n catalogs, not string literals."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1] / "etools" / "ui"
_CJK = re.compile(r"[\u4e00-\u9fff]")
# Search keywords for goto_tab and bundled Lua templates are not UI text.
_ALLOWED = {
    ("tools/program_page.py", "变量"),
    ("tools/program_page.py", "诊断"),
}
_ALLOWED_FILES = {"tools/script_page.py"}


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def test_ui_code_has_no_hardcoded_chinese() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in _ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in skip or not _CJK.search(node.value):
                continue
            if (rel, node.value) in _ALLOWED:
                continue
            offenders.append(f"{rel}:{node.lineno}: {node.value!r}")
    assert not offenders, "\n".join(offenders)


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_program_panels_switch_to_english(qapp, monkeypatch) -> None:
    from etools import i18n
    from etools.ui.tools.program_page import ProgramPage

    monkeypatch.setattr(i18n, "current_language", lambda: i18n.LANG_EN)
    page = ProgramPage()
    page.retranslate()
    texts = [
        page.rtt_panel.send_btn.text(),
        page.rtt_panel.send_edit.placeholderText(),
        page.swo_panel.start_btn.text(),
        page.variable_monitor.start_btn.text(),
        page.variable_monitor.mode_combo.itemText(0),
        page.device_manager.vendor_list.item(0).text(),
        page.device_manager.hint.text(),
        page.hex_preview.mem_view.info_label.text(),
    ]
    for text in texts:
        assert text
        assert not _CJK.search(text), text
    page.shutdown()
    page.close()
