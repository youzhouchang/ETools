"""AN3155 UART bootloader client against an in-memory fake bootloader."""

from __future__ import annotations

import pytest

from etools.core.fw_image import SparseImage
from etools.core.stm32_uart_boot import BootloaderError, LineEntry, Stm32UartBoot
from tests.fake_stm32_boot import FakeStm32Bootloader


def _client(**kw) -> tuple[Stm32UartBoot, FakeStm32Bootloader]:
    fake = FakeStm32Bootloader(**kw)
    return Stm32UartBoot(fake, timeout=0.05), fake


def test_connect_reads_version_commands_and_pid() -> None:
    boot, _fake = _client(pid=0x450)
    info = boot.connect()
    assert info.version_text() == "3.1"
    assert info.extended_erase
    assert info.pid == 0x450
    # A second sync gets NACK (already synchronised) and is still accepted.
    boot.sync()


def test_sync_without_bootloader_fails() -> None:
    class Silent:
        timeout = 0.01

        def write(self, data):
            return len(data)

        def read(self, n):
            return b""

    with pytest.raises(BootloaderError, match="sync"):
        Stm32UartBoot(Silent(), timeout=0.01).sync(attempts=2)


def test_program_verify_and_go() -> None:
    boot, fake = _client()
    boot.connect()
    image = SparseImage([(0x0800_0000, bytes(range(256)) * 3), (0x0800_1003, b"\x11\x22\x33")])
    seen: list[str] = []
    written = boot.program(image, progress=lambda stage, done, total: seen.append(stage))
    assert written == 4 * 256
    assert fake.erase_calls == ["mass"]
    assert bytes(fake.mem[:768]) == bytes(range(256)) * 3
    assert bytes(fake.mem[0x1003:0x1006]) == b"\x11\x22\x33"
    assert fake.mem[0x1002] == 0xFF
    assert {"erase", "write", "verify"} <= set(seen)
    boot.go(0x0800_0000)
    assert fake.go_address == 0x0800_0000


def test_program_skips_blank_blocks_after_mass_erase() -> None:
    boot, fake = _client()
    boot.connect()
    image = SparseImage([(0x0800_0000, b"\xff" * 512 + b"\x01")])
    boot.program(image)
    assert fake.writes == 1


def test_verify_mismatch_is_reported() -> None:
    boot, fake = _client()
    boot.connect()
    fake.mem[0:4] = b"\x00\x00\x00\x00"
    image = SparseImage([(0x0800_0000, b"\xaa" * 16)])
    with pytest.raises(BootloaderError, match="mismatch at 0x08000000"):
        boot.program(image, erase="none")


def test_standard_erase_and_pages() -> None:
    boot, fake = _client(extended_erase=False)
    boot.connect()
    boot.erase_pages([0, 1, 5])
    boot.mass_erase()
    assert fake.erase_calls == [[0, 1, 5], "mass"]


def test_extended_page_erase() -> None:
    boot, fake = _client()
    boot.connect()
    boot.erase_pages([3, 300])
    assert fake.erase_calls == [[3, 300]]


def test_protected_chip_nacks_read_and_unprotect_erases() -> None:
    boot, fake = _client(protected=True)
    boot.connect()
    fake.mem[0] = 0x00
    with pytest.raises(BootloaderError, match="NACK"):
        boot.read_memory(0x0800_0000, 4)
    boot.readout_unprotect()
    assert not fake.protected
    assert fake.mem[0] == 0xFF
    boot.connect()
    assert boot.read_memory(0x0800_0000, 4) == b"\xff" * 4


def test_read_range_spans_blocks() -> None:
    boot, fake = _client()
    boot.connect()
    fake.mem[:600] = bytes(i & 0xFF for i in range(600))
    assert boot.read_range(0x0800_0000, 600) == bytes(i & 0xFF for i in range(600))


def test_read_range_handles_unaligned_address_and_size() -> None:
    # The fake NACKs any Read Memory whose address isn't a multiple of 4
    # (per AN3155), so this only passes if read_range rounds the window to
    # the alignment and trims the extra bytes itself.
    boot, fake = _client()
    boot.connect()
    fake.mem[:600] = bytes(i & 0xFF for i in range(600))
    assert boot.read_range(0x0800_0001, 513) == bytes(
        i & 0xFF for i in range(1, 514)
    )


def test_write_pads_to_word() -> None:
    boot, fake = _client()
    boot.connect()
    boot.write_memory(0x0800_0010, b"\x01\x02\x03")
    assert bytes(fake.mem[0x10:0x14]) == b"\x01\x02\x03\xff"


def test_line_entry_drives_boot_and_reset() -> None:
    class Port:
        def __init__(self) -> None:
            self.log: list[tuple[str, bool]] = []

        def __setattr__(self, name, value):
            if name in ("dtr", "rts"):
                self.log.append((name, value))
            object.__setattr__(self, name, value)

    port = Port()
    port.log = []
    entry = LineEntry(boot_line="rts", reset_line="dtr", pulse_s=0, settle_s=0)
    entry.enter(port)
    assert port.log == [("rts", True), ("dtr", True), ("dtr", False)]
    port.log.clear()
    LineEntry(boot_line="dtr", reset_line="rts", boot_invert=True, pulse_s=0, settle_s=0).leave(
        port
    )
    assert port.log == [("dtr", True), ("rts", True), ("rts", False)]
