"""SshLink helpers that do not need a server."""

from __future__ import annotations

import pytest

from etools.core.ssh_link import _drain_channel


class _FakeChannel:
    """Exit is reported only once both streams are empty, like paramiko."""

    def __init__(self, out: bytes, err: bytes, chunk: int = 4096) -> None:
        self.out = bytearray(out)
        self.err = bytearray(err)
        self.chunk = chunk
        self.exited = not (out or err)

    def recv_ready(self) -> bool:
        return bool(self.out)

    def recv_stderr_ready(self) -> bool:
        return bool(self.err)

    def recv(self, n: int) -> bytes:
        data = bytes(self.out[: min(n, self.chunk)])
        del self.out[: len(data)]
        self.exited = not (self.out or self.err)
        return data

    def recv_stderr(self, n: int) -> bytes:
        data = bytes(self.err[: min(n, self.chunk)])
        del self.err[: len(data)]
        self.exited = not (self.out or self.err)
        return data

    def exit_status_ready(self) -> bool:
        return self.exited


def test_drain_reads_both_streams_and_caps_each():
    channel = _FakeChannel(b"o" * 300_000, b"e" * 300_000)
    out, err = _drain_channel(channel, limit=100_000)
    assert out.startswith("o" * 100_000) and "truncated" in out
    assert err.startswith("e" * 100_000) and "truncated" in err
    assert not channel.out and not channel.err


def test_drain_keeps_small_output():
    assert _drain_channel(_FakeChannel(b"hello", b"warn"), limit=100) == ("hello", "warn")


def test_drain_times_out_when_the_command_goes_silent():
    class Silent(_FakeChannel):
        def exit_status_ready(self) -> bool:
            return False

    with pytest.raises(TimeoutError):
        _drain_channel(Silent(b"", b""), idle_timeout=0.05)
