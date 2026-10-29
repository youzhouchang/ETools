"""Diagnosis page: HardFault decode and an RTOS thread list."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.diagnosis import (
    FaultFlag,
    FaultSnapshot,
    RtosSnapshot,
    capture,
    rtos_label,
)
from etools.core.probe_io import PROBE_LOCK
from etools.i18n import tr
from etools.ui.icons import set_button_icon

_FAULT_GROUPS = ("MMFSR", "BFSR", "UFSR", "HFSR")
_ELF_SUFFIXES = {".elf", ".axf", ".out"}


class _DiagJob(QThread):
    finished_ok = Signal(object, object)

    def __init__(
        self, session: Any, elf_path: str, halt: bool, lock: Any, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._elf_path = elf_path
        self._halt = halt
        self._lock = lock

    def run(self) -> None:  # noqa: D102
        fault, rtos = capture(self._session, self._elf_path, halt=self._halt, lock=self._lock)
        self.finished_ok.emit(fault, rtos)


class DiagPanel(QWidget):
    """Two stacked cards: fault status, then RTOS threads."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_getter: Callable[[], Any] | None = None
        self._firmware_getter: Callable[[], str] | None = None
        self._connected = False
        self._job: _DiagJob | None = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setFixedHeight(28)
        set_button_icon(self.refresh_btn, "refresh", 16)
        self.refresh_btn.clicked.connect(self.refresh)
        self.halt_check = QCheckBox()
        self.halt_check.setChecked(False)
        self.status_label = QLabel()
        self.status_label.setObjectName("hint")
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.halt_check)
        bar.addWidget(self.status_label, 1)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_fault())
        split.addWidget(self._build_rtos())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self.retranslate()
        self.refresh_btn.setEnabled(False)

    def _build_fault(self) -> QGroupBox:
        box = QGroupBox()
        box.setObjectName("ctxGroup")
        self.fault_box = box
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(6)
        self.fault_summary = QLabel()
        self.fault_summary.setWordWrap(True)
        self.fault_regs = QLabel()
        self.fault_regs.setObjectName("hint")
        self.fault_regs.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.flag_table = self._table(3)
        self.frame_title = QLabel()
        self.frame_table = self._table(3)
        lay.addWidget(self.fault_summary)
        lay.addWidget(self.fault_regs)
        lay.addWidget(self.flag_table, 1)
        lay.addWidget(self.frame_title)
        lay.addWidget(self.frame_table, 1)
        return box

    def _build_rtos(self) -> QGroupBox:
        box = QGroupBox()
        box.setObjectName("ctxGroup")
        self.rtos_box = box
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.elf_label = QLabel()
        self.elf_edit = QLineEdit()
        self.elf_btn = QPushButton()
        self.elf_btn.setObjectName("ghost")
        self.elf_btn.setFixedHeight(28)
        self.elf_btn.clicked.connect(self._browse_elf)
        row.addWidget(self.elf_label)
        row.addWidget(self.elf_edit, 1)
        row.addWidget(self.elf_btn)
        self.rtos_summary = QLabel()
        self.rtos_summary.setWordWrap(True)
        self.rtos_hint = QLabel()
        self.rtos_hint.setObjectName("hint")
        self.rtos_hint.setWordWrap(True)
        self.thread_table = self._table(5)
        lay.addLayout(row)
        lay.addWidget(self.rtos_summary)
        lay.addWidget(self.rtos_hint)
        lay.addWidget(self.thread_table, 1)
        return box

    @staticmethod
    def _table(columns: int) -> QTableWidget:
        table = QTableWidget(0, columns)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.setMinimumWidth(0)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    def set_session_getter(self, fn: Callable[[], Any]) -> None:
        self._session_getter = fn

    def set_firmware_getter(self, fn: Callable[[], str]) -> None:
        self._firmware_getter = fn

    def shutdown(self) -> None:
        job = self._job
        if job is not None and job.isRunning():
            job.wait(5000)
        self._job = None

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        busy = self._job is not None and self._job.isRunning()
        self.refresh_btn.setEnabled(connected and not busy)
        if connected:
            self._fill_elf_from_firmware()

    def retranslate(self) -> None:
        self.fault_box.setTitle(tr("diag.fault"))
        self.rtos_box.setTitle(tr("diag.rtos"))
        self.refresh_btn.setText(tr("diag.refresh"))
        self.halt_check.setText(tr("diag.halt"))
        self.halt_check.setToolTip(tr("diag.halt_tip"))
        self.elf_label.setText(tr("diag.elf"))
        self.elf_btn.setText(tr("diag.elf_browse"))
        self.rtos_hint.setText(tr("diag.rtos_hint"))
        self._set_headers(
            self.flag_table,
            (tr("diag.col_group"), tr("diag.col_bit"), tr("diag.col_meaning")),
        )
        self._set_headers(
            self.frame_table,
            (tr("diag.col_reg"), tr("diag.col_value"), tr("diag.col_symbol")),
        )
        self._set_headers(
            self.thread_table,
            (
                tr("diag.current"),
                tr("diag.col_name"),
                tr("diag.col_state"),
                tr("diag.col_pri"),
                tr("diag.col_id"),
            ),
        )
        if not self.fault_summary.text():
            self.fault_summary.setText(tr("diag.not_connected"))
        if not self.rtos_summary.text():
            self.rtos_summary.setText(tr("diag.rtos_need_elf"))

    def refresh(self) -> None:
        if self._job is not None and self._job.isRunning():
            return
        session = self._session_getter() if callable(self._session_getter) else None
        if session is None or not self._connected:
            self._show_disconnected()
            return
        self._fill_elf_from_firmware()
        self.refresh_btn.setEnabled(False)
        self.status_label.setText(tr("diag.refreshing"))
        job = _DiagJob(
            session,
            self.elf_edit.text().strip(),
            self.halt_check.isChecked(),
            PROBE_LOCK,
            self,
        )
        job.finished_ok.connect(self._apply)
        job.finished.connect(job.deleteLater)
        self._job = job
        job.start()

    def _browse_elf(self) -> None:
        start = self.elf_edit.text().strip()
        if not start and callable(self._firmware_getter):
            start = self._firmware_getter() or ""
        folder = str(Path(start).parent) if start else ""
        path, _selected = QFileDialog.getOpenFileName(
            self,
            tr("diag.elf_title"),
            folder,
            tr("diag.elf_filter"),
        )
        if path:
            self.elf_edit.setText(path)

    def _fill_elf_from_firmware(self) -> None:
        if self.elf_edit.text().strip() or not callable(self._firmware_getter):
            return
        path = self._firmware_getter() or ""
        if Path(path).suffix.lower() in _ELF_SUFFIXES:
            self.elf_edit.setText(path)

    def _apply(self, fault: FaultSnapshot, rtos: RtosSnapshot) -> None:
        self._job = None
        self.refresh_btn.setEnabled(self._connected)
        self.status_label.setText("")
        self._show_fault(fault)
        self._show_rtos(rtos)

    def _show_disconnected(self) -> None:
        text = tr("diag.not_connected")
        self.fault_summary.setText(text)
        self.rtos_summary.setText(text)
        self.fault_regs.setText("")
        self.frame_title.setText("")
        self.flag_table.setRowCount(0)
        self.frame_table.setRowCount(0)
        self.thread_table.setRowCount(0)

    def _show_fault(self, snap: FaultSnapshot) -> None:
        if not snap.ok:
            self.fault_summary.setText(self._error_text(snap.error, snap.detail))
            self.fault_regs.setText("")
            self.frame_title.setText("")
            self.flag_table.setRowCount(0)
            self.frame_table.setRowCount(0)
            return
        causes = [flag for flag in snap.flags if flag.group in _FAULT_GROUPS]
        if causes:
            summary = " · ".join(tr(f"diag.bit.{flag.name}") for flag in causes)
        else:
            summary = tr("diag.fault_none")
        where = self._where(snap)
        if snap.pc is not None:
            symbol = f" {snap.pc_symbol}" if snap.pc_symbol else ""
            summary = (
                f"{summary} · "
                + tr(
                    "diag.fault_at",
                    pc=f"0x{snap.pc:08X}",
                    symbol=symbol,
                    where=where,
                )
            )
        if snap.resumed:
            summary = f"{summary} · {tr('diag.fault_resumed')}"
        if snap.running:
            summary = f"{summary} · {tr('diag.fault_running')}"
        self.fault_summary.setText(summary)
        regs = f"CFSR 0x{snap.cfsr:08X}   HFSR 0x{snap.hfsr:08X}   DFSR 0x{snap.dfsr:08X}"
        if snap.mmfar_valid:
            regs += f"   MMFAR 0x{snap.mmfar:08X}"
        if snap.bfar_valid:
            regs += f"   BFAR 0x{snap.bfar:08X}"
        self.fault_regs.setText(regs)
        flags = snap.flags
        if snap.resumed:
            # The brief halt sets DFSR.HALTED; that bit is not a chip fault.
            flags = tuple(
                flag for flag in flags if not (flag.group == "DFSR" and flag.name == "HALTED")
            )
        self._fill_flags(flags)
        if snap.frame:
            self.frame_title.setText(tr("diag.frame_stack", stack=snap.frame_stack))
            self._fill_frame(snap)
        elif snap.running:
            self.frame_title.setText(tr("diag.frame_running"))
            self.frame_table.setRowCount(0)
        else:
            self.frame_title.setText(tr("diag.frame_none"))
            self.frame_table.setRowCount(0)

    def _show_rtos(self, snap: RtosSnapshot) -> None:
        label = rtos_label(snap.plugin)
        if snap.error == "not_connected":
            text = tr("diag.not_connected")
        elif snap.error == "no_elf":
            text = tr("diag.rtos_need_elf")
        elif snap.error == "not_elf":
            text = tr("diag.rtos_not_elf")
        elif snap.error == "elf_fail":
            text = tr("diag.rtos_elf_fail", err=snap.detail or snap.error)
        elif snap.error == "running":
            text = tr("diag.rtos_running")
        elif snap.error == "none":
            text = tr("diag.rtos_none")
        elif snap.error == "empty":
            text = tr("diag.rtos_empty", name=label)
        elif snap.error == "read_fail":
            text = tr("diag.read_fail", err=snap.detail or snap.error)
        elif snap.ok:
            text = tr("diag.rtos_ok", name=label, n=len(snap.threads))
        else:
            text = tr("diag.read_fail", err=snap.detail or snap.error)
        self.rtos_summary.setText(text)
        self.thread_table.setRowCount(len(snap.threads))
        for row, thread in enumerate(snap.threads):
            mark = tr("diag.current") if thread.current else ""
            priority = "—" if thread.priority is None else str(thread.priority)
            values = (
                mark,
                thread.name,
                thread.state,
                priority,
                f"0x{thread.ident:08X}",
            )
            for column, value in enumerate(values):
                self.thread_table.setItem(row, column, QTableWidgetItem(value))

    def _fill_flags(self, flags: tuple[FaultFlag, ...]) -> None:
        self.flag_table.setRowCount(len(flags))
        for row, flag in enumerate(flags):
            meaning = tr(f"diag.bit.{flag.name}")
            for column, value in enumerate((flag.group, flag.name, meaning)):
                self.flag_table.setItem(row, column, QTableWidgetItem(value))

    def _fill_frame(self, snap: FaultSnapshot) -> None:
        self.frame_table.setRowCount(len(snap.frame))
        for row, (name, value) in enumerate(snap.frame):
            symbol = snap.frame_pc_symbol if name == "pc" else ""
            for column, text in enumerate((name.upper(), f"0x{value:08X}", symbol)):
                self.frame_table.setItem(row, column, QTableWidgetItem(text))

    def _where(self, snap: FaultSnapshot) -> str:
        if snap.ipsr <= 0:
            return tr("diag.where_thread")
        if snap.ipsr >= 16:
            return tr("diag.exc.irq", n=snap.ipsr - 16)
        key = f"diag.exc.{snap.ipsr}"
        label = tr(key)
        return label if label != key else f"IPSR {snap.ipsr}"

    def _error_text(self, code: str, detail: str) -> str:
        if code == "not_connected":
            return tr("diag.not_connected")
        return tr("diag.read_fail", err=detail or code)

    @staticmethod
    def _set_headers(table: QTableWidget, labels: tuple[str, ...]) -> None:
        table.setHorizontalHeaderLabels(list(labels))
