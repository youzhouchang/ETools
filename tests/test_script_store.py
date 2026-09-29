"""Named Lua script store CRUD tests."""

from __future__ import annotations

import pytest

from etools.core import script_store


@pytest.fixture(autouse=True)
def _isolated_scripts_dir(tmp_path, monkeypatch):
    """Never write sample/test scripts into the real user config folder."""
    from etools import config as config_mod

    monkeypatch.setattr(config_mod, "get_config_dir", lambda: tmp_path)
    return tmp_path


def test_script_store_crud(_isolated_scripts_dir):
    assert script_store.list_scripts() == []
    path = script_store.save_script("demo", "etools.app.log('hi')")
    assert path.name == "demo.lua"
    assert script_store.list_scripts() == ["demo"]
    assert script_store.load_script("demo") == "etools.app.log('hi')"

    script_store.save_script("demo", "print(1)")
    assert script_store.load_script("demo") == "print(1)"

    script_store.save_script("other.lua", "x = 1")
    assert set(script_store.list_scripts()) == {"demo", "other"}

    assert script_store.delete_script("other") is True
    assert script_store.list_scripts() == ["demo"]
    assert script_store.delete_script("missing") is False


def test_script_store_rejects_bad_names(_isolated_scripts_dir):
    with pytest.raises(ValueError):
        script_store.save_script("../evil", "x")
    with pytest.raises(ValueError):
        script_store.save_script("a/b", "x")


def test_script_samples_seed(_isolated_scripts_dir):
    from etools.core.script_samples import SAMPLES, ensure_samples

    written = ensure_samples()
    assert set(written) == set(SAMPLES)
    assert set(script_store.list_scripts()) >= set(SAMPLES)
    # refreshing identical content is a no-op
    assert ensure_samples() == []
    text = script_store.load_script("2_CRC校验")
    assert "crc16_modbus" in text
    assert "util.append_checksum" in text
    assert "0_入门教程" in SAMPLES
