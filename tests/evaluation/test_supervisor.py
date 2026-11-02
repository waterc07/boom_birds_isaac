"""Tests for the stop-wait-resume supervisor state machine."""
import math

import pytest

from boom_birds.evaluation import clearance
from boom_birds.evaluation.supervisor import (_distance_point_segment,
                                              RouteSupervisor,
                                              SupervisorConfig)


def _obs(x, vx=0.0, valid=True, age=0.0):
    return {'valid': valid, 'age_s': age, 'position_world_m': (x, 0.0, 1.0),
            'velocity_world_mps': (vx, 0.0, 0.0), 'reason': 'ACCEPT'}


def _config(**overrides):
    values = dict(stop_distance_m=1.0, release_distance_m=1.5,
                  prediction_horizon_s=0.5, prediction_step_s=0.1,
                  observation_max_age_s=0.2, max_stale_s=1.0,
                  max_wait_s=2.0, min_hold_s=0.2, release_hold_s=0.3,
                  resume_hold_s=0.2, stop_speed_mps=0.1)
    values.update(overrides)
    return SupervisorConfig(**values)


def test_stop_wait_resume_on_temporary_obstacle():
    supervisor = RouteSupervisor(_config())
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    # Obstacle blocks ahead.
    decision = supervisor.update(robot, target, 0.5, _obs(0.8), 0.0, 0.05)
    assert decision['state'] == 'BRAKE'
    assert decision['action'] == 'STOP'
    for step in range(1, 10):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] in ('HOLD', 'WAIT')
    # Obstacle clears and stays clear long enough.
    for step in range(10, 30):
        decision = supervisor.update(robot, target, 0.0, _obs(3.0), step * 0.05, 0.05)
    assert decision['state'] in ('RESUME', 'FOLLOW')


def test_persistent_obstacle_aborts_after_max_wait():
    supervisor = RouteSupervisor(_config(max_wait_s=0.5))
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    for step in range(40):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'
    assert decision['abort_reason'] in ('MAX_WAIT_EXCEEDED', 'OBSERVATION_STALE')


def test_stale_observation_explicit_degradation():
    supervisor = RouteSupervisor(_config(max_stale_s=0.3))
    decision = supervisor.update((0, 0, 1), (2, 0, 1), 0.5, _obs(0.8, valid=False),
                                 0.0, 0.05)
    assert decision['state'] == 'DEGRADED'
    assert decision['action'] == 'STOP'
    for step in range(1, 10):
        decision = supervisor.update((0, 0, 1), (2, 0, 1), 0.0,
                                     _obs(0.8, valid=False), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'


def test_hysteresis_avoids_chatter_near_threshold():
    supervisor = RouteSupervisor(_config())
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    supervisor.update(robot, target, 0.5, _obs(0.9), 0.0, 0.05)
    transitions = supervisor.transitions
    # Oscillate just inside/outside stop distance; release requires sustained clearance.
    for step in range(1, 30):
        x = 0.9 if step % 2 else 1.2
        supervisor.update(robot, target, 0.0, _obs(x), step * 0.05, 0.05)
    assert supervisor.transitions - transitions <= 2
    assert supervisor.state in ('BRAKE', 'HOLD', 'WAIT')


def test_reset_clears_state_and_timers():
    supervisor = RouteSupervisor(_config())
    supervisor.update((0, 0, 1), (2, 0, 1), 0.5, _obs(0.8), 0.0, 0.05)
    supervisor.reset()
    assert supervisor.state == 'FOLLOW'
    assert supervisor.wait_s == 0.0
    assert supervisor.transitions == 0


def test_wait_timer_is_cumulative_and_not_reset_by_resume():
    supervisor = RouteSupervisor(_config(max_wait_s=1.0, release_hold_s=0.1))
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    # First blocked interval.
    for step in range(8):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] in ('HOLD', 'WAIT')
    first_wait = decision['wait_s']
    assert first_wait > 0.0
    # Clear long enough to enter RESUME/FOLLOW.
    for step in range(8, 20):
        decision = supervisor.update(robot, target, 0.0, _obs(3.0), step * 0.05, 0.05)
    assert decision['state'] in ('RESUME', 'FOLLOW')
    # Block again; cumulative wait must not be reset by the resume.
    for step in range(20, 45):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'
    assert decision['abort_reason'] == 'MAX_WAIT_EXCEEDED'
    assert decision['wait_s'] > first_wait


