"""Common shell for a tool page (context + main work area)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
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

_LEFT_MIN = 180
_LEFT_MAX = 520


def _form_layout() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(8)
    return form


class ToolPage(QWidget):
    """Vertical tool: left context rail + main work area, split like Program."""

    state_changed = Signal()

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
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self._left_width, 720])
        root.addWidget(self.splitter)

        self._build()
        self._watch_button_state()

    def notify_state(self) -> None:
        """Tell the shell that connection, busy, or button state changed."""
        self.state_changed.emit()

    def _watch_button_state(self) -> None:
        for button in self.findChildren(QAbstractButton):
            button.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.EnabledChange and isinstance(watched, QAbstractButton):
            self.notify_state()
        return super().eventFilter(watched, event)

    def set_left_width(self, width: int) -> None:
        """Set default left width. Window resize keeps it; user may still drag."""
        self._left_width = max(_LEFT_MIN, min(int(width), _LEFT_MAX))
        self._restore_left_width()

    def _restore_left_width(self) -> None:
        """Re-apply remembered left width (window resize path)."""
        left = self.splitter.widget(0)
        if left is None:
            return
        w = self._left_width
        # Soft bounds only — allow manual drag within [_LEFT_MIN, _LEFT_MAX].
        left.setMinimumWidth(_LEFT_MIN)
        left.setMaximumWidth(_LEFT_MAX)
        total = self.splitter.width() or (w + 720)
        self.splitter.blockSignals(True)
        self.splitter.setSizes([w, max(200, total - w)])
        self.splitter.blockSignals(False)

    def _on_left_split_moved(self, pos: int, _index: int) -> None:
        """User dragged the handle — accept and remember the new width."""
        self._left_width = max(_LEFT_MIN, min(int(pos), _LEFT_MAX))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._restore_left_width()

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

    def can_close(self) -> bool:
        return True

    def persist_prefs(self) -> None:
        """Persist this tool's UI preferences (shell / project capture)."""

    @property
    def left_width(self) -> int:
        return int(self._left_width)

    @property
    def runner(self):
        """Background OpRunner if the page owns one, else None."""
        return getattr(self, "_runner", None)

    @property
    def busy(self) -> bool:
        runner = self.runner
        svc = getattr(self, "svc", None)
        return bool((runner is not None and runner.busy) or (svc is not None and svc.running))

    def install_send_preview(self, layout) -> None:
        self.send_preview = QLabel()
        self.send_preview.setObjectName("mutedLabel")
        self.send_preview.setWordWrap(True)
        self.send_preview.setMinimumHeight(18)
        self.send_preview.setContentsMargins(0, 2, 0, 0)
        layout.addSpacing(4)
        layout.addWidget(self.send_preview)
        self.send_edit.textChanged.connect(self._update_send_preview)
        for name in ("mode_combo", "ending", "encoding", "checksum", "peer_combo"):
            control = getattr(self, name, None)
            if control is not None:
                control.currentIndexChanged.connect(self._update_send_preview)
        self._update_send_preview()

    def _update_send_preview(self, *_args) -> None:
        from etools.i18n import tr

        text = self.send_edit.text()
        if not text:
            self.send_preview.clear()
            self.send_edit.setToolTip("")
            return
        try:
            from etools.ui.tools.link_controller import LinkController

            mode = str(self.mode_combo.currentData())
            checksum = getattr(self, "checksum", None)
            ending = str(self.ending.currentData() or "none")
            data = LinkController.encode_payload(
                text,
                mode=mode,
                encoding=self._encoding_name(),
                ending=ending,
                checksum=str(checksum.currentData() or "none") if checksum is not None else "none",
            )
            peer_combo = getattr(self, "peer_combo", None)
            peer = peer_combo.currentText() if peer_combo else self.port_combo.currentText()
            self.send_preview.setText(
                tr("send.preview", n=len(data), mode=mode.upper(), ending=ending.upper(), peer=peer)
            )
            self.send_edit.setToolTip(data[:256].hex(" ").upper())
        except (ValueError, LookupError) as exc:
            self.send_preview.setText(tr("send.invalid", error=str(exc)))
            self.send_edit.setToolTip(str(exc))

    def toggle_connection(self) -> None:
        """Open/close the tool's primary connection (toolbar default)."""

    def send(self) -> None:
        """Send the current input, if the tool has a send action."""

    def clear_view(self) -> None:
        """Clear the tool's monitor / log view."""

    @property
    def is_open(self) -> bool:
        """True when the tool's primary connection is active."""
        return False

    def link_status(self) -> tuple[str, str]:
        """Return ``(text, kind)`` for the global status bar link badge."""
        return "", "warn"

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
        if isinstance(field, QComboBox):
            # Share the form column. A contents-sized combo makes "N" and
            # "115200" end at different places down the sidebar.
            field.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            field.setMinimumContentsLength(1)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            field.setMinimumWidth(72)
            field.setMaximumWidth(16777215)
        elif isinstance(field, QWidget):
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # Composite fields (edit+button, button grids) share the 28px rhythm
            # but may grow taller — never crush multi-button rows.
            if field.layout() is not None:
                field.setMinimumHeight(28)
                lay = field.layout()
                lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label)
        if key:
            lab.setProperty("i18nKey", key)
        form.addRow(lab, field)
        self._sync_form_labels(form)
        return lab

    def expand_field(self, field: QWidget, *, minimum: int = 120) -> None:
        """Undo a hug-content combo when the text is filled in later."""
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        field.setMinimumWidth(minimum)
        field.setMaximumWidth(16777215)

    def align_combo(self, combo: QComboBox, *, width: int = 100) -> None:
        """Give sibling option lists one width so their edges line up."""
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setFixedHeight(28)
        combo.setFixedWidth(width)

    def _sync_form_labels(self, form: QFormLayout) -> None:
        """Keep all labels in the same column width so 2-char and 4-char
        captions do not stagger the left edge."""
        width = 0
        labels: list[QLabel] = []
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QLabel):
                labels.append(w)
                width = max(width, w.sizeHint().width())
        if not labels:
            return
        # Cap at ~4 CJK chars so narrow side panels keep room for fields.
        width = min(max(width, 56) + 4, 96)
        for lab in labels:
            lab.setMinimumWidth(width)

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


class LinkToolPage(ToolPage):
    """Tool page whose open/closed flag lives in a :class:`LinkController`."""

    def _ensure_link(self):
        link = getattr(self, "_link_ctl", None)
        if link is None:
            from etools.ui.tools.link_controller import LinkController

            link = LinkController(self)
            link.state_changed.connect(self.notify_state)
            self._link_ctl = link
            self.link = link
        return link

    @property
    def _opened(self) -> bool:
        return self._ensure_link().opened

    @_opened.setter
    def _opened(self, value: bool) -> None:
        self._ensure_link().set_opened(bool(value))
