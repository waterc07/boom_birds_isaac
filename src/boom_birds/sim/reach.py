"""Minimal obstacle-free reach/stop task and deterministic outcome rules.

V2.2 12.2/20.2: collision beats success, timeout is truncated and never a
success, and invalid states carry an explicit reason. Truth here is ORACLE
simulator state; it is not a deployable observation.
"""
import math
from dataclasses import dataclass

OUTCOME_RUNNING = 'RUNNING'
OUTCOME_SUCCESS = 'SUCCESS'
OUTCOME_COLLISION = 'COLLISION'
OUTCOME_TIMEOUT = 'TIMEOUT'
OUTCOME_INVALID = 'INVALID'

TERMINAL_OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_COLLISION, OUTCOME_TIMEOUT, OUTCOME_INVALID)


def _finite(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


@dataclass(frozen=True)
class ReachSpec:
    """PROPOSED task thresholds; not frozen acceptance criteria."""
    goal_position_world_m: tuple = (1.5, 1.0, 0.75)
    success_distance_m: float = 0.3
    success_speed_mps: float = 0.2
    hold_time_s: float = 0.5
    timeout_s: float = 20.0
    collision_height_m: float = 0.1
    max_abs_position_m: float = 5.0

    def __post_init__(self):
        if len(tuple(self.goal_position_world_m)) != 3:
            raise ValueError('goal_position_world_m must have three components')
        for value in self.goal_position_world_m:
            _finite(value, 'goal_position_world_m component')
        for name in ('success_distance_m', 'success_speed_mps', 'hold_time_s',
                     'timeout_s', 'collision_height_m', 'max_abs_position_m'):
            value = getattr(self, name)
            _finite(value, name)
            if value <= 0:
                raise ValueError(name + ' must be positive')


@dataclass(frozen=True)
class ReachDecision:
    terminated: bool
    truncated: bool
    outcome: str
    reason: str
    distance_m: float
    speed_mps: float
    hold_time_s: float


class ReachEvaluator:
    """Deterministic step outcome; same inputs always give the same verdict."""

    def __init__(self, spec, dt_s):
        if not isinstance(spec, ReachSpec):
            raise ValueError('spec must be ReachSpec')
        _finite(dt_s, 'dt_s')
        if dt_s <= 0:
            raise ValueError('dt_s must be positive')
        self.spec = spec
        self.dt_s = dt_s
        self.required_hold_steps = max(1, int(math.ceil(spec.hold_time_s / dt_s - 1e-9)))
        self.hold_steps = 0

    def reset(self):
        self.hold_steps = 0

    def update(self, *, position_world_m, speed_mps, now_s, collision=False):
        try:
            for index, value in enumerate(position_world_m):
                _finite(value, 'position_world_m[' + str(index) + ']')
            _finite(speed_mps, 'speed_mps')
            _finite(now_s, 'now_s')
        except (TypeError, ValueError):
            return ReachDecision(True, False, OUTCOME_INVALID, 'NONFINITE',
                                 0.0, 0.0, self.hold_steps * self.dt_s)
        goal = self.spec.goal_position_world_m
        distance = math.sqrt(sum((position_world_m[index] - goal[index]) ** 2
                                 for index in range(3)))
        if (any(abs(position_world_m[index]) > self.spec.max_abs_position_m
                for index in range(3))
                or position_world_m[2] < -1.0):
            return ReachDecision(True, False, OUTCOME_INVALID, 'OUT_OF_BOUNDS',
                                 distance, speed_mps,
                                 self.hold_steps * self.dt_s)
        if collision or position_world_m[2] <= self.spec.collision_height_m:
            return ReachDecision(True, False, OUTCOME_COLLISION, 'COLLISION',
                                 distance, speed_mps,
                                 self.hold_steps * self.dt_s)
        if distance <= self.spec.success_distance_m and speed_mps <= self.spec.success_speed_mps:
            self.hold_steps += 1
            if self.hold_steps >= self.required_hold_steps:
                return ReachDecision(True, False, OUTCOME_SUCCESS, 'HOLD_SATISFIED',
                                     distance, speed_mps,
                                     self.hold_steps * self.dt_s)
        else:
            self.hold_steps = 0
        if now_s >= self.spec.timeout_s:
            return ReachDecision(True, True, OUTCOME_TIMEOUT, 'TIMEOUT',
                                 distance, speed_mps,
                                 self.hold_steps * self.dt_s)
        return ReachDecision(False, False, OUTCOME_RUNNING, 'RUNNING',
                             distance, speed_mps, self.hold_steps * self.dt_s)


@dataclass(frozen=True)
class GuidanceSpec:
    """PROPOSED proportional guidance limits for the classical baseline."""
    max_horizontal_mps: float = 0.6
    max_vertical_mps: float = 0.3
    gain_per_m: float = 1.0
    arrival_radius_m: float = 0.25
    max_yaw_rate_radps: float = 0.0

    def __post_init__(self):
        for name in ('max_horizontal_mps', 'max_vertical_mps', 'gain_per_m',
                     'arrival_radius_m', 'max_yaw_rate_radps'):
            _finite(getattr(self, name), name)


def _quat_to_matrix(quat_wxyz):
    w, x, y, z = quat_wxyz
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-9:
        raise ValueError('quaternion norm is zero')
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def guidance_command(*, position_world_m, quat_wxyz, goal_position_world_m, spec):
    """ORACLE-state proportional guidance; returns (forward, left, up, yaw_rate)."""
    if not isinstance(spec, GuidanceSpec):
        raise ValueError('spec must be GuidanceSpec')
    for index in range(3):
        _finite(position_world_m[index], 'position_world_m[' + str(index) + ']')
        _finite(goal_position_world_m[index], 'goal_position_world_m[' + str(index) + ']')
    error_world = tuple(goal_position_world_m[index] - position_world_m[index]
                        for index in range(3))
    distance = math.sqrt(sum(value * value for value in error_world))
    if distance <= spec.arrival_radius_m:
        return (0.0, 0.0, 0.0, 0.0)
    matrix = _quat_to_matrix(quat_wxyz)
    yaw = math.atan2(matrix[1][0], matrix[0][0])
    c, s = math.cos(yaw), math.sin(yaw)
    forward = c * error_world[0] + s * error_world[1]
    left = -s * error_world[0] + c * error_world[1]
    forward *= spec.gain_per_m
    left *= spec.gain_per_m
    horizontal = math.hypot(forward, left)
    if horizontal > spec.max_horizontal_mps:
        scale = spec.max_horizontal_mps / horizontal
        forward *= scale
        left *= scale
    up = max(-spec.max_vertical_mps,
             min(spec.max_vertical_mps, error_world[2] * spec.gain_per_m))
    # No yaw-rate command in the first obstacle-free baseline: headings are
    # held by the controller; explicit yaw alignment stays a later work package.
    yaw_rate = 0.0
    return (forward, left, up, yaw_rate)
