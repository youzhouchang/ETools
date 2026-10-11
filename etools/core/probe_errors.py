"""Typed failures from a debug probe session."""

from __future__ import annotations


class ProbeError(Exception):
    """Base class for probe and flash failures."""


class ProbeDisconnected(ProbeError):
    """The probe is unplugged or the debug session is not open."""


class ProbePackMissing(ProbeError):
    """The target support pack or target name is not available."""


class ProbeOperationError(ProbeError):
    """Program, erase, read, verify, reset, or connect failed."""


class ProbeTargetAbsent(ProbeError):
    """The probe is attached to the host, but no target answered on SWD/JTAG."""


_ABSENT_MARKERS = (
    "get idcode",
    "idcode error",
    "stlink error (9)",
)
_DISCONNECT_MARKERS = (
    "not connected",
    "unplugged",
    "disconnect",
    "transfer failed",
    "no device",
    "device not found",
    "no matching probe",
)
_PACK_MARKERS = (
    "pack",
    "target not",
    "no target",
    "cmsis-pack",
    "unknown target",
)


def target_is_absent(exc: BaseException | None, message: str = "") -> bool:
    """True when the probe is present but the chip did not answer."""
    if isinstance(exc, ProbeTargetAbsent):
        return True
    text = f"{message} {exc or ''}".lower()
    return any(marker in text for marker in _ABSENT_MARKERS)


def classify_probe_error(exc: BaseException, message: str = "") -> ProbeError:
    """Wrap an arbitrary backend error as a probe failure the UI can branch on."""
    if isinstance(exc, ProbeError):
        return exc
    text = f"{message} {exc}".lower()
    detail = message or str(exc)
    if target_is_absent(exc, message):
        return ProbeTargetAbsent(detail)
    if any(marker in text for marker in _DISCONNECT_MARKERS):
        return ProbeDisconnected(detail)
    if any(marker in text for marker in _PACK_MARKERS):
        return ProbePackMissing(detail)
    return ProbeOperationError(detail)
