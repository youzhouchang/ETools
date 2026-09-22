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


def test_ssh_link_not_connected():
    s = SshLink()
    assert not s.is_connected
    try:
        s.exec_command("true")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
