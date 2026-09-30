"""SFTP file-transfer panel (shown under Terminal tool)."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.ui.runtime import OpRunner, SignalRelay
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs

ROLE = 32  # Qt.UserRole


class SftpPanel(QWidget):
    """Upload / download / browse remote files via an SshLink."""

    tool_id = "terminal"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sftpPanel")
        self._ssh = None
        self._runner = OpRunner(self)
        self._progress_relay = SignalRelay(self)
        self._progress_relay.progressed.connect(self._show_progress)
        self._cancel_event: threading.Event | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.parent_btn = QPushButton()
        self.parent_btn.setObjectName("ghost")
        self.parent_btn.setEnabled(False)
        self.mkdir_btn = QPushButton()
        self.mkdir_btn.setObjectName("ghost")
        self.mkdir_btn.setEnabled(False)
        self.delete_btn = QPushButton()
        self.delete_btn.setObjectName("ghost")
        self.delete_btn.setEnabled(False)
        self.list_btn = QPushButton()
        self.list_btn.setObjectName("ghost")
        self.list_btn.setEnabled(False)
        head.addWidget(self.parent_btn)
        head.addWidget(self.mkdir_btn)
        head.addWidget(self.delete_btn)
        head.addWidget(self.list_btn)
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_remote = QLabel()
        self.lbl_remote.setMinimumWidth(64)
        self.remote_edit = QLineEdit("/home/pi/")
        self.remote_edit.setFixedHeight(28)
        row.addWidget(self.lbl_remote)
        row.addWidget(self.remote_edit, 1)
        root.addLayout(row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.file_list, 1)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setEnabled(False)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.upload_btn = QPushButton()
        self.upload_btn.setObjectName("accent")
        self.upload_btn.setEnabled(False)
        self.download_btn = QPushButton()
        self.download_btn.setObjectName("ghost")
        self.download_btn.setEnabled(False)
        actions.addWidget(self.upload_btn)
        actions.addWidget(self.download_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.list_btn.clicked.connect(self.refresh)
        self.parent_btn.clicked.connect(self._go_parent)
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.upload_btn.clicked.connect(self.upload)
        self.download_btn.clicked.connect(self.download)
        self.cancel_btn.clicked.connect(self._cancel_transfer)
        self.file_list.itemDoubleClicked.connect(self._on_item)
        self.remote_edit.returnPressed.connect(self.refresh)
        self.retranslate()
        self._load_prefs()
        self.remote_edit.editingFinished.connect(self.persist_prefs)

    def retranslate(self) -> None:
        self.title.setText(tr("sftp.title"))
        self.lbl_remote.setText(tr("sftp.remote"))
        self.remote_edit.setPlaceholderText(tr("sftp.remote_ph"))
        self.list_btn.setText(tr("sftp.list"))
        self.parent_btn.setText(tr("sftp.parent"))
        self.mkdir_btn.setText(tr("sftp.mkdir"))
        self.delete_btn.setText(tr("sftp.delete"))
        self.upload_btn.setText(tr("sftp.upload"))
        self.download_btn.setText(tr("sftp.download"))
        self.cancel_btn.setText(tr("sftp.cancel"))

    def toolbar_actions(self) -> list[ToolActionSpec]:
        return [
            ToolActionSpec("list", "sftp.list", "refresh", self.refresh),
            ToolActionSpec("upload", "sftp.upload", "save", self.upload),
            ToolActionSpec("download", "sftp.download", "open", self.download),
        ]

    def set_ssh(self, ssh) -> None:
        """Bind/unbind the shared SshLink from the Terminal page."""
        self._ssh = ssh
        connected = ssh is not None and getattr(ssh, "is_connected", False)
        self.list_btn.setEnabled(connected)
        self.upload_btn.setEnabled(connected)
        self.download_btn.setEnabled(connected)
        self.parent_btn.setEnabled(connected)
        self.mkdir_btn.setEnabled(connected)
        self.delete_btn.setEnabled(connected)
        if connected:
            self.refresh()
        else:
            self.status.setText(tr("sftp.no_ssh"))

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        remote = prefs.get("sftp_remote")
        if remote:
            self.remote_edit.setText(str(remote))

    def persist_prefs(self) -> None:
        save_tool_prefs(self.tool_id, {"sftp_remote": self.remote_edit.text().strip()})

    def _run(self, fn, on_ok) -> None:
        if self._runner.busy:
            self.status.setText(tr("sftp.transfer_busy"))
            return
        self.status.setText("…")
        self.progress.setValue(0)
        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        self.cancel_btn.setEnabled(True)
        self._runner.start(
            fn,
            on_ok,
            self._on_fail,
            cancel_event=cancel_event,
            on_cancel=self._on_cancelled,
        )

    def _cancel_transfer(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.status.setText(tr("sftp.cancelling"))
            self.cancel_btn.setEnabled(False)

    def _finish_transfer(self) -> None:
        self._cancel_event = None
        self.cancel_btn.setEnabled(False)

    def _on_cancelled(self) -> None:
        self._finish_transfer()
        self.status.setText(tr("sftp.cancelled"))

    def _show_progress(self, info) -> None:
        done, total, label = info
        self.progress.setRange(0, 100)
        self.progress.setValue(min(100, int(done * 100 / total)) if total else 0)
        self.status.setText(f"{label}: {done:,} / {total:,} B")

    def _on_fail(self, msg: str) -> None:
        self._finish_transfer()
        self.status.setText(tr("sftp.err", err=msg))

    def _remote_join(self, name: str) -> str:
        base = self.remote_edit.text().strip().rstrip("/")
        return f"{base}/{name}" if base else name

    def _set_path(self, path: str) -> None:
        self.remote_edit.setText(path)
        self.persist_prefs()
        self.refresh()

    def _go_parent(self) -> None:
        path = self.remote_edit.text().strip() or "/"
        if path in ("/", ""):
            self._set_path("/")
            return
        parent = path.rstrip("/").rsplit("/", 1)[0] or "/"
        self._set_path(parent if parent else "/")

    def refresh(self) -> None:
        if self._ssh is None or not self._ssh.is_connected:
            self.status.setText(tr("sftp.no_ssh"))
            return
        path = self.remote_edit.text().strip() or "."
        self._run(lambda: self._ssh.sftp_listdir(path), self._fill_list)

    def _fill_list(self, rows) -> None:
        self._finish_transfer()
        self.file_list.clear()
        for name, kind, size in rows:
            label = f"{name}/" if kind == "dir" else f"{name}  ({size:,} B)"
            item = QListWidgetItem(label)
            item.setData(ROLE, (name, kind))
            self.file_list.addItem(item)
        self.status.setText(f"{len(rows)}")

    def _selected(self) -> tuple[str, str] | None:
        item = self.file_list.currentItem()
        if item is None:
            return None
        data = item.data(ROLE)
        return (str(data[0]), str(data[1])) if data else None

    def _on_item(self, item: QListWidgetItem) -> None:
        data = item.data(ROLE)
        if not data:
            return
        name, kind = str(data[0]), str(data[1])
        if kind == "dir":
            self._set_path(self._remote_join(name))
        else:
            self.download()

    def _delete_selected(self) -> None:
        items = self.file_list.selectedItems()
        if not items or self._ssh is None:
            return
        from PySide6.QtWidgets import QMessageBox

        names = [it.text().split("\t")[0] for it in items]
        ret = QMessageBox.question(
            self,
            tr("sftp.delete"),
            tr("sftp.delete_confirm", names=", ".join(names[:5])),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if ret != QMessageBox.StandardButton.Ok:
            return
        base = self.remote_edit.text().strip() or "/"
        if not base.endswith("/"):
            base += "/"

        def work() -> int:
            count = 0
            for name in names:
                self._ssh.sftp_remove(base + name)
                count += 1
            return count

        def ok(count) -> None:
            self.status.setText(tr("sftp.delete_done", n=int(count)))
            self.refresh()

        def fail(msg: str) -> None:
            self.status.setText(msg)

        self._runner.start(work, ok, fail)

    def _mkdir(self) -> None:
        if self._ssh is None or not self._ssh.is_connected:
            self.status.setText(tr("sftp.no_ssh"))
            return
        name, ok = QInputDialog.getText(self, tr("sftp.mkdir_title"), tr("sftp.mkdir_label"))
        if not ok or not name.strip():
            return
        remote = self._remote_join(name.strip())

        def work():
            self._ssh.sftp_mkdir(remote)
            return remote

        def done(path: str) -> None:
            self.status.setText(tr("sftp.up_ok", src="mkdir", dst=path))
            self.refresh()

        self._run(work, done)

    def upload(self) -> None:
        if self._ssh is None or not self._ssh.is_connected:
            self.status.setText(tr("sftp.no_ssh"))
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("sftp.upload"), "")
        if not paths:
            return
        paths = list(paths)
        relay = self._progress_relay
        remote_base = self.remote_edit.text().strip().rstrip("/")

        def work(cancel_event):
            for index, path in enumerate(paths, 1):
                if cancel_event and cancel_event.is_set():
                    return paths[: index - 1]
                remote = f"{remote_base}/{Path(path).name}" if remote_base else Path(path).name
                def progress(done, total, i=index, p=path):
                    relay.push((done, total, f"{i}/{len(paths)} {Path(p).name}"))
                self._ssh.sftp_upload(path, remote, progress)
            return paths

        def done(result) -> None:
            self._finish_transfer()
            self.status.setText(
                tr(
                    "sftp.up_ok",
                    src=f"{len(result)} file(s)",
                    dst=remote_base or ".",
                )
            )
            self.progress.setValue(100)
            self.refresh()

        self._run(work, done)

    def download(self) -> None:
        if self._ssh is None or not self._ssh.is_connected:
            self.status.setText(tr("sftp.no_ssh"))
            return
        sel = self._selected()
        if sel is None or sel[1] != "file":
            self.status.setText(tr("sftp.select_file"))
            return
        name = sel[0]
        selected = [item.data(ROLE) for item in self.file_list.selectedItems()]
        files = [(str(row[0]), str(row[1])) for row in selected if row and row[1] == "file"]
        if not files:
            files = [(name, "file")]
        target = (
            QFileDialog.getExistingDirectory(self, tr("sftp.download"), "")
            if len(files) > 1
            else ""
        )
        if len(files) > 1 and not target:
            return
        if len(files) == 1:
            local, _ = QFileDialog.getSaveFileName(self, tr("sftp.download"), name)
            if not local:
                return
            destinations = [(files[0][0], local)]
        else:
            destinations = [(n, str(Path(target) / n)) for n, _ in files]
        relay = self._progress_relay
        remote_base = self.remote_edit.text().strip().rstrip("/")

        def work(cancel_event):
            for index, (remote_name, local_path) in enumerate(destinations, 1):
                if cancel_event and cancel_event.is_set():
                    return destinations[: index - 1]
                remote = f"{remote_base}/{remote_name}" if remote_base else remote_name
                def progress(done, total, i=index, n=remote_name):
                    relay.push((done, total, f"{i}/{len(destinations)} {n}"))
                self._ssh.sftp_download(remote, local_path, progress)
            return destinations

        def done(result) -> None:
            self._finish_transfer()
            destination = Path(result[0][1]).parent if result else ""
            self.status.setText(
                tr("sftp.down_ok", src=f"{len(result)} file(s)", dst=destination)
            )
            self.progress.setValue(100)

        self._run(work, done)

    def shutdown(self) -> None:
        self.persist_prefs()
        self._runner.shutdown()
