"""Application settings dialog (theme / language / behaviour)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
        self.setMinimumWidth(380)
        cfg = get_config()

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

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

        self.auto_scan = QCheckBox(tr("settings.auto_scan"))
        self.auto_scan.setChecked(bool(cfg.auto_probe_scan))
        self.verify_after = QCheckBox(tr("settings.verify_after"))
        self.verify_after.setChecked(bool(cfg.verify_after_program))
        self.auto_update = QCheckBox(tr("settings.auto_update"))
        self.auto_update.setChecked(bool(cfg.extra.get("auto_check_update", True)))

        form.addRow(tr("menu.theme"), self.theme)
        form.addRow(tr("menu.language"), self.language)
        form.addRow("", self.auto_scan)
        form.addRow("", self.verify_after)
        form.addRow("", self.auto_update)
        root.addLayout(form)

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

        path, _ = QFileDialog.getOpenFileName(
            self, tr("settings.import"), "", "JSON (*.json)"
        )
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

    def _accept(self) -> None:
        cfg = get_config()
        cfg.theme = str(self.theme.currentData() or "dark")
        cfg.language = str(self.language.currentData() or LANG_ZH)
        cfg.auto_probe_scan = self.auto_scan.isChecked()
        cfg.verify_after_program = self.verify_after.isChecked()
        extra = dict(cfg.extra or {})
        extra["auto_check_update"] = self.auto_update.isChecked()
        cfg.extra = extra
        save_config()
        self.accept()

    def selected_theme(self) -> str:
        return str(self.theme.currentData() or "dark")

    def selected_language(self) -> str:
        return str(self.language.currentData() or LANG_ZH)
