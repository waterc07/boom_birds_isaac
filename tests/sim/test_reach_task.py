"""Minimal reach/stop task outcome tests (ORACLE state, no Isaac)."""
import math

import pytest

from boom_birds.sim.reach import (
    OUTCOME_COLLISION,
    OUTCOME_INVALID,
    OUTCOME_OUT_OF_BOUNDS,
    OUTCOME_RUNNING,
    OUTCOME_SUCCESS,
    OUTCOME_TIMEOUT,
    GuidanceSpec,
    ReachEvaluator,
    ReachSpec,
    guidance_command,
)

GOAL = (1.5, 1.0, 0.75)


def evaluator(dt_s=0.05, **overrides):
    values = dict(goal_position_world_m=GOAL)
    values.update(overrides)
    return ReachEvaluator(ReachSpec(**values), dt_s)


def near_goal(distance=0.29):
    return (GOAL[0] - distance, GOAL[1], GOAL[2])


def test_success_requires_continuous_hold():
    task = evaluator()
    decisions = [task.update(position_world_m=near_goal(), speed_mps=0.19, now_s=step * 0.05)
                 for step in range(9)]
    assert all(decision.outcome == OUTCOME_RUNNING for decision in decisions)
    final = task.update(position_world_m=near_goal(), speed_mps=0.19, now_s=9 * 0.05)
    assert final.outcome == OUTCOME_SUCCESS and final.terminated and not final.truncated
    assert final.hold_time_s == pytest.approx(0.5)


def test_hold_counter_resets_when_condition_breaks():
    task = evaluator()
    for step in range(5):
        task.update(position_world_m=near_goal(), speed_mps=0.19, now_s=step * 0.05)
    task.update(position_world_m=(GOAL[0] - 0.5, GOAL[1], GOAL[2]), speed_mps=0.19, now_s=0.3)
    assert task.hold_steps == 0
    decisions = [task.update(position_world_m=near_goal(), speed_mps=0.19, now_s=0.35 + step * 0.05)
                 for step in range(9)]
    assert all(decision.outcome == OUTCOME_RUNNING for decision in decisions)


def test_collision_beats_success_on_the_same_step():
    task = evaluator()
    for step in range(9):
        task.update(position_world_m=near_goal(), speed_mps=0.19, now_s=step * 0.05)
    decision = task.update(position_world_m=near_goal(), speed_mps=0.19,
                           now_s=0.45, collision=True)
    assert decision.outcome == OUTCOME_COLLISION and decision.terminated


def test_ground_contact_is_collision():
    decision = evaluator().update(position_world_m=(GOAL[0], GOAL[1], 0.05),
                                  speed_mps=0.1, now_s=0.05)
    assert decision.outcome == OUTCOME_COLLISION


def test_timeout_is_truncated_and_not_success():
    decision = evaluator().update(position_world_m=(0.0, 0.0, 0.75),
                                  speed_mps=0.0, now_s=20.0)
    assert decision.outcome == OUTCOME_TIMEOUT
    assert decision.truncated and decision.terminated


def test_invalid_states_are_explicit_not_zero_filled():
    assert evaluator().update(position_world_m=(math.nan, 0.0, 0.75),
                              speed_mps=0.0, now_s=0.05).reason == 'NONFINITE'
    out_of_bounds = evaluator(max_abs_position_m=2.0).update(
        position_world_m=(3.0, 0.0, 0.75), speed_mps=0.0, now_s=0.05)
    assert out_of_bounds.outcome == OUTCOME_OUT_OF_BOUNDS
    assert out_of_bounds.reason == 'OUT_OF_BOUNDS'


@pytest.mark.parametrize('kwargs', [
    {'goal_position_world_m': (1.0, 2.0)}, {'success_distance_m': 0.0},
    {'timeout_s': -1.0}, {'hold_time_s': math.nan},
])
def test_invalid_specs_rejected(kwargs):
    with pytest.raises(ValueError):
        ReachSpec(**kwargs)


def test_guidance_points_at_goal_and_is_limited():
    spec = GuidanceSpec()
    forward, left, up, yaw_rate = guidance_command(
        position_world_m=(0.0, 0.0, 0.75), quat_wxyz=(1.0, 0.0, 0.0, 0.0),
        goal_position_world_m=GOAL, spec=spec)
    assert math.hypot(forward, left) == pytest.approx(spec.max_horizontal_mps, abs=1e-9)
    assert forward > 0 and left > 0
    assert forward / left == pytest.approx(1.5, rel=1e-9)
    assert up == pytest.approx(0.0)
    assert yaw_rate == 0.0
    _f, _l, high_up, _y = guidance_command(
        position_world_m=(0.0, 0.0, 0.75), quat_wxyz=(1.0, 0.0, 0.0, 0.0),
        goal_position_world_m=(0.0, 0.0, 2.0), spec=spec)
    assert high_up == pytest.approx(spec.max_vertical_mps)
    _f, _l, low_up, _y = guidance_command(
        position_world_m=(0.0, 0.0, 0.75), quat_wxyz=(1.0, 0.0, 0.0, 0.0),
        goal_position_world_m=(0.0, 0.0, 0.0), spec=spec)
    assert low_up == pytest.approx(-spec.max_vertical_mps)


def test_guidance_rotates_with_heading():
    forward, left, _up, _yaw = guidance_command(
        position_world_m=(0.0, 0.0, 0.75),
        quat_wxyz=(math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)),
        goal_position_world_m=(1.5, 1.0, 0.75), spec=GuidanceSpec(gain_per_m=1.0,
                                                                  max_horizontal_mps=10.0))
    assert forward == pytest.approx(1.0, abs=1e-9)
    assert left == pytest.approx(-1.5, abs=1e-9)


def test_guidance_stops_inside_arrival_radius():
    assert guidance_command(position_world_m=(GOAL[0] - 0.2, GOAL[1], GOAL[2]),
                            quat_wxyz=(1.0, 0.0, 0.0, 0.0),
                            goal_position_world_m=GOAL,
                            spec=GuidanceSpec()) == (0.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        guidance_command(position_world_m=(0.0, 0.0, 0.75), quat_wxyz=(0.0, 0.0, 0.0, 0.0),
                         goal_position_world_m=GOAL, spec=GuidanceSpec())