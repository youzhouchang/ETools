"""Tests for EDS parsing, PDO mapping helpers, and CAN trace I/O."""

from __future__ import annotations

from pathlib import Path

from etools.core.can_trace import TraceFrame, TraceWriter, read_trace
from etools.core.canopen import (
    comm_index_for_map,
    decode_pdo_mapping,
    encode_pdo_mapping,
    pdo_kind,
    pdo_number,
)
from etools.core.eds import parse_eds_text


def test_pdo_mapping_codec():
    raw = encode_pdo_mapping(0x6402, 1, 32)
    assert decode_pdo_mapping(raw) == (0x6402, 1, 32)
    assert pdo_kind(0x1A00) == "tpdo"
    assert pdo_kind(0x1600) == "rpdo"
    assert pdo_number(0x1A01) == 2
    assert comm_index_for_map(0x1A00) == 0x1800
    assert comm_index_for_map(0x1601) == 0x1401


def test_parse_eds_minimal():
    text = """
[FileInfo]
FileName=demo.eds
[DeviceInfo]
VendorName=Acme
ProductNumber=0x1234
ProductName=DemoDrive
[1000]
ParameterName=Device Type
DataType=0x0007
DefaultValue=0x00020192
[1A00]
ParameterName=TPDO1 mapping
[1A00sub0]
ParameterName=Number of mapped objects
DefaultValue=1
[1A00sub1]
ParameterName=mapped object
DefaultValue=0x64020120
[6402sub1]
ParameterName=Velocity actual
DataType=0x0007
AccessType=ro
"""
    eds = parse_eds_text(text)
    assert eds.vendor_name == "Acme"
    assert eds.product_name == "DemoDrive"
    assert eds.get(0x1000, None) is not None
    entry = eds.get(0x6402, 1)
    assert entry is not None and "Velocity" in entry.name
    maps = eds.pdo_mappings()
    assert 0x1A00 in maps
    assert maps[0x1A00][0] == (0x6402, 1, 32)
    labels = eds.mapping_labels()
    assert labels and labels[0][0] == 0x1A00
    assert labels[0][2][0][3] == "Velocity actual"


def test_trace_roundtrip(tmp_path: Path):
    path = tmp_path / "t.csv"
    w = TraceWriter(path)
    w.write(TraceFrame(0.0, "rx", 0x123, data=b"\x01\x02"))
    w.write(TraceFrame(0.05, "tx", 0x456, is_extended=True, data=b"\xFF"))
    w.close()
    frames = read_trace(path)
    assert len(frames) == 2
    assert frames[0].arbitration_id == 0x123
    assert frames[0].data == b"\x01\x02"
    assert frames[1].is_extended
    assert frames[1].data == b"\xff"