# ---------------------------------------------------------------------------
# Clearance refactor: old algorithm vs clearance.predicted_path_clearance
# ---------------------------------------------------------------------------

def _legacy_distance_point_segment(point, start, end):
    """Literal copy of the pre-refactor supervisor helper (equivalence oracle)."""
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(value * value for value in segment)
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = sum((point[index] - start[index]) * segment[index]
            for index in range(3)) / length_sq
    t = min(1.0, max(0.0, t))
    projection = [start[index] + segment[index] * t for index in range(3)]
    return math.dist(point, projection)


def _legacy_risk(robot_position, target, observation, horizon_s, step_s):
    steps = max(1, int(math.ceil(horizon_s / step_s)))
    predicted = []
    for step in range(steps + 1):
        t = step * step_s
        predicted.append([observation['position_world_m'][axis]
                          + observation['velocity_world_mps'][axis] * t
                          for axis in range(3)])
    distances = [_legacy_distance_point_segment(point, robot_position, target)
                 for point in predicted]
    return min(distances), distances


# Historical trigger sample reconstructed from
# docs/reports/map_eval/latency/analyze_latency_envelope.json
# (runs.A.brake_events[0], dynamic_B_south_0-supervisor-A, step 329, 16.5 s).
HISTORICAL_TRIGGER = {
    'robot_position_world_m': (-6.011325359344482, -6.183453559875488,
                               1.0006788969039917),
    'target_waypoint_world_m': (6.0, -6.2, 1.0),
    'observation': {
        'valid': True, 'reason': 'ACCEPT',
        'age_s': 0.2283, 'age_point_s': 0.2,
        'position_world_m': (-2.0, -14.2 + 0.4 * (16.5 - 0.2), 1.0),
        'velocity_world_mps': (0.0, 0.4, 0.0),
    },
    'clearance_reconstructed_m': 1.0910196175531948,
}


def _risk_samples():
    return [
        ((0.0, 0.0, 1.0), (2.0, 0.0, 1.0),
         {'position_world_m': (0.8, 0.5, 1.0),
          'velocity_world_mps': (0.1, -0.2, 0.0)}),
        ((0.0, 0.0, 1.0), (0.0, 2.0, 1.0),
         {'position_world_m': (1.5, 0.0, 1.0),
          'velocity_world_mps': (0.0, 0.3, 0.0)}),
        ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0),
         {'position_world_m': (1.0, 1.0, 3.0),
          'velocity_world_mps': (0.0, 0.0, 0.0)}),
        ((0.0, 0.0, 1.0), (-2.0, -1.0, 1.2),
         {'position_world_m': (0.5, -3.0, 0.8),
          'velocity_world_mps': (0.0, 0.5, 0.1)}),
        (HISTORICAL_TRIGGER['robot_position_world_m'],
         HISTORICAL_TRIGGER['target_waypoint_world_m'],
         HISTORICAL_TRIGGER['observation']),
    ]


def test_risk_uses_clearance_function_with_bitwise_identical_numbers():
    supervisor = RouteSupervisor(_config())
    for robot, target, observation in _risk_samples():
        legacy_min, legacy_distances = _legacy_risk(
            robot, target, observation, supervisor.config.prediction_horizon_s,
            supervisor.config.prediction_step_s)
        new_clearance, new_distances = supervisor._risk(robot, target,
                                                        observation)
        assert new_clearance == legacy_min
        assert new_distances == legacy_distances
        result = clearance.predicted_path_clearance(
            robot, target, observation['position_world_m'],
            observation['velocity_world_mps'],
            supervisor.config.prediction_horizon_s,
            supervisor.config.prediction_step_s)
        assert result['path_clearance_m'] == legacy_min
        assert result['point_distances_m'] == legacy_distances
    assert _distance_point_segment((0.0, 2.0, 0.0), (0.0, 0.0, 0.0),
                                   (5.0, 0.0, 0.0)) == 2.0


def test_historical_clearance_value_is_reproduced():
    supervisor = RouteSupervisor(_config(prediction_horizon_s=1.0,
                                         prediction_step_s=0.1,
                                         observation_max_age_s=0.3))
    decision = supervisor.update(
        HISTORICAL_TRIGGER['robot_position_world_m'],
        HISTORICAL_TRIGGER['target_waypoint_world_m'], 0.03,
        HISTORICAL_TRIGGER['observation'], 0.0, 0.05)
    assert decision['clearance_m'] == pytest.approx(
        HISTORICAL_TRIGGER['clearance_reconstructed_m'], abs=1e-12)
    record = decision['clearance_record']
    assert record['metrics']['path_clearance_m'] == decision['clearance_m']
    assert len(record['prediction']['obstacle_predicted_centers_world_m']) == 11


