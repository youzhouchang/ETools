"""Smoke tests for serial/net/ssh link helpers (no hardware)."""

from __future__ import annotations

import socket
import threading

from etools.core.net_link import NetLink
from etools.core.serial_link import list_serial_ports
from etools.core.ssh_link import SshLink


def test_list_serial_ports_does_not_raise():
    ports = list_serial_ports()
    assert isinstance(ports, list)


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
    import time

    time.sleep(0.3)
    link.close()
    assert b"ping" in b"".join(got)


def test_netlink_tcp_server_multi_client():
    import time

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
    time.sleep(0.4)
    peers = link.peers()
    assert len(peers) == 2

    c1.sendall(b"from-c1")
    c2.sendall(b"from-c2")
    time.sleep(0.4)
    rx_payloads = b"".join(b for b, _ in rx)
    assert b"from-c1" in rx_payloads
    assert b"from-c2" in rx_payloads

    link.send(b"hello1", peer=peers[0])
    link.send(b"hello2", peer=peers[1])
    link.send(b"broadcast")
    time.sleep(0.3)

    c1.settimeout(0.5)
    c2.settimeout(0.5)
    got1 = b""
    got2 = b""
    try:
        got1 += c1.recv(64)
        got1 += c1.recv(64)
    except TimeoutError:
        pass
    try:
        got2 += c2.recv(64)
        got2 += c2.recv(64)
    except TimeoutError:
        pass
    assert b"broadcast" in got1 and b"broadcast" in got2
    assert (b"hello1" in got1) or (b"hello2" in got1)
    assert (b"hello1" in got2) or (b"hello2" in got2)

    c1.close()
    c2.close()
    link.close()
    assert any(k == "on" for k, _ in events)


def test_ssh_link_not_connected():
    s = SshLink()
    assert not s.is_connected
    try:
        s.exec_command("true")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
