"""Target information panel — loads target_info_panel.ui."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from etools.core.models import TargetDetails
from etools.i18n import tr
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
        self._keys: dict[str, QLabel] = {}
        for name, attr in (
            ("keyTarget", "info.chip"),
            ("keyCpu", "info.cpu"),
            ("keyVendor", "info.vendor"),
            ("keyUid", "info.uid"),
            ("keyDevId", "info.devid"),
            ("keyFlash", "info.flash"),
            ("keyRam", "info.ram"),
            ("keyVolt", "info.volt"),
        ):
            k = f.findChild(QLabel, name)
            if k is not None:
                k.setObjectName("hint")
                self._keys[attr] = k
        self.retranslate()

    def retranslate(self) -> None:
        for key, lab in self._keys.items():
            lab.setText(tr(key))
        self.refresh_btn.setText(tr("info.refresh"))
        title = self._form.findChild(QLabel, "panelTitle")
        if title is not None:
            title.setText(tr("info.title"))

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
            base = f"0x{d.flash_base:08X}" if d.flash_base else ""
            flash = f"{base} · {d.flash_size_display}".strip(" ·")
        self.val_flash.setText(flash)
        ram = "—"
        if d.ram_size:
            rbase = f"0x{d.ram_base:08X}" if d.ram_base else "?"
            ram = f"{rbase} · {d.ram_size_display}"
        self.val_ram.setText(ram)
        self.val_volt.setText(d.voltage_display)
        self.set_refresh_enabled(True)
