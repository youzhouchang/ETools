"""Small MQTT 3.1.1 client (QoS 0) for the MQTT page."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

MAX_PACKET_SIZE = 1024 * 1024


class MqttError(RuntimeError):
    """Broker rejected the connection or the socket failed."""


def encode_remaining(length: int) -> bytes:
    out = bytearray()
    value = int(length)
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 0x80
        out.append(digit)
        if not value:
            break
    return bytes(out)


def encode_utf8(text: str) -> bytes:
    raw = str(text).encode("utf-8")
    return len(raw).to_bytes(2, "big") + raw


def connect_packet(
    client_id: str,
    username: str = "",
    password: str = "",
    keepalive: int = 30,
) -> bytes:
    flags = 0x02  # clean session
    payload = encode_utf8(client_id or "etools")
    if username or password:
        flags |= 0x80
        payload += encode_utf8(username)
    if password:
        flags |= 0x40
        payload += encode_utf8(password)
    variable = b"\x00\x04MQTT\x04" + bytes([flags]) + int(keepalive).to_bytes(2, "big")
    body = variable + payload
    return bytes([0x10]) + encode_remaining(len(body)) + body


def subscribe_packet(topic: str, packet_id: int = 1) -> bytes:
    body = int(packet_id).to_bytes(2, "big") + encode_utf8(topic) + bytes([0])
    return bytes([0x82]) + encode_remaining(len(body)) + body


def publish_packet(topic: str, payload: bytes) -> bytes:
    body = encode_utf8(topic) + bytes(payload)
    return bytes([0x30]) + encode_remaining(len(body)) + body


def decode_publish(body: bytes) -> tuple[str, bytes]:
    if len(body) < 2:
        raise MqttError("short PUBLISH")
    size = int.from_bytes(body[:2], "big")
    if size == 0 or 2 + size > len(body):
        raise MqttError("bad PUBLISH topic")
    topic = body[2 : 2 + size].decode("utf-8", errors="replace")
    return topic, body[2 + size :]


def _read_exact(sock: socket.socket, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def read_packet(sock: socket.socket, max_size: int = MAX_PACKET_SIZE) -> tuple[int, bytes]:
    header = _read_exact(sock, 1)[0]
    remaining = 0
    multiplier = 1
    for _ in range(4):
        digit = _read_exact(sock, 1)[0]
        remaining += (digit & 0x7F) * multiplier
        if not digit & 0x80:
            break
        multiplier *= 128
    else:
        raise MqttError("bad remaining length")
    if remaining > max(1, int(max_size)):
        raise MqttError("packet too large")
    body = _read_exact(sock, remaining) if remaining else b""
    return header, body


class MqttLink:
    """One TCP session. Callbacks run on the reader thread."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._keepalive = 30
        self._on_message: Callable[[str, bytes], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._packet_id = 1
        self._generation = 0
        self._last_sent = 0.0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def set_handlers(
        self,
        on_message: Callable[[str, bytes], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_error = on_error

    def connect(
        self,
        host: str,
        port: int = 1883,
        client_id: str = "etools",
        username: str = "",
        password: str = "",
        timeout: float = 8.0,
    ) -> None:
        self.close()
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.sendall(connect_packet(client_id, username, password))
            header, body = read_packet(sock)
            code = body[1] if header == 0x20 and len(body) >= 2 else -1
            if code != 0:
                raise MqttError(f"CONNACK {code}")
            sock.settimeout(1.0)
        except Exception:
            sock.close()
            raise
        self._sock = sock
        self._stop.clear()
        self._generation += 1
        generation = self._generation
        self._last_sent = time.monotonic()
        self._thread = threading.Thread(
            target=self._loop,
            args=(sock, generation),
            name="etools-mqtt",
            daemon=True,
        )
        self._thread.start()

    def subscribe(self, topic: str) -> None:
        self._packet_id = (self._packet_id % 65535) + 1
        self._send(subscribe_packet(topic, self._packet_id))

    def publish(self, topic: str, payload: bytes) -> None:
        self._send(publish_packet(topic, payload))

    def close(self) -> None:
        self._stop.set()
        self._generation += 1
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.sendall(bytes([0xE0, 0x00]))
            except Exception:
                pass
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            sock.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None

    def _send(self, packet: bytes) -> None:
        with self._lock:
            if self._sock is None:
                raise MqttError("not connected")
            try:
                self._sock.sendall(packet)
            except OSError as exc:
                raise MqttError(str(exc)) from exc
            self._last_sent = time.monotonic()

    def _loop(self, sock: socket.socket, generation: int) -> None:
        while not self._stop.is_set() and generation == self._generation:
            if time.monotonic() - self._last_sent >= self._keepalive / 2:
                try:
                    self._send(bytes([0xC0, 0x00]))
                except Exception:
                    self._fail("ping failed", sock, generation)
                    return
            try:
                header, body = read_packet(sock)
            except TimeoutError:
                continue
            except Exception as exc:
                if not self._stop.is_set() and generation == self._generation:
                    self._fail(str(exc), sock, generation)
                return
            if (header >> 4) == 3 and self._on_message is not None:
                try:
                    topic, payload = decode_publish(body)
                    qos = (header >> 1) & 0x03
                    if qos:
                        if len(payload) < 2:
                            raise MqttError("short PUBLISH packet id")
                        payload = payload[2:]
                    self._on_message(topic, payload)
                except Exception as exc:
                    self._fail(str(exc), sock, generation)

    def _fail(self, message: str, sock: socket.socket, generation: int) -> None:
        if generation != self._generation:
            return
        self._stop.set()
        with self._lock:
            if self._sock is sock:
                self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if self._on_error is not None:
            self._on_error(message)
