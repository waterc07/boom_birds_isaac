"""Traditional reach guidance baselines sharing one observation/action contract.

Both methods consume the same ORACLE position/velocity/attitude observation and
emit the same four-dimensional velocity command. ORACLE names the observation
permission, not the algorithm.
"""
import math
from dataclasses import dataclass

from .reach import GuidanceSpec, guidance_command

PROPORTIONAL = 'proportional'
BRAKING = 'braking'
METHODS = (PROPORTIONAL, BRAKING)


def _finite(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


def _positive(value, name):
    _finite(value, name)
    if value <= 0:
        raise ValueError(name + ' must be positive')


def _triple(values, name):
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain three numbers')
    if len(result) != 3 or any(not math.isfinite(value) for value in result):
        raise ValueError(name + ' must contain three finite values')
    return result


def _yaw_from_quat(quat_wxyz):
    try:
        w, x, y, z = (float(value) for value in quat_wxyz)
    except (TypeError, ValueError):
        raise ValueError('quat_wxyz must contain four numbers')
    if not all(math.isfinite(value) for value in (w, x, y, z)):
        raise ValueError('quat_wxyz must be finite')
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-9:
        raise ValueError('quaternion norm is zero')
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


@dataclass(frozen=True)
class BrakingGuidanceSpec:
    """PROPOSED braking-profile parameters, not frozen aircraft limits."""
    max_horizontal_mps: float = 0.6
    max_vertical_mps: float = 0.3
    deceleration_mps2: float = 0.8
    velocity_feedback_gain: float = 0.8
    arrival_radius_m: float = 0.25

    def __post_init__(self):
        _positive(self.max_horizontal_mps, 'max_horizontal_mps')
        _positive(self.max_vertical_mps, 'max_vertical_mps')
        _positive(self.deceleration_mps2, 'deceleration_mps2')
        _finite(self.velocity_feedback_gain, 'velocity_feedback_gain')
        if self.velocity_feedback_gain < 0:
            raise ValueError('velocity_feedback_gain must be nonnegative')
        _finite(self.arrival_radius_m, 'arrival_radius_m')
        if self.arrival_radius_m < 0:
            raise ValueError('arrival_radius_m must be nonnegative')


def _braking_command(goal, spec, position, velocity, quat):
    error = tuple(goal[index] - position[index] for index in range(3))
    distance = math.sqrt(sum(value * value for value in error))
    if distance <= spec.arrival_radius_m:
        return (0.0, 0.0, 0.0, 0.0)
    yaw = _yaw_from_quat(quat)
    c, s = math.cos(yaw), math.sin(yaw)
    horizontal_error = (error[0], error[1])
    horizontal_distance = math.hypot(*horizontal_error)
    if horizontal_distance <= spec.arrival_radius_m:
        forward = left = 0.0
    else:
        unit = (horizontal_error[0] / horizontal_distance,
                horizontal_error[1] / horizontal_distance)
        desired_speed = min(spec.max_horizontal_mps,
                            math.sqrt(2.0 * spec.deceleration_mps2 * horizontal_distance))
        desired = (unit[0] * desired_speed, unit[1] * desired_speed)
        gain = spec.velocity_feedback_gain
        command = (desired[0] + gain * (desired[0] - velocity[0]),
                   desired[1] + gain * (desired[1] - velocity[1]))
        forward = c * command[0] + s * command[1]
        left = -s * command[0] + c * command[1]
    vertical_error = error[2]
    if abs(vertical_error) <= spec.arrival_radius_m:
        up = 0.0
    else:
        desired_up = math.copysign(
            min(spec.max_vertical_mps,
                math.sqrt(2.0 * spec.deceleration_mps2 * abs(vertical_error))),
            vertical_error)
        up = desired_up + spec.velocity_feedback_gain * (desired_up - velocity[2])
    horizontal_norm = math.hypot(forward, left)
    if horizontal_norm > spec.max_horizontal_mps:
        scale = spec.max_horizontal_mps / horizontal_norm
        forward *= scale
        left *= scale
    up = max(-spec.max_vertical_mps, min(spec.max_vertical_mps, up))
    return (forward, left, up, 0.0)


@dataclass(frozen=True)
class TraditionalGuidance:
    name: str
    goal_position_world_m: tuple
    proportional_spec: GuidanceSpec | None = None
    braking_spec: BrakingGuidanceSpec | None = None

    def command(self, *, position_world_m, velocity_world_mps, quat_wxyz):
        position = _triple(position_world_m, 'position_world_m')
        velocity = _triple(velocity_world_mps, 'velocity_world_mps')
        if self.name == PROPORTIONAL:
            return guidance_command(position_world_m=position, quat_wxyz=quat_wxyz,
                                    goal_position_world_m=self.goal_position_world_m,
                                    spec=self.proportional_spec)
        if self.name == BRAKING:
            return _braking_command(self.goal_position_world_m, self.braking_spec,
                                    position, velocity, quat_wxyz)
        raise ValueError('unknown guidance method: ' + str(self.name))


def make_guidance(name, goal_position_world_m, *, proportional_spec=None,
                  braking_spec=None):
    if name not in METHODS:
        raise ValueError('unknown guidance method: ' + str(name))
    goal = _triple(goal_position_world_m, 'goal_position_world_m')
    if name == PROPORTIONAL:
        spec = proportional_spec if proportional_spec is not None else GuidanceSpec()
        if not isinstance(spec, GuidanceSpec):
            raise ValueError('proportional_spec must be a GuidanceSpec')
        return TraditionalGuidance(name=name, goal_position_world_m=goal,
                                   proportional_spec=spec)
    spec = braking_spec if braking_spec is not None else BrakingGuidanceSpec()
    if not isinstance(spec, BrakingGuidanceSpec):
        raise ValueError('braking_spec must be a BrakingGuidanceSpec')
    return TraditionalGuidance(name=name, goal_position_world_m=goal,
                               braking_spec=spec)
