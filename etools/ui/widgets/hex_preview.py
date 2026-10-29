"""Hex preview — multi-document tabs (+ open, × close) for files and chip dumps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.core.hexdump import load_image_segments, merge_segments
from etools.core.models import FIRMWARE_EXTENSIONS, format_size
from etools.i18n import tr
from etools.logger import get_logger
from etools.ui.widgets.spin_boxes import hex_spin

log = get_logger("ui.hex")

MAX_PREVIEW_BYTES = 2 * 1024 * 1024
PLUS_TAB_INDEX_ROLE = 99  # marker for the "+" placeholder tab
_ROW_BYTES = 16
_ASCII_COL = _ROW_BYTES + 1
_ROOT = QModelIndex()
_DISPLAY = Qt.ItemDataRole.DisplayRole
_Index = QModelIndex | QPersistentModelIndex


class HexTableModel(QAbstractTableModel):
    """Address, 16 byte columns, and ASCII. Cells are formatted on demand."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[int, bytes]] = []

    def set_segments(self, segments: list[tuple[int, bytes]], limit: int) -> int:
        """Load rows up to ``limit`` bytes. Returns how many bytes are shown."""
        rows: list[tuple[int, bytes]] = []
        shown = 0
        for addr, data in segments:
            room = limit - shown
            if room <= 0:
                break
            chunk = data[:room]
            for off in range(0, len(chunk), _ROW_BYTES):
                rows.append((addr + off, chunk[off : off + _ROW_BYTES]))
            shown += len(chunk)
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        return shown

    def rowCount(self, parent: _Index = _ROOT) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = _ROOT) -> int:  # noqa: N802
        return 0 if parent.isValid() else _ROW_BYTES + 2

    def data(self, index: _Index, role: int = _DISPLAY) -> Any:
        if not index.isValid():
            return None
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            addr, chunk = self._rows[index.row()]
            if col == 0:
                return f"0x{addr:08X}"
            if col == _ASCII_COL:
                return "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            pos = col - 1
            return f"{chunk[pos]:02X}" if pos < len(chunk) else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if col == _ASCII_COL:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return Qt.GlobalColor.gray
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = _DISPLAY
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if section == 0:
            return tr("hex.addr_col")
        if section == _ASCII_COL:
            return "ASCII"
        return f"{section - 1:02X}"


def segments_text(segments: list[tuple[int, bytes]]) -> str:
    if not segments:
        return tr("hex.empty")
    total = sum(len(d) for _, d in segments)
    lo = min(a for a, _ in segments)
    hi = max(a + len(d) for a, d in segments)
    return tr("hex.summary", n=len(segments), total=total, lo=lo, hi=hi - 1)


