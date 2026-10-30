"""Sparse firmware image: load, merge, relocate, cut, fill, patch and export."""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
from pathlib import Path

from etools.core.hexdump import parse_elf, parse_srec

HEX_SUFFIXES = (".hex", ".ihx", ".ihex")
SREC_SUFFIXES = (".srec", ".s19", ".s28", ".s37", ".mot")
ELF_SUFFIXES = (".elf", ".axf", ".alf", ".out")
MAX_SPAN = 256 * 1024 * 1024


class ImageError(ValueError):
    """Raised for invalid image edits (overlap conflict, bad range, …)."""


@dataclass
class Segment:
    start: int
    data: bytearray

    @property
    def end(self) -> int:
        return self.start + len(self.data)


class SparseImage:
    """Address-sorted, non-overlapping, coalesced byte segments."""

    def __init__(self, segments: list[tuple[int, bytes]] | None = None) -> None:
        self._segs: list[Segment] = []
        for addr, data in segments or ():
            self.write(addr, data)

    # -- loading ----------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path, *, bin_base: int = 0x0800_0000) -> SparseImage:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(str(p))
        suffix = p.suffix.lower()
        if suffix in HEX_SUFFIXES:
            from intelhex import IntelHex

            ih = IntelHex(str(p))
            segs = [
                (s, bytes(ih.tobinarray(start=s, size=e - s))) for s, e in ih.segments()
            ]
        elif suffix in SREC_SUFFIXES:
            segs = parse_srec(p.read_text(encoding="ascii", errors="replace"))
        elif suffix in ELF_SUFFIXES:
            segs = parse_elf(p)
        else:
            segs = [(int(bin_base), p.read_bytes())]
        image = cls()
        for addr, data in segs:
            image.write(addr, data, overwrite=False)
        return image

    def copy(self) -> SparseImage:
        out = SparseImage()
        out._segs = [Segment(s.start, bytearray(s.data)) for s in self._segs]
        return out

    # -- queries ----------------------------------------------------------

    def segments(self) -> list[tuple[int, bytes]]:
        return [(s.start, bytes(s.data)) for s in self._segs]

    def __len__(self) -> int:
        return sum(len(s.data) for s in self._segs)

    @property
    def empty(self) -> bool:
        return not self._segs

    @property
    def start(self) -> int:
        return self._segs[0].start if self._segs else 0

    @property
    def end(self) -> int:
        return self._segs[-1].end if self._segs else 0

    def read(self, address: int, size: int, fill: int = 0xFF) -> bytes:
        out = bytearray([fill & 0xFF]) * max(0, size)
        stop = address + size
        for seg in self._segs:
            if seg.end <= address or seg.start >= stop:
                continue
            lo = max(seg.start, address)
            hi = min(seg.end, stop)
            out[lo - address : hi - address] = seg.data[lo - seg.start : hi - seg.start]
        return bytes(out)

    def overlaps(self, other: SparseImage) -> list[tuple[int, int]]:
        """Address ranges present in both images."""
        found: list[tuple[int, int]] = []
        for a in self._segs:
            for b in other._segs:
                lo, hi = max(a.start, b.start), min(a.end, b.end)
                if lo < hi:
                    found.append((lo, hi))
        return found

    def conflicts(self, other: SparseImage) -> list[tuple[int, int]]:
        """Overlapping ranges whose bytes differ."""
        return [
            (lo, hi)
            for lo, hi in self.overlaps(other)
            if self.read(lo, hi - lo) != other.read(lo, hi - lo)
        ]

    # -- editing ----------------------------------------------------------

    def write(self, address: int, data: bytes, *, overwrite: bool = True) -> None:
        if address < 0 or address + len(data) > 1 << 32:
            raise ImageError(f"Address out of range: 0x{address:X}+{len(data)}")
        if not data:
            return
        new = Segment(int(address), bytearray(data))
        keep: list[Segment] = []
        touching: list[Segment] = []
        for seg in self._segs:
            if seg.end < new.start or seg.start > new.end:
                keep.append(seg)
                continue
            olo, ohi = max(seg.start, new.start), min(seg.end, new.end)
            if not overwrite and olo < ohi:
                old = seg.data[olo - seg.start : ohi - seg.start]
                fresh = new.data[olo - new.start : ohi - new.start]
                if old != fresh:
                    raise ImageError(f"Overlapping data differs at 0x{olo:08X}..0x{ohi:08X}")
            touching.append(seg)
        lo = min([new.start] + [s.start for s in touching])
        hi = max([new.end] + [s.end for s in touching])
        buf = bytearray(hi - lo)
        for seg in touching:
            buf[seg.start - lo : seg.end - lo] = seg.data
        buf[new.start - lo : new.end - lo] = new.data
        keep.append(Segment(lo, buf))
        keep.sort(key=lambda s: s.start)
        self._segs = keep

    def merge(self, other: SparseImage, *, overwrite: bool = False) -> None:
        for addr, data in other.segments():
            self.write(addr, data, overwrite=overwrite)

    def delete(self, start: int, end: int) -> None:
        if end <= start:
            raise ImageError("Empty range")
        out: list[Segment] = []
        for seg in self._segs:
            if seg.end <= start or seg.start >= end:
                out.append(seg)
                continue
            if seg.start < start:
                out.append(Segment(seg.start, seg.data[: start - seg.start]))
            if seg.end > end:
                out.append(Segment(end, seg.data[end - seg.start :]))
        self._segs = out

    def crop(self, start: int, end: int) -> None:
        if end <= start:
            raise ImageError("Empty range")
        if start > 0:
            self.delete(0, start)
        if end < 1 << 32:
            self.delete(end, 1 << 32)

    def relocate(self, delta: int) -> None:
        if not self._segs:
            return
        if self.start + delta < 0 or self.end + delta > 1 << 32:
            raise ImageError("Relocation leaves the 32-bit address space")
        for seg in self._segs:
            seg.start += delta

    def rebase(self, new_start: int) -> None:
        self.relocate(int(new_start) - self.start)

    def fill_gaps(self, value: int = 0xFF, start: int | None = None, end: int | None = None) -> int:
        """Fill holes in [start, end); returns the number of bytes added."""
        lo = self.start if start is None else int(start)
        hi = self.end if end is None else int(end)
        if hi <= lo:
            return 0
        if hi - lo > MAX_SPAN:
            raise ImageError("Fill range too large")
        before = len(self)
        cursor = lo
        holes: list[tuple[int, int]] = []
        for seg in self._segs:
            if seg.end <= lo or seg.start >= hi:
                continue
            if seg.start > cursor:
                holes.append((cursor, seg.start))
            cursor = max(cursor, seg.end)
        if cursor < hi:
            holes.append((cursor, hi))
        for a, b in holes:
            self.write(a, bytes([value & 0xFF]) * (b - a))
        return len(self) - before

    def pad_to(self, alignment: int, value: int = 0xFF) -> None:
        """Extend the last segment so the image end is a multiple of alignment."""
        if alignment <= 1 or not self._segs:
            return
        rem = self.end % alignment
        if rem:
            self.write(self.end, bytes([value & 0xFF]) * (alignment - rem))

    # -- export -----------------------------------------------------------

    def to_bin(self, fill: int = 0xFF) -> tuple[int, bytes]:
        if not self._segs:
            return 0, b""
        if self.end - self.start > MAX_SPAN:
            raise ImageError("Image span too large for a flat binary")
        return self.start, self.read(self.start, self.end - self.start, fill)

    def _digest_stream(self) -> bytes:
        """Address-framed concatenation of the real segment bytes.

        Unlike ``to_bin``, this never materialises the gap-filled range
        between segments, so it stays well-defined even when an image spans
        far-apart regions (e.g. on-chip flash plus an external QSPI chip at
        0x90000000) that would otherwise blow past ``MAX_SPAN``. Each segment
        is framed with its address and length so the digest still changes if
        content moves between regions.
        """
        out = bytearray()
        for start, data in self.segments():
            out += start.to_bytes(4, "big")
            out += len(data).to_bytes(4, "big")
            out += data
        return bytes(out)

    def crc32(self) -> int:
        return zlib.crc32(self._digest_stream()) & 0xFFFFFFFF

    def sha256(self) -> str:
        return hashlib.sha256(self._digest_stream()).hexdigest()

    def save(self, path: str | Path, *, fill: int = 0xFF) -> str:
        """Write HEX / SREC / BIN by suffix; returns the format name."""
        p = Path(path)
        suffix = p.suffix.lower()
        if suffix in HEX_SUFFIXES:
            p.write_text(to_ihex(self), encoding="ascii")
            return "hex"
        if suffix in SREC_SUFFIXES:
            p.write_text(to_srec(self), encoding="ascii")
            return "srec"
        p.write_bytes(self.to_bin(fill)[1])
        return "bin"

    def summary(self) -> str:
        if not self._segs:
            return "empty"
        parts = [f"0x{s.start:08X}..0x{s.end - 1:08X} ({len(s.data)} B)" for s in self._segs]
        return f"{len(self._segs)} segment(s), {len(self)} bytes: " + ", ".join(parts)


