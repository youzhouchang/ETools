"""Option byte model and programming sequences against register simulators."""

from __future__ import annotations

import pytest

from etools.core import option_bytes as obm
from etools.core.option_bytes import (
    F0,
    F1,
    F4,
    G0,
    H7,
    L4,
    OptionBytes,
    OptionBytesError,
    family_for_dev_id,
    read_dev_id,
)


class _Sim:
    """Minimal bus: 32-bit registers plus optional halfword memory."""

    def __init__(self, idcode_addr: int, dev_id: int) -> None:
        self.regs: dict[int, int] = {idcode_addr: 0x10000000 | dev_id}
        self.mem16: dict[int, int] = {}
        self.halted = False

    def halt(self) -> None:
        self.halted = True

    def read32(self, addr: int) -> int:
        if addr not in self.regs:
            raise OSError(f"bus fault @ {addr:#x}")
        return self.regs[addr]

    def write32(self, addr: int, value: int) -> None:
        self.regs[addr] = value & 0xFFFFFFFF

    def read16(self, addr: int) -> int:
        return self.mem16[addr]

    def write16(self, addr: int, value: int) -> None:
        self.mem16[addr] = value & 0xFFFF


class H7Sim(_Sim):
    B = 0x52002000

    def __init__(self, optsr: int = 0x0BC6AAF0) -> None:
        super().__init__(0x5C001000, 0x450)
        b = self.B
        self.regs.update(
            {
                b + 0x08: 0,
                b + 0x18: 0x1,  # OPTCR locked
                b + 0x1C: optsr,
                b + 0x20: optsr,
                b + 0x24: 0,
                b + 0x28: 0xFF,
                b + 0x30: 0xFF,
                b + 0x38: 0xFF,
                b + 0x3C: 0xFF,
                b + 0x40: 0x1FF00800,
                b + 0x44: 0x1FF00800,
                b + 0x138: 0xFF,
                b + 0x13C: 0xFF,
            }
        )
        self._keys: list[int] = []
        self.mass_erased = False
        self.commits = 0

    def write32(self, addr: int, value: int) -> None:
        b = self.B
        if addr == b + 0x08:
            self._keys.append(value)
            if self._keys[-2:] == [obm.OPT_KEY1, obm.OPT_KEY2]:
                self.regs[b + 0x18] &= ~1
            return
        locked = self.regs[b + 0x18] & 1
        if addr in (b + 0x20, b + 0x44, b + 0x3C, b + 0x13C):
            if not locked:
                self.regs[addr] = value
            return
        if addr == b + 0x18:
            if locked and not value & 1:
                return
            if value & 0x2 and not locked:
                old_rdp = (self.regs[b + 0x1C] >> 8) & 0xFF
                new_rdp = (self.regs[b + 0x20] >> 8) & 0xFF
                if old_rdp != 0xAA and new_rdp == 0xAA:
                    self.mass_erased = True
                for cur, prg in ((0x1C, 0x20), (0x40, 0x44), (0x38, 0x3C), (0x138, 0x13C)):
                    self.regs[b + cur] = self.regs[b + prg]
                self.commits += 1
                value &= ~0x2
            self.regs[addr] = value
            return
        super().write32(addr, value)


