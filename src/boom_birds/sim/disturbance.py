"""External physical disturbance in the body frame (N and N*m)."""
import math
from dataclasses import dataclass

DEFAULT_RAMP_S = 0.1


def _triple(values, name):
    try:
        converted = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain three numbers')
    if len(converted) != 3 or any(not math.isfinite(value) for value in converted):
        raise ValueError(name + ' must contain three finite values')
    return converted


@dataclass(frozen=True)
class DisturbanceSpec:
    """Body-frame force (N) and torque (N*m) over a time window."""
    force_body_n: tuple
    torque_body_nm: tuple
    start_s: float
    duration_s: float
    ramp_s: float = DEFAULT_RAMP_S

    def __post_init__(self):
        _triple(self.force_body_n, 'force_body_n')
        _triple(self.torque_body_nm, 'torque_body_nm')
        for name in ('start_s', 'duration_s', 'ramp_s'):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or not math.isfinite(value):
                raise ValueError(name + ' must be a finite number')
        if self.start_s < 0:
            raise ValueError('start_s must be nonnegative')
        if self.duration_s <= 0:
            raise ValueError('duration_s must be positive')
        if self.ramp_s < 0:
            raise ValueError('ramp_s must be nonnegative')


def is_active(spec, time_s):
    return spec.start_s <= time_s < spec.start_s + spec.duration_s


def _scale(spec, time_s):
    if not is_active(spec, time_s):
        return 0.0
    if spec.ramp_s == 0:
        return 1.0
    return min(1.0, max(0.0, (time_s - spec.start_s) / spec.ramp_s))


def wrench_at(spec, time_s):
    scale = _scale(spec, time_s)
    force = tuple(scale * value for value in spec.force_body_n)
    torque = tuple(scale * value for value in spec.torque_body_nm)
    return force, torque

def compose_actor_wrench(base_thrust_body_n, base_moment_body_nm, force_body_n,
                         torque_body_nm, com_delta_body_m=(0.0, 0.0, 0.0)):
    """Compose the actuator wrench with an external body-frame disturbance.

    Two implementation rules are regression-tested: lateral force components
    are ASSIGNED, not added, so repeated policy steps cannot accumulate
    residue; and the force is applied at the base-link COM while the
    articulation COM is offset by com_delta_body_m, so the lever-arm torque is
    cancelled to keep the scenario force a pure force plus its recorded torque.
    """
    base_thrust = _triple(base_thrust_body_n, 'base_thrust_body_n')
    base_moment = _triple(base_moment_body_nm, 'base_moment_body_nm')
    force = _triple(force_body_n, 'force_body_n')
    torque = _triple(torque_body_nm, 'torque_body_nm')
    delta = _triple(com_delta_body_m, 'com_delta_body_m')
    compensation = (delta[1] * force[2] - delta[2] * force[1],
                    delta[2] * force[0] - delta[0] * force[2],
                    delta[0] * force[1] - delta[1] * force[0])
    composed_force = (force[0], force[1], base_thrust[2] + force[2])
    composed_moment = tuple(base_moment[index] + torque[index]
                            + compensation[index] for index in range(3))
    return composed_force, composed_moment
