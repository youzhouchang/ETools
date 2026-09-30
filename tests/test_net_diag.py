"""Network diagnostic helpers."""

from __future__ import annotations

import socket
import threading

from etools.core.net_diag import check_tcp_port, check_udp_port


def test_tcp_port_open_and_closed():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def accept_once():
        conn, _ = srv.accept()
        conn.close()
        srv.close()

    t = threading.Thread(target=accept_once, daemon=True)
    t.start()
    ok, ms, msg = check_tcp_port("127.0.0.1", port, timeout=2)
    assert ok is True
    assert ms >= 0
    assert msg == "open"

    ok2, _ms, msg2 = check_tcp_port("127.0.0.1", 1, timeout=0.3)
    assert ok2 is False
    assert msg2


def test_udp_probe_returns():
    # Closed UDP may raise ICMP unreachable (ok=False) or silently drop (ok=True).
    ok, ms, msg = check_udp_port("127.0.0.1", 9, timeout=0.3)
    assert ms >= 0
    assert msg
    assert isinstance(ok, bool)
