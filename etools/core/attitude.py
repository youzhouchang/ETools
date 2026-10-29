"""Euler-angle and quaternion math for the dashboard's 3D attitude widget.

Convention: aerospace ZYX intrinsic order (yaw about Z, then pitch about Y,
then roll about X), angles in degrees. This matches how most IMU/AHRS
firmware (e.g. Madgwick/Mahony filters) reports roll/pitch/yaw.
"""

from __future__ import annotations

import math

AttitudeMode = str  # "euler" or "quat"
ATTITUDE_MODES = ("euler", "quat")
Quat = tuple[float, float, float, float]


def euler_to_quat(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Quat:
    """Roll/pitch/yaw in degrees to a (w, x, y, z) quaternion."""
    roll = math.radians(roll_deg) * 0.5
    pitch = math.radians(pitch_deg) * 0.5
    yaw = math.radians(yaw_deg) * 0.5
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return qw, qx, qy, qz


def quat_to_euler(qw: float, qx: float, qy: float, qz: float) -> tuple[float, float, float]:
    """Quaternion back to roll/pitch/yaw in degrees. Clamps at the pitch gimbal lock."""
    roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    sin_pitch = max(-1.0, min(1.0, 2.0 * (qw * qy - qz * qx)))
    pitch = math.asin(sin_pitch)
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def normalize_quat(qw: float, qx: float, qy: float, qz: float) -> Quat | None:
    """Unit quaternion, or None for non-finite input or a near-zero magnitude."""
    values = (qw, qx, qy, qz)
    if not all(math.isfinite(v) for v in values):
        return None
    norm = math.sqrt(sum(v * v for v in values))
    if norm < 1e-9:
        return None
    return tuple(v / norm for v in values)  # type: ignore[return-value]


def attitude_quat(mode: AttitudeMode, values: list[float]) -> Quat | None:
    """Build a unit quaternion from a widget's resolved bind values.

    ``euler`` expects exactly 3 values (roll, pitch, yaw in degrees).
    ``quat`` expects exactly 4 values (w, x, y, z), any magnitude.
    """
    if mode == "quat":
        if len(values) != 4:
            return None
        return normalize_quat(*values)
    if len(values) != 3:
        return None
    if not all(math.isfinite(v) for v in values):
        return None
    return normalize_quat(*euler_to_quat(*values))
