"""Unit tests for core models."""

from __future__ import annotations

from pathlib import Path

import pytest

from etools.core.models import (
    FirmwareImage,
    OperationResult,
    ProbeInfo,
    ProbeType,
    ProgressInfo,
    ProgressStage,
    TargetDetails,
    format_size,
)


class TestFormatSize:
    def test_zero(self):
        assert format_size(0) == "—"

    def test_bytes(self):
        assert format_size(512) == "512 B"

    def test_kib(self):
        assert format_size(1024) == "1 KiB"
        assert format_size(64 * 1024) == "64 KiB"

    def test_mib(self):
        assert format_size(1024 * 1024) == "1 MiB"
        assert format_size(2 * 1024 * 1024) == "2 MiB"

    def test_non_aligned(self):
        assert format_size(1500) == "1500 B"


class TestProbeInfo:
    def test_display_with_serial(self):
        p = ProbeInfo(probe_type=ProbeType.STLINK, unique_id="ABC123", product_name="ST-Link V2")
        assert "STLINK" in p.display_name
        assert "ABC123" in p.display_name
        assert "ST-Link V2" in p.display_name

    def test_display_minimal(self):
        p = ProbeInfo(probe_type=ProbeType.CMSIS_DAP, unique_id="")
        assert "CMSISDAP" in p.display_name.upper()


class TestTargetDetails:
    def test_voltage_na(self):
        d = TargetDetails()
        assert d.voltage_display == "N/A"

    def test_voltage_ok(self):
        d = TargetDetails(voltage=3.3, voltage_ok=True)
        assert d.voltage_display == "3.30 V"

    def test_flash_display(self):
        d = TargetDetails(flash_size=512 * 1024)
        assert d.flash_size_display == "512 KiB"

    def test_summary(self):
        d = TargetDetails(
            target_name="stm32f103rc",
            flash_size=1024 * 1024,
            voltage=3.3,
            voltage_ok=True,
        )
        s = d.summary_line()
        assert "stm32f103rc" in s
        assert "Flash" in s
        assert "3.30 V" in s


class TestProgressInfo:
    def test_indeterminate(self):
        assert ProgressInfo(percent=-1).indeterminate
        assert not ProgressInfo(percent=50).indeterminate

    def test_format_bytes(self):
        assert ProgressInfo(bytes_done=10, bytes_total=100).format_bytes == "10/100 B"
        assert ProgressInfo().format_bytes == ""


class TestFirmwareImage:
    def test_missing(self, tmp_path: Path):
        img = FirmwareImage(path=tmp_path / "nope.bin")
        assert not img.exists
        assert img.size == 0

    def test_detect_format_and_size(self, tmp_path: Path):
        f = tmp_path / "app.hex"
        f.write_bytes(b":00000001FF\n")
        img = FirmwareImage(path=f)
        assert img.exists
        assert img.format == "hex"
        assert img.size > 0
        assert img.display_name == "app.hex"


class TestOperationResult:
    def test_defaults(self):
        r = OperationResult(ok=True)
        assert r.message == ""
        assert r.duration_s == 0.0
        assert r.data is None
