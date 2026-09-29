"""ELF variable monitor and lightweight waveform view."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from etools.core.elf import ElfImage, ElfVariable, load_elf
from etools.core.trace_stream import (
    TYPE_FLOAT32,
    TYPE_FLOAT64,
    TYPE_SIGNED,
    TYPE_UNSIGNED,
    TraceFrameParser,
)
from etools.logger import get_logger

log = get_logger("ui.variable_monitor")
MAX_HISTORY = 900
MAX_VARIABLES = 5000
PAINT_INTERVAL_MS = 33


def _decode_value(raw: bytes, variable: ElfVariable) -> float | int | None:
    """Decode scalar values for display and plotting."""
    size = max(1, min(len(raw), int(variable.byte_size or variable.size or 4)))
    data = raw[:size]
    if variable.kind == "float" and size in (4, 8):
        import struct

        try:
            return struct.unpack("<f" if size == 4 else "<d", data)[0]
        except struct.error:
            return None
    if variable.kind in {"array", "struct"}:
        return None
    signed = variable.encoding in {"DW_ATE_signed", "signed", "5", "6"} or (
        "signed" in variable.encoding
    )
    return int.from_bytes(data, "little", signed=signed)


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


class _Sampler(QObject):
    sample_ready = Signal(object)  # dict[key, (value, raw)]
    status = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, session: Any, variables: list[ElfVariable], interval_ms: int) -> bool:
        self.stop()
        target = getattr(session, "target", None) if session is not None else None
        if target is None or not variables:
            self.status.emit("目标未连接或没有选中的变量")
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(target, list(variables), max(20, int(interval_ms)) / 1000.0),
            name="VariableSampler",
            daemon=True,
        )
        self._thread.start()
        self.status.emit("采样中")
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self, target: Any, variables: list[ElfVariable], interval: float) -> None:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                sample: dict[str, tuple[Any, bytes | None]] = {}
                for variable in variables:
                    if self._stop.is_set():
                        break
                    if variable.kind in {"array", "struct"}:
                        sample[_variable_key(variable)] = (None, None)
                        continue
                    try:
                        # Sampling is for scalar values; cap reads so a large
                        # linker object cannot stall the probe for one tick.
                        read_size = min(max(1, int(variable.size)), 8)
                        raw = bytes(target.read_memory_block8(variable.address, read_size))
                        sample[_variable_key(variable)] = (_decode_value(raw, variable), raw)
                    except Exception as exc:
                        sample[_variable_key(variable)] = (None, None)
                        log.debug("read variable %s failed: %s", variable.name, exc)
                if sample:
                    self.sample_ready.emit(sample)
                self._stop.wait(max(0.001, interval - (time.monotonic() - started)))
        finally:
            self.status.emit("已停止")


def _variable_key(variable: ElfVariable) -> str:
    return f"{variable.name}@{variable.address:08X}"


class _Waveform(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._series: dict[str, deque[float]] = {}
        self._dirty = False
        self._paint_timer = QTimer(self)
        self._paint_timer.setInterval(PAINT_INTERVAL_MS)
        self._paint_timer.timeout.connect(self._render_tick)
        self._paint_timer.start()
        self.setMinimumHeight(240)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setObjectName("waveform")

    def clear(self) -> None:
        self._series.clear()
        self._dirty = True
        self.update()

    def push_batch(self, values: dict[str, Any]) -> None:
        """Append one sampler tick and coalesce repaints to ~30 FPS."""
        changed = False
        for key, value in values.items():
            if not isinstance(value, (int, float)):
                continue
            self._series.setdefault(key, deque(maxlen=MAX_HISTORY)).append(float(value))
            changed = True
        self._dirty = self._dirty or changed

    def _render_tick(self) -> None:
        if self._dirty:
            self._dirty = False
            self.update()

    @staticmethod
    def _envelope(values: list[float], max_points: int) -> list[tuple[int, float]]:
        """Reduce samples to min/max buckets while retaining sharp transitions."""
        if len(values) <= max_points:
            return list(enumerate(values))
        bucket = max(1, (len(values) + max_points - 1) // max_points)
        result: list[tuple[int, float]] = []
        for start in range(0, len(values), bucket):
            end = min(len(values), start + bucket)
            chunk = values[start:end]
            low = min(range(len(chunk)), key=chunk.__getitem__)
            high = max(range(len(chunk)), key=chunk.__getitem__)
            ordered = (low, high) if low <= high else (high, low)
            result.extend((start + index, chunk[index]) for index in ordered)
        return result

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = self.palette().base().color()
        text = self.palette().text().color()
        dim = self.palette().mid().color()
        canvas = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(canvas, base)
        plot = canvas.adjusted(14, 48, -14, -22)
        panel = base.lighter(108) if base.lightness() < 128 else base.darker(106)
        painter.setPen(QPen(dim, 1))
        painter.setBrush(panel)
        painter.drawRoundedRect(canvas, 7, 7)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(text)
        painter.drawText(canvas.left() + 14, canvas.top() + 22, "波形监视")
        painter.setPen(dim)
        painter.drawText(
            canvas.left() + 92,
            canvas.top() + 22,
            f"{len(self._series)} 路 · {PAINT_INTERVAL_MS} FPS",
        )
        if not self._series:
            painter.setPen(dim)
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "选择变量并开始采样")
            return
        painter.setPen(QPen(dim, 1, Qt.PenStyle.DotLine))
        for column in range(1, 7):
            xx = plot.left() + plot.width() * column / 7
            painter.drawLine(QPointF(xx, plot.top()), QPointF(xx, plot.bottom()))
        for row in range(1, 5):
            yy = plot.top() + plot.height() * row / 5
            painter.drawLine(QPointF(plot.left(), yy), QPointF(plot.right(), yy))

        colors = [
            QColor("#54a0ff"),
            QColor("#1dd1a1"),
            QColor("#ff9f43"),
            QColor("#ee5253"),
            QColor("#a55eea"),
        ]
        max_points = max(80, int(plot.width() * 1.5))
        for index, (key, values) in enumerate(self._series.items()):
            samples = list(values)
            if len(samples) < 2:
                continue
            lo, hi = min(samples), max(samples)
            if hi == lo:
                hi = lo + 1.0
            color = colors[index % len(colors)]
            envelope = self._envelope(samples, max_points)
            points = [
                QPointF(
                    plot.left() + i * plot.width() / max(1, len(samples) - 1),
                    plot.bottom() - (value - lo) / (hi - lo) * plot.height(),
                )
                for i, value in envelope
            ]
            line = QPainterPath(points[0])
            for point in points[1:]:
                line.lineTo(point)
            fill = QPainterPath(line)
            fill.lineTo(points[-1].x(), plot.bottom())
            fill.lineTo(points[0].x(), plot.bottom())
            fill.closeSubpath()
            fill_color = QColor(color)
            fill_color.setAlpha(28)
            painter.fillPath(fill, fill_color)
            painter.setPen(QPen(color, 1.7))
            painter.drawPath(line)
            last = points[-1]
            painter.setBrush(color)
            painter.drawEllipse(last, 3.2, 3.2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(color)
            label = key.split("@", 1)[0]
            painter.drawText(
                canvas.left() + 14 + index * max(150, canvas.width() // max(1, len(self._series))),
                canvas.top() + 38,
                (
                    f"● {label}  {_format_value(samples[-1])}  "
                    f"[{_format_value(lo)}…{_format_value(hi)}]"
                ),
            )


class VariableMonitorPanel(QWidget):
    """Load an ELF, choose globals, and sample them through the active pyOCD session."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_getter = None
        self._image: ElfImage | None = None
        self._variables: list[ElfVariable] = []
        self._rows: dict[str, int] = {}
        self._variable_lookup: dict[str, ElfVariable] = {}
        self._variables_by_address: dict[int, ElfVariable] = {}
        self._history: dict[str, deque[float]] = {}
        self._sampler = _Sampler()
        self._trace_parsers: dict[tuple[str, int], TraceFrameParser] = {}
        self._stream_active = False
        self._stream_variables: set[str] = set()
        self._pending_values: dict[str, Any] = {}
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(PAINT_INTERVAL_MS)
        self._sample_timer.timeout.connect(self._flush_pending_values)
        self._sample_timer.start()
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        bar = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 ELF / AXF / ALF 文件以加载调试符号")
        self.open_btn = QPushButton("打开 ELF/ALF")
        self.open_btn.setObjectName("ghost")
        bar.addWidget(QLabel("ELF"))
        bar.addWidget(self.path_edit, 1)
        bar.addWidget(self.open_btn)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("筛选变量名…")
        bar.addWidget(self.filter_edit)
        root.addLayout(bar)

        self.status_label = QLabel("未加载 ELF")
        self.status_label.setObjectName("hint")
        root.addWidget(self.status_label)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["监控", "变量", "地址", "类型", "当前值"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 150)
        root.addWidget(self.table, 2)

        controls = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("SWD 轮询", "swd")
        self.mode_combo.addItem("RTT 数据流", "rtt")
        self.mode_combo.addItem("SWO 数据流", "swo")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(20, 5000)
        self.interval_spin.setValue(100)
        self.interval_spin.setSuffix(" ms")
        self.start_btn = QPushButton("开始采样")
        self.start_btn.setObjectName("accent")
        self.clear_btn = QPushButton("清除波形")
        self.clear_btn.setObjectName("ghost")
        controls.addWidget(QLabel("模式"))
        controls.addWidget(self.mode_combo)
        controls.addWidget(QLabel("间隔"))
        controls.addWidget(self.interval_spin)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.clear_btn)
        controls.addStretch(1)
        root.addLayout(controls)
        self.waveform = _Waveform()
        root.addWidget(self.waveform, 1)

    def _wire(self) -> None:
        self.open_btn.clicked.connect(self._choose_elf)
        self.filter_edit.textChanged.connect(self._filter_rows)
        self.start_btn.clicked.connect(self._toggle)
        self.clear_btn.clicked.connect(self._clear)
        self._sampler.sample_ready.connect(self._on_sample)
        self._sampler.status.connect(self.status_label.setText)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)

    def set_session_getter(self, fn) -> None:
        self._session_getter = fn

    def set_connected(self, connected: bool) -> None:
        if not connected:
            self._stop_monitoring()
        self.start_btn.setEnabled(connected and bool(self._variables))

    def feed_rtt_data(self, channel: int, data: bytes) -> None:
        self._feed_trace("rtt", channel, data)

    def feed_swo_data(self, port: int, data: bytes) -> None:
        self._feed_trace("swo", port, data)

    def _feed_trace(self, transport: str, channel: int, data: bytes) -> None:
        if not self._stream_active or self.mode_combo.currentData() != transport:
            return
        parser = self._trace_parsers.setdefault((transport, int(channel)), TraceFrameParser())
        sample: dict[str, tuple[Any, bytes]] = {}
        for record in parser.feed(data):
            variable = self._variables_by_address.get(record.address)
            if variable is None or _variable_key(variable) not in self._stream_variables:
                continue
            value = self._decode_trace(record.value_type, record.raw, variable)
            sample[_variable_key(variable)] = (value, record.raw)
        if sample:
            self._on_sample(sample)

    @staticmethod
    def _decode_trace(value_type: int, raw: bytes, variable: ElfVariable) -> Any:
        import struct

        if value_type == TYPE_FLOAT32 and len(raw) == 4:
            return struct.unpack("<f", raw)[0]
        if value_type == TYPE_FLOAT64 and len(raw) == 8:
            return struct.unpack("<d", raw)[0]
        if value_type in (TYPE_SIGNED, TYPE_UNSIGNED):
            return int.from_bytes(raw, "little", signed=value_type == TYPE_SIGNED)
        return _decode_value(raw, variable)

    def load_path(self, path: str) -> bool:
        # A new image changes the address-to-variable map. Stop an active
        # stream first so late frames cannot update rows from the old ELF.
        self._stop_monitoring()
        try:
            image = load_elf(path)
        except Exception as exc:
            self._image = None
            self._variables = []
            self._variable_lookup.clear()
            self._variables_by_address.clear()
            self.table.setRowCount(0)
            self.status_label.setText(f"ELF 加载失败：{exc}")
            log.exception("ELF load failed")
            return False
        self._image = image
        self.path_edit.setText(str(image.path))
        self._variables = list(image.variables[:MAX_VARIABLES])
        self._variable_lookup = {_variable_key(variable): variable for variable in self._variables}
        self._variables_by_address = {variable.address: variable for variable in self._variables}
        self._populate_table()
        dwarf = "DWARF" if image.has_dwarf else "仅符号表"
        self.status_label.setText(
            f"已加载 {image.path.name} · {len(image.variables)} 个变量 · {dwarf}"
        )
        self.start_btn.setEnabled(bool(self._variables) and self._session_getter() is not None)
        return True

    def _choose_elf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 ELF/ALF", "", "ELF (*.elf *.axf *.alf);;All files (*)"
        )
        if path:
            self.load_path(path)

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        self._rows.clear()
        for variable in self._variables:
            row = self.table.rowCount()
            self.table.insertRow(row)
            key = _variable_key(variable)
            self._rows[key] = row
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(variable.name))
            self.table.setItem(row, 2, QTableWidgetItem(variable.display_address))
            self.table.setItem(row, 3, QTableWidgetItem(variable.type_name))
            self.table.setItem(row, 4, QTableWidgetItem("—"))
        self._filter_rows(self.filter_edit.text())

    def _filter_rows(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 1)
            self.table.setRowHidden(
                row, bool(needle and (name is None or needle not in name.text().lower()))
            )

    def _selected(self) -> list[ElfVariable]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            variable = self._variable_lookup.get(key)
            if variable is not None:
                result.append(variable)
        return result

    def _toggle(self) -> None:
        if self._sampler.running or self._stream_active:
            self._stop_monitoring()
            self.start_btn.setEnabled(bool(self._variables))
            return
        selected = self._selected()
        if not selected:
            self.status_label.setText("请先勾选要监控的变量")
            return
        mode = str(self.mode_combo.currentData() or "swd")
        if mode == "swd":
            session = self._session_getter() if callable(self._session_getter) else None
            if self._sampler.start(session, selected, self.interval_spin.value()):
                self.start_btn.setText("停止采样")
            return
        self._stream_active = True
        self._stream_variables = {_variable_key(variable) for variable in selected}
        self._trace_parsers.clear()
        self.start_btn.setText("停止数据流")
        self.status_label.setText("等待 RTT/SWO 数据帧…")

    def _mode_changed(self) -> None:
        if self._sampler.running or self._stream_active:
            self._stop_monitoring()
        if self.mode_combo.currentData() != "swd":
            self.status_label.setText("已切换为数据流模式，请先启动对应 RTT/SWO 读取器")
        else:
            self.status_label.setText("已切换为 SWD 轮询模式")

    def _stop_monitoring(self) -> None:
        self._sampler.stop()
        self._stream_active = False
        self._stream_variables.clear()
        self._trace_parsers.clear()
        self.start_btn.setText("开始采样")

    def _on_sample(self, sample: dict[str, tuple[Any, bytes | None]]) -> None:
        wave_values: dict[str, Any] = {}
        for key, (value, _raw) in sample.items():
            self._pending_values[key] = value
            wave_values[key] = value
        self.waveform.push_batch(wave_values)

    def _flush_pending_values(self) -> None:
        if not self._pending_values:
            return
        pending, self._pending_values = self._pending_values, {}
        for key, value in pending.items():
            row = self._rows.get(key)
            if row is not None and self.table.item(row, 4) is not None:
                self.table.item(row, 4).setText(_format_value(value))

    def _clear(self) -> None:
        self.waveform.clear()
        self._pending_values.clear()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 4) is not None:
                self.table.item(row, 4).setText("—")

    def retranslate(self) -> None:
        # Labels are intentionally concise; the page is usable in both locales
        # while the rest of the application is translated.
        pass

    def shutdown(self) -> None:
        self._sample_timer.stop()
        self._stop_monitoring()


__all__ = ["VariableMonitorPanel"]
