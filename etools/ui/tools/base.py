"""Common shell for a tool page (context + main work area)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


def _form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(8)
    return form


class ToolPage(QWidget):
    """Vertical tool: left context rail + main work area, split like Program."""

    tool_id = "tool"
    tool_title = ""
    tool_title_key = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"toolPage_{self.tool_id}")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self._left_width = 260
        self.splitter.splitterMoved.connect(self._on_left_split_moved)

        self.ctx_host = QWidget()
        self.ctx_layout = QVBoxLayout(self.ctx_host)
        self.ctx_layout.setContentsMargins(0, 0, 0, 0)
        self.ctx_layout.setSpacing(10)

        self._active_form: QFormLayout | None = None

        self.main_host = QWidget()
        self.main_layout = QVBoxLayout(self.main_host)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setObjectName(f"toolCtxScroll_{self.tool_id}")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.ctx_host)

        self.splitter.addWidget(scroll)
        self.splitter.addWidget(self.main_host)
        self.splitter.setSizes([self._left_width, 720])
        root.addWidget(self.splitter)

        self._build()

    def set_left_width(self, width: int) -> None:
        """Pin the left context pane width (window resize won't change it)."""
        self._left_width = max(180, int(width))
        self._apply_left_width()

    def _apply_left_width(self) -> None:
        left = self.splitter.widget(0)
        if left is None:
            return
        w = self._left_width
        left.setMinimumWidth(w)
        left.setMaximumWidth(w)
        total = self.splitter.width() or (w + 720)
        self.splitter.blockSignals(True)
        self.splitter.setSizes([w, max(200, total - w)])
        self.splitter.blockSignals(False)

    def _on_left_split_moved(self, pos: int, _index: int) -> None:
        if abs(int(pos) - self._left_width) <= 2:
            return
        self._left_width = max(180, int(pos))
        self._apply_left_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_left_width()

    def _build(self) -> None:
        """Subclass populates ctx_layout / main_layout."""

    # -- shell-facing public API ---------------------------------------

    def toolbar_actions(self) -> list:
        """Return list[ToolActionSpec] for the shared shell toolbar."""
        return []

    def retranslate(self) -> None:
        """Refresh all user-visible strings after a language switch."""

    def shutdown(self) -> None:
        """Release background threads / sockets on window close."""

    def toggle_connection(self) -> None:
        """Open/close the tool's primary connection (toolbar default)."""

    def send(self) -> None:
        """Send the current input, if the tool has a send action."""

    def clear_view(self) -> None:
        """Clear the tool's monitor / log view."""

    def ctx_group(self, title: str) -> QGroupBox:
        """Framed group on the left; stretches so its bottom matches the main group."""
        box = QGroupBox(title)
        box.setObjectName("ctxGroup")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(8, 10, 8, 8)
        outer.setSpacing(8)
        form = _form_layout()
        outer.addLayout(form)
        self._active_form = form
        self._active_group_layout = outer
        self.ctx_layout.addWidget(box, 1)
        return box

    def main_group(self, title: str) -> QGroupBox:
        """Framed group on the main work area (with vertical layout)."""
        box = QGroupBox(title)
        box.setObjectName("mainGroup")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(6)
        self.main_layout.addWidget(box, 1)
        return box

    def form_row(self, label: str, field: QWidget, *, key: str | None = None) -> QLabel:
        """Add a right-aligned label + field to the active group form."""
        form = self._active_form
        if form is None:
            form = _form_layout()
            holder = QWidget()
            holder.setLayout(form)
            self.ctx_layout.addWidget(holder)
            self._active_form = form
        if isinstance(field, QWidget):
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lab = QLabel(label)
        if key:
            lab.setProperty("i18nKey", key)
        form.addRow(lab, field)
        return lab

    def ctx_action(self, widget: QWidget) -> None:
        """Put a button inside the current left group, right under the form."""
        lay = getattr(self, "_active_group_layout", None)
        if lay is not None:
            lay.addWidget(widget)
            # Keep button next to fields; empty space stays below
            lay.addStretch(1)
        else:
            self.ctx_layout.addWidget(widget)

    def _hint(self, parent_layout: QLayout, text: str) -> None:
        lab = QLabel(text)
        lab.setObjectName("hint")
        lab.setWordWrap(True)
        if isinstance(parent_layout, QVBoxLayout):
            parent_layout.addWidget(lab)
        else:
            self.ctx_layout.addWidget(lab)
