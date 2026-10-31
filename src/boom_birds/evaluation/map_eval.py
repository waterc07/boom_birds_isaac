"""Map-specific evaluators (bounds, floor, takeoff/landing phases)."""
from dataclasses import dataclass

MAP_OUTCOMES = ('SUCCESS', 'COLLISION', 'TIMEOUT', 'OUT_OF_BOUNDS', 'INVALID')


@dataclass(frozen=True)
class MapReachSpec:
    goal_position_world_m: tuple
    bounds_min_m: tuple
    bounds_max_m: tuple
    floor_z_m: float
    success_distance_m: float = 0.2
    success_speed_mps: float = 0.2
    hold_time_s: float = 0.5
    timeout_s: float = 15.0


class MapReachEvaluator:
    def __init__(self, spec, dt_s=0.05):
        self.spec = spec
        self.dt_s = dt_s
        self.hold_steps = max(1, int(round(spec.hold_time_s / dt_s)))
        self.count = 0
        self.outcome = 'RUNNING'
        self.reason = 'RUNNING'

    def reset(self):
        self.count = 0
        self.outcome = 'RUNNING'
        self.reason = 'RUNNING'

    def update(self, position_world_m, speed_mps, now_s, collision=False):
        if self.outcome != 'RUNNING':
            return self._decision(position_world_m)
        if collision:
            self.outcome, self.reason = 'COLLISION', 'MAP_CONTACT'
            return self._decision(position_world_m)
        low, high = self.spec.bounds_min_m, self.spec.bounds_max_m
        outside = (not (low[0] <= position_world_m[0] <= high[0]
                        and low[1] <= position_world_m[1] <= high[1]
                        and self.spec.floor_z_m - 0.5 <= position_world_m[2]
                        <= high[2]))
        if outside:
            self.outcome, self.reason = 'OUT_OF_BOUNDS', 'MAP_BOUNDS'
            return self._decision(position_world_m)
        distance = sum((self.spec.goal_position_world_m[index]
                        - position_world_m[index]) ** 2 for index in range(3)) ** 0.5
        if distance <= self.spec.success_distance_m and speed_mps <= self.spec.success_speed_mps:
            self.count += 1
        else:
            self.count = 0
        if self.count >= self.hold_steps:
            self.outcome, self.reason = 'SUCCESS', 'HOLD_SATISFIED'
        elif now_s >= self.spec.timeout_s:
            self.outcome, self.reason = 'TIMEOUT', 'TIMEOUT'
        return self._decision(position_world_m)

    def _decision(self, position_world_m):
        distance = sum((self.spec.goal_position_world_m[index]
                        - position_world_m[index]) ** 2 for index in range(3)) ** 0.5
        return {
            'outcome': self.outcome, 'reason': self.reason,
            'terminated': self.outcome != 'RUNNING',
            'distance_m': distance, 'hold_time_s': self.count * self.dt_s,
        }


class TakeoffLandingEvaluator:
    """Explicit ground, takeoff, hover, descent and landing phase machine."""

    def __init__(self, case, timeout_s):
        self.case = case
        self.timeout_s = timeout_s
        self.state = 'GROUND'
        self.hover_start = None
        self.outcome = 'RUNNING'
        self.reason = 'RUNNING'
        self.landing_contact_force = 0.0

    def update(self, position_world_m, speed_mps, contact_force_n, now_s):
        if self.outcome != 'RUNNING':
            return self._decision(position_world_m)
        if now_s >= self.timeout_s:
            self.outcome, self.reason = 'TIMEOUT', 'TAKEOFF_LANDING_TIMEOUT'
            return self._decision(position_world_m)
        ground = self.case.ground_z_m
        altitude = position_world_m[2] - ground
        target = self.case.hover_altitude_m
        if self.state == 'GROUND':
            if altitude >= target - 0.05:
                self.state, self.hover_start = 'HOVER', now_s
        elif self.state == 'HOVER':
            if now_s - self.hover_start >= self.case.hover_time_s:
                self.state = 'DESCEND'
        elif self.state == 'DESCEND':
            if contact_force_n > 0.02:
                self.landing_contact_force = max(self.landing_contact_force,
                                                 contact_force_n)
                if altitude <= 0.25 and speed_mps <= self.case.landing_speed_max_mps:
                    self.outcome, self.reason = 'SUCCESS', 'LANDED'
                    self.state = 'LANDED'
                elif altitude <= 0.25:
                    self.outcome, self.reason = 'INVALID', 'HARD_LANDING'
                    self.state = 'LANDED'
        return self._decision(position_world_m)

    def _decision(self, position_world_m):
        return {
            'outcome': self.outcome, 'reason': self.reason,
            'terminated': self.outcome != 'RUNNING', 'phase': self.state,
            'altitude_m': position_world_m[2] - self.case.ground_z_m,
            'landing_contact_force_n': self.landing_contact_force,
        }
