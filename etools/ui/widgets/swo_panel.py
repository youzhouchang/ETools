"""SWV (Serial Wire Viewer) — multi ITM port tabs."""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from etools.logger import get_logger

log = get_logger("ui.swv")

MAX_VIEW_LINES = 5000
from etools.i18n import tr as _tr


# Common ITM ports people use; user can type any 0–31
DEFAULT_PORTS = [0]


class _Bridge(QObject):
    text_received = Signal(int, str)  # port, text
    status = Signal(str)


class _MultiPortSink:
    """Decode TraceITMEvent for selected ports only."""

    def __init__(self, bridge: _Bridge, ports: set[int]) -> None:
        self._bridge = bridge
        self._ports = ports

    def receive(self, event: Any) -> None:
        try:
            from pyocd.trace.events import TraceITMEvent

            if not isinstance(event, TraceITMEvent):
                return
            port = int(getattr(event, "port", -1))
            if port not in self._ports:
                return
            width = int(getattr(event, "width", 1))
            data = int(getattr(event, "data", 0))
            if width == 1:
                text = chr(data & 0xFF)
            elif width == 2:
                text = chr(data & 0xFF) + chr((data >> 8) & 0xFF)
            elif width == 4:
                text = "".join(chr((data >> (8 * i)) & 0xFF) for i in range(4))
            else:
                return
            if text:
                self._bridge.text_received.emit(port, text)
        except Exception:
            log.exception("SWV sink error")


class _SwvReader:
    """Minimal SWV reader: TPIU + ITM + probe SWO + SWOParser."""

    def __init__(self, bridge: _Bridge) -> None:
        self._bridge = bridge
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._session: Any = None
        self._sys_clock = 0
        self._swo_clock = 0
        self._ports: set[int] = set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        session: Any,
        sys_clock: int,
        swo_clock: int,
        ports: set[int],
    ) -> bool:
        self.stop()
        if session is None:
            self._bridge.status.emit("—")
            return False
        probe = getattr(session, "probe", None)
        if probe is None:
            self._bridge.status.emit("无探针")
            return False
        try:
            from pyocd.probe.debug_probe import DebugProbe

            caps = getattr(probe, "capabilities", set())
            if DebugProbe.Capability.SWO not in caps:
                self._bridge.status.emit("探针不支持 SWO")
                return False
        except Exception:
            pass

        target = session.target
        try:
            from pyocd.coresight.itm import ITM
            from pyocd.coresight.tpiu import TPIU

            tpiu = target.get_first_child_of_type(TPIU, "has_swo_uart")
            itm = target.get_first_child_of_type(ITM)
            if tpiu is None or itm is None:
                self._bridge.status.emit("目标缺少 ITM/TPIU，无法启用 SWV")
                return False
            if not tpiu.set_swo_clock(swo_clock, sys_clock):
                self._bridge.status.emit("设置 SWO 时钟失败")
                return False
            itm.enable()
        except Exception as exc:
            log.exception("SWV init failed")
            self._bridge.status.emit(f"SWV 初始化失败：{exc}")
            return False

        from pyocd.trace.swo import SWOParser

        sink = _MultiPortSink(self._bridge, set(ports))
        parser = SWOParser(target, sink)
        # connect(sink) is optional if sink passed in constructor
        try:
            if hasattr(parser, "connect"):
                parser.connect(sink)
        except Exception as exc:
            self._bridge.status.emit(f"SWO 解析器连接失败：{exc}")
            return False

        self._session = session
        self._sys_clock = sys_clock
        self._swo_clock = swo_clock
        self._ports = set(ports)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="SWVReader", daemon=True, args=(probe, parser)
        )
        self._thread.start()
        self._bridge.status.emit(
            f"SWV 运行中 · 系统 {sys_clock} Hz · SWO {swo_clock} Hz · 端口 {sorted(ports)}"
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.5)
        self._thread = None
        try:
            probe = getattr(self._session, "probe", None)
            if probe is not None:
                probe.swo_stop()
        except Exception:
            pass

    def _run(self, probe: Any, parser: Any) -> None:
        try:
            try:
                probe.swo_stop()
            except Exception:
                pass
            probe.swo_start(self._swo_clock)
            while not self._stop.is_set():
                try:
                    data = probe.swo_read()
                except Exception as exc:
                    self._bridge.status.emit(f"SWO 读取错误：{exc}")
                    break
                if data:
                    try:
                        parser.parse(data)
                    except Exception:
                        log.debug("SWO parse error", exc_info=True)
                else:
                    # avoid busy spin
                    self._stop.wait(0.01)
        finally:
            try:
                probe.swo_stop()
            except Exception:
                pass


