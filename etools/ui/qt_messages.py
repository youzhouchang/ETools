"""Turn Qt's own warnings into sentences for the log and the status bar.

Qt prints lines such as ``QWidgetWindow ... must be a top level window`` on
stderr. Those names do not say what broke. This bridge keeps one plain
sentence, writes it to the application log, and shows it on the status bar.
"""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QObject, Qt, QtMsgType, Signal, qInstallMessageHandler

from etools.i18n import tr
from etools.logger import get_logger

_HEX = re.compile(r"0x[0-9a-fA-F]+")
_DEDUP_SEC = 30.0
_seen: dict[str, float] = {}
_bridge: _Bridge | None = None

log = get_logger("qt")


def clear_qt_message_cache() -> None:
    _seen.clear()


def describe_qt_warning(message: str) -> tuple[str, bool]:
    """Return ``(i18n key, show on the status bar)``. An empty key is generic."""
    low = message.lower()
    if "must be a top level window" in low:
        if "dash" in low:
            return "qt.toplevel_dash", True
        return "qt.toplevel", True
    graphic = "opengl" in low or "qt3d" in low
    failed = any(word in low for word in ("fail", "error", "unable", "cannot", "could not"))
    if graphic and failed:
        return "qt.gl_fail", True
    return "", False


def _fingerprint(key: str, message: str) -> str:
    if key:
        return key
    return _HEX.sub("0x…", " ".join(message.split()))


def _remember(fingerprint: str) -> bool:
    """True when this warning was already reported a moment ago."""
    now = time.monotonic()
    previous = _seen.get(fingerprint)
    _seen[fingerprint] = now
    return previous is not None and now - previous < _DEDUP_SEC


def _short(message: str) -> str:
    text = _HEX.sub("0x…", " ".join(message.split()))
    if len(text) > 180:
        return text[:177] + "…"
    return text


def _sentence(key: str, detail: str) -> str:
    if key:
        return tr(key)
    return tr("qt.warning", detail=detail)


class _Bridge(QObject):
    """Hop from the Qt message handler onto the GUI thread."""

    report = Signal(str, str, bool, bool)

    def __init__(self) -> None:
        super().__init__()
        self.report.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def _deliver(self, key: str, detail: str, on_status: bool, is_error: bool) -> None:
        text = _sentence(key, detail)
        if is_error:
            log.error(text)
        else:
            log.warning(text)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        for window in app.topLevelWidgets():
            panel = getattr(window, "log_panel", None)
            append = getattr(panel, "append", None)
            if callable(append):
                append(text, is_error)
                break
        if on_status:
            from etools.ui.kit import toast

            toast(text, ms=8000)


def report_qt_message(message: str, *, critical: bool = False) -> None:
    """Record one Qt warning. Repeated copies within a short time are dropped."""
    text = str(message or "").strip()
    if not text:
        return
    key, on_status = describe_qt_warning(text)
    if _remember(_fingerprint(key, text)):
        return
    if critical:
        on_status = True
    if _bridge is None:
        sentence = _sentence(key, _short(text))
        log.error(sentence) if critical else log.warning(sentence)
        return
    _bridge.report.emit(key, _short(text), on_status, critical)


def _handler(mode, _context, message) -> None:
    try:
        if mode in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
            return
        report_qt_message(str(message), critical=mode != QtMsgType.QtWarningMsg)
    except Exception:
        return


def install_qt_message_bridge() -> None:
    """Install once for this process. Qt debug and info lines stay quiet."""
    global _bridge
    if _bridge is not None:
        return
    _bridge = _Bridge()
    qInstallMessageHandler(_handler)
