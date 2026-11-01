"""Tests for kinematic dynamic obstacle specs/observations."""
import pytest

from boom_birds.sim.dynamic_obstacle import DynamicObstacleSpec


def test_linear_obstacle_pose_and_observation():
    spec = DynamicObstacleSpec(
        obstacle_id='obs', size_m=(0.4, 0.4, 0.6), kind='linear',
        start_time_s=0.0, end_time_s=10.0,
        start_position_world_m=(0.0, 0.0, 1.0),
        velocity_world_mps=(0.5, 0.0, 0.0),
        observation_delay_s=0.1)
    position, velocity = spec.pose_at(2.0)
    assert position == pytest.approx((1.0, 0.0, 1.0))
    assert velocity == pytest.approx((0.5, 0.0, 0.0))
    observation = spec.observation_at(2.0)
    assert observation['valid'] is True
    assert observation['age_s'] == pytest.approx(0.1)
    assert observation['position_world_m'] == pytest.approx((0.95, 0.0, 1.0))


def test_oscillating_obstacle_and_observation_dropout():
    spec = DynamicObstacleSpec(
        obstacle_id='osc', size_m=(0.4, 0.4, 0.6), kind='oscillate',
        start_time_s=0.0, end_time_s=10.0,
        oscillation_center_world_m=(0.0, 0.0, 1.0),
        oscillation_axis_world=(0.0, 1.0, 0.0),
        oscillation_amplitude_m=0.5, oscillation_period_s=2.0,
        observation_dropout_windows_s=((0.1, 0.3),))
    position, velocity = spec.pose_at(0.5)
    assert position[1] == pytest.approx(0.5)
    assert abs(velocity[1]) < 1e-9
    assert spec.observation_at(0.2)['valid'] is False
    assert spec.observation_at(0.2)['reason'] == 'OBSERVATION_DROPOUT'
