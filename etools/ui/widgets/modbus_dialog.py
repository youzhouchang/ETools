"""Modbus RTU / TCP / ASCII request builder dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from etools.core import modbus
from etools.i18n import tr


class ModbusDialog(QDialog):
    """Build a Modbus frame (RTU / TCP / ASCII); send via *send_bytes*."""

    def __init__(
        self, send_bytes, parent: QWidget | None = None, mode: str = modbus.MODE_RTU
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("modbus.title"))
        self.setMinimumWidth(460)
        self._send_bytes = send_bytes

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self.mode = QComboBox()
        self.mode.addItem(tr("modbus.mode.rtu"), modbus.MODE_RTU)
        self.mode.addItem(tr("modbus.mode.tcp"), modbus.MODE_TCP)
        self.mode.addItem(tr("modbus.mode.ascii"), modbus.MODE_ASCII)
        idx = self.mode.findData(mode)
        self.mode.setCurrentIndex(max(0, idx))

        self.slave = QSpinBox()
        self.slave.setRange(0, 255)
        self.slave.setValue(1)
        self.lbl_slave = QLabel(tr("modbus.slave"))

        self.func = QComboBox()
        self.func.addItem(tr("modbus.fc.read_holding"), modbus.FC_READ_HOLDING)
        self.func.addItem(tr("modbus.fc.read_input"), modbus.FC_READ_INPUT)
        self.func.addItem(tr("modbus.fc.read_coils"), modbus.FC_READ_COILS)
        self.func.addItem(tr("modbus.fc.read_discrete"), modbus.FC_READ_DISCRETE)
        self.func.addItem(tr("modbus.fc.write_reg"), modbus.FC_WRITE_REGISTER)
        self.func.addItem(tr("modbus.fc.write_coil"), modbus.FC_WRITE_COIL)

        self.addr = QSpinBox()
        self.addr.setRange(0, 65535)
        self.count = QSpinBox()
        self.count.setRange(1, 125)
        self.count.setValue(1)
        self.value = QLineEdit("0")
        self.value.setPlaceholderText("0x0001")

        form.addRow(tr("modbus.mode"), self.mode)
        form.addRow(self.lbl_slave, self.slave)
        form.addRow(tr("modbus.func"), self.func)
        form.addRow(tr("modbus.addr"), self.addr)
        form.addRow(tr("modbus.count"), self.count)
        form.addRow(tr("modbus.value"), self.value)
        root.addLayout(form)

        self.preview = QLabel("")
        self.preview.setObjectName("mutedLabel")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(
            self.preview.textInteractionFlags()
            | self.preview.textInteractionFlags().TextSelectableByMouse
        )
        root.addWidget(self.preview)

        row = QHBoxLayout()
        self.build_btn = QPushButton(tr("modbus.preview"))
        self.build_btn.setObjectName("ghost")
        self.send_btn = QPushButton(tr("modbus.send"))
        self.send_btn.setObjectName("accent")
        row.addWidget(self.build_btn)
        row.addWidget(self.send_btn)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.build_btn.clicked.connect(self._refresh_preview)
        self.send_btn.clicked.connect(self._do_send)
        self.mode.currentIndexChanged.connect(self._on_mode_changed)
        for w in (self.slave, self.addr, self.count):
            w.valueChanged.connect(self._refresh_preview)
        self.func.currentIndexChanged.connect(self._refresh_preview)
        self.value.textChanged.connect(self._refresh_preview)
        self._on_mode_changed()
        self._refresh_preview()

    def _on_mode_changed(self) -> None:
        mode = self.current_mode()
        is_tcp = mode == modbus.MODE_TCP
        self.lbl_slave.setText(tr("modbus.unit") if is_tcp else tr("modbus.slave"))
        self.slave.setRange(0, 255 if is_tcp else 247)
        self._refresh_preview()

    def current_mode(self) -> str:
        return str(self.mode.currentData() or modbus.MODE_RTU)

    def _parse_value(self) -> int:
        text = self.value.text().strip() or "0"
        return int(text, 0)

    def build_pdu(self) -> bytes:
        addr = self.addr.value()
        count = self.count.value()
        func = int(self.func.currentData())
        if func == modbus.FC_READ_HOLDING:
            return modbus.build_pdu_read(modbus.FC_READ_HOLDING, addr, count)
        if func == modbus.FC_READ_INPUT:
            return modbus.build_pdu_read(modbus.FC_READ_INPUT, addr, count)
        if func == modbus.FC_READ_COILS:
            return modbus.build_pdu_read(modbus.FC_READ_COILS, addr, count)
        if func == modbus.FC_READ_DISCRETE:
            return modbus.build_pdu_read(modbus.FC_READ_DISCRETE, addr, count)
        if func == modbus.FC_WRITE_REGISTER:
            return modbus.build_pdu_write_register(addr, self._parse_value())
        if func == modbus.FC_WRITE_COIL:
            on = self._parse_value() not in (0, 0x0000)
            return modbus.build_pdu_write_coil(addr, on)
        raise ValueError(f"unsupported function {func}")

    def build_frame(self) -> bytes:
        return modbus.frame(self.current_mode(), self.slave.value(), self.build_pdu())

    def _refresh_preview(self) -> None:
        try:
            raw = self.build_frame()
        except ValueError as exc:
            self.preview.setText(str(exc))
            self.send_btn.setEnabled(False)
            return
        mode = self.current_mode()
        if mode == modbus.MODE_ASCII:
            self.preview.setText(raw.decode("ascii", errors="replace"))
        else:
            self.preview.setText(raw.hex(" ").upper())
        self.send_btn.setEnabled(True)

    def _do_send(self) -> None:
        try:
            raw = self.build_frame()
        except ValueError:
            return
        self._send_bytes(raw)
        self.accept()
