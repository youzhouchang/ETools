"""Batch firmware programming queue dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.core.models import FIRMWARE_EXTENSIONS
from etools.i18n import tr


class BatchProgramDialog(QDialog):
    """Collect firmware paths and run them one-by-one via *program_fn*."""

    def __init__(self, program_fn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("batch.title"))
        self.setMinimumSize(520, 360)
        self._program_fn = program_fn
        self._queue: list[str] = []
        self._index = 0
        self._running = False
        self._stop_requested = False
        self._active_queue: tuple[str, ...] = ()

        root = QVBoxLayout(self)
        self.hint = QLabel(tr("batch.hint"))
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.listw = QListWidget()
        root.addWidget(self.listw, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton(tr("batch.add"))
        self.add_btn.setObjectName("ghost")
        self.remove_btn = QPushButton(tr("batch.remove"))
        self.remove_btn.setObjectName("ghost")
        self.start_btn = QPushButton(tr("batch.start"))
        self.start_btn.setObjectName("accent")
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        row.addWidget(self.start_btn)
        self.stop_btn = QPushButton(tr("script.stop"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("mutedLabel")
        root.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.add_btn.clicked.connect(self._add)
        self.remove_btn.clicked.connect(self._remove)
        self.start_btn.clicked.connect(self._start)

    def _add(self) -> None:
        if self._running:
            return
        from PySide6.QtWidgets import QFileDialog

        paths, _ = QFileDialog.getOpenFileNames(self, tr("batch.add"), "", FIRMWARE_EXTENSIONS)
        for p in paths:
            if p not in self._queue:
                self._queue.append(p)
                QListWidgetItem(Path(p).name, self.listw)
        self._refresh()

    def _remove(self) -> None:
        if self._running:
            return
        row = self.listw.currentRow()
        if 0 <= row < len(self._queue):
            del self._queue[row]
            self.listw.takeItem(row)
        self._refresh()

    def _refresh(self) -> None:
        self.start_btn.setEnabled(bool(self._queue) and not self._running)
        self.add_btn.setEnabled(not self._running)
        self.remove_btn.setEnabled(not self._running)
        self.stop_btn.setEnabled(self._running and not self._stop_requested)
        self.hint.setText(tr("batch.hint_n", n=len(self._queue)))

    def _start(self) -> None:
        if not self._queue or self._running:
            return
        self._running = True
        self._stop_requested = False
        self._active_queue = tuple(self._queue)
        for index, path in enumerate(self._active_queue):
            self.listw.item(index).setText(Path(path).name)
        self._index = 0
        self._refresh()
        self.status.setText(tr("batch.running"))
        self._run_next()

    def _run_next(self) -> None:
        if self._stop_requested or self._index >= len(self._active_queue):
            self._running = False
            self.status.setText(tr("script.stopped") if self._stop_requested else tr("batch.done"))
            self._refresh()
            return
        path = self._active_queue[self._index]
        self.status.setText(
            tr("batch.item", i=self._index + 1, n=len(self._active_queue), name=Path(path).name)
        )
        self.listw.setCurrentRow(self._index)

        def ok(_result=None) -> None:
            self.listw.item(self._index).setText(f"{Path(path).name} - OK")
            self._index += 1
            self._run_next()

        def fail(msg: str) -> None:
            self.listw.item(self._index).setText(f"{Path(path).name} - {msg}")
            self._running = False
            self.status.setText(tr("batch.failed", err=msg))
            self._refresh()

        try:
            self._program_fn(path, ok, fail)
        except Exception as exc:  # noqa: BLE001
            fail(str(exc))

    def _stop(self) -> None:
        self._stop_requested = True
        self.status.setText(tr("batch.stopping"))
        self._refresh()

    def reject(self) -> None:
        if self._running:
            self._stop()
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._running:
            self._stop()
            event.ignore()
        else:
            super().closeEvent(event)