class F1Sim(_Sim):
    """FPEC + option byte halfwords (F0/F1/F3 style)."""

    B = 0x40022000
    OB = 0x1FFFF800

    def __init__(self, dev_id: int, rdp: int, obl_raises: bool = False) -> None:
        idaddr = 0xE0042000 if dev_id in F1.dev_ids else 0x40015800
        super().__init__(idaddr, dev_id)
        b = self.B
        self.regs.update({b + 0x04: 0, b + 0x08: 0, b + 0x0C: 0, b + 0x10: 0x80})
        values = [rdp, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
        for i, v in enumerate(values):
            self.mem16[self.OB + 2 * i] = v | ((~v & 0xFF) << 8)
        self._keys: list[int] = []
        self._optkeys: list[int] = []
        self.obl_raises = obl_raises
        self.obl = False
        self.erases = 0

    def write32(self, addr: int, value: int) -> None:
        b = self.B
        cr = b + 0x10
        if addr == b + 0x04:
            self._keys.append(value)
            if self._keys[-2:] == [obm.FLASH_KEY1, obm.FLASH_KEY2]:
                self.regs[cr] &= ~0x80
            return
        if addr == b + 0x08:
            self._optkeys.append(value)
            if self._optkeys[-2:] == [obm.FLASH_KEY1, obm.FLASH_KEY2] and not self.regs[cr] & 0x80:
                self.regs[cr] |= 1 << 9
            return
        if addr == b + 0x0C:
            self.regs[addr] &= ~value
            return
        if addr == cr:
            if self.regs[cr] & 0x80:
                return
            if value & (1 << 5) and value & (1 << 6):
                for i in range(8):
                    self.mem16[self.OB + 2 * i] = 0xFFFF
                self.erases += 1
                value &= ~(1 << 6)
            if value & (1 << 13):
                self.obl = True
                if self.obl_raises:
                    raise OSError("link lost")
            if value & 0x80:
                value &= ~(1 << 9)
            self.regs[cr] = value
            return
        super().write32(addr, value)

    def write16(self, addr: int, value: int) -> None:
        cr = self.regs[self.B + 0x10]
        if not cr & (1 << 4) or not cr & (1 << 9):
            raise AssertionError("option byte write without OPTPG/OPTWRE")
        if self.mem16[addr] != 0xFFFF:
            self.regs[self.B + 0x0C] |= 1 << 2
            return
        self.mem16[addr] = value

    def ob(self, i: int) -> int:
        return self.mem16[self.OB + 2 * i]


class F4Sim(_Sim):
    B = 0x40023C00

    def __init__(self) -> None:
        super().__init__(0xE0042000, 0x413)
        self.regs.update({self.B + 0x08: 0, self.B + 0x0C: 0, self.B + 0x14: 0x0FFFAAED})
        self._keys: list[int] = []
        self.committed: int | None = None

    def write32(self, addr: int, value: int) -> None:
        b = self.B
        if addr == b + 0x08:
            self._keys.append(value)
            if self._keys[-2:] == [obm.OPT_KEY1, obm.OPT_KEY2]:
                self.regs[b + 0x14] &= ~1
            return
        if addr == b + 0x0C:
            self.regs[addr] &= ~value
            return
        if addr == b + 0x14:
            if self.regs[addr] & 1:
                return
            if value & 2:
                self.committed = value & ~3
                value &= ~2
            self.regs[addr] = value
            return
        super().write32(addr, value)


class OptrSim(_Sim):
    B = 0x40022000

    def __init__(self, dev_id: int, optr: int, idaddr: int = 0xE0042000) -> None:
        super().__init__(idaddr, dev_id)
        b = self.B
        self.regs.update(
            {
                b + 0x08: 0,
                b + 0x0C: 0,
                b + 0x10: 0,
                b + 0x14: 0xC0000000,
                b + 0x20: optr,
                b + 0x2C: 0xFF00FFFF,
                b + 0x30: 0xFF00FFFF,
            }
        )
        self._keys: list[int] = []
        self._optkeys: list[int] = []
        self.loaded_optr = optr
        self.obl = False

    def write32(self, addr: int, value: int) -> None:
        b = self.B
        cr = b + 0x14
        if addr == b + 0x08:
            self._keys.append(value)
            if self._keys[-2:] == [obm.FLASH_KEY1, obm.FLASH_KEY2]:
                self.regs[cr] &= ~(1 << 31)
            return
        if addr == b + 0x0C:
            self._optkeys.append(value)
            if self._optkeys[-2:] == [obm.OPT_KEY1, obm.OPT_KEY2] and not self.regs[cr] >> 31:
                self.regs[cr] &= ~(1 << 30)
            return
        if addr == b + 0x10:
            self.regs[addr] &= ~value
            return
        if addr in (b + 0x20, b + 0x2C, b + 0x30):
            if not self.regs[cr] & (1 << 30):
                self.regs[addr] = value
            return
        if addr == cr:
            if value & (1 << 27):
                self.obl = True
                self.loaded_optr = self.regs[b + 0x20]
                raise OSError("target reset by OBL_LAUNCH")
            self.regs[cr] = value & ~(1 << 17)
            return
        super().write32(addr, value)


# -- detection ------------------------------------------------------------


def test_detects_h7_and_other_families() -> None:
    assert read_dev_id(H7Sim()) == 0x450
    assert read_dev_id(F1Sim(0x414, 0xA5)) == 0x414
    assert read_dev_id(F1Sim(0x440, 0xAA)) == 0x440
    assert family_for_dev_id(0x450) is H7
    assert family_for_dev_id(0x469).name == "g4"
    assert family_for_dev_id(0x999) is None
    ids = [d for fam in obm.FAMILIES for d in fam.dev_ids]
    assert len(ids) == len(set(ids))


def test_unknown_device_is_refused() -> None:
    sim = _Sim(0xE0042000, 0x999)
    with pytest.raises(OptionBytesError):
        OptionBytes.detect(sim)


def test_field_layouts_do_not_overlap() -> None:
    for fam in obm.FAMILIES:
        used: dict[str, int] = {}
        keys = set()
        for f in fam.fields:
            assert f.key not in keys, (fam.name, f.key)
            keys.add(f.key)
            assert f.reg in fam.registers, (fam.name, f.key)
            assert not used.get(f.reg, 0) & f.mask, (fam.name, f.key)
            used[f.reg] = used.get(f.reg, 0) | f.mask
            if f.default is not None:
                assert 0 <= f.default <= f.max_value
            for value, _label in f.choices:
                assert 0 <= value <= f.max_value
        assert fam.get_field("RDP").kind == "rdp"


# -- H7 -------------------------------------------------------------------


def test_h7_reads_real_board_values() -> None:
    ob = OptionBytes.detect(H7Sim())
    snap = ob.snapshot()
    assert snap.family is H7
    assert snap.values["RDP"] == 0xAA
    assert snap.rdp_level == 0
    assert snap.values["BOOT_ADD0"] == 0x0800
    assert snap.values["BOOT_ADD1"] == 0x1FF0
    # A fresh H743 already matches the factory defaults.
    assert ob.plan(snap.regs, snap.factory).changes == []


def test_h7_write_bor_preserves_unknown_bits_and_locks() -> None:
    sim = H7Sim()
    ob = OptionBytes.detect(sim)
    outcome = ob.write({"BOR_LEV": 2})
    assert [c.key for c in outcome.changes] == ["BOR_LEV"]
    assert outcome.reload == "none"
    cur = sim.regs[H7Sim.B + 0x1C]
    assert (cur >> 2) & 3 == 2
    assert cur & ~0xC == 0x0BC6AAF0 & ~0xC
    assert sim.regs[H7Sim.B + 0x18] & 1  # relocked
    assert sim.halted


def test_h7_noop_write_touches_nothing() -> None:
    sim = H7Sim()
    outcome = OptionBytes.detect(sim).write({"RDP": 0xAA, "BOR_LEV": 0})
    assert outcome.changes == []
    assert sim.commits == 0


def test_h7_rdp_level1_then_back_to_level0_mass_erases() -> None:
    sim = H7Sim()
    ob = OptionBytes.detect(sim)
    assert ob.set_rdp(1).rdp_action == "protect"
    assert ob.rdp_level() == 1
    assert ob.set_rdp(0).rdp_action == "unprotect"
    assert sim.mass_erased
    assert ob.rdp_level() == 0


def test_rdp_level2_is_refused() -> None:
    sim = H7Sim()
    ob = OptionBytes.detect(sim)
    with pytest.raises(OptionBytesError):
        ob.write({"RDP": 0xCC})
    with pytest.raises(OptionBytesError):
        ob.set_rdp(2)
    assert sim.commits == 0


def test_readonly_field_is_refused() -> None:
    ob = OptionBytes.detect(H7Sim())
    with pytest.raises(OptionBytesError):
        ob.write({"SECURITY": 1})


def test_level2_device_is_frozen() -> None:
    sim = H7Sim(optsr=(0x0BC6AAF0 & ~0xFF00) | 0xCC00)
    ob = OptionBytes.detect(sim)
    assert ob.rdp_level() == 2
    with pytest.raises(OptionBytesError):
        ob.write({"BOR_LEV": 1})


def test_h7_change_error_is_reported() -> None:
    class Failing(H7Sim):
        def write32(self, addr: int, value: int) -> None:
            super().write32(addr, value)
            if addr == self.B + 0x18 and value & 0x2:
                self.regs[self.B + 0x1C] |= 1 << 30

    sim = Failing()
    with pytest.raises(OptionBytesError, match="change error"):
        OptionBytes.detect(sim).write({"BOR_LEV": 1})
    assert sim.regs[H7Sim.B + 0x18] & 1


def test_field_value_range_checked() -> None:
    ob = OptionBytes.detect(H7Sim())
    with pytest.raises(OptionBytesError):
        ob.write({"BOR_LEV": 7})


# -- F0 / F1 --------------------------------------------------------------


def test_f1_erase_program_sequence() -> None:
    sim = F1Sim(0x414, 0xA5)
    ob = OptionBytes.detect(sim)
    assert ob.family is F1
    assert ob.rdp_level() == 0
    outcome = ob.write({"WDG_SW": 0, "DATA0": 0x5A})
    assert outcome.reload == "reset"
    assert sim.erases == 1
    assert sim.ob(0) == 0x5AA5  # RDP kept with its complement
    assert sim.ob(1) & 0xFF == 0xFE
    assert sim.ob(2) == (0x5A | (0xA5 << 8))
    assert sim.regs[F1Sim.B + 0x10] & 0x80  # FPEC relocked


def test_f1_protect_uses_non_a5_value_and_no_level2() -> None:
    sim = F1Sim(0x414, 0xA5)
    ob = OptionBytes.detect(sim)
    assert not F1.has_level2
    assert ob.set_rdp(1).rdp_action == "protect"
    assert sim.ob(0) & 0xFF == 0x00
    assert ob.rdp_level() == 1


def test_f0_obl_launch_drop_is_tolerated() -> None:
    sim = F1Sim(0x440, 0xAA, obl_raises=True)
    ob = OptionBytes.detect(sim)
    assert ob.family is F0
    outcome = ob.write({"RAM_PARITY_CHECK": 0})
    assert outcome.reload == "obl"
    assert sim.obl
    assert sim.ob(1) & 0xFF == 0xBF


def test_f1_unlock_failure() -> None:
    class Stuck(F1Sim):
        def write32(self, addr: int, value: int) -> None:
            if addr == self.B + 0x08:
                return
            super().write32(addr, value)

    with pytest.raises(OptionBytesError, match="unlock"):
        OptionBytes.detect(Stuck(0x414, 0xA5)).write({"DATA1": 1})


# -- F4 -------------------------------------------------------------------


def test_f4_write_commits_optcr() -> None:
    sim = F4Sim()
    ob = OptionBytes.detect(sim)
    assert ob.family is F4
    assert ob.values()["BOR_LEV"] == 3
    ob.write({"BOR_LEV": 1, "nWRP": 0xFFE})
    assert sim.committed is not None
    assert (sim.committed >> 2) & 3 == 1
    assert (sim.committed >> 16) & 0xFFF == 0xFFE
    assert sim.regs[F4Sim.B + 0x14] & 1  # relocked


# -- L4 / G0 (OPTR) -------------------------------------------------------


def test_l4_write_then_obl_launch() -> None:
    sim = OptrSim(0x415, 0xFFEFF8AA)
    ob = OptionBytes.detect(sim)
    assert ob.family is L4
    outcome = ob.write({"nBOOT1": 0})
    assert outcome.reload == "obl"
    assert sim.obl
    assert not (sim.loaded_optr >> 23) & 1
    assert sim.loaded_optr & 0xFF == 0xAA


def test_g0_fields_and_wrp() -> None:
    sim = OptrSim(0x460, 0xDFFFE1AA, idaddr=0x40015800)
    ob = OptionBytes.detect(sim)
    assert ob.family is G0
    values = ob.values()
    assert values["WRP1A_STRT"] == 0x7F
    ob.write({"WRP1A_STRT": 0, "WRP1A_END": 3})
    assert sim.regs[OptrSim.B + 0x2C] & 0x7F == 0
    assert (sim.regs[OptrSim.B + 0x2C] >> 16) & 0x7F == 3


def test_optr_error_flags_raise() -> None:
    class Bad(OptrSim):
        def write32(self, addr: int, value: int) -> None:
            if addr == self.B + 0x14 and value & (1 << 17):
                self.regs[self.B + 0x10] |= 1 << 15  # OPTVERR
                return
            super().write32(addr, value)

    with pytest.raises(OptionBytesError, match="failed"):
        OptionBytes.detect(Bad(0x415, 0xFFEFF8AA)).write({"nBOOT1": 0})
