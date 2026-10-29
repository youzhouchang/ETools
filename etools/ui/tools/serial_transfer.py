"""Serial page: raw file send and YMODEM/XMODEM transfers."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QProgressBar, QPushButton

from etools.i18n import tr


class SerialTransferMixin:
    """File transfer controls and workers for SerialPage."""

    def _build_transfer_controls(self) -> None:
        """Protocol pickers, send/receive buttons, and the progress row."""
        self.xfer_proto = QComboBox()
        self.xfer_proto.setFixedHeight(28)
        for pid, label in (
            ("ymodem", "YMODEM"),
            ("xmodem", "XMODEM"),
            ("zmodem", "ZMODEM"),
            ("raw", "Raw"),
        ):
            self.xfer_proto.addItem(label, pid)
        self.xfer_proto.setToolTip(tr("serial.xfer_proto_tip"))
        self.xfer_proto.currentIndexChanged.connect(lambda _i: self._relabel_xfer_buttons())
        self.xmode_combo = QComboBox()
        self.xmode_combo.setFixedHeight(28)
        self.xmode_combo.addItem(tr("serial.xmode_crc"), "crc")
        self.xmode_combo.addItem(tr("serial.xmode_checksum"), "checksum")
        self.xmode_combo.setToolTip(tr("serial.xmode_tip"))
        self.ymodem_btn = QPushButton(tr("serial.ymodem_send"))
        self.ymodem_btn.setObjectName("ghost")
        self.ymodem_btn.setFixedHeight(28)
        self.ymodem_btn.setMinimumWidth(80)
        self.ymodem_btn.setEnabled(False)
        self.ymodem_btn.setToolTip(tr("serial.ymodem_tip"))
        self.ymodem_recv_btn = QPushButton(tr("serial.ymodem_recv"))
        self.ymodem_recv_btn.setObjectName("ghost")
        self.ymodem_recv_btn.setFixedHeight(28)
        self.ymodem_recv_btn.setMinimumWidth(80)
        self.ymodem_recv_btn.setEnabled(False)
        self.ymodem_recv_btn.setToolTip(tr("serial.ymodem_recv_tip"))
        self.xfer_progress = QProgressBar()
        self.xfer_progress.setFixedHeight(18)
        self.xfer_progress.setRange(0, 100)
        self.xfer_progress.setValue(0)
        self.xfer_progress.setVisible(False)
        self.xfer_cancel_btn = QPushButton(tr("serial.xfer_cancel"))
        self.xfer_cancel_btn.setObjectName("ghost")
        self.xfer_cancel_btn.setFixedHeight(18)
        self.xfer_cancel_btn.setVisible(False)

    def _on_send_file(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        if not self._opened:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("serial.send_file_title"), "", tr("hex.file_filter")
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            self.traffic.append_status(tr("serial.send_file_err", err=str(exc)))
            return
        try:
            self._link.write(data)
        except Exception as exc:  # noqa: BLE001
            self.traffic.append_status(tr("serial.send_file_err", err=str(exc)))
            return
        self.traffic.append_tx(data)
        self.traffic.append_status(
            tr("serial.send_file_done", name=Path(path).name, size=len(data))
        )

    def _xfer_mode(self) -> str:
        return "checksum" if self.xmode_combo.currentData() == "checksum" else "crc"

    def _relabel_xfer_buttons(self) -> None:
        """Send/Recv labels follow the selected protocol."""
        proto = str(self.xfer_proto.currentData() or "ymodem")
        name = {
            "ymodem": "YMODEM",
            "xmodem": "XMODEM",
            "zmodem": "ZMODEM",
            "raw": "RAW",
        }.get(proto, proto.upper())
        self.ymodem_btn.setText(tr("serial.xfer_send", proto=name))
        self.ymodem_btn.setToolTip(tr("serial.xfer_send_tip", proto=name))
        self.ymodem_recv_btn.setText(tr("serial.xfer_recv", proto=name))
        self.ymodem_recv_btn.setToolTip(tr("serial.xfer_recv_tip", proto=name))

    def _show_xfer_progress(self, on: bool) -> None:
        self.xfer_progress.setVisible(on)
        self.xfer_cancel_btn.setVisible(on)
        if not on:
            self.xfer_progress.setValue(0)
        self._xfer_cancel = False

    def _cancel_transfer(self) -> None:
        self._xfer_cancel = True

    def _on_xfer_progress(self, done: int, total: int) -> None:
        # Called from a worker thread — only touch Qt via queued invoke-safe path.
        def apply() -> None:
            if total > 0:
                self.xfer_progress.setMaximum(max(1, total))
                self.xfer_progress.setValue(min(done, total))
                self.xfer_progress.setFormat("%v / %m B")
            else:
                self.xfer_progress.setMaximum(0)  # busy indicator

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, apply)

    def _run_transfer(self, label: str, work) -> None:
        link = self._link
        link.begin_transfer()
        self._show_xfer_progress(True)
        self._set_send_enabled(False)
        self.ymodem_btn.setEnabled(False)
        self.ymodem_recv_btn.setEnabled(False)

        def on_ok(result) -> None:
            link.end_transfer()
            self._show_xfer_progress(False)
            self._set_send_enabled(True)
            if getattr(result, "ok", False):
                extra = getattr(result, "filename", "") or ""
                self.traffic.append_status(
                    tr(
                        "serial.ymodem_done",
                        n=result.bytes_sent,
                        p=result.packets,
                    )
                    + (f"  {extra}" if extra else "")
                )
                payload = getattr(result, "data", None)
                if payload:
                    self._save_received_file(extra or "ymodem.bin", bytes(payload))
            else:
                self.traffic.append_status(
                    tr("serial.ymodem_err", err=getattr(result, "message", "failed"))
                )

        def on_err(msg: str) -> None:
            link.end_transfer()
            self._show_xfer_progress(False)
            self._set_send_enabled(True)
            self.traffic.append_status(tr("serial.ymodem_err", err=msg))

        runner = getattr(self, "_runner", None)
        if runner is None:
            from etools.ui.runtime import OpRunner

            self._runner = OpRunner(self)
            self._runner.busy_changed.connect(lambda _busy: self.notify_state())
            runner = self._runner
        if not runner.start(work, on_ok, on_err):
            link.end_transfer()
            self._show_xfer_progress(False)
            self._set_send_enabled(True)
            self.traffic.append_status(tr("serial.ymodem_err", err=label))

    def _save_received_file(self, name: str, data: bytes) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, tr("serial.ymodem_save"), name)
        if not path:
            return
        try:
            Path(path).write_bytes(data)
        except OSError as exc:
            self.traffic.append_status(tr("serial.ymodem_err", err=str(exc)))
            return
        self.traffic.append_status(tr("serial.ymodem_saved", path=path, size=len(data)))

    def _on_ymodem_send(self) -> None:
        """YMODEM download to an IAP bootloader (runs in the background)."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        if not self._opened:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("serial.ymodem_send"), "", "Firmware (*.bin *.hex *.elf *.dat);;All (*.*)"
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            self.traffic.append_status(tr("serial.ymodem_err", err=str(exc)))
            return
        name = Path(path).name
        self.traffic.append_status(tr("serial.ymodem_start", name=name, size=len(data)))
        link = self._link
        mode = self._xfer_mode()
        xfer_cancel = lambda: self._xfer_cancel  # noqa: E731
        progress = self._on_xfer_progress

        def work():
            from etools.core.file_xfer import send_file

            proto = self.xfer_proto.currentData() or "ymodem"
            return send_file(
                link.write,
                link.transfer_read,
                name,
                data,
                protocol=proto,
                mode=mode,
                on_progress=progress,
                cancel=xfer_cancel,
            )

        self._run_transfer("start", work)

    def _on_ymodem_recv(self) -> None:
        """Receive a file pushed by a peer / bootloader (YMODEM or XMODEM)."""
        if not self._opened:
            return
        self.traffic.append_status(tr("serial.ymodem_recv_start"))
        link = self._link
        mode = self._xfer_mode()
        xfer_cancel = lambda: self._xfer_cancel  # noqa: E731
        progress = self._on_xfer_progress

        def work():
            from etools.core.file_xfer import receive_file

            proto = self.xfer_proto.currentData() or "ymodem"
            return receive_file(
                link.write,
                link.transfer_read,
                protocol=proto,
                mode=mode,
                timeout=90.0,
                on_progress=progress,
                cancel=xfer_cancel,
            )

        self._run_transfer("recv", work)
