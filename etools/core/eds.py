"""CANopen EDS (Electronic Data Sheet) parser.

Parses the common CiA 306 INI-style EDS enough to support:
- object dictionary browsing (index/subindex → name, type, access, default)
- PDO mapping extraction (0x1A00 / 0x1600 families)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EdsEntry:
    index: int
    subindex: int | None
    name: str = ""
    data_type: str = ""
    access: str = ""
    default: str = ""
    comments: str = ""


@dataclass
class EdsFile:
    path: str = ""
    file_name: str = ""
    vendor_name: str = ""
    vendor_number: int = 0
    product_name: str = ""
    product_number: int = 0
    revision: str = ""
    entries: dict[tuple[int, int | None], EdsEntry] = field(default_factory=dict)

    def get(self, index: int, subindex: int | None = None) -> EdsEntry | None:
        return self.entries.get((int(index) & 0xFFFF, subindex))

    def objects(self) -> list[EdsEntry]:
        return sorted(
            self.entries.values(),
            key=lambda e: (e.index, e.subindex if e.subindex is not None else -1),
        )

    def find(self, needle: str) -> list[EdsEntry]:
        low = (needle or "").lower()
        return [e for e in self.objects() if low in e.name.lower()]

    def pdo_mappings(self) -> dict[int, list[tuple[int, int, int]]]:
        """Return {pdo_cob_offset: [(index, subindex, bitlen), ...]}.

        Keys: 0x1600→0 for RPDO1, 0x1A00→0 for TPDO1, etc.
        """
        out: dict[int, list[tuple[int, int, int]]] = {}
        for (index, sub), entry in self.entries.items():
            if sub is None:
                continue
            # Mapping entry lives at 0x1Axx sub 1..n / 0x16xx sub 1..n
            if index < 0x1600 or index > 0x1BFF:
                continue
            if sub < 1:
                continue
            raw = (entry.default or "").strip().lower()
            if not raw:
                continue
            value = _parse_int(raw)
            if value is None:
                continue
            obj_index = (value >> 16) & 0xFFFF
            obj_sub = (value >> 8) & 0xFF
            bitlen = value & 0xFF
            if obj_index == 0 and obj_sub == 0:
                continue
            out.setdefault(index, []).append((obj_index, obj_sub, bitlen))
        for k in out:
            out[k] = sorted(out[k], key=lambda t: (t[0], t[1]))
        return out

    def mapping_labels(self) -> list[tuple[int, str, list[tuple[int, int, int, str]]]]:
        """Human-readable PDO map rows: (pdo_index, pdo_name, [(obj, sub, bits, name)])."""
        maps = self.pdo_mappings()
        rows: list[tuple[int, str, list[tuple[int, int, int, str]]]] = []
        for pdo_index in sorted(maps):
            head = self.get(pdo_index, None)
            items: list[tuple[int, int, int, str]] = []
            for obj_index, obj_sub, bitlen in maps[pdo_index]:
                entry = self.get(obj_index, obj_sub) or self.get(obj_index, None)
                name = entry.name if entry else f"0x{obj_index:04X}/{obj_sub}"
                items.append((obj_index, obj_sub, bitlen, name))
            rows.append((pdo_index, head.name if head else f"0x{pdo_index:04X}", items))
        return rows


def _parse_int(text: str) -> int | None:
    t = (text or "").strip().lower().replace("_", "")
    if not t:
        return None
    try:
        if t.startswith("0x"):
            return int(t, 16)
        return int(t, 0)
    except ValueError:
        return None


_SECTION_RE = re.compile(r"^\[(.+)\]\s*$")
_KV_RE = re.compile(r"^([^=;#]+)=(.*)$")


def parse_eds(path: str | Path) -> EdsFile:
    """Parse an EDS/DCF file into :class:`EdsFile`."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return parse_eds_text(text, path=str(p))


def parse_eds_text(text: str, *, path: str = "") -> EdsFile:
    eds = EdsFile(path=path)
    section: str | None = None
    pending_sub: dict[str, str] = {}
    pending_key: tuple[int, int | None] | None = None

    def flush() -> None:
        nonlocal pending_sub, pending_key
        if pending_key is None:
            pending_sub = {}
            return
        index, sub = pending_key
        name = pending_sub.get("ParameterName", pending_sub.get("parametername", ""))
        dtype = pending_sub.get("DataType", pending_sub.get("datatype", ""))
        access = pending_sub.get("AccessType", pending_sub.get("accesstype", ""))
        default = pending_sub.get("DefaultValue", pending_sub.get("defaultvalue", ""))
        comments = pending_sub.get("Comments", pending_sub.get("comments", ""))
        eds.entries[(index, sub)] = EdsEntry(
            index=index,
            subindex=sub,
            name=name,
            data_type=dtype,
            access=access,
            default=default,
            comments=comments,
        )
        pending_sub = {}
        pending_key = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        m = _SECTION_RE.match(line)
        if m:
            flush()
            section = m.group(1).strip()
            low = section.lower()
            if low == "fileinfo":
                pending_key = None
            elif low == "deviceinfo":
                pending_key = None
            else:
                parsed = _parse_object_key(section)
                pending_key = parsed
            continue
        kv = _KV_RE.match(line)
        if not kv or section is None:
            continue
        key = kv.group(1).strip()
        val = kv.group(2).strip()
        low = section.lower()
        if low == "fileinfo":
            if key.lower() == "filename":
                eds.file_name = val
        elif low == "deviceinfo":
            kl = key.lower()
            if kl == "vendorname":
                eds.vendor_name = val
            elif kl == "vendornumber":
                eds.vendor_number = _parse_int(val) or 0
            elif kl == "productname":
                eds.product_name = val
            elif kl == "productnumber":
                eds.product_number = _parse_int(val) or 0
            elif kl == "revisionnumber":
                eds.revision = val
        elif pending_key is not None:
            pending_sub[key] = val
    flush()
    return eds


def _parse_object_key(section: str) -> tuple[int, int | None] | None:
    """'1018sub2' / '0x1018sub2' / '1018' → (0x1018, 2)."""
    s = section.strip().lower().replace(" ", "")
    if s.startswith("0x"):
        s = s[2:]
    m = re.match(r"^([0-9a-f]+)(?:sub([0-9a-f]+))?$", s)
    if not m:
        return None
    try:
        index = int(m.group(1), 16)
    except ValueError:
        return None
    sub = int(m.group(2), 16) if m.group(2) else None
    return index, sub
