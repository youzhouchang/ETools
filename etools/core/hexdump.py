"""Hex dump helpers: file segments and formatted lines."""

from __future__ import annotations

from pathlib import Path


def load_image_segments(path: str | Path) -> list[tuple[int, bytes]]:
    """Parse firmware into (base_address, data) segments."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    suffix = p.suffix.lower()
    raw = p.read_bytes()

    if suffix == ".hex":
        return parse_ihex(raw.decode("ascii", errors="replace"))
    if suffix in (".elf", ".axf"):
        return parse_elf(p)
    if suffix == ".srec":
        return parse_srec(raw.decode("ascii", errors="replace"))
    # .bin and unknown → treat as raw at flash base (caller may override)
    return [(0x0800_0000, raw)]


def parse_ihex(text: str) -> list[tuple[int, bytes]]:
    segments: list[tuple[int, bytes]] = []
    base = 0
    current: int | None = None
    buf = bytearray()

    def flush() -> None:
        nonlocal current, buf
        if current is not None and buf:
            segments.append((current, bytes(buf)))
        current = None
        buf = bytearray()

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        length, addr_hi, addr_lo, rtype = raw[0], raw[1], raw[2], raw[3]
        addr = (addr_hi << 8) | addr_lo
        payload = raw[4 : 4 + length]
        if rtype == 0x00:
            abs_addr = base + addr
            if current is None or abs_addr != current + len(buf):
                flush()
                current = abs_addr
            buf.extend(payload)
        elif rtype == 0x04:
            flush()
            base = int.from_bytes(payload, "big") << 16
        elif rtype == 0x02:
            flush()
            base = int.from_bytes(payload, "big") << 4
        elif rtype == 0x01:
            flush()
            break
        else:
            flush()
    flush()
    return segments


def parse_srec(text: str) -> list[tuple[int, bytes]]:
    segments: list[tuple[int, bytes]] = []
    current: int | None = None
    buf = bytearray()

    def flush() -> None:
        nonlocal current, buf
        if current is not None and buf:
            segments.append((current, bytes(buf)))
        current = None
        buf = bytearray()

    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] != "S":
            continue
        rtype = line[1]
        if rtype == "0":
            continue
        if rtype in ("7", "8", "9"):
            flush()
            break
        if rtype not in ("1", "2", "3"):
            continue
        raw = bytes.fromhex(line[2:])
        count = raw[0]
        if rtype == "1":
            addr = int.from_bytes(raw[1:3], "big")
            payload = raw[3:count]
        elif rtype == "2":
            addr = int.from_bytes(raw[1:4], "big")
            payload = raw[4:count]
        else:
            addr = int.from_bytes(raw[1:5], "big")
            payload = raw[5:count]
        if current is None or addr != current + len(buf):
            flush()
            current = addr
        buf.extend(payload)
    flush()
    return segments


def parse_elf(path: Path) -> list[tuple[int, bytes]]:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as exc:
        raise RuntimeError("pyelftools is required for ELF preview") from exc

    segments: list[tuple[int, bytes]] = []
    with path.open("rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            data = seg.data()
            if data:
                segments.append((int(seg["p_paddr"]), data))
    return segments


def merge_segments(segments: list[tuple[int, bytes]]) -> list[tuple[int, bytes]]:
    """Sort and merge contiguous segments (gaps stay separate)."""
    if not segments:
        return []
    items = sorted(segments, key=lambda x: x[0])
    merged: list[tuple[int, bytes]] = []
    for addr, data in items:
        if merged:
            paddr, pdata = merged[-1]
            if paddr + len(pdata) == addr:
                merged[-1] = (paddr, pdata + data)
                continue
            if paddr + len(pdata) > addr:
                # overlap: keep first, skip overlapping prefix
                overlap = paddr + len(pdata) - addr
                data = data[overlap:]
                if not data:
                    continue
        merged.append((addr, data))
    return merged


def format_hex_lines(
    base_addr: int,
    data: bytes,
    width: int = 16,
    max_bytes: int | None = None,
) -> list[tuple[str, str, str]]:
    """Return list of (address, hex_bytes, ascii)."""
    if max_bytes is not None:
        data = data[:max_bytes]
    rows: list[tuple[str, str, str]] = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        # pad hex column
        pad = width - len(chunk)
        if pad:
            hex_part = hex_part + ("   " * pad)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append((f"{base_addr + off:08X}", hex_part, ascii_part))
    return rows


def segments_summary(segments: list[tuple[int, bytes]]) -> str:
    if not segments:
        return "空"
    total = sum(len(d) for _, d in segments)
    lo = min(a for a, _ in segments)
    hi = max(a + len(d) for a, d in segments)
    return f"{len(segments)} 段 · {total:,} 字节 · 0x{lo:08X}–0x{hi - 1:08X}"
