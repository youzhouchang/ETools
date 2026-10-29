"""Shared 'Run script' popup used by every tool toolbar."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QWidget

from etools.core import script_store
from etools.i18n import tr


def exec_script_menu(parent: QWidget) -> str | None:
    """Show saved scripts; return the chosen name (or None)."""
    from etools.core.script_samples import ensure_samples
    from etools.ui.script_service import script_service

    ensure_samples()
    menu = QMenu(parent)
    service = script_service()
    if service.running:
        menu.addAction(tr("script.stop"), service.stop)
        menu.addSeparator()
    names = script_store.list_scripts()
    if not names:
        menu.addAction(tr("script.none"))
        menu.exec(QCursor.pos())
        return None
    for name in names:
        menu.addAction(name, lambda n=name: _run(parent, n))
    menu.exec(QCursor.pos())
    return None


def _script_page(widget: QWidget):
    node = widget
    while node is not None:
        page = getattr(node, "script_page", None)
        if page is not None and hasattr(page, "note_toolbar_run"):
            return page
        node = node.parent()
    return None


class MenuRunWatch(QObject):
    """Mirror a toolbar-launched script into that page's monitor."""

    def __init__(self, page: QWidget, name: str) -> None:
        super().__init__(page)
        self._page = page
        self._name = name
        from etools.ui.script_service import script_service

        self._svc = script_service()

    def arm(self) -> None:
        """Connect before the worker starts, or early log lines are missed."""
        self._svc.log.connect(self._on_log)
        self._svc.done.connect(self._on_done)
        self._note(tr("script.running_name", name=self._name))
        page = _script_page(self._page)
        if page is not None:
            page.note_toolbar_run(self._name)

    def fail(self, message: str) -> None:
        self._note(f"{tr('script.failed')}: {message}")
        self._release()

    def _note(self, text: str) -> None:
        traffic = getattr(self._page, "traffic", None)
        if traffic is not None:
            traffic.append_status(text)

    def _on_log(self, message: str) -> None:
        self._note(tr("script.log_line", msg=message))

    def _on_done(self, ok: bool, message: str) -> None:
        if message == "script stopped":
            text = tr("script.stopped")
        elif ok:
            text = tr("script.done")
        else:
            text = tr("script.failed")
            if message:
                text = f"{text}: {message}"
        self._note(text)
        self._release()
        self.deleteLater()

    def _release(self) -> None:
        for signal, slot in (
            (self._svc.log, self._on_log),
            (self._svc.done, self._on_done),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass


def _run(page: QWidget, name: str) -> None:
    from etools.logger import get_logger
    from etools.ui.script_service import script_service

    watch = MenuRunWatch(page, name)
    watch.arm()
    try:
        script_service().run_named(name)
    except Exception as exc:  # noqa: BLE001
        get_logger("script").exception("run %s failed: %s", name, exc)
        watch.fail(str(exc))
