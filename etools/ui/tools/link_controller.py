"""Connection lifecycle shared by the serial, Ethernet, and CAN pages."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from etools.core.checksum import append_checksum
from etools.core.hextext import parse_hex_input

_ENDINGS = {"none": b"", "lf": b"\n", "cr": b"\r", "crlf": b"\r\n"}


class LinkController(QObject):
    """Owns open/closed state and the shared outgoing-byte encoder.

    Pages keep their own sockets and protocol widgets. They assign
    ``page._opened`` through :class:`LinkToolPage`, which stores the flag here
    and tells the shell to refresh toolbar actions.
    """

    state_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.opened = False

    def set_opened(self, opened: bool) -> None:
        self.opened = bool(opened)
        self.state_changed.emit()

    def notify(self) -> None:
        self.state_changed.emit()

    @staticmethod
    def encode_payload(
        text: str,
        *,
        mode: str,
        encoding: str = "utf-8",
        ending: str = "none",
        checksum: str = "none",
    ) -> bytes:
        """Encode a send box into wire bytes (hex or text, checksum, line ending)."""
        data = parse_hex_input(text) if mode == "hex" else text.encode(encoding)
        if checksum and checksum != "none":
            data = append_checksum(data, checksum)
        return data + _ENDINGS.get(ending, b"")
