"""External flash (CMSIS FLM) selector shown under the Flash tab."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from etools.config import get_config, save_config
from etools.i18n import tr
from etools.ui.widgets.flash_tools_common import tool_button

CONFIG_KEY = "ext_flm"


class ExtFlashBox(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ctxGroup")
        self._host: Any = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 8)
        lay.setSpacing(6)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.browse_btn = tool_button("open")
        self.apply_btn = tool_button("connect")
        self.remove_btn = tool_button("disconnect")
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse_btn)
        row.addWidget(self.apply_btn)
        row.addWidget(self.remove_btn)
        lay.addLayout(row)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.path_edit.setText(str((get_config().extra or {}).get(CONFIG_KEY) or ""))
        self.browse_btn.clicked.connect(self._browse)
        self.apply_btn.clicked.connect(self.apply)
        self.remove_btn.clicked.connect(self.remove)
        self.retranslate()

    def bind(self, host: Any) -> None:
        self._host = host
        driver = getattr(host.service, "driver", None)
        if driver is not None and hasattr(driver, "ext_flm_path"):
            driver.ext_flm_path = self.path_edit.text().strip()

    def retranslate(self) -> None:
        self.setTitle(tr("ext.title"))
        self.path_edit.setPlaceholderText(tr("ext.placeholder"))
        self.browse_btn.setText(tr("prod.browse"))
        self.apply_btn.setText(tr("ext.apply"))
        self.remove_btn.setText(tr("ext.remove"))
        if not self.info.text():
            self.info.setText(tr("ext.hint"))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("ext.title"), self.path_edit.text(), "CMSIS Flash Algorithm (*.FLM *.flm)"
        )
        if path:
            self.path_edit.setText(path)

    def _remember(self, path: str) -> None:
        cfg = get_config()
        extra = dict(cfg.extra or {})
        extra[CONFIG_KEY] = path
        cfg.extra = extra
        save_config()

    def apply(self) -> None:
        self._set(self.path_edit.text().strip())

    def remove(self) -> None:
        self.path_edit.clear()
        self._set("")

    def _set(self, path: str) -> None:
        if self._host is None:
            return
        service = self._host.service

        def on_ok(info) -> None:
            self._remember(path)
            if info is None:
                self.info.setText(tr("ext.removed"))
                self._host.log(tr("ext.removed"))
                return
            key = "ext.attached" if self._host.connected else "ext.saved"
            self.info.setText(tr(key, info=info.summary()))
            self._host.log(tr(key, info=info.summary()))

        def on_err(msg: str) -> None:
            self.info.setText(tr("ext.fail", err=msg))

        self._host.run_job(lambda: service.set_external_flm(path), on_ok, on_err)
