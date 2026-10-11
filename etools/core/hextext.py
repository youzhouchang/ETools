"""Parse user-entered hex text into bytes."""

from __future__ import annotations


def parse_hex_input(text: str) -> bytes:
    """Parse 'DE AD BE' / 'DEADBE' / '0xde 0xad' into bytes."""
    cleaned = []
    for tok in text.replace(",", " ").replace(";", " ").split():
        tok = tok.strip().lower()
        if tok.startswith("0x"):
            tok = tok[2:]
        if not tok:
            continue
        if len(tok) % 2:
            tok = "0" + tok
        cleaned.append(tok)
    raw = "".join(cleaned)
    return bytes.fromhex(raw)
