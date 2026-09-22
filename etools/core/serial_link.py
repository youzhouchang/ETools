"""Serial port link (pyserial) with thread-safe RX callbacks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def list_serial_ports() -> list[tuple[str, str]]:
    """Return [(device, description), ...]. Uses pyserial if installed."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out: list[tuple[str, str]] = []
    for p in list_ports.comports():
        desc = p.description or p.hwid or ""
        out.append((p.device, f"{p.device} — {desc}" if desc else p.device))
    return out


class SerialLink:
    """Open/close a serial port and pump bytes to a callback."""

    def __init__(self) -> None:
        self._ser: Any = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_rx: Callable[[bytes], None] | None = None
        self._on_error: Callable[[str], None] | None = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def set_handlers(
        self,
        on_rx: Callable[[bytes], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_rx = on_rx
        self._on_error = on_error

    def open(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
    ) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial not installed") from exc

        self.close()
        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }
        self._ser = serial.Serial(
            port=port,
            baudrate=int(baudrate),
            bytesize=int(bytesize),
            parity=parity_map.get(parity.upper(), serial.PARITY_NONE),
            stopbits=float(stopbits),
            timeout=0.05,
        )
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise RuntimeError("serial not open")
        self._ser.write(data)
        self._ser.flush()

    def set_dtr(self, on: bool) -> None:
        if self.is_open:
            self._ser.dtr = bool(on)

    def set_rts(self, on: bool) -> None:
        if self.is_open:
            self._ser.rts = bool(on)

    def close(self) -> None:
        self._stop.set()
        reader, self._reader = self._reader, None
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                break
            try:
                if ser.in_waiting:
                    data = ser.read(ser.in_waiting)
                    if data and self._on_rx:
                        self._on_rx(data)
                else:
                    data = ser.read(1)
                    if data and self._on_rx:
                        self._on_rx(data)
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set() and self._on_error:
                    self._on_error(str(exc))
                break
