"""SFTP file-transfer panel (shown under Terminal tool)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from etools.i18n import tr
from etools.ui.runtime import OpRunner
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
        self.list_btn = QPushButton()
        self.list_btn.setObjectName("ghost")
        self.list_btn.setEnabled(False)
        head.addWidget(self.parent_btn)
        head.addWidget(self.mkdir_btn)
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
        root.addWidget(self.file_list, 1)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        root.addWidget(self.status)

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
        actions.addStretch(1)
        root.addLayout(actions)

        self.list_btn.clicked.connect(self.refresh)
        self.parent_btn.clicked.connect(self._go_parent)
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.upload_btn.clicked.connect(self.upload)
        self.download_btn.clicked.connect(self.download)
        self.file_list.itemDoubleClicked.connect(self._on_item)
        self.remote_edit.returnPressed.connect(self.refresh)
        self.retranslate()
        self._load_prefs()
        self.remote_edit.editingFinished.connect(self._persist_prefs)

    def retranslate(self) -> None:
        self.title.setText(tr("sftp.title"))
        self.lbl_remote.setText(tr("sftp.remote"))
        self.remote_edit.setPlaceholderText(tr("sftp.remote_ph"))
        self.list_btn.setText(tr("sftp.list"))
        self.parent_btn.setText(tr("sftp.parent"))
        self.mkdir_btn.setText(tr("sftp.mkdir"))
        self.upload_btn.setText(tr("sftp.upload"))
        self.download_btn.setText(tr("sftp.download"))

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
        if connected:
            self.refresh()
        else:
            self.status.setText(tr("sftp.no_ssh"))

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        remote = prefs.get("sftp_remote")
        if remote:
            self.remote_edit.setText(str(remote))

    def _persist_prefs(self) -> None:
        save_tool_prefs(self.tool_id, {"sftp_remote": self.remote_edit.text().strip()})

    def _run(self, fn, on_ok) -> None:
        if self._runner.busy:
            self.status.setText(tr("sftp.transfer_busy"))
            return
        self.status.setText("…")
        self._runner.start(fn, on_ok, self._on_fail)

    def _on_fail(self, msg: str) -> None:
        self.status.setText(tr("sftp.err", err=msg))
        self.file_list.clear()
        item = QListWidgetItem(tr("sftp.err", err=msg))
        self.file_list.addItem(item)

    def _remote_join(self, name: str) -> str:
        base = self.remote_edit.text().strip().rstrip("/")
        return f"{base}/{name}" if base else name

    def _set_path(self, path: str) -> None:
        self.remote_edit.setText(path)
        self._persist_prefs()
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
        path, _ = QFileDialog.getOpenFileName(self, tr("sftp.upload"), "")
        if not path:
            return
        remote = self._remote_join(Path(path).name)

        def work():
            self._ssh.sftp_upload(path, remote)
            return path, remote

        def done(result) -> None:
            src, dst = result
            self.status.setText(tr("sftp.up_ok", src=Path(src).name, dst=dst))
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
        local, _ = QFileDialog.getSaveFileName(self, tr("sftp.download"), name)
        if not local:
            return
        remote = self._remote_join(name)

        def work():
            self._ssh.sftp_download(remote, local)
            return remote, local

        def done(result) -> None:
            src, dst = result
            self.status.setText(tr("sftp.down_ok", src=src, dst=dst))

        self._run(work, done)

    def shutdown(self) -> None:
        self._persist_prefs()
        self._runner.shutdown()
