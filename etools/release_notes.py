"""Extract a version section from CHANGELOG.md for GitHub Release notes."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_section(text: str, version: str) -> str:
    """Return the body under '## [version]' (optional ' - date') until next ##."""
    pat = re.compile(
        rf"^##\s*\[{re.escape(version)}\](?:\s*-\s*[0-9-\s./]+)?\s*$",
        re.MULTILINE,
    )
    m = pat.search(text)
    if not m:
        return ""
    rest = text[m.end() :]
    next_h = re.search(r"^##\s", rest, re.MULTILINE)
    section = rest[: next_h.start()] if next_h else rest
    section = section.strip()
    # Drop trailing horizontal-rule separators used between CHANGELOG sections
    while True:
        stripped = re.sub(r"\n?---\s*$", "", section).rstrip()
        if stripped == section:
            break
        section = stripped
    return section


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Version without leading v, e.g. 0.1.2")
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        type=Path,
        help="Path to CHANGELOG.md",
    )
    args = parser.parse_args(argv)
    if not args.changelog.is_file():
        return 0
    text = args.changelog.read_text(encoding="utf-8")
    section = extract_section(text, args.version)
    if section:
        sys.stdout.write(section + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