def _ihex_record(rtype: int, address: int, payload: bytes) -> str:
    body = bytes([len(payload), (address >> 8) & 0xFF, address & 0xFF, rtype]) + payload
    checksum = (-sum(body)) & 0xFF
    return ":" + (body + bytes([checksum])).hex().upper()


def to_ihex(image: SparseImage, row: int = 32) -> str:
    lines: list[str] = []
    upper = -1
    for start, data in image.segments():
        offset = 0
        while offset < len(data):
            addr = start + offset
            if addr >> 16 != upper:
                upper = addr >> 16
                lines.append(_ihex_record(0x04, 0, upper.to_bytes(2, "big")))
            room = min(row, 0x10000 - (addr & 0xFFFF), len(data) - offset)
            lines.append(_ihex_record(0x00, addr & 0xFFFF, data[offset : offset + room]))
            offset += room
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def _srec_record(rtype: str, address: int, payload: bytes, addr_len: int) -> str:
    body = bytes([addr_len + len(payload) + 1]) + address.to_bytes(addr_len, "big") + payload
    checksum = 0xFF - (sum(body) & 0xFF)
    return f"S{rtype}" + (body + bytes([checksum])).hex().upper()


def to_srec(image: SparseImage, row: int = 32, header: str = "ETools") -> str:
    lines = [_srec_record("0", 0, header.encode("ascii", "replace")[:60], 2)]
    for start, data in image.segments():
        for offset in range(0, len(data), row):
            lines.append(_srec_record("3", start + offset, data[offset : offset + row], 4))
    # The S7 termination record's address is the execution start address;
    # use the image's lowest address so tools that jump there land in range
    # instead of at 0x00000000.
    lines.append(_srec_record("7", image.start, b"", 4))
    return "\n".join(lines) + "\n"
