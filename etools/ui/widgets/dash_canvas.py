"""Snap-to-grid dashboard board.

Widgets are dragged from :class:`DashPalette` or by their title bar. While the
pointer is down the card follows it; on release the rectangle snaps to the grid.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMenu,
    QPushButton,
    QWidget,
)

from etools.core.dashboard import (
    CELL_HEIGHT,
    GRID_COLUMNS,
    MAX_ROW_SPAN,
    DashWidget,
    ensure_layout,
    fits,
    new_widget,
    try_move,
    try_resize,
)
from etools.i18n import tr
from etools.ui.widgets.dashboard_cards import DashCard

MIME = "application/x-etools-dash"
INSET = 6
MIN_CARD_W = 96
MIN_CARD_H = 72


def _set_drag_pixmap(drag: QDrag, widget: QWidget) -> None:
    """Carry a translucent snapshot of the dragged widget under the cursor.

    The default QDrag has no visible pixmap on this platform, so a drag in
    progress looked like nothing was happening until the cursor crossed a
    drop target.
    """
    pixmap = widget.grab()
    if pixmap.isNull():
        return
    faded = QPixmap(pixmap.size())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.8)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    drag.setPixmap(faded)
    drag.setHotSpot(widget.rect().center())


class _Chip(QPushButton):
    """Palette button. A short drag starts a drop; a click appends a widget."""

    add_requested = Signal(str, str)

    def __init__(self, kind: str, shape: str, text: str) -> None:
        super().__init__(text)
        self.kind = kind
        self.shape = shape
        self.setObjectName("ghost")
        self.setFixedHeight(28)
        self._origin: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.position().toPoint() - self._origin
        if delta.manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._origin = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, f"new|{self.kind}|{self.shape}".encode())
        drag.setMimeData(mime)
        _set_drag_pixmap(drag, self)
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._origin is not None and event.button() == Qt.MouseButton.LeftButton:
            self.add_requested.emit(self.kind, self.shape)
        self._origin = None


class DashPalette(QWidget):
    """Draggable widget kinds. ``entries`` are ``(kind, shape, i18n key)``."""

    add_requested = Signal(str, str)

    def __init__(self, entries: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chips: list[tuple[_Chip, str]] = []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for index, (kind, shape, key) in enumerate(entries):
            chip = _Chip(kind, shape, tr(key))
            chip.setToolTip(tr("dash.drag_hint"))
            chip.add_requested.connect(self.add_requested)
            grid.addWidget(chip, index // 2, index % 2)
            self._chips.append((chip, key))

    def retranslate(self) -> None:
        for chip, key in self._chips:
            chip.setText(tr(key))
            chip.setToolTip(tr("dash.drag_hint"))


class DashCanvas(QWidget):
    """Grid of :class:`DashCard`. Mutates the widget list it was given."""

    selected = Signal(int)
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[DashWidget] = []
        self._cards: list[DashCard] = []
        self._press: QPoint | None = None
        self._press_card: DashCard | None = None
        self._moving: DashCard | None = None
        self._move_offset = QPoint()
        self._pending_cell: tuple[int, int] | None = None
        self._resizing: DashCard | None = None
        self._resize_span: tuple[int, int] | None = None
        self._resize_press: QPoint | None = None
        self._resize_start = (0, 0)
        self._grabbed: QWidget | None = None
        self.setAcceptDrops(True)
        self.setObjectName("dashBoard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(CELL_HEIGHT * 8)
        self._notice = QLabel(tr("dash.empty"), self)
        self._notice.setObjectName("hint")
        self._notice.setWordWrap(True)
        self._hint = QWidget(self)
        self._hint.setObjectName("dashDropHint")
        self._hint.hide()
        self._selected_index = -1

    @property
    def cards(self) -> list[DashCard]:
        return self._cards

    @property
    def notice(self) -> QLabel:
        return self._notice

    def set_items(self, items: list[DashWidget]) -> None:
        self._items = items
        ensure_layout(items)
        self._selected_index = -1
        self._rebuild_cards()

    def highlight(self, index: int) -> None:
        """Mark one card as selected. Called by the field table and by clicks here."""
        self._selected_index = index
        for position, card in enumerate(self._cards):
            card.set_selected(position == index)

    def add_widget(self, kind: str, shape: str, row: int = -1, col: int = -1) -> bool:
        spec = new_widget(kind, shape)
        if row >= 0 and not fits(self._items, spec, row, col, spec.row_span, spec.col_span):
            return False
        if row >= 0:
            spec.row = row
            spec.col = col
        self._items.append(spec)
        ensure_layout(self._items)
        self._rebuild_cards()
        self.changed.emit()
        return True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.relayout()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        self._preview(event, event.position().toPoint())

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self._preview(event, event.position().toPoint())

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._hint.hide()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._finish(event, event.position().toPoint())

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        card = self._card_for(watched)
        if card is None:
            return False
        kind = event.type()
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            pos = self.mapFromGlobal(watched.mapToGlobal(event.position().toPoint()))
            self._preview(event, pos)
            return True
        if kind == QEvent.Type.Drop:
            pos = self.mapFromGlobal(watched.mapToGlobal(event.position().toPoint()))
            self._finish(event, pos)
            return True
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
            self._delete_menu(card, event.globalPosition().toPoint())
            return True
        if watched is card.grip:
            return self._grip_event(card, event)
        if watched is card.caption:
            return self._caption_event(card, event)
        return False

    def relayout(self) -> None:
        rows = 1
        bottom = 0
        for card in self._cards:
            spec = card.spec
            rows = max(rows, spec.row + spec.row_span)
            if card is self._resizing or card is self._moving:
                bottom = max(bottom, card.y() + card.height())
                continue
            card.setGeometry(*self._rect(spec.row, spec.col, spec.row_span, spec.col_span))
            bottom = max(bottom, card.geometry().bottom())
        height = max(rows * CELL_HEIGHT, bottom + INSET)
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
        if self._cards:
            self._notice.hide()
        else:
            self._notice.setGeometry(12, 12, max(40, self.width() - 24), 48)
            self._notice.show()
            self._notice.raise_()

    def _rebuild_cards(self) -> None:
        self._release_grab()
        self._resizing = None
        self._moving = None
        for card in self._cards:
            card.hide()
            card.deleteLater()
        self._cards = []
        self._hint.hide()
        for spec in self._items:
            card = DashCard(spec, self)
            card.caption.setCursor(Qt.CursorShape.OpenHandCursor)
            card.setAcceptDrops(True)
            card.installEventFilter(self)
            for child in card.findChildren(QWidget):
                child.installEventFilter(self)
            card.show()
            self._cards.append(card)
        if 0 <= self._selected_index < len(self._cards):
            self.highlight(self._selected_index)
        self.relayout()

    def _card_for(self, watched) -> DashCard | None:
        widget = watched if isinstance(watched, QWidget) else None
        while widget is not None and widget is not self:
            if isinstance(widget, DashCard):
                return widget
            widget = widget.parentWidget()
        return None

    def _index_of(self, card: DashCard) -> int:
        for index, item in enumerate(self._items):
            if item is card.spec:
                return index
        return -1

    def _col_width(self) -> int:
        return max(1, self.width() // GRID_COLUMNS)

    def _rect(self, row: int, col: int, row_span: int, col_span: int) -> tuple[int, int, int, int]:
        col_w = self._col_width()
        return (
            col * col_w + INSET,
            row * CELL_HEIGHT + INSET,
            max(40, col_span * col_w - INSET * 2),
            max(40, row_span * CELL_HEIGHT - INSET * 2),
        )

    def _cell_at(self, pos: QPoint) -> tuple[int, int]:
        col_w = self._col_width()
        col = max(0, min(GRID_COLUMNS - 1, pos.x() // col_w))
        row = max(0, pos.y() // CELL_HEIGHT)
        return row, col

    def _min_span(self) -> tuple[int, int]:
        """Smallest span that still leaves the title and the resize handle usable."""
        col_w = self._col_width()
        min_cols = max(1, (MIN_CARD_W + INSET * 2 + col_w - 1) // col_w)
        min_rows = max(1, (MIN_CARD_H + INSET * 2 + CELL_HEIGHT - 1) // CELL_HEIGHT)
        return min_rows, min_cols

    def _parse(self, mime: QMimeData) -> tuple[str, ...] | None:
        if not mime.hasFormat(MIME):
            return None
        parts = bytes(mime.data(MIME)).decode().split("|")
        if parts[0] == "move" and len(parts) == 2 and parts[1].isdigit():
            return tuple(parts)
        if parts[0] == "new" and len(parts) == 3:
            return tuple(parts)
        return None

    def _span_for(self, parsed: tuple[str, ...]) -> tuple[int, int]:
        if parsed[0] == "move":
            index = int(parsed[1])
            if 0 <= index < len(self._items):
                spec = self._items[index]
                return spec.row_span, spec.col_span
            return 1, 1
        spec = new_widget(parsed[1], parsed[2])
        return spec.row_span, spec.col_span

    def _can_place(self, parsed: tuple[str, ...], row: int, col: int) -> bool:
        row_span, col_span = self._span_for(parsed)
        if parsed[0] == "move":
            index = int(parsed[1])
            if not 0 <= index < len(self._items):
                return False
            spec = self._items[index]
            return fits(self._items, spec, row, col, row_span, col_span)
        spec = new_widget(parsed[1], parsed[2])
        return fits(self._items, spec, row, col, spec.row_span, spec.col_span)

    def _preview(self, event, pos: QPoint) -> None:
        parsed = self._parse(event.mimeData())
        if parsed is None:
            event.ignore()
            return
        row, col = self._cell_at(pos)
        row_span, col_span = self._span_for(parsed)
        ok = self._can_place(parsed, row, col)
        self._show_hint(row, col, row_span, col_span, ok)
        if ok:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _finish(self, event, pos: QPoint) -> None:
        parsed = self._parse(event.mimeData())
        self._hint.hide()
        if parsed is None:
            event.ignore()
            return
        row, col = self._cell_at(pos)
        if not self._can_place(parsed, row, col):
            event.ignore()
            return
        if parsed[0] == "move":
            spec = self._items[int(parsed[1])]
            before = (spec.row, spec.col)
            if try_move(self._items, spec, row, col) and (spec.row, spec.col) != before:
                self.relayout()
                self.changed.emit()
        else:
            self.add_widget(parsed[1], parsed[2], row, col)
        event.acceptProposedAction()

    def _show_hint(self, row: int, col: int, row_span: int, col_span: int, ok: bool) -> None:
        self._hint.setGeometry(*self._rect(row, col, row_span, col_span))
        color = "rgba(59, 158, 255, 56)" if ok else "rgba(255, 90, 54, 64)"
        border = "rgba(59, 158, 255, 200)" if ok else "rgba(255, 90, 54, 200)"
        self._hint.setStyleSheet(f"background: {color}; border: 1px solid {border};")
        self._hint.show()
        self._hint.raise_()

    def _caption_event(self, card: DashCard, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._press_card = card
            self._moving = None
            index = self._index_of(card)
            if index >= 0:
                self.highlight(index)
                self.selected.emit(index)
            return True
        if (
            kind == QEvent.Type.MouseMove
            and self._press_card is card
            and self._press is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            global_pos = event.globalPosition().toPoint()
            if self._moving is None:
                if (global_pos - self._press).manhattanLength() < QApplication.startDragDistance():
                    return True
                local = self.mapFromGlobal(global_pos)
                self._move_offset = local - card.pos()
                self._moving = card
                self._grab(card.caption)
                card.caption.setCursor(Qt.CursorShape.ClosedHandCursor)
                card.raise_()
            self._follow_move(card, global_pos)
            return True
        if kind == QEvent.Type.MouseButtonRelease and (
            self._moving is card or self._press_card is card
        ):
            moved = self._moving is card
            self._release_grab()
            card.caption.setCursor(Qt.CursorShape.OpenHandCursor)
            self._moving = None
            self._press_card = None
            self._press = None
            self._hint.hide()
            if moved:
                self._commit_move(card)
            return True
        return False

    def _follow_move(self, card: DashCard, global_pos: QPoint) -> None:
        local = self.mapFromGlobal(global_pos)
        origin = local - self._move_offset
        origin.setX(max(0, origin.x()))
        origin.setY(max(0, origin.y()))
        card.move(origin)
        card.raise_()
        row, col = self._snap_origin(card)
        spec = card.spec
        ok = fits(self._items, spec, row, col, spec.row_span, spec.col_span)
        self._pending_cell = (row, col) if ok else None
        self._show_hint(row, col, spec.row_span, spec.col_span, ok)
        self._grow_to(card.y() + card.height())

    def _snap_origin(self, card: DashCard) -> tuple[int, int]:
        spec = card.spec
        col = int(round(card.x() / self._col_width()))
        row = int(round(card.y() / CELL_HEIGHT))
        col = max(0, min(GRID_COLUMNS - spec.col_span, col))
        return max(0, row), col

    def _commit_move(self, card: DashCard) -> None:
        pending = self._pending_cell
        self._pending_cell = None
        spec = card.spec
        before = (spec.row, spec.col)
        moved = False
        if pending is not None:
            row, col = pending
            moved = try_move(self._items, spec, row, col) and (spec.row, spec.col) != before
        self.relayout()
        if moved:
            self.changed.emit()

    def _grip_event(self, card: DashCard, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._resizing = card
            self._resize_press = event.globalPosition().toPoint()
            self._resize_start = (card.width(), card.height())
            self._resize_span = (card.spec.row_span, card.spec.col_span)
            self._grab(card.grip)
            return True
        if (
            kind == QEvent.Type.MouseMove
            and self._resizing is card
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            self._follow_resize(card, event.globalPosition().toPoint())
            return True
        if kind == QEvent.Type.MouseButtonRelease and self._resizing is card:
            span = self._resize_span
            self._resizing = None
            self._resize_span = None
            self._resize_press = None
            self._release_grab()
            self._hint.hide()
            spec = card.spec
            before = (spec.row_span, spec.col_span)
            changed = False
            if span is not None and try_resize(self._items, spec, span[0], span[1]):
                changed = (spec.row_span, spec.col_span) != before
            self.relayout()
            if changed:
                self.changed.emit()
            return True
        return False

    def _follow_resize(self, card: DashCard, global_pos: QPoint) -> None:
        """Grow the card with the pointer. The handle sits inside the corner, so size is a delta."""
        if self._resize_press is None:
            return
        spec = card.spec
        delta = global_pos - self._resize_press
        col_w = self._col_width()
        left = spec.col * col_w + INSET
        top = spec.row * CELL_HEIGHT + INSET
        max_w = max(MIN_CARD_W, (GRID_COLUMNS - spec.col) * col_w - INSET * 2)
        max_h = max(MIN_CARD_H, MAX_ROW_SPAN * CELL_HEIGHT - INSET * 2)
        width = int(max(MIN_CARD_W, min(max_w, self._resize_start[0] + delta.x())))
        height = int(max(MIN_CARD_H, min(max_h, self._resize_start[1] + delta.y())))
        card.setGeometry(left, top, width, height)
        card.raise_()
        row_span, col_span = self._span_for_size(card, width, height)
        ok = fits(self._items, spec, spec.row, spec.col, row_span, col_span)
        if ok:
            self._resize_span = (row_span, col_span)
        self._show_hint(spec.row, spec.col, row_span, col_span, ok)
        self._grow_to(top + height)

    def _span_for_size(self, card: DashCard, width: int, height: int) -> tuple[int, int]:
        """Span of the rectangle that contains this pixel size, rounded to the nearest cell."""
        spec = card.spec
        col_w = self._col_width()
        min_rows, min_cols = self._min_span()
        right = spec.col * col_w + width + INSET * 2
        bottom = spec.row * CELL_HEIGHT + height + INSET * 2
        row_span = int(round((bottom - spec.row * CELL_HEIGHT) / CELL_HEIGHT))
        col_span = int(round((right - spec.col * col_w) / col_w))
        max_cols = max(1, GRID_COLUMNS - spec.col)
        row_span = max(1, min(MAX_ROW_SPAN, row_span))
        col_span = max(1, min(max_cols, col_span))
        if row_span < min_rows:
            row_span = min(min_rows, MAX_ROW_SPAN)
        if col_span < min_cols:
            col_span = min(min_cols, max_cols)
        return row_span, col_span

    def _grow_to(self, bottom: int) -> None:
        height = bottom + INSET
        if height > self.minimumHeight():
            self.setMinimumHeight(height)

    def _grab(self, widget: QWidget) -> None:
        if self._grabbed is not None and self._grabbed is not widget:
            self._grabbed.releaseMouse()
        widget.grabMouse()
        self._grabbed = widget

    def _release_grab(self) -> None:
        if self._grabbed is not None:
            self._grabbed.releaseMouse()
            self._grabbed = None

    def _delete_menu(self, card: DashCard, global_pos: QPoint) -> None:
        index = self._index_of(card)
        if index < 0:
            return
        menu = QMenu(self)
        menu.addAction(tr("dash.remove"))
        if menu.exec(global_pos) is None:
            return
        del self._items[index]
        self._rebuild_cards()
        self.changed.emit()
        self.selected.emit(-1)


__all__ = ["DashCanvas", "DashPalette", "MIME"]
