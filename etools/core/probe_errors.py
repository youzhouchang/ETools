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


def classify_probe_error(exc: BaseException, message: str = "") -> ProbeError:
    """Wrap an arbitrary backend error as a probe failure the UI can branch on."""
    if isinstance(exc, ProbeError):
        return exc
    text = f"{message} {exc}".lower()
    detail = message or str(exc)
    if any(marker in text for marker in _DISCONNECT_MARKERS):
        return ProbeDisconnected(detail)
    if any(marker in text for marker in _PACK_MARKERS):
        return ProbePackMissing(detail)
    return ProbeOperationError(detail)
