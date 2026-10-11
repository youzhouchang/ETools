"""Dashboard bindings, map projection, frame hub, and MQTT packets."""

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
        DashWidget(type="gauge", title="Temp", unit="C", minimum=-80, maximum=0, bind="temp")
    ]
    loaded = project_from_json(project_to_json(widgets))
    assert loaded[0].type == "gauge"
    assert loaded[0].bind == "temp"
    assert loaded[0].minimum == -80
    assert loaded[0].maximum == 0


def test_project_rejects_non_finite_ranges():
    with pytest.raises(ValueError, match="finite"):
        project_from_json('{"widgets":[{"minimum":NaN,"maximum":100}]}')


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
