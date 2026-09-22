"""Shared UI-thread-safe background job helpers.

All long-running work should go through :class:`OpRunner` so completion
handlers stay on the GUI thread (never connect bare closures to worker
signals without a QObject slot receiver).
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal

from etools.logger import get_logger

log = get_logger("ui.runtime")


class Worker(QObject):
    """Runs a callable on a QThread; emits finished/failed from that thread."""

    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn: Callable[..., Any], cancel_event: threading.Event | None = None) -> None:
        super().__init__()
        self._fn = fn
        self.cancel_event = cancel_event or threading.Event()

    def _invoke(self) -> Any:
        """Call fn, injecting cancel_event only when the signature wants it.

        Never probe by catching TypeError — that would retry on TypeErrors
        raised inside the worker body and hide the real error.
        Never inject into an arbitrary positional slot (e.g. address/size),
        which would silently corrupt arguments.
        """
        fn = self._fn
        try:
            params = list(inspect.signature(fn).parameters.values())
        except (TypeError, ValueError):
            return fn()
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
            return fn(self.cancel_event)
        for p in params:
            if p.kind not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            name = p.name.lower()
            if "cancel" in name or name in {"event", "stop", "abort", "stop_event"}:
                return fn(self.cancel_event)
        return fn()

    def run(self) -> None:
        try:
            result = self._invoke()
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("worker error")
            self.failed.emit(str(exc))


class OpRunner(QObject):
    """Owns one background QThread at a time.

    Completion handlers must be QObject slots living on the GUI thread.
    Connecting QueuedConnection to a bare Python closure is unreliable
    (no receiver thread affinity) and can run cleanup on the worker
    thread → QThread.wait() on itself → crash (0xC0000409).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._on_ok: Callable[[Any], None] | None = None
        self._on_err: Callable[[str], None] | None = None
        self._on_cancel: Callable[[], None] | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self,
        fn: Callable[[], Any],
        on_ok: Callable[[Any], None],
        on_err: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> bool:
        if self.busy:
            return False
        self._on_ok = on_ok
        self._on_err = on_err
        self._on_cancel = on_cancel

        thread = QThread(self)
        worker = Worker(fn, cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(self._slot_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._slot_failed, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(self._slot_cancelled, Qt.ConnectionType.QueuedConnection)

        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    def _slot_finished(self, result) -> None:
        self._teardown()
        cb, self._on_ok, self._on_err = self._on_ok, None, None
        if cb is not None:
            cb(result)

    def _slot_failed(self, message: str) -> None:
        self._teardown()
        cb, self._on_err, self._on_ok = self._on_err, None, None
        if cb is not None:
            cb(message)

    def _slot_cancelled(self) -> None:
        self._teardown()
        cb, self._on_cancel = self._on_cancel, None
        self._on_ok = self._on_err = None
        if cb is not None:
            cb()

    def _teardown(self) -> None:
        thread, self._thread = self._thread, None
        worker, self._worker = self._worker, None
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                thread.wait(5000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()

    def shutdown(self) -> None:
        thread = self._thread
        worker = self._worker
        self._thread = self._worker = None
        self._on_ok = self._on_err = self._on_cancel = None
        if worker is not None:
            worker.cancel_event.set()
            for signal in (worker.finished, worker.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()


@dataclass
class TaskInfo:
    task_id: str
    runner: OpRunner
    cancel_event: threading.Event


class TaskManager(QObject):
    """Run multiple named background tasks concurrently."""

    task_started = Signal(str)
    task_finished = Signal(str, object)
    task_failed = Signal(str, str)
    task_cancelled = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: dict[str, TaskInfo] = {}

    def is_running(self, task_id: str) -> bool:
        info = self._tasks.get(task_id)
        return bool(info and info.runner.busy)

    def start(self, task_id: str, fn: Callable[..., Any]) -> bool:
        if self.is_running(task_id):
            return False
        runner = OpRunner(self)
        cancel = threading.Event()
        info = TaskInfo(task_id, runner, cancel)
        self._tasks[task_id] = info

        def ok(result):
            self._tasks.pop(task_id, None)
            self.task_finished.emit(task_id, result)
            runner.deleteLater()

        def fail(message):
            self._tasks.pop(task_id, None)
            self.task_failed.emit(task_id, message)
            runner.deleteLater()

        def cancelled():
            self._tasks.pop(task_id, None)
            self.task_cancelled.emit(task_id)
            runner.deleteLater()

        self.task_started.emit(task_id)
        runner.start(fn, ok, fail, cancel, cancelled)
        return True

    def cancel(self, task_id: str) -> bool:
        info = self._tasks.get(task_id)
        if not info or not info.runner.busy:
            return False
        info.cancel_event.set()
        return True

    def shutdown(self) -> None:
        for info in list(self._tasks.values()):
            info.cancel_event.set()
            info.runner.shutdown()
        self._tasks.clear()


class SignalRelay(QObject):
    """Marshal callbacks from worker threads onto the UI thread via Signal."""

    progressed = Signal(object)

    def push(self, info) -> None:
        self.progressed.emit(info)
