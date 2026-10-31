"""Velocity outer-loop contract tests (no Isaac, no GPU)."""
import math

import pytest

from boom_birds.contracts import reasons
from boom_birds.sim.velocity_control import (
    ControlOutput,
    KinematicVelocitySource,
    VehicleParams,
    VehicleState,
    VelocityExecutor,
    VelocityGains,
    VelocitySetpoint,
    heading_from_matrix,
    quat_to_matrix,
)

MASS = 0.0282
INERTIA = (1.4e-5, 1.4e-5, 2.1e-5)


def params(**overrides):
    values = dict(mass_kg=MASS, inertia_kgm2=INERTIA)
    values.update(overrides)
    return VehicleParams(**values)


def quat_from_yaw(yaw):
    return (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))


def state(yaw=0.0, velocity=(0.0, 0.0, 0.0), angular=(0.0, 0.0, 0.0)):
    return VehicleState(
        position_world_m=(0.0, 0.0, 0.75),
        velocity_world_mps=velocity,
        quat_wxyz=quat_from_yaw(yaw),
        angular_velocity_body_radps=angular,
    )


def setpoint(**overrides):
    values = dict(vx_forward_mps=0.0, vy_left_mps=0.0, vz_up_mps=0.0,
                  yaw_rate_ccw_world_radps=0.0, issued_at_s=0.0,
                  expires_at_s=1.0, control_epoch=0)
    values.update(overrides)
    return VelocitySetpoint(**values)


def test_zero_command_holds_hover_thrust():
    executor = VelocityExecutor(params())
    out = executor.step(setpoint(), state(), 0.10)
    assert out.reason == reasons.ACCEPT
    assert out.thrust_body_n == pytest.approx(MASS * 9.81)
    assert out.desired_velocity_world_mps == pytest.approx((0.0, 0.0, 0.0))
    assert out.to_actuator_action(params())[0] == pytest.approx(2.0 / 1.9 - 1.0)


@pytest.mark.parametrize('yaw,command,expected', [
    (0.0, (0.5, 0.0), (0.5, 0.0)),
    (math.pi / 2, (0.5, 0.0), (0.0, 0.5)),
    (0.0, (0.0, 0.4), (0.0, 0.4)),
    (-math.pi / 2, (0.5, 0.0), (0.0, -0.5)),
    (math.pi / 2, (0.3, 0.2), (-0.2, 0.3)),
])
def test_forward_and_left_map_to_world_with_heading(yaw, command, expected):
    executor = VelocityExecutor(params())
    out = executor.step(setpoint(vx_forward_mps=command[0], vy_left_mps=command[1], yaw_rate_ccw_world_radps=0.0),
                        state(yaw=yaw), 0.10)
    assert out.yaw_rad == pytest.approx(yaw, abs=1e-9)
    assert out.desired_velocity_world_mps[:2] == pytest.approx(expected, abs=1e-9)


def test_forward_command_tilts_thrust_forward():
    out = VelocityExecutor(params()).step(setpoint(vx_forward_mps=0.5), state(), 0.10)
    assert out.desired_thrust_world_n[0] > 0
    assert out.desired_thrust_world_n[2] == pytest.approx(MASS * 9.81)
    assert out.thrust_body_n > MASS * 9.81


def test_vertical_command_changes_collective_thrust():
    up = VelocityExecutor(params()).step(setpoint(vz_up_mps=0.3), state(), 0.10)
    down = VelocityExecutor(params()).step(setpoint(vz_up_mps=-0.3), state(), 0.10)
    assert up.thrust_body_n > MASS * 9.81
    assert down.thrust_body_n < MASS * 9.81
    assert up.desired_velocity_world_mps[2] == pytest.approx(0.3)


def test_positive_yaw_rate_commands_positive_world_up_torque():
    out = VelocityExecutor(params()).step(setpoint(yaw_rate_ccw_world_radps=0.5), state(), 0.10)
    assert out.torque_body_nm[2] > 0
    assert out.yaw_ref_rad > 0


