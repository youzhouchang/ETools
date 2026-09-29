"""Left tool rail + stacked pages (Program / Serial / Ethernet / Terminal)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from etools.config import get_config
from etools.i18n import tr
from etools.ui.icons import icon as load_icon
from etools.ui.icons import semantic_color, set_action_icon
from etools.ui.styles import Theme, get_theme
from etools.ui.widgets.icon_button import IconToolButton

#: Qt's QWIDGETSIZE_MAX — allow the collapsed strip to fill the rail column.
_QWIDGETSIZE_MAX = 16_777_215

#: Canonical tool order for the rail. Icon ids are dedicated shell glyphs.
TOOL_ORDER: list[tuple[str, str]] = [
    ("program", "tool-program"),
    ("serial", "tool-serial"),
    ("ethernet", "tool-ethernet"),
    ("terminal", "tool-terminal"),
    ("script", "tool-script"),
]

_RAIL_BTN = 48
_RAIL_GAP = 6
_RAIL_PAD = 16
#: Rail has exactly two widths — drag snaps between them (never free-resize).
_RAIL_W_COLLAPSED = 20
_RAIL_W_EXPANDED = 52


class _RailToggle(QToolButton):
    """Collapse/expand chevron that shares the tool-button visual language.

    Painted (not text) so it reads as one family with the icon rail, and
    adapts to the thin collapsed strip without looking like a foreign header.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("railCollapseBtn")
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._collapsed = False
        self._hover_bg: str | None = None
        self._fg = "#9AA3B2"
        self.setFixedSize(_RAIL_W_EXPANDED - 4, 36)

    def set_appearance(self, fg: str, hover_bg: str | None) -> None:
        self._fg = fg
        self._hover_bg = hover_bg
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        if self._collapsed:
            self.setFixedSize(_RAIL_W_COLLAPSED, 28)
        else:
            self.setFixedSize(_RAIL_W_EXPANDED - 4, 36)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        if self.underMouse() and self._hover_bg:
            inner = rect.adjusted(2, 2, -2, -2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._hover_bg))
            painter.drawRoundedRect(inner, 8, 8)

        # Chevron: ‹ when expanded (collapse next), › when collapsed (expand next).
        arm = 5 if self._collapsed else 6
        cx, cy = rect.center().x(), rect.center().y()
        pen = QPen(QColor(self._fg))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if self._collapsed:
            path.moveTo(cx - 2, cy - arm)
            path.lineTo(cx + 2, cy)
            path.lineTo(cx - 2, cy + arm)
        else:
            path.moveTo(cx + 2, cy - arm)
            path.lineTo(cx - 2, cy)
            path.lineTo(cx + 2, cy + arm)
        painter.drawPath(path)
        painter.end()


@dataclass(frozen=True)
class ToolActionSpec:
    """One toolbar action a tool page exposes to the shell."""

    key: str
    text_key: str
    icon_name: str
    slot: Callable[[], None]
    separator_before: bool = False


