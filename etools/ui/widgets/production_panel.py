"""One-click production programming with serial number / UID injection and CSV log."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from etools.core.models import FIRMWARE_EXTENSIONS
from etools.core.production import (
    SERIAL_FORMATS,
    ProductionPlan,
    ProductionResult,
    ProductionRunner,
    SerialSpec,
    UidSpec,
)
from etools.i18n import tr
from etools.ui.icons import icon
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.widgets.flash_tools_common import confirm, int_edit, parse_int, tool_button

PREFS_ID = "production"
_INT_MAX = 2_147_483_647


class ProductionPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host: Any = None
        self._connected = False
        self._running = False
        self._passed = 0
        self._failed = 0
        self._protect_confirmed = False
        self._cancel: threading.Event | None = None
        self._build()
        self._load_prefs()

    def bind(self, host: Any) -> None:
        self._host = host

    # -- layout -----------------------------------------------------------

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(8)

        self.fw_box = QGroupBox()
        self.fw_box.setObjectName("ctxGroup")
        fw = QFormLayout(self.fw_box)
        row = QHBoxLayout()
        self.fw_edit = QLineEdit()
        self.fw_browse = tool_button("open")
        self.fw_use_current = tool_button("program")
        row.addWidget(self.fw_edit, 1)
        row.addWidget(self.fw_browse)
        row.addWidget(self.fw_use_current)
        self.fw_label = QLabel()
        fw.addRow(self.fw_label, row)
        self.base_label = QLabel()
        self.base_edit = int_edit(0x0800_0000)
        fw.addRow(self.base_label, self.base_edit)
        self.erase_label = QLabel()
        self.erase_combo = QComboBox()
        self.erase_combo.addItem("", "sector")
        self.erase_combo.addItem("", "chip")
        fw.addRow(self.erase_label, self.erase_combo)
        opts = QHBoxLayout()
        self.incremental_check = QCheckBox()
        self.verify_check = QCheckBox()
        self.verify_check.setChecked(True)
        self.protect_check = QCheckBox()
        self.run_check = QCheckBox()
        self.run_check.setChecked(True)
        for w in (self.verify_check, self.incremental_check, self.protect_check, self.run_check):
            opts.addWidget(w)
        opts.addStretch(1)
        fw.addRow(opts)
        left.addWidget(self.fw_box)

        self.sn_box = QGroupBox()
        self.sn_box.setObjectName("ctxGroup")
        self.sn_box.setCheckable(True)
        self.sn_box.setChecked(False)
        sn = QFormLayout(self.sn_box)
        self.sn_addr_label = QLabel()
        self.sn_addr = int_edit(0x0800_0000)
        sn.addRow(self.sn_addr_label, self.sn_addr)
        self.sn_fmt_label = QLabel()
        self.sn_fmt = QComboBox()
        for fmt in SERIAL_FORMATS:
            self.sn_fmt.addItem("", fmt)
        sn.addRow(self.sn_fmt_label, self.sn_fmt)
        self.sn_width_label = QLabel()
        self.sn_width = QSpinBox()
        self.sn_width.setRange(1, 20)
        self.sn_width.setValue(8)
        self.sn_prefix = QLineEdit()
        self.sn_prefix.setMaxLength(16)
        wrow = QHBoxLayout()
        wrow.addWidget(self.sn_width)
        self.sn_prefix_label = QLabel()
        wrow.addWidget(self.sn_prefix_label)
        wrow.addWidget(self.sn_prefix, 1)
        sn.addRow(self.sn_width_label, wrow)
        self.sn_next_label = QLabel()
        self.sn_next = QSpinBox()
        self.sn_next.setRange(0, _INT_MAX)
        self.sn_next.setValue(1)
        self.sn_step = QSpinBox()
        self.sn_step.setRange(1, 1_000_000)
        nrow = QHBoxLayout()
        nrow.addWidget(self.sn_next, 1)
        self.sn_step_label = QLabel()
        nrow.addWidget(self.sn_step_label)
        nrow.addWidget(self.sn_step)
        sn.addRow(self.sn_next_label, nrow)
        self.sn_preview = QLabel()
        self.sn_preview.setObjectName("hint")
        sn.addRow(self.sn_preview)
        left.addWidget(self.sn_box)

        self.uid_box = QGroupBox()
        self.uid_box.setObjectName("ctxGroup")
        self.uid_box.setCheckable(True)
        self.uid_box.setChecked(False)
        uid = QFormLayout(self.uid_box)
        self.uid_addr_label = QLabel()
        self.uid_addr = int_edit(0x0800_0000)
        uid.addRow(self.uid_addr_label, self.uid_addr)
        left.addWidget(self.uid_box)

        self.log_box = QGroupBox()
        self.log_box.setObjectName("ctxGroup")
        lg = QHBoxLayout(self.log_box)
        self.log_edit = QLineEdit()
        self.log_browse = tool_button("save")
        lg.addWidget(self.log_edit, 1)
        lg.addWidget(self.log_browse)
        left.addWidget(self.log_box)
        left.addStretch(1)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.start_btn = tool_button("program", kind="accent")
        self.start_btn.setFixedHeight(44)
        right.addWidget(self.start_btn)
        self.cancel_btn = tool_button("stop")
        right.addWidget(self.cancel_btn)
        self.result_label = QLabel("—")
        self.result_label.setObjectName("prodResult")
        self.result_label.setStyleSheet("font-size: 28px; font-weight: 700;")
        right.addWidget(self.result_label)
        self.stats_label = QLabel()
        right.addWidget(self.stats_label)
        self.steps_list = QListWidget()
        right.addWidget(self.steps_list, 1)
        self.reset_stats_btn = tool_button("clear")
        right.addWidget(self.reset_stats_btn)
        root.addLayout(right, 2)

        self.fw_browse.clicked.connect(self._browse_fw)
        self.fw_use_current.clicked.connect(self._use_current_fw)
        self.log_browse.clicked.connect(self._browse_log)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        self.erase_combo.currentIndexChanged.connect(self._erase_changed)
        self.reset_stats_btn.clicked.connect(self._reset_stats)
        self.sn_fmt.currentIndexChanged.connect(self._update_preview)
        self.sn_width.valueChanged.connect(self._update_preview)
        self.sn_next.valueChanged.connect(self._update_preview)
        self.sn_prefix.textChanged.connect(self._update_preview)
        self.retranslate()
        self._apply_enabled()

    def retranslate(self) -> None:
        self.fw_box.setTitle(tr("prod.firmware_group"))
        self.fw_label.setText(tr("prod.firmware"))
        self.fw_browse.setText(tr("prod.browse"))
        self.fw_use_current.setText(tr("prod.use_current"))
        self.base_label.setText(tr("prod.bin_base"))
        self.erase_label.setText(tr("prod.erase"))
        self.erase_combo.setItemText(0, tr("prod.erase_sector"))
        self.erase_combo.setItemText(1, tr("prod.erase_chip"))
        self.verify_check.setText(tr("prod.verify"))
        self.incremental_check.setText(tr("flash.incremental"))
        self.protect_check.setText(tr("prod.protect"))
        self.run_check.setText(tr("prod.run"))
        self.sn_box.setTitle(tr("prod.serial_group"))
        self.sn_addr_label.setText(tr("prod.address"))
        self.sn_fmt_label.setText(tr("prod.format"))
        for i, fmt in enumerate(SERIAL_FORMATS):
            self.sn_fmt.setItemText(i, tr(f"prod.fmt.{fmt}"))
        self.sn_width_label.setText(tr("prod.width"))
        self.sn_prefix_label.setText(tr("prod.prefix"))
        self.sn_next_label.setText(tr("prod.next"))
        self.sn_step_label.setText(tr("prod.step"))
        self.uid_box.setTitle(tr("prod.uid_group"))
        self.uid_addr_label.setText(tr("prod.address"))
        self.log_box.setTitle(tr("prod.log_group"))
        self.log_edit.setPlaceholderText(tr("prod.log_placeholder"))
        self.log_browse.setText(tr("prod.browse"))
        self.start_btn.setText(tr("prod.start"))
        self.cancel_btn.setText(tr("prod.cancel"))
        self.cancel_btn.setToolTip(tr("prod.cancel_tip"))
        self.reset_stats_btn.setText(tr("prod.reset_stats"))
        self._update_stats()
        self._update_preview()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        self.start_btn.setEnabled(self._connected and not self._running)
        self.cancel_btn.setEnabled(self._running)

    def _erase_changed(self, *_args) -> None:
        chip = self.erase_combo.currentData() == "chip"
        if chip:
            self.incremental_check.setChecked(False)
        self.incremental_check.setEnabled(not chip)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            if self._host is not None:
                self._host.log(tr("prod.cancelling"))

    # -- prefs ------------------------------------------------------------

    def plan(self) -> ProductionPlan:
        return ProductionPlan(
            firmware=self.fw_edit.text().strip(),
            bin_base=parse_int(self.base_edit.text(), 0x0800_0000),
            erase=str(self.erase_combo.currentData()),
            incremental=self.incremental_check.isChecked(),
            verify=self.verify_check.isChecked(),
            protect=self.protect_check.isChecked(),
            run_after=self.run_check.isChecked(),
            serial=SerialSpec(
                enabled=self.sn_box.isChecked(),
                address=parse_int(self.sn_addr.text(), 0),
                fmt=str(self.sn_fmt.currentData()),
                width=self.sn_width.value(),
                prefix=self.sn_prefix.text(),
                start=self.sn_next.value(),
                step=self.sn_step.value(),
            ),
            uid=UidSpec(
                enabled=self.uid_box.isChecked(), address=parse_int(self.uid_addr.text(), 0)
            ),
            log_path=self.log_edit.text().strip(),
        )

    def _load_prefs(self) -> None:
        data = load_tool_prefs(PREFS_ID).get("plan")
        if not isinstance(data, dict):
            return
        try:
            plan = ProductionPlan.from_dict(data)
        except (TypeError, ValueError):
            return
        self.fw_edit.setText(plan.firmware)
        self.base_edit.setText(f"0x{plan.bin_base:08X}")
        idx = self.erase_combo.findData(plan.erase)
        self.erase_combo.setCurrentIndex(max(0, idx))
        self.incremental_check.setChecked(plan.incremental)
        self.verify_check.setChecked(plan.verify)
        self.protect_check.setChecked(plan.protect)
        self.run_check.setChecked(plan.run_after)
        s = plan.serial
        self.sn_box.setChecked(s.enabled)
        self.sn_addr.setText(f"0x{s.address:08X}")
        self.sn_fmt.setCurrentIndex(max(0, self.sn_fmt.findData(s.fmt)))
        self.sn_width.setValue(int(s.width))
        self.sn_prefix.setText(s.prefix)
        self.sn_next.setValue(max(0, min(_INT_MAX, int(s.start))))
        self.sn_step.setValue(max(1, int(s.step)))
        self.uid_box.setChecked(plan.uid.enabled)
        self.uid_addr.setText(f"0x{plan.uid.address:08X}")
        self.log_edit.setText(plan.log_path)
        self._erase_changed()
        self._update_preview()

    def _save_prefs(self, plan: ProductionPlan) -> None:
        save_tool_prefs(PREFS_ID, {"plan": plan.to_dict()})

    # -- actions ----------------------------------------------------------

    def _browse_fw(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("prod.firmware"), self.fw_edit.text(), FIRMWARE_EXTENSIONS
        )
        if path:
            self.fw_edit.setText(path)

    def _use_current_fw(self) -> None:
        if self._host is not None:
            path = self._host.firmware_path()
            if path:
                self.fw_edit.setText(path)

    def _browse_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("prod.log_group"), self.log_edit.text() or "production.csv", "CSV (*.csv)"
        )
        if path:
            self.log_edit.setText(path)

    def _update_preview(self, *_args) -> None:
        try:
            spec = SerialSpec(
                enabled=True,
                fmt=str(self.sn_fmt.currentData()),
                width=self.sn_width.value(),
                prefix=self.sn_prefix.text(),
            )
            raw = spec.render(self.sn_next.value())
            self.sn_preview.setText(
                tr("prod.preview", text=spec.text(self.sn_next.value()), raw=raw.hex(" ").upper())
            )
        except Exception as exc:
            self.sn_preview.setText(str(exc))

    def _update_stats(self) -> None:
        self.stats_label.setText(tr("prod.stats", ok=self._passed, fail=self._failed))

    def _reset_stats(self) -> None:
        self._passed = self._failed = 0
        self._update_stats()

    def start(self) -> None:
        if self._host is None or self._running:
            return
        try:
            plan = self.plan()
        except ValueError as exc:
            self._show_error(str(exc))
            return
        if not plan.firmware or not Path(plan.firmware).is_file():
            self._show_error(tr("prod.no_firmware"))
            return
        if plan.protect and not self._protect_confirmed:
            if not confirm(self, tr("prod.protect"), tr("prod.protect_confirm"), danger=True):
                return
            self._protect_confirmed = True
        self._save_prefs(plan)
        serial_no = plan.serial.start if plan.serial.enabled else None
        service = self._host.service

        cancel = threading.Event()
        self._cancel = cancel

        def work() -> ProductionResult:
            return ProductionRunner(service, plan).run(serial_no, cancelled=cancel.is_set)

        def on_ok(result: ProductionResult) -> None:
            self._running = False
            self._apply_enabled()
            self._show_result(result)
            if result.ok:
                self._passed += 1
            else:
                self._failed += 1
            if plan.serial.enabled and result.serial_consumed:
                self.sn_next.setValue(min(_INT_MAX, plan.serial.start + plan.serial.step))
                self._save_prefs(self.plan())
                if not result.ok:
                    self._host.log(tr("prod.sn_consumed", sn=result.serial_text), True)
            self._update_stats()

        def on_err(msg: str) -> None:
            self._running = False
            self._apply_enabled()
            self._failed += 1
            self._update_stats()
            self._show_error(msg)

        self.steps_list.clear()
        self.result_label.setText("…")
        self.result_label.setStyleSheet("font-size: 28px; font-weight: 700;")
        sn = f" SN={plan.serial.text(serial_no)}" if serial_no is not None else ""
        self._host.log(tr("prod.started", name=Path(plan.firmware).name) + sn)
        if plan.protect:
            # Enabling RDP may reload option bytes and re-open the session.
            self._host.stop_debug_views()
        self._running = True
        self._apply_enabled()
        if not self._host.run_job(work, on_ok, on_err):
            self._running = False
            self._apply_enabled()
            self.result_label.setText("—")

    def _show_error(self, msg: str) -> None:
        self.result_label.setText("FAIL")
        self.result_label.setStyleSheet("font-size: 28px; font-weight: 700; color: #e5484d;")
        self.steps_list.addItem(QListWidgetItem(icon("error"), msg))
        if self._host is not None:
            self._host.log(msg, True)

    def _show_result(self, result: ProductionResult) -> None:
        color = "#30a46c" if result.ok else "#e5484d"
        self.result_label.setText("PASS" if result.ok else "FAIL")
        self.result_label.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {color};")
        self.steps_list.clear()
        for step in result.steps:
            text = f"{tr(f'prod.step.{step.name}')}  {step.seconds:.2f}s  {step.detail}"
            self.steps_list.addItem(
                QListWidgetItem(icon("success" if step.ok else "error"), text.strip())
            )
        if result.error:
            self.steps_list.addItem(QListWidgetItem(icon("warning"), result.error))
        summary = tr(
            "prod.done",
            result="PASS" if result.ok else "FAIL",
            sn=result.serial_text or "-",
            uid=result.uid_hex or "-",
            sec=f"{result.duration_s:.2f}",
        )
        self._host.log(summary, not result.ok)
