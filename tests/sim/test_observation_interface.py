"""Observation interface degradation: noise, delay, dropout, validity."""
import math

import pytest

from boom_birds.sim.observation_interface import (
    DegradationSpec,
    ObservationInterface,
)


def spec(**overrides):
    values = dict(position_noise_std_m=0.0, velocity_noise_std_mps=0.0,
                  delay_steps=0, dropout_probability=0.0, max_stale_s=0.3)
    values.update(overrides)
    return DegradationSpec(**values)


def test_identity_observation_is_valid_and_fresh():
    interface = ObservationInterface(spec(), dt_s=0.05, seed=0)
    observation = interface.observe(position=(1.0, 2.0, 0.75),
                                    velocity=(0.1, 0.0, 0.0),
                                    quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    assert observation.valid is True
    assert observation.position == pytest.approx((1.0, 2.0, 0.75))
    assert observation.velocity == pytest.approx((0.1, 0.0, 0.0))
    assert observation.age_s == 0.0
    assert observation.source_step == 0


def test_delay_returns_older_sample_with_age():
    interface = ObservationInterface(spec(delay_steps=2), dt_s=0.05, seed=1)
    for step, x in enumerate((0.0, 1.0, 2.0, 3.0)):
        observation = interface.observe(position=(x, 0.0, 0.75), velocity=(0.0, 0.0, 0.0),
                                        quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=step)
    assert observation.position[0] == pytest.approx(1.0)
    assert observation.age_s == pytest.approx(0.1)
    assert observation.source_step == 1
    assert observation.valid is True


def test_noise_is_deterministic_and_nonzero():
    first = ObservationInterface(spec(position_noise_std_m=0.05), dt_s=0.05, seed=7)
    second = ObservationInterface(spec(position_noise_std_m=0.05), dt_s=0.05, seed=7)
    a = first.observe(position=(1.0, 2.0, 0.75), velocity=(0.0, 0.0, 0.0),
                      quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    b = second.observe(position=(1.0, 2.0, 0.75), velocity=(0.0, 0.0, 0.0),
                       quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    assert a.position == pytest.approx(b.position)
    assert a.position != pytest.approx((1.0, 2.0, 0.75))


def test_total_dropout_marks_invalid_without_zero_filling():
    interface = ObservationInterface(spec(dropout_probability=1.0), dt_s=0.05, seed=2)
    observation = interface.observe(position=(5.0, 6.0, 0.75), velocity=(0.2, 0.0, 0.0),
                                    quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=3)
    assert observation.valid is False
    assert observation.reason == 'DROPOUT'
    assert observation.position == pytest.approx((5.0, 6.0, 0.75))
    assert observation.position != (0.0, 0.0, 0.0)
    assert observation.age_s > 0.0


def test_stale_valid_sample_becomes_invalid_beyond_max_age():
    interface = ObservationInterface(spec(delay_steps=1, max_stale_s=0.02),
                                     dt_s=0.05, seed=3)
    interface.observe(position=(1.0, 0.0, 0.75), velocity=(0.0, 0.0, 0.0),
                      quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    observation = interface.observe(position=(2.0, 0.0, 0.75), velocity=(0.0, 0.0, 0.0),
                                    quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=1)
    assert observation.valid is False
    assert observation.reason == 'STALE'


def test_reset_clears_delay_and_rng_state():
    interface = ObservationInterface(spec(delay_steps=2), dt_s=0.05, seed=4)
    interface.observe(position=(9.0, 0.0, 0.75), velocity=(0.0, 0.0, 0.0),
                      quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    interface.reset()
    observation = interface.observe(position=(1.0, 0.0, 0.75), velocity=(0.0, 0.0, 0.0),
                                    quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=0)
    assert observation.valid is True
    assert observation.position == pytest.approx((1.0, 0.0, 0.75))
    assert observation.age_s == 0.0


def test_invalid_observation_does_not_zero_fill_velocity():
    interface = ObservationInterface(spec(dropout_probability=1.0), dt_s=0.05, seed=5)
    observation = interface.observe(position=(1.0, 1.0, 0.75), velocity=(0.3, 0.0, 0.0),
                                    quat_wxyz=(1.0, 0.0, 0.0, 0.0), step_index=1)
    assert observation.velocity == pytest.approx((0.3, 0.0, 0.0))


def test_spec_validation():
    with pytest.raises(ValueError):
        DegradationSpec(position_noise_std_m=math.nan)
    with pytest.raises(ValueError):
        DegradationSpec(delay_steps=-1)
    with pytest.raises(ValueError):
        DegradationSpec(dropout_probability=1.2)
    with pytest.raises(ValueError):
        DegradationSpec(max_stale_s=0.0)
