"""Network diagnostics: TCP port check and ICMP-less reachability helpers."""

from __future__ import annotations

import socket
import time


def check_tcp_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float, str]:
    """Try a TCP connect. Returns (ok, elapsed_ms, message)."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed = (time.perf_counter() - start) * 1000.0
            return True, elapsed, "open"
    except TimeoutError:
        elapsed = (time.perf_counter() - start) * 1000.0
        return False, elapsed, "timeout"
    except OSError as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        return False, elapsed, str(exc)


def check_udp_port(host: str, port: int, timeout: float = 1.0) -> tuple[bool, float, str]:
    """Best-effort UDP probe: send empty datagram; ICMP unreachable may surface."""
    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(b"", (host, int(port)))
        try:
            sock.recvfrom(256)
            return True, (time.perf_counter() - start) * 1000.0, "reply"
        except TimeoutError:
            # No reply is normal for UDP; treat as reachable-but-unknown.
            return True, (time.perf_counter() - start) * 1000.0, "no-reply"
    except OSError as exc:
        return False, (time.perf_counter() - start) * 1000.0, str(exc)
    finally:
        sock.close()
