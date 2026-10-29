"""Dashboard bindings, map projection, frame hub, and MQTT packets."""

import math
import socket
import threading

import pytest
from PySide6.QtWidgets import QApplication

from etools.core.dashboard import DashWidget, lookup, project_from_json, project_to_json
from etools.core.frame_hub import FrameHub
from etools.core.map_proj import latlon_to_world, tile_xy, world_to_latlon
from etools.core.mqtt_link import (
    MAX_PACKET_SIZE,
    MqttError,
    MqttLink,
    connect_packet,
    decode_publish,
    publish_packet,
    read_packet,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_lookup_index_and_json_key():
    frame = {"f1": 1.5, "temp": 21.0}
    assert lookup(frame, "1") == 1.5
    assert lookup(frame, "2") == 21.0
    assert lookup(frame, "temp") == 21.0
    assert lookup(frame, "missing") is None


def test_project_json_roundtrip():
    widgets = [
        DashWidget(type="gauge", title="Temp", unit="C", minimum=-80, maximum=0, bind="temp"),
        DashWidget(type="lamp", title="Armed", bind="arm"),
    ]
    loaded = project_from_json(project_to_json(widgets))
    assert loaded[0].type == "gauge"
    assert loaded[1].type == "lamp"
    assert loaded[0].bind == "temp"
    assert loaded[0].minimum == -80
    assert loaded[0].maximum == 0


def test_attitude3d_widget_roundtrips_mode_through_json():
    widgets = [
        DashWidget(type="attitude3d", title="IMU", bind="roll,pitch,yaw", mode="euler"),
        DashWidget(type="attitude3d", title="IMU2", bind="qw,qx,qy,qz", mode="quat"),
    ]
    loaded = project_from_json(project_to_json(widgets))
    assert [item.mode for item in loaded] == ["euler", "quat"]
    assert [item.bind for item in loaded] == ["roll,pitch,yaw", "qw,qx,qy,qz"]


def test_attitude3d_widget_rejects_an_unknown_mode():
    loaded = project_from_json(
        '{"widgets":[{"type":"attitude3d","mode":"bogus","bind":"roll,pitch,yaw"}]}'
    )
    assert loaded[0].mode == "euler"


def test_widget_layout_and_shape_roundtrip_through_json():
    widgets = [
        DashWidget(type="attitude3d", shape="cube", row=1, col=2, row_span=2, col_span=2)
    ]
    loaded = project_from_json(project_to_json(widgets))
    item = loaded[0]
    assert item.shape == "cube"
    assert (item.row, item.col, item.row_span, item.col_span) == (1, 2, 2, 2)


def test_unknown_shape_falls_back_to_aircraft():
    loaded = project_from_json('{"widgets":[{"type":"attitude3d","shape":"car"}]}')
    assert loaded[0].shape == "aircraft"


def test_unplaced_widgets_pack_into_free_cells():
    from etools.core.dashboard import ensure_layout, try_move, try_resize

    items = [DashWidget(type="value", title=str(index)) for index in range(3)]
    ensure_layout(items)
    assert [(item.row, item.col) for item in items] == [(0, 0), (0, 1), (0, 2)]
    wide = DashWidget(type="plot", row=0, col=1, col_span=2)
    assert try_move([*items, wide], items[0], 0, 1) is False
    assert try_resize([wide], wide, 1, 99) is True
    assert wide.col_span == 11


def test_version1_layout_scales_onto_the_finer_grid():
    from etools.core.dashboard import LEGACY_COL_SCALE, LEGACY_ROW_SCALE

    loaded = project_from_json(
        '{"version":1,"widgets":[{"type":"value","row":1,"col":2,"row_span":2,"col_span":2}]}'
    )
    item = loaded[0]
    assert item.row == 1 * LEGACY_ROW_SCALE
    assert item.col == 2 * LEGACY_COL_SCALE
    assert item.row_span == 2 * LEGACY_ROW_SCALE
    assert item.col_span == 2 * LEGACY_COL_SCALE


def test_canvas_places_cards_and_rejects_an_occupied_cell(qapp):
    from etools.ui.widgets.dash_canvas import DashCanvas

    canvas = DashCanvas()
    canvas.resize(800, 500)
    canvas.set_items([DashWidget(type="value", title="A", row=0, col=0)])
    assert canvas.add_widget("gauge", "", 0, 0) is False
    assert len(canvas._items) == 1
    assert canvas.add_widget("gauge", "", 0, 1) is True
    assert canvas.cards[1].x() > canvas.cards[0].x()
    canvas.close()


def test_card_outline_is_a_single_closed_edge(qapp):
    from etools.ui.styles import build_stylesheet, get_theme
    from etools.ui.widgets.dash_canvas import DashCanvas

    theme = get_theme()
    canvas = DashCanvas()
    canvas.setStyleSheet(build_stylesheet(theme.name))
    canvas.resize(960, 640)
    canvas.show()
    canvas.set_items([DashWidget(type="value", title="A", row=0, col=0, row_span=8, col_span=3)])
    qapp.processEvents()
    card = canvas.cards[0]
    image = canvas.grab().toImage()
    board = theme.bg.lower()

    mid_y = card.y() + card.height() // 2
    left = [image.pixelColor(card.x() + dx, mid_y).name() for dx in range(-2, card.width() + 2)]
    transitions = 0
    was_board = True
    for name in left:
        is_board = name == board
        if is_board != was_board:
            transitions += 1
            was_board = is_board
    assert transitions == 2  # enter the card, then leave it
    fill = theme.bg_input.lower()
    assert image.pixelColor(card.x() + card.width() // 2, mid_y).name() == fill
    for x, y in (
        (card.x() + card.width() // 2, card.y() + 1),
        (card.x() + card.width() - 2, mid_y),
        (card.x() + card.width() // 2, card.y() + card.height() - 2),
    ):
        assert image.pixelColor(x, y).name() != board
    canvas.close()


def test_canvas_resize_follows_the_pointer_in_small_steps(qapp):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from etools.core.dashboard import CELL_HEIGHT
    from etools.ui.widgets.dash_canvas import DashCanvas

    canvas = DashCanvas()
    canvas.resize(960, 700)
    canvas.show()
    canvas.set_items(
        [DashWidget(type="value", title="A", row=0, col=0, row_span=8, col_span=3)]
    )
    card = canvas.cards[0]
    grip = card.grip
    qapp.processEvents()
    assert grip.y() > card.height() // 2
    start_h = card.height()
    origin = grip.mapToGlobal(grip.rect().center())

    def send(kind, global_pos, buttons):
        local = grip.mapFromGlobal(global_pos)
        event = QMouseEvent(
            kind,
            QPointF(local),
            QPointF(global_pos),
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(grip, event)

    moved = origin + QPoint(0, CELL_HEIGHT)
    send(QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseMove, moved, Qt.MouseButton.LeftButton)
    assert card.height() - start_h == CELL_HEIGHT
    send(QEvent.Type.MouseButtonRelease, moved, Qt.MouseButton.NoButton)
    assert card.spec.row_span == 9
    canvas.close()


def test_attitude_card_keeps_the_resize_handle_below_the_view(qapp):
    from PySide6.QtCore import QPoint

    from etools.ui.widgets.dashboard_cards import DashCard

    card = DashCard(DashWidget(type="attitude3d", shape="horizon", row_span=16, col_span=6))
    card.resize(360, 320)
    card.show()
    qapp.processEvents()
    view = card._attitude
    assert view is not None
    view_bottom = view.mapTo(card, QPoint(0, view.height())).y()
    assert card.grip.y() >= view_bottom - 2
    card.close()


def test_horizon_and_other_shapes_accept_a_quaternion(qapp):
    from etools.core.attitude import euler_to_quat
    from etools.ui.widgets.attitude_view import build_attitude_view
    from etools.ui.widgets.horizon_view import HorizonView

    quat = euler_to_quat(12, -5, 30)
    horizon = HorizonView()
    horizon.resize(220, 160)
    horizon.set_quaternion(quat)
    horizon.grab()
    assert horizon._pitch == pytest.approx(-5, abs=0.2)
    # Positive roll drops the right wing: sky stays on the left, ground on the right.
    banked = HorizonView()
    banked.resize(240, 160)
    banked.set_quaternion(euler_to_quat(30, 0, 0))
    image = banked.grab().toImage()
    left = image.pixelColor(30, 80)
    right = image.pixelColor(210, 80)
    assert left.blue() > left.red()
    assert right.red() > right.blue()
    banked.close()
    for shape in ("cube", "quad", "horizon"):
        view = build_attitude_view(shape=shape)
        view.set_quaternion(quat)
        view.close()
    horizon.close()


def test_waveform_keeps_a_long_history_between_paints(qapp):
    from etools.ui.widgets.variable_monitor import MAX_HISTORY, PAINT_INTERVAL_MS, _Waveform

    assert PAINT_INTERVAL_MS <= 16
    assert MAX_HISTORY >= 10_000
    wave = _Waveform()
    for index in range(1000):
        wave.push_batch({"a": float(index)})
    assert len(wave._series["a"]) == 1000
    assert wave._dirty is True
    wave.close()


def test_lamp_lights_only_for_a_nonzero_value(qapp):
    from etools.ui.widgets.dashboard_cards import DashCard, lamp_lit

    assert lamp_lit(0.0) is False
    assert lamp_lit(1.0) is True
    assert lamp_lit(float("nan")) is False
    card = DashCard(DashWidget(type="lamp", bind="arm"))
    card.resize(180, 140)
    card.show()
    assert card._meter is not None
    card.push({"arm": 0.0})
    assert card._meter._value == 0.0
    card.grab()
    card.push({"arm": 1.0})
    assert lamp_lit(card._meter._value)
    card.grab()
    card.close()


def test_palette_fills_complete_rows(qapp, monkeypatch):
    import etools.ui.tools.dashboard_page as dash_mod

    monkeypatch.setattr(dash_mod, "save_tool_prefs", lambda *_a, **_k: None)
    monkeypatch.setattr(dash_mod, "load_tool_prefs", lambda *_a, **_k: {})
    page = dash_mod.DashboardPage()
    entries = page._palette_entries()
    assert len(entries) % 2 == 0
    assert ("lamp", "", "dash.type.lamp") in entries
    page.shutdown()


def test_dash_card_attitude3d_updates_from_euler_and_quat_frames(qapp):
    from etools.ui.widgets.dashboard_cards import DashCard

    euler_card = DashCard(DashWidget(type="attitude3d", bind="roll,pitch,yaw", mode="euler"))
    euler_card.push({"roll": 10.0, "pitch": 0.0, "yaw": 0.0})
    assert "roll" in euler_card._value.text()

    quat_card = DashCard(DashWidget(type="attitude3d", bind="qw,qx,qy,qz", mode="quat"))
    quat_card.push({"qw": 1.0, "qx": 0.0, "qy": 0.0, "qz": 0.0})
    assert "roll" in quat_card._value.text()

    # Missing a bind leaves the last good reading rather than crashing.
    quat_card.push({"qw": 1.0})
    euler_card.close()
    quat_card.close()


def test_attitude_view_fallback_never_raises(qapp):
    from etools.ui.widgets.attitude_view import _FallbackAttitudeView

    view = _FallbackAttitudeView()
    view.set_quaternion((1.0, 0.0, 0.0, 0.0))
    assert "roll" in view.readout.text()
    view.close()


def test_project_rejects_non_finite_ranges():
    with pytest.raises(ValueError, match="finite"):
        project_from_json('{"widgets":[{"minimum":NaN,"maximum":100}]}')


def test_basemap_urls_match_the_projected_tile():
    from etools.core.map_basemap import from_tile_latlon, tile_url, to_tile_latlon

    lat, lon, zoom = 31.2304, 121.4737, 13
    osm_x, osm_y = tile_xy(lat, lon, zoom)
    amap_lat, amap_lon = to_tile_latlon("amap", lat, lon)
    amap_x, amap_y = tile_xy(amap_lat, amap_lon, zoom)
    wgs_px = latlon_to_world(lat, lon, zoom)
    gcj_px = latlon_to_world(amap_lat, amap_lon, zoom)
    assert math.hypot(gcj_px[0] - wgs_px[0], gcj_px[1] - wgs_px[1]) > 15
    fine = 17
    assert tile_xy(lat, lon, fine) != tile_xy(*to_tile_latlon("amap", lat, lon), fine)

    amap = tile_url("amap", zoom, amap_x, amap_y)
    assert f"x={amap_x}" in amap and f"y={amap_y}" in amap and f"z={zoom}" in amap
    assert "style=8" in amap
    esri = tile_url("esri", zoom, osm_x, osm_y)
    assert esri.endswith(f"/{zoom}/{osm_y}/{osm_x}")
    assert tile_url("osm", zoom, osm_x, osm_y).endswith(f"/{zoom}/{osm_x}/{osm_y}.png")
    assert tile_url("none", zoom, osm_x, osm_y) == ""
    assert to_tile_latlon("osm", lat, lon) == (lat, lon)
    back_lat, back_lon = from_tile_latlon("amap", amap_lat, amap_lon)
    assert abs(back_lat - lat) < 1e-6
    assert abs(back_lon - lon) < 1e-6


def test_overzoom_source_is_the_parent_quadrant():
    from etools.core.map_proj import overzoom_source

    parent_x, parent_y, sx, sy, size = overzoom_source(27440, 13388, 2)
    assert (parent_x, parent_y) == (6860, 3347)
    assert (sx, sy, size) == (0, 0, 64)
    parent_x, parent_y, sx, sy, size = overzoom_source(27441, 13390, 2)
    assert (parent_x, parent_y) == (6860, 3347)
    assert (sx, sy, size) == (64, 128, 64)


def test_esri_placeholder_is_not_treated_as_a_street_tile(qapp):
    from PySide6.QtGui import QColor, QImage

    from etools.ui.widgets.map_canvas import tile_is_unavailable

    blank = QImage(256, 256, QImage.Format.Format_RGB32)
    blank.fill(QColor(204, 204, 204))
    assert tile_is_unavailable(blank)
    street = QImage(256, 256, QImage.Format.Format_RGB32)
    street.fill(QColor(225, 180, 141))
    street.setPixelColor(128, 128, QColor(40, 90, 200))
    assert tile_is_unavailable(street) is False


def test_track_color_can_be_changed(qapp):
    from PySide6.QtGui import QColor

    from etools.ui.widgets.map_canvas import DEFAULT_TRACK, MapCanvas

    canvas = MapCanvas()
    assert canvas.track_color.name().upper() == DEFAULT_TRACK
    canvas.set_track_color(QColor("#22C55E"))
    assert canvas.track_color.name().upper() == "#22C55E"
    canvas.set_track_color(QColor())
    assert canvas.track_color.name().upper() == "#22C55E"
    canvas.shutdown()


def test_gcj02_shifts_china_and_leaves_other_places():
    from etools.core.map_basemap import wgs84_to_gcj02

    lat, lon = wgs84_to_gcj02(31.2304, 121.4737)
    d_lat = math.radians(lat - 31.2304) * 6378137
    d_lon = math.radians(lon - 121.4737) * 6378137 * math.cos(math.radians(31.2304))
    assert 50 < math.hypot(d_lat, d_lon) < 800
    assert wgs84_to_gcj02(40.7, -74.0) == (40.7, -74.0)


def test_switching_basemap_keeps_the_wgs84_view(qapp):
    from etools.core.map_basemap import from_tile_latlon
    from etools.ui.widgets.map_canvas import MapCanvas

    canvas = MapCanvas()
    assert canvas.basemap == "amap"
    canvas.add_point(31.2304, 121.4737)
    lat, lon = world_to_latlon(canvas._center[0], canvas._center[1], canvas._zoom)
    wgs = from_tile_latlon("amap", lat, lon)
    canvas.set_basemap("esri")
    lat, lon = world_to_latlon(canvas._center[0], canvas._center[1], canvas._zoom)
    assert abs(lat - wgs[0]) < 1e-6
    assert abs(lon - wgs[1]) < 1e-6
    assert canvas._points == [(31.2304, 121.4737)]
    canvas.set_basemap("none")
    assert canvas.basemap == "none"
    canvas.shutdown()


def test_mercator_roundtrip():
    x, y = latlon_to_world(31.2, 121.5, 10)
    lat, lon = world_to_latlon(x, y, 10)
    assert abs(lat - 31.2) < 1e-6
    assert abs(lon - 121.5) < 1e-6
    tx, ty = tile_xy(31.2, 121.5, 10)
    assert tx >= 0 and ty >= 0


def test_map_does_not_override_manual_center_after_first_point(qapp):
    from etools.ui.widgets.map_canvas import MapCanvas

    canvas = MapCanvas()
    canvas.add_point(31.2, 121.5)
    canvas._center = (100.0, 200.0)
    canvas.add_point(31.3, 121.6)
    assert canvas._center == (100.0, 200.0)
    canvas.shutdown()


def test_frame_hub_reassembles_split_frames():
    hub = FrameHub()
    seen: list[dict[str, float]] = []
    hub.subscribe(lambda _source, frame: seen.append(frame))
    hub.publish("serial", b"/*1.5,")
    assert seen == []
    hub.publish("serial", b"2*/")
    assert seen == [{"f1": 1.5, "f2": 2.0}]


def test_frame_hub_uses_source_field_names():
    hub = FrameHub()
    seen: list[dict[str, float]] = []
    hub.subscribe(lambda _source, frame: seen.append(frame))
    hub.set_names("serial", "ax,ay")
    hub.publish("serial", b"/*1,2*/")
    assert seen == [{"ax": 1.0, "ay": 2.0}]


def test_mqtt_publish_codec():
    packet = publish_packet("a/b", b"/*1*/")
    assert packet[0] == 0x30
    topic, payload = decode_publish(packet[2:])
    assert topic == "a/b"
    assert payload == b"/*1*/"
    assert connect_packet("etools")[0] == 0x10
    with pytest.raises(MqttError, match="topic"):
        decode_publish(b"\x00\x05ab")


def test_mqtt_rejects_oversized_packet_before_reading_body():
    left, right = socket.socketpair()
    try:
        right.sendall(bytes([0x30, 0xFF, 0xFF, 0x7F]))
        with pytest.raises(MqttError, match="too large"):
            read_packet(left, max_size=MAX_PACKET_SIZE)
    finally:
        left.close()
        right.close()


def test_mqtt_link_loopback():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    received: list[tuple[str, bytes]] = []

    def serve() -> None:
        conn, _addr = server.accept()
        read_packet(conn)
        conn.sendall(bytes([0x20, 0x02, 0x00, 0x00]))
        conn.sendall(publish_packet("device/data", b'{"temp":21}'))
        try:
            while conn.recv(64):
                pass
        except Exception:
            pass
        conn.close()

    thread = threading.Thread(target=serve)
    thread.start()
    link = MqttLink()
    try:
        link.set_handlers(on_message=lambda topic, payload: received.append((topic, payload)))
        link.connect("127.0.0.1", port, client_id="etools")
        for _ in range(50):
            if received:
                break
            threading.Event().wait(0.02)
    finally:
        link.close()
        thread.join(timeout=2)
        server.close()
    assert received and received[0][0] == "device/data"
    assert b"temp" in received[0][1]
