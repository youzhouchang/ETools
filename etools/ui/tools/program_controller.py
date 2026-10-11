"""Flash session owned by the program tool, hosted by the main window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from etools.core.models import ProbeInfo, ProgressInfo, ProgressStage, TargetInfo
from etools.i18n import tr
from etools.logger import get_logger

log = get_logger("ui.program")


class ProgramController:
    """Probe scan, connect, and flash operations for the Program tool.

    The main window keeps thin wrappers so existing call sites and tests
    still reach these methods. Widget state stays on the window.
    """

    def __init__(self, host) -> None:
        self.host = host

    def _toolbar_open_firmware(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from etools.core.models import FIRMWARE_EXTENSIONS

        path, _ = QFileDialog.getOpenFileName(self.host, tr("act.open"), "", FIRMWARE_EXTENSIONS)
        if not path:
            return
        self.host.flash_panel.fw_edit.setText(path)
        self.host.flash_panel.remember_firmware(path)
        self.host.hex_preview.load_file(path)
        self.host._goto_tab("Hex")
        self._log(tr("log.firmware_opened", name=Path(path).name))

    def _toolbar_program(self) -> None:
        path = self.host.flash_panel.firmware_path()
        if not path:
            self._toolbar_open_firmware()
            path = self.host.flash_panel.firmware_path()
            if not path:
                return
        self._start_program(path, self.host.flash_panel.verify_check.isChecked())

    def _toolbar_erase(self) -> None:
        ret = QMessageBox.warning(
            self.host,
            tr("confirm.erase_all_title"),
            tr("confirm.erase_all_text"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ret == QMessageBox.StandardButton.Ok:
            self._start_erase()

    def _toolbar_verify(self) -> None:
        path = self.host.flash_panel.firmware_path()
        if path:
            self._start_verify(path)

    def _toolbar_reset(self) -> None:
        self._start_reset()

    def _toolbar_read_chip(self) -> None:
        self.host._goto_tab("Hex")
        addr = int(self.host.hex_preview.addr_spin.value())
        size = self.host.hex_preview._read_size_bytes()
        self._start_read_chip(addr, size)

    def _wire(self) -> None:
        self.host.probe_panel.connect_requested.connect(self._start_connect)
        self.host.probe_panel.disconnect_requested.connect(self._do_disconnect)

        self.host.flash_panel.program_requested.connect(self._start_program)
        self.host.flash_panel.erase_requested.connect(self._start_erase)
        self.host.flash_panel.erase_range_requested.connect(self._start_erase_range)
        self.host.flash_panel.read_requested.connect(self._start_read)
        self.host.flash_panel.verify_requested.connect(self._start_verify)
        self.host.flash_panel.reset_requested.connect(self._start_reset)

        self.host.target_info_panel.refresh_btn.clicked.connect(self._start_refresh_info)

        self.host.hex_preview.read_chip_requested.connect(self._start_read_chip)
        self.host.hex_preview.fill_requested.connect(self._start_fill_ram)
        self.host.flash_panel.fw_edit.textChanged.connect(self._on_firmware_path_changed)
        self.host.device_manager.catalog_changed.connect(self._on_catalog_changed)

    def _hotplug_tick(self) -> None:
        if self.host._runner.busy:
            return
        self.host._start_scan(silent=True)

    def _on_progress_info(self, info: ProgressInfo) -> None:
        text = info.message or info.stage.value
        extra = info.format_bytes
        if extra:
            text = f"{text}  ({extra})"
        if info.stage != ProgressStage.IDLE or info.is_error:
            self._log(text, info.is_error)

        flash_stages = (
            ProgressStage.PROGRAM,
            ProgressStage.ERASE,
            ProgressStage.READ,
            ProgressStage.VERIFY,
            ProgressStage.CONNECT,
        )
        if info.stage == ProgressStage.DONE:
            self._show_progress(100, text)
        elif info.is_error or info.stage == ProgressStage.ERROR:
            self._hide_progress()
        elif info.stage in flash_stages:
            if info.indeterminate:
                self.host.progress.setRange(0, 0)
                self.host.progress_label.setText(text)
                self.host.progress_label.show()
                self.host.progress.show()
            else:
                self._show_progress(info.percent, text)

    def _show_progress(self, percent: int, label: str = "") -> None:
        self.host.progress.setRange(0, 100)
        self.host.progress.setValue(max(0, min(100, percent)))
        self.host.progress.show()
        if label:
            self.host.progress_label.setText(label)
            self.host.progress_label.show()
        else:
            self.host.progress_label.hide()

    def _hide_progress(self) -> None:
        self.host.progress.setRange(0, 100)
        self.host.progress.setValue(0)
        self.host.progress_label.hide()
        self.host.progress.show()

    def _log(self, message: str, is_error: bool = False) -> None:
        self.host.log_panel.append(message, is_error)
        if is_error:
            log.error(message)
        else:
            log.info(message)

    def _set_status(self, text: str, kind: str = "warn") -> None:
        obj = {"ok": "statusOk", "err": "statusErr", "warn": "statusWarn"}.get(kind, "statusWarn")
        self.host.conn_badge.setText(text)
        self.host.conn_badge.setObjectName(obj)
        st = self.host.conn_badge.style()
        st.unpolish(self.host.conn_badge)
        st.polish(self.host.conn_badge)

    def _run_async(self, fn, on_ok, on_err=None, *, quiet_busy: bool = False) -> bool:
        if self.host.workflow_active:
            return False

        def ok(result) -> None:
            self._set_busy(False)
            on_ok(result)

        def err(msg: str) -> None:
            self._set_busy(False)
            if not quiet_busy:
                self._log(msg, True)
            self._hide_progress()
            if on_err:
                on_err(msg)

        if not self.host._runner.start(fn, ok, err):
            return False
        if not quiet_busy:
            self._set_busy(True)
        return True

    def _set_busy(self, busy: bool) -> None:
        self.host.flash_panel.set_busy(busy)
        for key, action in getattr(self.host, "_flash_menu_actions", {}).items():
            action.setEnabled(getattr(self.host.flash_panel, key + "_btn").isEnabled())

    def _start_scan(self, silent: bool = False) -> None:
        if self.host._runner.busy:
            return
        if not silent:
            self._log(tr("log.scan_probes"))
            self.host.probe_panel.set_scanning_hint(True)

        def on_ok(probes) -> None:
            probes = probes or []
            ids = tuple(p.unique_id for p in probes)
            if ids != self.host._last_probe_ids:
                self.host._last_probe_ids = ids
                if probes:
                    self._log(tr("log.probe_list", n=len(probes)))
                else:
                    if not silent:
                        self._log(tr("log.probe_none"), True)
            self.host.probe_panel.set_probes(probes)

        def on_err(msg: str) -> None:
            self.host.probe_panel.set_probes([])
            if not silent:
                self._log(tr("log.probe_scan_err", err=msg), True)

        self._run_async(self.host.service.scan_probes, on_ok, on_err, quiet_busy=silent)

    def _start_connect(self, probe: ProbeInfo, target: TargetInfo) -> None:
        self._log(
            tr(
                "log.connecting",
                probe=probe.display_name,
                target=target.target_override,
            )
        )
        self.host.probe_panel.set_connecting()
        self._set_status(tr("status.probe_connecting"), "warn")
        self._show_progress(0, tr("status.probe_connecting"))

        def on_ok(result) -> None:
            if result.ok:
                self.host.probe_panel.set_connected(True, result.detail or result.message)
                self.host.flash_panel.set_ops_enabled(True)
                self.host.hex_preview.set_chip_read_enabled(True)
                self.host.rtt_panel.set_connected(True)
                self.host.swo_panel.set_connected(True)
                self.host.variable_monitor.set_connected(True)
                details_for_flash = getattr(result, "data", None)
                if details_for_flash is not None and getattr(details_for_flash, "flash_size", 0):
                    self.host.hex_preview._flash_size_hint = int(details_for_flash.flash_size)
                else:
                    self.host.hex_preview._flash_size_hint = 0
                self._set_status(tr("log.connected", target=target.target_override), "ok")
                self._log(result.message)
                details = getattr(result, "data", None)
                if details is not None:
                    self.host.target_info_panel.apply(details)
                else:
                    self._start_refresh_info()
                self._auto_preview_chip(details)
            else:
                self.host.probe_panel.set_error(result.message)
                self.host.flash_panel.set_ops_enabled(False)
                self.host.hex_preview.set_chip_read_enabled(False)
                self.host.target_info_panel.clear()
                self._set_status(tr("status.failed"), "err")
                self._log(result.message, True)
                self._hide_progress()

        def on_err(msg: str) -> None:
            self.host.probe_panel.set_error(msg)
            self.host.flash_panel.set_ops_enabled(False)
            self.host.hex_preview.set_chip_read_enabled(False)
            self.host.target_info_panel.clear()
            self._set_status(tr("status.failed"), "err")

        self._run_async(lambda: self.host.service.connect(probe, target), on_ok, on_err)

    def _auto_preview_chip(self, details: object | None) -> None:
        addr = 0x0800_0000
        size = 0x1000
        if details is not None:
            base = int(getattr(details, "flash_base", 0) or 0)
            flash_size = int(getattr(details, "flash_size", 0) or 0)
            if base:
                addr = base
            if flash_size:
                size = min(0x1000, flash_size)
        try:
            self.host.hex_preview.addr_spin.setValue(addr)
            self.host.hex_preview.size_spin.setValue(size)
        except Exception:
            log.debug("sync hex spins failed", exc_info=True)
        self._log(tr("log.hex_loading", addr=f"{addr:08X}", size=f"{size:,}"))
        self._start_read_chip(addr, size)

    def _do_disconnect(self) -> None:
        try:
            self.host.service.disconnect()
        except Exception as exc:
            self._log(tr("log.disconnect_err", err=str(exc)), True)
        self.host.probe_panel.set_connected(False)
        self.host.flash_panel.set_ops_enabled(False)
        self.host.hex_preview.set_chip_read_enabled(False)
        self.host.rtt_panel.set_connected(False)
        self.host.swo_panel.set_connected(False)
        self.host.variable_monitor.set_connected(False)
        self.host.target_info_panel.clear()
        self._set_status(tr("status.disconnected"), "warn")
        self._hide_progress()
        self._log(tr("log.disconnected"))

    def _on_catalog_changed(self) -> None:
        self.host.probe_panel.reload_targets()
        self._log(tr("log.devices_updated"))

    def _on_firmware_path_changed(self, path: str) -> None:
        path = path.strip()
        if not path or not Path(path).is_file():
            return
        try:
            self.host.hex_preview.load_file(path)
            if Path(path).suffix.lower() in {".elf", ".axf", ".alf"}:
                self.host.variable_monitor.load_path(path)
            self._log(tr("log.hex_loaded", name=Path(path).name))
        except Exception:
            log.exception("hex preview load")

    def _start_read_chip(self, addr: int, size: int) -> None:
        self._show_progress(0, tr("log.chip_read", addr=f"0x{addr:08X}"))

        def work():
            data = self.host.service.read_memory_bytes(addr, size)
            return addr, data

        def on_ok(result) -> None:
            a, data = result
            self.host.hex_preview.load_bytes(a, data, source=None)
            self._show_progress(100, tr("log.chip_read_done", size=f"{len(data):,}"))

        def on_err(msg: str) -> None:
            self._log(msg, True)
            self._hide_progress()

        self._run_async(work, on_ok, on_err)

    def _start_program(self, path: str, verify: bool = True) -> None:
        self._show_progress(0, tr("log.programming"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            if result.ok:
                self._show_progress(100, result.message or "OK")
            else:
                self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        if not self._run_async(
            lambda: self.host.service.program_file(path, verify=verify), on_ok, on_err
        ):
            self._log(tr("log.busy"), True)

    def _start_erase(self) -> None:
        self._show_progress(0, tr("log.erasing"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(self.host.service.erase_all, on_ok, on_err)

    def _start_erase_range(self, address: int, size: int) -> None:
        self._show_progress(0, tr("log.erasing_range"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(lambda: self.host.service.erase_range(address, size), on_ok, on_err)

    def _start_read(self, address: int, size: int, out_path: str) -> None:
        self._show_progress(0, tr("log.reading"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(
            lambda: self.host.service.read_flash(address, size, out_path), on_ok, on_err
        )

    def _start_verify(self, path: str) -> None:
        self._show_progress(0, tr("log.verifying"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(lambda: self.host.service.verify_file(path), on_ok, on_err)

    def _start_reset(self) -> None:
        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)

        self._run_async(lambda: self.host.service.reset_target(halt=False), on_ok, on_err)

    def _start_refresh_info(self) -> None:
        def on_ok(details) -> None:
            self.host.target_info_panel.apply(details)

        def on_err(msg: str) -> None:
            self._log(msg, True)

        self._run_async(self.host.service.target_details, on_ok, on_err, quiet_busy=True)

    def _start_fill_ram(self, addr: int, size: int, value: int) -> None:
        self._show_progress(0, tr("log.filling"))

        def on_ok(result) -> None:
            self._set_busy(False)
            self._log(result.message, not result.ok)
            self._hide_progress()

        def on_err(msg: str) -> None:
            self._set_busy(False)
            self._log(msg, True)
            self._hide_progress()

        self._run_async(lambda: self.host.service.fill_memory(addr, size, value), on_ok, on_err)

