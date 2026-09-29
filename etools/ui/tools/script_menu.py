"""Shared 'Run script' popup used by every tool toolbar."""

from __future__ import annotations

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QWidget

from etools.core import script_store
from etools.i18n import tr


def exec_script_menu(parent: QWidget) -> str | None:
    """Show saved scripts; return the chosen name (or None)."""
    from etools.core.script_samples import ensure_samples

    ensure_samples()
    menu = QMenu(parent)
    names = script_store.list_scripts()
    if not names:
        menu.addAction(tr("script.none"))
        menu.exec(QCursor.pos())
        return None
    for name in names:
        menu.addAction(name, lambda n=name: _run(n))
    menu.exec(QCursor.pos())
    return None


def _run(name: str) -> None:
    from etools.logger import get_logger
    from etools.ui.script_service import script_service

    try:
        script_service().run_named(name)
    except Exception as exc:  # noqa: BLE001
        get_logger("script").exception("run %s failed: %s", name, exc)
