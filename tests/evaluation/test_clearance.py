"""Tests for the clearance geometry contract (2026-11-02 plan section 2).

Fields, envelope radius rule and the four separated geometric quantities are
pinned here before the implementation exists (failing-first regression).
"""
import math
import random

import pytest

from boom_birds.evaluation import clearance

ROBOT_HALF_EXTENTS_M = (0.05454223374277353, 0.03820826672017574,
                        0.013588040310423821)
OBSTACLE_SIZE_M = (0.4, 0.4, 0.6)
OBSTACLE_HALF_EXTENTS_M = (0.2, 0.2, 0.3)


def _rotation_matrix(rng):
    """Uniformly random rigid rotation matrix from a unit quaternion."""
    quaternion = [rng.gauss(0.0, 1.0) for _ in range(4)]
    norm = math.sqrt(sum(value * value for value in quaternion))
    w, x, y, z = [value / norm for value in quaternion]
    return (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
        (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
        (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
    )


def _apply(matrix, vector):
    return tuple(sum(matrix[row][column] * vector[column]
                     for column in range(3)) for row in range(3))


def _aabb_vertices(half_extents_m):
    return [(sx * half_extents_m[0], sy * half_extents_m[1],
             sz * half_extents_m[2])
            for sx in (-1.0, 1.0) for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)]


def _legacy_distance_point_segment(point, start, end):
    """Literal copy of the pre-change RouteSupervisor helper for regression."""
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(value * value for value in segment)
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = sum((point[index] - start[index]) * segment[index]
            for index in range(3)) / length_sq
    t = min(1.0, max(0.0, t))
    projection = [start[index] + segment[index] * t for index in range(3)]
    return math.dist(point, projection)


def test_box_conservative_sphere_radius_is_half_diagonal():
    radius = clearance.box_conservative_sphere_radius(ROBOT_HALF_EXTENTS_M)
    expected = math.sqrt(sum(value * value for value in ROBOT_HALF_EXTENTS_M))
    assert radius == expected
    assert radius == pytest.approx(0.0677, abs=1e-3)
    assert radius > max(ROBOT_HALF_EXTENTS_M)
    assert clearance.box_conservative_sphere_radius(OBSTACLE_HALF_EXTENTS_M) \
        == pytest.approx(math.sqrt(0.17), abs=0.0)


def test_random_rigid_rotations_keep_the_aabb_inside_the_conservative_sphere():
    radius = clearance.box_conservative_sphere_radius(ROBOT_HALF_EXTENTS_M)
    vertices = _aabb_vertices(ROBOT_HALF_EXTENTS_M)
    rng = random.Random(20261102)
    rotations = 0
    for _ in range(128):
        matrix = _rotation_matrix(rng)
        for vertex in vertices:
            rotated = _apply(matrix, vertex)
            norm = math.sqrt(sum(value * value for value in rotated))
            # Any rigid rotation about the box center maps the 8 vertices onto
            # vectors whose norms are unchanged, so the half diagonal bounds
            # them all.  The bound must be conservative for every rotation.
            assert norm <= radius + 1e-12
        rotations += 1
    assert rotations == 128


def test_max_half_extent_radius_is_not_conservative_for_the_aabb():
    half_extents_m = (0.2, 0.2, 0.3)
    max_half_extent = max(half_extents_m)
    conservative = clearance.box_conservative_sphere_radius(half_extents_m)
    assert conservative == pytest.approx(math.sqrt(0.17), abs=0.0)
    rng = random.Random(7)
    counterexamples = 0
    for _ in range(8):
        matrix = _rotation_matrix(rng)
        for vertex in _aabb_vertices(half_extents_m):
            rotated = _apply(matrix, vertex)
            norm = math.sqrt(sum(value * value for value in rotated))
            # The max-half-extent sphere cannot contain the box corners.
            assert norm > max_half_extent + 1e-6
            assert norm <= conservative + 1e-12
            counterexamples += 1
    assert counterexamples == 64


def test_point_to_segment_distance_matches_legacy_formula():
    samples = [
        ((0.0, 2.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),   # inside
        ((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),  # beyond start
        ((6.0, 0.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),   # beyond end
        ((1.0, 1.0, 3.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),   # degenerate
        ((2.5, -3.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
    ]
    rng = random.Random(11)
    for _ in range(100):
        samples.append((
            tuple(rng.uniform(-3.0, 3.0) for _ in range(3)),
            tuple(rng.uniform(-3.0, 3.0) for _ in range(3)),
            tuple(rng.uniform(-3.0, 3.0) for _ in range(3)),
        ))
    for point, start, end in samples:
        assert clearance.point_to_segment_distance(point, start, end) == \
            _legacy_distance_point_segment(point, start, end)
    assert clearance.point_to_segment_distance(
        (0.0, 2.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)) == 2.0
    assert clearance.point_to_segment_distance(
        (1.0, 1.0, 3.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)) == pytest.approx(2.0)


def test_predict_obstacle_positions_default_horizon_and_step():
    center = (1.0, 2.0, 3.0)
    velocity = (0.5, -0.2, 0.1)
    centers = clearance.predict_obstacle_positions(center, velocity)
    assert len(centers) == 11
    assert clearance.PREDICTION_HORIZON_S == 1.0
    assert clearance.PREDICTION_STEP_S == 0.1
    for index, predicted in enumerate(centers):
        t = index * clearance.PREDICTION_STEP_S
        expected = [center[axis] + velocity[axis] * t for axis in range(3)]
        assert predicted == expected
    assert centers[0] == list(center)


def test_predict_obstacle_positions_respects_custom_horizon():
    centers = clearance.predict_obstacle_positions(
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), horizon_s=0.5, step_s=0.25)
    assert len(centers) == 3
    assert [point[0] for point in centers] == [0.0, 0.25, 0.5]
    centers = clearance.predict_obstacle_positions(
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), horizon_s=1.5, step_s=1.0)
    assert len(centers) == 3
    with pytest.raises(ValueError):
        clearance.predict_obstacle_positions(
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), step_s=0.0)


def test_predicted_path_clearance_returns_prediction_and_min_index():
    result = clearance.predicted_path_clearance(
        (0.0, 0.0, 1.0), (2.0, 0.0, 1.0), (1.0, 2.0, 1.0), (0.0, -0.5, 0.0))
    assert set(result) == {
        'prediction_horizon_s', 'prediction_step_s',
        'obstacle_predicted_centers_world_m', 'point_distances_m',
        'min_index', 'path_clearance_m'}
    assert len(result['obstacle_predicted_centers_world_m']) == 11
    assert len(result['point_distances_m']) == 11
    expected_distances = [point[1] for point in
                          result['obstacle_predicted_centers_world_m']]
    assert result['point_distances_m'] == pytest.approx(expected_distances,
                                                        abs=1e-12)
    assert result['path_clearance_m'] == min(result['point_distances_m'])
    assert result['min_index'] == 10  # obstacle keeps closing to y=1.5
    assert result['path_clearance_m'] == pytest.approx(1.5, abs=1e-12)


def test_predicted_path_clearance_degenerate_target_uses_point_distance():
    result = clearance.predicted_path_clearance(
        (1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 3.0), (0.0, 0.0, 0.0))
    assert result['path_clearance_m'] == pytest.approx(2.0, abs=1e-12)
    assert len(set(result['point_distances_m'])) == 1


def _observation(**overrides):
    observation = {
        'valid': True, 'reason': 'ACCEPT',
        'age_s': 0.228, 'age_point_s': 0.2,
        'position_world_m': (1.0, 1.5, 1.0),
        'velocity_world_mps': (0.0, 0.0, 0.0),
    }
    observation.update(overrides)
    return observation


def _record(**overrides):
    arguments = {
        'robot_center_world_m': (0.0, 0.0, 1.0),
        'target_waypoint_world_m': (2.0, 0.0, 1.0),
        'observation': _observation(),
        'robot_velocity_world_mps': (0.1, 0.0, 0.0),
        'waypoint_index': 3,
        'robot_envelope': {'half_extents_m': ROBOT_HALF_EXTENTS_M,
                           'measured_prim': '/World/envs/env_0/Robot',
                           'source': 'measured_usd_aabb_at_runtime'},
        'obstacle_envelope': {'size_m': OBSTACLE_SIZE_M,
                              'source': 'case_obstacle_size'},
    }
    arguments.update(overrides)
    return clearance.build_clearance_record(**arguments)


def test_clearance_schema_constants():
    assert clearance.CLEARANCE_SCHEMA_VERSION == 'boom_birds.clearance.v1'
    assert clearance.CLEARANCE_ALGORITHM_ID == \
        'supervisor_predicted_path_clearance'
    assert clearance.CLEARANCE_ALGORITHM_VERSION == '1.0.0'
    assert clearance.CLEARANCE_UNITS == 'm'
    assert clearance.CLEARANCE_FRAME == 'world_ENU_Z_up'
    assert clearance.CLEARANCE_TIME_BASE == 'simulation_time_s'


def test_clearance_record_echoes_inputs_and_algorithm():
    record = _record()
    assert record['schema_version'] == clearance.CLEARANCE_SCHEMA_VERSION
    algorithm = record['algorithm']
    assert algorithm['id'] == clearance.CLEARANCE_ALGORITHM_ID
    assert algorithm['version'] == clearance.CLEARANCE_ALGORITHM_VERSION
    assert algorithm['units'] == 'm'
    assert algorithm['frame'] == 'world_ENU_Z_up'
    assert algorithm['time_base'] == 'simulation_time_s'
    assert algorithm['prediction_horizon_s'] == 1.0
    assert algorithm['prediction_step_s'] == 0.1
    assert 'point-to-segment' in algorithm['definition']
    inputs = record['inputs']
    assert inputs['robot_center_world_m'] == [0.0, 0.0, 1.0]
    assert inputs['robot_velocity_world_mps'] == [0.1, 0.0, 0.0]
    assert inputs['target_waypoint_world_m'] == [2.0, 0.0, 1.0]
    assert inputs['waypoint_index'] == 3
    assert inputs['obstacle_observed_center_world_m'] == [1.0, 1.5, 1.0]
    assert inputs['obstacle_observed_velocity_world_mps'] == [0.0, 0.0, 0.0]
    assert inputs['observation_age_point_s'] == 0.2
    assert inputs['observation_age_bound_s'] == 0.228
    assert inputs['observation_valid'] is True
    assert inputs['observation_reason'] == 'ACCEPT'


def test_clearance_record_prediction_field():
    record = _record()
    prediction = record['prediction']
    assert set(prediction) == {'obstacle_predicted_centers_world_m',
                               'point_distances_m', 'min_index'}
    assert len(prediction['obstacle_predicted_centers_world_m']) == 11
    assert len(prediction['point_distances_m']) == 11
    assert prediction['min_index'] == \
        prediction['point_distances_m'].index(min(prediction['point_distances_m']))
    assert record['metrics']['path_clearance_m'] == \
        min(prediction['point_distances_m'])


def test_clearance_record_keeps_four_geometric_quantities_distinct():
    record = _record()
    metrics = record['metrics']
    robot_radius = clearance.box_conservative_sphere_radius(
        ROBOT_HALF_EXTENTS_M)
    # Frozen obstacle envelope rule: max(case size) / 2.
    obstacle_radius = max(OBSTACLE_SIZE_M) / 2.0
    center_distance = math.dist((0.0, 0.0, 1.0), (1.0, 1.5, 1.0))
    assert metrics['center_distance_m'] == pytest.approx(center_distance,
                                                         abs=1e-12)
    assert metrics['envelope_gap_sphere_m'] == pytest.approx(
        center_distance - robot_radius - obstacle_radius, abs=1e-12)
    assert metrics['path_clearance_m'] == pytest.approx(1.5, abs=1e-12)
    assert metrics['path_clearance_gap_sphere_m'] == pytest.approx(
        1.5 - robot_radius - obstacle_radius, abs=1e-12)
    # The four quantities must not be substituted for one another.
    assert metrics['center_distance_m'] != pytest.approx(
        metrics['path_clearance_m'], abs=1e-6)
    assert metrics['envelope_gap_sphere_m'] != pytest.approx(
        metrics['path_clearance_gap_sphere_m'], abs=1e-6)
    assert metrics['path_clearance_m'] != pytest.approx(
        metrics['center_distance_m'], abs=1e-6)


def test_clearance_record_envelopes_follow_frozen_rules():
    record = _record()
    envelopes = record['envelopes']
    assert envelopes['robot']['kind'] == 'sphere_over_spawn_aabb_half_diagonal'
    assert envelopes['robot']['radius_m'] == \
        clearance.box_conservative_sphere_radius(ROBOT_HALF_EXTENTS_M)
    assert envelopes['robot']['aabb_half_extents_m'] == \
        list(ROBOT_HALF_EXTENTS_M)
    assert envelopes['robot']['measured_prim'] == '/World/envs/env_0/Robot'
    assert envelopes['robot']['source'] == 'measured_usd_aabb_at_runtime'
    assert envelopes['robot']['attitude_scope'] == \
        'any_rigid_rotation_about_center'
    assert 'limitation' in envelopes['robot']
    assert envelopes['obstacle']['kind'] == 'sphere_over_case_cuboid'
    # Frozen obstacle rule from the dynamic reports: max(size) / 2.
    assert envelopes['obstacle']['radius_m'] == max(OBSTACLE_SIZE_M) / 2.0
    assert envelopes['obstacle']['size_m'] == list(OBSTACLE_SIZE_M)
    assert envelopes['obstacle']['source'] == 'case_obstacle_size'
    # The robot AABB must not use the non-conservative max-half-extent radius.
    assert envelopes['robot']['radius_m'] != max(ROBOT_HALF_EXTENTS_M)
    assert envelopes['robot']['radius_m'] == pytest.approx(
        math.sqrt(sum(value * value for value in ROBOT_HALF_EXTENTS_M)),
        abs=1e-12)


def test_clearance_record_validity_and_applicability_when_valid():
    record = _record()
    assert record['validity'] == {'valid': True, 'reasons': []}
    assert record['applicability']['status'] == 'SUPPORTED'
    assert record['applicability']['reasons'] == []
    notes = ' '.join(record['applicability']['notes'])
    assert 'path clearance is not center distance' in notes


def test_clearance_record_invalid_observation_is_unsupported():
    record = _record(observation={
        'valid': False, 'reason': 'OBSERVATION_DROPOUT',
        'age_s': 0.0, 'age_point_s': 0.0,
        'position_world_m': None, 'velocity_world_mps': None})
    assert record['validity']['valid'] is False
    assert 'OBSERVATION_DROPOUT' in record['validity']['reasons']
    assert record['prediction'] == {
        'obstacle_predicted_centers_world_m': [],
        'point_distances_m': [], 'min_index': None}
    assert all(value is None for value in record['metrics'].values())
    assert record['applicability']['status'] == 'UNSUPPORTED'
    assert record['applicability']['reasons'] == record['validity']['reasons']


def test_clearance_record_invalid_target_is_unsupported():
    record = _record(target_waypoint_world_m=None)
    assert record['validity']['valid'] is False
    assert 'TARGET_INVALID' in record['validity']['reasons']
    assert record['metrics']['path_clearance_m'] is None


def test_clearance_record_explicit_invalid_override_for_stale_observation():
    record = _record(observation=_observation(age_s=0.4),
                     observation_valid=False,
                     validity_reasons=['OBSERVATION_AGE_EXCEEDS_LIMIT'])
    assert record['validity'] == {
        'valid': False, 'reasons': ['OBSERVATION_AGE_EXCEEDS_LIMIT']}
    assert record['inputs']['observation_valid'] is True
    assert record['prediction']['point_distances_m'] == []
    assert record['applicability']['status'] == 'UNSUPPORTED'


def test_clearance_record_default_envelopes_use_runtime_aabb_defaults():
    record = _record(robot_envelope=None, obstacle_envelope=None)
    robot = record['envelopes']['robot']
    obstacle = record['envelopes']['obstacle']
    assert robot['radius_m'] == clearance.box_conservative_sphere_radius(
        clearance.DEFAULT_ROBOT_AABB_HALF_EXTENTS_M)
    assert robot['measured_prim'] == clearance.DEFAULT_ROBOT_AABB_PRIM
    assert robot['source'] == clearance.DEFAULT_ROBOT_AABB_SOURCE
    assert obstacle['radius_m'] == pytest.approx(
        max(clearance.DEFAULT_OBSTACLE_SIZE_M) / 2.0, abs=0.0)
    assert obstacle['source'] == clearance.DEFAULT_OBSTACLE_ENVELOPE_SOURCE
