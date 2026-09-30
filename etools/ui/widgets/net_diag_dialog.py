"""Network connectivity check dialog (TCP / UDP port)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
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

from etools.core.net_diag import check_tcp_port, check_udp_port
from etools.i18n import tr


class _Worker(QObject):
    done = Signal(bool, float, str)

    def __init__(self, kind: str, host: str, port: int) -> None:
        super().__init__()
        self._kind = kind
        self._host = host
        self._port = port

    def run(self) -> None:
        if self._kind == "udp":
            ok, ms, msg = check_udp_port(self._host, self._port)
        else:
            ok, ms, msg = check_tcp_port(self._host, self._port)
        self.done.emit(ok, ms, msg)


class NetDiagDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, host: str = "127.0.0.1") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("diag.title"))
        self.setMinimumWidth(420)
        self._thread: QThread | None = None

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.host = QLineEdit(host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        self.kind = QComboBox()
        self.kind.addItem("TCP", "tcp")
        self.kind.addItem("UDP", "udp")
        form.addRow(tr("net.remote_host"), self.host)
        form.addRow(tr("net.remote_port"), self.port)
        form.addRow(tr("diag.kind"), self.kind)
        root.addLayout(form)

        row = QHBoxLayout()
        self.check_btn = QPushButton(tr("diag.check"))
        self.check_btn.setObjectName("accent")
        self.result = QLabel(tr("diag.idle"))
        self.result.setObjectName("mutedLabel")
        self.result.setWordWrap(True)
        row.addWidget(self.check_btn)
        row.addWidget(self.result, 1)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.check_btn.clicked.connect(self._check)

    def _check(self) -> None:
        host = self.host.text().strip()
        if not host:
            return
        self.check_btn.setEnabled(False)
        self.result.setText(tr("diag.running"))
        thread = QThread(self)
        worker = _Worker(str(self.kind.currentData()), host, int(self.port.value()))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _on_done(self, ok: bool, ms: float, msg: str) -> None:
        self.check_btn.setEnabled(True)
        if ok:
            self.result.setText(tr("diag.ok", ms=f"{ms:.0f}", msg=msg))
            self.result.setObjectName("statusOk")
        else:
            self.result.setText(tr("diag.fail", msg=msg))
            self.result.setObjectName("statusErr")
        st = self.result.style()
        st.unpolish(self.result)
        st.polish(self.result)
