"""Target information panel — loads target_info_panel.ui."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from etools.core.models import TargetDetails
from etools.ui.icons import set_button_icon
from etools.ui.ui_loader import embed_form


class TargetInfoPanel(QFrame):
    """Shows live MCU inventory after connect."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TargetInfoHost")
        self.setStyleSheet("QFrame#TargetInfoHost { border: none; background: transparent; }")
        self._form = embed_form(self, "target_info_panel")
        self._form.setObjectName("panel")
        self._bind()
        self.clear()

    def _bind(self) -> None:
        f = self._form
        self.refresh_btn: QPushButton = f.findChild(QPushButton, "refreshBtn")
        self.refresh_btn.setObjectName("ghost")
        set_button_icon(self.refresh_btn, "refresh", 16)

        def val(name: str) -> QLabel:
            w = f.findChild(QLabel, name)
            if w is None:
                raise RuntimeError(f"target_info_panel.ui missing {name}")
            w.setObjectName("infoValue")
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            w.setWordWrap(True)
            return w

        self.val_target = val("valTarget")
        self.val_cpu = val("valCpu")
        self.val_vendor = val("valVendor")
        self.val_uid = val("valUid")
        self.val_devid = val("valDevId")
        self.val_flash = val("valFlash")
        self.val_ram = val("valRam")
        self.val_volt = val("valVolt")
        self.val_probe = val("valProbe")
        self.val_wire = val("valWire")

        hint = f.findChild(QLabel, "hintLabel")
        if hint is not None:
            hint.setObjectName("hint")

        for name in (
            "keyTarget",
            "keyCpu",
            "keyVendor",
            "keyUid",
            "keyDevId",
            "keyFlash",
            "keyRam",
            "keyVolt",
            "keyProbe",
            "keyWire",
        ):
            k = f.findChild(QLabel, name)
            if k is not None:
                k.setObjectName("hint")

    def set_refresh_enabled(self, enabled: bool) -> None:
        self.refresh_btn.setEnabled(enabled)

    def clear(self) -> None:
        for w in (
            self.val_target,
            self.val_cpu,
            self.val_vendor,
            self.val_uid,
            self.val_devid,
            self.val_flash,
            self.val_ram,
            self.val_volt,
            self.val_probe,
            self.val_wire,
        ):
            w.setText("—")
        self.set_refresh_enabled(False)

    def apply(self, d: TargetDetails | None) -> None:
        if d is None:
            self.clear()
            return
        self.val_target.setText(d.target_name or "—")
        self.val_cpu.setText(d.cpu or d.core_name or "—")
        self.val_vendor.setText(d.vendor or "—")
        uid = d.uid if d.uid_ok else "—"
        if d.uid_ok and len(d.uid) == 24:
            uid = f"{d.uid[0:8]} {d.uid[8:16]} {d.uid[16:24]}"
        self.val_uid.setText(uid)
        self.val_devid.setText(d.device_id or "—")
        flash = "—"
        if d.flash_size:
            base = f"0x{d.flash_base:08X}" if d.flash_base else "?"
            flash = f"{base} · {d.flash_size_display} ({d.flash_size:,} B)"
        self.val_flash.setText(flash)
        ram = "—"
        if d.ram_size:
            rbase = f"0x{d.ram_base:08X}" if d.ram_base else "?"
            ram = f"{rbase} · {d.ram_size_display}"
        self.val_ram.setText(ram)
        self.val_volt.setText(d.voltage_display)
        self.val_probe.setText(d.probe_name or d.probe_type or "—")
        self.val_wire.setText(str(d.wire_protocol or "—"))
        self.set_refresh_enabled(True)
