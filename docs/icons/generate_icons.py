#!/usr/bin/env python3
"""Generate ETools icon set as SVG files.

Writes polished 24×24 UI icons + brand logos to:
  docs/icons/icons/          (design preview)
  etools/ui/resources/icons/ (runtime package)
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

DOCS_OUT = Path(__file__).resolve().parent / "icons"
APP_OUT = Path(__file__).resolve().parents[2] / "etools" / "ui" / "resources" / "icons"

UI_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"
  fill="none" stroke="currentColor" stroke-width="1.75"
  stroke-linecap="round" stroke-linejoin="round">
{body}
</svg>
"""

ACCENT = "#3B9EFF"
DARK_BG = "#0B1220"
CHIP_FILL = "#1A2740"
CHIP_FILL_HI = "#243452"
WHITE = "#E6EAF0"
SUCCESS = "#3DDC97"
DANGER = "#FF5C5C"
WARNING = "#F5A623"
RING = "#2A3A55"


def write_ui(name: str, body: str) -> None:
    svg = UI_SVG.format(body=body.strip("\n"))
    for out in (DOCS_OUT, APP_OUT):
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.svg").write_text(svg, encoding="utf-8")


def write_raw(name: str, svg: str) -> None:
    for out in (DOCS_OUT, APP_OUT):
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.svg").write_text(svg, encoding="utf-8")


# Shared QFP chip geometry (body 7→17, pins on all four sides)
CHIP_PINS = """\
  <path d="M9.25 7V4.5M14.75 7V4.5M9.25 17v2.5M14.75 17v2.5"/>
  <path d="M7 9.25H4.5M7 14.75H4.5M17 9.25h2.5M17 14.75h2.5"/>
"""
CHIP_BODY = '<rect x="7" y="7" width="10" height="10" rx="2"/>'


