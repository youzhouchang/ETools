from __future__ import annotations

from etools.release_notes import extract_section

SAMPLE = """# Changelog

## [Unreleased]

### Added

- nothing yet

---

## [0.1.2] - 2026-09-14

### Added

- feature A

### Fixed

- bug B

---

## [0.1.1] - 2026-09-13

### Changed

- layout
"""


def test_extract_section_with_date():
    section = extract_section(SAMPLE, "0.1.2")
    assert "feature A" in section
    assert "bug B" in section
    assert "0.1.1" not in section
    assert "nothing yet" not in section
    assert not section.rstrip().endswith("---")


def test_extract_section_missing_version():
    assert extract_section(SAMPLE, "9.9.9") == ""


def test_extract_section_unreleased():
    section = extract_section(SAMPLE, "Unreleased")
    assert "nothing yet" in section
