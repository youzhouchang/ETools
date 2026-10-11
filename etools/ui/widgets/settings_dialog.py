"""Application settings dialog (appearance, flash defaults, link defaults)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.config import get_config, save_config
from etools.i18n import LANG_EN, LANG_ZH, tr


class SettingsDialog(QDialog):
    """Edit AppConfig preferences that apply app-wide."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(420)
        cfg = get_config()
        extra = cfg.extra or {}

        root = QVBoxLayout(self)
        root.setSpacing(12)

        look = QGroupBox(tr("settings.group_look"))
        look_form = QFormLayout(look)
        self.theme = QComboBox()
        self.theme.addItem(tr("act.theme_dark"), "dark")
        self.theme.addItem(tr("act.theme_light"), "light")
        self.theme.addItem(tr("settings.theme_system"), "system")
        idx = self.theme.findData((cfg.theme or "dark").lower())
        self.theme.setCurrentIndex(max(0, idx))
        self.language = QComboBox()
        self.language.addItem(tr("act.lang_zh"), LANG_ZH)
        self.language.addItem(tr("act.lang_en"), LANG_EN)
        idx = self.language.findData(cfg.language or LANG_ZH)
        self.language.setCurrentIndex(max(0, idx))
        self.rail_labels = QCheckBox(tr("tool.labels"))
        self.rail_labels.setChecked(bool(extra.get("rail_labels", False)))
        look_form.addRow(tr("menu.theme"), self.theme)
        look_form.addRow(tr("menu.language"), self.language)
        look_form.addRow("", self.rail_labels)
        root.addWidget(look)

        flash = QGroupBox(tr("settings.group_flash"))
        flash_form = QFormLayout(flash)
        self.auto_scan = QCheckBox(tr("settings.auto_scan"))
        self.auto_scan.setChecked(bool(cfg.auto_probe_scan))
        self.verify_after = QCheckBox(tr("settings.verify_after"))
        self.verify_after.setChecked(bool(cfg.verify_after_program))
        self.auto_update = QCheckBox(tr("settings.auto_update"))
        self.auto_update.setChecked(bool(extra.get("auto_check_update", True)))
        flash_form.addRow("", self.auto_scan)
        flash_form.addRow("", self.verify_after)
        flash_form.addRow("", self.auto_update)
        root.addWidget(flash)

        link = QGroupBox(tr("settings.group_link"))
        link_form = QFormLayout(link)
        page = getattr(parent, "serial_page", None)
        self.only_free = QCheckBox(tr("serial.only_free"))
        self.only_free.setToolTip(tr("serial.only_free_tip"))
        self.only_free.setChecked(bool(getattr(page, "only_free", True)))
        link_form.addRow("", self.only_free)
        root.addWidget(link)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        io_row = QHBoxLayout()
        self.export_btn = QPushButton(tr("settings.export"))
        self.export_btn.setObjectName("ghost")
        self.import_btn = QPushButton(tr("settings.import"))
        self.import_btn.setObjectName("ghost")
        self.export_btn.clicked.connect(self._export)
        self.import_btn.clicked.connect(self._import)
        io_row.addWidget(self.export_btn)
        io_row.addWidget(self.import_btn)
        io_row.addStretch(1)
        root.addLayout(io_row)

    def _export(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from etools.config import export_config

        path, _ = QFileDialog.getSaveFileName(
            self, tr("settings.export"), "etools-config.json", "JSON (*.json)"
        )
        if path:
            export_config(path)

    def _import(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from etools.config import import_config

        path, _ = QFileDialog.getOpenFileName(self, tr("settings.import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            import_config(path)
        except Exception:  # noqa: BLE001
            return
        cfg = get_config()
        idx = self.theme.findData((cfg.theme or "dark").lower())
        if idx >= 0:
            self.theme.setCurrentIndex(idx)
        idx = self.language.findData(cfg.language or LANG_ZH)
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        self.auto_scan.setChecked(bool(cfg.auto_probe_scan))
        self.verify_after.setChecked(bool(cfg.verify_after_program))
        extra = cfg.extra or {}
        self.auto_update.setChecked(bool(extra.get("auto_check_update", True)))
        self.rail_labels.setChecked(bool(extra.get("rail_labels", False)))

    def _accept(self) -> None:
        cfg = get_config()
        cfg.theme = str(self.theme.currentData() or "dark")
        cfg.language = str(self.language.currentData() or LANG_ZH)
        cfg.auto_probe_scan = self.auto_scan.isChecked()
        cfg.verify_after_program = self.verify_after.isChecked()
        extra = dict(cfg.extra or {})
        extra["auto_check_update"] = self.auto_update.isChecked()
        extra["rail_labels"] = self.rail_labels.isChecked()
        cfg.extra = extra
        save_config()
        self.accept()

    def selected_theme(self) -> str:
        return str(self.theme.currentData() or "dark")

    def selected_language(self) -> str:
        return str(self.language.currentData() or LANG_ZH)

    def rail_labels_checked(self) -> bool:
        return self.rail_labels.isChecked()

    def only_free_checked(self) -> bool:
        return self.only_free.isChecked()
