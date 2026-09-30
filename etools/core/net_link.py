"""TCP/UDP debug link (stdlib socket) with background RX thread."""

from __future__ import annotations

import select
import socket
import threading
from collections.abc import Callable


def peer_label(addr: tuple[str, int] | None) -> str:
    if not addr:
        return "?"
    return f"{addr[0]}:{addr[1]}"


class NetLink:
    """TCP client / multi-client TCP server / UDP endpoint."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._conns: dict[str, socket.socket] = {}
        self._peer: tuple[str, int] | None = None  # default UDP remote / last TCP peer
        self._mode = "tcp-client"
        self._rx_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._on_rx: Callable[[bytes, str], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._on_peer: Callable[[str, str], None] | None = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    @property
    def mode(self) -> str:
        return self._mode

    def peers(self) -> list[str]:
        with self._lock:
            return list(self._conns.keys())

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
        with self._lock:
            self._conns = {peer_label(self._peer): sock}
        self._start_rx(sock)

    def listen_tcp_server(self, host: str, port: int) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        sock.listen(8)
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

    def send(self, data: bytes, peer: str | None = None) -> None:
        """Send *data*. In TCP server mode, *peer* selects a client (or all)."""
        if self._sock is None:
            raise RuntimeError("not connected")
        if self._mode == "tcp-server":
            with self._lock:
                if peer and peer != "*":
                    targets = {peer: self._conns.get(peer)}
                else:
                    targets = dict(self._conns)
            if not targets or all(v is None for v in targets.values()):
                raise RuntimeError("no client connected")
            for label, conn in targets.items():
                if conn is None:
                    continue
                try:
                    conn.sendall(data)
                except OSError as exc:
                    raise RuntimeError(f"send to {label} failed: {exc}") from exc
            return
        if self._mode == "tcp-client":
            self._sock.sendall(data)
            return
        if self._peer is None:
            raise RuntimeError("no UDP peer")
        self._sock.sendto(data, self._peer)

    def close(self) -> None:
        stop, thread = self._stop, self._rx_thread
        stop.set()
        with self._lock:
            conns = list(self._conns.values())
            self._conns.clear()
        for s in list(conns) + [self._sock]:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._sock = None
        self._peer = None
        self._rx_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _start_rx(self, sock: socket.socket) -> None:
        self._stop = threading.Event()
        self._rx_thread = threading.Thread(target=self._rx_loop, args=(sock,), daemon=True)
        self._rx_thread.start()

    def _drop_client(self, label: str) -> None:
        with self._lock:
            conn = self._conns.pop(label, None)
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if self._on_peer:
            self._on_peer("off", label)

    def _rx_loop(self, sock: socket.socket) -> None:
        stop = self._stop
        while not stop.is_set():
            try:
                if self._mode == "tcp-server" and self._sock is sock:
                    with self._lock:
                        items = list(self._conns.items())
                    # select() so accepts and client reads share one thread.
                    readers = [sock] + [c for _, c in items]
                    try:
                        readable, _, _ = select.select(readers, [], [], 0.2)
                    except (OSError, ValueError):
                        stop.wait(0.05)
                        continue
                    if sock in readable:
                        conn, addr = sock.accept()
                        label = peer_label(addr)
                        conn.settimeout(0.2)
                        with self._lock:
                            self._conns[label] = conn
                        self._peer = addr
                        if self._on_peer:
                            self._on_peer("on", label)
                        readable = [s for s in readable if s is not sock]
                    for s in readable:
                        label = next((lb for lb, c in items if c is s), None)
                        if label is None:
                            continue
                        try:
                            data = s.recv(4096)
                        except TimeoutError:
                            continue
                        except OSError:
                            self._drop_client(label)
                            continue
                        if not data:
                            self._drop_client(label)
                            continue
                        if self._on_rx:
                            self._on_rx(data, label)
                    continue

                src = self._sock if self._mode == "udp" else sock
                if src is None:
                    continue
                if self._mode == "udp":
                    data, addr = src.recvfrom(4096)
                    if data and self._on_rx:
                        self._on_rx(data, peer_label(addr))
                else:
                    data = src.recv(4096)
                    if not data:
                        break
                    if data and self._on_rx:
                        peer = self._peer or ("?", 0)
                        self._on_rx(data, peer_label(peer))
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop.is_set() and self._on_error:
                    self._on_error(str(exc))
                break
