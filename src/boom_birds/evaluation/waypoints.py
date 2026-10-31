"""Minimal multi-waypoint runner (offline waypoints, no online planning)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class WaypointConfig:
    arrival_radius_m: float = 0.25
    arrival_speed_mps: float = 0.2
    intermediate_hold_s: float = 0.2
    final_hold_s: float = 0.5
    segment_timeout_s: float = 20.0
    dt_s: float = 0.05


class WaypointRunner:
    """Sequential waypoint state machine with explicit intermediate/final stops."""

    def __init__(self, waypoints, config=None, timeout_s=60.0):
        if len(waypoints) < 2:
            raise ValueError('at least two waypoints are required')
        self.waypoints = [tuple(float(value) for value in item)
                          for item in waypoints]
        self.config = config or WaypointConfig()
        self.timeout_s = float(timeout_s)
        self.reset()

    def reset(self):
        self.index = 0
        self.hold_s = 0.0
        self.segment_start_s = 0.0
        self.outcome = 'RUNNING'
        self.reason = 'RUNNING'
        self.start_time_s = 0.0
        self.waypoints_completed = 0

    def update(self, position_world_m, speed_mps, now_s, contact=False):
        if self.outcome != 'RUNNING':
            return self._decision(position_world_m)
        if contact:
            self.outcome, self.reason = 'COLLISION', 'MAP_CONTACT'
            return self._decision(position_world_m)
        if now_s >= self.timeout_s:
            self.outcome, self.reason = 'TIMEOUT', 'ROUTE_TIMEOUT'
            return self._decision(position_world_m)
        if now_s - self.segment_start_s > self.config.segment_timeout_s:
            self.outcome, self.reason = 'TIMEOUT', 'WAYPOINT_TIMEOUT'
            return self._decision(position_world_m)
        target = self.waypoints[self.index]
        distance = sum((target[axis] - position_world_m[axis]) ** 2
                       for axis in range(3)) ** 0.5
        reached = (distance <= self.config.arrival_radius_m
                   and speed_mps <= self.config.arrival_speed_mps)
        if reached:
            self.hold_s += self.config.dt_s
        else:
            self.hold_s = 0.0
        final = self.index == len(self.waypoints) - 1
        hold_required = (self.config.final_hold_s if final
                         else self.config.intermediate_hold_s)
        if reached and self.hold_s >= hold_required:
            if final:
                self.outcome, self.reason = 'SUCCESS', 'ROUTE_COMPLETE'
                self.waypoints_completed = len(self.waypoints)
            else:
                self.index += 1
                self.waypoints_completed = self.index
                self.hold_s = 0.0
                self.segment_start_s = now_s
        return self._decision(position_world_m)

    def _decision(self, position_world_m):
        target = self.waypoints[self.index]
        distance = sum((target[axis] - position_world_m[axis]) ** 2
                       for axis in range(3)) ** 0.5
        return {
            'outcome': self.outcome, 'reason': self.reason,
            'terminated': self.outcome != 'RUNNING',
            'waypoint_index': self.index,
            'waypoint_count': len(self.waypoints),
            'waypoints_completed': self.waypoints_completed,
            'waypoint_distance_m': distance,
            'hold_s': self.hold_s,
            'target_world_m': target,
            'final_waypoint': self.index == len(self.waypoints) - 1,
        }
