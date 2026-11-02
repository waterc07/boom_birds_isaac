"""V2.2 10.4 / 26.3: velocity outer loop producing body thrust and body torque.

Pure standard-library math: no Isaac, Torch or MAVLink import. The simulator
adapter turns ControlOutput into the installed asset's (thrust, body torque)
action and executes it in PhysX. This is a simulation model, not a PX4
controller and not evidence of flight capability.
"""
import math
from dataclasses import dataclass

from boom_birds.contracts import reasons

ACCEPT = reasons.ACCEPT
EPSILON = 1e-9


def _finite(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


def _positive(value, name):
    _finite(value, name)
    if value <= 0:
        raise ValueError(name + ' must be positive')


def _vector(values, size, name):
    try:
        converted = tuple(float(v) for v in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be numeric')
    if len(converted) != size or any(not math.isfinite(v) for v in converted):
        raise ValueError(name + ' must contain ' + str(size) + ' finite values')
    return converted


@dataclass(frozen=True)
class VehicleParams:
    """Identified/documented plant parameters; not a flight envelope."""
    mass_kg: float
    inertia_kgm2: tuple
    gravity_mps2: float = 9.81
    thrust_to_weight: float = 1.9
    moment_scale_nm: float = 0.01
    max_tilt_rad: float = 0.2

    def __post_init__(self):
        _positive(self.mass_kg, 'mass_kg')
        inertia = _vector(self.inertia_kgm2, 3, 'inertia_kgm2')
        if any(value <= 0 for value in inertia):
            raise ValueError('inertia_kgm2 entries must be positive')
        _positive(self.gravity_mps2, 'gravity_mps2')
        _positive(self.thrust_to_weight, 'thrust_to_weight')
        _positive(self.moment_scale_nm, 'moment_scale_nm')
        _finite(self.max_tilt_rad, 'max_tilt_rad')
        if not 0 < self.max_tilt_rad < math.pi / 2:
            raise ValueError('max_tilt_rad must be in (0, pi/2)')

    @property
    def weight_n(self):
        return self.mass_kg * self.gravity_mps2

    @property
    def hover_thrust_n(self):
        return self.weight_n

    @property
    def max_thrust_n(self):
        return self.thrust_to_weight * self.weight_n


@dataclass(frozen=True)
class VelocityGains:
    kp_velocity_xy: float = 2.0
    ki_velocity_xy: float = 0.5
    kp_velocity_z: float = 3.0
    ki_velocity_z: float = 1.0
    k_attitude: float = 8.0
    k_yaw: float = 2.0
    k_rate: float = 30.0
    integral_limit: float = 0.5

    def __post_init__(self):
        for name in ('kp_velocity_xy', 'ki_velocity_xy', 'kp_velocity_z',
                     'ki_velocity_z', 'k_attitude', 'k_yaw', 'k_rate'):
            _finite(getattr(self, name), name)
            if getattr(self, name) < 0:
                raise ValueError(name + ' must be nonnegative')
        _positive(self.integral_limit, 'integral_limit')


@dataclass(frozen=True)
class VelocitySetpoint:
    """Normalized contract command already mapped to physical units.

    The trailing provenance fields are optional so existing positional
    construction keeps working; the delayed arrival gate reads them to verify
    the six-tuple context epochs, sync generation and action identity at
    arrival. ``check()`` semantics are unchanged (no renewal).
    """
    vx_forward_mps: float
    vy_left_mps: float
    vz_up_mps: float
    yaw_rate_ccw_world_radps: float
    issued_at_s: float
    expires_at_s: float
    control_epoch: int
    action_id: str = ''
    sync_generation: int = -1
    epochs: tuple | None = None

    def __post_init__(self):
        for name in ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
                     'yaw_rate_ccw_world_radps', 'issued_at_s', 'expires_at_s'):
            _finite(getattr(self, name), name)
        if self.expires_at_s <= self.issued_at_s:
            raise ValueError('expires_at_s must be later than issued_at_s')
        if not isinstance(self.control_epoch, int) or isinstance(self.control_epoch, bool) \
                or self.control_epoch < 0:
            raise ValueError('control_epoch must be a nonnegative integer')

    def check(self, now_s, control_epoch):
        if self.control_epoch != control_epoch:
            return reasons.REJECT_CONTROL_EPOCH
        if now_s < self.issued_at_s:
            return reasons.REJECT_NOT_YET_VALID
        if now_s >= self.expires_at_s:
            return reasons.ACTION_EXPIRED
        return reasons.ACCEPT


@dataclass(frozen=True)
class VehicleState:
    position_world_m: tuple
    velocity_world_mps: tuple
    quat_wxyz: tuple
    angular_velocity_body_radps: tuple

    def __post_init__(self):
        _vector(self.position_world_m, 3, 'position_world_m')
        _vector(self.velocity_world_mps, 3, 'velocity_world_mps')
        quat = _vector(self.quat_wxyz, 4, 'quat_wxyz')
        if math.sqrt(sum(value * value for value in quat)) < EPSILON:
            raise ValueError('quat_wxyz norm is zero')
        _vector(self.angular_velocity_body_radps, 3, 'angular_velocity_body_radps')


@dataclass(frozen=True)
class ControlOutput:
    thrust_body_n: float
    torque_body_nm: tuple
    desired_velocity_world_mps: tuple
    desired_thrust_world_n: tuple
    yaw_rad: float
    yaw_ref_rad: float
    reason: str
    degraded: bool

    def to_actuator_action(self, params):
        """Installed asset action: normalized total thrust plus body moments."""
        normalized_thrust = 2.0 * self.thrust_body_n / params.max_thrust_n - 1.0
        normalized_thrust = max(-1.0, min(1.0, normalized_thrust))
        moments = tuple(max(-1.0, min(1.0, value / params.moment_scale_nm))
                        for value in self.torque_body_nm)
        return (normalized_thrust,) + moments


def _normalize_quat(quat):
    norm = math.sqrt(sum(value * value for value in quat))
    if norm < EPSILON:
        raise ValueError('quaternion norm is zero')
    return tuple(value / norm for value in quat)


def quat_to_matrix(quat_wxyz):
    """Body-to-world rotation matrix as row tuples."""
    w, x, y, z = _normalize_quat(_vector(quat_wxyz, 4, 'quat_wxyz'))
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def matrix_vector(matrix, vector):
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3))
                 for row in range(3))


