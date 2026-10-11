"""Clock domains must match; an unmeasured capture age stays unknown."""
import math

from .types import SCHEMA_ID, VelocityCommand, is_counter


def sample_age_s(sample_time_ns: int, sample_clock_id: str, now_ns: int,
                 now_clock_id: str) -> float | None:
    """None means unknown/invalid, never zero-age substitution.

    External-clock capture timestamps require a separately validated mapping.
    A caller may measure receive age explicitly in the host clock instead.
    """
    if (not all(is_counter(v) for v in (sample_time_ns, now_ns))
            or not sample_clock_id or sample_clock_id != now_clock_id or now_ns < sample_time_ns):
        return None
    return (now_ns - sample_time_ns) / 1_000_000_000


def command_is_valid(command: VelocityCommand, now_ns: int, mission_epoch: int,
                     *, origin_epoch: int = 0, clock_id: str = 'host_monotonic') -> bool:
    """Validity only: mode/state permission checks belong to the supervisor."""
    if not isinstance(command, VelocityCommand):
        return False
    if (not all(is_counter(v) for v in (now_ns, mission_epoch, origin_epoch,
                                       command.created_ns, command.valid_until_ns,
                                       command.mission_epoch, command.origin_epoch))
            or command.schema_id != SCHEMA_ID or not clock_id
            or command.clock_id != clock_id or command.mission_epoch != mission_epoch
            or command.origin_epoch != origin_epoch
            or not command.created_ns <= now_ns < command.valid_until_ns):
        return False
    try:
        values = (*command.velocity_enu_mps, command.yaw_rate_rad_s)
        return (len(command.velocity_enu_mps) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in values))
    except TypeError:
        return False
