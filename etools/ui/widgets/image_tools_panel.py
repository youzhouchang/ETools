"""Firmware image tools: merge, relocate, cut, fill, patch, checksum, export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.fw_image import ImageError, SparseImage
from etools.core.models import FIRMWARE_EXTENSIONS
from etools.i18n import tr
from etools.ui.widgets.flash_tools_common import int_edit, parse_int, tool_button

_SAVE_FILTER = "Intel HEX (*.hex);;Motorola S-record (*.srec *.s19 *.s37);;Binary (*.bin)"
_UNDO_DEPTH = 20


class ImageToolsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host: Any = None
        self.image = SparseImage()
        self._undo: list[SparseImage] = []
        self._sources: list[str] = []
        self._build()

    def bind(self, host: Any) -> None:
        self._host = host

    def set_connected(self, connected: bool) -> None:
        """Image editing works offline."""

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self.add_btn = tool_button("open", kind="accent")
        self.add_current_btn = tool_button("program")
        self.base_label = QLabel()
        self.base_edit = int_edit(0x0800_0000)
        self.undo_btn = tool_button("refresh")
        self.clear_btn = tool_button("clear")
        self.save_btn = tool_button("save")
        self.use_btn = tool_button("program")
        for w in (self.add_btn, self.add_current_btn, self.base_label, self.base_edit):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.undo_btn, self.clear_btn, self.save_btn, self.use_btn):
            bar.addWidget(w)
        root.addLayout(bar)

        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.ops_box = QGroupBox()
        self.ops_box.setObjectName("ctxGroup")
        grid = QGridLayout(self.ops_box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.lbl_start = QLabel()
        self.lbl_end = QLabel()
        self.range_start = int_edit()
        self.range_end = int_edit()
        self.delete_btn = tool_button("erase", kind="danger")
        self.crop_btn = tool_button("compare")
        self.fill_value = int_edit(0xFF, width=70, digits=2)
        self.fill_btn = tool_button("fill")
        self.lbl_fill = QLabel()
        grid.addWidget(self.lbl_start, 0, 0)
        grid.addWidget(self.range_start, 0, 1)
        grid.addWidget(self.lbl_end, 0, 2)
        grid.addWidget(self.range_end, 0, 3)
        grid.addWidget(self.delete_btn, 0, 4)
        grid.addWidget(self.crop_btn, 0, 5)
        grid.addWidget(self.lbl_fill, 0, 6)
        grid.addWidget(self.fill_value, 0, 7)
        grid.addWidget(self.fill_btn, 0, 8)

        self.lbl_rebase = QLabel()
        self.rebase_edit = int_edit()
        self.rebase_btn = tool_button("memory")
        self.lbl_align = QLabel()
        self.align_edit = int_edit(16, width=70, digits=1)
        self.align_btn = tool_button("fill")
        grid.addWidget(self.lbl_rebase, 1, 0)
        grid.addWidget(self.rebase_edit, 1, 1)
        grid.addWidget(self.rebase_btn, 1, 2)
        grid.addWidget(self.lbl_align, 1, 3)
        grid.addWidget(self.align_edit, 1, 4)
        grid.addWidget(self.align_btn, 1, 5)

        self.lbl_patch = QLabel()
        self.patch_addr = int_edit()
        self.patch_bytes = QLineEdit()
        self.patch_btn = tool_button("hex")
        grid.addWidget(self.lbl_patch, 2, 0)
        grid.addWidget(self.patch_addr, 2, 1)
        grid.addWidget(self.patch_bytes, 2, 2, 1, 5)
        grid.addWidget(self.patch_btn, 2, 7, 1, 2)
        grid.setColumnStretch(9, 1)
        root.addWidget(self.ops_box)

        self.add_btn.clicked.connect(self._add_files)
        self.add_current_btn.clicked.connect(self._add_current)
        self.undo_btn.clicked.connect(self.undo)
        self.clear_btn.clicked.connect(self._clear)
        self.save_btn.clicked.connect(lambda: self._save(use=False))
        self.use_btn.clicked.connect(lambda: self._save(use=True))
        self.delete_btn.clicked.connect(lambda: self._range_op("delete"))
        self.crop_btn.clicked.connect(lambda: self._range_op("crop"))
        self.fill_btn.clicked.connect(lambda: self._range_op("fill"))
        self.rebase_btn.clicked.connect(self._rebase)
        self.align_btn.clicked.connect(self._align)
        self.patch_btn.clicked.connect(self._patch)
        self.retranslate()

    def retranslate(self) -> None:
        self.add_btn.setText(tr("img.add"))
        self.add_current_btn.setText(tr("img.add_current"))
        self.base_label.setText(tr("img.bin_base"))
        self.undo_btn.setText(tr("img.undo"))
        self.clear_btn.setText(tr("img.clear"))
        self.save_btn.setText(tr("img.save"))
        self.use_btn.setText(tr("img.save_use"))
        self.table.setHorizontalHeaderLabels(
            [tr("img.col.start"), tr("img.col.end"), tr("img.col.size")]
        )
        self.ops_box.setTitle(tr("img.ops"))
        self.lbl_start.setText(tr("img.start"))
        self.lbl_end.setText(tr("img.end"))
        self.delete_btn.setText(tr("img.delete"))
        self.crop_btn.setText(tr("img.crop"))
        self.lbl_fill.setText(tr("img.fill_value"))
        self.fill_btn.setText(tr("img.fill"))
        self.lbl_rebase.setText(tr("img.rebase_to"))
        self.rebase_btn.setText(tr("img.rebase"))
        self.lbl_align.setText(tr("img.align"))
        self.align_btn.setText(tr("img.pad"))
        self.lbl_patch.setText(tr("img.patch"))
        self.patch_bytes.setPlaceholderText(tr("img.patch_placeholder"))
        self.patch_btn.setText(tr("img.patch_apply"))
        self._refresh()

    # -- state ------------------------------------------------------------

    def _push_undo(self) -> None:
        self._undo.append(self.image.copy())
        del self._undo[:-_UNDO_DEPTH]

    def undo(self) -> None:
        if self._undo:
            self.image = self._undo.pop()
            self._refresh()

    def _clear(self) -> None:
        self._push_undo()
        self.image = SparseImage()
        self._sources = []
        self._refresh()

    def _refresh(self) -> None:
        segs = self.image.segments()
        self.table.setRowCount(len(segs))
        for row, (start, data) in enumerate(segs):
            self.table.setItem(row, 0, QTableWidgetItem(f"0x{start:08X}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"0x{start + len(data) - 1:08X}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{len(data):,}"))
        if self.image.empty:
            self.summary.setText(tr("img.empty"))
        else:
            try:
                crc = f"{self.image.crc32():08X}"
                sha = self.image.sha256()[:16] + "…"
                if not self.image.digest_is_flat:
                    crc = tr("img.crc_segmented", crc=crc)
            except ImageError:
                crc = sha = "—"
            self.summary.setText(
                tr(
                    "img.summary",
                    files=", ".join(Path(p).name for p in self._sources) or "—",
                    segs=len(segs),
                    size=f"{len(self.image):,}",
                    start=f"0x{self.image.start:08X}",
                    end=f"0x{self.image.end - 1:08X}",
                    crc=crc,
                    sha=sha,
                )
            )
        self.undo_btn.setEnabled(bool(self._undo))
        has = not self.image.empty
        for w in (self.save_btn, self.use_btn, self.delete_btn, self.crop_btn, self.fill_btn):
            w.setEnabled(has)
        for w in (self.rebase_btn, self.align_btn):
            w.setEnabled(has)

    def _error(self, msg: str) -> None:
        QMessageBox.warning(self, tr("img.title"), msg)

    def _log(self, msg: str) -> None:
        if self._host is not None:
            self._host.log(msg)

    # -- loading ----------------------------------------------------------

    def add_file(self, path: str) -> bool:
        try:
            base = parse_int(self.base_edit.text(), 0x0800_0000)
            incoming = SparseImage.from_file(path, bin_base=base)
        except (OSError, ValueError, RuntimeError) as exc:
            self._error(tr("img.load_fail", name=Path(path).name, err=str(exc)))
            return False
        conflicts = self.image.conflicts(incoming)
        overwrite = False
        if conflicts:
            ranges = ", ".join(f"0x{a:08X}..0x{b - 1:08X}" for a, b in conflicts[:6])
            ret = QMessageBox.question(
                self,
                tr("img.title"),
                tr("img.conflict", name=Path(path).name, ranges=ranges),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return False
            overwrite = True
        self._push_undo()
        self.image.merge(incoming, overwrite=overwrite)
        self._sources.append(path)
        self._refresh()
        self._log(tr("img.added", name=Path(path).name, summary=incoming.summary()))
        return True

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("img.add"), "", FIRMWARE_EXTENSIONS)
        for path in paths:
            if not self.add_file(path):
                break

    def _add_current(self) -> None:
        path = self._host.firmware_path() if self._host is not None else ""
        if path and Path(path).is_file():
            self.add_file(path)
        else:
            self._error(tr("img.no_current"))

    # -- edits ------------------------------------------------------------

    def _range(self) -> tuple[int, int]:
        start = parse_int(self.range_start.text(), self.image.start)
        end = parse_int(self.range_end.text(), self.image.end)
        if end <= start:
            raise ValueError(tr("img.bad_range"))
        return start, end

    def _range_op(self, op: str) -> None:
        try:
            start, end = self._range()
            snapshot = self.image.copy()
            if op == "delete":
                self.image.delete(start, end)
            elif op == "crop":
                self.image.crop(start, end)
            else:
                value = parse_int(self.fill_value.text(), 0xFF)
                if not 0 <= value <= 0xFF:
                    raise ValueError(tr("img.bad_fill"))
                added = self.image.fill_gaps(value, start, end)
                self._log(tr("img.filled", n=f"{added:,}"))
        except (ValueError, ImageError) as exc:
            self._error(str(exc))
            return
        self._undo.append(snapshot)
        del self._undo[:-_UNDO_DEPTH]
        self._refresh()

    def _rebase(self) -> None:
        try:
            target = parse_int(self.rebase_edit.text())
            snapshot = self.image.copy()
            self.image.rebase(target)
        except (ValueError, ImageError) as exc:
            self._error(str(exc))
            return
        self._undo.append(snapshot)
        self._refresh()

    def _align(self) -> None:
        try:
            alignment = parse_int(self.align_edit.text(), 16)
            value = parse_int(self.fill_value.text(), 0xFF)
            if alignment <= 0 or not 0 <= value <= 0xFF:
                raise ValueError(tr("img.bad_fill"))
        except ValueError as exc:
            self._error(str(exc))
            return
        self._push_undo()
        self.image.pad_to(alignment, value)
        self._refresh()

    def _patch(self) -> None:
        try:
            addr = parse_int(self.patch_addr.text())
            text = self.patch_bytes.text().replace(",", " ").replace("0x", "").replace("0X", "")
            data = bytes.fromhex(text)
            if not data:
                raise ValueError(tr("img.bad_patch"))
            snapshot = self.image.copy()
            self.image.write(addr, data)
        except (ValueError, ImageError) as exc:
            self._error(str(exc) or tr("img.bad_patch"))
            return
        self._undo.append(snapshot)
        self._refresh()
        self._log(tr("img.patched", n=len(data), addr=f"0x{addr:08X}"))

    # -- export -----------------------------------------------------------

    def _save(self, *, use: bool) -> None:
        if self.image.empty:
            return
        start = str(Path(self._sources[-1]).with_suffix(".merged.hex")) if self._sources else ""
        path, selected = QFileDialog.getSaveFileName(self, tr("img.save"), start, _SAVE_FILTER)
        if not path:
            return
        if not Path(path).suffix:
            if "Binary" in selected:
                path += ".bin"
            elif "S-record" in selected:
                path += ".srec"
            else:
                path += ".hex"
        try:
            fmt = self.image.save(path)
        except (OSError, ImageError) as exc:
            self._error(str(exc))
            return
        self._log(tr("img.saved", path=path, fmt=fmt.upper()))
        if fmt == "bin" and self._host is not None:
            self._host.log(tr("img.bin_base_note", addr=f"0x{self.image.start:08X}"))
        if use and self._host is not None:
            self._host.use_firmware(path)
