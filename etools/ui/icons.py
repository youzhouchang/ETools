"""Theme-aware SVG icon loader for ETools UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QTabWidget

from etools.ui.styles import Theme, get_theme

ICON_DIR = Path(__file__).resolve().parent / "resources" / "icons"

ICON_PROP = "etoolsIconName"
ICON_SIZE_PROP = "etoolsIconSize"
ICON_COLOR_PROP = "etoolsIconColor"

# Semantic tint by icon id. Role names resolve against Theme.
_SEMANTIC_ROLE: dict[str, str] = {
    "open": "accent",
    "program": "accent",
    "erase": "danger",
    "verify": "success",
    "reset": "warning",
    "read": "accent",
    "hex": "accent",
    "chip": "accent",
    "probe": "accent",
    "connect": "success",
    "disconnect": "danger",
    "scan": "accent",
    "devices": "accent",
    "refresh": "accent",
    "info": "accent",
    "about": "accent",
    "rtt": "accent",
    "swv": "success",
    "memory": "accent",
    "save": "accent",
    "fill": "warning",
    "blank": "success",
    "compare": "accent",
    "clear": "danger",
    "theme-dark": "accent",
    "theme-light": "warning",
    "language": "accent",
    "success": "success",
    "warning": "warning",
    "error": "danger",
    "power": "warning",
    "pause": "warning",
    "stop": "danger",
    "quit": "danger",
}

_cache: dict[tuple[str, str, int], QPixmap] = {}
_logo_cache: QIcon | None = None


def current_theme() -> Theme:
    from etools.config import get_config

    return get_theme(get_config().theme)


def _as_theme(theme: Theme | str | None) -> Theme:
    if theme is None:
        return current_theme()
    if isinstance(theme, Theme):
        return theme
    return get_theme(theme)


def icon_names() -> list[str]:
    return sorted(
        p.stem for p in ICON_DIR.glob("*.svg") if not p.stem.startswith("logo")
    )


def _svg_source(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"icon not found: {name}")
    return path.read_text(encoding="utf-8")


def _role_color(role: str, theme: Theme) -> str:
    if role == "accent":
        return theme.accent
    if role == "danger":
        return theme.danger
    if role == "success":
        return theme.success
    if role == "warning":
        return theme.warning
    if role == "on_accent":
        return theme.on_accent
    return theme.text_dim


def semantic_color(name: str, theme: Theme, override_role: str | None = None) -> str:
    """Resolve stroke color for an icon id under a theme."""
    if override_role and override_role != "dim":
        return _role_color(override_role, theme)
    role = _SEMANTIC_ROLE.get(name)
    if role:
        return _role_color(role, theme)
    return theme.text_dim


def pixmap(name: str, color: str | None = None, size: int = 24) -> QPixmap:
    """Render an icon SVG to a pixmap, tinting `currentColor` with `color`."""
    tint = color or "#E6EAF0"
    key = (name, tint.lower(), size)
    cached = _cache.get(key)
    if cached is not None and not cached.isNull():
        return cached

    svg = _svg_source(name).replace("currentColor", tint)

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()

    pm = QPixmap.fromImage(img)
    _cache[key] = pm
    return pm


def icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    return QIcon(pixmap(name, color, size))


def themed_icon(name: str, size: int = 24, theme: Theme | str | None = None) -> QIcon:
    t = _as_theme(theme)
    return icon(name, semantic_color(name, t), size)


def _render_logo(size: int) -> QPixmap | None:
    path = ICON_DIR / "logo.svg"
    if not path.exists():
        return None
    svg = path.read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return QPixmap.fromImage(img)


def app_icon() -> QIcon:
    """Multi-size application / window icon from logo.svg."""
    global _logo_cache
    if _logo_cache is not None:
        return _logo_cache

    result = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = _render_logo(s)
        if pm is not None and not pm.isNull():
            result.addPixmap(pm)
    _logo_cache = result
    return result


def clear_cache() -> None:
    global _logo_cache
    _cache.clear()
    _logo_cache = None


def widget_icon_color(widget, theme: Theme) -> str:
    """Pick stroke color for a control based on its objectName role."""
    name = widget.objectName() if widget is not None else ""
    if name == "accent":
        return theme.on_accent
    if name == "danger":
        return theme.danger
    icon_id = widget.property(ICON_PROP) if widget is not None else None
    if icon_id:
        return semantic_color(str(icon_id), theme)
    return theme.text_dim


def set_button_icon(
    btn, name: str, size: int = 16, theme: Theme | str | None = None
) -> None:
    """Bind a themed icon onto a button and remember it for theme switches."""
    t = _as_theme(theme)
    btn.setProperty(ICON_PROP, name)
    btn.setProperty(ICON_SIZE_PROP, size)
    color = widget_icon_color(btn, t)
    btn.setIcon(icon(name, color, size))


def set_action_icon(
    action, name: str, size: int = 18, role: str = "semantic"
) -> None:
    """role: semantic | dim | accent | danger | success | warning | on_accent."""
    t = _as_theme(None)
    color = semantic_color(name, t, None if role == "semantic" else role)
    action.setIcon(icon(name, color, size))
    action.setProperty(ICON_PROP, name)
    action.setProperty(ICON_SIZE_PROP, size)
    action.setProperty(ICON_COLOR_PROP, role)


def set_tab_icon(
    tabs: QTabWidget, index: int, name: str, color: str | None = None
) -> None:
    t = _as_theme(None)
    c = color or semantic_color(name, t)
    tabs.setTabIcon(index, icon(name, c, 14))
    tabs.tabBar().setTabData(index, name)


def refresh_icons(root, theme: Theme | str | None = None) -> None:
    """Re-apply icons on every widget that has etoolsIconName set under `root`."""
    if root is None:
        return

    t = _as_theme(theme)
    clear_cache()

    for action in root.findChildren(QAction):
        name = action.property(ICON_PROP)
        if not name:
            continue
        size = int(action.property(ICON_SIZE_PROP) or 18)
        role = str(action.property(ICON_COLOR_PROP) or "semantic")
        color = semantic_color(str(name), t, None if role == "semantic" else role)
        action.setIcon(icon(str(name), color, size))

    for btn in root.findChildren(QAbstractButton):
        name = btn.property(ICON_PROP)
        if not name:
            continue
        size = int(btn.property(ICON_SIZE_PROP) or 16)
        color = widget_icon_color(btn, t)
        btn.setIcon(icon(str(name), color, size))

    for tabs in root.findChildren(QTabWidget):
        for i in range(tabs.count()):
            name = tabs.tabBar().tabData(i)
            if isinstance(name, str) and name:
                tabs.setTabIcon(i, icon(name, semantic_color(name, t), 14))
