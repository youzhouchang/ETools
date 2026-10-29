"""HardFault register decode and RTOS thread snapshot.

The decode helpers are pure. ``capture`` talks to a live pyOCD session and
only halts a running core when asked to.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CFSR = 0xE000ED28
HFSR = 0xE000ED2C
DFSR = 0xE000ED30
MMFAR = 0xE000ED34
BFAR = 0xE000ED38

_ELF_SUFFIXES = {".elf", ".axf", ".out"}

_MMFSR = (
    ("IACCVIOL", 0),
    ("DACCVIOL", 1),
    ("MUNSTKERR", 3),
    ("MSTKERR", 4),
)
_BFSR = (
    ("IBUSERR", 0),
    ("PRECISERR", 1),
    ("IMPRECISERR", 2),
    ("UNSTKERR", 3),
    ("STKERR", 4),
    ("LSPERR", 5),
)
_UFSR = (
    ("UNDEFINSTR", 0),
    ("INVSTATE", 1),
    ("INVPC", 2),
    ("NOCP", 3),
    ("STKOF", 4),
    ("UNALIGNED", 8),
    ("DIVBYZERO", 9),
)
_HFSR = (
    ("VECTTBL", 1),
    ("FORCED", 30),
    ("DEBUGEVT", 31),
)
_DFSR = (
    ("HALTED", 0),
    ("BKPT", 1),
    ("DWTTRAP", 2),
    ("VCATCH", 3),
    ("EXTERNAL", 4),
)
_FRAME_REGS = ("r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr")

_RTOS_LABELS = {
    "freertos": "FreeRTOS",
    "zephyr": "Zephyr",
    "rtx5": "RTX5",
    "threadx": "ThreadX",
    "argon": "Argon",
}


@dataclass(frozen=True)
class FaultFlag:
    group: str
    name: str


@dataclass
class FaultSnapshot:
    ok: bool = False
    error: str = ""
    detail: str = ""
    cfsr: int = 0
    hfsr: int = 0
    dfsr: int = 0
    mmfar: int = 0
    bfar: int = 0
    mmfar_valid: bool = False
    bfar_valid: bool = False
    flags: tuple[FaultFlag, ...] = ()
    pc: int | None = None
    lr: int | None = None
    xpsr: int | None = None
    msp: int | None = None
    psp: int | None = None
    ipsr: int = 0
    frame_stack: str = ""
    frame: tuple[tuple[str, int], ...] = ()
    pc_symbol: str = ""
    frame_pc_symbol: str = ""
    resumed: bool = False
    running: bool = False


@dataclass(frozen=True)
class ThreadRow:
    name: str
    state: str
    priority: int | None
    current: bool
    ident: int


@dataclass
class RtosSnapshot:
    ok: bool = False
    error: str = ""
    detail: str = ""
    plugin: str = ""
    threads: tuple[ThreadRow, ...] = ()


def rtos_label(plugin: str) -> str:
    return _RTOS_LABELS.get(plugin, plugin)


def decode_flags(cfsr: int, hfsr: int, dfsr: int) -> tuple[FaultFlag, ...]:
    """Return the asserted fault bits. Address-valid bits are not causes."""
    found: list[FaultFlag] = []
    mmfsr = cfsr & 0xFF
    bfsr = (cfsr >> 8) & 0xFF
    ufsr = (cfsr >> 16) & 0xFFFF
    for name, bit in _MMFSR:
        if mmfsr & (1 << bit):
            found.append(FaultFlag("MMFSR", name))
    for name, bit in _BFSR:
        if bfsr & (1 << bit):
            found.append(FaultFlag("BFSR", name))
    for name, bit in _UFSR:
        if ufsr & (1 << bit):
            found.append(FaultFlag("UFSR", name))
    for name, bit in _HFSR:
        if hfsr & (1 << bit):
            found.append(FaultFlag("HFSR", name))
    for name, bit in _DFSR:
        if dfsr & (1 << bit):
            found.append(FaultFlag("DFSR", name))
    return tuple(found)


def address_valid(cfsr: int) -> tuple[bool, bool]:
    """MMFAR and BFAR are valid only when the matching bit is set."""
    mmfsr = cfsr & 0xFF
    bfsr = (cfsr >> 8) & 0xFF
    return bool(mmfsr & (1 << 7)), bool(bfsr & (1 << 7))


def is_exc_return(value: int) -> bool:
    return (int(value) & 0xFF000000) == 0xFF000000


def frame_stack_name(lr: int) -> str:
    """EXC_RETURN bit 2 selects PSP; otherwise the frame sits on MSP."""
    if not is_exc_return(lr):
        return ""
    return "PSP" if (int(lr) & 0x4) else "MSP"


def frame_from_words(words: tuple[int, ...]) -> tuple[tuple[str, int], ...]:
    count = min(len(words), len(_FRAME_REGS))
    return tuple((_FRAME_REGS[i], int(words[i]) & 0xFFFFFFFF) for i in range(count))


def frame_pc(frame: tuple[tuple[str, int], ...]) -> int | None:
    for name, value in frame:
        if name == "pc":
            return value
    return None


def inspect_rtos(target: Any, symbol_provider: Any, plugins: dict[str, Any]) -> RtosSnapshot:
    """Try each RTOS plugin. The first one that finds its symbols wins."""
    if symbol_provider is None:
        return RtosSnapshot(error="no_elf")
    failures: list[str] = []
    for name, cls in plugins.items():
        try:
            provider = cls(target)
            if not provider.init(symbol_provider):
                continue
            provider.read_from_target = True
            # update_threads skips a second read while the core stays halted.
            if hasattr(provider, "_last_run_token"):
                provider._last_run_token = None
            if hasattr(provider, "update_threads"):
                provider.update_threads()
            threads = tuple(_thread_row(item) for item in provider.get_threads())
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        if not threads:
            return RtosSnapshot(ok=True, error="empty", plugin=str(name))
        return RtosSnapshot(ok=True, plugin=str(name), threads=threads)
    if failures:
        return RtosSnapshot(error="read_fail", detail="; ".join(failures))
    return RtosSnapshot(error="none")


def capture(
    session: Any,
    elf_path: str = "",
    *,
    halt: bool = False,
    lock: Any = None,
) -> tuple[FaultSnapshot, RtosSnapshot]:
    """Read fault state and RTOS threads.

    A running core is only halted when ``halt`` is true, and is resumed
    afterwards. Without it, only the fault status registers are read: core
    registers and RTOS lists are not stable while the core runs.
    """
    if session is None or getattr(session, "target", None) is None:
        return FaultSnapshot(error="not_connected"), RtosSnapshot(error="not_connected")
    held = lock if lock is not None else nullcontext()
    symbols = _ElfSymbols(elf_path)
    try:
        with held:
            return _capture_locked(session, symbols, halt)
    except Exception as exc:
        return _failed_pair(str(exc) or exc.__class__.__name__)
    finally:
        symbols.close()


def _failed_pair(text: str) -> tuple[FaultSnapshot, RtosSnapshot]:
    return (
        FaultSnapshot(error="read_fail", detail=text),
        RtosSnapshot(error="read_fail", detail=text),
    )


def _capture_locked(
    session: Any, symbols: _ElfSymbols, halt: bool
) -> tuple[FaultSnapshot, RtosSnapshot]:
    core = _core(session)
    resumed = False
    try:
        running = bool(core.is_running())
    except Exception:
        running = False
    try:
        if running and halt:
            core.halt()
            resumed = True
            running = False
        try:
            fault = _read_fault(core, symbols, resumed, running)
        except Exception as exc:
            fault = FaultSnapshot(error="read_fail", detail=str(exc) or exc.__class__.__name__)
        if running:
            return fault, RtosSnapshot(error="running")
        try:
            rtos = _read_rtos(session, symbols)
        except Exception as exc:
            rtos = RtosSnapshot(error="read_fail", detail=str(exc) or exc.__class__.__name__)
        return fault, rtos
    except Exception as exc:
        text = str(exc) or exc.__class__.__name__
        return _failed_pair(text)
    finally:
        if resumed:
            try:
                core.resume()
            except Exception:
                pass


def _core(session: Any) -> Any:
    target = session.target
    selected = getattr(target, "selected_core", None)
    return selected if selected is not None else target


def _read_fault(
    core: Any, symbols: _ElfSymbols, resumed: bool, running: bool
) -> FaultSnapshot:
    cfsr = _read32(core, CFSR)
    hfsr = _read32(core, HFSR)
    dfsr = _read32(core, DFSR)
    mmfar = _read32(core, MMFAR)
    bfar = _read32(core, BFAR)
    mm_ok, bus_ok = address_valid(cfsr)
    if running:
        # SCB registers are readable on a running core; CPU registers are not.
        return FaultSnapshot(
            ok=True,
            cfsr=cfsr,
            hfsr=hfsr,
            dfsr=dfsr,
            mmfar=mmfar,
            bfar=bfar,
            mmfar_valid=mm_ok,
            bfar_valid=bus_ok,
            flags=decode_flags(cfsr, hfsr, dfsr),
            running=True,
        )
    pc = _reg(core, "pc")
    lr = _reg(core, "lr")
    xpsr = _reg(core, "xpsr")
    msp = _reg(core, "msp")
    psp = _reg(core, "psp")
    stack = frame_stack_name(lr) if lr is not None else ""
    frame: tuple[tuple[str, int], ...] = ()
    if stack:
        base = psp if stack == "PSP" else msp
        if base is not None:
            words = _read_words(core, base, len(_FRAME_REGS))
            if words is not None:
                frame = frame_from_words(words)
    stacked_pc = frame_pc(frame)
    return FaultSnapshot(
        ok=True,
        cfsr=cfsr,
        hfsr=hfsr,
        dfsr=dfsr,
        mmfar=mmfar,
        bfar=bfar,
        mmfar_valid=mm_ok,
        bfar_valid=bus_ok,
        flags=decode_flags(cfsr, hfsr, dfsr),
        pc=pc,
        lr=lr,
        xpsr=xpsr,
        msp=msp,
        psp=psp,
        ipsr=(xpsr or 0) & 0x1FF,
        frame_stack=stack,
        frame=frame,
        pc_symbol=symbols.name_at(pc),
        frame_pc_symbol=symbols.name_at(stacked_pc),
        resumed=resumed,
    )


def _read_rtos(session: Any, symbols: _ElfSymbols) -> RtosSnapshot:
    if symbols.error:
        return RtosSnapshot(error=symbols.error, detail=symbols.detail)
    try:
        from pyocd.rtos import RTOS
    except Exception as exc:
        return RtosSnapshot(error="read_fail", detail=str(exc))
    return inspect_rtos(session.target, symbols.provider, RTOS)


def _reg(core: Any, name: str) -> int | None:
    try:
        return int(core.read_core_register(name)) & 0xFFFFFFFF
    except Exception:
        return None


def _read32(core: Any, addr: int) -> int:
    return int(core.read32(addr)) & 0xFFFFFFFF


def _read_words(core: Any, addr: int, count: int) -> tuple[int, ...] | None:
    size = count * 4
    try:
        raw = core.read_memory_block8(addr, size)
        data = bytes(raw)
        if len(data) >= size:
            return tuple(
                int.from_bytes(data[i : i + 4], "little") for i in range(0, size, 4)
            )
    except Exception:
        pass
    words: list[int] = []
    try:
        for index in range(count):
            words.append(_read32(core, addr + index * 4))
    except Exception:
        return None
    return tuple(words)


def _thread_row(thread: Any) -> ThreadRow:
    state = ""
    names = getattr(thread, "STATE_NAMES", None)
    raw_state = getattr(thread, "state", None)
    if isinstance(names, dict) and raw_state in names:
        state = str(names[raw_state])
    if not state:
        try:
            state = str(thread.description)
        except Exception:
            state = ""
    priority = getattr(thread, "priority", None)
    if not isinstance(priority, int):
        priority = None
    try:
        ident = int(thread.unique_id)
    except Exception:
        ident = 0
    try:
        current = bool(thread.is_current)
    except Exception:
        current = False
    try:
        name = str(thread.name)
    except Exception:
        name = ""
    return ThreadRow(
        name=name,
        state=state,
        priority=priority,
        current=current,
        ident=ident,
    )


class _ElfSymbols:
    """Symbol lookup from an ELF/AXF file. Missing files stay empty."""

    def __init__(self, path: str) -> None:
        self.provider: Any = None
        self.error = ""
        self.detail = ""
        self._elf: Any = None
        text = (path or "").strip()
        if not text:
            self.error = "no_elf"
            return
        file = Path(text)
        if file.suffix.lower() not in _ELF_SUFFIXES:
            self.error = "not_elf"
            return
        if not file.is_file():
            self.error = "no_elf"
            return
        try:
            from pyocd.debug.elf.elf import ELFBinaryFile
            from pyocd.debug.elf.symbols import ELFSymbolProvider

            self._elf = ELFBinaryFile(str(file))
            self.provider = ELFSymbolProvider(self._elf)
        except Exception as exc:
            self.error = "elf_fail"
            self.detail = str(exc) or exc.__class__.__name__
            self.close()

    def name_at(self, addr: int | None) -> str:
        if addr is None or self._elf is None:
            return ""
        try:
            symbol = self._elf.symbol_decoder.get_symbol_for_address(addr & 0xFFFFFFFE)
        except Exception:
            return ""
        if symbol is None:
            return ""
        return str(symbol.name or "")

    def close(self) -> None:
        elf = self._elf
        self._elf = None
        self.provider = None
        if elf is not None:
            try:
                elf.close()
            except Exception:
                pass
