"""Minimal stop-wait-resume supervisor for a frozen waypoint route (ORACLE)."""
import math
from dataclasses import dataclass

SUPERVISOR_STATES = ('FOLLOW', 'BRAKE', 'HOLD', 'WAIT', 'RESUME',
                     'DEGRADED', 'ABORT', 'SUCCESS')


@dataclass(frozen=True)
class SupervisorConfig:
    stop_distance_m: float = 1.1
    release_distance_m: float = 1.6
    prediction_horizon_s: float = 1.0
    prediction_step_s: float = 0.1
    observation_max_age_s: float = 0.3
    max_stale_s: float = 2.0
    max_wait_s: float = 8.0
    min_hold_s: float = 0.5
    release_hold_s: float = 0.5
    resume_hold_s: float = 0.3
    stop_speed_mps: float = 0.12


def _distance_point_segment(point, start, end):
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(value * value for value in segment)
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = sum((point[index] - start[index]) * segment[index]
            for index in range(3)) / length_sq
    t = min(1.0, max(0.0, t))
    projection = [start[index] + segment[index] * t for index in range(3)]
    return math.dist(point, projection)


class RouteSupervisor:
    def __init__(self, config=None):
        self.config = config or SupervisorConfig()
        self.reset()

    def reset(self):
        self.state = 'FOLLOW'
        self.wait_s = 0.0
        self.stale_s = 0.0
        self.hold_s = 0.0
        self.release_s = 0.0
        self.resume_s = 0.0
        self.transitions = 0
        self.last_transition_s = 0.0
        self.abort_reason = None
        self.clearance_m = None
        self.risk = False

    def _set_state(self, state, now_s):
        if state != self.state:
            self.state = state
            self.transitions += 1
            self.last_transition_s = now_s

    def _risk(self, robot_position, target, observation):
        cfg = self.config
        predicted = []
        steps = max(1, int(math.ceil(cfg.prediction_horizon_s
                                     / cfg.prediction_step_s)))
        for step in range(steps + 1):
            t = step * cfg.prediction_step_s
            predicted.append([observation['position_world_m'][axis]
                              + observation['velocity_world_mps'][axis] * t
                              for axis in range(3)])
        distances = [_distance_point_segment(point, robot_position, target)
                     for point in predicted]
        return min(distances), distances

    def update(self, robot_position_world_m, target_world_m, speed_mps,
               observation, now_s, dt_s):
        cfg = self.config
        stale = (not observation.get('valid', False)
                 or float(observation.get('age_s', 0.0)) > cfg.observation_max_age_s)
        if stale:
            self.stale_s += dt_s
            self.wait_s += dt_s
            self._set_state('DEGRADED', now_s)
            if self.stale_s > cfg.max_stale_s:
                self._set_state('ABORT', now_s)
                self.abort_reason = 'OBSERVATION_STALE'
            return self._decision(now_s, 'STOP' if self.state != 'ABORT' else 'ABORT')
        self.stale_s = 0.0
        clearance, distances = self._risk(robot_position_world_m, target_world_m,
                                          observation)
        self.clearance_m = clearance
        self.risk = clearance < cfg.stop_distance_m
        released = clearance > cfg.release_distance_m
        if self.risk:
            self.release_s = 0.0
        else:
            self.release_s += dt_s
        if self.state == 'FOLLOW':
            if self.risk:
                self._set_state('BRAKE', now_s)
        elif self.state == 'BRAKE':
            if speed_mps <= cfg.stop_speed_mps:
                self.hold_s = 0.0
                self._set_state('HOLD', now_s)
        elif self.state == 'HOLD':
            self.hold_s += dt_s
            if self.hold_s >= cfg.min_hold_s:
                self._set_state('WAIT', now_s)
        elif self.state == 'WAIT':
            self.wait_s += dt_s
            if self.release_s >= cfg.release_hold_s and not self.risk:
                self.resume_s = 0.0
                self._set_state('RESUME', now_s)
            elif self.wait_s > cfg.max_wait_s:
                self._set_state('ABORT', now_s)
                self.abort_reason = 'MAX_WAIT_EXCEEDED'
        elif self.state == 'RESUME':
            self.resume_s += dt_s
            if self.risk:
                self._set_state('BRAKE', now_s)
            elif self.resume_s >= cfg.resume_hold_s:
                self._set_state('FOLLOW', now_s)
        elif self.state == 'DEGRADED':
            self._set_state('WAIT', now_s)
        if self.state == 'ABORT':
            return self._decision(now_s, 'ABORT')
        action = 'STOP' if self.state in ('BRAKE', 'HOLD', 'WAIT') else 'ROUTE'
        return self._decision(now_s, action)

    def _decision(self, now_s, action):
        return {
            'state': self.state, 'action': action,
            'wait_s': self.wait_s, 'stale_s': self.stale_s,
            'clearance_m': self.clearance_m, 'transitions': self.transitions,
            'abort_reason': self.abort_reason,
        }