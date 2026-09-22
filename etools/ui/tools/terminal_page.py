"""SSH terminal page (commands). SFTP UI lives in the bottom SftpPanel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
)

from etools.core.ssh_link import (
    SshLink,
    inspect_host_key,
)
from etools.i18n import tr
from etools.ui.runtime import OpRunner
from etools.ui.shell import ToolActionSpec
from etools.ui.tool_prefs import load_tool_prefs, save_tool_prefs
from etools.ui.tools.base import ToolPage
from etools.ui.tools.sftp_panel import SftpPanel
from etools.ui.widgets.ip_edit import IPv4Edit

_HISTORY_MAX = 30


class TerminalPage(ToolPage):
    tool_id = "terminal"
    tool_title_key = "tool.terminal"

    #: Shared with SftpPanel
    ssh_link_changed = Signal(object)

    def _build(self) -> None:
        self._ssh = SshLink()
        self._opened = False
        self._runner = OpRunner(self)
        self._history: list[str] = []
        self._history_idx = -1

        self.ctx_ssh = self.ctx_group(tr("term.title"))

        self.host = IPv4Edit("192.168.1.10")
        self.lbl_host = self.form_row(tr("term.host"), self.host)

        self.user = QLineEdit("pi")
        self.user.setFixedHeight(28)
        self.lbl_user = self.form_row(tr("term.user"), self.user)

        self.port = QLineEdit("22")
        self.port.setFixedHeight(28)
        self.lbl_port = self.form_row(tr("term.port"), self.port)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setFixedHeight(28)
        self.lbl_pass = self.form_row(tr("term.password"), self.password)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.key_edit = QLineEdit()
        self.key_edit.setFixedHeight(28)
        self.key_edit.setPlaceholderText(tr("term.keyfile"))
        self.key_browse = QPushButton(tr("term.key_browse"))
        self.key_browse.setObjectName("ghost")
        self.key_browse.setFixedHeight(28)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.key_browse)
        from PySide6.QtWidgets import QWidget as _QW

        key_box = _QW()
        key_box.setLayout(key_row)
        self.lbl_key = self.form_row(tr("term.keyfile"), key_box)
        self.key_browse.clicked.connect(self._browse_key)

        self.conn_btn = QPushButton()
        self.conn_btn.setObjectName("accent")
        self.conn_btn.setFixedHeight(32)
        self.ctx_action(self.conn_btn)

        # Main: SSH output group + SFTP group (bottom)
        term_box = self.main_group("SSH")
        self.term_box = term_box
        term_lay = term_box.layout()
        self.term = QPlainTextEdit()
        self.term.setObjectName("logView")
        self.term.setReadOnly(True)
        term_lay.addWidget(self.term, 3)

        cmd_row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setFixedHeight(28)
        self.cmd.setEnabled(False)
        self.exec_btn = QPushButton()
        self.exec_btn.setObjectName("ghost")
        self.exec_btn.setEnabled(False)
        self.clear_btn = QPushButton(tr("term.clear"))
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setFixedHeight(28)
        cmd_row.addWidget(self.cmd, 1)
        cmd_row.addWidget(self.exec_btn)
        cmd_row.addWidget(self.clear_btn)
        term_lay.addLayout(cmd_row)

        self.sftp_panel = SftpPanel()
        self.ssh_link_changed.connect(self.sftp_panel.set_ssh)
        sftp_box = self.main_group(tr("sftp.title"))
        self.sftp_box = sftp_box
        sftp_box.layout().addWidget(self.sftp_panel, 1)

        self.conn_btn.clicked.connect(self.toggle_connection)
        self.exec_btn.clicked.connect(self.exec_command)
        self.cmd.returnPressed.connect(self.exec_command)
        self.cmd.installEventFilter(self)
        self.clear_btn.clicked.connect(self.clear_view)
        self.retranslate()
        self._load_prefs()
        self.host.editingFinished.connect(self._persist_prefs)
        self.user.editingFinished.connect(self._persist_prefs)
        self.port.editingFinished.connect(self._persist_prefs)
        self.key_edit.editingFinished.connect(self._persist_prefs)

    @property
    def ssh_link(self) -> SshLink:
        return self._ssh

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent, Qt

        if obj is self.cmd and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._browse_history(event.key() == Qt.Key.Key_Up)
                return True
        return super().eventFilter(obj, event)

    def _browse_history(self, up: bool) -> None:
        if not self._history:
            return
        if up:
            self._history_idx = min(self._history_idx + 1, len(self._history) - 1)
        else:
            self._history_idx = max(self._history_idx - 1, -1)
        if self._history_idx < 0:
            self.cmd.clear()
        else:
            self.cmd.setText(self._history[-(self._history_idx + 1)])

    def _browse_key(self) -> None:
        start = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, tr("term.key_title"), start)
        if path:
            self.key_edit.setText(path)
            self._persist_prefs()

    def retranslate(self) -> None:
        self.ctx_ssh.setTitle(tr("term.title"))
        self.lbl_host.setText(tr("term.host"))
        self.lbl_user.setText(tr("term.user"))
        self.lbl_port.setText(tr("term.port"))
        self.lbl_pass.setText(tr("term.password"))
        self.lbl_key.setText(tr("term.keyfile"))
        self.key_browse.setText(tr("term.key_browse"))
        self.key_edit.setPlaceholderText(tr("term.keyfile"))
        self.conn_btn.setText(tr("term.disconnect") if self._opened else tr("term.connect"))
        self.term.setPlaceholderText(tr("term.placeholder"))
        self.cmd.setPlaceholderText(tr("term.cmd_ph"))
        self.exec_btn.setText(tr("term.exec"))
        self.clear_btn.setText(tr("term.clear"))
        self.sftp_box.setTitle(tr("sftp.title"))
        self.sftp_panel.retranslate()

    def toolbar_actions(self) -> list[ToolActionSpec]:
        acts = [
            ToolActionSpec("toggle", "term.connect", "connect", self.toggle_connection),
            ToolActionSpec("exec", "term.exec", "read", self.exec_command),
            ToolActionSpec(
                "clear", "term.clear", "clear", self.clear_view, separator_before=True
            ),
        ]
        acts.extend(self.sftp_panel.toolbar_actions())
        return acts

    def toggle_connection(self) -> None:
        self._on_toggle()

    def exec_command(self) -> None:
        self._on_exec()

    def clear_view(self) -> None:
        self.term.clear()

    def _log(self, line: str) -> None:
        self.term.appendPlainText(line)

    def _repaint_btn(self) -> None:
        self.conn_btn.setObjectName("danger" if self._opened else "accent")
        st = self.conn_btn.style()
        st.unpolish(self.conn_btn)
        st.polish(self.conn_btn)

    def _set_ready(self, on: bool) -> None:
        self.cmd.setEnabled(on)
        self.exec_btn.setEnabled(on)

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        if prefs.get("host"):
            self.host.setText(str(prefs["host"]))
        if prefs.get("user"):
            self.user.setText(str(prefs["user"]))
        if prefs.get("port"):
            self.port.setText(str(prefs["port"]))
        if prefs.get("keyfile"):
            self.key_edit.setText(str(prefs["keyfile"]))
        # password intentionally not persisted

    def _persist_prefs(self) -> None:
        save_tool_prefs(
            self.tool_id,
            {
                "host": self.host.text().strip(),
                "user": self.user.text().strip(),
                "port": self.port.text().strip(),
                "keyfile": self.key_edit.text().strip(),
            },
        )

    def _confirm_host_key(self, host: str, port: int, fingerprint: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("term.hostkey_title"))
        box.setText(
            tr("term.hostkey_missing", host=host, port=port, fingerprint=fingerprint or "?")
        )
        trust = box.addButton(tr("term.hostkey_trust"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("term.hostkey_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is trust

    def _on_toggle(self) -> None:
        if self._opened:
            self._ssh.close()
            self._opened = False
            self._set_ready(False)
            self.conn_btn.setText(tr("term.connect"))
            self._repaint_btn()
            self._log(tr("term.closed"))
            self.ssh_link_changed.emit(None)
            self._persist_prefs()
            return
        host = self.host.text().strip()
        user = self.user.text().strip()
        password = self.password.text() or None
        keyfile = self.key_edit.text().strip() or None
        try:
            port = int(self.port.text().strip() or "22")
        except ValueError:
            self._log(tr("term.err", err="bad port"))
            return
        if not host:
            self._log(tr("term.err", err="host required"))
            return
        self.conn_btn.setEnabled(False)
        self._persist_prefs()

        status, fingerprint = inspect_host_key(host, port)
        accept_new = False
        if status == "mismatch":
            self._log(
                tr("term.hostkey_mismatch", host=host, port=port, fingerprint=fingerprint)
            )
            self.conn_btn.setEnabled(True)
            return
        if status == "missing":
            if not self._confirm_host_key(host, port, fingerprint or "?"):
                self.conn_btn.setEnabled(True)
                return
            accept_new = True

        def work():
            self._ssh.connect(
                host=host,
                port=port,
                username=user,
                password=password,
                key_filename=keyfile,
                accept_new_host_key=accept_new,
            )
            return user, host

        def ok(result) -> None:
            self._opened = True
            self._set_ready(True)
            self.conn_btn.setEnabled(True)
            self.conn_btn.setText(tr("term.disconnect"))
            self._repaint_btn()
            self._log(tr("term.opened", user=result[0], host=result[1]))
            self.ssh_link_changed.emit(self._ssh)

        def fail(msg: str) -> None:
            self.conn_btn.setEnabled(True)
            self._log(tr("term.err", err=msg))

        self._runner.start(work, ok, fail)

    def _on_exec(self) -> None:
        if not self._opened:
            return
        text = self.cmd.text().strip()
        if not text:
            return
        self.cmd.clear()
        if text not in self._history:
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._history_idx = -1

        def work():
            return text, self._ssh.exec_command(text)

        def ok(result) -> None:
            cmd, (status, out, err) = result
            self._log(f"$ {cmd}")
            if out:
                self._log(out.rstrip())
            if err:
                self._log(err.rstrip())
            self._log(f"[exit {status}]")

        def fail(msg: str) -> None:
            self._log(tr("term.err", err=msg))

        self._runner.start(work, ok, fail)

    def shutdown(self) -> None:
        self._persist_prefs()
        self._runner.shutdown()
        self._ssh.close()
        self.sftp_panel.shutdown()
