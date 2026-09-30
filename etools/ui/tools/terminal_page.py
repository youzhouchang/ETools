"""SSH terminal page (commands). SFTP UI lives in the bottom SftpPanel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
)

from etools.core.net_addr import suggest_remote_ipv4
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
_SESSIONS_MAX = 20
_QUICK_COMMANDS = [
    ("uptime", "uptime"),
    ("df -h", "df -h"),
    ("free -m", "free -m"),
    ("uname -a", "uname -a"),
    ("ip a", "ip a"),
    ("top -bn1 | head", "top -bn1 | head -n 15"),
]


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

        self.session_combo = QComboBox()
        self.session_combo.setFixedHeight(28)
        self.session_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.session_save_btn = QPushButton(tr("term.session_save"))
        self.session_save_btn.setObjectName("ghost")
        self.session_save_btn.setFixedHeight(28)
        self.session_save_btn.setMinimumWidth(64)
        self.session_del_btn = QPushButton(tr("term.session_delete"))
        self.session_del_btn.setObjectName("ghost")
        self.session_del_btn.setFixedHeight(28)
        self.session_del_btn.setMinimumWidth(56)
        # Session picker + actions share one form row so buttons are not
        # crushed into a leftover empty-label strip below.
        sess_row = QHBoxLayout()
        sess_row.setContentsMargins(0, 0, 0, 0)
        sess_row.setSpacing(6)
        sess_row.addWidget(self.session_combo, 1)
        sess_row.addWidget(self.session_save_btn)
        sess_row.addWidget(self.session_del_btn)
        from PySide6.QtWidgets import QWidget as _QWidget

        sess_wrap = _QWidget()
        sess_wrap.setLayout(sess_row)
        self.lbl_session = self.form_row(tr("term.session"), sess_wrap)

        self.host = IPv4Edit(suggest_remote_ipv4())
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

        # Private key: browse button sits inside the line edit (visible label).
        self.key_edit = QLineEdit()
        self.key_edit.setFixedHeight(28)
        self.key_edit.setTextMargins(0, 0, 56, 0)
        self.key_edit.setPlaceholderText(tr("term.keyfile_ph"))
        self.key_browse = QToolButton(self.key_edit)
        self.key_browse.setText(tr("term.key_browse"))
        self.key_browse.setFixedHeight(22)
        self.key_browse.setStyleSheet(
            "QToolButton { border: none; background: transparent;"
            " padding: 0 6px; color: #8A96A8; font-size: 11px; }"
            "QToolButton:hover { color: #1F2933; background: rgba(0,0,0,0.08);"
            " border-radius: 4px; }"
        )
        self.key_browse.clicked.connect(self._browse_key)
        self.lbl_key = self.form_row(tr("term.keyfile"), self.key_edit)
        self.key_edit.installEventFilter(self)
        self._place_key_browse()

        self.conn_btn = QPushButton()
        self.conn_btn.setObjectName("accent")
        self.conn_btn.setFixedHeight(32)
        self.ctx_action(self.conn_btn)

        # Main: SSH output group + SFTP group (bottom)
        term_box = self.main_group(tr("term.command_mode"))
        self.term_box = term_box
        term_lay = term_box.layout()
        self.term = QPlainTextEdit()
        self.term.setObjectName("logView")
        self.term.setReadOnly(True)
        self.term.document().setMaximumBlockCount(10000)
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

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        self._quick_btns: list[QPushButton] = []
        for label, command in _QUICK_COMMANDS:
            btn = QPushButton(label)
            btn.setObjectName("ghost")
            btn.setFixedHeight(26)
            btn.setToolTip(command)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _c=False, c=command: self._run_quick(c))
            quick_row.addWidget(btn)
            self._quick_btns.append(btn)
        self.copy_out_btn = QPushButton(tr("mon.copy"))
        self.copy_out_btn.setObjectName("ghost")
        self.copy_out_btn.setFixedHeight(26)
        self.copy_out_btn.clicked.connect(self._copy_output)
        self.snippet_btn = QPushButton(tr("term.snippets"))
        self.snippet_btn.setObjectName("ghost")
        self.snippet_btn.setFixedHeight(26)
        self.snippet_btn.clicked.connect(self._show_snippets)
        quick_row.addStretch(1)
        quick_row.addWidget(self.snippet_btn)
        quick_row.addWidget(self.copy_out_btn)
        term_lay.addLayout(quick_row)

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
        self.session_combo.currentIndexChanged.connect(self._on_session_selected)
        self.session_save_btn.clicked.connect(self._save_session)
        self.session_del_btn.clicked.connect(self._delete_session)
        self.retranslate()
        self._load_prefs()
        self._reload_sessions()
        self.host.editingFinished.connect(self.persist_prefs)
        self.user.editingFinished.connect(self.persist_prefs)
        self.port.editingFinished.connect(self.persist_prefs)
        self.key_edit.editingFinished.connect(self.persist_prefs)

    @property
    def ssh_link(self) -> SshLink:
        return self._ssh

    def eventFilter(self, obj, event):  # noqa: N802
        from PySide6.QtCore import QEvent, Qt

        if obj is getattr(self, "key_edit", None) and event.type() == QEvent.Type.Resize:
            self._place_key_browse()
        if obj is getattr(self, "cmd", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._browse_history(event.key() == Qt.Key.Key_Up)
                return True
        return super().eventFilter(obj, event)

    def _place_key_browse(self) -> None:
        btn = getattr(self, "key_browse", None)
        edit = getattr(self, "key_edit", None)
        if btn is None or edit is None:
            return
        w = max(40, btn.sizeHint().width())
        btn.resize(w, 22)
        btn.move(edit.width() - w - 3, (edit.height() - 22) // 2)

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
            self.persist_prefs()

    def retranslate(self) -> None:
        self.term_box.setTitle(tr("term.command_mode"))
        self.ctx_ssh.setTitle(tr("term.title"))
        self.lbl_session.setText(tr("term.session"))
        self.session_save_btn.setText(tr("term.session_save"))
        self.session_del_btn.setText(tr("term.session_delete"))
        self.lbl_host.setText(tr("term.host"))
        self.lbl_user.setText(tr("term.user"))
        self.lbl_port.setText(tr("term.port"))
        self.lbl_pass.setText(tr("term.password"))
        self.lbl_key.setText(tr("term.keyfile"))
        self.key_browse.setText(tr("term.key_browse"))
        self.key_edit.setPlaceholderText(tr("term.keyfile_ph"))
        self.conn_btn.setText(tr("term.disconnect") if self._opened else tr("term.connect"))
        self.term.setPlaceholderText(tr("term.placeholder"))
        self.cmd.setPlaceholderText(tr("term.cmd_ph"))
        self.exec_btn.setText(tr("term.exec"))
        self.clear_btn.setText(tr("term.clear"))
        self.snippet_btn.setText(tr("term.snippets"))
        self.copy_out_btn.setText(tr("mon.copy"))
        self.sftp_box.setTitle(tr("sftp.title"))
        self.sftp_panel.retranslate()

    def toolbar_actions(self) -> list[ToolActionSpec]:
        acts = [
            ToolActionSpec("toggle", "term.connect", "connect", self.toggle_connection),
            ToolActionSpec("exec", "term.exec", "read", self.exec_command),
            ToolActionSpec("run_script", "script.run_menu", "hex", self._run_script_menu),
            ToolActionSpec("clear", "term.clear", "clear", self.clear_view, separator_before=True),
        ]
        acts.extend(self.sftp_panel.toolbar_actions())
        return acts

    def _run_script_menu(self) -> None:
        from etools.ui.tools.script_menu import exec_script_menu

        exec_script_menu(self)

    @property
    def is_open(self) -> bool:
        return self._opened

    def link_status(self) -> tuple[str, str]:
        if not self._opened:
            return tr("status.link_idle"), "warn"
        host = getattr(self, "host", None)
        host_text = host.text().strip() if host is not None else ""
        return tr("status.link_ssh", host=host_text or "?"), "ok"

    def toggle_connection(self) -> None:
        self._on_toggle()

    def exec_command(self) -> None:
        self._on_exec()

    def clear_view(self) -> None:
        self.term.clear()

    def lua_send_text(self, text: str) -> bool:
        """Run one SSH command from Lua (terminal tool)."""
        if not self._opened:
            return False
        text = str(text)
        try:
            status, out, err = self._ssh.exec_command(text)
            self._log(f"$ {text}")
            if out:
                self._log(out.rstrip())
            if err:
                self._log(err.rstrip())
            self._log(f"[exit {status}]")
            return status == 0
        except Exception as exc:  # noqa: BLE001
            self._log(tr("term.err", err=str(exc)))
            return False

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
        for btn in self._quick_btns:
            btn.setEnabled(on)

    def _run_quick(self, command: str) -> None:
        self.cmd.setText(command)
        self._on_exec()

    def _copy_output(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self.term.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._log(tr("mon.copied"))

    def _snippets(self) -> list[str]:
        prefs = load_tool_prefs(self.tool_id)
        raw = prefs.get("snippets")
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if isinstance(x, str) and x.strip()][:30]

    def _show_snippets(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        manage = menu.addAction(tr("term.snippets_edit"))
        menu.addSeparator()
        snippets = self._snippets()
        if not snippets:
            menu.addAction("—")
        else:
            for text in snippets:
                menu.addAction(text, lambda t=text: self._run_quick(t))
        chosen = menu.exec(self.snippet_btn.mapToGlobal(self.snippet_btn.rect().bottomLeft()))
        if chosen is manage:
            self._edit_snippets()

    def _edit_snippets(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("term.snippets"))
        dlg.setMinimumSize(420, 320)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setPlaceholderText(tr("term.snippets_ph"))
        edit.setPlainText("\n".join(self._snippets()))
        lay.addWidget(edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec():
            lines = [ln.strip() for ln in edit.toPlainText().splitlines() if ln.strip()]
            save_tool_prefs(self.tool_id, {"snippets": lines[:30]})

    def _sessions(self) -> list[dict]:
        prefs = load_tool_prefs(self.tool_id)
        raw = prefs.get("sessions")
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict) and item.get("name") and item.get("host"):
                out.append(item)
        return out[:_SESSIONS_MAX]

    def _reload_sessions(self) -> None:
        current = self.session_combo.currentData()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem(tr("term.session_none"), "")
        for item in self._sessions():
            label = f"{item.get('name')} · {item.get('user', '')}@{item.get('host')}"
            self.session_combo.addItem(label, item.get("name"))
        if current:
            idx = self.session_combo.findData(current)
            if idx >= 0:
                self.session_combo.setCurrentIndex(idx)
        self.session_combo.blockSignals(False)

    def _on_session_selected(self, _index: int = 0) -> None:
        name = self.session_combo.currentData()
        if not name:
            return
        for item in self._sessions():
            if item.get("name") == name:
                self.host.setText(str(item.get("host", "")))
                self.user.setText(str(item.get("user", "")))
                self.port.setText(str(item.get("port", "22")))
                self.key_edit.setText(str(item.get("keyfile", "") or ""))
                self.persist_prefs()
                break

    def _save_session(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        host = self.host.text().strip()
        if not host:
            self._log(tr("term.err", err="host required"))
            return
        default = f"{self.user.text().strip() or 'user'}@{host}"
        name, ok = QInputDialog.getText(
            self, tr("term.session_save"), tr("term.session_name"), text=default
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        sessions = [s for s in self._sessions() if s.get("name") != name]
        sessions.insert(
            0,
            {
                "name": name,
                "host": host,
                "user": self.user.text().strip(),
                "port": self.port.text().strip() or "22",
                "keyfile": self.key_edit.text().strip(),
            },
        )
        sessions = sessions[:_SESSIONS_MAX]
        save_tool_prefs(self.tool_id, {"sessions": sessions})
        self._reload_sessions()
        idx = self.session_combo.findData(name)
        if idx >= 0:
            self.session_combo.setCurrentIndex(idx)
        self._log(tr("term.session_saved", name=name))

    def _delete_session(self) -> None:
        name = self.session_combo.currentData()
        if not name:
            return
        sessions = [s for s in self._sessions() if s.get("name") != name]
        save_tool_prefs(self.tool_id, {"sessions": sessions})
        self._reload_sessions()
        self._log(tr("term.session_deleted", name=name))

    def _load_prefs(self) -> None:
        prefs = load_tool_prefs(self.tool_id)
        host = str(prefs.get("host") or "").strip()
        if not host:
            # Reuse the last Ethernet target when Terminal has no host yet.
            eth = load_tool_prefs("ethernet")
            by_mode = eth.get("host_by_mode") or {}
            host = str(
                by_mode.get("client")
                or by_mode.get("udp")
                or eth.get("host")
                or suggest_remote_ipv4()
            ).strip()
            if host in {"", "0.0.0.0"}:
                host = suggest_remote_ipv4()
        if host:
            self.host.setText(host)
        if prefs.get("user"):
            self.user.setText(str(prefs["user"]))
        if prefs.get("port"):
            self.port.setText(str(prefs["port"]))
        if prefs.get("keyfile"):
            self.key_edit.setText(str(prefs["keyfile"]))
        # password intentionally not persisted

    def persist_prefs(self) -> None:
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
        if self._runner.busy:
            return
        if self._opened:
            self._ssh.close()
            self._opened = False
            self._set_ready(False)
            self.conn_btn.setText(tr("term.connect"))
            self._repaint_btn()
            self._log(tr("term.closed"))
            self.ssh_link_changed.emit(None)
            self.persist_prefs()
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
        self.persist_prefs()

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

        def inspected(result):
            status, fingerprint = result
            if status == "mismatch":
                fail(tr("term.hostkey_mismatch", host=host, port=port, fingerprint=fingerprint))
                return
            accept_new = False
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

            self._runner.start(work, ok, fail)

        self._log(tr("connection.connecting"))
        self._runner.start(lambda: inspect_host_key(host, port), inspected, fail)

    def _on_exec(self) -> None:
        if not self._opened or self._runner.busy:
            return
        text = self.cmd.text().strip()
        if not text:
            return
        if text not in self._history:
            self._history.append(text)
            del self._history[:-_HISTORY_MAX]
        self._history_idx = -1

        def work():
            return text, self._ssh.exec_command(text)

        def ok(result) -> None:
            self._set_ready(self._opened)
            _cmd, (status, out, err) = result
            if out:
                self._log(out.rstrip())
            if err:
                self._log(err.rstrip())
            self._log(f"[exit {status}]")

        def fail(msg: str) -> None:
            self._set_ready(self._opened)
            self._log(tr("term.err", err=msg))

        if self._runner.start(work, ok, fail):
            self.cmd.clear()
            self._set_ready(False)
            self._log(f"$ {text}")

    def shutdown(self) -> None:
        self.persist_prefs()
        self._runner.shutdown()
        self._ssh.close()
        self.sftp_panel.shutdown()
