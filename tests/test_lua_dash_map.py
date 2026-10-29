"""Lua access to parsed frames, the dashboard, and the map."""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from etools.core.frame_hub import LUA_SOURCE, FrameHub, FrameTap  # noqa: E402
from etools.core.lua_host import LuaHost  # noqa: E402


def test_frame_tap_queues_filters_and_merges_latest():
    hub = FrameHub()
    tap = FrameTap(hub, maxlen=4)
    tap.start()
    hub.publish_frames("serial", [{"a": 1.0}, {"b": 2.0}])
    hub.publish_frames("mqtt", [{"c": 3.0}])
    hub.publish_frames(LUA_SOURCE, [{"out": 9.0}])

    assert [f["fields"] for f in tap.take(8, "mqtt")] == [{"c": 3.0}]
    items = tap.take(8)
    assert [f["source"] for f in items] == ["serial", "serial"]
    assert tap.take(8) == []
    assert tap.latest("serial") == {"a": 1.0, "b": 2.0}
    assert tap.latest()["out"] == 9.0

    assert tap.wait(0.05) is None
    threading.Timer(0.05, lambda: hub.publish_frames("serial", [{"z": 1.0}])).start()
    got = tap.wait(2.0, "serial")
    assert got is not None and got["fields"] == {"z": 1.0}
    tap.stop()
    hub.publish_frames("serial", [{"late": 1.0}])
    assert tap.take(8) == []


class _InlinePump:
    """Runs bridge jobs on the calling thread (no Qt involved)."""

    def submit(self, fn, timeout: float = 30.0):
        return fn()

    def post(self, fn, timeout: float = 30.0) -> None:
        fn()


def _run(host: LuaHost, source: str, *, pump_events=None) -> tuple[bool, str]:
    done: list[tuple[bool, str]] = []
    host.set_done_hook(lambda ok, msg: done.append((ok, msg)))
    host.run_script(source)
    deadline = time.monotonic() + 5
    while not host.wait(0.01):
        if pump_events is not None:
            pump_events()
        assert time.monotonic() < deadline, "script did not finish"
    if pump_events is not None:
        pump_events()
    return done[0]


def test_lua_reads_frames_and_publishes_results():
    pytest.importorskip("lupa")
    from etools.ui.tools.script_bridges import FramesLuaBridge

    hub = FrameHub()
    published: list[tuple[str, dict]] = []
    hub.subscribe(lambda source, frame: published.append((source, frame)))
    bridge = FramesLuaBridge(_InlinePump(), hub)
    host = LuaHost()
    host.set_bridge("frames", bridge)

    hub.publish_frames("serial", [{"stale": 1.0}])
    host.set_done_hook(None)
    threading.Timer(
        0.1, lambda: hub.publish_frames("serial", [{"speed": 2.0}, {"speed": 4.0}])
    ).start()
    ok, msg = _run(
        host,
        """
        local first = etools.frames.wait(2000, 'serial')
        assert(first and first.source == 'serial' and first.fields.speed == 2.0)
        local rest = etools.frames.recv(8)
        assert(#rest == 1 and rest[1].fields.speed == 4.0)
        local latest = etools.frames.latest('serial')
        assert(latest.speed == 4.0 and latest.stale == 1.0)
        etools.frames.publish{avg = (first.fields.speed + rest[1].fields.speed) / 2}
        etools.frames.publish{10, 20}
        -- the script's own output never comes back through recv
        assert(#etools.frames.recv(8) == 0)
        """,
    )
    assert ok, msg
    lua_frames = [frame for source, frame in published if source == LUA_SOURCE]
    assert lua_frames == [{"avg": 3.0}, {"f1": 10.0, "f2": 20.0}]
    bridge.shutdown()


@pytest.fixture
def qapp(monkeypatch):
    from PySide6.QtWidgets import QApplication

    import etools.ui.tools.dashboard_page as dash_mod
    import etools.ui.tools.map_page as map_mod

    monkeypatch.setattr(dash_mod, "save_tool_prefs", lambda *_a, **_k: None)
    monkeypatch.setattr(dash_mod, "load_tool_prefs", lambda *_a, **_k: {})
    monkeypatch.setattr(map_mod, "save_tool_prefs", lambda *_a, **_k: None)
    monkeypatch.setattr(map_mod, "load_tool_prefs", lambda *_a, **_k: {"basemap": "none"})
    yield QApplication.instance() or QApplication([])


def test_dashboard_page_lua_helpers(qapp):
    from etools.ui.tools.dashboard_page import DashboardPage

    page = DashboardPage()
    assert page.lua_add({"type": "value", "title": "Avg", "bind": "speed_avg", "unit": "m/s"}) == 1
    assert page.lua_add({"type": "multiplot", "bind": "a,b"}) == 2
    with pytest.raises(ValueError):
        page.lua_add({"type": "nope"})
    widgets = page.lua_widgets()
    assert [w["bind"] for w in widgets] == ["speed_avg", "a,b"]
    assert page.lua_source("lua") == LUA_SOURCE
    with pytest.raises(ValueError):
        page.lua_source("bogus")

    page.lua_push({"speed_avg": 1.5, "a": 1.0, "b": 2.0})
    values = page.lua_values()
    assert values[0]["value"] == 1.5
    assert values[1]["values"] == [1.0, 2.0]
    assert page.lua_remove(1) and not page.lua_remove(9)
    assert len(page.lua_widgets()) == 1
    page.shutdown()


def test_map_page_lua_helpers(qapp):
    from etools.ui.tools.map_page import MapPage

    page = MapPage()
    assert page.lua_add_point(31.2, 121.5)
    assert not page.lua_add_point(120.0, 0.0)
    page.lua_add_point(31.3, 121.6)
    assert page.lua_points() == [{"lat": 31.2, "lon": 121.5}, {"lat": 31.3, "lon": 121.6}]
    assert page.lua_points(1) == [{"lat": 31.3, "lon": 121.6}]
    page.lua_bind("gps_lat", "gps_lon")
    assert page.lat_bind.text() == "gps_lat"
    assert page.lua_source("lua") == LUA_SOURCE
    page.lua_clear()
    assert page.lua_points() == []
    page.shutdown()


def test_lua_drives_dashboard_and_map_through_the_qt_pump(qapp):
    pytest.importorskip("lupa")
    from PySide6.QtWidgets import QWidget

    from etools.ui.tools.dashboard_page import DashboardPage
    from etools.ui.tools.map_page import MapPage
    from etools.ui.tools.script_bridges import DashLuaBridge, MapLuaBridge, _QueueBridge

    owner = QWidget()
    pump = _QueueBridge()
    pump.install(owner)
    dash, map_page = DashboardPage(), MapPage()
    host = LuaHost()
    host.set_bridge("dash", DashLuaBridge(dash, pump))
    host.set_bridge("map", MapLuaBridge(map_page, pump))
    ok, msg = _run(
        host,
        """
        assert(etools.dash.source('lua') == 'lua')
        local n = etools.dash.add{type = 'gauge', title = 'T', bind = 'temp', min = 0, max = 50}
        etools.dash.push{temp = 21.5}
        local v = etools.dash.values()
        assert(v[n].value == 21.5)
        assert(etools.dash.widgets()[n].type == 'gauge')
        etools.map.add(30.0, 120.0)
        etools.map.add(30.1, 120.1)
        local last = etools.map.last()
        assert(last.lat == 30.1 and #etools.map.points() == 2)
        etools.map.clear()
        assert(etools.map.last() == nil)
        """,
        pump_events=qapp.processEvents,
    )
    assert ok, msg
    dash.shutdown()
    map_page.shutdown()
