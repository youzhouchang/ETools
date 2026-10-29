"""SEGGER RTT viewer — multi up-channel tabs."""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot
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

from etools.core.probe_io import PROBE_LOCK
from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("ui.rtt")

MAX_VIEW_LINES = 5000


class _RttReader(QObject):
    """Poll all RTT up-channels; emit (channel_index, text)."""

    text_received = Signal(int, str)
    raw_received = Signal(int, bytes)
    status = Signal(str)
    channels_ready = Signal(int, int)  # n_up, n_down
    # The leading int is the session generation; a reader abandoned by a slow
    # stop() must not feed or stop the session started after it.
    _polled = Signal(int, int, bytes)
    _poll_failed = Signal(int, str)

    POLL_INTERVAL_S = 0.05

    def __init__(self) -> None:
        super().__init__()
        self._cb: Any = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        # Bound-method slots on this GUI-thread object make delivery queued.
        self._polled.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._poll_failed.connect(self._on_poll_failed, Qt.ConnectionType.QueuedConnection)

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
            with PROBE_LOCK:
                cb = RTTControlBlock.from_target(session.target, address=addr, size=sz)
                cb.start()
            ups = getattr(cb, "up_channels", None) or []
            if not ups:
                self.status.emit(tr("rtt.no_channel"))
                return False
            self._cb = cb
            self._running = True
            self._stop_event = threading.Event()
            self._generation += 1
            self._thread = threading.Thread(
                target=self._poll_loop,
                args=(cb, self._stop_event, self._generation),
                name="etools-rtt",
                daemon=True,
            )
            self._thread.start()
            self.channels_ready.emit(len(ups), self.n_down)
            self.status.emit(tr("rtt.started", up=len(ups), down=self.n_down))
            return True
        except Exception as exc:
            log.exception("RTT start failed")
            self.status.emit(tr("rtt.failed", err=str(exc)))
            return False

    def stop(self) -> None:
        self._stop_event.set()
        self._generation += 1
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._running = False
        self._cb = None

    def write_down(self, channel: int, data: bytes) -> None:
        if not self._cb:
            return
        try:
            downs = getattr(self._cb, "down_channels", None) or []
            if 0 <= channel < len(downs):
                # Runs on the GUI thread: skip instead of freezing during a flash job.
                if not PROBE_LOCK.acquire(blocking=False):
                    return
                try:
                    downs[channel].write(data)
                finally:
                    PROBE_LOCK.release()
        except Exception:
            log.exception("RTT write down failed")

    def _poll_loop(self, cb: Any, stop: threading.Event, generation: int) -> None:
        """Worker thread: read every up-channel without touching Qt widgets."""
        while not stop.wait(self.POLL_INTERVAL_S):
            try:
                ups = getattr(cb, "up_channels", None) or []
                for i, ch in enumerate(ups):
                    # Flash jobs hold the lock for long; skip this round instead of queuing.
                    if not PROBE_LOCK.acquire(timeout=self.POLL_INTERVAL_S):
                        break
                    try:
                        raw = ch.read()
                    finally:
                        PROBE_LOCK.release()
                    if raw and not stop.is_set():
                        self._polled.emit(generation, i, bytes(raw))
            except Exception as exc:  # noqa: BLE001
                log.debug("RTT poll error: %s", exc)
                if not stop.is_set():
                    self._poll_failed.emit(generation, str(exc))
                return

    @Slot(int, int, bytes)
    def _deliver(self, generation: int, channel: int, payload: bytes) -> None:
        if not self._running or generation != self._generation:
            return
        self.raw_received.emit(channel, payload)
        text = payload.decode("utf-8", errors="replace")
        if text:
            self.text_received.emit(channel, text)

    @Slot(int, str)
    def _on_poll_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self.status.emit(tr("rtt.read_error", err=message))
        self.stop()


class RttPanel(QWidget):
    """Multi-channel RTT console."""

    data_received = Signal(int, bytes)

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

        self.addr_label = QLabel(tr("rtt.addr"))
        bar.addWidget(self.addr_label)
        from etools.ui.widgets.spin_boxes import hex_spin

        self.addr_spin = hex_spin(0, step=0x100, width=130)
        self.addr_spin.setSpecialValueText(tr("rtt.auto"))
        self.addr_edit = self.addr_spin
        bar.addWidget(self.addr_spin)

        self.size_label = QLabel(tr("rtt.size"))
        bar.addWidget(self.size_label)
        self.size_spin = hex_spin(0, step=0x1000, width=110)
        self.size_spin.setSpecialValueText(tr("rtt.auto"))
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
        self.ch_spin.setPrefix(tr("rtt.channel") + " ")
        self.ch_spin.setFixedWidth(90)
        self.send_edit = QLineEdit()
        self.send_edit.setPlaceholderText(tr("rtt.send_ph"))
        self.send_edit.setEnabled(False)
        self.send_btn = QPushButton(tr("rtt.send"))
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
        self.tabs.addTab(ph, tr("rtt.channel_none"))

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._toggle)
        self.clear_btn.clicked.connect(self._clear_current)
        self.send_btn.clicked.connect(self._send)
        self.send_edit.returnPressed.connect(self._send)
        self._reader.text_received.connect(self._on_text)
        self._reader.raw_received.connect(self.data_received)
        self._reader.status.connect(lambda m: self.status_label.setText(m))
        self._reader.channels_ready.connect(self._on_channels)

    def retranslate(self) -> None:
        self.clear_btn.setText(tr("rtt.clear"))
        running = self._reader.running
        self.start_btn.setText(tr("rtt.stop_rtt") if running else tr("rtt.start"))
        self.addr_label.setText(tr("rtt.addr"))
        self.size_label.setText(tr("rtt.size"))
        self.addr_spin.setSpecialValueText(tr("rtt.auto"))
        self.size_spin.setSpecialValueText(tr("rtt.auto"))
        self.ch_spin.setPrefix(tr("rtt.channel") + " ")
        self.send_edit.setPlaceholderText(tr("rtt.send_ph"))
        self.send_btn.setText(tr("rtt.send"))
        if self._views:
            for index in range(self.tabs.count()):
                self.tabs.setTabText(index, tr("rtt.up_tab", n=index))
        elif self.tabs.count():
            self.tabs.setTabText(0, tr("rtt.channel_none"))

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
            self.status_label.setText(tr("rtt.stopped"))
            return
        sess = self._session_getter() if callable(self._session_getter) else None
        ok = self._reader.start(
            sess,
            address=int(self.addr_spin.value()),
            size=int(self.size_spin.value()),
        )
        if ok:
            self.start_btn.setText(tr("rtt.stop_rtt"))
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
            self.tabs.addTab(view, tr("rtt.up_tab", n=i))
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
