"""Coverage for the design-review split: catalogs, link encoder, probe errors."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from etools.core.probe_errors import (  # noqa: E402
    ProbeDisconnected,
    ProbeOperationError,
    ProbePackMissing,
    classify_probe_error,
)
from etools.i18n import _STRINGS, LANG_EN, LANG_ZH  # noqa: E402
from etools.i18n_catalog import CATALOGS  # noqa: E402
from etools.ui.tools.link_controller import LinkController  # noqa: E402


def test_zh_and_en_keys_match():
    assert set(_STRINGS[LANG_ZH]) == set(_STRINGS[LANG_EN])
    assert _STRINGS[LANG_ZH]


def test_catalogs_do_not_overlap():
    seen: set[str] = set()
    for catalog in CATALOGS:
        keys = set(catalog.ZH)
        assert keys == set(catalog.EN)
        assert seen.isdisjoint(keys)
        seen.update(keys)
    assert seen == set(_STRINGS[LANG_ZH])


def test_classify_disconnect_pack_and_operation():
    gone = classify_probe_error(RuntimeError("transfer failed"))
    assert isinstance(gone, ProbeDisconnected)
    missing = classify_probe_error(RuntimeError("No target with name stm32"))
    assert isinstance(missing, ProbePackMissing)
    other = classify_probe_error(RuntimeError("erase timeout"))
    assert isinstance(other, ProbeOperationError)
    again = classify_probe_error(gone)
    assert again is gone


def test_encode_payload_hex_text_and_checksum():
    assert LinkController.encode_payload("DE AD", mode="hex") == bytes.fromhex("DEAD")
    assert LinkController.encode_payload("hi", mode="ascii", ending="crlf") == b"hi\r\n"
    framed = LinkController.encode_payload(
        "0102", mode="hex", checksum="sum8", ending="none"
    )
    assert framed == bytes.fromhex("010203")


def test_require_session_is_typed():
    from etools.core.pyocd_driver import PyOCDDriver

    driver = PyOCDDriver()
    with pytest.raises(ProbeDisconnected, match="Not connected"):
        driver._require_session()
    result = driver._fail("No matching probe found (device unplugged?)")
    assert result.ok is False
    assert isinstance(result.error, ProbeDisconnected)
    assert "unplugged" in result.message


def test_shell_has_no_poll_timer(qapp):
    from etools.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert not hasattr(window.shell, "_state_timer")
        assert window.program is not None
        window.shell.refresh_action_states()
    finally:
        window.close()


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
