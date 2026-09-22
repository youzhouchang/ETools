"""SEGGER RTT viewer — multi up-channel tabs."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("ui.rtt")

MAX_VIEW_LINES = 5000


class _RttReader(QObject):
    """Poll all RTT up-channels; emit (channel_index, text)."""

    text_received = Signal(int, str)
    status = Signal(str)
    channels_ready = Signal(int, int)  # n_up, n_down

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._cb: Any = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def n_up(self) -> int:
        if not self._cb:
            return 0
        return len(getattr(self._cb, "up_channels", None) or [])

    @property
    def n_down(self) -> int:
        if not self._cb:
            return 0
        return len(getattr(self._cb, "down_channels", None) or [])

    def start(
        self,
        session: Any,
        address: int | None = None,
        size: int | None = None,
    ) -> bool:
        self.stop()
        if session is None or session.target is None:
            self.status.emit(tr("rtt.not_connected"))
            return False
        try:
            from pyocd.debug.rtt import RTTControlBlock

            if address is None:
                addr, sz = 0x20000000, 0x20000
            else:
                addr = int(address)
                sz = int(size or 0)
            cb = RTTControlBlock.from_target(session.target, address=addr, size=sz)
            cb.start()
            ups = getattr(cb, "up_channels", None) or []
            if not ups:
                self.status.emit(tr("rtt.no_channel"))
                return False
            self._cb = cb
            self._running = True
            self._timer.start()
            self.channels_ready.emit(len(ups), self.n_down)
            self.status.emit(tr("rtt.started", up=len(ups), down=self.n_down))
            return True
        except Exception as exc:
            log.exception("RTT start failed")
            self.status.emit(tr("rtt.failed", err=str(exc)))
            return False

    def stop(self) -> None:
        self._timer.stop()
        self._running = False
        self._cb = None

    def write_down(self, channel: int, data: bytes) -> None:
        if not self._cb:
            return
        try:
            downs = getattr(self._cb, "down_channels", None) or []
            if 0 <= channel < len(downs):
                downs[channel].write(data)
        except Exception:
            log.exception("RTT write down failed")

    def _poll(self) -> None:
        if not self._cb:
            return
        try:
            ups = getattr(self._cb, "up_channels", None) or []
            for i, ch in enumerate(ups):
                raw = ch.read()
                if raw:
                    text = bytes(raw).decode("utf-8", errors="replace")
                    if text:
                        self.text_received.emit(i, text)
        except Exception as exc:
            log.debug("RTT poll error: %s", exc)
            self.status.emit(f"RTT 读取错误：{exc}")
            self.stop()


class RttPanel(QWidget):
    """Multi-channel RTT console."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reader = _RttReader()
        self._session_getter = None
        self._views: list[QPlainTextEdit] = []
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        title = QLabel("RTT View")
        title.setObjectName("panelTitle")
        bar.addWidget(title)
        bar.addStretch(1)

        bar.addWidget(QLabel(tr("rtt.addr")))
        from etools.ui.widgets.spin_boxes import hex_spin

        self.addr_spin = hex_spin(0, step=0x100, width=130)
        self.addr_spin.setSpecialValueText("自动")
        self.addr_edit = self.addr_spin
        bar.addWidget(self.addr_spin)

        bar.addWidget(QLabel(tr("rtt.size")))
        self.size_spin = hex_spin(0, step=0x1000, width=110)
        self.size_spin.setSpecialValueText("自动")
        self.size_edit = self.size_spin
        bar.addWidget(self.size_spin)

        self.start_btn = QPushButton(tr("rtt.start"))
        self.start_btn.setObjectName("accent")
        self.start_btn.setEnabled(False)
        bar.addWidget(self.start_btn)

        self.clear_btn = QPushButton(tr("rtt.clear"))
        self.clear_btn.setObjectName("ghost")
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.status_label = QLabel(tr("rtt.status_idle"))
        self.status_label.setObjectName("hint")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("hexTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)
        root.addWidget(self.tabs, 1)
        self._ensure_placeholder()

        send_row = QHBoxLayout()
        self.ch_spin = QSpinBox()
        self.ch_spin.setRange(0, 0)
        self.ch_spin.setPrefix("通道 ")
        self.ch_spin.setFixedWidth(90)
        self.send_edit = QLineEdit()
        self.send_edit.setPlaceholderText("向所选下行通道发送…（回车）")
        self.send_edit.setEnabled(False)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("ghost")
        self.send_btn.setEnabled(False)
        send_row.addWidget(self.ch_spin)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

    def _ensure_placeholder(self) -> None:
        self.tabs.clear()
        self._views.clear()
        ph = QPlainTextEdit()
        ph.setObjectName("logView")
        ph.setReadOnly(True)
        ph.setPlaceholderText(tr("rtt.ph"))
        self.tabs.addTab(ph, "通道 —")

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._toggle)
        self.clear_btn.clicked.connect(self._clear_current)
        self.send_btn.clicked.connect(self._send)
        self.send_edit.returnPressed.connect(self._send)
        self._reader.text_received.connect(self._on_text)
        self._reader.status.connect(lambda m: self.status_label.setText(m))
        self._reader.channels_ready.connect(self._on_channels)

    def retranslate(self) -> None:
        self.clear_btn.setText(tr("rtt.clear"))
        if not getattr(self, "_running", False):
            self.start_btn.setText(tr("rtt.start"))

    def set_connected(self, connected: bool) -> None:
        self.start_btn.setEnabled(connected)
        if not connected and self._reader.running:
            self._toggle()

    def set_session_getter(self, fn) -> None:
        self._session_getter = fn

    def _parse_int(self, text: str) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return int(text, 0)
        except ValueError:
            return None

    def _toggle(self) -> None:
        if self._reader.running:
            self._reader.stop()
            self.start_btn.setText(tr("rtt.start"))
            self.send_edit.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.ch_spin.setRange(0, 0)
            self._ensure_placeholder()
            self.status_label.setText("RTT 已停止")
            return
        sess = self._session_getter() if callable(self._session_getter) else None
        ok = self._reader.start(
            sess,
            address=int(self.addr_spin.value()),
            size=int(self.size_spin.value()),
        )
        if ok:
            self.start_btn.setText("停止 RTT")
            self.send_edit.setEnabled(True)
            self.send_btn.setEnabled(True)

    def _on_channels(self, n_up: int, n_down: int) -> None:
        self.tabs.clear()
        self._views.clear()
        for i in range(max(1, n_up)):
            view = QPlainTextEdit()
            view.setObjectName("logView")
            view.setReadOnly(True)
            view.setMaximumBlockCount(MAX_VIEW_LINES)
            self._views.append(view)
            name = f"上行 {i}" if n_up > 1 else "上行 0"
            self.tabs.addTab(view, name)
        self.ch_spin.setRange(0, max(0, n_down - 1))

    def _on_text(self, channel: int, text: str) -> None:
        if 0 <= channel < len(self._views):
            view = self._views[channel]
            view.moveCursor(view.textCursor().MoveOperation.End)
            view.insertPlainText(text)
            view.moveCursor(view.textCursor().MoveOperation.End)

    def _clear_current(self) -> None:
        w = self.tabs.currentWidget()
        if isinstance(w, QPlainTextEdit):
            w.clear()

    def _send(self) -> None:
        data = self.send_edit.text()
        if not data:
            return
        self._reader.write_down(self.ch_spin.value(), (data + "\n").encode("utf-8"))
        self.send_edit.clear()

    def shutdown(self) -> None:
        self._reader.stop()
