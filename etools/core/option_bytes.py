"""STM32 option bytes: family detection, field model, read and program.

The target object only needs ``read32/write32/read16/write16`` (a pyOCD
target, or a register simulator in tests). Programming sequences follow the
reference manuals of each family; unknown register bits are preserved.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from etools.logger import get_logger

log = get_logger("option_bytes")

FLASH_KEY1, FLASH_KEY2 = 0x45670123, 0xCDEF89AB
OPT_KEY1, OPT_KEY2 = 0x08192A3B, 0x4C5D6E7F
F1_OPT_KEY1, F1_OPT_KEY2 = FLASH_KEY1, FLASH_KEY2

IDCODE_ADDRS = (0xE0042000, 0x40015800, 0x5C001000)
RDP_LEVEL2 = 0xCC
OPT_TIMEOUT_S = 5.0
MASS_ERASE_TIMEOUT_S = 120.0


class OptionBytesError(RuntimeError):
    """Option byte access failed or a request was refused."""


# -- field model ----------------------------------------------------------

_RST = ((1, "ob.v.no_reset"), (0, "ob.v.reset"))
_WDG = ((1, "ob.v.software"), (0, "ob.v.hardware"))
_FRZ = ((1, "ob.v.running"), (0, "ob.v.frozen"))
_BIT = ((1, "1"), (0, "0"))
_ON = ((0, "ob.v.off"), (1, "ob.v.on"))
_PARITY = ((1, "ob.v.off"), (0, "ob.v.on"))
_SRAM_RST = ((1, "ob.v.keep"), (0, "ob.v.erase_on_reset"))


@dataclass(frozen=True)
class ObField:
    key: str
    reg: str
    shift: int
    width: int = 1
    kind: str = "enum"  # enum | rdp | hex
    choices: tuple[tuple[int, str], ...] = ()
    default: int | None = None
    danger: bool = False
    readonly: bool = False

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.shift

    @property
    def max_value(self) -> int:
        return (1 << self.width) - 1

    def get(self, regs: dict[str, int]) -> int:
        return (regs[self.reg] >> self.shift) & self.max_value

    def put(self, regs: dict[str, int], value: int) -> None:
        if not 0 <= int(value) <= self.max_value:
            raise OptionBytesError(f"{self.key}: value {value} out of range")
        regs[self.reg] = (regs[self.reg] & ~self.mask) | (int(value) << self.shift)


def _rdp(reg: str, shift: int, l0: int, l1: int) -> ObField:
    return ObField(
        "RDP", reg, shift, 8, "rdp", ((l0, "ob.v.rdp0"), (l1, "ob.v.rdp1")), default=l0
    )


def _bor4(reg: str, shift: int) -> ObField:
    # L4 / G4: VBOR0..VBOR4 thresholds.
    return ObField(
        "BOR_LEV",
        reg,
        shift,
        3,
        choices=(
            (0, "1.7 V"),
            (1, "2.0 V"),
            (2, "2.2 V"),
            (3, "2.5 V"),
            (4, "2.8 V"),
        ),
        default=0,
    )


def _wdg_fields(reg: str, base: int) -> tuple[ObField, ...]:
    return (
        ObField("IWDG_SW", reg, base, choices=_WDG, default=1),
        ObField("IWDG_STOP", reg, base + 1, choices=_FRZ, default=1),
        ObField("IWDG_STDBY", reg, base + 2, choices=_FRZ, default=1),
        ObField("WWDG_SW", reg, base + 3, choices=_WDG, default=1),
    )


def _wrp_area(reg: str, name: str, width: int) -> tuple[ObField, ...]:
    return (
        ObField(f"{name}_STRT", reg, 0, width, "hex"),
        ObField(f"{name}_END", reg, 16, width, "hex"),
    )


# -- target helpers -------------------------------------------------------


def _wait(cond: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    delay = 0.002
    while not cond():
        if time.monotonic() > deadline:
            raise OptionBytesError(f"Timeout waiting for {what}")
        time.sleep(delay)
        delay = min(0.05, delay * 2)


def _set_bits(t: Any, addr: int, bits: int) -> None:
    t.write32(addr, t.read32(addr) | bits)


def _clear_bits(t: Any, addr: int, bits: int) -> None:
    t.write32(addr, t.read32(addr) & ~bits & 0xFFFFFFFF)


# -- families -------------------------------------------------------------


@dataclass
class ObFamily:
    name: str
    title: str
    dev_ids: tuple[int, ...]
    fields: tuple[ObField, ...] = ()
    rdp_l0: int = 0xAA
    rdp_l1: int = 0xBB
    has_level2: bool = True
    # How new values take effect: "none" (immediately), "reset" (system reset)
    # or "obl" (OBL_LAUNCH reset; the debug session drops and must reconnect).
    reload: str = "reset"
    registers: tuple[str, ...] = field(default_factory=tuple)

    def get_field(self, key: str) -> ObField:
        for f in self.fields:
            if f.key == key:
                return f
        raise KeyError(key)

    def rdp_level(self, value: int) -> int:
        if value == self.rdp_l0:
            return 0
        if self.has_level2 and value == RDP_LEVEL2:
            return 2
        return 1

    def read(self, t: Any) -> dict[str, int]:
        raise NotImplementedError

    def program(self, t: Any, regs: dict[str, int], timeout: float) -> None:
        raise NotImplementedError


@dataclass
class F1StyleFamily(ObFamily):
    """F0 / F1 / F3: option bytes are halfword pairs at 0x1FFFF800."""

    ob_addr: int = 0x1FFFF800
    base: int = 0x40022000
    obl_launch: bool = False

    def __post_init__(self) -> None:
        self.registers = ("RDP", "USER", "DATA0", "DATA1", "WRP0", "WRP1", "WRP2", "WRP3")
        self.reload = "obl" if self.obl_launch else "reset"

    def read(self, t: Any) -> dict[str, int]:
        return {
            name: t.read16(self.ob_addr + 2 * i) & 0xFF for i, name in enumerate(self.registers)
        }

    def program(self, t: Any, regs: dict[str, int], timeout: float) -> None:
        b = self.base
        keyr, optkeyr, sr, cr = b + 0x04, b + 0x08, b + 0x0C, b + 0x10
        bsy, pgerr, wrprterr, eop = 1 << 0, 1 << 2, 1 << 4, 1 << 5
        optpg, opter, strt, lock, optwre, obl = 1 << 4, 1 << 5, 1 << 6, 1 << 7, 1 << 9, 1 << 13

        def idle() -> bool:
            return not t.read32(sr) & bsy

        _wait(idle, OPT_TIMEOUT_S, "flash idle")
        if t.read32(cr) & lock:
            t.write32(keyr, FLASH_KEY1)
            t.write32(keyr, FLASH_KEY2)
        t.write32(optkeyr, F1_OPT_KEY1)
        t.write32(optkeyr, F1_OPT_KEY2)
        if not t.read32(cr) & optwre:
            raise OptionBytesError("Option byte unlock failed (OPTWRE not set)")
        t.write32(sr, pgerr | wrprterr | eop)

        _set_bits(t, cr, opter)
        _set_bits(t, cr, strt)
        _wait(idle, timeout, "option byte erase")
        _clear_bits(t, cr, opter | strt)

        _set_bits(t, cr, optpg)
        # RDP first so an interrupted write never leaves the chip locked.
        for i, name in enumerate(self.registers):
            value = regs[name] & 0xFF
            t.write16(self.ob_addr + 2 * i, value | ((~value & 0xFF) << 8))
            _wait(idle, OPT_TIMEOUT_S, f"programming {name}")
            status = t.read32(sr)
            if status & (pgerr | wrprterr):
                _clear_bits(t, cr, optpg)
                raise OptionBytesError(f"Programming {name} failed (SR=0x{status:08X})")
        _clear_bits(t, cr, optpg)
        if self.obl_launch:
            try:
                _set_bits(t, cr, obl)
            except Exception:
                log.debug("OBL_LAUNCH dropped the link (expected)", exc_info=True)
        else:
            _set_bits(t, cr, lock)


@dataclass
class F4Family(ObFamily):
    base: int = 0x40023C00
    dual: bool = False

    def __post_init__(self) -> None:
        self.registers = ("OPTCR", "OPTCR1") if self.dual else ("OPTCR",)

    def read(self, t: Any) -> dict[str, int]:
        regs = {"OPTCR": t.read32(self.base + 0x14) & ~0x3 & 0xFFFFFFFF}
        if self.dual:
            regs["OPTCR1"] = t.read32(self.base + 0x18)
        return regs

    def program(self, t: Any, regs: dict[str, int], timeout: float) -> None:
        optkeyr, sr, optcr, optcr1 = (
            self.base + 0x08,
            self.base + 0x0C,
            self.base + 0x14,
            self.base + 0x18,
        )
        bsy, errors = 1 << 16, 0xF2

        def idle() -> bool:
            return not t.read32(sr) & bsy

        _wait(idle, OPT_TIMEOUT_S, "flash idle")
        if t.read32(optcr) & 1:
            t.write32(optkeyr, OPT_KEY1)
            t.write32(optkeyr, OPT_KEY2)
        if t.read32(optcr) & 1:
            raise OptionBytesError("Option byte unlock failed (OPTLOCK still set)")
        t.write32(sr, errors)
        if self.dual:
            t.write32(optcr1, regs["OPTCR1"])
        value = regs["OPTCR"] & ~0x3 & 0xFFFFFFFF
        t.write32(optcr, value)
        t.write32(optcr, value | 0x2)
        _wait(idle, timeout, "option byte programming")
        status = t.read32(sr)
        _set_bits(t, optcr, 0x1)
        if status & errors:
            raise OptionBytesError(f"Option byte programming failed (SR=0x{status:08X})")


@dataclass
class OptrFamily(ObFamily):
    """L4 / G4 / G0: FLASH_OPTR + WRP area registers, OBL_LAUNCH to reload."""

    base: int = 0x40022000

    def __post_init__(self) -> None:
        self.registers = ("OPTR", "WRP1AR", "WRP1BR")
        self.reload = "obl"

    def _addr(self, reg: str) -> int:
        return self.base + {"OPTR": 0x20, "WRP1AR": 0x2C, "WRP1BR": 0x30}[reg]

    def read(self, t: Any) -> dict[str, int]:
        return {reg: t.read32(self._addr(reg)) for reg in self.registers}

    def program(self, t: Any, regs: dict[str, int], timeout: float) -> None:
        b = self.base
        keyr, optkeyr, sr, cr = b + 0x08, b + 0x0C, b + 0x10, b + 0x14
        bsy, errors = 1 << 16, 0xC3FA
        optstrt, obl, optlock, lock = 1 << 17, 1 << 27, 1 << 30, 1 << 31

        def idle() -> bool:
            return not t.read32(sr) & bsy

        _wait(idle, OPT_TIMEOUT_S, "flash idle")
        if t.read32(cr) & lock:
            t.write32(keyr, FLASH_KEY1)
            t.write32(keyr, FLASH_KEY2)
        if t.read32(cr) & optlock:
            t.write32(optkeyr, OPT_KEY1)
            t.write32(optkeyr, OPT_KEY2)
        if t.read32(cr) & (lock | optlock):
            raise OptionBytesError("Option byte unlock failed")
        t.write32(sr, errors | 1)
        for reg in self.registers:
            t.write32(self._addr(reg), regs[reg])
        _set_bits(t, cr, optstrt)
        _wait(idle, timeout, "option byte programming")
        status = t.read32(sr)
        if status & errors:
            _set_bits(t, cr, lock)
            raise OptionBytesError(f"Option byte programming failed (SR=0x{status:08X})")
        try:
            _set_bits(t, cr, obl)
        except Exception:
            log.debug("OBL_LAUNCH dropped the link (expected)", exc_info=True)


@dataclass
class H7Family(ObFamily):
    """H74x/75x and H72x/73x: CUR/PRG register pairs, effective immediately."""

    base: int = 0x52002000
    dual_bank: bool = True

    # register -> (CUR offset, PRG offset); None PRG means read-only here.
    _layout: dict[str, tuple[int, int | None]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        layout: dict[str, tuple[int, int | None]] = {
            "OPTSR": (0x1C, 0x20),
            "BOOT": (0x40, 0x44),
            "WPSN1": (0x38, 0x3C),
            "PRAR1": (0x28, None),
            "SCAR1": (0x30, None),
        }
        if self.dual_bank:
            layout["WPSN2"] = (0x138, 0x13C)
        self._layout = layout
        self.registers = tuple(layout)
        self.reload = "none"

    def read(self, t: Any) -> dict[str, int]:
        return {reg: t.read32(self.base + cur) for reg, (cur, _prg) in self._layout.items()}

    def program(self, t: Any, regs: dict[str, int], timeout: float) -> None:
        optkeyr, optcr = self.base + 0x08, self.base + 0x18
        optsr_cur, optccr = self.base + 0x1C, self.base + 0x24
        optlock, optstart, busy, changeerr = 1 << 0, 1 << 1, 1 << 0, 1 << 30

        if t.read32(optcr) & optlock:
            t.write32(optkeyr, OPT_KEY1)
            t.write32(optkeyr, OPT_KEY2)
        if t.read32(optcr) & optlock:
            raise OptionBytesError("Option byte unlock failed (OPTLOCK still set)")
        t.write32(optccr, changeerr)
        for reg, (_cur, prg) in self._layout.items():
            if prg is None:
                continue
            value = regs[reg]
            if reg == "OPTSR":
                value &= ~(busy | changeerr) & 0xFFFFFFFF
            t.write32(self.base + prg, value)
        _set_bits(t, optcr, optstart)
        _wait(lambda: not t.read32(optsr_cur) & busy, timeout, "option byte programming")
        status = t.read32(optsr_cur)
        if status & changeerr:
            t.write32(optccr, changeerr)
            _set_bits(t, optcr, optlock)
            raise OptionBytesError(f"Option byte change error (OPTSR=0x{status:08X})")
        _set_bits(t, optcr, optlock)


def _f1_user(fields: tuple[tuple[str, int, tuple], ...]) -> tuple[ObField, ...]:
    return tuple(ObField(key, "USER", bit, choices=ch, default=1) for key, bit, ch in fields)


def _f1_common() -> tuple[ObField, ...]:
    return (
        ObField("DATA0", "DATA0", 0, 8, "hex", default=0xFF),
        ObField("DATA1", "DATA1", 0, 8, "hex", default=0xFF),
        *(ObField(f"WRP{i}", f"WRP{i}", 0, 8, "hex", default=0xFF) for i in range(4)),
    )


F1 = F1StyleFamily(
    "f1",
    "STM32F1",
    (0x410, 0x412, 0x414, 0x418, 0x420, 0x428, 0x430),
    fields=(
        _rdp("RDP", 0, 0xA5, 0x00),
        *_f1_user(
            (("WDG_SW", 0, _WDG), ("nRST_STOP", 1, _RST), ("nRST_STDBY", 2, _RST))
        ),
        *_f1_common(),
    ),
    rdp_l0=0xA5,
    rdp_l1=0x00,
    has_level2=False,
)

F0 = F1StyleFamily(
    "f0",
    "STM32F0",
    (0x440, 0x442, 0x444, 0x445, 0x448),
    fields=(
        _rdp("RDP", 0, 0xAA, 0xBB),
        *_f1_user(
            (
                ("WDG_SW", 0, _WDG),
                ("nRST_STOP", 1, _RST),
                ("nRST_STDBY", 2, _RST),
                ("nBOOT0", 3, _BIT),
                ("nBOOT1", 4, _BIT),
                ("VDDA_MONITOR", 5, _ON),
                ("RAM_PARITY_CHECK", 6, _PARITY),
                ("BOOT_SEL", 7, _BIT),
            )
        ),
        *_f1_common(),
    ),
    obl_launch=True,
)

F3 = F1StyleFamily(
    "f3",
    "STM32F3",
    (0x422, 0x432, 0x438, 0x439, 0x446),
    fields=(
        _rdp("RDP", 0, 0xAA, 0xBB),
        *_f1_user(
            (
                ("WDG_SW", 0, _WDG),
                ("nRST_STOP", 1, _RST),
                ("nRST_STDBY", 2, _RST),
                ("nBOOT1", 4, _BIT),
                ("VDDA_MONITOR", 5, _ON),
                ("SRAM_PE", 6, _PARITY),
            )
        ),
        *_f1_common(),
    ),
    obl_launch=True,
)

_F4_BOR = ObField(
    "BOR_LEV",
    "OPTCR",
    2,
    2,
    choices=((3, "ob.v.off"), (2, "2.2 V"), (1, "2.5 V"), (0, "2.8 V")),
    default=3,
)


def _f4_fields(extra: tuple[ObField, ...] = ()) -> tuple[ObField, ...]:
    return (
        _rdp("OPTCR", 8, 0xAA, 0xBB),
        _F4_BOR,
        ObField("WDG_SW", "OPTCR", 5, choices=_WDG, default=1),
        ObField("nRST_STOP", "OPTCR", 6, choices=_RST, default=1),
        ObField("nRST_STDBY", "OPTCR", 7, choices=_RST, default=1),
        ObField("nWRP", "OPTCR", 16, 12, "hex", default=0xFFF),
        *extra,
    )


F4 = F4Family(
    "f4",
    "STM32F4",
    (0x413, 0x423, 0x433, 0x431, 0x458, 0x421, 0x441, 0x463),
    fields=_f4_fields(),
)

F4_DUAL = F4Family(
    "f4d",
    "STM32F42x/43x/469",
    (0x419, 0x434),
    fields=_f4_fields(
        (
            ObField("BFB2", "OPTCR", 4, choices=_ON, default=0, danger=True),
            ObField("DB1M", "OPTCR", 30, choices=_ON, danger=True),
            ObField("nWRP2", "OPTCR1", 16, 12, "hex", default=0xFFF),
        )
    ),
    dual=True,
)

L4 = OptrFamily(
    "l4",
    "STM32L4",
    (0x415, 0x435, 0x461, 0x462, 0x464, 0x470, 0x471),
    fields=(
        _rdp("OPTR", 0, 0xAA, 0xBB),
        _bor4("OPTR", 8),
        ObField("nRST_STOP", "OPTR", 12, choices=_RST, default=1),
        ObField("nRST_STDBY", "OPTR", 13, choices=_RST, default=1),
        ObField("nRST_SHDW", "OPTR", 14, choices=_RST, default=1),
        *_wdg_fields("OPTR", 16),
        ObField("BFB2", "OPTR", 20, choices=_ON, default=0, danger=True),
        ObField("DUALBANK", "OPTR", 21, choices=_ON, danger=True),
        ObField("nBOOT1", "OPTR", 23, choices=_BIT, default=1),
        ObField("SRAM2_PE", "OPTR", 24, choices=_PARITY, default=1),
        ObField("SRAM2_RST", "OPTR", 25, choices=_SRAM_RST, default=1),
        ObField(
            "nSWBOOT0",
            "OPTR",
            26,
            choices=((1, "ob.v.boot0_pin"), (0, "ob.v.boot0_bit")),
            default=1,
            danger=True,
        ),
        ObField("nBOOT0", "OPTR", 27, choices=_BIT, default=1, danger=True),
        *_wrp_area("WRP1AR", "WRP1A", 8),
        *_wrp_area("WRP1BR", "WRP1B", 8),
    ),
)

_NRST_MODE = ((3, "ob.v.nrst_bidir"), (1, "ob.v.nrst_input"), (2, "ob.v.nrst_gpio"))

G4 = OptrFamily(
    "g4",
    "STM32G4",
    (0x468, 0x469, 0x479),
    fields=(
        _rdp("OPTR", 0, 0xAA, 0xBB),
        _bor4("OPTR", 8),
        ObField("nRST_STOP", "OPTR", 12, choices=_RST, default=1),
        ObField("nRST_STDBY", "OPTR", 13, choices=_RST, default=1),
        ObField("nRST_SHDW", "OPTR", 14, choices=_RST, default=1),
        *_wdg_fields("OPTR", 16),
        ObField("BFB2", "OPTR", 20, choices=_ON, default=0, danger=True),
        ObField("DBANK", "OPTR", 22, choices=_ON, danger=True),
        ObField("nBOOT1", "OPTR", 23, choices=_BIT, default=1),
        ObField("SRAM_PE", "OPTR", 24, choices=_PARITY, default=1),
        ObField("CCMSRAM_RST", "OPTR", 25, choices=_SRAM_RST, default=1),
        ObField(
            "nSWBOOT0",
            "OPTR",
            26,
            choices=((1, "ob.v.boot0_pin"), (0, "ob.v.boot0_bit")),
            default=1,
            danger=True,
        ),
        ObField("nBOOT0", "OPTR", 27, choices=_BIT, default=1, danger=True),
        ObField("NRST_MODE", "OPTR", 28, 2, choices=_NRST_MODE, default=3, danger=True),
        ObField("IRHEN", "OPTR", 30, choices=_ON, default=1),
        *_wrp_area("WRP1AR", "WRP1A", 7),
        *_wrp_area("WRP1BR", "WRP1B", 7),
    ),
)

G0 = OptrFamily(
    "g0",
    "STM32G0",
    (0x460, 0x466, 0x467, 0x456),
    fields=(
        _rdp("OPTR", 0, 0xAA, 0xBB),
        ObField("BOR_EN", "OPTR", 8, choices=_ON, default=0),
        ObField("BORF_LEV", "OPTR", 9, 2, "hex", default=0),
        ObField("BORR_LEV", "OPTR", 11, 2, "hex", default=0),
        ObField("nRST_STOP", "OPTR", 13, choices=_RST, default=1),
        ObField("nRST_STDBY", "OPTR", 14, choices=_RST, default=1),
        ObField("nRST_SHDW", "OPTR", 15, choices=_RST, default=1),
        *_wdg_fields("OPTR", 16),
        ObField("RAM_PARITY_CHECK", "OPTR", 22, choices=_PARITY, default=1),
        ObField(
            "nBOOT_SEL",
            "OPTR",
            24,
            choices=((1, "ob.v.boot0_bit"), (0, "ob.v.boot0_pin")),
            default=1,
            danger=True,
        ),
        ObField("nBOOT1", "OPTR", 25, choices=_BIT, default=1),
        ObField("nBOOT0", "OPTR", 26, choices=_BIT, default=1, danger=True),
        ObField("NRST_MODE", "OPTR", 27, 2, choices=_NRST_MODE, default=3, danger=True),
        ObField("IRHEN", "OPTR", 29, choices=_ON, default=1),
        *_wrp_area("WRP1AR", "WRP1A", 7),
        *_wrp_area("WRP1BR", "WRP1B", 7),
    ),
)


def _h7_fields(dual_bank: bool) -> tuple[ObField, ...]:
    fields: list[ObField] = [
        _rdp("OPTSR", 8, 0xAA, 0xBB),
        ObField(
            "BOR_LEV",
            "OPTSR",
            2,
            2,
            choices=((0, "ob.v.off"), (1, "2.1 V"), (2, "2.4 V"), (3, "2.7 V")),
            default=0,
        ),
        ObField("IWDG1_SW", "OPTSR", 4, choices=_WDG, default=1),
        ObField("NRST_STOP_D1", "OPTSR", 6, choices=_RST, default=1),
        ObField("NRST_STBY_D1", "OPTSR", 7, choices=_RST, default=1),
        ObField("FZ_IWDG_STOP", "OPTSR", 17, choices=_FRZ, default=1),
        ObField("FZ_IWDG_SDBY", "OPTSR", 18, choices=_FRZ, default=1),
        ObField("ST_RAM_SIZE", "OPTSR", 19, 2, "hex", readonly=True),
        ObField("SECURITY", "OPTSR", 21, choices=_ON, readonly=True),
        ObField("IO_HSLV", "OPTSR", 29, choices=_ON, default=0, danger=True),
        ObField("BOOT_ADD0", "BOOT", 0, 16, "hex", default=0x0800, danger=True),
        ObField("BOOT_ADD1", "BOOT", 16, 16, "hex", default=0x1FF0, danger=True),
        ObField("nWRP_BANK1", "WPSN1", 0, 8, "hex", default=0xFF),
    ]
    if dual_bank:
        fields.insert(
            10, ObField("SWAP_BANK_OPT", "OPTSR", 31, choices=_ON, default=0, danger=True)
        )
        fields.append(ObField("nWRP_BANK2", "WPSN2", 0, 8, "hex", default=0xFF))
    return tuple(fields)


H7 = H7Family("h7", "STM32H74x/75x", (0x450,), fields=_h7_fields(True), dual_bank=True)
H7_SINGLE = H7Family(
    "h7s", "STM32H72x/73x", (0x483,), fields=_h7_fields(False), dual_bank=False
)

FAMILIES: tuple[ObFamily, ...] = (F0, F1, F3, F4, F4_DUAL, G0, G4, L4, H7, H7_SINGLE)


def family_for_dev_id(dev_id: int) -> ObFamily | None:
    for fam in FAMILIES:
        if dev_id in fam.dev_ids:
            return fam
    return None


def read_dev_id(t: Any) -> int | None:
    """Return the first known STM32 DEV_ID from the DBGMCU IDCODE candidates."""
    for addr in IDCODE_ADDRS:
        try:
            dev = t.read32(addr) & 0xFFF
        except Exception:
            continue
        if family_for_dev_id(dev) is not None:
            return dev
    return None


# -- high level -----------------------------------------------------------


@dataclass
class ObChange:
    key: str
    old: int
    new: int


@dataclass
class ObWriteOutcome:
    changes: list[ObChange]
    rdp_action: str  # none | protect | unprotect
    reload: str
    regs: dict[str, int]


@dataclass
class ObSnapshot:
    """Thread-safe copy of the option bytes for the UI."""

    family: ObFamily
    dev_id: int
    regs: dict[str, int]
    values: dict[str, int]
    rdp_level: int
    factory: dict[str, int]

    @classmethod
    def capture(cls, ob: OptionBytes) -> ObSnapshot:
        regs = ob.read()
        return cls(
            family=ob.family,
            dev_id=ob.dev_id,
            regs=regs,
            values=ob.values(regs),
            rdp_level=ob.rdp_level(regs),
            factory=ob.factory_values(),
        )


class OptionBytes:
    """Option-byte accessor bound to one live target."""

    def __init__(self, target: Any, family: ObFamily, dev_id: int = 0) -> None:
        self.target = target
        self.family = family
        self.dev_id = dev_id

    @classmethod
    def detect(cls, target: Any) -> OptionBytes:
        dev = read_dev_id(target)
        if dev is None:
            raise OptionBytesError("Unsupported device: no known STM32 DEV_ID found")
        fam = family_for_dev_id(dev)
        assert fam is not None
        return cls(target, fam, dev)

    def read(self) -> dict[str, int]:
        return self.family.read(self.target)

    def values(self, regs: dict[str, int] | None = None) -> dict[str, int]:
        regs = regs if regs is not None else self.read()
        return {f.key: f.get(regs) for f in self.family.fields}

    def rdp_level(self, regs: dict[str, int] | None = None) -> int:
        return self.family.rdp_level(self.values(regs)["RDP"])

    def plan(
        self, current: dict[str, int], values: dict[str, int], *, allow_level2: bool = False
    ) -> ObWriteOutcome:
        """Validate the requested field values and compute the new registers."""
        regs = dict(current)
        changes: list[ObChange] = []
        for key, value in values.items():
            f = self.family.get_field(key)
            old = f.get(current)
            if int(value) == old:
                continue
            if f.readonly:
                raise OptionBytesError(f"{key} is read-only")
            f.put(regs, int(value))
            changes.append(ObChange(key, old, int(value)))
        old_level = self.family.rdp_level(self.family.get_field("RDP").get(current))
        new_level = self.family.rdp_level(self.family.get_field("RDP").get(regs))
        if new_level == 2 and old_level != 2 and not allow_level2:
            raise OptionBytesError("RDP Level 2 is permanent and refused")
        if old_level == 2:
            raise OptionBytesError("Device is at RDP Level 2; option bytes are frozen")
        action = "none"
        if new_level > old_level:
            action = "protect"
        elif new_level < old_level:
            action = "unprotect"
        return ObWriteOutcome(changes, action, self.family.reload, regs)

    def write(
        self, values: dict[str, int], *, allow_level2: bool = False
    ) -> ObWriteOutcome:
        current = self.read()
        outcome = self.plan(current, values, allow_level2=allow_level2)
        if not outcome.changes:
            return outcome
        halt = getattr(self.target, "halt", None)
        if callable(halt):
            try:
                halt()
            except Exception:
                log.debug("halt before option byte write failed", exc_info=True)
        timeout = MASS_ERASE_TIMEOUT_S if outcome.rdp_action == "unprotect" else OPT_TIMEOUT_S
        log.info(
            "Option bytes %s: %s",
            self.family.title,
            ", ".join(f"{c.key} {c.old:#x}->{c.new:#x}" for c in outcome.changes),
        )
        self.family.program(self.target, outcome.regs, timeout)
        return outcome

    def factory_values(self) -> dict[str, int]:
        return {
            f.key: f.default
            for f in self.family.fields
            if f.default is not None and not f.readonly
        }

    def snapshot(self) -> ObSnapshot:
        return ObSnapshot.capture(self)

    def set_rdp(self, level: int) -> ObWriteOutcome:
        if level not in (0, 1):
            raise OptionBytesError("Only RDP Level 0 and Level 1 are supported")
        value = self.family.rdp_l0 if level == 0 else self.family.rdp_l1
        return self.write({"RDP": value})
