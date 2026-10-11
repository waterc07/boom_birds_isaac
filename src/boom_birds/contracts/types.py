"""Physical-unit messages; no simulator, tensors or flight permissions."""
from dataclasses import dataclass
import math

SCHEMA_ID = 'boom_birds.velocity.v1'


def is_counter(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class ActionLimits:
    """PROPOSED simulation defaults, not measured aircraft limits."""
    horizontal_mps: float = 1.0
    vertical_mps: float = 0.5
    yaw_rate_rad_s: float = 0.5
    ttl_ns: int = 150_000_000

    def __post_init__(self):
        for value in (self.horizontal_mps, self.vertical_mps, self.yaw_rate_rad_s):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError('Motion limits must be finite nonnegative numbers')
        if not is_counter(self.ttl_ns) or self.ttl_ns == 0:
            raise ValueError('ttl_ns must be a positive integer')


@dataclass(frozen=True)
class VelocityCommand:
    velocity_enu_mps: tuple[float, float, float]
    yaw_rate_rad_s: float
    created_ns: int
    valid_until_ns: int
    mission_epoch: int
    source: str = 'policy'
    origin_epoch: int = 0
    clock_id: str = 'host_monotonic'
    schema_id: str = SCHEMA_ID
