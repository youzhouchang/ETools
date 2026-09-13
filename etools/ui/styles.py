"""Application QSS themes (dark / light) — compact layout."""

from __future__ import annotations

import atexit
import tempfile
from dataclasses import dataclass
from pathlib import Path


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


def get_theme(name: str | None = None) -> Theme:
    """Resolve a theme by name; *None* uses the saved app config."""
    if not name:
        try:
            from etools.config import get_config

            name = get_config().theme
        except Exception:  # noqa: BLE001 — config optional in pure-style use
            name = "dark"
    return THEMES.get((name or "dark").lower(), DARK)


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


_QSS = """
/* ========== Global — compact ========== */
* {{
    font-size: 12px;
}}
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{
    background: {bg};
}}
QToolTip {{
    background: {bg_panel};
    color: {text};
    border: 1px solid {border};
    padding: 3px 6px;
    font-size: 11px;
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 6px;
    background: {bg};
    top: -1px;
}}
QTabBar::tab {{
    background: {bg_input};
    color: {text_dim};
    border: 1px solid {border};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 4px 12px;
    margin-right: 1px;
    min-width: 64px;
    max-height: 24px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {bg};
    color: {text};
    border-color: {accent};
}}
QTabBar::tab:hover:!selected {{
    color: {text};
    background: {bg_hover};
}}
/* Hex document sub-tabs — extra compact */
QTabWidget#hexTabs QTabBar::tab {{
    padding: 1px 8px;
    min-width: 40px;
    max-height: 18px;
    font-size: 11px;
    margin-right: 0px;
}}
QTabWidget#hexTabs QTabBar {{
    icon-size: 12px;
}}
QTabWidget#hexTabs::pane {{
    top: -1px;
    margin-top: 1px;
}}

/* ========== Panels ========== */
QFrame#panel {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#panelTitle {{
    color: {text};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {text_dim};
    font-size: 11px;
}}
QLabel#infoValue {{
    color: {text};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
QLabel#progressLabel {{
    color: {text_dim};
    font-size: 11px;
}}
QLabel#statusOk {{ color: {success}; font-weight: 600; font-size: 11px; }}
QLabel#statusErr {{ color: {danger}; font-weight: 600; font-size: 11px; }}
QLabel#statusWarn {{ color: {warning}; font-weight: 600; font-size: 11px; }}
QLabel#brandTitle {{
    color: {text};
    font-size: 18px;
    font-weight: 700;
    min-height: 22px;
}}

/* ========== Controls — compact ========== */
QPushButton {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 5px 12px;
    min-height: 18px;
    font-size: 12px;
}}
QPushButton:hover {{
    background: {bg_hover};
    border-color: {accent};
}}
QPushButton:pressed {{ background: {bg_panel}; }}
QPushButton:disabled {{
    color: {text_muted};
    background: {bg_panel};
    border-color: {border};
}}
QPushButton#accent {{
    background: {accent};
    color: {on_accent};
    border: none;
    font-weight: 600;
    padding: 7px 14px;
}}
QPushButton#accent:hover {{ background: {accent_hover}; }}
QPushButton#accent:disabled {{
    background: {bg_input};
    color: {text_muted};
}}
QToolButton#accentTool {{
    background: {accent};
    color: {on_accent};
    border: none;
    border-radius: 5px;
    padding: 5px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QToolButton#accentTool:hover {{ background: {accent_hover}; }}
QToolButton#accentTool:disabled {{
    background: {bg_input};
    color: {text_muted};
}}
QToolButton#accentTool::menu-button {{
    border-left: 1px solid rgba(0,0,0,0.2);
    width: 14px;
}}
QPushButton#danger {{
    background: transparent;
    color: {danger};
    border: 1px solid {danger};
    padding: 7px 14px;
}}
QPushButton#danger:hover {{ background: rgba(255, 92, 92, 0.12); }}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid {border};
    color: {text_dim};
    padding: 4px 8px;
}}
QPushButton#ghost:hover {{
    color: {text};
    border-color: {accent};
}}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {accent};
}}
QComboBox {{
    padding-right: 26px;
    min-width: 0;
}}
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: center right;
    border: none;
    background: transparent;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: url({arrow_url});
    width: 10px;
    height: 10px;
}}
QSpinBox, QDoubleSpinBox {{
    padding-right: 30px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    border: none;
    border-left: 1px solid {border};
    border-bottom: 1px solid {border};
    border-top-right-radius: 5px;
    background: {bg_hover};
    margin: 1px 1px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    border: none;
    border-left: 1px solid {border};
    border-bottom-right-radius: 5px;
    background: {bg_hover};
    margin: 0 1px 1px 0;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {accent};
    border-left-color: {accent};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {accent_hover};
}}
QSpinBox::up-button:disabled, QSpinBox::down-button:disabled,
QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled {{
    background: {bg_input};
    border-left-color: {border};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({spin_up_url});
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({spin_down_url});
    width: 9px;
    height: 9px;
}}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{
    opacity: 0.35;
}}
QComboBox QAbstractItemView,
QListView {{
    background-color: {bg_panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px;
    outline: none;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QComboBox QAbstractItemView::item,
QListView::item {{
    background-color: {bg_panel};
    color: {text};
    min-height: 24px;
    padding: 3px 6px;
    border-radius: 4px;
    margin: 1px 2px;
}}
QComboBox QAbstractItemView::item:selected,
QListView::item:selected {{
    background-color: {accent};
    color: {on_accent};
}}
QComboBox QAbstractScrollArea {{
    background: transparent;
    border: none;
}}

QCheckBox {{
    spacing: 6px;
    color: {text_dim};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {border};
    background: {bg_input};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}

QProgressBar {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 3px;
    text-align: center;
    color: {text};
    height: 8px;
    max-height: 10px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 2px;
}}

QPlainTextEdit#logView {{
    background: {log_bg};
    color: {text_dim};
    border: 1px solid {border};
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;
    font-size: 11px;
    padding: 6px;
}}

QTextBrowser, QTextEdit {{
    background: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {accent};
    selection-color: {on_accent};
    font-size: 12px;
}}
QTextBrowser a, QTextEdit a {{ color: {accent}; }}

QMessageBox {{
    background: {bg};
    color: {text};
}}
QMessageBox QLabel {{
    color: {text};
    background: transparent;
}}
QProgressDialog {{
    background: {bg};
    color: {text};
}}
QProgressDialog QLabel {{
    color: {text};
    background: transparent;
}}

/* ========== Scroll ========== */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea QWidget#qt_scrollarea_viewport {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: {bg};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {bg};
    height: 0;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ========== Chrome ========== */
QMenuBar {{
    background: {bg};
    color: {text};
    border-bottom: 1px solid {border};
    padding: 2px 6px;
    font-size: 12px;
}}
QMenuBar::item:selected {{
    background: {bg_hover};
    border-radius: 4px;
}}
QMenu {{
    background: {bg_panel};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {accent};
    color: {on_accent};
}}
QToolBar {{
    background: {bg};
    border: none;
    border-bottom: 1px solid {border};
    spacing: 6px;
    padding: 4px 8px;
}}
QToolButton {{
    background: transparent;
    color: {text_dim};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    color: {text};
    background: {bg_hover};
    border-color: {border};
}}
QStatusBar {{
    background: {bg};
    color: {text_dim};
    border-top: 1px solid {border};
    font-size: 11px;
}}
QStatusBar QLabel {{
    background: transparent;
    padding: 0 4px;
}}"""
