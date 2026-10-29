"""Euler/quaternion math behind the dashboard's 3D attitude widget."""

from __future__ import annotations

import math

from etools.core.attitude import (
    attitude_quat,
    euler_to_quat,
    normalize_quat,
    quat_to_euler,
)


def test_identity_euler_is_identity_quat():
    assert euler_to_quat(0.0, 0.0, 0.0) == (1.0, 0.0, 0.0, 0.0)


def test_euler_quat_roundtrip_away_from_gimbal_lock():
    for roll, pitch, yaw in ((15.0, 20.0, 30.0), (-40.0, 10.0, -170.0), (5.0, -60.0, 90.0)):
        quat = euler_to_quat(roll, pitch, yaw)
        back_roll, back_pitch, back_yaw = quat_to_euler(*quat)
        assert abs(back_roll - roll) < 1e-6
        assert abs(back_pitch - pitch) < 1e-6
        assert abs(back_yaw - yaw) < 1e-6


def test_normalize_quat_scales_to_unit_length():
    result = normalize_quat(2.0, 0.0, 0.0, 0.0)
    assert result is not None
    assert math.isclose(sum(v * v for v in result), 1.0, abs_tol=1e-9)
    assert result == (1.0, 0.0, 0.0, 0.0)


def test_normalize_quat_rejects_non_finite_and_zero():
    assert normalize_quat(math.nan, 0.0, 0.0, 0.0) is None
    assert normalize_quat(math.inf, 0.0, 0.0, 0.0) is None
    assert normalize_quat(0.0, 0.0, 0.0, 0.0) is None


def test_attitude_quat_euler_mode_needs_exactly_three_values():
    quat = attitude_quat("euler", [10.0, 0.0, 0.0])
    assert quat is not None
    assert attitude_quat("euler", [10.0, 0.0]) is None
    assert attitude_quat("euler", [10.0, 0.0, 0.0, 0.0]) is None
    assert attitude_quat("euler", [math.nan, 0.0, 0.0]) is None


def test_attitude_quat_quat_mode_needs_exactly_four_values_and_normalizes():
    quat = attitude_quat("quat", [2.0, 0.0, 0.0, 0.0])
    assert quat == (1.0, 0.0, 0.0, 0.0)
    assert attitude_quat("quat", [1.0, 0.0, 0.0]) is None
    assert attitude_quat("quat", [0.0, 0.0, 0.0, 0.0]) is None


def test_attitude_quat_unknown_mode_falls_back_to_euler_rule():
    # attitude_quat treats anything that is not literally "quat" as Euler input.
    assert attitude_quat("bogus", [1.0, 0.0, 0.0]) is not None
    assert attitude_quat("bogus", [1.0, 0.0, 0.0, 0.0]) is None