class SwvPanel(QWidget):
    """SWV console with multi ITM port tabs (renamed from SWO)."""
    """SWV console with multi ITM port tabs (renamed from SWO)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = _Bridge(self)
        self._reader = _SwvReader(self._bridge)
        self._session_getter = None
        self._views: dict[int, QPlainTextEdit] = {}
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        from etools.i18n import tr as _tr

        bar = QHBoxLayout()
        bar.setSpacing(6)
        title = QLabel("SWV")
        title.setObjectName("panelTitle")
        bar.addWidget(title)
        bar.addStretch(1)

        bar.addWidget(QLabel(_tr("swv.sysclk")))
        from etools.ui.widgets.spin_boxes import int_spin

        spin_w = 110
        self.sys_spin = int_spin(
            72_000_000, minimum=1_000, maximum=400_000_000, step=1_000_000, width=spin_w
        )
        self.sys_spin.setFixedWidth(spin_w)
        self.sys_edit = self.sys_spin
        bar.addWidget(self.sys_spin)

        bar.addWidget(QLabel(_tr("swv.swoclk")))
        self.swo_spin = int_spin(
            2_000_000, minimum=1_000, maximum=50_000_000, step=100_000, width=spin_w
        )
        self.swo_spin.setFixedWidth(spin_w)
        self.swo_edit = self.swo_spin
        bar.addWidget(self.swo_spin)

        bar.addWidget(QLabel(_tr("swv.itm_port")))
        self.port_spin = int_spin(0, minimum=0, maximum=31, step=1, width=spin_w)
        self.port_spin.setFixedWidth(spin_w)
        self.port_edit = self.port_spin
        bar.addWidget(self.port_spin)

        self.start_btn = QPushButton(_tr("swv.start"))
        self.start_btn.setObjectName("accent")
        self.start_btn.setEnabled(False)
        bar.addWidget(self.start_btn)

        self.clear_btn = QPushButton(_tr("swv.clear"))
        self.clear_btn.setObjectName("ghost")
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.status_label = QLabel(_tr("swv.status_off"))
        self.status_label.setObjectName("hint")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("hexTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self._ensure_placeholder()

    def _ensure_placeholder(self) -> None:
        self.tabs.clear()
        self._views.clear()
        ph = QPlainTextEdit()
        ph.setObjectName("logView")
        ph.setReadOnly(True)
        ph.setPlaceholderText(_tr("swv.placeholder"))
        self.tabs.addTab(ph, "端口 —")

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._toggle)
        self.clear_btn.clicked.connect(self._clear_current)
        self._bridge.text_received.connect(self._on_text)
        self._bridge.status.connect(lambda m: self.status_label.setText(m))

    def retranslate(self) -> None:
        from etools.i18n import tr as _tr

        self.clear_btn.setText(_tr("swv.clear"))

    def set_connected(self, connected: bool) -> None:
        self.start_btn.setEnabled(connected)
        if not connected and self._reader.running:
            self._stop()

    def set_session_getter(self, fn) -> None:
        self._session_getter = fn

    def _parse_ports(self) -> set[int]:
        return {int(self.port_spin.value())}

    def _toggle(self) -> None:
        if self._reader.running:
            self._stop()
            return
        sess = self._session_getter() if callable(self._session_getter) else None
        sys_clk = int(self.sys_spin.value())
        swo_clk = int(self.swo_spin.value())
        ports = self._parse_ports()
        self._build_channel_tabs(ports)
        if self._reader.start(sess, sys_clk, swo_clk, ports):
            self.start_btn.setText("停止 SWV")
        else:
            self._ensure_placeholder()

    def _stop(self) -> None:
        self._reader.stop()
        self.start_btn.setText(_tr("swv.start"))
        self.status_label.setText("已停止")

    def _build_channel_tabs(self, ports: set[int]) -> None:
        self.tabs.clear()
        self._views.clear()
        for p in sorted(ports):
            view = QPlainTextEdit()
            view.setObjectName("logView")
            view.setReadOnly(True)
            view.setMaximumBlockCount(MAX_VIEW_LINES)
            self._views[p] = view
            self.tabs.addTab(view, f"端口 {p}")

    def _on_text(self, port: int, text: str) -> None:
        view = self._views.get(port)
        if view is None:
            return
        view.moveCursor(view.textCursor().MoveOperation.End)
        view.insertPlainText(text)
        view.moveCursor(view.textCursor().MoveOperation.End)

    def _clear_current(self) -> None:
        w = self.tabs.currentWidget()
        if isinstance(w, QPlainTextEdit):
            w.clear()

    def shutdown(self) -> None:
        self._stop()

    # alias for older callers
    def set_connected_alias(self, connected: bool) -> None:
        self.set_connected(connected)


# back-compat
SwoPanel = SwvPanel
