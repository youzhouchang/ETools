"""Global Lua host tests (skipped when lupa is unavailable)."""

from __future__ import annotations

import time

import pytest

from etools.core.lua_host import LuaError, LuaHost

pytest.importorskip("lupa")


def test_lua_util_checksum_and_hex():
    host = LuaHost()
    logs: list[str] = []
    host.set_log_hook(logs.append)
    done: list[tuple[bool, str]] = []
    host.set_done_hook(lambda ok, msg: done.append((ok, msg)))
    host.run_script(
        """
        local body = etools.util.unhex('01 03 00 00 00 01')
        local frame = etools.util.append_checksum(body, 'crc16_modbus')
        etools.app.log(etools.util.hex(frame))
        assert(etools.util.verify_checksum(frame, 'crc16_modbus'))
        """
    )
    deadline = time.time() + 3
    while not done and time.time() < deadline:
        time.sleep(0.02)
    assert done and done[0][0] is True
    assert any("01 03 00 00 00 01 84 0A" in line for line in logs)


def test_lua_serial_bridge_and_flash_api():
    host = LuaHost()

    class SerialStub:
        def __init__(self):
            self.sent = []

        def send(self, text):
            self.sent.append(text)
            return True

        def expect(self, needle, timeout):
            return needle == "OK"

    class FlashStub:
        def connected(self):
            return True

        def program(self, path, verify=True):
            return path == "app.bin" and verify

        def erase_range(self, addr, size):
            return addr == 0x08000000 and size == 0x1000

    serial = SerialStub()
    flash = FlashStub()
    host.set_bridge("serial", serial)
    host.set_bridge("flash", flash)
    done: list[tuple[bool, str]] = []
    host.set_done_hook(lambda ok, msg: done.append((ok, msg)))
    host.run_script(
        """
        etools.serial.send('AT')
        assert(etools.serial.expect('OK', 10))
        assert(etools.flash.connected())
        assert(etools.flash.program('app.bin', true))
        assert(etools.flash.erase_range(0x08000000, 0x1000))
        """
    )
    deadline = time.time() + 3
    while not done and time.time() < deadline:
        time.sleep(0.02)
    assert done and done[0][0] is True
    assert serial.sent == ["AT"]


def test_lua_stops_and_reports_errors():
    host = LuaHost()
    done: list[tuple[bool, str]] = []
    host.set_done_hook(lambda ok, msg: done.append((ok, msg)))

    # while a script is running, a second start is rejected
    host.run_script("etools.app.sleep(200)")
    with pytest.raises(LuaError):
        host.run_script("etools.app.log('x')")
    host.stop()
    deadline = time.time() + 3
    while not done and time.time() < deadline:
        time.sleep(0.02)

    # runtime errors are reported via done(ok=False)
    done.clear()
    host.run_script("error('boom')")
    deadline = time.time() + 3
    while not done and time.time() < deadline:
        time.sleep(0.02)
    assert done and done[0][0] is False
    assert "boom" in done[0][1]
