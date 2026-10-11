"""Yaw-only horizontal FLU -> ENU -> NED. Positive ENU yaw is CCW."""
import math
from collections.abc import Sequence

from .types import ActionLimits, VelocityCommand, is_counter


def _finite_vector(vector: Sequence[float], size: int) -> tuple[float, ...]:
    try:
        values = tuple(vector)
        if len(values) != size or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                     or not math.isfinite(v) for v in values):
            raise ValueError(f'Expected {size} finite numeric values')
    except TypeError as exc:
        raise ValueError(f'Expected {size} finite numeric values') from exc
    return tuple(float(v) for v in values)


def decode_action(action: Sequence[float], yaw_rad: float, limits: ActionLimits,
                  now_ns: int, mission_epoch: int, *, origin_epoch: int = 0,
                  clock_id: str = 'host_monotonic') -> VelocityCommand:
    """Create a NEW command once; resend this immutable message unchanged.

    Batch tensor callers must convert to scalars at the adapter boundary.
    Only heading rotates horizontal velocity, independent of roll/pitch.
    """
    values = _finite_vector(action, 4)
    yaw = _finite_vector((yaw_rad,), 1)[0]
    if not all(is_counter(v) for v in (now_ns, mission_epoch, origin_epoch)):
        raise ValueError('Time and epochs must be nonnegative integers')
    if not isinstance(clock_id, str) or not clock_id:
        raise ValueError('clock_id must identify the current clock domain')
    forward, left, up, turn = (max(-1.0, min(1.0, v)) for v in values)
    divisor = max(1.0, math.hypot(forward, left))
    forward = forward / divisor * limits.horizontal_mps
    left = left / divisor * limits.horizontal_mps
    c, s = math.cos(yaw), math.sin(yaw)
    velocity = (c * forward - s * left, s * forward + c * left, up * limits.vertical_mps)
    return VelocityCommand(velocity, turn * limits.yaw_rate_rad_s, now_ns,
                           now_ns + limits.ttl_ns, mission_epoch,
                           origin_epoch=origin_epoch, clock_id=clock_id)


def enu_to_ned(vector: Sequence[float]) -> tuple[float, float, float]:
    east, north, up = _finite_vector(vector, 3)
    return north, east, -up


def yaw_rate_enu_to_ned(yaw_rate_rad_s: float) -> float:
    return -_finite_vector((yaw_rate_rad_s,), 1)[0]
