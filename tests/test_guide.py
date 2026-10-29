"""The in-app user guide stays aligned with the frame protocols."""

from __future__ import annotations

from etools.i18n_catalog.common import EN, ZH
from etools.ui.guide_doc import guide_path, load_guide
from etools.ui.markdown import markdown_to_html


def test_guide_file_is_next_to_the_source_tree() -> None:
    path = guide_path()
    assert path.name == "guide.md"
    assert path.is_file()


def test_guide_covers_the_protocols() -> None:
    text = load_guide()
    for needle in (
        "/*1.2,3.4,-5*/",
        "key=value",
        "AA 55 u16be:v f32le:x",
        "roll,pitch,yaw",
        "qw,qx,qy,qz",
        "WGS84",
        "GCJ-02",
        "EVM1",
        "etools.frames.publish",
        "etools.dash.values",
        "etools.map.points",
    ):
        assert needle in text
    assert "拆字节" not in text


def test_guide_renders_to_html() -> None:
    html = markdown_to_html(load_guide())
    assert "<h1>" in html
    assert "<h2>" in html
    assert "<pre>" in html
    assert "<table>" in html


def test_guide_menu_strings_exist_in_both_languages() -> None:
    for key in ("act.guide", "guide.title", "guide.missing"):
        assert key in ZH
        assert key in EN
        assert ZH[key] != EN[key]
