"""Numeric input helpers for firmware addresses / sizes / clocks."""

from __future__ import annotations

from PySide6.QtWidgets import QSpinBox


def hex_spin(
    value: int = 0,
    *,
    minimum: int = 0,
    maximum: int = 0x7FFF_FFFF,
    step: int = 0x100,
    prefix: str = "0x",
    width: int = 120,
) -> QSpinBox:
    """Hexadecimal QSpinBox suitable for flash addresses / lengths."""
    spin = QSpinBox()
    spin.setDisplayIntegerBase(16)
    spin.setPrefix(prefix)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setAccelerated(True)
    spin.setKeyboardTracking(False)
    spin.setGroupSeparatorShown(False)
    spin.setMinimumWidth(width)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
    spin.setValue(min(max(value, minimum), maximum))
    return spin


def int_spin(
    value: int = 0,
    *,
    minimum: int = 0,
    maximum: int = 1_000_000_000,
    step: int = 1,
    suffix: str = "",
    width: int = 100,
) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setAccelerated(True)
    spin.setKeyboardTracking(False)
    if suffix:
        spin.setSuffix(suffix)
    spin.setMinimumWidth(width)
    spin.setValue(min(max(value, minimum), maximum))
    return spin
