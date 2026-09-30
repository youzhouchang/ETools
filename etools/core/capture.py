"""Portable raw traffic recordings; independent of presentation settings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MAX_CAPTURE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class CaptureRecord:
    timestamp: str
    direction: str
    peer: str
    hex: str

    @property
    def data(self) -> bytes:
        try:
            return bytes.fromhex(self.hex)
        except ValueError as exc:
            raise ValueError("Invalid record hex") from exc


def save_capture(path: str | Path, records: list[CaptureRecord]) -> None:
    Path(path).write_text(
        json.dumps(
            {"version": 1, "records": [asdict(r) for r in records]}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )


def load_capture(path: str | Path) -> list[CaptureRecord]:
    source = Path(path)
    if source.stat().st_size > MAX_CAPTURE_BYTES * 4:
        raise ValueError("Recording exceeds size limit")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("records"), list)
    ):
        raise ValueError("Unsupported recording")
    if len(payload["records"]) > 100000:
        raise ValueError("Recording exceeds record limit")
    records = []
    total = 0
    timezone_aware = None
    for item in payload["records"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid record")
        keys = ("timestamp", "direction", "peer", "hex")
        if not all(isinstance(item.get(key), str) for key in keys):
            raise ValueError("Invalid record fields")
        record = CaptureRecord(
            timestamp=item["timestamp"],
            direction=item["direction"],
            peer=item["peer"],
            hex=item["hex"],
        )
        if record.direction not in {"rx", "tx"}:
            raise ValueError("Invalid direction")
        try:
            parsed = datetime.fromisoformat(record.timestamp)
        except ValueError as exc:
            raise ValueError("Invalid timestamp") from exc
        aware = parsed.utcoffset() is not None
        if timezone_aware is not None and timezone_aware != aware:
            raise ValueError("Inconsistent timestamp timezone")
        timezone_aware = aware
        try:
            size = len(record.data)
        except ValueError as exc:
            raise ValueError("Invalid record hex") from exc
        if size > 64 * 1024:
            raise ValueError("Record exceeds size limit")
        total += size
        if total > MAX_CAPTURE_BYTES:
            raise ValueError("Recording exceeds size limit")
        records.append(record)
    return records
