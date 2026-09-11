"""Hex preview — multi-document tabs (+ open, × close) for files and chip dumps."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.hexdump import (
    format_hex_lines,
    load_image_segments,
    merge_segments,
    segments_summary,
)
from etools.core.models import FIRMWARE_EXTENSIONS, format_size
from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("ui.hex")

MAX_PREVIEW_BYTES = 256 * 1024
PLUS_TAB_INDEX_ROLE = 99  # marker for the "+" placeholder tab


class HexDocumentView(QWidget):
    """One hex/ASCII dump page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[tuple[int, bytes]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.info_label = QLabel("尚未加载数据")
        self.info_label.setObjectName("hint")
        root.addWidget(self.info_label)

        self.table = QTableWidget(0, 18)
        self.table.setHorizontalHeaderLabels(
            ["地址"] + [f"{i:X}" for i in range(16)] + ["ASCII"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)

        mono = QFont("Cascadia Mono", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.table.setFont(mono)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(True)
        self.table.setColumnWidth(0, 78)
        for i in range(1, 17):
            self.table.setColumnWidth(i, 28)
        self.table.setColumnWidth(17, 120)
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

    def load_bytes(self, addr: int, data: bytes, source: str = "芯片内存") -> None:
        self.load_segments([(addr, data)], source=source)

    def _render(self, source: str = "") -> None:
        rows_data: list[tuple[str, str, str]] = []
        total = 0
        for addr, data in self._segments:
            total += len(data)
            rows_data.extend(
                format_hex_lines(addr, data, width=16, max_bytes=MAX_PREVIEW_BYTES)
            )
            if total >= MAX_PREVIEW_BYTES:
                break

        self.table.setRowCount(len(rows_data))
        for r, (addr_s, hex_s, ascii_s) in enumerate(rows_data):
            item0 = QTableWidgetItem(addr_s)
            item0.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            item0.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(r, 0, item0)
            parts = hex_s.split()
            for c in range(16):
                it = QTableWidgetItem(parts[c] if c < len(parts) else "")
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
            it_a = QTableWidgetItem(ascii_s)
            it_a.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(r, 17, it_a)

        summary = segments_summary(self._segments)
        shown = f"显示 {len(rows_data)} 行"
        if total > MAX_PREVIEW_BYTES:
            shown += f"（截断，共 {format_size(total)}）"
        src = f" · 来源：{source}" if source else ""
        self.info_label.setText(f"{summary} · {shown}{src}")
        self.table.scrollToTop()


class HexPreviewPanel(QWidget):
    """Multi-tab hex viewer: + opens a new page, × closes one."""

    read_chip_requested = Signal(int, int)  # addr, size
    # extra actions (label, addr, size) for parent to handle if needed
    memory_action = Signal(str, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QToolButton

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._title = QLabel(tr("hex.title"))
        self._title.setObjectName("panelTitle")
        bar.addWidget(self._title)
        bar.addStretch(1)

        self.open_btn = QPushButton(tr("hex.open"))
        self.open_btn.setObjectName("ghost")
        self.open_btn.clicked.connect(self._open_file)
        bar.addWidget(self.open_btn)

        self._lbl_addr = QLabel(tr("hex.addr"))
        bar.addWidget(self._lbl_addr)
        self.addr_edit = QLineEdit("0x08000000")
        self.addr_edit.setFixedWidth(100)
        bar.addWidget(self.addr_edit)

        self._lbl_size = QLabel(tr("hex.size"))
        bar.addWidget(self._lbl_size)
        self.size_edit = QLineEdit("0x1000")
        self.size_edit.setFixedWidth(90)
        bar.addWidget(self.size_edit)

        # Read split-button with CubeProg-like menu
        self.read_btn = QToolButton()
        self.read_btn.setText(tr("hex.read"))
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
        for a in (
            act_read,
            act_read_all,
            act_save,
            act_fill,
            act_blank,
            act_cmp_file,
            act_cmp_two,
        ):
            menu.addAction(a)
        self.read_btn.setMenu(menu)
        self.read_btn.setDefaultAction(act_read)

        act_read.triggered.connect(self._on_read_chip)
        act_read_all.triggered.connect(self._on_read_all)
        act_save.triggered.connect(self._on_save_as)
        act_fill.triggered.connect(self._on_fill_memory)
        act_blank.triggered.connect(self._on_blank_check)
        act_cmp_file.triggered.connect(self._on_compare_with_file)
        act_cmp_two.triggered.connect(self._on_compare_two_files)

        bar.addWidget(self.read_btn)
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
        self._menu_actions = [
            act_read,
            act_read_all,
            act_save,
            act_fill,
            act_blank,
            act_cmp_file,
            act_cmp_two,
        ]

    def retranslate(self) -> None:
        self._title.setText(tr("hex.title"))
        self.open_btn.setText(tr("hex.open"))
        self._lbl_addr.setText(tr("hex.addr"))
        self._lbl_size.setText(tr("hex.size"))
        self.read_btn.setText(tr("hex.read"))
        keys = [
            "hex.read_by_size",
            "hex.read_all",
            "hex.save_as",
            "hex.fill",
            "hex.blank",
            "hex.cmp_file",
            "hex.cmp_two",
        ]
        for a, k in zip(self._menu_actions, keys):
            a.setText(tr(k))
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is self.mem_view:
                self.tabs.setTabText(i, tr("hex.mem"))
                break

    def _read_size_bytes(self) -> int:
        try:
            return int(self.size_edit.text().strip(), 0)
        except ValueError:
            return 0x1000

    def _current_addr(self) -> int:
        try:
            return int(self.addr_edit.text().strip(), 0)
        except ValueError:
            return 0x08000000

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
        idx = self.tabs.insertTab(idx, view, "文件")
        self.tabs.setCurrentIndex(idx)
        return view

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "预览固件", "", FIRMWARE_EXTENSIONS)
        if path:
            self.load_file(path)

    def load_file(self, path: str | Path) -> bool:
        try:
            view = self._new_empty_doc()
            view.load_file(path)
            name = Path(path).name
            if len(name) > 18:
                name = name[:15] + "…"
            idx = self.tabs.indexOf(view)
            self.tabs.setTabText(idx, name)
            self.tabs.setTabToolTip(idx, str(path))
            self.tabs.setCurrentIndex(idx)
            return True
        except Exception as exc:
            log.exception("load file failed")
            w = self.tabs.currentWidget()
            if isinstance(w, HexDocumentView):
                w.info_label.setText(f"加载失败：{exc}")
            return False

    def load_bytes(self, addr: int, data: bytes, source: str | None = None) -> None:
        """Load into 内存信息 page (device memory)."""
        self.mem_view.load_bytes(addr, data, source=source or f"芯片 0x{addr:08X}")
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
        # Read a full typical flash bank from address
        addr = self._current_addr()
        self.size_edit.setText("0x100000")  # 1 MB
        self.read_chip_requested.emit(addr, 0x100000)

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "另存内存", "memory_dump.bin", "Binary (*.bin);;All files (*)"
        )
        if not path:
            return
        # save current mem_view if it has data
        try:
            data = self.mem_view._segments
            if not data:
                self.mem_view.info_label.setText("无内存数据可保存，请先读取芯片")
                return
            blob = b"".join(d for _, d in data)
            Path(path).write_bytes(blob)
            self.mem_view.info_label.setText(f"已保存 {path} ({len(blob):,} 字节)")
        except Exception as exc:
            self.mem_view.info_label.setText(f"保存失败：{exc}")

    def _on_fill_memory(self) -> None:
        self.memory_action.emit("fill", self._current_addr(), self._read_size_bytes())

    def _on_blank_check(self) -> None:
        # Check if current mem dump is all 0xFF
        segs = self.mem_view._segments
        if not segs:
            self.mem_view.info_label.setText("请先读取芯片再做空白检查")
            return
        blank = all(all(b == 0xFF for b in d) for _, d in segs)
        total = sum(len(d) for _, d in segs)
        msg = "空白检查通过（全部 0xFF）" if blank else "空白检查失败（存在非 0xFF 数据）"
        self.mem_view.info_label.setText(f"{msg} · {total:,} 字节")

    def _on_compare_with_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择比较文件", "", FIRMWARE_EXTENSIONS)
        if not path:
            return
        if not self.mem_view._segments:
            self.mem_view.info_label.setText("请先读取芯片内存")
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
                self.mem_view.info_label.setText(f"与 {Path(path).name} 完全一致")
            elif mismatch is None:
                self.mem_view.info_label.setText(
                    f"长度不同：芯片 {len(chip):,} vs 文件 {len(file_blob):,}"
                )
            else:
                self.mem_view.info_label.setText(
                    f"与 {Path(path).name} 不一致，首处偏移 0x{mismatch:X}"
                )
        except Exception as exc:
            self.mem_view.info_label.setText(f"比较失败：{exc}")

    def _on_compare_two_files(self) -> None:
        p1, _ = QFileDialog.getOpenFileName(self, "选择文件 1", "", FIRMWARE_EXTENSIONS)
        if not p1:
            return
        p2, _ = QFileDialog.getOpenFileName(self, "选择文件 2", "", FIRMWARE_EXTENSIONS)
        if not p2:
            return
        try:
            b1 = Path(p1).read_bytes()
            b2 = Path(p2).read_bytes()
            if b1 == b2:
                msg = "两个文件完全一致"
            else:
                n = min(len(b1), len(b2))
                i = next((j for j in range(n) if b1[j] != b2[j]), n)
                msg = (
                    f"不一致，首处偏移 0x{i:X}；长度 {len(b1):,} vs {len(b2):,}"
                )
            self.mem_view.info_label.setText(msg)
        except Exception as exc:
            self.mem_view.info_label.setText(f"比较失败：{exc}")
