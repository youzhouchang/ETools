"""Flash tools tab: option bytes, production, image tools, UART bootloader, FLM box."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from etools.core import option_bytes as obm
from etools.core.models import OperationResult
from etools.core.option_bytes import OptionBytes
from etools.core.production import SERIAL_FORMATS
from etools.i18n_catalog import flashtools
from tests.fake_stm32_boot import FakeStm32Bootloader
from tests.test_option_bytes import H7Sim
from tests.test_production import FakeService

ROOT = Path(__file__).resolve().parents[1]
_UI_FILES = [
    "etools/ui/widgets/option_bytes_panel.py",
    "etools/ui/widgets/production_panel.py",
    "etools/ui/widgets/image_tools_panel.py",
    "etools/ui/widgets/uart_boot_panel.py",
    "etools/ui/widgets/ext_flash_box.py",
    "etools/ui/widgets/flash_tools_panel.py",
    "etools/ui/widgets/flash_panel.py",
]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class SyncHost:
    """Runs jobs inline so the panels can be driven without threads."""

    def __init__(self, service) -> None:
        self.service = service
        self.connected = True
        self.logs: list[tuple[str, bool]] = []
        self.firmware = ""
        self.used: list[str] = []
        self.refreshed = 0
        self.disconnected = 0

    def run_job(self, fn, on_ok, on_err=None) -> bool:
        try:
            result = fn()
        except Exception as exc:
            if on_err:
                on_err(str(exc))
            return True
        on_ok(result)
        return True

    def log(self, message: str, is_error: bool = False) -> None:
        self.logs.append((message, is_error))

    def progress(self, percent: int, label: str = "") -> None:
        pass

    def firmware_path(self) -> str:
        return self.firmware

    def use_firmware(self, path: str) -> None:
        self.used.append(path)

    def refresh_target(self) -> None:
        self.refreshed += 1

    def mark_disconnected(self) -> None:
        self.disconnected += 1


class ObService:
    def __init__(self) -> None:
        self.sim = H7Sim()

    def read_option_bytes(self):
        return OptionBytes.detect(self.sim).snapshot()

    def write_option_bytes(self, values, allow_level2=False):
        outcome = OptionBytes.detect(self.sim).write(values, allow_level2=allow_level2)
        return OperationResult(ok=True, message="Option bytes written", data=outcome)


@pytest.fixture
def no_confirm(monkeypatch):
    calls: list[str] = []

    def fake(parent, title, text, *, danger=False):
        calls.append(text)
        return True

    for mod in ("option_bytes_panel", "production_panel", "uart_boot_panel"):
        monkeypatch.setattr(f"etools.ui.widgets.{mod}.confirm", fake)
    return calls


def test_catalog_keys_match_between_languages() -> None:
    assert set(flashtools.ZH) == set(flashtools.EN)


def test_literal_tr_keys_exist() -> None:
    keys = set(flashtools.ZH)
    from etools.i18n import _STRINGS

    known = set(_STRINGS["zh"])
    for rel in _UI_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for key in re.findall(r"""tr\(\s*["']([a-z_.0-9]+)["']""", text):
            assert key in known, f"{rel}: {key}"
    dynamic = (
        [f"ob.reload.{r}" for r in ("none", "reset", "obl")]
        + [f"ob.reload_note.{r}" for r in ("none", "reset", "obl")]
        + [f"prod.fmt.{f}" for f in SERIAL_FORMATS]
        + [f"prod.step.{s}" for s in ("uid", "prepare", "program", "protect", "run")]
        + [f"uboot.line.{x}" for x in ("none", "dtr", "rts")]
        + [f"uboot.stage.{x}" for x in ("erase", "write", "verify", "read")]
        + [f"uboot.{x}" for x in ("rdp", "rup", "wup")]
    )
    for key in dynamic:
        assert key in keys, key


def test_every_option_field_and_choice_is_translated() -> None:
    from etools.ui.widgets.option_bytes_panel import field_desc_key

    for fam in obm.FAMILIES:
        for f in fam.fields:
            assert field_desc_key(f.key) in flashtools.ZH, (fam.name, f.key)
            for _value, label in f.choices:
                if label.startswith("ob."):
                    assert label in flashtools.ZH, label


def test_option_bytes_panel_read_edit_write(qapp, no_confirm) -> None:
    from etools.ui.widgets.option_bytes_panel import OptionBytesPanel

    svc = ObService()
    host = SyncHost(svc)
    panel = OptionBytesPanel()
    panel.bind(host)
    panel.set_connected(True)
    panel.read()
    assert panel.table.rowCount() == len(obm.H7.fields)
    assert panel.pending_values() == {}
    assert panel.protect_btn.isEnabled() and not panel.unprotect_btn.isEnabled()

    row = [f.key for f in obm.H7.fields].index("BOR_LEV")
    combo = panel.table.cellWidget(row, 2)
    combo.setCurrentIndex(combo.findData(2))
    assert panel.pending_values() == {"BOR_LEV": 2}
    panel._write_clicked()
    assert (svc.sim.regs[H7Sim.B + 0x1C] >> 2) & 3 == 2
    assert panel.pending_values() == {}
    assert len(no_confirm) == 1

    panel._factory_clicked()
    assert panel.pending_values() == {"BOR_LEV": 0}
    panel.close()


def test_option_bytes_panel_rdp_buttons(qapp, no_confirm) -> None:
    from etools.ui.widgets.option_bytes_panel import OptionBytesPanel

    svc = ObService()
    panel = OptionBytesPanel()
    panel.bind(SyncHost(svc))
    panel.set_connected(True)
    panel.read()
    panel._rdp_clicked(1)
    assert panel._snap.rdp_level == 1
    assert panel.unprotect_btn.isEnabled()
    panel._rdp_clicked(0)
    assert svc.sim.mass_erased
    # Unprotect asks twice (changes + mass erase).
    assert len(no_confirm) == 3
    panel.set_connected(False)
    assert panel.table.rowCount() == 0
    panel.close()


def test_production_panel_run_increments_serial(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etools.ui.widgets.production_panel.save_tool_prefs", lambda *a: None)
    monkeypatch.setattr("etools.ui.widgets.production_panel.load_tool_prefs", lambda *a: {})
    from etools.ui.widgets.production_panel import ProductionPanel

    fw = tmp_path / "app.bin"
    fw.write_bytes(b"\x00" * 64)
    svc = FakeService()
    panel = ProductionPanel()
    panel.bind(SyncHost(svc))
    panel.set_connected(True)
    panel.fw_edit.setText(str(fw))
    panel.sn_box.setChecked(True)
    panel.sn_addr.setText("0x08000010")
    panel.sn_next.setValue(41)
    panel.log_edit.setText(str(tmp_path / "log.csv"))
    panel.start()
    assert panel.result_label.text() == "PASS"
    assert svc.read(0x0800_0010, 4) == (41).to_bytes(4, "little")
    assert panel.sn_next.value() == 42
    assert "1" in panel.stats_label.text()
    assert (tmp_path / "log.csv").is_file()
    svc.fail_program = True
    panel.start()
    assert panel.result_label.text() == "FAIL"
    assert panel.sn_next.value() == 42
    panel.close()


def test_production_panel_requires_firmware(qapp, monkeypatch) -> None:
    monkeypatch.setattr("etools.ui.widgets.production_panel.load_tool_prefs", lambda *a: {})
    from etools.ui.widgets.production_panel import ProductionPanel

    panel = ProductionPanel()
    host = SyncHost(FakeService())
    panel.bind(host)
    panel.set_connected(True)
    panel.fw_edit.setText("/no/such/file.hex")
    panel.start()
    assert panel.result_label.text() == "FAIL"
    assert host.logs and host.logs[-1][1]
    panel.close()


def test_image_tools_merge_edit_save(qapp, tmp_path, monkeypatch) -> None:
    from etools.core.fw_image import SparseImage
    from etools.ui.widgets.image_tools_panel import ImageToolsPanel

    a = tmp_path / "boot.hex"
    b = tmp_path / "app.hex"
    SparseImage([(0x0800_0000, b"\x01" * 16)]).save(a)
    SparseImage([(0x0800_0100, b"\x02" * 16)]).save(b)
    host = SyncHost(None)
    panel = ImageToolsPanel()
    panel.bind(host)
    assert panel.add_file(str(a)) and panel.add_file(str(b))
    assert panel.table.rowCount() == 2
    panel.range_start.setText("0x08000000")
    panel.range_end.setText("0x08000110")
    panel.fill_value.setText("0xFF")
    panel._range_op("fill")
    assert panel.table.rowCount() == 1
    panel.undo()
    assert panel.table.rowCount() == 2
    panel.patch_addr.setText("0x08000004")
    panel.patch_bytes.setText("DE AD BE EF")
    panel._patch()
    assert panel.image.read(0x0800_0004, 4) == b"\xde\xad\xbe\xef"
    out = tmp_path / "merged.hex"
    monkeypatch.setattr(
        "etools.ui.widgets.image_tools_panel.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), "Intel HEX (*.hex)"),
    )
    panel._save(use=True)
    assert out.is_file()
    assert host.used == [str(out)]
    assert SparseImage.from_file(out).segments() == panel.image.segments()
    panel.close()


def test_image_tools_conflict_cancel(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from etools.core.fw_image import SparseImage
    from etools.ui.widgets.image_tools_panel import ImageToolsPanel

    a = tmp_path / "a.hex"
    b = tmp_path / "b.hex"
    SparseImage([(0x100, b"\x01\x02")]).save(a)
    SparseImage([(0x101, b"\x09")]).save(b)
    monkeypatch.setattr(
        "etools.ui.widgets.image_tools_panel.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    panel = ImageToolsPanel()
    assert panel.add_file(str(a))
    assert not panel.add_file(str(b))
    assert panel.image.read(0x100, 2) == b"\x01\x02"
    panel.close()


def test_uart_boot_panel_programs_fake_chip(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etools.ui.widgets.uart_boot_panel.save_tool_prefs", lambda *a: None)
    monkeypatch.setattr("etools.ui.widgets.uart_boot_panel.load_tool_prefs", lambda *a: {})
    from etools.ui.widgets.uart_boot_panel import UartBootPanel

    fake = FakeStm32Bootloader(pid=0x450)
    opened: list[tuple[str, int]] = []

    def factory(port: str, baud: int):
        opened.append((port, baud))
        return fake

    fw = tmp_path / "app.bin"
    fw.write_bytes(bytes(range(256)) * 2)
    host = SyncHost(None)
    panel = UartBootPanel(port_factory=factory)
    panel.bind(host)
    panel.port_combo.setEditText("/dev/ttyFAKE")
    panel.fw_edit.setText(str(fw))
    panel.boot_line.setCurrentIndex(panel.boot_line.findData("none"))
    panel.program()
    assert opened and opened[-1][0] == "/dev/ttyFAKE"
    assert bytes(fake.mem[:512]) == bytes(range(256)) * 2
    assert fake.go_address == 0x0800_0000
    assert "0x450" in panel.info_label.text()
    panel.probe()
    assert any("Bootloader" in m or "PID" in m for m, _ in host.logs)
    panel.close()


def test_uart_boot_panel_reports_failure(qapp, monkeypatch) -> None:
    monkeypatch.setattr("etools.ui.widgets.uart_boot_panel.save_tool_prefs", lambda *a: None)
    monkeypatch.setattr("etools.ui.widgets.uart_boot_panel.load_tool_prefs", lambda *a: {})
    from etools.ui.widgets.uart_boot_panel import UartBootPanel

    def factory(port: str, baud: int):
        raise OSError("port busy")

    panel = UartBootPanel(port_factory=factory)
    panel.bind(SyncHost(None))
    panel.port_combo.setEditText("/dev/ttyFAKE")
    panel.probe()
    assert "port busy" in panel.info_label.text()
    panel.close()


def test_ext_flash_box_reports_bad_flm(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etools.ui.widgets.ext_flash_box.save_config", lambda: None)
    from etools.core.ext_flash import inspect_flm
    from etools.ui.widgets.ext_flash_box import ExtFlashBox

    class Svc:
        driver = None

        def set_external_flm(self, path):
            return inspect_flm(path) if path else None

    box = ExtFlashBox()
    box.bind(SyncHost(Svc()))
    bad = tmp_path / "x.FLM"
    bad.write_bytes(b"junk")
    box.path_edit.setText(str(bad))
    box.apply()
    assert "Invalid FLM" in box.info.text()
    box.remove()
    assert box.path_edit.text() == ""
    box.close()


def test_program_page_has_tools_tab(qapp) -> None:
    from etools.ui.tools.program_page import ProgramPage

    page = ProgramPage()
    page.goto_tab("production")
    assert page.main_tabs.currentWidget().objectName() == "tabTools"
    assert page.flash_tools.tabs.currentWidget() is page.flash_tools.production
    page.goto_tab("uart_boot")
    assert page.flash_tools.tabs.currentWidget() is page.flash_tools.uart_boot
    page.set_connected(True)
    assert page.flash_tools.option_bytes.read_btn.isEnabled()
    page.set_connected(False)
    assert not page.flash_tools.option_bytes.read_btn.isEnabled()
    assert page.flash_panel.incremental_check.text()
    page.close()
