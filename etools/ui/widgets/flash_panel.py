"""Flash operation panel — loads flash_panel.ui."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from etools.config import get_config, save_config
from etools.core.models import FIRMWARE_EXTENSIONS
from etools.ui.icons import set_button_icon
from etools.ui.ui_loader import embed_form


class FlashPanel(QFrame):
    """Firmware path and flash operations."""

    program_requested = Signal(str, bool)
    erase_requested = Signal()
    read_requested = Signal(int, int, str)
    verify_requested = Signal(str)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FlashPanelHost")
        self.setStyleSheet("QFrame#FlashPanelHost { border: none; background: transparent; }")
        self._ops_connected = False
        self._busy = False
        self._form = embed_form(self, "flash_panel")
        self._form.setObjectName("panel")
        self._bind()
        self._init_state()
        self._wire()
        self.set_ops_enabled(False)

    def _bind(self) -> None:
        f = self._form
        self.fw_edit: QLineEdit = f.findChild(QLineEdit, "fwEdit")
        self.browse_btn: QPushButton = f.findChild(QPushButton, "browseBtn")
        self.fw_info: QLabel = f.findChild(QLabel, "fwInfo")
        self.verify_check: QCheckBox = f.findChild(QCheckBox, "verifyCheck")
        self.program_btn: QPushButton = f.findChild(QPushButton, "programBtn")
        self.erase_btn: QPushButton = f.findChild(QPushButton, "eraseBtn")
        self.verify_btn: QPushButton = f.findChild(QPushButton, "verifyBtn")
        self.reset_btn: QPushButton = f.findChild(QPushButton, "resetBtn")
        self.addr_edit: QSpinBox = f.findChild(QSpinBox, "addrEdit")
        self.size_edit: QSpinBox = f.findChild(QSpinBox, "sizeEdit")
        self.read_btn: QPushButton = f.findChild(QPushButton, "readBtn")
        for n, w in [
            ("fwEdit", self.fw_edit),
            ("browseBtn", self.browse_btn),
            ("programBtn", self.program_btn),
            ("eraseBtn", self.erase_btn),
            ("verifyBtn", self.verify_btn),
            ("resetBtn", self.reset_btn),
            ("addrEdit", self.addr_edit),
            ("sizeEdit", self.size_edit),
            ("readBtn", self.read_btn),
            ("verifyCheck", self.verify_check),
            ("fwInfo", self.fw_info),
        ]:
            if w is None:
                raise RuntimeError(f"flash_panel.ui missing widget: {n}")

    def _init_state(self) -> None:
        from PySide6.QtWidgets import QSizePolicy

        self.browse_btn.setObjectName("ghost")
        self.program_btn.setObjectName("accent")
        self.erase_btn.setObjectName("danger")
        self.fw_info.setObjectName("hint")

        # Keep label glued to its spin: no horizontal expansion in the read row.
        for spin, w in ((self.addr_edit, 140), (self.size_edit, 120)):
            spin.setFixedWidth(w)
            spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            spin.setFixedHeight(28)

        # Don't reserve a blank line when no firmware is loaded.
        self.fw_info.setMinimumHeight(0)
        self.fw_info.setMaximumHeight(0)

        set_button_icon(self.browse_btn, "open", 16)
        set_button_icon(self.program_btn, "program", 16)
        set_button_icon(self.erase_btn, "erase", 16)
        set_button_icon(self.verify_btn, "verify", 16)
        set_button_icon(self.reset_btn, "reset", 16)
        set_button_icon(self.read_btn, "read", 16)

        cfg = get_config()
        if cfg.last_firmware:
            self.fw_edit.setText(cfg.last_firmware)
        self.verify_check.setChecked(cfg.verify_after_program)
        self._update_fw_info()

    def _wire(self) -> None:
        self.browse_btn.clicked.connect(self._browse)
        self.program_btn.clicked.connect(self._on_program)
        self.erase_btn.clicked.connect(self.erase_requested.emit)
        self.verify_btn.clicked.connect(self._on_verify)
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.read_btn.clicked.connect(self._on_read)
        self.fw_edit.textChanged.connect(lambda _=None: self._update_fw_info())

    def _browse(self) -> None:
        start = str(Path(self.fw_edit.text()).parent) if self.fw_edit.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "选择固件", start, FIRMWARE_EXTENSIONS)
        if path:
            self.fw_edit.setText(path)
            cfg = get_config()
            cfg.last_firmware = path
            save_config()

    def _update_fw_info(self) -> None:
        p = Path(self.fw_edit.text().strip())
        if p.is_file():
            size = p.stat().st_size
            self.fw_info.setText(
                f"{p.name} · {size:,} bytes · {p.suffix.lstrip('.').upper()}"
            )
            self.fw_info.setMaximumHeight(16777215)
        else:
            self.fw_info.setText("")
            self.fw_info.setMaximumHeight(0)

    def firmware_path(self) -> str:
        return self.fw_edit.text().strip()

    def set_ops_enabled(self, enabled: bool) -> None:
        self._ops_connected = enabled
        self._apply_enabled()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        enabled = self._ops_connected and not self._busy
        for w in (
            self.program_btn,
            self.erase_btn,
            self.verify_btn,
            self.reset_btn,
            self.read_btn,
        ):
            w.setEnabled(enabled)

    def _on_program(self) -> None:
        path = self.firmware_path()
        if not path:
            return
        verify = self.verify_check.isChecked()
        cfg = get_config()
        cfg.verify_after_program = verify
        cfg.last_firmware = path
        save_config()
        self.program_requested.emit(path, verify)

    def _on_verify(self) -> None:
        path = self.firmware_path()
        if path:
            self.verify_requested.emit(path)

    def _on_read(self) -> None:
        addr = int(self.addr_edit.value())
        size = int(self.size_edit.value())
        if size <= 0:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "保存读取结果", "flash_dump.bin", "Binary (*.bin)"
        )
        if out:
            self.read_requested.emit(addr, size, out)