class ToolShell(QWidget):
    """Owns the activity rail, per-tool toolbars, and the page stack."""

    tool_changed = Signal(str)

    def __init__(
        self,
        pages: dict[str, QWidget],
        action_providers: dict[str, Callable[[], list[ToolActionSpec]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("shellHost")
        self._pages = pages
        self._action_providers = action_providers
        self._current_key = "program"
        self._rail_collapsed = False
        self._tool_buttons: dict[str, IconToolButton] = {}
        self._toolbars: dict[str, QToolBar] = {}
        self._icon_names: dict[str, str] = dict(TOOL_ORDER)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setObjectName("toolStack")
        self._key_order = [k for k, _ in TOOL_ORDER if k in pages]
        for key in self._key_order:
            page = pages[key]
            wrap = QWidget()
            wrap.setObjectName(f"page_{key}")
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            tb = self._make_toolbar(key)
            self._toolbars[key] = tb
            lay.addWidget(tb)
            lay.addWidget(page, 1)
            self._stack.addWidget(wrap)

        self._rail = QWidget()
        self._rail.setObjectName("toolRail")
        self._rail.setMinimumWidth(_RAIL_W_EXPANDED)
        self._rail.setMaximumWidth(_RAIL_W_EXPANDED)
        rail_lay = QVBoxLayout(self._rail)
        rail_lay.setContentsMargins(4, 8, 4, 8)
        rail_lay.setSpacing(_RAIL_GAP)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        theme = get_theme(get_config().theme)
        for i, (key, icon_name) in enumerate(TOOL_ORDER):
            if key not in pages:
                continue
            btn = IconToolButton()
            btn.setIconSize(QSize(28, 28))
            btn.set_backgrounds(theme.accent, theme.bg_hover)
            btn.setIcon(load_icon(icon_name, semantic_color(icon_name, theme), 28))
            self._group.addButton(btn, i)
            rail_lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            self._tool_buttons[key] = btn

        # Collapse control lives at the bottom of the icon column (same visual
        # family as the tool buttons) — not a detached header chip.
        self._pre_toggle_spacer = QSpacerItem(
            0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        self._post_toggle_spacer = QSpacerItem(
            0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        rail_lay.addSpacerItem(self._pre_toggle_spacer)
        self._collapse_btn = _RailToggle()
        self._collapse_btn.set_appearance(theme.text_dim, theme.bg_hover)
        self._collapse_btn.clicked.connect(self.toggle_rail)
        rail_lay.addWidget(self._collapse_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        rail_lay.addSpacerItem(self._post_toggle_spacer)
        self._update_rail_height()
        self._rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        self._rail.mouseDoubleClickEvent = self._on_rail_double_click  # type: ignore[method-assign]

        rail_box = QWidget()
        rail_box.setObjectName("toolRailBox")
        rail_box_lay = QVBoxLayout(rail_box)
        rail_box_lay.setContentsMargins(0, 0, 0, 0)
        rail_box_lay.setSpacing(0)
        rail_box_lay.addWidget(self._rail, 0, Qt.AlignmentFlag.AlignTop)
        rail_box_lay.addStretch(1)

        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.setCollapsible(0, True)
        self._split.setCollapsible(1, False)
        self._split.setHandleWidth(4)
        self._split.setOpaqueResize(True)
        self._split.addWidget(rail_box)
        self._split.addWidget(self._stack)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([52, 1000])
        self._split.splitterMoved.connect(self._on_splitter_moved)
        root.addWidget(self._split)

        self._group.idClicked.connect(self._on_id_clicked)
        for index, key in enumerate(self._key_order, start=1):
            shortcut = QAction(self)
            shortcut.setShortcut(QKeySequence(f"Ctrl+{index}"))
            shortcut.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.triggered.connect(lambda _checked=False, k=key: self.set_current_tool(k))
            self.addAction(shortcut)
        self.apply_language()
        self.refresh_rail_icons()
        if "program" in self._tool_buttons:
            self._tool_buttons["program"].setChecked(True)
        self.set_current_tool("program")

    # -- public API ----------------------------------------------------

    @property
    def current_tool(self) -> str:
        return self._current_key

    @property
    def tool_keys(self) -> list[str]:
        return list(self._key_order)

    @property
    def tool_buttons(self) -> dict[str, IconToolButton]:
        return self._tool_buttons

    @property
    def toolbars(self) -> dict[str, QToolBar]:
        return self._toolbars

    @property
    def stack(self) -> QStackedWidget:
        return self._stack

    def set_current_tool(self, key: str) -> None:
        if key not in self._pages:
            key = self._key_order[0] if self._key_order else key
            if key not in self._pages:
                return
        idx = self._key_order.index(key)
        self._stack.setCurrentIndex(idx)
        self._current_key = key
        btn = self._tool_buttons.get(key)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self.refresh_rail_icons()
        self.tool_changed.emit(key)

    def apply_language(self) -> None:
        for key, btn in self._tool_buttons.items():
            tip = tr(f"tool.{key}_tip")
            btn.setText("")
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
        self._collapse_btn.setToolTip(
            tr("tool.rail_expand") if self._rail_collapsed else tr("tool.rail_collapse")
        )
        self._collapse_btn.setAccessibleName(self._collapse_btn.toolTip())
        for key, tb in self._toolbars.items():
            tb.setWindowTitle(tr(f"tool.{key}"))
            self._rebuild_toolbar(key)

    def refresh_rail_icons(self, theme: Theme | None = None) -> None:
        t = theme or get_theme(get_config().theme)
        for key, btn in self._tool_buttons.items():
            icon_name = self._icon_names.get(key)
            if not icon_name:
                continue
            color = t.on_accent if btn.isChecked() else semantic_color(icon_name, t)
            btn.setIcon(load_icon(icon_name, color, 28))
            btn.set_backgrounds(t.accent, t.bg_hover)
            btn.update()
        self._collapse_btn.set_appearance(t.text_dim, t.bg_hover)

    def toggle_rail(self) -> None:
        self.set_rail_collapsed(not self._rail_collapsed)

    def set_rail_collapsed(self, collapsed: bool) -> None:
        """Two-state rail: expanded ↔ collapsed. Never free width."""
        collapsed = bool(collapsed)
        self._rail_collapsed = collapsed
        width = _RAIL_W_COLLAPSED if collapsed else _RAIL_W_EXPANDED
        for btn in self._tool_buttons.values():
            btn.setVisible(not collapsed)
        self._collapse_btn.set_collapsed(collapsed)
        self._rail.setMinimumWidth(width)
        self._rail.setMaximumWidth(width)
        # Keep the chevron at the same Y as the expanded icon stack's bottom
        # edge so collapse does not make the control jump.
        tools_span = (
            len(self._tool_buttons) * _RAIL_BTN
            + max(1, len(self._tool_buttons)) * _RAIL_GAP
        )
        if collapsed:
            self._pre_toggle_spacer.changeSize(
                0, tools_span, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            self._post_toggle_spacer.changeSize(
                0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
            )
            self._rail.setMaximumHeight(_QWIDGETSIZE_MAX)
        else:
            self._pre_toggle_spacer.changeSize(
                0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
            )
            self._post_toggle_spacer.changeSize(
                0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
            )
            self._update_rail_height()
        self._rail.layout().invalidate()
        self._rail.layout().activate()
        self._split.blockSignals(True)
        self._split.setSizes([width, max(200, self._split.width() - width)])
        self._split.blockSignals(False)
        tip = tr("tool.rail_expand") if collapsed else tr("tool.rail_collapse")
        self._rail.setToolTip(tip)
        self._collapse_btn.setToolTip(tip)
        self._collapse_btn.setAccessibleName(tip)

    def shutdown(self) -> None:
        for page in self._pages.values():
            if hasattr(page, "shutdown"):
                try:
                    page.shutdown()
                except Exception:  # noqa: BLE001
                    pass

    # -- internals -----------------------------------------------------

    def _update_rail_height(self) -> None:
        n = max(1, len(self._tool_buttons))
        # tools + bottom toggle + gaps + vertical padding
        self._rail.setMaximumHeight(n * _RAIL_BTN + 36 + (n + 3) * _RAIL_GAP + _RAIL_PAD)

    def _on_rail_double_click(self, event) -> None:
        self.toggle_rail()
        event.accept()

    def _on_splitter_moved(self, pos: int, _index: int) -> None:
        """Drag left → hide, drag right → expand; always snap to two widths."""
        mid = (_RAIL_W_COLLAPSED + _RAIL_W_EXPANDED) // 2
        self.set_rail_collapsed(int(pos) <= mid)

    def _on_id_clicked(self, index: int) -> None:
        if 0 <= index < len(self._key_order):
            self.set_current_tool(self._key_order[index])

    def _make_toolbar(self, key: str) -> QToolBar:
        tb = QToolBar(tr(f"tool.{key}"), self)
        tb.setObjectName(f"toolbar_{key}")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(18, 18))
        tb.setFixedHeight(40)
        self._rebuild_toolbar(key)
        return tb

    def _rebuild_toolbar(self, key: str) -> None:
        tb = self._toolbars.get(key)
        if tb is None:
            return
        tb.clear()
        provider = self._action_providers.get(key)
        if provider is None:
            return
        for spec in provider():
            if spec.separator_before:
                tb.addSeparator()
            action = QAction(tr(spec.text_key), self)
            set_action_icon(action, spec.icon_name, 18)
            action.triggered.connect(spec.slot)
            tb.addAction(action)