def main() -> None:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    APP_OUT.mkdir(parents=True, exist_ok=True)

    # ---- brand logo (app icon) ----
    logo = dedent(
        f"""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
          <defs>
            <linearGradient id="bg" x1="0" y1="0" x2="256" y2="256" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="{DARK_BG}"/>
              <stop offset="100%" stop-color="#1A2740"/>
            </linearGradient>
            <linearGradient id="die" x1="84" y1="84" x2="172" y2="172" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="{CHIP_FILL_HI}"/>
              <stop offset="100%" stop-color="#152038"/>
            </linearGradient>
            <filter id="soft" x="-24%" y="-24%" width="148%" height="148%">
              <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#000" flood-opacity="0.4"/>
            </filter>
            <filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="6" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <rect width="256" height="256" rx="56" fill="url(#bg)"/>
          <rect x="2" y="2" width="252" height="252" rx="54" fill="none" stroke="{RING}" stroke-width="2"/>
          <g stroke="{ACCENT}" stroke-width="7" stroke-linecap="round">
            <path d="M76 100H58"/><path d="M76 128H58"/><path d="M76 156H58"/>
            <path d="M180 100h18"/><path d="M180 128h18"/><path d="M180 156h18"/>
            <path d="M108 76V58"/><path d="M148 76V58"/>
            <path d="M108 180v18"/><path d="M148 180v18"/>
          </g>
          <g filter="url(#soft)">
            <rect x="76" y="76" width="104" height="104" rx="22" fill="url(#die)" stroke="{ACCENT}" stroke-width="4"/>
            <circle cx="100" cy="100" r="5" fill="{ACCENT}" opacity="0.55"/>
          </g>
          <path filter="url(#glow)"
                d="M145 88 L104 142 H124 L111 176 L152 120 H130 L145 88 Z"
                fill="{WHITE}"/>
        </svg>
        """
    )
    write_raw("logo", logo)

    logo_mark = dedent(
        f"""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
          <g stroke="{ACCENT}" stroke-width="7" stroke-linecap="round">
            <path d="M76 100H58"/><path d="M76 128H58"/><path d="M76 156H58"/>
            <path d="M180 100h18"/><path d="M180 128h18"/><path d="M180 156h18"/>
            <path d="M108 76V58"/><path d="M148 76V58"/>
            <path d="M108 180v18"/><path d="M148 180v18"/>
          </g>
          <rect x="76" y="76" width="104" height="104" rx="22" fill="{CHIP_FILL}" stroke="{ACCENT}" stroke-width="4"/>
          <circle cx="100" cy="100" r="5" fill="{ACCENT}" opacity="0.55"/>
          <path d="M145 88 L104 142 H124 L111 176 L152 120 H130 L145 88 Z" fill="{WHITE}"/>
        </svg>
        """
    )
    write_raw("logo-mark", logo_mark)

    # ---- flash / firmware ----
    write_ui("chip", f"{CHIP_BODY}\n{CHIP_PINS}\n  <circle cx=\"10\" cy=\"10\" r=\"0.9\" fill=\"currentColor\" stroke=\"none\"/>")

    write_ui(
        "program",
        f"""
{CHIP_BODY}
{CHIP_PINS}
  <path d="M13.4 8.4L9.9 13.1h2.5L10.8 16.4l3.7-4.6h-2.4l1.3-3.4z" fill="currentColor" stroke="none"/>
""",
    )

    write_ui(
        "erase",
        f"""
{CHIP_BODY}
  <path d="M9.25 7V4.5M14.75 7V4.5M9.25 17v2.5M14.75 17v2.5"/>
  <path d="M9.1 15.4l5.2-5.2a1.55 1.55 0 012.2 2.2l-5.2 5.2H9.1z"/>
  <path d="M13.2 11.3l2.2 2.2"/>
""",
    )

    write_ui(
        "verify",
        """
  <circle cx="12" cy="12" r="8.25"/>
  <path d="M8.15 12.15l2.55 2.55 5.2-5.35"/>
""",
    )

    write_ui(
        "reset",
        """
  <path d="M5 12a7 7 0 0111.85-4.95"/>
  <path d="M19 12a7 7 0 01-11.85 4.95"/>
  <path d="M16.6 3.9v3.4h-3.4"/>
  <path d="M7.4 20.1v-3.4h3.4"/>
""",
    )

    write_ui(
        "read",
        f"""
{CHIP_BODY}
  <path d="M9.25 7V4.5M14.75 7V4.5M9.25 17v2.5M14.75 17v2.5"/>
  <path d="M12 15.6V8.8"/>
  <path d="M9.6 11.2L12 8.6l2.4 2.6"/>
  <path d="M9.5 17.4h5"/>
""",
    )

    write_ui(
        "open",
        """
  <path d="M3.75 8.4A1.75 1.75 0 015.5 6.65h3.15l1.55 1.75H18.5a1.75 1.75 0 011.75 1.75v7.1A1.75 1.75 0 0118.5 19H5.5a1.75 1.75 0 01-1.75-1.75V8.4z"/>
  <path d="M12 11.3v4.9"/>
  <path d="M10.05 14.15L12 16.25l1.95-2.1"/>
""",
    )

    write_ui(
        "hex",
        """
  <rect x="4" y="5" width="16" height="14" rx="2"/>
  <path d="M8.2 9.5h.01M12 9.5h.01M15.8 9.5h.01M8.2 14.5h.01M12 14.5h.01M15.8 14.5h.01"
        stroke-width="2.5"/>
""",
    )

    # ---- probe / target ----
    write_ui(
        "probe",
        """
  <rect x="7.25" y="4.25" width="9.5" height="7.5" rx="1.75"/>
  <path d="M9.75 4.25V3M14.25 4.25V3"/>
  <path d="M10.25 11.75v2.2M13.75 11.75v2.2"/>
  <path d="M7.75 16h8.5"/>
  <path d="M9.25 16v2.2M12 16v2.75M14.75 16v2.2"/>
  <circle cx="10.4" cy="7.6" r="0.75" fill="currentColor" stroke="none"/>
  <circle cx="13.6" cy="7.6" r="0.75" fill="currentColor" stroke="none"/>
""",
    )

    write_ui(
        "connect",
        """
  <circle cx="5.1" cy="9.6" r="1.55"/>
  <circle cx="18.9" cy="9.6" r="1.55"/>
  <path d="M5.1 8.05V5.6M18.9 8.05V5.6"/>
  <path d="M8.15 12.9l2.35 2.35a3.15 3.15 0 004.45 0l2.35-2.35"/>
  <path d="M6.15 10.9l2 2M17.85 10.9l-2 2"/>
""",
    )

    write_ui(
        "disconnect",
        """
  <circle cx="5.4" cy="10" r="1.55"/>
  <circle cx="18.6" cy="10" r="1.55"/>
  <path d="M5.4 8.45V6M18.6 8.45V6"/>
  <path d="M7.35 11.25l2.15 2.15M16.65 11.25l-2.15 2.15"/>
  <path d="M9.35 15.15l-1.65 1.65M14.65 15.15l1.65 1.65"/>
  <path d="M9.85 14.7l4.3-4.3"/>
""",
    )

    write_ui(
        "scan",
        """
  <rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1"/>
  <path d="M7.35 12a4.65 4.65 0 014.65-4.65"/>
  <path d="M12 16.65A4.65 4.65 0 017.35 12"/>
  <path d="M16.65 12a4.65 4.65 0 01-4.65 4.65"/>
  <path d="M4.95 12A7.05 7.05 0 0112 4.95" opacity="0.65"/>
  <path d="M12 19.05A7.05 7.05 0 014.95 12" opacity="0.65"/>
""",
    )

    write_ui(
        "devices",
        """
  <rect x="7.25" y="8.5" width="9.5" height="9.5" rx="2"/>
  <path d="M9.75 8.5V6.6M14.25 8.5V6.6M9.75 18v1.9M14.25 18v1.9"/>
  <path d="M7.25 11.2H5.35M7.25 15.3H5.35M16.75 11.2h1.9M16.75 15.3h1.9"/>
  <path d="M4.2 6.6h3.2M16.6 6.6H19.8" opacity="0.5"/>
  <path d="M4.2 19.9h3.2M16.6 19.9H19.8" opacity="0.5"/>
""",
    )

    write_ui(
        "refresh",
        """
  <path d="M5.6 12a6.4 6.4 0 0110.95-4.45"/>
  <path d="M18.4 12a6.4 6.4 0 01-10.95 4.45"/>
  <path d="M16.15 4.85v2.85h-2.85"/>
  <path d="M7.85 19.15v-2.85h2.85"/>
""",
    )

    write_ui(
        "info",
        """
  <circle cx="12" cy="12" r="8.25"/>
  <path d="M12 11.15v5.05"/>
  <circle cx="12" cy="8.2" r="0.9" fill="currentColor" stroke="none"/>
""",
    )

    # ---- debug views ----
    write_ui(
        "rtt",
        """
  <rect x="3.75" y="5" width="16.5" height="14" rx="2"/>
  <path d="M3.75 8.4h16.5"/>
  <circle cx="6.55" cy="6.7" r="0.7" fill="currentColor" stroke="none"/>
  <circle cx="8.85" cy="6.7" r="0.7" fill="currentColor" stroke="none"/>
  <path d="M7.1 12.1l2.5 2.2-2.5 2.2"/>
  <path d="M12.3 16.5H16"/>
""",
    )

    write_ui(
        "swv",
        """
  <path d="M3.6 5.5v13.2h16.8" opacity="0.4"/>
  <path d="M3.6 15.4c1.95 0 2.15-6.9 4.1-6.9s2.35 6.9 4.2 6.9 2.25-4.9 4.1-4.9 2.25 1.95 4.2 1.95"/>
""",
    )

    write_ui(
        "memory",
        """
  <rect x="5" y="6.2" width="14" height="3.8" rx="1"/>
  <rect x="5" y="11.1" width="14" height="3.8" rx="1"/>
  <rect x="5" y="16" width="14" height="2.8" rx="1" opacity="0.5"/>
  <path d="M8.2 6.2v3.8M12 6.2v3.8M15.8 6.2v3.8M8.2 11.1v3.8M12 11.1v3.8M15.8 11.1v3.8" opacity="0.5"/>
""",
    )

    write_ui(
        "save",
        """
  <path d="M12 4.6v9.1"/>
  <path d="M9.05 10.95L12 14.05l2.95-3.1"/>
  <path d="M5.55 16.4v1.25A1.75 1.75 0 007.3 19.4h9.4a1.75 1.75 0 001.75-1.75V16.4"/>
""",
    )

    write_ui(
        "fill",
        """
  <rect x="4.5" y="4.5" width="15" height="15" rx="2"/>
  <path d="M4.5 10h15M4.5 15h15M10 4.5v15M15 4.5v15" opacity="0.4"/>
  <path d="M4.5 4.5h5.5v5.5H4.5z" fill="currentColor" stroke="none" opacity="0.85"/>
  <path d="M10 10h5v5h-5z" fill="currentColor" stroke="none" opacity="0.4"/>
""",
    )

    write_ui(
        "blank",
        """
  <rect x="5" y="5" width="14" height="14" rx="2.5" stroke-dasharray="2.7 2.4"/>
  <path d="M8.75 12.2l2.35 2.35 4.25-4.5"/>
""",
    )

    write_ui(
        "compare",
        """
  <rect x="4.1" y="5.6" width="6.9" height="12.8" rx="1.5"/>
  <rect x="13" y="5.6" width="6.9" height="12.8" rx="1.5"/>
  <path d="M12 8.1v7.8"/>
  <path d="M6.3 9.2h2.5M6.3 12h2.5M6.3 14.8h1.55" opacity="0.55"/>
  <path d="M15.2 9.2h2.5M15.2 12h2.5M15.2 14.8h1.55" opacity="0.55"/>
""",
    )

    write_ui(
        "clear",
        """
  <path d="M8.15 8.5h7.7"/>
  <path d="M9.65 8.5V6.85A1.3 1.3 0 0110.95 5.55h2.1a1.3 1.3 0 011.3 1.3V8.5"/>
  <path d="M7.35 8.5l.75 9.05A1.55 1.55 0 009.65 19h4.7a1.55 1.55 0 001.55-1.45L16.65 8.5"/>
  <path d="M10.35 11.4v4.1M13.65 11.4v4.1"/>
""",
    )

    # ---- system / status ----
    write_ui(
        "theme-dark",
        """
  <path d="M18.15 14.55A7.15 7.15 0 019.45 5.85 7.35 7.35 0 1018.15 14.55z"/>
""",
    )

    write_ui(
        "theme-light",
        """
  <circle cx="12" cy="12" r="3.55"/>
  <path d="M12 3.85v1.55M12 18.6v1.55M3.85 12h1.55M18.6 12h1.55"/>
  <path d="M6.2 6.2l1.1 1.1M16.7 16.7l1.1 1.1M17.8 6.2l-1.1 1.1M7.3 16.7l-1.1 1.1"/>
""",
    )

    write_ui(
        "language",
        """
  <circle cx="12" cy="12" r="8.25"/>
  <path d="M4.25 12h15.5"/>
  <path d="M12 3.85c2.35 2.35 3.55 5.05 3.55 8.15S14.35 17.8 12 20.15C9.65 17.8 8.45 15.1 8.45 12S9.65 6.2 12 3.85z"/>
""",
    )

    write_ui(
        "success",
        f"""
  <circle cx="12" cy="12" r="8.25" stroke="{SUCCESS}"/>
  <path d="M8.15 12.15l2.55 2.55 5.2-5.35" stroke="{SUCCESS}"/>
""",
    )

    write_ui(
        "warning",
        f"""
  <path d="M12 4.85l8.15 14.15H3.85L12 4.85z" stroke="{WARNING}"/>
  <path d="M12 10.05v4.15" stroke="{WARNING}"/>
  <circle cx="12" cy="16.55" r="0.85" fill="{WARNING}" stroke="none"/>
""",
    )

    write_ui(
        "error",
        f"""
  <circle cx="12" cy="12" r="8.25" stroke="{DANGER}"/>
  <path d="M9.25 9.25l5.5 5.5M14.75 9.25l-5.5 5.5" stroke="{DANGER}"/>
""",
    )

    write_ui(
        "pause",
        """
  <circle cx="12" cy="12" r="8.25"/>
  <path d="M10.05 9.55v4.9M13.95 9.55v4.9"/>
""",
    )

    write_ui(
        "power",
        """
  <path d="M12 4.55v6.9"/>
  <path d="M7.85 7.3a5.45 5.45 0 108.3 0"/>
""",
    )

    write_ui(
        "stop",
        f"""
  <circle cx="12" cy="12" r="8.25"/>
  <rect x="9.25" y="9.25" width="5.5" height="5.5" rx="1" fill="{DANGER}" stroke="{DANGER}"/>
""",
    )

    write_ui(
        "about",
        """
  <circle cx="12" cy="12" r="8.25"/>
  <path d="M12 11.15v5.05"/>
  <circle cx="12" cy="8.2" r="0.9" fill="currentColor" stroke="none"/>
""",
    )

    write_ui(
        "quit",
        """
  <path d="M9.5 5.5H6.75A1.75 1.75 0 005 7.25v9.5A1.75 1.75 0 006.75 18.5H9.5"/>
  <path d="M14.2 8.2L17.5 12l-3.3 3.8"/>
  <path d="M17.2 12H9.8"/>
""",
    )

    # ---- multi-tool shell rail (dedicated, not borrowed) ----
    write_ui(
        "tool-program",
        f"""
{CHIP_BODY}
{CHIP_PINS}
  <path d="M13.4 8.4L9.9 13.1h2.5L10.8 16.4l3.7-4.6h-2.4l1.3-3.4z" fill="currentColor" stroke="none"/>
""",
    )

    write_ui(
        "tool-serial",
        """
  <rect x="4.25" y="8.25" width="15.5" height="10" rx="2"/>
  <path d="M7.5 8.25V6.4M12 8.25V5.6M16.5 8.25V6.4"/>
  <path d="M8.2 13.25h.01M12 13.25h.01M15.8 13.25h.01" stroke-width="2.4"/>
  <path d="M8.5 16.25h7"/>
""",
    )

    write_ui(
        "tool-ethernet",
        """
  <path d="M8 4.75h8v4.1l-2.1 2.1v6.4h-3.8v-6.4L8 8.85V4.75z"/>
  <path d="M10.2 4.75V3.4M13.8 4.75V3.4"/>
  <path d="M10.35 12.1v3.6M12 12.1v3.6M13.65 12.1v3.6" opacity="0.7"/>
""",
    )

    write_ui(
        "tool-terminal",
        """
  <rect x="3.75" y="5" width="16.5" height="14" rx="2"/>
  <path d="M3.75 8.4h16.5"/>
  <path d="M7.4 12.4l2.4 2.15-2.4 2.15"/>
  <path d="M12.2 16.7H16.4"/>
""",
    )

    print(f"Wrote icons to {DOCS_OUT}")
    print(f"Wrote icons to {APP_OUT}")


if __name__ == "__main__":
    main()