def test_tilt_and_torque_limits_are_enforced():
    aggressive = VelocityExecutor(params())
    out = aggressive.step(setpoint(vx_forward_mps=5.0), state(), 0.10)
    tilt = math.atan2(out.desired_thrust_world_n[0], out.desired_thrust_world_n[2])
    assert tilt <= params().max_tilt_rad + 1e-9
    assert abs(out.desired_thrust_world_n[1]) < 1e-12
    out_fast_spin = aggressive.step(setpoint(yaw_rate_ccw_world_radps=0.5),
                                    state(angular=(0.0, 0.0, -100.0)), 0.15)
    assert all(abs(value) <= params().moment_scale_nm + 1e-12
               for value in out_fast_spin.torque_body_nm)
    action = out_fast_spin.to_actuator_action(params())
    assert all(-1.0 <= value <= 1.0 for value in action)


def test_expiry_and_epoch_mismatch_are_rejected_without_renewal():
    executor = VelocityExecutor(params())
    expired = executor.step(setpoint(expires_at_s=0.5), state(), 0.5)
    assert expired.reason == reasons.ACTION_EXPIRED and expired.degraded
    assert expired.desired_velocity_world_mps == pytest.approx((0.0, 0.0, 0.0))
    assert executor.rejections[reasons.ACTION_EXPIRED] == 1
    early = executor.step(setpoint(issued_at_s=1.0, expires_at_s=2.0), state(), 0.5)
    assert early.reason == reasons.REJECT_NOT_YET_VALID
    other_epoch = executor.step(setpoint(control_epoch=3), state(), 0.5)
    assert other_epoch.reason == reasons.REJECT_CONTROL_EPOCH
    missing = executor.step(None, state(), 0.5)
    assert missing.reason == reasons.REJECT_NO_CACHED_ACTION


def test_reset_clears_integrals_and_reference_heading():
    executor = VelocityExecutor(params())
    for index in range(20):
        executor.step(setpoint(vx_forward_mps=0.5, yaw_rate_ccw_world_radps=0.2),
                      state(yaw=math.pi / 2), 0.05 * index)
    executor.reset(state(yaw=math.pi / 2))
    out = executor.step(setpoint(vx_forward_mps=0.0), state(yaw=math.pi / 2), 1.0)
    assert out.thrust_body_n == pytest.approx(MASS * 9.81)
    assert out.yaw_ref_rad == pytest.approx(math.pi / 2)
    assert abs(out.torque_body_nm[2]) < 1e-6


@pytest.mark.parametrize('kwargs', [
    {'vx_forward_mps': math.nan}, {'vy_left_mps': math.inf},
    {'vz_up_mps': -math.inf}, {'expires_at_s': 0.0}, {'control_epoch': -1},
])
def test_invalid_setpoints_are_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        setpoint(**kwargs)


@pytest.mark.parametrize('kwargs', [
    {'mass_kg': 0.0}, {'mass_kg': math.nan},
    {'inertia_kgm2': (1e-5, -1e-5, 1e-5)}, {'gravity_mps2': -9.81},
    {'max_tilt_rad': 1.7}, {'thrust_to_weight': 0.0},
])
def test_invalid_plant_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        params(**kwargs)


def test_zero_quaternion_and_bad_state_are_rejected():
    with pytest.raises(ValueError):
        quat_to_matrix((0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        VehicleState((0, 0, 0), (0, 0, 0), (0, 0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError):
        VelocityGains(k_rate=-1)


def test_heading_extraction_and_kinematic_label():
    assert heading_from_matrix(quat_to_matrix(quat_from_yaw(0.0))) == pytest.approx(0.0)
    assert heading_from_matrix(quat_to_matrix(quat_from_yaw(math.pi / 2))) == pytest.approx(math.pi / 2)
    source = KinematicVelocitySource()
    result = source.step(setpoint(vx_forward_mps=1.0), state(), 0.1)
    assert result['label'] == 'KINEMATIC'
    assert result['reason'] == reasons.ACCEPT
    assert ControlOutput.__dataclass_fields__['degraded']
