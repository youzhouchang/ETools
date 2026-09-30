"""Serial port link (pyserial) with thread-safe RX callbacks."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Port availability classes returned by :func:`probe_port`.
PORT_OK = "ok"
PORT_BUSY = "busy"
PORT_ERROR = "error"
PORT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class PortEntry:
    """A serial port candidate with optional availability status."""

    device: str
    description: str = ""
    status: str = PORT_UNKNOWN
    detail: str = ""

    @property
    def label(self) -> str:
        """Display text without a status suffix."""
        return f"{self.device} — {self.description}" if self.description else self.device


def probe_port(device: str) -> tuple[str, str]:
    """Classify *device* with a brief exclusive open. Returns ``(status, detail)``.

    DTR/RTS are forced low before close to limit reset side-effects on
    Arduino-like boards. Callers should not probe on a tight poll loop.
    """
    try:
        import serial
    except ImportError:
        return PORT_UNKNOWN, ""
    ser: Any = None
    try:
        ser = serial.Serial()
        ser.port = device
        ser.baudrate = 9600
        ser.timeout = 0
        ser.write_timeout = 0
        ser.dsrdtr = False
        ser.rtscts = False
        ser.xonxoff = False
        try:
            ser.exclusive = True
        except Exception:  # noqa: BLE001 — not supported on all backends
            pass
        ser.open()
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:  # noqa: BLE001
            pass
        return PORT_OK, ""
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        low = msg.lower()
        busy_markers = (
            "access is denied",
            "permission",
            "busy",
            "in use",
            "being used",
        )
        if any(k in low for k in busy_markers):
            return PORT_BUSY, msg
        return PORT_ERROR, msg
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass


def list_serial_ports(*, probe: bool = False) -> list[PortEntry]:
    """Return serial ports as :class:`PortEntry` rows.

    When *probe* is true each port is briefly opened to classify availability
    (``ok`` / ``busy`` / ``error``). Keep probe off for hotplug polling.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out: list[PortEntry] = []
    for p in list_ports.comports():
        desc = p.description or p.hwid or ""
        status, detail = PORT_UNKNOWN, ""
        if probe:
            status, detail = probe_port(p.device)
        out.append(PortEntry(p.device, desc, status, detail))
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
        flow_control: str = "none",
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
        flow = str(flow_control or "none").lower()
        self._ser = serial.Serial(
            port=port,
            baudrate=int(baudrate),
            bytesize=int(bytesize),
            parity=parity_map.get(parity.upper(), serial.PARITY_NONE),
            stopbits=float(stopbits),
            xonxoff=flow == "software",
            rtscts=flow == "hardware",
            dsrdtr=False,
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

    def send_break(self, duration: float = 0.25) -> None:
        """Assert the serial BREAK condition briefly (as in minicom Ctrl-A F)."""
        if not self.is_open:
            raise RuntimeError("serial not open")
        self._ser.send_break(duration=max(0.0, float(duration)))

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
