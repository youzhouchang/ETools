"""TCP/UDP debug link (stdlib socket) with background RX thread."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable


class NetLink:
    """TCP client/server or UDP endpoint for a network debug assistant."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._conn: socket.socket | None = None  # accepted TCP client
        self._peer: tuple[str, int] | None = None
        self._mode = "tcp-client"
        self._rx_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_rx: Callable[[bytes, str], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._on_peer: Callable[[str, str], None] | None = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def set_handlers(
        self,
        on_rx: Callable[[bytes, str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_peer: Callable[[str, str], None] | None = None,
    ) -> None:
        self._on_rx = on_rx
        self._on_error = on_error
        self._on_peer = on_peer

    def connect_tcp_client(self, host: str, port: int) -> None:
        self.close()
        sock = socket.create_connection((host, int(port)), timeout=5.0)
        sock.settimeout(0.2)
        self._sock = sock
        self._mode = "tcp-client"
        self._peer = (host, int(port))
        self._start_rx(sock)

    def listen_tcp_server(self, host: str, port: int) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        sock.listen(1)
        sock.settimeout(0.2)
        self._sock = sock
        self._mode = "tcp-server"
        self._start_rx(sock)

    def open_udp(self, host: str, port: int, local_port: int | None = None) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", int(port if local_port is None else local_port)))
        self._sock = sock
        self._mode = "udp"
        self._peer = (host, int(port))
        self._start_rx(sock)

    def send(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("not connected")
        if self._mode == "tcp-client":
            self._sock.sendall(data)
        elif self._mode == "tcp-server":
            conn = self._conn
            if conn is None:
                raise RuntimeError("no client connected")
            conn.sendall(data)
        else:
            if self._peer is None:
                raise RuntimeError("no UDP peer")
            self._sock.sendto(data, self._peer)

    def close(self) -> None:
        stop, thread = self._stop, self._rx_thread
        stop.set()
        for s in (self._conn, self._sock):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._conn = None
        self._sock = None
        self._peer = None
        self._rx_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _start_rx(self, sock: socket.socket) -> None:
        self._stop = threading.Event()
        self._rx_thread = threading.Thread(target=self._rx_loop, args=(sock,), daemon=True)
        self._rx_thread.start()

    def _rx_loop(self, sock: socket.socket) -> None:
        stop = self._stop
        while not stop.is_set():
            try:
                if self._mode == "tcp-server" and self._sock is sock:
                    conn, addr = sock.accept()
                    self._conn = conn
                    self._peer = addr
                    conn.settimeout(0.2)
                    if self._on_peer:
                        self._on_peer("on", f"{addr[0]}:{addr[1]}")
                    continue
                src = self._conn if self._mode == "tcp-server" else sock
                if src is None:
                    continue
                if self._mode == "udp":
                    data, addr = sock.recvfrom(4096)
                    if data and self._on_rx:
                        self._on_rx(data, f"{addr[0]}:{addr[1]}")
                else:
                    data = src.recv(4096)
                    if not data:
                        if self._mode == "tcp-server":
                            peer = self._peer or ("?", 0)
                            self._conn = None
                            self._peer = None
                            try:
                                src.close()
                            except OSError:
                                pass
                            if self._on_peer:
                                self._on_peer("off", f"{peer[0]}:{peer[1]}")
                            continue
                        break
                    if data and self._on_rx:
                        peer = self._peer or ("?", 0)
                        self._on_rx(data, f"{peer[0]}:{peer[1]}")
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop.is_set() and self._on_error:
                    self._on_error(str(exc))
                break
