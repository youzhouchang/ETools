"""ELF/DWARF symbol discovery for the variable monitor.

The parser intentionally keeps the public model small.  ELF loading happens
once when a firmware file is selected; live values are read by the pyOCD
monitor using the addresses returned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ElfVariable:
    """A monitorable object symbol from an ELF image."""

    name: str
    address: int
    size: int
    type_name: str = "unsigned"
    kind: str = "integer"
    encoding: str = "unsigned"
    byte_size: int = 4

    @property
    def display_address(self) -> str:
        return f"0x{self.address:08X}"


@dataclass(frozen=True)
class ElfImage:
    """Parsed ELF image and its monitorable variables."""

    path: Path
    variables: tuple[ElfVariable, ...]
    elf_class: int
    machine: str
    little_endian: bool
    has_dwarf: bool


def _attr(die: Any, key: str, default: Any = None) -> Any:
    item = getattr(die, "attributes", {}).get(key)
    return getattr(item, "value", default) if item is not None else default


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _expr_address(raw: Any, *, address_size: int, little_endian: bool) -> int | None:
    """Decode the common DW_OP_addr location expression."""
    if not isinstance(raw, (bytes, bytearray)) or not raw or raw[0] != 0x03:
        return None
    width = min(max(1, int(address_size or 4)), len(raw) - 1)
    return int.from_bytes(raw[1 : 1 + width], "little" if little_endian else "big")


class _TypeResolver:
    def __init__(self, dwarf: Any) -> None:
        self.dwarf = dwarf
        self.cache: dict[int, dict[str, Any]] = {}

    def resolve(self, die: Any | None) -> dict[str, Any]:
        if die is None:
            return {"name": "unsigned", "kind": "integer", "encoding": "unsigned", "size": 4}
        offset = int(getattr(die, "offset", 0) or 0)
        if offset in self.cache:
            return self.cache[offset]
        # Cache a placeholder first to break recursive struct/pointer types.
        result: dict[str, Any] = {"name": "?", "kind": "integer", "encoding": "unsigned", "size": 4}
        self.cache[offset] = result
        tag = str(getattr(die, "tag", ""))
        size = int(_attr(die, "DW_AT_byte_size", 0) or 0)
        name = _text(_attr(die, "DW_AT_name", ""))
        if tag == "DW_TAG_pointer_type":
            result.update(
                name=name or "pointer", kind="pointer", encoding="unsigned", size=size or 4
            )
            child = self.resolve(self._type_die(die))
            result["target"] = child
        elif tag in {
            "DW_TAG_const_type",
            "DW_TAG_volatile_type",
            "DW_TAG_restrict_type",
            "DW_TAG_typedef",
        }:
            child = self.resolve(self._type_die(die))
            result.update(child)
            if name:
                result["name"] = name
        elif tag == "DW_TAG_array_type":
            child = self.resolve(self._type_die(die))
            count = 0
            for child_die in die.iter_children():
                if getattr(child_die, "tag", "") != "DW_TAG_subrange_type":
                    continue
                count = int(_attr(child_die, "DW_AT_count", 0) or 0)
                if not count:
                    upper = _attr(child_die, "DW_AT_upper_bound", None)
                    count = int(upper) + 1 if upper is not None else 0
                break
            elem_size = int(child.get("size", 0) or 0)
            result.update(
                name=name or f"{child.get('name', '?')}[]",
                kind="array",
                encoding=child.get("encoding", "unsigned"),
                size=size or (elem_size * count if count else elem_size),
                count=count,
                target=child,
            )
        elif tag in {"DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"}:
            result.update(
                name=name or tag.removeprefix("DW_TAG_"),
                kind="struct",
                encoding="aggregate",
                size=size or 1,
            )
        elif tag == "DW_TAG_enumeration_type":
            result.update(name=name or "enum", kind="integer", encoding="signed", size=size or 4)
        elif tag == "DW_TAG_base_type":
            enc = _text(_attr(die, "DW_AT_encoding", "unsigned"))
            result.update(
                name=name or "unsigned",
                kind="float" if enc in {"DW_ATE_float", "4", "8"} else "integer",
                encoding=enc,
                size=size or 4,
            )
        else:
            result.update(name=name or tag.removeprefix("DW_TAG_") or "unsigned", size=size or 4)
        return result

    def _type_die(self, die: Any) -> Any | None:
        ref = _attr(die, "DW_AT_type", None)
        if ref is None or self.dwarf is None:
            return None
        try:
            return die.get_DIE_from_attribute("DW_AT_type")
        except Exception:
            try:
                return self.dwarf.get_DIE_from_refaddr(int(ref))
            except Exception:
                return None


def load_elf(path: str | Path) -> ElfImage:
    """Load symbols and basic DWARF types from *path*.

    ``pyelftools`` is imported lazily so the rest of ETools remains usable on
    systems that only want flashing and serial tools.
    """
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection

    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    with file_path.open("rb") as stream:
        elf = ELFFile(stream)
        little = bool(elf.little_endian)
        address_size = int(elf.elfclass // 8)
        dwarf = elf.get_dwarf_info() if elf.has_dwarf_info() else None
        resolver = _TypeResolver(dwarf)
        symbols: dict[tuple[str, int], ElfVariable] = {}

        # The symbol table remains useful even when the compiler emitted no
        # DWARF.  It also provides the final linked address for static objects.
        for section in elf.iter_sections():
            if not isinstance(section, SymbolTableSection):
                continue
            for symbol in section.iter_symbols():
                name = _text(symbol.name).strip()
                info = symbol["st_info"]
                if not name or info["type"] not in {"STT_OBJECT", "STT_COMMON", "STT_TLS"}:
                    continue
                address = int(symbol["st_value"] or 0)
                size = int(symbol["st_size"] or 0)
                if address <= 0 or address >= 0x1_0000_0000:
                    continue
                size = max(1, min(size or 4, 0x100000))
                symbols[(name, address)] = ElfVariable(name, address, size, byte_size=size)

        if dwarf is not None:
            for cu in dwarf.iter_CUs():
                root = cu.get_top_DIE()
                for die in root.iter_DIEs():
                    if getattr(die, "tag", "") not in {"DW_TAG_variable", "DW_TAG_constant"}:
                        continue
                    name = _text(_attr(die, "DW_AT_name", "")).strip()
                    if not name:
                        continue
                    address = _expr_address(
                        _attr(die, "DW_AT_location", None),
                        address_size=address_size,
                        little_endian=little,
                    )
                    if not address:
                        continue
                    typ = resolver.resolve(resolver._type_die(die))
                    size = max(1, int(typ.get("size", 0) or 0))
                    # Prefer a symbol's exact size when it exists.
                    current = symbols.get((name, address))
                    if current is not None:
                        size = max(size, current.size)
                    symbols[(name, address)] = ElfVariable(
                        name=name,
                        address=address,
                        size=min(size, 0x100000),
                        type_name=str(typ.get("name") or "unsigned"),
                        kind=str(typ.get("kind") or "integer"),
                        encoding=str(typ.get("encoding") or "unsigned"),
                        byte_size=max(1, int(typ.get("size", size) or size)),
                    )

        variables = tuple(
            sorted(symbols.values(), key=lambda item: (item.name.lower(), item.address))
        )
        machine = _text(getattr(elf, "get_machine_arch", lambda: "")())
        return ElfImage(file_path, variables, int(elf.elfclass), machine, little, dwarf is not None)


__all__ = ["ElfImage", "ElfVariable", "load_elf"]
