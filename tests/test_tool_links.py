"""Smoke tests for serial/net/ssh link helpers (no hardware)."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable

import pytest

from etools.core.net_link import NetLink
from etools.core.serial_link import list_serial_ports
from etools.core.ssh_link import SshLink


def _until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll *predicate* until true or *timeout* passes (no fixed sleeps)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_list_serial_ports_does_not_raise():
    ports = list_serial_ports()
    assert isinstance(ports, list)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs a POSIX pty")
def test_serial_link_survives_ports_without_modem_lines():
    import tty

    from etools.core.serial_link import SerialLink

    master, slave = os.openpty()
    tty.setraw(master)
    tty.setraw(slave)
    got: list[bytes] = []
    link = SerialLink()
    link.set_handlers(on_rx=got.append)
    try:
        link.open(port=os.ttyname(slave), baudrate=115200)
        # A pty rejects TIOCMBIS; the port must stay usable.
        assert link.set_dtr(True) is False
        assert link.set_rts(True) is False
        os.write(master, b"ping")
        assert _until(lambda: b"ping" in b"".join(got))
    finally:
        link.close()
        os.close(master)
        os.close(slave)


def test_netlink_tcp_loopback():
    # Tiny echo server
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def echo():
        conn, _ = srv.accept()
        data = conn.recv(1024)
        conn.sendall(data)
        conn.close()
        srv.close()

    t = threading.Thread(target=echo, daemon=True)
    t.start()

    got: list[bytes] = []
    link = NetLink()
    link.set_handlers(on_rx=lambda b, peer: got.append(b))
    link.connect_tcp_client("127.0.0.1", port)
    link.send(b"ping")
    assert _until(lambda: b"ping" in b"".join(got))
    link.close()


def test_netlink_tcp_server_multi_client():
    events: list[tuple[str, str]] = []
    rx: list[tuple[bytes, str]] = []
    link = NetLink()
    link.set_handlers(
        on_rx=lambda b, peer: rx.append((b, peer)),
        on_peer=lambda kind, peer: events.append((kind, peer)),
    )
    link.listen_tcp_server("127.0.0.1", 0)
    # discover bound port via the internal socket
    port = link._sock.getsockname()[1]

    c1 = socket.create_connection(("127.0.0.1", port), timeout=2)
    c2 = socket.create_connection(("127.0.0.1", port), timeout=2)
    assert _until(lambda: len(link.peers()) == 2)
    peers = link.peers()

    c1.sendall(b"from-c1")
    c2.sendall(b"from-c2")

    def both_arrived() -> bool:
        payloads = b"".join(b for b, _ in rx)
        return b"from-c1" in payloads and b"from-c2" in payloads

    assert _until(both_arrived)

    link.send(b"hello1", peer=peers[0])
    link.send(b"hello2", peer=peers[1])
    link.send(b"broadcast")

    def read_until(sock: socket.socket, needle: bytes) -> bytes:
        sock.settimeout(2.0)
        data = b""
        while needle not in data:
            try:
                chunk = sock.recv(64)
            except TimeoutError:
                break
            if not chunk:
                break
            data += chunk
        return data

    got1 = read_until(c1, b"broadcast")
    got2 = read_until(c2, b"broadcast")
    assert b"broadcast" in got1 and b"broadcast" in got2
    assert (b"hello1" in got1) or (b"hello2" in got1)
    assert (b"hello1" in got2) or (b"hello2" in got2)

    c1.close()
    c2.close()
    link.close()
    assert any(k == "on" for k, _ in events)


def test_ssh_shell_roundtrip():
    link = SshLink()

    class Channel:
        def __init__(self) -> None:
            self.buf = b"prompt"
            self.sent = b""
            self.size = (0, 0)

        def recv_ready(self) -> bool:
            return bool(self.buf)

        def recv(self, n: int) -> bytes:
            data, self.buf = self.buf[:n], b""
            return data

        def sendall(self, data: bytes) -> None:
            self.sent += data

        def resize_pty(self, width: int = 0, height: int = 0) -> None:
            self.size = (width, height)

        def close(self) -> None:
            self.closed = True

    channel = Channel()
    link._client = object()
    link._shell = channel
    assert link.shell_open
    link.shell_write(b"ls\r")
    link.shell_resize(80, 24)
    assert channel.sent == b"ls\r"
    assert channel.size == (80, 24)
    assert link.shell_read() == b"prompt"
    link.close()
    assert not link.shell_open
    assert not link.is_connected


def test_ssh_link_not_connected():
    s = SshLink()
    assert not s.is_connected
    try:
        s.exec_command("true")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
