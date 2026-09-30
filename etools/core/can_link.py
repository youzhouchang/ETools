"""CAN bus link (python-can) with thread-safe RX callbacks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanEndpoint:
    """A selectable CAN backend + channel pair."""

    interface: str
    channel: str
    label: str


#: Curated backends. `virtual` works without hardware (great for demos/tests).
KNOWN_ENDPOINTS: list[CanEndpoint] = [
    CanEndpoint("virtual", "0", "Virtual bus 0"),
    CanEndpoint("virtual", "1", "Virtual bus 1"),
    CanEndpoint("socketcan", "can0", "socketcan can0"),
    CanEndpoint("socketcan", "can1", "socketcan can1"),
    CanEndpoint("pcan", "PCAN_USBBUS1", "PCAN USB 1"),
    CanEndpoint("pcan", "PCAN_USBBUS2", "PCAN USB 2"),
    CanEndpoint("ixxat", "0", "IXXAT 0"),
    CanEndpoint("kvaser", "0", "Kvaser 0"),
    CanEndpoint("vector", "0", "Vector 0"),
    CanEndpoint("slcan", "COM1", "SLCAN COM1"),
]

#: Common bitrates offered in the UI.
COMMON_BITRATES = [125000, 250000, 500000, 1000000]


def python_can_available() -> bool:
    try:
        import can  # noqa: F401
    except ImportError:
        return False
    return True


class CanLink:
    """Open/close a CAN interface and pump frames to a callback."""

    def __init__(self) -> None:
        self._bus: Any = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_rx: Callable[[Any], None] | None = None
        self._on_error: Callable[[str], None] | None = None

    @property
    def is_open(self) -> bool:
        return self._bus is not None

    def set_handlers(
        self,
        on_rx: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_rx = on_rx
        self._on_error = on_error

    def open(
        self,
        interface: str,
        channel: str,
        bitrate: int = 500000,
        *,
        fd: bool = False,
        data_bitrate: int | None = None,
    ) -> None:
        try:
            import can
        except ImportError as exc:
            raise RuntimeError("python-can not installed") from exc

        self.close()
        kwargs: dict[str, Any] = {
            "bustype": interface,
            "channel": channel,
            "bitrate": int(bitrate),
        }
        if fd:
            kwargs["fd"] = True
            if data_bitrate:
                kwargs["data_bitrate"] = int(data_bitrate)
        try:
            self._bus = can.interface.Bus(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"CAN open failed: {exc}") from exc
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def send(
        self,
        arbitration_id: int,
        data: bytes = b"",
        *,
        is_extended: bool = False,
        is_rtr: bool = False,
        is_fd: bool = False,
        bitrate_switch: bool = False,
    ) -> None:
        if not self.is_open:
            raise RuntimeError("CAN not open")
        import can

        msg = can.Message(
            arbitration_id=int(arbitration_id) & 0x1FFFFFFF,
            data=bytes(data),
            is_extended_id=bool(is_extended),
            is_remote_frame=bool(is_rtr),
            is_fd=bool(is_fd),
            bitrate_switch=bool(bitrate_switch),
        )
        self._bus.send(msg)

    def close(self) -> None:
        self._stop.set()
        reader, self._reader = self._reader, None
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        bus, self._bus = self._bus, None
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:  # noqa: BLE001
                pass

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            bus = self._bus
            if bus is None:
                break
            try:
                msg = bus.recv(timeout=0.05)
                if msg is not None and self._on_rx:
                    self._on_rx(msg)
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set() and self._on_error:
                    self._on_error(str(exc))
                break


def format_can_frame(msg: Any) -> str:
    """Human-readable one-liner for a python-can Message."""
    arb = getattr(msg, "arbitration_id", 0)
    ext = bool(getattr(msg, "is_extended_id", False))
    id_text = f"{arb:08X}" if ext else f"{arb:03X}"
    flags = []
    if ext:
        flags.append("EXT")
    if getattr(msg, "is_remote_frame", False):
        flags.append("RTR")
    if getattr(msg, "is_error_frame", False):
        flags.append("ERR")
    if getattr(msg, "is_fd", False):
        flags.append("FD")
        if getattr(msg, "bitrate_switch", False):
            flags.append("BRS")
    flag_text = f" [{' '.join(flags)}]" if flags else ""
    data = bytes(getattr(msg, "data", b"") or b"")
    return f"ID={id_text}{flag_text}  DLC={len(data)}  {data.hex(' ').upper()}"
