"""Core package — probe backends and flash operations."""

from etools.core.models import (
    CONNECT_MODES,
    FIRMWARE_EXTENSIONS,
    RESET_TYPES,
    WIRE_PROTOCOLS,
    ConnectionState,
    FirmwareImage,
    OperationKind,
    OperationResult,
    ProbeInfo,
    ProbeType,
    ProgressInfo,
    ProgressStage,
    TargetDetails,
    TargetInfo,
    format_size,
)
from etools.core.operations import FlashService
from etools.core.probe import ProbeDriver
from etools.core.pyocd_driver import PyOCDDriver
from etools.core.targets import CURATED_TARGETS, KNOWN_TARGETS, list_target_choices

__all__ = [
    "CONNECT_MODES",
    "CURATED_TARGETS",
    "FIRMWARE_EXTENSIONS",
    "KNOWN_TARGETS",
    "RESET_TYPES",
    "WIRE_PROTOCOLS",
    "ConnectionState",
    "FirmwareImage",
    "OperationKind",
    "OperationResult",
    "ProbeInfo",
    "ProbeType",
    "ProgressInfo",
    "ProgressStage",
    "TargetDetails",
    "TargetInfo",
    "format_size",
    "list_target_choices",
    "PyOCDDriver",
    "FlashService",
    "ProbeDriver",
]