class HexDocumentView(QWidget):
    """One hex/ASCII dump page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[tuple[int, bytes]] = []
        self._source = ""
        self._shown = 0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.info_label = QLabel(tr("hex.no_data"))
        self.info_label.setObjectName("hint")
        root.addWidget(self.info_label)

        self.model = HexTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)

        mono = QFont("Cascadia Mono", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.table.setFont(mono)
        # Uniform rows let the view skip per-row size queries on large dumps.
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(
            self.table.fontMetrics().height() + 6
        )

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(True)
        # Full 32-bit address "0x08000000" needs room
        self.table.setColumnWidth(0, 96)
        for i in range(1, _ROW_BYTES + 1):
            self.table.setColumnWidth(i, 30)
        self.table.setColumnWidth(_ASCII_COL, 120)
        root.addWidget(self.table, 1)

    def load_segments(self, segments: list[tuple[int, bytes]], source: str = "") -> None:
        self._segments = merge_segments(segments)
        self._render(source)

    def load_file(self, path: str | Path, bin_base: int = 0x0800_0000) -> None:
        p = Path(path)
        if p.suffix.lower() == ".bin":
            segments = [(bin_base, p.read_bytes())]
        else:
            segments = load_image_segments(p)
        self.load_segments(segments, source=p.name)

    def load_bytes(self, addr: int, data: bytes, source: str | None = None) -> None:
        self.load_segments([(addr, data)], source=source or tr("hex.chip_mem"))

    def retranslate(self) -> None:
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        if self._segments:
            self._update_info()
        else:
            self.info_label.setText(tr("hex.no_data"))

    def _render(self, source: str = "") -> None:
        self._source = source
        self._shown = self.model.set_segments(self._segments, MAX_PREVIEW_BYTES)
        self._update_info()
        self.table.scrollToTop()

    def _update_info(self) -> None:
        total = sum(len(d) for _, d in self._segments)
        shown = tr("hex.shown_rows", n=self.model.rowCount())
        if total > self._shown:
            shown += tr("hex.truncated", total=format_size(total))
        src = tr("hex.source", src=self._source) if self._source else ""
        self.info_label.setText(f"{segments_text(self._segments)} · {shown}{src}")


class HexPreviewPanel(QWidget):
    """Multi-tab hex viewer: + opens a new page, × closes one."""

    read_chip_requested = Signal(int, int)  # addr, size
    fill_requested = Signal(int, int, int)  # addr, size, value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QToolButton

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Toolbar: left-aligned controls, no redundant page title
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.open_btn = QPushButton(tr("hex.open"))
        self.open_btn.setObjectName("ghost")
        self.open_btn.clicked.connect(self._open_file)
        bar.addWidget(self.open_btn)

        self._lbl_addr = QLabel(tr("hex.addr"))
        bar.addWidget(self._lbl_addr)
        self.addr_spin = hex_spin(
            0x0800_0000, step=0x100, width=130
        )
        self.addr_edit = self.addr_spin  # alias for older callers
        bar.addWidget(self.addr_spin)

        self._lbl_size = QLabel(tr("hex.size"))
        bar.addWidget(self._lbl_size)
        self.size_spin = hex_spin(0x1000, step=0x100, width=110)
        self.size_edit = self.size_spin
        bar.addWidget(self.size_spin)

        # Split control: menu only *selects* the action; click runs it
        self.read_btn = QToolButton()
        self.read_btn.setText(tr("hex.read_by_size"))
        self.read_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.read_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.read_btn.setObjectName("accentTool")
        self.read_btn.setEnabled(False)

        menu = QMenu(self.read_btn)
        act_read = QAction(tr("hex.read_by_size"), menu)
        act_read_all = QAction(tr("hex.read_all"), menu)
        act_save = QAction(tr("hex.save_as"), menu)
        act_fill = QAction(tr("hex.fill"), menu)
        act_blank = QAction(tr("hex.blank"), menu)
        act_cmp_file = QAction(tr("hex.cmp_file"), menu)
        act_cmp_two = QAction(tr("hex.cmp_two"), menu)
        actions = [
            act_read,
            act_read_all,
            act_save,
            act_fill,
            act_blank,
            act_cmp_file,
            act_cmp_two,
        ]
        for a in actions:
            a.setCheckable(True)
            menu.addAction(a)
        act_read.setChecked(True)
        self.read_btn.setMenu(menu)
        self.read_btn.clicked.connect(self._run_selected_action)

        for a in actions:
            # Selecting a menu item only updates the button label / mode
            a.triggered.connect(lambda _c=False, act=a: self._select_read_action(act))

        self._action_handlers = {
            act_read: self._on_read_chip,
            act_read_all: self._on_read_all,
            act_save: self._on_save_as,
            act_fill: self._on_fill_memory,
            act_blank: self._on_blank_check,
            act_cmp_file: self._on_compare_with_file,
            act_cmp_two: self._on_compare_two_files,
        }

        bar.addWidget(self.read_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("hexTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        root.addWidget(self.tabs, 1)

        # Device memory page + "+" (no empty "空" page)
        self.mem_view = HexDocumentView()
        self.tabs.addTab(self.mem_view, tr("hex.mem"))
        self.tabs.addTab(QWidget(), "+")
        self.tabs.setTabToolTip(0, tr("hex.mem"))
        self.tabs.setTabToolTip(1, tr("hex.plus_tip"))
        self._menu_actions = actions
        self._selected_action = act_read
        self._fit_read_button()

        # Default blank-chip look (erased flash is 0xFF)
        self.mem_view.load_bytes(
            0x0800_0000,
            b"\xFF" * 0x400,
            source=tr("hex.blank_source"),
        )

    def _fit_read_button(self) -> None:
        """Size the split button and its menu for the longest action label."""
        metrics = self.read_btn.fontMetrics()
        text_width = max(
            (metrics.horizontalAdvance(action.text()) for action in self._menu_actions),
            default=0,
        )
        # QSS padding, checkmark gutter, and the menu-button arrow.
        width = text_width + 72
        self.read_btn.setMinimumWidth(width)
        menu = self.read_btn.menu()
        if menu is not None:
            menu.setMinimumWidth(width)

    def _select_read_action(self, action) -> None:
        self._selected_action = action
        self.read_btn.setText(action.text())
        for a in self._menu_actions:
            a.setChecked(a is action)

    def _run_selected_action(self) -> None:
        handler = self._action_handlers.get(self._selected_action)
        if handler is not None:
            handler()

    def retranslate(self) -> None:
        self.open_btn.setText(tr("hex.open"))
        self._lbl_addr.setText(tr("hex.addr"))
        self._lbl_size.setText(tr("hex.size"))
        keys = [
            "hex.read_by_size",
            "hex.read_all",
            "hex.save_as",
            "hex.fill",
            "hex.blank",
            "hex.cmp_file",
            "hex.cmp_two",
        ]
        for a, k in zip(self._menu_actions, keys, strict=False):
            a.setText(tr(k))
            if a.isChecked():
                self.read_btn.setText(tr(k))
        self._fit_read_button()
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget is self.mem_view:
                self.tabs.setTabText(i, tr("hex.mem"))
            if isinstance(widget, HexDocumentView):
                widget.retranslate()

    def _read_size_bytes(self) -> int:
        return int(self.size_spin.value())

    def _current_addr(self) -> int:
        return int(self.addr_spin.value())

    def _on_tab_bar_clicked(self, index: int) -> None:
        if 0 <= index < self.tabs.count() and self.tabs.tabText(index) == "+":
            self._open_file()

    def set_chip_read_enabled(self, enabled: bool) -> None:
        self.read_btn.setEnabled(enabled)

    def clear(self) -> None:
        for i in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.tabText(i) != "+":
                self.tabs.removeTab(i)
        self.tabs.insertTab(0, self.mem_view, tr("hex.mem"))

    def _new_empty_doc(self) -> HexDocumentView:
        view = HexDocumentView()
        idx = max(0, self.tabs.count() - 1)
        idx = self.tabs.insertTab(idx, view, tr("hex.file_tab"))
        self.tabs.setCurrentIndex(idx)
        return view

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("hex.preview_title"), "", FIRMWARE_EXTENSIONS
        )
        if path:
            self.load_file(path)

    def current_firmware_path(self) -> str:
        """Path of the open firmware tab, or empty on 内存信息 / +."""
        index = self.tabs.currentIndex()
        widget = self.tabs.widget(index)
        if widget is None or widget is self.mem_view or self.tabs.tabText(index) == "+":
            return ""
        path = self.tabs.tabToolTip(index)
        return path if path and Path(path).is_file() else ""

    def load_file(self, path: str | Path) -> bool:
        try:
            resolved = str(Path(path).resolve())
            for index in range(self.tabs.count()):
                tip = self.tabs.tabToolTip(index)
                if tip and tip in {resolved, str(path)}:
                    self.tabs.setCurrentIndex(index)
                    return True
            view = self._new_empty_doc()
            view.load_file(path)
            name = Path(path).name
            if len(name) > 18:
                name = name[:15] + "…"
            idx = self.tabs.indexOf(view)
            self.tabs.setTabText(idx, name)
            self.tabs.setTabToolTip(idx, resolved)
            self.tabs.setCurrentIndex(idx)
            # Keep toolbar address in sync with the image base
            if view._segments:
                base = int(view._segments[0][0])
                if 0 <= base <= self.addr_spin.maximum():
                    self.addr_spin.setValue(base)
            return True
        except Exception as exc:
            log.exception("load file failed")
            w = self.tabs.currentWidget()
            if isinstance(w, HexDocumentView):
                w.info_label.setText(tr("hex.load_fail", err=exc))
            return False

    def load_bytes(self, addr: int, data: bytes, source: str | None = None) -> None:
        """Load into 内存信息 page (device memory)."""
        src = source or tr("hex.chip_src", addr=f"{addr:08X}")
        self.mem_view.load_bytes(addr, data, source=src)
        idx = self.tabs.indexOf(self.mem_view)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def _close_tab(self, index: int) -> None:
        if self.tabs.tabText(index) == "+":
            return
        # keep 内存信息
        if self.tabs.widget(index) is self.mem_view:
            return
        self.tabs.removeTab(index)

    # ----- Read menu actions (CubeProg-like) -----

    def _on_read_chip(self) -> None:
        addr = self._current_addr()
        size = self._read_size_bytes()
        if size <= 0 or size > 1024 * 1024:
            return
        self.read_chip_requested.emit(addr, size)

    def _on_read_all(self) -> None:
        # Prefer the live flash size; fall back to 1 MiB when unknown.
        hint = getattr(self, "_flash_size_hint", 0) or 0
        size = min(int(hint), 2 * 1024 * 1024) if hint > 0 else 0x100000
        addr = self._current_addr()
        self.size_spin.setValue(size)
        self.read_chip_requested.emit(addr, size)

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("hex.save_mem_title"), "memory_dump.bin", "Binary (*.bin);;All files (*)"
        )
        if not path:
            return
        # save current mem_view if it has data
        try:
            data = self.mem_view._segments
            if not data:
                self.mem_view.info_label.setText(tr("hex.need_data_save"))
                return
            blob = b"".join(d for _, d in data)
            Path(path).write_bytes(blob)
            self.mem_view.info_label.setText(tr("hex.saved", path=path, n=len(blob)))
        except Exception as exc:
            self.mem_view.info_label.setText(tr("hex.save_fail", err=exc))

    def _on_fill_memory(self) -> None:
        """Ask for fill byte, then request a RAM fill of addr/size."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        addr = self._current_addr()
        size = self._read_size_bytes()
        if size <= 0 or size > 256 * 1024:
            self.mem_view.info_label.setText(tr("hex.fill_limit"))
            return

        text, ok = QInputDialog.getText(
            self,
            tr("hex.fill"),
            tr("hex.fill_prompt"),
            text="FF",
        )
        if not ok:
            return
        raw = (text or "").strip().lower().removeprefix("0x")
        try:
            value = int(raw, 16)
        except ValueError:
            self.mem_view.info_label.setText(tr("hex.fill_invalid"))
            return
        if not 0 <= value <= 0xFF:
            self.mem_view.info_label.setText(tr("hex.fill_range"))
            return

        confirm = QMessageBox.question(
            self,
            tr("hex.fill_confirm_title"),
            tr("confirm.fill_text", addr=addr, size=size, value=value),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.fill_requested.emit(addr, size, value)

    def _on_blank_check(self) -> None:
        # Check if current mem dump is all 0xFF
        segs = self.mem_view._segments
        if not segs:
            self.mem_view.info_label.setText(tr("hex.need_chip_blank"))
            return
        blank = all(all(b == 0xFF for b in d) for _, d in segs)
        total = sum(len(d) for _, d in segs)
        msg = tr("hex.blank_ok") if blank else tr("hex.blank_fail")
        self.mem_view.info_label.setText(f"{msg} · {tr('hex.bytes', n=total)}")

    def _on_compare_with_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("hex.cmp_file_title"), "", FIRMWARE_EXTENSIONS
        )
        if not path:
            return
        if not self.mem_view._segments:
            self.mem_view.info_label.setText(tr("hex.need_chip"))
            return
        try:
            from etools.core.hexdump import load_image_segments

            segs = load_image_segments(path)
            # flatten first segment pair comparison (simple)
            chip = b"".join(d for _, d in self.mem_view._segments)
            file_blob = b"".join(d for _, d in segs)
            n = min(len(chip), len(file_blob))
            mismatch = next((i for i in range(n) if chip[i] != file_blob[i]), None)
            if mismatch is None and len(chip) == len(file_blob):
                self.mem_view.info_label.setText(tr("hex.cmp_with", name=Path(path).name))
            elif mismatch is None:
                self.mem_view.info_label.setText(
                    tr("hex.cmp_len_diff", a=len(chip), b=len(file_blob))
                )
            else:
                self.mem_view.info_label.setText(
                    tr("hex.cmp_mismatch", name=Path(path).name, offset=mismatch)
                )
        except Exception as exc:
            self.mem_view.info_label.setText(tr("hex.cmp_fail", err=str(exc)))

    def _on_compare_two_files(self) -> None:
        p1, _ = QFileDialog.getOpenFileName(self, tr("hex.cmp_p1"), "", FIRMWARE_EXTENSIONS)
        if not p1:
            return
        p2, _ = QFileDialog.getOpenFileName(self, tr("hex.cmp_p2"), "", FIRMWARE_EXTENSIONS)
        if not p2:
            return
        try:
            b1 = Path(p1).read_bytes()
            b2 = Path(p2).read_bytes()
            if b1 == b2:
                msg = tr("hex.cmp_files_ok")
            else:
                n = min(len(b1), len(b2))
                i = next((j for j in range(n) if b1[j] != b2[j]), n)
                msg = tr("hex.cmp_files_diff", offset=i, a=len(b1), b=len(b2))
            self.mem_view.info_label.setText(msg)
        except Exception as exc:
            self.mem_view.info_label.setText(tr("hex.cmp_fail", err=str(exc)))
