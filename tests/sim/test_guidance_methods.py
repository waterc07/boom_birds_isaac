"""Traditional guidance baselines: proportional vs braking with velocity feedback."""
import math

import pytest

from boom_birds.sim.guidance import (
    BRAKING,
    PROPORTIONAL,
    BrakingGuidanceSpec,
    make_guidance,
)
from boom_birds.sim.reach import GuidanceSpec, guidance_command

GOAL = (1.5, 1.0, 0.75)
IDENTITY = (1.0, 0.0, 0.0, 0.0)


def command(method, *, position, velocity=(0.0, 0.0, 0.0), quat=IDENTITY):
    return method.command(position_world_m=position, velocity_world_mps=velocity,
                          quat_wxyz=quat)


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError):
        make_guidance('pid', GOAL)
    with pytest.raises(ValueError):
        make_guidance(BRAKING, (1.0, 0.0))


def test_proportional_method_matches_existing_reach_guidance():
    method = make_guidance(PROPORTIONAL, GOAL, proportional_spec=GuidanceSpec())
    expected = guidance_command(position_world_m=(0.0, 0.0, 0.75),
                                quat_wxyz=IDENTITY, goal_position_world_m=GOAL,
                                spec=GuidanceSpec())
    assert command(method, position=(0.0, 0.0, 0.75)) == pytest.approx(expected)
    assert method.name == PROPORTIONAL


def test_braking_method_speeds_up_from_rest_and_points_at_goal():
    method = make_guidance(BRAKING, GOAL, braking_spec=BrakingGuidanceSpec(
        deceleration_mps2=0.8, velocity_feedback_gain=0.8, arrival_radius_m=0.05))
    forward, left, up, yaw_rate = command(method, position=(0.0, 0.0, 0.75))
    assert math.hypot(forward, left) == pytest.approx(0.6, abs=1e-9)
    assert forward > 0 and left > 0
    assert up == pytest.approx(0.0)
    assert yaw_rate == 0.0


def test_braking_profile_slows_down_near_the_goal():
    spec = BrakingGuidanceSpec(deceleration_mps2=0.8, velocity_feedback_gain=0.8,
                               arrival_radius_m=0.02)
    method = make_guidance(BRAKING, GOAL, braking_spec=spec)
    far = math.hypot(*command(method, position=(GOAL[0] - 0.5, GOAL[1], GOAL[2]))[:2])
    near = math.hypot(*command(method, position=(GOAL[0] - 0.05, GOAL[1], GOAL[2]))[:2])
    closer = math.hypot(*command(method, position=(GOAL[0] - 0.02, GOAL[1], GOAL[2]))[:2])
    assert far == pytest.approx(0.6, abs=1e-9)
    assert near < far
    assert closer < near


def test_braking_uses_velocity_feedback_to_brake_when_overspeeding():
    spec = BrakingGuidanceSpec(deceleration_mps2=0.8, velocity_feedback_gain=0.8,
                               arrival_radius_m=0.02)
    braking = make_guidance(BRAKING, GOAL, braking_spec=spec)
    proportional = make_guidance(PROPORTIONAL, GOAL, proportional_spec=GuidanceSpec())
    position = (GOAL[0] - 0.5, GOAL[1], GOAL[2])
    overspeed = (1.0, 0.0, 0.0)
    brake_forward = command(braking, position=position, velocity=overspeed)[0]
    proportional_forward = command(proportional, position=position,
                                   velocity=overspeed)[0]
    assert brake_forward < proportional_forward
    very_fast = command(braking, position=position, velocity=(1.5, 0.0, 0.0))[0]
    assert very_fast < 0


def test_braking_respects_arrival_radius_and_limits():
    spec = BrakingGuidanceSpec(arrival_radius_m=0.2)
    method = make_guidance(BRAKING, GOAL, braking_spec=spec)
    assert command(method, position=(GOAL[0] - 0.1, GOAL[1], GOAL[2])) == (0.0, 0.0, 0.0, 0.0)
    fast = command(method, position=(GOAL[0] - 2.0, GOAL[1], GOAL[2]),
                   velocity=(-2.0, 0.0, 0.0))
    assert math.hypot(fast[0], fast[1]) <= spec.max_horizontal_mps + 1e-9
    assert abs(fast[2]) <= spec.max_vertical_mps + 1e-9


def test_braking_vertical_profile_and_heading_rotation():
    spec = BrakingGuidanceSpec(deceleration_mps2=0.8, velocity_feedback_gain=0.2,
                               arrival_radius_m=0.02)
    method = make_guidance(BRAKING, (0.0, 2.0, 1.5), braking_spec=spec)
    quat = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))
    forward, left, up, _yaw = command(method, position=(0.0, 0.0, 0.75), quat=quat)
    assert forward > 0
    assert abs(left) < 1e-9
    assert up > 0
    low = command(make_guidance(BRAKING, (0.0, 0.0, 0.8), braking_spec=spec),
                  position=(0.0, 0.0, 0.75))
    assert low[2] > 0


@pytest.mark.parametrize('position,velocity', [
    ((math.nan, 0.0, 0.75), (0.0, 0.0, 0.0)),
    ((0.0, 0.0, 0.75), (math.inf, 0.0, 0.0)),
])
def test_nonfinite_observations_are_rejected(position, velocity):
    method = make_guidance(BRAKING, GOAL)
    with pytest.raises(ValueError):
        command(method, position=position, velocity=velocity)


@pytest.mark.parametrize('kwargs', [
    {'max_horizontal_mps': -1.0}, {'deceleration_mps2': 0.0},
    {'velocity_feedback_gain': -0.1}, {'arrival_radius_m': math.nan},
])
def test_invalid_braking_specs_rejected(kwargs):
    with pytest.raises(ValueError):
        BrakingGuidanceSpec(**kwargs)


def test_braking_method_is_deterministic_and_stateless():
    method = make_guidance(BRAKING, GOAL)
    first = command(method, position=(0.0, 0.0, 0.75))
    for _ in range(5):
        assert command(method, position=(0.0, 0.0, 0.75)) == first
