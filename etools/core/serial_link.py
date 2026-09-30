"""Serial port link (pyserial) with thread-safe RX callbacks."""

from __future__ import annotations

import os
import queue
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


def _registry_serialcomm() -> dict[str, str]:
    """Windows SERIALCOMM map: device name → friendly hint.

    pySerial's SetupAPI walk misses some virtual pairs (e.g. VSPD ``VSerial``),
    but the kernel still publishes them under ``HARDWARE\\DEVICEMAP\\SERIALCOMM``.
    """
    if os.name != "nt":
        return {}
    try:
        import winreg
    except ImportError:
        return {}
    out: dict[str, str] = {}
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM", 0, winreg.KEY_READ
        )
    except OSError:
        return {}
    try:
        index = 0
        while True:
            try:
                _name, value, _kind = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            port = str(value).strip()
            if not port:
                continue
            # Map VSerial / named pairs to a readable description.
            hint = "virtual"
            raw = str(_name).rsplit("\\", 1)[-1].lower()
            if raw.startswith("vserial"):
                hint = "virtual (VSPD/VSerial)"
            elif raw.startswith("usbdser") or raw.startswith("usbser"):
                hint = "USB serial"
            out[port] = hint
    finally:
        winreg.CloseKey(key)
    return out


def _friendly_description(device: str, desc: str, hwid: str = "") -> str:
    """Enrich sparse descriptions so DAPLink / virtual pairs are obvious."""
    blob = f"{desc} {hwid} {device}".upper()
    text = (desc or "").strip()
    # pyserial sometimes returns just the device name as description.
    if not text or text.upper() == device.upper():
        reg = _registry_serialcomm().get(device, "")
        text = reg or "serial"
    if "0D28" in blob or "CMSIS" in blob or "DAPLINK" in blob or "DAP-LINK" in blob:
        if "DAP" not in text.upper():
            return f"{text} · DAPLink/CMSIS-DAP"
    if "VSERIAL" in blob or "VSPD" in blob:
        return f"{text} · Virtual"
    return text


def list_serial_ports(*, probe: bool = False) -> list[PortEntry]:
    """Return serial ports as :class:`PortEntry` rows.

    Combines pySerial enumeration with a Windows SERIALCOMM fallback so
    virtual pairs (VSPD etc.) are not silently dropped. When *probe* is true
    each port is briefly opened to classify availability (``ok`` / ``busy``).
    """
    found: dict[str, PortEntry] = {}
    try:
        from serial.tools import list_ports

        for p in list_ports.comports():
            device = str(p.device or "")
            if not device:
                continue
            desc = p.description or p.hwid or ""
            desc = _friendly_description(device, desc, getattr(p, "hwid", "") or "")
            status, detail = PORT_UNKNOWN, ""
            if probe:
                status, detail = probe_port(device)
            found[device] = PortEntry(device, desc, status, detail)
    except ImportError:
        pass

    # Fallback: ports the SetupAPI walk missed (common with VSPD virtual pairs).
    for device, hint in _registry_serialcomm().items():
        if device in found:
            continue
        status, detail = PORT_UNKNOWN, ""
        if probe:
            status, detail = probe_port(device)
        found[device] = PortEntry(device, hint, status, detail)

    def _sort_key(entry: PortEntry) -> tuple[int, str]:
        name = entry.device.upper()
        if name.startswith("COM") and name[3:].isdigit():
            return (0, f"{int(name[3:]):05d}")
        return (1, name)

    return sorted(found.values(), key=_sort_key)


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


class SerialLink:
    """Open/close a serial port and pump bytes to a callback."""

    def __init__(self) -> None:
        self._ser: Any = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_rx: Callable[[bytes], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._transfer_q: queue.Queue[bytes] | None = None

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

    def begin_transfer(self) -> None:
        """Route RX into a private queue for protocol sessions (YMODEM…)."""
        self._transfer_q = queue.Queue()

    def transfer_read(self, timeout: float = 1.0) -> bytes:
        q = self._transfer_q
        if q is None:
            return b""
        try:
            chunk = q.get(timeout=max(0.01, float(timeout)))
        except queue.Empty:
            return b""
        # Drain anything already queued without blocking.
        while True:
            try:
                chunk += q.get_nowait()
            except queue.Empty:
                break
        return bytes(chunk)

    def end_transfer(self) -> None:
        self._transfer_q = None

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
                else:
                    data = ser.read(1)
                if not data:
                    continue
                q = self._transfer_q
                if q is not None:
                    q.put(data)
                    continue
                if self._on_rx:
                    self._on_rx(data)
            except Exception as exc:  # noqa: BLE001
                if not self._stop.is_set() and self._on_error:
                    self._on_error(str(exc))
                break
