"""Kinematic dynamic obstacle specs and observations (simulation-only)."""
import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DynamicObstacleSpec:
    obstacle_id: str
    size_m: tuple
    kind: str
    start_time_s: float
    end_time_s: float
    start_position_world_m: tuple = (0.0, 0.0, 0.0)
    velocity_world_mps: tuple = (0.0, 0.0, 0.0)
    oscillation_center_world_m: tuple | None = None
    oscillation_axis_world: tuple = (1.0, 0.0, 0.0)
    oscillation_amplitude_m: float = 0.0
    oscillation_period_s: float = 2.0
    observation_delay_s: float = 0.0
    observation_dropout_windows_s: tuple = ()
    observation_max_age_s: float = 0.3

    def pose_at(self, t_s):
        if self.kind == 'linear':
            position = tuple(self.start_position_world_m[index]
                             + self.velocity_world_mps[index] * t_s
                             for index in range(3))
            return position, tuple(self.velocity_world_mps)
        if self.kind == 'oscillate':
            if self.oscillation_center_world_m is None:
                raise ValueError('oscillate obstacle needs a center')
            phase = 2.0 * math.pi * t_s / self.oscillation_period_s
            offset = self.oscillation_amplitude_m * math.sin(phase)
            derivative = (self.oscillation_amplitude_m * 2.0 * math.pi
                          / self.oscillation_period_s) * math.cos(phase)
            position = tuple(self.oscillation_center_world_m[index]
                             + self.oscillation_axis_world[index] * offset
                             for index in range(3))
            velocity = tuple(self.oscillation_axis_world[index] * derivative
                             for index in range(3))
            return position, velocity
        raise ValueError('unknown obstacle kind: ' + str(self.kind))

    def active_at(self, t_s):
        return self.start_time_s <= t_s <= self.end_time_s

    def observation_at(self, t_s):
        for start, end in self.observation_dropout_windows_s:
            if start <= t_s < end:
                return {'valid': False, 'reason': 'OBSERVATION_DROPOUT',
                        'age_s': 0.0, 'position_world_m': None,
                        'velocity_world_mps': None, 'timestamp_s': t_s}
        sample_t = t_s - self.observation_delay_s
        if sample_t < 0.0:
            sample_t = 0.0
        position, velocity = self.pose_at(sample_t)
        return {'valid': True, 'reason': 'ACCEPT',
                'age_s': self.observation_delay_s, 'position_world_m': position,
                'velocity_world_mps': velocity, 'timestamp_s': sample_t}


def load_obstacle_spec(payload):
    return DynamicObstacleSpec(
        obstacle_id=payload['obstacle_id'],
        size_m=tuple(float(value) for value in payload['size_m']),
        kind=payload['kind'],
        start_time_s=float(payload.get('start_time_s', 0.0)),
        end_time_s=float(payload.get('end_time_s', 1e9)),
        start_position_world_m=tuple(float(value) for value in
                                     payload.get('start_position_world_m',
                                                 (0.0, 0.0, 0.0))),
        velocity_world_mps=tuple(float(value) for value in
                                 payload.get('velocity_world_mps',
                                             (0.0, 0.0, 0.0))),
        oscillation_center_world_m=(None if payload.get('oscillation_center_world_m')
                                    is None else tuple(float(value) for value in
                                                       payload['oscillation_center_world_m'])),
        oscillation_axis_world=tuple(float(value) for value in
                                     payload.get('oscillation_axis_world',
                                                 (1.0, 0.0, 0.0))),
        oscillation_amplitude_m=float(payload.get('oscillation_amplitude_m', 0.0)),
        oscillation_period_s=float(payload.get('oscillation_period_s', 2.0)),
        observation_delay_s=float(payload.get('observation_delay_s', 0.0)),
        observation_dropout_windows_s=tuple(
            (float(item[0]), float(item[1]))
            for item in payload.get('observation_dropout_windows_s', ())),
        observation_max_age_s=float(payload.get('observation_max_age_s', 0.3)))
