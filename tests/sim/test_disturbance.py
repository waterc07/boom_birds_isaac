"""External physical disturbance schedule in the body frame."""
import math

import pytest

from boom_birds.sim.disturbance import DisturbanceSpec, is_active, wrench_at


def spec(**overrides):
    values = dict(force_body_n=(0.05, 0.0, 0.0), torque_body_nm=(0.0, 0.0, 0.001),
                  start_s=1.0, duration_s=0.5)
    values.update(overrides)
    return DisturbanceSpec(**values)


def test_window_and_ramp():
    item = spec()
    assert not is_active(item, 0.99)
    assert is_active(item, 1.0)
    assert is_active(item, 1.49)
    assert not is_active(item, 1.5)
    force, torque = wrench_at(item, 0.5)
    assert force == (0.0, 0.0, 0.0) and torque == (0.0, 0.0, 0.0)
    force, torque = wrench_at(item, 1.0)
    assert abs(force[0]) < 0.05
    force, torque = wrench_at(item, 1.2)
    assert force == pytest.approx(item.force_body_n)
    assert torque == pytest.approx(item.torque_body_nm)
    force, _torque = wrench_at(item, 2.0)
    assert force == (0.0, 0.0, 0.0)


def test_zero_ramp_applies_full_value_immediately():
    item = spec(ramp_s=0.0)
    force, _torque = wrench_at(item, 1.0)
    assert force == pytest.approx(item.force_body_n)


@pytest.mark.parametrize('kwargs', [
    {'force_body_n': (math.nan, 0.0, 0.0)},
    {'force_body_n': (0.0, 0.0)},
    {'torque_body_nm': (0.0, math.inf, 0.0)},
    {'start_s': -1.0},
    {'duration_s': 0.0},
    {'ramp_s': -0.1},
])
def test_validation(kwargs):
    with pytest.raises(ValueError):
        spec(**kwargs)


def test_force_magnitude_is_recorded_in_newtons():
    item = spec(force_body_n=(0.03, 0.04, 0.0))
    force, _torque = wrench_at(item, 1.2)
    assert math.hypot(force[0], force[1]) == pytest.approx(0.05)
