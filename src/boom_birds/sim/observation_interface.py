"""Observation-interface degradation for controller input only.

Noise, delay and dropout are applied to the ORACLE-derived controller input.
Evaluation always uses the raw simulator truth. Invalid samples keep their
raw values but are marked invalid; they are never zero-filled or relabelled.
"""
import math
import random
from collections import deque
from dataclasses import dataclass

from .layered import DegradationSpec


@dataclass(frozen=True)
class Observation:
    position_world_m: tuple
    velocity_world_mps: tuple
    quat_wxyz: tuple
    valid: bool
    age_s: float
    source_step: int
    reason: str

    @property
    def position(self):
        return self.position_world_m

    @property
    def velocity(self):
        return self.velocity_world_mps


def _triple(values, name):
    try:
        converted = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain three numbers')
    if len(converted) != 3 or any(not math.isfinite(value) for value in converted):
        raise ValueError(name + ' must contain three finite values')
    return converted


class ObservationInterface:
    """Deterministic degraded observation source; reset clears delay and RNG."""

    def __init__(self, spec, dt_s, seed):
        if not isinstance(spec, DegradationSpec):
            raise ValueError('spec must be a DegradationSpec')
        if not isinstance(dt_s, (int, float)) or isinstance(dt_s, bool) \
                or not math.isfinite(dt_s) or dt_s <= 0:
            raise ValueError('dt_s must be a positive finite number')
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ValueError('seed must be a nonnegative integer')
        self.spec = spec
        self.dt_s = float(dt_s)
        self.seed = seed
        self._buffer = deque()
        self._rng = random.Random(seed)

    def reset(self):
        self._buffer.clear()
        self._rng = random.Random(self.seed)

    def _noise(self, sigma):
        if sigma == 0.0:
            return 0.0
        return self._rng.gauss(0.0, sigma)

    def observe(self, *, position, velocity, quat_wxyz, step_index):
        position = _triple(position, 'position')
        velocity = _triple(velocity, 'velocity')
        quat = tuple(float(value) for value in quat_wxyz)
        if len(quat) != 4 or any(not math.isfinite(value) for value in quat):
            raise ValueError('quat_wxyz must contain four finite values')
        if not isinstance(step_index, int) or isinstance(step_index, bool) \
                or step_index < 0:
            raise ValueError('step_index must be a nonnegative integer')
        self._buffer.append((step_index, position, velocity, quat))
        while len(self._buffer) > self.spec.delay_steps + 1:
            self._buffer.popleft()
        target_index = max(0, len(self._buffer) - 1 - self.spec.delay_steps)
        source_step, source_position, source_velocity, source_quat = \
            self._buffer[target_index]
        age_s = max(0.0, (step_index - source_step) * self.dt_s)
        noisy_position = tuple(
            value + self._noise(self.spec.position_noise_std_m)
            for value in source_position)
        noisy_velocity = tuple(
            value + self._noise(self.spec.velocity_noise_std_mps)
            for value in source_velocity)
        noisy_position = tuple(max(-10.0, min(10.0, value))
                               for value in noisy_position)
        noisy_velocity = tuple(max(-5.0, min(5.0, value))
                               for value in noisy_velocity)
        if self._rng.random() < self.spec.dropout_probability:
            return Observation(noisy_position, noisy_velocity, source_quat, False,
                               max(age_s, self.dt_s), source_step, 'DROPOUT')
        if age_s > self.spec.max_stale_s:
            return Observation(noisy_position, noisy_velocity, source_quat, False,
                               age_s, source_step, 'STALE')
        return Observation(noisy_position, noisy_velocity, source_quat, True,
                           age_s, source_step, 'ACCEPT')