def matrix_transpose_vector(matrix, vector):
    return tuple(sum(matrix[row][col] * vector[row] for row in range(3))
                 for col in range(3))


def heading_from_matrix(matrix):
    forward = (matrix[0][0], matrix[1][0], matrix[2][0])
    return math.atan2(forward[1], forward[0])


def wrap_angle(angle):
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def _cross(left, right):
    return (left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0])


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _norm(vector):
    return math.sqrt(_dot(vector, vector))


class VelocityExecutor:
    """Cascaded velocity -> acceleration -> attitude/rate -> body wrench loop."""

    def __init__(self, params, gains=None, *, dt_s=0.05, control_epoch=0):
        if not isinstance(params, VehicleParams):
            raise ValueError('params must be VehicleParams')
        self.params = params
        self.gains = gains if gains is not None else VelocityGains()
        if not isinstance(self.gains, VelocityGains):
            raise ValueError('gains must be VelocityGains')
        _positive(dt_s, 'dt_s')
        self.dt_s = dt_s
        self.control_epoch = control_epoch
        self._integral_xy = [0.0, 0.0]
        self._integral_z = 0.0
        self._yaw_ref = None
        self._last_state = None
        self.rejections = {}

    def reset(self, state=None):
        self._integral_xy = [0.0, 0.0]
        self._integral_z = 0.0
        if state is not None:
            matrix = quat_to_matrix(state.quat_wxyz)
            self._yaw_ref = heading_from_matrix(matrix)
        else:
            self._yaw_ref = None

    def _note_rejection(self, reason):
        self.rejections[reason] = self.rejections.get(reason, 0) + 1

    def step(self, setpoint, state, now_s):
        if not isinstance(state, VehicleState):
            raise ValueError('state must be a VehicleState')
        _finite(now_s, 'now_s')
        reason = reasons.ACCEPT
        degraded = False
        if setpoint is None:
            reason = reasons.REJECT_NO_CACHED_ACTION
        elif not isinstance(setpoint, VelocitySetpoint):
            raise ValueError('setpoint must be a VelocitySetpoint or None')
        else:
            reason = setpoint.check(now_s, self.control_epoch)
        if reason == reasons.ACTION_EXPIRED:
            degraded = True
        elif reason != reasons.ACCEPT:
            degraded = True
        if degraded:
            self._note_rejection(reason)
            self._integral_xy = [0.0, 0.0]
            self._integral_z = 0.0
            setpoint = None

        matrix = quat_to_matrix(state.quat_wxyz)
        yaw = heading_from_matrix(matrix)
        if self._yaw_ref is None:
            self._yaw_ref = yaw
        body_z = (matrix[0][2], matrix[1][2], matrix[2][2])

        if setpoint is None:
            command_forward, command_left = 0.0, 0.0
            command_up, yaw_rate = 0.0, 0.0
        else:
            command_forward = setpoint.vx_forward_mps
            command_left = setpoint.vy_left_mps
            command_up = setpoint.vz_up_mps
            yaw_rate = setpoint.yaw_rate_ccw_world_radps
            self._yaw_ref += yaw_rate * self.dt_s

        c, s = math.cos(yaw), math.sin(yaw)
        desired_velocity = (
            c * command_forward - s * command_left,
            s * command_forward + c * command_left,
            command_up,
        )
        error = tuple(desired_velocity[index] - state.velocity_world_mps[index]
                      for index in range(3))
        self._integral_xy[0] += error[0] * self.dt_s
        self._integral_xy[1] += error[1] * self.dt_s
        self._integral_z += error[2] * self.dt_s
        limit = self.gains.integral_limit
        self._integral_xy = [max(-limit, min(limit, value)) for value in self._integral_xy]
        self._integral_z = max(-limit, min(limit, self._integral_z))

        accel_xy = [
            self.gains.kp_velocity_xy * error[index]
            + self.gains.ki_velocity_xy * self._integral_xy[index]
            for index in range(2)
        ]
        horizontal_limit = self.params.gravity_mps2 * math.tan(self.params.max_tilt_rad)
        horizontal_norm = math.hypot(accel_xy[0], accel_xy[1])
        if horizontal_norm > horizontal_limit:
            scale = horizontal_limit / horizontal_norm
            accel_xy = [value * scale for value in accel_xy]
        accel_z = (self.gains.kp_velocity_z * error[2]
                   + self.gains.ki_velocity_z * self._integral_z)

        force = (
            self.params.mass_kg * accel_xy[0],
            self.params.mass_kg * accel_xy[1],
            self.params.mass_kg * (accel_z + self.params.gravity_mps2),
        )
        force_norm = _norm(force)
        if force_norm < EPSILON:
            force = (0.0, 0.0, self.params.hover_thrust_n)
            force_norm = self.params.hover_thrust_n
        desired_z = tuple(value / force_norm for value in force)
        thrust = min(self.params.max_thrust_n,
                     max(0.0, force_norm))

        cross = _cross(body_z, desired_z)
        sin_angle = _norm(cross)
        cos_angle = max(-1.0, min(1.0, _dot(body_z, desired_z)))
        if sin_angle < 1e-6:
            axis_body = (0.0, 0.0, 0.0)
            angle = 0.0
        else:
            axis_world = tuple(value / sin_angle for value in cross)
            axis_body = matrix_transpose_vector(matrix, axis_world)
            angle = math.atan2(sin_angle, cos_angle)
        yaw_error = wrap_angle(self._yaw_ref - yaw)
        desired_rate = [
            self.gains.k_attitude * angle * axis_body[index] for index in range(3)
        ]
        desired_rate[2] += self.gains.k_yaw * yaw_error + yaw_rate
        torque = tuple(
            self.params.inertia_kgm2[index]
            * self.gains.k_rate
            * (desired_rate[index] - state.angular_velocity_body_radps[index])
            for index in range(3)
        )
        torque = tuple(max(-self.params.moment_scale_nm,
                           min(self.params.moment_scale_nm, value)) for value in torque)
        return ControlOutput(
            thrust_body_n=thrust, torque_body_nm=torque,
            desired_velocity_world_mps=desired_velocity,
            desired_thrust_world_n=force, yaw_rad=yaw,
            yaw_ref_rad=self._yaw_ref, reason=reason, degraded=degraded)


class KinematicVelocitySource:
    """Direct velocity assignment for REFERENCE ONLY; labeled KINEMATIC."""

    label = 'KINEMATIC'

    def __init__(self):
        self.accepted = 0

    def step(self, setpoint, state, now_s):
        reason = reasons.ACCEPT if setpoint is not None else reasons.REJECT_NO_CACHED_ACTION
        if reason == reasons.ACCEPT:
            self.accepted += 1
        return {
            'label': self.label,
            'reason': reason,
            'velocity_world_mps': (None if setpoint is None else setpoint),
        }
