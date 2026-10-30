"""STM32 UART system bootloader (AN3155) programming without a debug probe."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from etools.core.fw_image import SparseImage
from etools.core.models import FIRMWARE_EXTENSIONS
from etools.core.stm32_uart_boot import (
    BAUD_RATES,
    LINES,
    LineEntry,
    Stm32UartBoot,
    open_serial,
)
from etools.i18n import tr
from etools.ui.runtime import OpRunner
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.widgets.flash_tools_common import confirm, int_edit, parse_int, tool_button

PREFS_ID = "uart_boot"


def list_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    return [(p.device, f"{p.device} — {p.description}") for p in sorted(lp.comports())]


class UartBootPanel(QWidget):
    _progressed = Signal(str, int, int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        port_factory: Callable[[str, int], Any] | None = None,
        run_job: Callable[..., bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._host: Any = None
        self._open = port_factory or (lambda port, baud: open_serial(port, baud))
        # The UART bootloader needs no debug probe, so it runs on its own
        # runner instead of queueing behind (and blocking) probe jobs.
        self._runner = OpRunner(self)
        self._runner.busy_changed.connect(self._apply_busy)
        self._run_job = run_job or self._runner.start
        self._cancel = threading.Event()
        self._build()
        self._progressed.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self._load_prefs()

    def bind(self, host: Any) -> None:
        self._host = host

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.link_box = QGroupBox()
        self.link_box.setObjectName("ctxGroup")
        form = QFormLayout(self.link_box)
        prow = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(260)
        self.refresh_btn = tool_button("refresh")
        self.baud_combo = QComboBox()
        for baud in BAUD_RATES:
            self.baud_combo.addItem(str(baud), baud)
        self.baud_combo.setCurrentIndex(BAUD_RATES.index(115200))
        prow.addWidget(self.port_combo, 1)
        prow.addWidget(self.refresh_btn)
        prow.addWidget(self.baud_combo)
        self.port_label = QLabel()
        form.addRow(self.port_label, prow)

        erow = QHBoxLayout()
        self.boot_label = QLabel()
        self.boot_line = QComboBox()
        self.reset_label = QLabel()
        self.reset_line = QComboBox()
        for combo in (self.boot_line, self.reset_line):
            for line in LINES:
                combo.addItem("", line)
        self.boot_line.setCurrentIndex(LINES.index("rts"))
        self.reset_line.setCurrentIndex(LINES.index("dtr"))
        self.boot_invert = QCheckBox()
        self.reset_invert = QCheckBox()
        for w in (
            self.boot_label,
            self.boot_line,
            self.boot_invert,
            self.reset_label,
            self.reset_line,
            self.reset_invert,
        ):
            erow.addWidget(w)
        erow.addStretch(1)
        self.entry_label = QLabel()
        form.addRow(self.entry_label, erow)
        self.info_label = QLabel()
        self.info_label.setObjectName("hint")
        self.info_label.setWordWrap(True)
        form.addRow(self.info_label)
        root.addWidget(self.link_box)

        self.fw_box = QGroupBox()
        self.fw_box.setObjectName("ctxGroup")
        fw = QFormLayout(self.fw_box)
        frow = QHBoxLayout()
        self.fw_edit = QLineEdit()
        self.fw_browse = tool_button("open")
        self.fw_current = tool_button("program")
        frow.addWidget(self.fw_edit, 1)
        frow.addWidget(self.fw_browse)
        frow.addWidget(self.fw_current)
        self.fw_label = QLabel()
        fw.addRow(self.fw_label, frow)
        self.base_label = QLabel()
        self.base_edit = int_edit(0x0800_0000)
        fw.addRow(self.base_label, self.base_edit)
        orow = QHBoxLayout()
        self.erase_check = QCheckBox()
        self.erase_check.setChecked(True)
        self.verify_check = QCheckBox()
        self.verify_check.setChecked(True)
        self.run_check = QCheckBox()
        self.run_check.setChecked(True)
        for w in (self.erase_check, self.verify_check, self.run_check):
            orow.addWidget(w)
        orow.addStretch(1)
        fw.addRow(orow)
        root.addWidget(self.fw_box)

        self.read_box = QGroupBox()
        self.read_box.setObjectName("ctxGroup")
        rrow = QHBoxLayout(self.read_box)
        self.read_addr_label = QLabel()
        self.read_addr = int_edit(0x0800_0000)
        self.read_size_label = QLabel()
        self.read_size = int_edit(0x10000)
        self.read_btn = tool_button("read")
        for w in (
            self.read_addr_label,
            self.read_addr,
            self.read_size_label,
            self.read_size,
            self.read_btn,
        ):
            rrow.addWidget(w)
        rrow.addStretch(1)
        root.addWidget(self.read_box)

        bar = QHBoxLayout()
        self.connect_btn = tool_button("connect")
        self.program_btn = tool_button("program", kind="accent")
        self.erase_btn = tool_button("erase", kind="danger")
        self.unprotect_btn = tool_button("warning", kind="danger")
        self.protect_btn = tool_button("warning")
        self.wunprotect_btn = tool_button("refresh")
        self._action_btns = (
            self.connect_btn,
            self.program_btn,
            self.erase_btn,
            self.protect_btn,
            self.unprotect_btn,
            self.wunprotect_btn,
            self.read_btn,
        )
        for w in self._action_btns[:-1]:
            bar.addWidget(w)
        bar.addStretch(1)
        self.cancel_btn = tool_button("stop")
        self.cancel_btn.setEnabled(False)
        bar.addWidget(self.cancel_btn)
        root.addLayout(bar)
        root.addStretch(1)

        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.fw_browse.clicked.connect(self._browse_fw)
        self.fw_current.clicked.connect(self._use_current)
        self.connect_btn.clicked.connect(self.probe)
        self.program_btn.clicked.connect(self.program)
        self.erase_btn.clicked.connect(self._erase)
        self.read_btn.clicked.connect(self._read)
        self.cancel_btn.clicked.connect(self.cancel)
        self.protect_btn.clicked.connect(lambda: self._protect_cmd("rdp"))
        self.unprotect_btn.clicked.connect(lambda: self._protect_cmd("rup"))
        self.wunprotect_btn.clicked.connect(lambda: self._protect_cmd("wup"))
        self.refresh_ports()
        self.retranslate()

    def retranslate(self) -> None:
        self.link_box.setTitle(tr("uboot.link"))
        self.port_label.setText(tr("uboot.port"))
        self.refresh_btn.setToolTip(tr("uboot.refresh"))
        self.entry_label.setText(tr("uboot.entry"))
        self.boot_label.setText("BOOT0")
        self.reset_label.setText("NRST")
        for combo in (self.boot_line, self.reset_line):
            for i, line in enumerate(LINES):
                combo.setItemText(i, tr(f"uboot.line.{line}"))
        self.boot_invert.setText(tr("uboot.invert"))
        self.reset_invert.setText(tr("uboot.invert"))
        self.fw_box.setTitle(tr("uboot.firmware"))
        self.fw_label.setText(tr("prod.firmware"))
        self.fw_browse.setText(tr("prod.browse"))
        self.fw_current.setText(tr("prod.use_current"))
        self.base_label.setText(tr("prod.bin_base"))
        self.erase_check.setText(tr("uboot.mass_erase_first"))
        self.verify_check.setText(tr("prod.verify"))
        self.run_check.setText(tr("prod.run"))
        self.read_box.setTitle(tr("uboot.read_group"))
        self.read_addr_label.setText(tr("prod.address"))
        self.read_size_label.setText(tr("hex.size"))
        self.read_btn.setText(tr("uboot.read"))
        self.connect_btn.setText(tr("uboot.probe"))
        self.program_btn.setText(tr("uboot.program"))
        self.erase_btn.setText(tr("uboot.erase"))
        self.protect_btn.setText(tr("uboot.rdp"))
        self.unprotect_btn.setText(tr("uboot.rup"))
        self.wunprotect_btn.setText(tr("uboot.wup"))
        self.cancel_btn.setText(tr("prod.cancel"))
        if not self.info_label.text():
            self.info_label.setText(tr("uboot.hint"))

    def set_connected(self, connected: bool) -> None:
        """UART bootloader does not depend on the debug probe."""

    def _apply_busy(self, busy: bool) -> None:
        for btn in self._action_btns:
            btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def cancel(self) -> None:
        self._cancel.set()
        if self._host is not None:
            self._host.log(tr("prod.cancelling"))

    # -- prefs ------------------------------------------------------------

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(PREFS_ID)
        port = prefs.get("port")
        if isinstance(port, str) and port:
            idx = self.port_combo.findData(port)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
            else:
                self.port_combo.setEditText(port)
        for combo, key in (
            (self.baud_combo, "baud"),
            (self.boot_line, "boot_line"),
            (self.reset_line, "reset_line"),
        ):
            idx = combo.findData(prefs.get(key))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.boot_invert.setChecked(bool(prefs.get("boot_invert")))
        self.reset_invert.setChecked(bool(prefs.get("reset_invert")))
        if isinstance(prefs.get("firmware"), str):
            self.fw_edit.setText(prefs["firmware"])

    def _save_prefs(self) -> None:
        save_tool_prefs(
            PREFS_ID,
            {
                "port": self.port_name(),
                "baud": int(self.baud_combo.currentData()),
                "boot_line": str(self.boot_line.currentData()),
                "reset_line": str(self.reset_line.currentData()),
                "boot_invert": self.boot_invert.isChecked(),
                "reset_invert": self.reset_invert.isChecked(),
                "firmware": self.fw_edit.text().strip(),
            },
        )

    # -- helpers ----------------------------------------------------------

    def refresh_ports(self) -> None:
        current = self.port_name()
        self.port_combo.clear()
        for device, label in list_ports():
            self.port_combo.addItem(label, device)
        idx = self.port_combo.findData(current)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)
        elif current:
            self.port_combo.setEditText(current)

    def port_name(self) -> str:
        data = self.port_combo.currentData()
        if data and self.port_combo.currentText() == self.port_combo.itemText(
            self.port_combo.currentIndex()
        ):
            return str(data)
        return self.port_combo.currentText().split(" — ", 1)[0].strip()

    def entry(self) -> LineEntry:
        return LineEntry(
            boot_line=str(self.boot_line.currentData()),
            reset_line=str(self.reset_line.currentData()),
            boot_invert=self.boot_invert.isChecked(),
            reset_invert=self.reset_invert.isChecked(),
        )

    def _browse_fw(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("uboot.firmware"), self.fw_edit.text(), FIRMWARE_EXTENSIONS
        )
        if path:
            self.fw_edit.setText(path)

    def _use_current(self) -> None:
        if self._host is not None and self._host.firmware_path():
            self.fw_edit.setText(self._host.firmware_path())

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        if self._host is None:
            return
        pct = int(done * 100 / total) if total else 0
        self._host.progress(pct, f"{tr(f'uboot.stage.{stage}')} {pct}%")

    def _session(self, job: Callable[[Stm32UartBoot, Any], Any], *, leave: bool = False):
        """Open the port, enter the bootloader, run ``job`` and close."""
        port_name = self.port_name()
        baud = int(self.baud_combo.currentData())
        entry = self.entry()
        opener = self._open

        def work():
            port = opener(port_name, baud)
            try:
                entry.enter(port)
                boot = Stm32UartBoot(port)
                boot.connect()
                result = job(boot, port)
                if leave:
                    entry.leave(port)
                return boot.info, result
            finally:
                try:
                    port.close()
                except Exception:
                    pass

        return work

    def _run(self, work, done: Callable[[Any, Any], None], label: str) -> None:
        if self._host is None:
            return
        if not self.port_name():
            self.info_label.setText(tr("uboot.no_port"))
            return
        self._save_prefs()

        def on_ok(pair) -> None:
            info, result = pair
            self._show_info(info)
            done(info, result)

        def on_err(msg: str) -> None:
            self.info_label.setText(tr("uboot.fail", err=msg))
            self._host.log(tr("uboot.fail", err=msg), True)
            self._host.progress(-1)

        self._cancel.clear()
        self._host.log(tr("uboot.start", op=label, port=self.port_name()))
        if not self._run_job(work, on_ok, on_err):
            self._host.log(tr("log.busy"), True)

    def _show_info(self, info) -> None:
        if info is None:
            return
        cmds = " ".join(f"{c:02X}" for c in info.commands)
        self.info_label.setText(
            tr("uboot.info", ver=info.version_text(), pid=f"0x{info.pid:03X}", cmds=cmds)
        )

    # -- operations -------------------------------------------------------

    def probe(self) -> None:
        work = self._session(lambda boot, port: None)
        self._run(work, lambda info, _r: self._host.log(self.info_label.text()), tr("uboot.probe"))

    def program(self) -> None:
        path = self.fw_edit.text().strip()
        if not path or not Path(path).is_file():
            self.info_label.setText(tr("prod.no_firmware"))
            return
        try:
            base = parse_int(self.base_edit.text(), 0x0800_0000)
            image = SparseImage.from_file(path, bin_base=base)
        except (OSError, ValueError, RuntimeError) as exc:
            self.info_label.setText(str(exc))
            return
        erase = "mass" if self.erase_check.isChecked() else "none"
        verify = self.verify_check.isChecked()
        run = self.run_check.isChecked()
        emit = self._progressed.emit
        cancelled = self._cancel.is_set
        entry = self.entry()
        # Reset into the app via the control lines when both are wired,
        # otherwise jump there with the Go command.
        leave = run and entry.boot_line != "none" and entry.reset_line != "none"
        go = run and not leave

        def job(boot: Stm32UartBoot, port):
            written = boot.program(
                image, erase=erase, verify=verify, progress=emit, cancelled=cancelled
            )
            if go:
                boot.go(image.start)
            return written

        def done(_info, written) -> None:
            self._host.progress(100, tr("uboot.program_ok", n=f"{written:,}"))
            self._host.log(tr("uboot.program_ok", n=f"{written:,}"))

        self._run(self._session(job, leave=leave), done, tr("uboot.program"))

    def _erase(self) -> None:
        if not confirm(self, tr("uboot.erase"), tr("uboot.erase_confirm"), danger=True):
            return
        work = self._session(lambda boot, port: boot.mass_erase())
        self._run(work, lambda *_: self._host.log(tr("uboot.erase_ok")), tr("uboot.erase"))

    def _read(self) -> None:
        try:
            addr = parse_int(self.read_addr.text())
            size = parse_int(self.read_size.text())
        except ValueError:
            self.info_label.setText(tr("img.bad_range"))
            return
        if not 0 < size <= 16 * 1024 * 1024:
            self.info_label.setText(tr("img.bad_range"))
            return
        out, _ = QFileDialog.getSaveFileName(
            self, tr("uboot.read"), "uart_dump.bin", "Binary (*.bin)"
        )
        if not out:
            return
        emit = self._progressed.emit
        cancelled = self._cancel.is_set

        def job(boot: Stm32UartBoot, port):
            data = boot.read_range(addr, size, progress=emit, cancelled=cancelled)
            Path(out).write_bytes(data)
            return len(data)

        def done(_info, n) -> None:
            self._host.progress(100, tr("uboot.read_ok", n=f"{n:,}", path=out))
            self._host.log(tr("uboot.read_ok", n=f"{n:,}", path=out))

        self._run(self._session(job), done, tr("uboot.read"))

    def _protect_cmd(self, which: str) -> None:
        texts = {
            "rdp": tr("uboot.rdp_confirm"),
            "rup": tr("uboot.rup_confirm"),
            "wup": tr("uboot.wup_confirm"),
        }
        if not confirm(self, tr(f"uboot.{which}"), texts[which], danger=which != "wup"):
            return

        method = {
            "rdp": "readout_protect",
            "rup": "readout_unprotect",
            "wup": "write_unprotect",
        }[which]

        def job(boot: Stm32UartBoot, port):
            getattr(boot, method)()

        self._run(
            self._session(job),
            lambda *_: self._host.log(tr("uboot.cmd_ok", op=tr(f"uboot.{which}"))),
            tr(f"uboot.{which}"),
        )
