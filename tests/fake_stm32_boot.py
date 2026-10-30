"""In-memory STM32 AN3155 bootloader used by tests and simulations."""

from __future__ import annotations

ACK, NACK = 0x79, 0x1F


def _xor(data: bytes) -> int:
    v = 0
    for b in data:
        v ^= b
    return v


class FakeStm32Bootloader:
    """Behaves like a pyserial port connected to the STM32 system bootloader."""

    def __init__(
        self,
        *,
        base: int = 0x0800_0000,
        size: int = 64 * 1024,
        pid: int = 0x450,
        extended_erase: bool = True,
        protected: bool = False,
    ) -> None:
        self.base = base
        self.mem = bytearray(b"\xff" * size)
        self.pid = pid
        self.extended = extended_erase
        self.protected = protected
        self.tx = bytearray()
        self.timeout = 0.05
        self.dtr = False
        self.rts = False
        self.synced = False
        self.go_address: int | None = None
        self.erase_calls: list[object] = []
        self.writes = 0
        self._gen = self._run()
        next(self._gen)

    # pyserial-like surface
    def write(self, data: bytes) -> int:
        for b in data:
            self._gen.send(b)
        return len(data)

    def read(self, n: int) -> bytes:
        out = bytes(self.tx[:n])
        del self.tx[:n]
        return out

    def reset_input_buffer(self) -> None:
        self.tx.clear()

    def close(self) -> None:
        pass

    # protocol
    def _commands(self) -> list[int]:
        erase = 0x44 if self.extended else 0x43
        return [0x00, 0x01, 0x02, 0x11, 0x21, 0x31, erase, 0x63, 0x73, 0x82, 0x92]

    def _addr(self):
        raw = bytearray()
        for _ in range(5):
            raw.append((yield))
        if _xor(bytes(raw[:4])) != raw[4]:
            return None
        return int.from_bytes(raw[:4], "big")

    def _offset(self, addr: int, n: int) -> int | None:
        off = addr - self.base
        if off < 0 or off + n > len(self.mem):
            return None
        return off

    def _run(self):
        while True:
            b = yield
            if not self.synced:
                if b == 0x7F:
                    self.synced = True
                    self.tx.append(ACK)
                continue
            if b == 0x7F:
                self.tx.append(NACK)
                continue
            cmd = b
            chk = yield
            if chk != cmd ^ 0xFF:
                self.tx.append(NACK)
                continue
            if cmd == 0x00:
                cmds = self._commands()
                self.tx += bytes([ACK, len(cmds), 0x31, *cmds, ACK])
            elif cmd == 0x01:
                self.tx += bytes([ACK, 0x31, 0, 0, ACK])
            elif cmd == 0x02:
                self.tx += bytes([ACK, 1, self.pid >> 8, self.pid & 0xFF, ACK])
            elif cmd == 0x11:
                if self.protected:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                addr = yield from self._addr()
                if addr is None:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                n = yield
                nchk = yield
                if nchk != n ^ 0xFF:
                    self.tx.append(NACK)
                    continue
                off = self._offset(addr, n + 1)
                if off is None:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                self.tx += self.mem[off : off + n + 1]
            elif cmd == 0x31:
                if self.protected:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                addr = yield from self._addr()
                if addr is None:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                n = yield
                data = bytearray()
                for _ in range(n + 1):
                    data.append((yield))
                chk = yield
                off = self._offset(addr, len(data))
                if chk != _xor(bytes([n]) + bytes(data)) or off is None:
                    self.tx.append(NACK)
                    continue
                for i, v in enumerate(data):
                    # Flash can only clear bits.
                    self.mem[off + i] &= v
                self.writes += 1
                self.tx.append(ACK)
            elif cmd == 0x21:
                self.tx.append(ACK)
                addr = yield from self._addr()
                self.go_address = addr
                self.tx.append(ACK)
            elif cmd in (0x43, 0x44):
                if (cmd == 0x44) != self.extended or self.protected:
                    self.tx.append(NACK)
                    continue
                self.tx.append(ACK)
                if cmd == 0x44:
                    hi, lo = (yield), (yield)
                    n = hi << 8 | lo
                    if n == 0xFFFF:
                        _ = yield
                        self.mem[:] = b"\xff" * len(self.mem)
                        self.erase_calls.append("mass")
                        self.tx.append(ACK)
                        continue
                    pages = []
                    for _ in range(n + 1):
                        pages.append(((yield) << 8) | (yield))
                    _ = yield
                else:
                    n = yield
                    if n == 0xFF:
                        _ = yield
                        self.mem[:] = b"\xff" * len(self.mem)
                        self.erase_calls.append("mass")
                        self.tx.append(ACK)
                        continue
                    pages = []
                    for _ in range(n + 1):
                        pages.append((yield))
                    _ = yield
                self.erase_calls.append(pages)
                self.tx.append(ACK)
            elif cmd == 0x92:
                self.tx.append(ACK)
                self.mem[:] = b"\xff" * len(self.mem)
                self.protected = False
                self.synced = False
                self.tx.append(ACK)
            elif cmd == 0x82:
                self.tx.append(ACK)
                self.protected = True
                self.synced = False
                self.tx.append(ACK)
            elif cmd in (0x63, 0x73):
                self.tx += bytes([ACK, ACK])
                self.synced = False
            else:
                self.tx.append(NACK)
