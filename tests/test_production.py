"""Production flow, serial numbers, UID injection and CSV log."""

from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

from etools.core.fw_image import SparseImage
from etools.core.models import OperationResult
from etools.core.production import (
    ProductionError,
    ProductionPlan,
    ProductionRunner,
    SerialSpec,
    UidSpec,
    build_image,
)

UID = bytes(range(1, 13))


class FakeService:
    def __init__(self, *, fail_program: bool = False, uid: bytes = UID) -> None:
        self.flash: dict[int, int] = {}
        self.calls: list[str] = []
        self.fail_program = fail_program
        self.uid = uid
        self.rdp = 0
        self.erase = ""

    def read_uid(self) -> bytes:
        self.calls.append("uid")
        return self.uid

    def program_segments(self, segments, *, verify, erase, incremental, label):
        self.calls.append("program")
        self.erase = erase
        if self.fail_program:
            return OperationResult(ok=False, message="Verify failed: mismatch")
        for addr, data in segments:
            for i, b in enumerate(data):
                self.flash[addr + i] = b
        return OperationResult(ok=True, message=f"Programmed {label}")

    def read_option_bytes(self):
        return SimpleNamespace(rdp_level=self.rdp, family=SimpleNamespace(rdp_l1=0xBB))

    def write_option_bytes(self, values):
        self.calls.append(f"ob:{values['RDP']:#x}")
        self.rdp = 1
        return OperationResult(ok=True, message="Option bytes written")

    def reset_target(self, halt=False):
        self.calls.append("run")
        return OperationResult(ok=True, message="Target reset")

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.flash.get(addr + i, 0xFF) for i in range(n))


def _image() -> SparseImage:
    return SparseImage([(0x0800_0000, b"\x00" * 64)])


@pytest.mark.parametrize(
    ("fmt", "number", "expected"),
    [
        ("u32le", 0x01020304, b"\x04\x03\x02\x01"),
        ("u32be", 0x01020304, b"\x01\x02\x03\x04"),
        ("u16le", 0x1234, b"\x34\x12"),
        ("u64le", 1, b"\x01" + b"\x00" * 7),
        ("ascii_dec", 42, b"SN000042"),
        ("ascii_hex", 0xAB, b"SN0000AB"),
        ("bcd", 1234, b"\x00\x00\x12\x34"),
    ],
)
def test_serial_formats(fmt: str, number: int, expected: bytes) -> None:
    spec = SerialSpec(enabled=True, fmt=fmt, width=6 if fmt.startswith("ascii") else 8)
    if fmt.startswith("ascii"):
        spec.prefix = "SN"
    assert spec.render(number) == expected


def test_serial_overflow_is_rejected() -> None:
    with pytest.raises(ProductionError):
        SerialSpec(fmt="ascii_dec", width=2).render(123)
    with pytest.raises(OverflowError):
        SerialSpec(fmt="u16le").render(0x10000)


def test_build_image_patches_serial_and_uid() -> None:
    plan = ProductionPlan(
        serial=SerialSpec(enabled=True, address=0x0800_0010, fmt="u32le"),
        uid=UidSpec(enabled=True, address=0x0800_0020),
    )
    base = _image()
    image = build_image(base, plan, 7, UID)
    assert image.read(0x0800_0010, 4) == b"\x07\x00\x00\x00"
    assert image.read(0x0800_0020, 12) == UID
    assert base.read(0x0800_0010, 4) == b"\x00" * 4  # original untouched


def test_overlapping_serial_and_uid_rejected() -> None:
    plan = ProductionPlan(
        serial=SerialSpec(enabled=True, address=0x0800_0010),
        uid=UidSpec(enabled=True, address=0x0800_0012),
    )
    with pytest.raises(ProductionError):
        ProductionRunner(FakeService(), plan, _image())


def test_full_flow_with_protect_and_csv(tmp_path) -> None:
    log_path = tmp_path / "logs" / "prod.csv"
    plan = ProductionPlan(
        firmware="app.hex",
        erase="chip",
        protect=True,
        serial=SerialSpec(enabled=True, address=0x0800_0030, fmt="ascii_dec", width=4),
        uid=UidSpec(enabled=True, address=0x0800_0010),
        log_path=str(log_path),
    )
    svc = FakeService()
    runner = ProductionRunner(svc, plan, _image())
    first = runner.run(5)
    second = runner.run(6)
    assert first.ok and second.ok
    assert svc.erase == "chip"
    assert svc.read(0x0800_0030, 4) == b"0006"
    assert svc.read(0x0800_0010, 12) == UID
    assert svc.calls[:5] == ["uid", "program", "ob:0xbb", "run", "uid"]
    assert "ob:0xbb" not in svc.calls[5:]  # already protected the second time
    assert [s.name for s in first.steps] == ["uid", "prepare", "program", "protect", "run"]
    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert [r["serial"] for r in rows] == ["0005", "0006"]
    assert rows[0]["result"] == "PASS"
    assert rows[0]["uid"] == UID.hex().upper()


def test_failure_stops_flow_and_logs(tmp_path) -> None:
    log_path = tmp_path / "prod.csv"
    plan = ProductionPlan(firmware="app.bin", log_path=str(log_path))
    svc = FakeService(fail_program=True)
    result = ProductionRunner(svc, plan, _image()).run()
    assert not result.ok
    assert "mismatch" in result.error
    assert "run" not in svc.calls
    assert result.steps[-1].name == "program" and not result.steps[-1].ok
    rows = list(csv.DictReader(log_path.open(encoding="utf-8")))
    assert rows[0]["result"] == "FAIL"


def test_uid_required_but_missing() -> None:
    plan = ProductionPlan(uid=UidSpec(enabled=True, address=0x0800_0000))
    result = ProductionRunner(FakeService(uid=b""), plan, _image()).run()
    assert not result.ok and "UID" in result.error


def test_cancel_before_first_step() -> None:
    result = ProductionRunner(FakeService(), ProductionPlan(), _image()).run(cancelled=lambda: True)
    assert not result.ok and result.error == "Cancelled"


def test_plan_dict_roundtrip_ignores_unknown_keys() -> None:
    plan = ProductionPlan(firmware="x.hex", serial=SerialSpec(enabled=True, start=100))
    data = plan.to_dict()
    data["bogus"] = 1
    data["serial"]["bogus"] = 2
    again = ProductionPlan.from_dict(data)
    assert again == plan
