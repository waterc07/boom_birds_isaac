"""Conservative envelope/gap and stop-requirement decomposition."""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class Envelope:
    half_extents_m: tuple
    label: str = 'UNSPECIFIED'
    def __post_init__(self):
        if len(self.half_extents_m) != 3 or any(x <= 0 for x in self.half_extents_m):
            raise ValueError('half_extents_m must be three positive values')
    def conservative_radius_m(self):
        return max(self.half_extents_m)
    def sphere_gap_m(self, center_distance_m, other):
        return center_distance_m - self.conservative_radius_m() - other.conservative_radius_m()

@dataclass(frozen=True)
class StopRequirement:
    brake_distance_m: float
    relative_speed_mps: float
    observation_age_s: float
    queue_delay_s: float
    decision_latency_s: float
    actuation_latency_s: float
    envelope_sum_m: float
    margin_m: float
    def reaction_distance_m(self):
        return self.relative_speed_mps * (self.observation_age_s + self.queue_delay_s
                                          + self.decision_latency_s + self.actuation_latency_s)
    def required_center_distance_m(self):
        return (self.brake_distance_m + self.reaction_distance_m()
                + self.envelope_sum_m + self.margin_m)
