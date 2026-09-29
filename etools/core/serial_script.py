"""Line-based serial automation scripts (send / wait / expect / log).

Grammar (one command per line, ``#`` comments):

    send "AT+RST"
    send_hex 01 03 00 00 00 01
    wait 100
    expect "OK" 2000
    log "step ok"

``expect`` blocks until the RX text buffer contains the needle or the
timeout elapses.  The runner lives in the serial page and drives these
commands without blocking the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class ScriptError(ValueError):
    """Raised for invalid script text; ``line`` is 1-based."""

    def __init__(self, message: str, line: int = 0) -> None:
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass(frozen=True)
class ScriptCmd:
    op: str  # send | send_hex | wait | expect | log
    text: str = ""
    value: int = 0
    line: int = 0


_QUOTED = re.compile(r'^"(.*)"$')
_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]{1,2}$")


def parse_script(source: str) -> list[ScriptCmd]:
    """Parse automation script text into commands. Raises ScriptError."""
    cmds: list[ScriptCmd] = []
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        op = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if op == "send":
            text = _unquote(rest, lineno)
            cmds.append(ScriptCmd("send", text=text, line=lineno))
        elif op == "send_hex":
            tokens = rest.replace(",", " ").split()
            if not tokens:
                raise ScriptError("send_hex needs at least one byte", lineno)
            for tok in tokens:
                if not _HEX_TOKEN.match(tok):
                    raise ScriptError(f"bad hex byte {tok!r}", lineno)
            cmds.append(ScriptCmd("send_hex", text=" ".join(tokens), line=lineno))
        elif op == "wait":
            cmds.append(ScriptCmd("wait", value=_int_arg(rest, lineno, "wait"), line=lineno))
        elif op == "expect":
            m = re.match(r'^"(.*)"\s*(\d+)?$', rest)
            if not m:
                raise ScriptError('expect needs a quoted string and optional timeout ms', lineno)
            timeout = int(m.group(2)) if m.group(2) else 2000
            cmds.append(ScriptCmd("expect", text=m.group(1), value=timeout, line=lineno))
        elif op == "log":
            cmds.append(ScriptCmd("log", text=_unquote(rest, lineno), line=lineno))
        else:
            raise ScriptError(f"unknown command {op!r}", lineno)
    return cmds


def _unquote(text: str, lineno: int) -> str:
    m = _QUOTED.match(text.strip())
    if not m:
        raise ScriptError("expected quoted string", lineno)
    return m.group(1)


def _int_arg(text: str, lineno: int, op: str) -> int:
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ScriptError(f"{op} needs an integer", lineno) from exc
    if value < 0:
        raise ScriptError(f"{op} must be >= 0", lineno)
    return value
