"""Minimal stop-wait-resume supervisor for a frozen waypoint route (ORACLE)."""
from dataclasses import dataclass

from boom_birds.evaluation.clearance import (build_clearance_record,
                                             point_to_segment_distance,
                                             predicted_path_clearance,
                                             PREDICTION_HORIZON_S,
                                             PREDICTION_STEP_S,
                                             DEFAULT_ROBOT_AABB_HALF_EXTENTS_M,
                                             DEFAULT_OBSTACLE_SIZE_M)

SUPERVISOR_STATES = ('FOLLOW', 'BRAKE', 'HOLD', 'WAIT', 'RESUME',
                     'DEGRADED', 'ABORT', 'SUCCESS')

# Backward-compatible module-level helper (still imported by
# ``scripts/analyze_latency_envelope.py``); it is the shared clearance function.
_distance_point_segment = point_to_segment_distance


@dataclass(frozen=True)
class SupervisorConfig:
    stop_distance_m: float = 1.1
    release_distance_m: float = 1.6
    prediction_horizon_s: float = PREDICTION_HORIZON_S
    prediction_step_s: float = PREDICTION_STEP_S
    observation_max_age_s: float = 0.3
    max_stale_s: float = 2.0
    max_wait_s: float = 8.0
    min_hold_s: float = 0.5
    release_hold_s: float = 0.5
    resume_hold_s: float = 0.3
    stop_speed_mps: float = 0.12
    # Envelope inputs for the decision ``clearance_record``.  The evaluation
    # runner should override these with the AABB/size measured in its own run.
    robot_aabb_half_extents_m: tuple = DEFAULT_ROBOT_AABB_HALF_EXTENTS_M
    robot_aabb_prim: str = '/World/envs/env_0/Robot'
    robot_aabb_source: str = 'measured_usd_aabb_at_runtime'
    obstacle_size_m: tuple = DEFAULT_OBSTACLE_SIZE_M
    obstacle_envelope_source: str = 'case_obstacle_size'


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
        self.clearance_record = None

    def _set_state(self, state, now_s):
        if state != self.state:
            self.state = state
            self.transitions += 1
            self.last_transition_s = now_s

    def _risk(self, robot_position, target, observation):
        cfg = self.config
        result = predicted_path_clearance(
            robot_position, target,
            observation['position_world_m'],
            observation['velocity_world_mps'],
            cfg.prediction_horizon_s, cfg.prediction_step_s)
        return result['path_clearance_m'], result['point_distances_m']

    def _robot_envelope(self, robot_envelope):
        if robot_envelope is not None:
            return robot_envelope
        return {'half_extents_m': self.config.robot_aabb_half_extents_m,
                'measured_prim': self.config.robot_aabb_prim,
                'source': self.config.robot_aabb_source}

    def _obstacle_envelope(self, obstacle_envelope):
        if obstacle_envelope is not None:
            return obstacle_envelope
        return {'size_m': self.config.obstacle_size_m,
                'source': self.config.obstacle_envelope_source}

    def _build_clearance_record(self, robot_position, target, observation,
                                *, observation_valid, validity_reasons,
                                robot_velocity_world_mps, waypoint_index,
                                robot_envelope, obstacle_envelope):
        return build_clearance_record(
            robot_position, target, observation,
            robot_velocity_world_mps=robot_velocity_world_mps,
            waypoint_index=waypoint_index,
            robot_envelope=self._robot_envelope(robot_envelope),
            obstacle_envelope=self._obstacle_envelope(obstacle_envelope),
            horizon_s=self.config.prediction_horizon_s,
            step_s=self.config.prediction_step_s,
            observation_valid=observation_valid,
            validity_reasons=validity_reasons)

    def update(self, robot_position_world_m, target_world_m, speed_mps,
               observation, now_s, dt_s, *, robot_velocity_world_mps=None,
               waypoint_index=None, robot_envelope=None,
               obstacle_envelope=None):
        cfg = self.config
        age = float(observation.get('age_s', 0.0))
        stale = (not observation.get('valid', False)
                 or age > cfg.observation_max_age_s)
        if stale:
            self.stale_s += dt_s
            self.wait_s += dt_s
            self._set_state('DEGRADED', now_s)
            if self.stale_s > cfg.max_stale_s:
                self._set_state('ABORT', now_s)
                self.abort_reason = 'OBSERVATION_STALE'
            validity_reasons = []
            if not observation.get('valid', False):
                reason = observation.get('reason')
                validity_reasons.append(
                    reason if reason not in (None, '', 'ACCEPT')
                    else 'OBSERVATION_INVALID')
            if age > cfg.observation_max_age_s:
                validity_reasons.append('OBSERVATION_AGE_EXCEEDS_LIMIT')
            if not validity_reasons:
                validity_reasons.append('OBSERVATION_STALE')
            self.clearance_record = self._build_clearance_record(
                robot_position_world_m, target_world_m, observation,
                observation_valid=False,
                validity_reasons=validity_reasons,
                robot_velocity_world_mps=robot_velocity_world_mps,
                waypoint_index=waypoint_index,
                robot_envelope=robot_envelope,
                obstacle_envelope=obstacle_envelope)
            action = 'STOP' if self.state != 'ABORT' else 'ABORT'
            return self._decision(now_s, action)
        self.stale_s = 0.0
        clearance, _distances = self._risk(robot_position_world_m,
                                           target_world_m, observation)
        self.clearance_m = clearance
        self.clearance_record = self._build_clearance_record(
            robot_position_world_m, target_world_m, observation,
            observation_valid=True, validity_reasons=[],
            robot_velocity_world_mps=robot_velocity_world_mps,
            waypoint_index=waypoint_index,
            robot_envelope=robot_envelope,
            obstacle_envelope=obstacle_envelope)
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
            'clearance_record': self.clearance_record,
        }
