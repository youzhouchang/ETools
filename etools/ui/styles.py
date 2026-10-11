"""Application QSS themes (dark / light) — compact layout."""

from __future__ import annotations

import atexit
import tempfile
from dataclasses import dataclass
from pathlib import Path

from etools.ui.qss_sections import SECTIONS


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str
    accent_hover: str
    bg: str
    bg_panel: str
    bg_input: str
    bg_hover: str
    border: str
    text: str
    text_dim: str
    text_muted: str
    success: str
    warning: str
    danger: str
    log_bg: str
    on_accent: str


DARK = Theme(
    name="dark",
    accent="#3B9EFF",
    accent_hover="#5CB0FF",
    bg="#1E222A",
    bg_panel="#1E222A",
    bg_input="#2A303A",
    bg_hover="#323A46",
    border="#343C48",
    text="#E6EAF0",
    text_dim="#9AA3B2",
    text_muted="#6B7382",
    success="#3DDC97",
    warning="#F5A623",
    danger="#FF5C5C",
    log_bg="#181C23",
    on_accent="#0B1220",
)

LIGHT = Theme(
    name="light",
    accent="#1A73E8",
    accent_hover="#1557B0",
    bg="#F3F5F8",
    bg_panel="#F3F5F8",
    bg_input="#FFFFFF",
    bg_hover="#E7ECF3",
    border="#D5DCE6",
    text="#1F2933",
    text_dim="#5B6B7C",
    text_muted="#8B98A8",
    success="#0F9D6E",
    warning="#C27803",
    danger="#D93025",
    log_bg="#EBEFF5",
    on_accent="#FFFFFF",
)

THEMES: dict[str, Theme] = {"dark": DARK, "light": LIGHT}

# Cached arrow PNG files (Qt QSS cannot use data: URLs reliably)
_arrow_files: dict[str, str] = {}
_tmpdir: Path | None = None


def resolve_system_theme() -> str:
    """Best-effort light/dark detection from the OS palette."""
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            return "dark"
        # Window color luminance is a cheap proxy for system light/dark.
        color = app.palette().color(app.palette().ColorRole.Window)
        lum = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        return "light" if lum >= 128 else "dark"
    except Exception:  # noqa: BLE001
        return "dark"


def get_theme(name: str | None = None) -> Theme:
    """Resolve a theme by name; *None* uses the saved app config."""
    if not name:
        try:
            from etools.config import get_config

            name = get_config().theme
        except Exception:  # noqa: BLE001 — config optional in pure-style use
            name = "dark"
    key = (name or "dark").lower()
    if key == "system":
        key = resolve_system_theme()
    return THEMES.get(key, DARK)


def _ensure_tmpdir() -> Path:
    global _tmpdir
    if _tmpdir is None:
        _tmpdir = Path(tempfile.mkdtemp(prefix="etools_icons_"))
        atexit.register(_cleanup_tmp)
    return _tmpdir


def _cleanup_tmp() -> None:
    global _tmpdir
    if _tmpdir and _tmpdir.exists():
        for p in _tmpdir.glob("*.png"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            _tmpdir.rmdir()
        except OSError:
            pass
    _tmpdir = None


def arrow_file(color: str, direction: str = "down") -> str:
    """Write a small triangle PNG (up/down) and return its path for QSS url()."""
    key = f"{direction}_{color.lower()}"
    if key in _arrow_files and Path(_arrow_files[key]).exists():
        return _arrow_files[key]

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygon

    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(Qt.PenStyle.NoPen))
    p.setBrush(QBrush(QColor(color)))
    if direction == "up":
        p.drawPolygon(QPolygon([QPoint(1, 7), QPoint(9, 7), QPoint(5, 2)]))
    else:
        p.drawPolygon(QPolygon([QPoint(1, 3), QPoint(9, 3), QPoint(5, 8)]))
    p.end()

    path = _ensure_tmpdir() / f"arrow_{key.lstrip('#').replace('#', '')}.png"
    img.save(str(path), "PNG")
    _arrow_files[key] = str(path)
    return str(path)


def build_stylesheet(theme: str | Theme = "dark") -> str:
    t = theme if isinstance(theme, Theme) else get_theme(theme)
    fields = dict(t.__dict__)
    fields["arrow_url"] = arrow_file(t.text_dim).replace("\\", "/")
    fields["spin_up_url"] = arrow_file(t.text_dim, "up").replace("\\", "/")
    fields["spin_down_url"] = arrow_file(t.text_dim, "down").replace("\\", "/")
    return _QSS.format(**fields)


def theme_combo_stylesheet(t: Theme) -> str:
    """Per-combo stylesheet: rounded popup + triangle via file url."""
    arrow = arrow_file(t.text_dim)
    # Use forward slashes for QSS url()
    arrow_qss = arrow.replace("\\", "/")
    return f"""
    QComboBox {{
        background-color: {t.bg_input};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 5px;
        padding: 4px 26px 4px 8px;
        font-size: 12px;
    }}
    QComboBox:hover {{
        border-color: {t.accent};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: border;
        subcontrol-position: center right;
        border: none;
        background: transparent;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        image: url({arrow_qss});
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.bg_panel};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 6px;
        outline: none;
        selection-background-color: {t.accent};
        selection-color: {t.on_accent};
        font-size: 12px;
    }}
    QComboBox QAbstractItemView::item {{
        background-color: {t.bg_panel};
        color: {t.text};
        min-height: 24px;
        padding: 3px 6px;
        border-radius: 4px;
        margin: 1px 2px;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {t.accent};
        color: {t.on_accent};
    }}
    QComboBox QAbstractScrollArea {{
        background: transparent;
        border: none;
    }}
    QComboBoxPrivateContainer {{
        background: {t.bg_panel};
        border: 1px solid {t.border};
        border-radius: 6px;
    }}
    """


def apply_combo_style(combo, theme: str | Theme) -> None:
    """Style combo + force rounded frameless popup container."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame

    t = theme if isinstance(theme, Theme) else get_theme(theme)
    combo.setStyleSheet(theme_combo_stylesheet(t))

    view = combo.view()
    if view is None:
        return
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setLineWidth(0)
    view.setMidLineWidth(0)
    # Margin so rounded corners are not clipped by the popup window
    view.setContentsMargins(6, 6, 6, 6)
    view.viewport().setAutoFillBackground(True)

    # Style the private container (true popup window) for rounded corners
    parent = view.parentWidget()
    if parent is not None:
        parent.setObjectName("comboPopupFrame")
        parent.setStyleSheet(
            f"""
            QFrame#comboPopupFrame {{
                background: {t.bg_panel};
                border: 1px solid {t.border};
                border-radius: 6px;
            }}
            """
        )
        try:
            parent.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass


_QSS = "".join(SECTIONS)
