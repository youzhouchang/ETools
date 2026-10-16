"""RX trigger auto-reply engine."""

from etools.core.trigger_reply import TriggerEngine, TriggerRule


def test_text_match_and_cooldown():
    engine = TriggerEngine()
    engine.rules[0] = TriggerRule(
        enabled=True, mode="text", pattern="OK", reply="ACK", cooldown_ms=1000
    )
    hits = engine.feed(b"noise OK tail", encoding="utf-8")
    assert len(hits) == 1
    assert hits[0].rule.reply == "ACK"
    assert engine.feed(b"OK again", encoding="utf-8") == []


def test_hex_match_and_once():
    engine = TriggerEngine()
    engine.rules[0] = TriggerRule(
        enabled=True,
        mode="hex",
        pattern="01 02",
        reply="AA",
        reply_hex=True,
        once=True,
        cooldown_ms=0,
    )
    assert len(engine.feed(bytes.fromhex("00 01 02 03"))) == 1
    assert engine.feed(bytes.fromhex("01 02")) == []


def test_regex_and_persistence_roundtrip():
    engine = TriggerEngine()
    engine.rules[0] = TriggerRule(
        enabled=True, mode="regex", pattern=r"ID=(\d+)", reply="pong", cooldown_ms=0
    )
    assert len(engine.feed(b"ID=42\n")) == 1
    payload = engine.dump_rules()
    other = TriggerEngine()
    other.load_rules(payload)
    assert other.rules[0].pattern == r"ID=(\d+)"
    assert other.rules[0].mode == "regex"
