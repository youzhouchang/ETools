"""Qt's own warnings become one plain sentence in the log."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMessageLogger  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from etools.i18n import tr  # noqa: E402
from etools.ui.qt_messages import (  # noqa: E402
    clear_qt_message_cache,
    describe_qt_warning,
    install_qt_message_bridge,
)


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_dashboard_window_warning_is_a_known_sentence() -> None:
    key, on_status = describe_qt_warning(
        'QWidgetWindow(0x5fa4, name="dashBoardWindow") must be a top level window.'
    )
    assert key == "qt.toplevel_dash"
    assert on_status is True
    assert "0x" not in tr(key)


def test_opengl_failure_is_a_known_sentence() -> None:
    key, on_status = describe_qt_warning("Qt3D could not create an OpenGL context")
    assert key == "qt.gl_fail"
    assert on_status is True


def test_handler_logs_one_sentence_and_drops_the_repeat(qapp, caplog) -> None:
    install_qt_message_bridge()
    clear_qt_message_cache()
    raw = 'QWidgetWindow(0x11, name="dashBoardWindow") must be a top level window.'
    with caplog.at_level("WARNING", logger="etools.qt"):
        QMessageLogger().warning(raw)
        qapp.processEvents()
        QMessageLogger().warning(raw.replace("0x11", "0x22"))
        qapp.processEvents()
    matches = [rec for rec in caplog.records if rec.name == "etools.qt"]
    assert len(matches) == 1
    assert matches[0].message == tr("qt.toplevel_dash")
