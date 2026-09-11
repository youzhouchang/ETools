"""Probe connection panel — loads probe_panel.ui."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton, QSizePolicy, QWidget

from etools.config import get_config
from etools.core.models import CONNECT_MODES, ProbeInfo, TargetInfo
from etools.core.targets import list_target_choices
from etools.logger import get_logger
from etools.ui.ui_loader import embed_form

log = get_logger("ui.probe")


class ProbePanel(QFrame):
    """Left column: probe list + target settings + connect/disconnect toggle."""

    connect_requested = Signal(object, object)  # ProbeInfo, TargetInfo
    disconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProbePanelHost")
        self.setStyleSheet(
            "QFrame#ProbePanelHost { border: none; background: transparent; }"
        )
        self._probes: list[ProbeInfo] = []
        self._connected = False
        self._form = embed_form(self, "probe_panel")
        self._form.setObjectName("panel")
        self._bind()
        self._populate()
        self._wire()

    def _bind(self) -> None:
        f = self._form
        self.probe_combo: QComboBox = f.findChild(QComboBox, "probeCombo")
        self.target_combo: QComboBox = f.findChild(QComboBox, "targetCombo")
        self.mode_combo: QComboBox = f.findChild(QComboBox, "modeCombo")
        self.connect_btn: QPushButton = f.findChild(QPushButton, "connectBtn")
        self.status_label: QLabel = f.findChild(QLabel, "statusLabel")
        self.detail_label: QLabel = f.findChild(QLabel, "detailLabel")
        missing = [
            n
            for n, w in [
                ("probeCombo", self.probe_combo),
                ("targetCombo", self.target_combo),
                ("modeCombo", self.mode_combo),
                ("connectBtn", self.connect_btn),
                ("statusLabel", self.status_label),
                ("detailLabel", self.detail_label),
            ]
            if w is None
        ]
        if missing:
            raise RuntimeError(f"probe_panel.ui missing widgets: {missing}")

    def _populate(self) -> None:
        self.probe_combo.addItem("检测探针中…")
        self.probe_combo.setEnabled(False)
        self.connect_btn.setEnabled(False)
        for name, label in list_target_choices():
            self.target_combo.addItem(label, name)
        for value, label in CONNECT_MODES:
            self.mode_combo.addItem(label, value)

        self.connect_btn.setObjectName("accent")
        self.status_label.setObjectName("statusWarn")
        self.detail_label.setObjectName("hint")
        self.connect_btn.setFixedHeight(30)

        from etools.ui.styles import apply_combo_style, get_theme

        # Fixed-width combos: fill panel but never grow with long text
        for combo in (self.probe_combo, self.target_combo, self.mode_combo):
            combo.setFixedHeight(28)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(12)
            combo.setMaxVisibleItems(12)
            combo.view().setTextElideMode(Qt.TextElideMode.ElideMiddle)
            apply_combo_style(combo, get_theme(get_config().theme))

        self.probe_combo.setMinimumWidth(120)
        self.target_combo.setMinimumWidth(120)
        self.mode_combo.setMinimumWidth(120)

    def _wire(self) -> None:
        self.connect_btn.clicked.connect(self._on_toggle)

    def reload_targets(self) -> None:
        """Refresh target combo after device catalog changes."""
        current = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for name, label in list_target_choices():
            self.target_combo.addItem(label, name)
        if current is not None:
            idx = self.target_combo.findData(current)
            if idx >= 0:
                self.target_combo.setCurrentIndex(idx)
        self.target_combo.blockSignals(False)

    # ----- public API -----

    def probe_ids(self) -> tuple[str, ...]:
        return tuple(p.unique_id for p in self._probes)

    def set_probes(self, probes: list[ProbeInfo]) -> None:
        """Refresh combo, keep selection by unique_id when possible."""
        prev = self._probes
        prev_uid = ""
        if self.probe_combo.currentData() is not None:
            prev_uid = getattr(self.probe_combo.currentData(), "unique_id", "") or ""

        self._probes = list(probes)
        if not probes:
            self.probe_combo.blockSignals(True)
            self.probe_combo.clear()
            self.probe_combo.blockSignals(False)
            self.probe_combo.addItem("未发现探针")
            self.probe_combo.setEnabled(False)
            if not self._connected:
                self.connect_btn.setEnabled(False)
            return

        self.probe_combo.blockSignals(True)
        self.probe_combo.clear()
        restore = 0
        for i, p in enumerate(probes):
            self.probe_combo.addItem(p.display_name, p)
            if p.unique_id and p.unique_id == prev_uid:
                restore = i
        self.probe_combo.setCurrentIndex(restore)
        self.probe_combo.blockSignals(False)
        self.probe_combo.setEnabled(not self._connected)
        if not self._connected:
            self.connect_btn.setEnabled(True)

    def set_connected(self, connected: bool, detail: str = "") -> None:
        self._connected = connected
        self.probe_combo.setEnabled(not connected and bool(self._probes))
        self.target_combo.setEnabled(not connected)
        self.mode_combo.setEnabled(not connected)
        self.connect_btn.setEnabled(True)
        if connected:
            self.connect_btn.setText("断开连接")
            self.connect_btn.setObjectName("danger")
            self.status_label.setText("● 已连接")
            self.status_label.setObjectName("statusOk")
            self.detail_label.setText(detail)
        else:
            self.connect_btn.setText("连接目标")
            self.connect_btn.setObjectName("accent")
            self.status_label.setText("● 未连接")
            self.status_label.setObjectName("statusWarn")
            self.detail_label.setText("")
            self.connect_btn.setEnabled(bool(self._probes))
        self._repolish(self.connect_btn)
        self._repolish(self.status_label)

    def set_error(self, message: str) -> None:
        self._connected = False
        self.connect_btn.setText("连接目标")
        self.connect_btn.setObjectName("accent")
        self.connect_btn.setEnabled(bool(self._probes))
        self.probe_combo.setEnabled(bool(self._probes))
        self.target_combo.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.status_label.setText("● 连接失败")
        self.status_label.setObjectName("statusErr")
        self.detail_label.setText(message)
        self._repolish(self.connect_btn)
        self._repolish(self.status_label)

    def set_connecting(self) -> None:
        self.status_label.setText("● 连接中…")
        self.status_label.setObjectName("statusWarn")
        self.connect_btn.setEnabled(False)
        self._repolish(self.status_label)

    def set_scanning_hint(self, scanning: bool) -> None:
        if not self._probes and scanning:
            if self.probe_combo.count() == 0 or self.probe_combo.itemText(0).startswith(
                "检测"
            ):
                self.probe_combo.blockSignals(True)
                self.probe_combo.clear()
                self.probe_combo.addItem("检测探针中…")
                self.probe_combo.blockSignals(False)

    @staticmethod
    def _repolish(w: QWidget) -> None:
        st = w.style()
        st.unpolish(w)
        st.polish(w)

    def _on_toggle(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
            return
        probe = self.probe_combo.currentData()
        if not isinstance(probe, ProbeInfo):
            return
        text = self.target_combo.currentText().strip()
        data = self.target_combo.currentData()
        # Allow typing a custom pyOCD target name not in the list
        target_name = data if isinstance(data, str) and data else text
        if not target_name:
            target_name = "cortex_m"
        target = TargetInfo(
            target_override=target_name,
            connect_mode=self.mode_combo.currentData() or "halt",
            description=self.target_combo.currentText(),
        )
        self.connect_requested.emit(probe, target)
