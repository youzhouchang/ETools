"""Config & FlashService unit tests (no hardware)."""

from __future__ import annotations

from pathlib import Path

import etools.config as config_mod
from etools.config import AppConfig
from etools.core.models import OperationResult, ProbeInfo, ProbeType, TargetInfo
from etools.core.operations import FlashService
from etools.core.probe import ProbeDriver
from etools.core.models import TargetDetails


class DummyDriver(ProbeDriver):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def discover(self):
        self.calls.append("discover")
        return [ProbeInfo(probe_type=ProbeType.STLINK, unique_id="X1")]

    def connect(self, probe, target):
        self.calls.append("connect")
        self._set_state(type(self.state).CONNECTED)
        return OperationResult(ok=True, message="ok", data=TargetDetails(target_name="dummy"))

    def disconnect(self):
        self.calls.append("disconnect")
        self._set_state(type(self.state).DISCONNECTED)

    def erase(self, full_chip=True):
        self.calls.append(f"erase:{full_chip}")
        return OperationResult(ok=True, message="erased")

    def program(self, firmware_path, verify=True):
        self.calls.append(f"program:{verify}")
        return OperationResult(ok=True, message="programmed", bytes_processed=4)

    def read(self, address, size, out_path):
        self.calls.append("read")
        Path(out_path).write_bytes(b"\x00" * size)
        return OperationResult(ok=True, message="read", bytes_processed=size)

    def verify(self, firmware_path):
        self.calls.append("verify")
        return OperationResult(ok=True, message="verified")

    def reset(self, halt=False):
        self.calls.append(f"reset:{halt}")
        return OperationResult(ok=True, message="reset")

    def get_target_details(self):
        return TargetDetails(target_name="dummy", flash_size=0x10000)


class TestAppConfig:
    def test_defaults(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(config_mod, "_app_data_dir", lambda: tmp_path)
        cfg = AppConfig()
        assert cfg.default_target == "cortex_m"
        assert cfg.verify_after_program is True

    def test_save_load_roundtrip(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(config_mod, "_app_data_dir", lambda: tmp_path)
        cfg = AppConfig()
        cfg.last_firmware = "C:/fw/app.bin"
        cfg.default_target = "stm32f103rc"
        cfg.save()
        assert cfg.config_file.exists()
        loaded = AppConfig().load()
        assert loaded.last_firmware == "C:/fw/app.bin"
        assert loaded.default_target == "stm32f103rc"

    def test_load_missing(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(config_mod, "_app_data_dir", lambda: tmp_path)
        cfg = AppConfig().load()
        assert cfg.default_target == "cortex_m"


class TestFlashService:
    def test_scan(self):
        svc = FlashService(DummyDriver())
        probes = svc.scan_probes()
        assert len(probes) == 1
        assert probes[0].probe_type is ProbeType.STLINK

    def test_connect_disconnect(self):
        d = DummyDriver()
        svc = FlashService(d)
        r = svc.connect(
            ProbeInfo(probe_type=ProbeType.STLINK, unique_id="X1"),
            TargetInfo(),
        )
        assert r.ok
        assert svc.connected
        svc.disconnect()
        assert not svc.connected
        assert "disconnect" in d.calls

    def test_program_missing_file(self, tmp_path: Path):
        svc = FlashService(DummyDriver())
        r = svc.program_file(tmp_path / "missing.bin")
        assert not r.ok

    def test_program_ok(self, tmp_path: Path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        d = DummyDriver()
        svc = FlashService(d)
        r = svc.program_file(f, verify=True)
        assert r.ok
        assert "program:True" in d.calls

    def test_erase_all(self):
        d = DummyDriver()
        svc = FlashService(d)
        assert svc.erase_all().ok
        assert "erase:True" in d.calls