def test_decision_contains_clearance_record_with_contract_fields():
    supervisor = RouteSupervisor(_config())
    observation = {
        'valid': True, 'reason': 'ACCEPT', 'age_s': 0.05, 'age_point_s': 0.05,
        'position_world_m': (0.8, 1.0, 1.0),
        'velocity_world_mps': (0.0, 0.0, 0.0)}
    decision = supervisor.update(
        (0.0, 0.0, 1.0), (2.0, 0.0, 1.0), 0.5, observation, 0.0, 0.05,
        robot_velocity_world_mps=(0.5, 0.0, 0.0), waypoint_index=4)
    record = decision['clearance_record']
    assert record['schema_version'] == clearance.CLEARANCE_SCHEMA_VERSION
    assert record['algorithm']['id'] == clearance.CLEARANCE_ALGORITHM_ID
    assert record['inputs']['robot_center_world_m'] == [0.0, 0.0, 1.0]
    assert record['inputs']['robot_velocity_world_mps'] == [0.5, 0.0, 0.0]
    assert record['inputs']['target_waypoint_world_m'] == [2.0, 0.0, 1.0]
    assert record['inputs']['waypoint_index'] == 4
    assert record['inputs']['obstacle_observed_center_world_m'] == \
        [0.8, 1.0, 1.0]
    assert record['validity'] == {'valid': True, 'reasons': []}
    assert record['applicability']['status'] == 'SUPPORTED'
    assert record['metrics']['path_clearance_m'] == decision['clearance_m']
    assert record['metrics']['center_distance_m'] == pytest.approx(
        math.dist((0.0, 0.0, 1.0), (0.8, 1.0, 1.0)), abs=1e-12)
    robot_radius = clearance.box_conservative_sphere_radius(
        clearance.DEFAULT_ROBOT_AABB_HALF_EXTENTS_M)
    obstacle_radius = max(clearance.DEFAULT_OBSTACLE_SIZE_M) / 2.0
    assert record['envelopes']['robot']['radius_m'] == pytest.approx(
        robot_radius, abs=0.0)
    assert record['envelopes']['obstacle']['radius_m'] == pytest.approx(
        obstacle_radius, abs=0.0)
    assert record['metrics']['envelope_gap_sphere_m'] == pytest.approx(
        record['metrics']['center_distance_m'] - robot_radius
        - obstacle_radius, abs=1e-12)
    # clearance_m is still the production decision value (path clearance).
    assert decision['clearance_m'] == pytest.approx(1.0, abs=1e-12)


def test_stale_observation_records_unsupported_clearance_record():
    supervisor = RouteSupervisor(_config(observation_max_age_s=0.2))
    decision = supervisor.update((0.0, 0.0, 1.0), (2.0, 0.0, 1.0), 0.5,
                                 _obs(0.8, age=0.35), 0.0, 0.05)
    assert decision['state'] == 'DEGRADED'
    assert decision['clearance_m'] is None
    record = decision['clearance_record']
    assert record['validity']['valid'] is False
    assert 'OBSERVATION_AGE_EXCEEDS_LIMIT' in record['validity']['reasons']
    assert record['applicability']['status'] == 'UNSUPPORTED'
    assert record['prediction']['point_distances_m'] == []
    assert record['inputs']['robot_center_world_m'] == [0.0, 0.0, 1.0]


def test_invalid_observation_records_observation_reason():
    supervisor = RouteSupervisor(_config())
    observation = {'valid': False, 'reason': 'CLOCK_MAPPING_UNUSABLE',
                   'age_s': 0.0, 'position_world_m': None,
                   'velocity_world_mps': None}
    decision = supervisor.update((0.0, 0.0, 1.0), (2.0, 0.0, 1.0), 0.5,
                                 observation, 0.0, 0.05)
    record = decision['clearance_record']
    assert record['validity']['valid'] is False
    assert record['validity']['reasons'] == ['CLOCK_MAPPING_UNUSABLE']
    assert record['inputs']['observation_reason'] == 'CLOCK_MAPPING_UNUSABLE'

