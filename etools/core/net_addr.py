"""Local IPv4 helpers for smarter address pre-fill in network tools."""

from __future__ import annotations

import socket


def local_ipv4() -> str:
    """Best-effort outbound-facing IPv4 of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:  # noqa: BLE001
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:  # noqa: BLE001
        pass
    return "127.0.0.1"


def suggest_remote_ipv4(local_ip: str | None = None) -> str:
    """Guess a useful peer address on the same /24 as *local_ip*.

    Typical embedded bench: device sits at ``.1`` / ``.10`` / ``.100`` while
    the PC is ``.xxx``. Prefer ``.1`` (gateway / common static), else bump the
    last octet so we never suggest the PC itself.
    """
    ip = (local_ip if local_ip is not None else local_ipv4()).strip()
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return "192.168.1.1"
    last = int(parts[3])
    prefix = ".".join(parts[:3])
    if last != 1:
        return f"{prefix}.1"
    return f"{prefix}.{min(254, last + 1)}"
