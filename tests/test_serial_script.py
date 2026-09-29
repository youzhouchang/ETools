"""Parser tests for serial automation scripts."""

from __future__ import annotations

import pytest

from etools.core.serial_script import ScriptCmd, ScriptError, parse_script


def test_parse_basic_flow():
    src = """
    # wake
    send "AT+RST"
    wait 50
    expect "OK" 1500
    send_hex 01 03 00 00 00 01
    log "done"
    """
    cmds = parse_script(src)
    assert [c.op for c in cmds] == ["send", "wait", "expect", "send_hex", "log"]
    assert cmds[0] == ScriptCmd("send", text="AT+RST", line=3)
    assert cmds[1].value == 50
    assert cmds[2].text == "OK" and cmds[2].value == 1500
    assert cmds[3].text == "01 03 00 00 00 01"
    assert cmds[4].text == "done"


def test_parse_expect_default_timeout():
    cmds = parse_script('expect "READY"')
    assert cmds[0].op == "expect" and cmds[0].value == 2000


def test_parse_errors_carry_line():
    with pytest.raises(ScriptError) as exc:
        parse_script('send "ok"\nnope 1')
    assert exc.value.line == 2
    with pytest.raises(ScriptError):
        parse_script("wait abc")
    with pytest.raises(ScriptError):
        parse_script("send_hex ZZ")
    with pytest.raises(ScriptError):
        parse_script("send AT")
