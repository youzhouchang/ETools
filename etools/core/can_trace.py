"""CAN frame trace record / playback (CSV).

Format (header + rows)::

    time,direction,id,extended,rtr,fd,data
    0.000000,rx,123,0,0,0,01 02 03 04

``time`` is seconds since the recording started (float). Playback restores
inter-frame delays with an optional speed factor.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any


@dataclass(frozen=True)
class TraceFrame:
    t: float
    direction: str  # "rx" | "tx"
    arbitration_id: int
    is_extended: bool = False
    is_rtr: bool = False
    is_fd: bool = False
    data: bytes = b""

    def data_hex(self) -> str:
        return self.data.hex(" ").upper()

    @classmethod
    def from_message(cls, t: float, direction: str, msg: Any) -> TraceFrame:
        return cls(
            t=float(t),
            direction=direction,
            arbitration_id=int(getattr(msg, "arbitration_id", 0)),
            is_extended=bool(getattr(msg, "is_extended_id", False)),
            is_rtr=bool(getattr(msg, "is_remote_frame", False)),
            is_fd=bool(getattr(msg, "is_fd", False)),
            data=bytes(getattr(msg, "data", b"") or b""),
        )


class TraceWriter:
    """Append-only CSV writer for CAN traces."""

    HEADER = ["time", "direction", "id", "extended", "rtr", "fd", "data"]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh: IO[str] | None = open(self.path, "w", encoding="utf-8", newline="")
        self._csv = csv.writer(self._fh)
        self._csv.writerow(self.HEADER)
        self._t0 = time.monotonic()
        self.count = 0

    def write(self, frame: TraceFrame) -> None:
        if self._fh is None:
            raise RuntimeError("trace writer closed")
        self._csv.writerow(
            [
                f"{frame.t:.6f}",
                frame.direction,
                f"{frame.arbitration_id:X}",
                int(frame.is_extended),
                int(frame.is_rtr),
                int(frame.is_fd),
                frame.data_hex(),
            ]
        )
        self.count += 1

    def write_msg(self, direction: str, msg: Any) -> None:
        self.write(TraceFrame.from_message(time.monotonic() - self._t0, direction, msg))

    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            fh.close()


def read_trace(path: str | Path) -> list[TraceFrame]:
    p = Path(path)
    frames: list[TraceFrame] = []
    with open(p, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            frames.append(_row_to_frame(row))
    return frames


def _row_to_frame(row: dict[str, str]) -> TraceFrame:
    data_hex = (row.get("data") or "").replace(" ", "").replace(":", "")
    try:
        data = bytes.fromhex(data_hex) if data_hex else b""
    except ValueError:
        data = b""
    try:
        arb = int((row.get("id") or "0").strip(), 16)
    except ValueError:
        arb = 0
    try:
        t = float(row.get("time") or 0)
    except ValueError:
        t = 0.0
    return TraceFrame(
        t=t,
        direction=(row.get("direction") or "rx").strip().lower(),
        arbitration_id=arb,
        is_extended=str(row.get("extended") or "0").strip() in {"1", "true", "True"},
        is_rtr=str(row.get("rtr") or "0").strip() in {"1", "true", "True"},
        is_fd=str(row.get("fd") or "0").strip() in {"1", "true", "True"},
        data=data,
    )


class TracePlayer:
    """Replay a recorded trace with original (optionally scaled) timing."""

    def __init__(self, frames: list[TraceFrame], *, speed: float = 1.0) -> None:
        self.frames = list(frames)
        self.speed = max(0.01, float(speed))
        self._i = 0

    def __iter__(self) -> Iterator[tuple[float, TraceFrame]]:
        """Yield (delay_before_seconds, frame)."""
        prev_t = 0.0
        for i, frame in enumerate(self.frames):
            delay = max(0.0, (frame.t - prev_t) / self.speed) if i else 0.0
            prev_t = frame.t
            yield delay, frame

    def remaining(self) -> int:
        return max(0, len(self.frames) - self._i)
