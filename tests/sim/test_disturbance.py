"""External physical disturbance schedule in the body frame."""
import math

import pytest

from boom_birds.sim.disturbance import (
    DisturbanceSpec, compose_actor_wrench, is_active, wrench_at,
)


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

def test_actor_wrench_assigns_lateral_force_without_accumulation():
    base_thrust = (0.0, 0.0, 0.277)
    base_moment = (0.0, 0.0, 0.0)
    force = (0.02, -0.01, 0.0)
    torque = (0.0, 0.0, 0.0001)
    first = compose_actor_wrench(base_thrust, base_moment, force, torque)
    second = compose_actor_wrench(base_thrust, base_moment, force, torque)
    assert first == second
    assert first[0] == pytest.approx((0.02, -0.01, 0.277))
    assert first[1] == pytest.approx((0.0, 0.0, 0.0001))


def test_actor_wrench_zero_force_clears_lateral_residue():
    composed_force, composed_moment = compose_actor_wrench(
        (0.0, 0.0, 0.277), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert composed_force == pytest.approx((0.0, 0.0, 0.277))
    assert composed_moment == pytest.approx((0.0, 0.0, 0.0))


def test_actor_wrench_cancels_com_lever_arm():
    # 2 mm system-COM offset above the base-link COM and 0.02 N forward force
    # would otherwise create a nose-down pitch torque.
    composed_force, composed_moment = compose_actor_wrench(
        (0.0, 0.0, 0.277), (0.0, 0.0, 0.0), (0.02, 0.0, 0.0),
        (0.0, 0.0, 0.0), (0.0, 0.0, 0.002))
    assert composed_force == pytest.approx((0.02, 0.0, 0.277))
    assert composed_moment == pytest.approx((0.0, 0.00004, 0.0))
