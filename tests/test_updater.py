"""Update checker unit tests (no network)."""

from __future__ import annotations

from etools.core.updater import is_newer, parse_version


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
