"""Tests for the minimal waypoint runner."""
import pytest

from boom_birds.evaluation.waypoints import WaypointConfig, WaypointRunner


def _config():
    return WaypointConfig(arrival_radius_m=0.2, arrival_speed_mps=0.2,
                          intermediate_hold_s=0.1, final_hold_s=0.2,
                          segment_timeout_s=5.0, dt_s=0.05)


def test_waypoint_sequence_and_final_hold():
    runner = WaypointRunner([(0, 0, 1), (1, 0, 1), (2, 0, 1)], _config(),
                            timeout_s=20)
    decision = runner.update((0, 0, 1), 0.0, 0.0)
    assert decision['waypoint_index'] == 0
    # hold at first waypoint
    decision = runner.update((0, 0, 1), 0.0, 0.05)
    decision = runner.update((0, 0, 1), 0.0, 0.10)
    assert decision['waypoint_index'] == 1
    # reach second then final
    runner.update((1, 0, 1), 0.0, 0.2)
    runner.update((1, 0, 1), 0.0, 0.3)
    decision = runner.update((2, 0, 1), 0.0, 0.4)
    decision = runner.update((2, 0, 1), 0.0, 0.5)
    decision = runner.update((2, 0, 1), 0.0, 0.6)
    decision = runner.update((2, 0, 1), 0.0, 0.7)
    assert decision['outcome'] == 'SUCCESS'
    assert decision['waypoints_completed'] == 3


def test_waypoint_contact_and_timeout():
    runner = WaypointRunner([(0, 0, 1), (2, 0, 1)], _config(), timeout_s=2)
    assert runner.update((0, 0, 1), 0.0, 0.1, contact=True)['outcome'] == 'COLLISION'
    runner.reset()
    assert runner.update((0, 0, 1), 0.0, 2.1)['outcome'] == 'TIMEOUT'


def test_waypoint_segment_timeout():
    runner = WaypointRunner([(0, 0, 1), (2, 0, 1)], _config(), timeout_s=20)
    decision = runner.update((0, 0, 1), 0.0, 5.1)
    assert decision['outcome'] == 'TIMEOUT'
    assert decision['reason'] == 'WAYPOINT_TIMEOUT'


def test_reset_clears_index():
    runner = WaypointRunner([(0, 0, 1), (1, 0, 1)], _config())
    runner.index = 1
    runner.reset()
    assert runner.index == 0
    assert runner.outcome == 'RUNNING'
