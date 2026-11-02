"""Tests for the body-envelope geometry contract (``boom_birds.body_envelope.v2``).

Failing-first regression for the U2 work package.  The previous round quoted a
robot envelope radius of 0.067966 m derived as the half diagonal of the spawn
AABB about the *AABB center*.  That value is only an around-origin radius when
the AABB center coincides with the robot reference origin; the contract here
pins the coverage fields, the around-origin radius rule, the legacy comparison
and the record validator before the implementation exists.
"""
import copy
import json
import math
import random

import pytest

from boom_birds.sim import body_envelope

HALF_EXTENTS_M = (0.05454223374277353, 0.03820826672017574, 0.013588040310423821)
# Radius quoted by the previous round handoff (half diagonal of the AABB).
QUOTED_PREVIOUS_RADIUS_M = 0.067966
OFFSET_M = (0.012, -0.007, 0.004)
ROBOT_PRIM = '/World/envs/env_0/Robot'
COLLISION_PATHS = (
    '/World/envs/env_0/Robot/collision',
    '/World/envs/env_0/Robot/m1/collision',
    '/World/envs/env_0/Robot/m2/collision',
)
VISUAL_PATHS = (
    '/World/envs/env_0/Robot/visual',
    '/World/envs/env_0/Robot/m1/visual',
)
SUB_BODIES = ('body', 'm1', 'm2', 'm3', 'm4')


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


def _bound(half_extents_m, center_offset_m):
    return math.sqrt(sum((abs(center_offset_m[axis]) + half_extents_m[axis]) ** 2
                         for axis in range(3)))


def _collision_coverage(**overrides):
    fields = dict(source=body_envelope.ENVELOPE_SOURCE_COLLISION_GEOMETRY,
                  collision_prim_paths=COLLISION_PATHS,
                  sub_bodies=SUB_BODIES,
                  limitations=('collision prim paths resolved via '
                               'UsdPhysics.CollisionAPI',))
    fields.update(overrides)
    return body_envelope.EnvelopeCoverage(**fields)


def _record(half_extents_m=HALF_EXTENTS_M, center_offset_m=OFFSET_M, coverage=None):
    return body_envelope.body_envelope_record(
        half_extents_m=half_extents_m,
        center_offset_m=center_offset_m,
        coverage=_collision_coverage() if coverage is None else coverage,
        measurement={'bbox_cache_purpose': ['default', 'render'],
                     'robot_root_prim': ROBOT_PRIM,
                     'frame': 'robot_reference_frame'})


# --------------------------------------------------------------------------- #
# aabb_from_points / aabb_corners / to_reference_frame
# --------------------------------------------------------------------------- #

def test_aabb_from_points_recovers_centered_box():
    points = body_envelope.aabb_corners(HALF_EXTENTS_M, (0.0, 0.0, 0.0))
    half_extents, center_offset = body_envelope.aabb_from_points(points)
    assert half_extents == pytest.approx(HALF_EXTENTS_M, abs=0.0)
    assert center_offset == pytest.approx((0.0, 0.0, 0.0), abs=0.0)


def test_aabb_from_points_recovers_offset_center():
    points = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    half_extents, center_offset = body_envelope.aabb_from_points(points)
    assert half_extents == pytest.approx(HALF_EXTENTS_M, abs=1e-15)
    assert center_offset == pytest.approx(OFFSET_M, abs=1e-15)


def test_aabb_from_points_accepts_world_points_and_reference_origin():
    origin = (0.3, -0.2, 1.0)
    world_points = [tuple(point[axis] + origin[axis] for axis in range(3))
                    for point in body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)]
    half_extents, center_offset = body_envelope.aabb_from_points(
        world_points, reference_origin_m=origin)
    assert half_extents == pytest.approx(HALF_EXTENTS_M, abs=1e-15)
    assert center_offset == pytest.approx(OFFSET_M, abs=1e-15)


def test_aabb_from_points_is_independent_of_point_order():
    points = list(body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M))
    shuffled = points[::-1] + points[:3]
    assert body_envelope.aabb_from_points(shuffled) == \
        body_envelope.aabb_from_points(points)


def test_aabb_from_points_rejects_empty_points():
    with pytest.raises(ValueError, match='must not be empty'):
        body_envelope.aabb_from_points([])


def test_aabb_from_points_rejects_non_three_dimensional_point():
    with pytest.raises(ValueError, match='three components'):
        body_envelope.aabb_from_points([(0.0, 0.0)])


def test_aabb_from_points_rejects_non_finite_coordinate():
    with pytest.raises(ValueError, match='finite'):
        body_envelope.aabb_from_points([(0.0, 0.0, float('nan'))])


def test_aabb_corners_are_the_eight_box_corners():
    corners = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    assert len(corners) == 8
    assert len({tuple(round(value, 12) for value in corner)
                for corner in corners}) == 8
    for corner in corners:
        for axis in range(3):
            assert abs(corner[axis] - OFFSET_M[axis]) == pytest.approx(
                HALF_EXTENTS_M[axis], abs=1e-15)


def test_to_reference_frame_inverts_translation_and_rotation():
    rng = random.Random(11)
    matrix = _rotation_matrix(rng)
    origin = (0.4, 0.1, -0.3)
    local_points = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    world_points = [tuple(_apply(matrix, point)[axis] + origin[axis]
                          for axis in range(3)) for point in local_points]
    recovered = body_envelope.to_reference_frame(
        world_points, origin_world_m=origin,
        rotation_world_from_reference=matrix)
    for got, expected in zip(recovered, local_points):
        assert got == pytest.approx(expected, abs=1e-12)


def test_world_aabb_inverse_transform_is_a_conservative_bound():
    rng = random.Random(12)
    matrix = _rotation_matrix(rng)
    origin = (0.5, -0.4, 0.9)
    true_corners = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    world_corners = [tuple(_apply(matrix, point)[axis] + origin[axis]
                           for axis in range(3)) for point in true_corners]
    minimums = [min(point[axis] for point in world_corners) for axis in range(3)]
    maximums = [max(point[axis] for point in world_corners) for axis in range(3)]
    world_aabb = body_envelope.aabb_corners(
        tuple((maximums[axis] - minimums[axis]) / 2.0 for axis in range(3)),
        tuple((maximums[axis] + minimums[axis]) / 2.0 for axis in range(3)))
    reference_corners = body_envelope.to_reference_frame(
        world_aabb, origin_world_m=origin,
        rotation_world_from_reference=matrix)
    half_extents, center_offset = body_envelope.aabb_from_points(reference_corners)
    # The inverse-transformed world AABB still contains the true geometry, so
    # the reduced half extents may only grow.
    for axis in range(3):
        assert half_extents[axis] >= HALF_EXTENTS_M[axis] - 1e-12
    # ... and the derived around-origin sphere contains every true corner.
    radius = _bound(half_extents, center_offset)
    assert max(math.dist((0.0, 0.0, 0.0), corner) for corner in true_corners) \
        <= radius + 1e-12


def test_body_envelope_from_world_aabb_identity_attitude_matches_input():
    origin = (0.5, -0.4, 0.9)
    world_center = tuple(origin[axis] + OFFSET_M[axis] for axis in range(3))
    record = body_envelope.body_envelope_from_world_aabb(
        HALF_EXTENTS_M, world_center, origin_world_m=origin,
        coverage=_collision_coverage(),
        measurement={'frame': 'robot_reference_frame'})
    assert record['aabb']['half_extents_m'] == pytest.approx(
        list(HALF_EXTENTS_M), abs=1e-15)
    assert record['aabb']['center_offset_m'] == pytest.approx(
        list(OFFSET_M), abs=1e-15)
    assert record['sphere_about_origin']['radius_m'] == pytest.approx(
        _bound(HALF_EXTENTS_M, OFFSET_M), abs=1e-15)


def test_body_envelope_from_world_aabb_rotated_attitude_stays_conservative():
    rng = random.Random(13)
    matrix = _rotation_matrix(rng)
    origin = (0.2, 0.7, -0.5)
    true_corners = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    world_corners = [tuple(_apply(matrix, corner)[axis] + origin[axis]
                           for axis in range(3)) for corner in true_corners]
    minimums = [min(point[axis] for point in world_corners) for axis in range(3)]
    maximums = [max(point[axis] for point in world_corners) for axis in range(3)]
    record = body_envelope.body_envelope_from_world_aabb(
        tuple((maximums[axis] - minimums[axis]) / 2.0 for axis in range(3)),
        tuple((maximums[axis] + minimums[axis]) / 2.0 for axis in range(3)),
        origin_world_m=origin, rotation_world_from_reference=matrix,
        coverage=_collision_coverage())
    radius = record['sphere_about_origin']['radius_m']
    assert radius >= _bound(HALF_EXTENTS_M, OFFSET_M) - 1e-12
    assert max(math.dist((0.0, 0.0, 0.0), corner)
               for corner in true_corners) <= radius + 1e-12


# --------------------------------------------------------------------------- #
# around-origin sphere rule
# --------------------------------------------------------------------------- #

def test_conservative_sphere_about_origin_radius_formula():
    sphere = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, OFFSET_M)
    assert sphere['radius_m'] == pytest.approx(_bound(HALF_EXTENTS_M, OFFSET_M), abs=1e-15)
    # The farthest AABB corner from the origin is exactly that radius.
    corner_distances = [math.dist((0.0, 0.0, 0.0), corner)
                        for corner in body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)]
    assert max(corner_distances) == pytest.approx(sphere['radius_m'], abs=1e-15)
    assert sphere['rule'] == body_envelope.SPHERE_ABOUT_ORIGIN_RULE


def test_conservative_sphere_about_origin_zero_offset_equals_half_diagonal():
    sphere = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, (0.0, 0.0, 0.0))
    assert sphere['radius_m'] == pytest.approx(
        math.sqrt(sum(value * value for value in HALF_EXTENTS_M)), abs=1e-15)


def test_conservative_sphere_about_origin_contains_rotated_corners():
    sphere = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, OFFSET_M)
    corners = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    rng = random.Random(5)
    for _ in range(64):
        matrix = _rotation_matrix(rng)
        for corner in corners:
            rotated = _apply(matrix, corner)
            assert math.dist((0.0, 0.0, 0.0), rotated) \
                <= sphere['radius_m'] + 1e-12


def test_conservative_sphere_about_origin_center_is_reference_origin():
    sphere = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, OFFSET_M)
    assert sphere['center_offset_m'] == [0.0, 0.0, 0.0]
    assert sphere['center_kind'] == 'robot_reference_origin'
    assert sphere['attitude_scope'] == \
        body_envelope.ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN
    assert sphere['aabb_center_offset_m'] == pytest.approx(list(OFFSET_M), abs=0.0)
    joined = ' '.join(sphere['proof_notes']).lower()
    assert 'rotation' in joined and 'origin' in joined


def test_conservative_sphere_about_origin_offset_sign_symmetry():
    positive = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, OFFSET_M)
    negative = body_envelope.conservative_sphere_about_origin(
        HALF_EXTENTS_M, tuple(-value for value in OFFSET_M))
    assert positive['radius_m'] == pytest.approx(negative['radius_m'], abs=0.0)
    for axis in range(3):
        single = [0.0, 0.0, 0.0]
        single[axis] = 0.01
        radius = body_envelope.conservative_sphere_about_origin(
            HALF_EXTENTS_M, single)['radius_m']
        assert radius == pytest.approx(_bound(HALF_EXTENTS_M, single), abs=1e-15)


@pytest.mark.parametrize('half_extents, offset', [
    ((0.1, -0.1, 0.1), (0.0, 0.0, 0.0)),
    ((0.1, 0.1), (0.0, 0.0, 0.0)),
    ((0.1, 0.1, 0.1), (0.0, float('inf'), 0.0)),
])
def test_conservative_sphere_about_origin_rejects_invalid_input(half_extents, offset):
    with pytest.raises(ValueError):
        body_envelope.conservative_sphere_about_origin(half_extents, offset)


# --------------------------------------------------------------------------- #
# legacy AABB-center sphere and comparison with the previous rule
# --------------------------------------------------------------------------- #

def test_sphere_about_aabb_center_is_half_diagonal():
    sphere = body_envelope.sphere_about_aabb_center(HALF_EXTENTS_M, OFFSET_M)
    assert sphere['radius_m'] == pytest.approx(
        math.sqrt(sum(value * value for value in HALF_EXTENTS_M)), abs=1e-15)
    assert sphere['rule'] == body_envelope.SPHERE_ABOUT_AABB_CENTER_RULE
    assert sphere['center_kind'] == 'aabb_center'
    assert sphere['center_offset_m'] == pytest.approx(list(OFFSET_M), abs=0.0)
    assert sphere['attitude_scope'] == body_envelope.ATTITUDE_SCOPE_AABB_CENTER_ONLY
    assert any('around-origin' in limitation.lower()
               for limitation in sphere['limitations'])


def test_sphere_about_aabb_center_is_not_an_around_origin_radius():
    legacy = body_envelope.sphere_about_aabb_center(HALF_EXTENTS_M, OFFSET_M)
    corrected = body_envelope.conservative_sphere_about_origin(HALF_EXTENTS_M, OFFSET_M)
    assert legacy['radius_m'] < corrected['radius_m']
    corners = body_envelope.aabb_corners(HALF_EXTENTS_M, OFFSET_M)
    rng = random.Random(7)
    contained = []
    for _ in range(32):
        matrix = _rotation_matrix(rng)
        contained.append(all(math.dist((0.0, 0.0, 0.0), _apply(matrix, corner))
                             <= legacy['radius_m'] + 1e-12 for corner in corners))
    assert not all(contained)


def test_compare_with_previous_rule_equal_at_zero_offset():
    comparison = body_envelope.compare_with_previous_rule(
        HALF_EXTENTS_M, (0.0, 0.0, 0.0))
    assert comparison['previous_radius_m'] == pytest.approx(
        body_envelope.PREVIOUS_ROUND_SPHERE_RADIUS_M, abs=1e-15)
    assert comparison['previous_radius_m'] == pytest.approx(
        QUOTED_PREVIOUS_RADIUS_M, abs=1e-6)
    assert comparison['corrected_radius_m'] == pytest.approx(
        comparison['previous_radius_m'], abs=1e-15)
    assert comparison['underestimate_m'] == pytest.approx(0.0, abs=1e-15)
    assert comparison['equal_within_tolerance'] is True


def test_compare_with_previous_rule_quantifies_underestimate():
    comparison = body_envelope.compare_with_previous_rule(HALF_EXTENTS_M, OFFSET_M)
    corrected = _bound(HALF_EXTENTS_M, OFFSET_M)
    previous = math.sqrt(sum(value * value for value in HALF_EXTENTS_M))
    assert comparison['previous_radius_m'] == pytest.approx(previous, abs=1e-15)
    assert comparison['corrected_radius_m'] == pytest.approx(corrected, abs=1e-15)
    assert comparison['underestimate_m'] == pytest.approx(
        corrected - previous, abs=1e-15)
    assert comparison['underestimate_m'] > 0.0
    assert comparison['equal_within_tolerance'] is False
    assert comparison['underestimate_formula'] == \
        body_envelope.UNDERESTIMATE_FORMULA


def test_compare_with_previous_rule_is_per_axis():
    for axis in range(3):
        offset = [0.0, 0.0, 0.0]
        offset[axis] = 0.005
        comparison = body_envelope.compare_with_previous_rule(HALF_EXTENTS_M, offset)
        previous = math.sqrt(sum(value * value for value in HALF_EXTENTS_M))
        assert comparison['underestimate_m'] == pytest.approx(
            _bound(HALF_EXTENTS_M, offset) - previous, abs=1e-15)
        assert comparison['underestimate_m'] > 0.0


# --------------------------------------------------------------------------- #
# full record: schema, coverage, JSON round trip
# --------------------------------------------------------------------------- #

def test_body_envelope_record_schema_and_geometry_fields():
    record = _record()
    assert record['schema_version'] == 'boom_birds.body_envelope.v2'
    assert record['units'] == 'm'
    aabb = record['aabb']
    assert aabb['half_extents_m'] == pytest.approx(list(HALF_EXTENTS_M), abs=0.0)
    assert aabb['center_offset_m'] == pytest.approx(list(OFFSET_M), abs=0.0)
    assert aabb['lengths_m'] == pytest.approx(
        [2.0 * value for value in HALF_EXTENTS_M], abs=0.0)
    assert aabb['reference_origin'] == 'robot_root_prim_origin'
    assert record['sphere_about_origin']['rule'] == \
        body_envelope.SPHERE_ABOUT_ORIGIN_RULE
    assert record['sphere_about_origin']['radius_m'] == pytest.approx(
        _bound(HALF_EXTENTS_M, OFFSET_M), abs=1e-15)
    assert record['sphere_about_aabb_center']['rule'] == \
        body_envelope.SPHERE_ABOUT_AABB_CENTER_RULE
    assert record['production']['envelope_field'] == 'sphere_about_origin'
    assert record['production']['radius_m'] == pytest.approx(
        record['sphere_about_origin']['radius_m'], abs=0.0)
    assert record['production']['center_kind'] == 'robot_reference_origin'
    assert 'previous_rule_comparison' in record


def test_body_envelope_record_json_round_trip_then_validates():
    record = _record()
    reloaded = json.loads(json.dumps(record))
    assert reloaded['schema_version'] == record['schema_version']
    assert reloaded['sphere_about_origin']['radius_m'] == pytest.approx(
        record['sphere_about_origin']['radius_m'], abs=1e-15)
    assert reloaded['aabb']['center_offset_m'] == pytest.approx(
        OFFSET_M, abs=1e-15)
    body_envelope.validate_body_envelope_record(reloaded)


def test_body_envelope_record_coverage_fields():
    record = _record()
    coverage = record['coverage']
    assert coverage['source'] == body_envelope.ENVELOPE_SOURCE_COLLISION_GEOMETRY
    assert coverage['collision_prim_paths'] == list(COLLISION_PATHS)
    assert coverage['visual_prim_paths'] == []
    assert coverage['prim_paths'] == list(COLLISION_PATHS)
    assert coverage['sub_bodies'] == list(SUB_BODIES)
    assert coverage['joint_state_scope'] == \
        body_envelope.JOINT_STATE_SCOPE_FIXED_AT_MEASUREMENT
    assert coverage['limitations'] == list(record['limitations'])
    assert record['joint_state_scope'] == coverage['joint_state_scope']
    joined = ' '.join(record['limitations']).lower()
    assert 'not an all-attitude triangle-mesh sweep proof' in joined
    assert any('propeller' in limitation.lower()
               for limitation in record['limitations'])


def test_body_envelope_record_mixed_coverage_keeps_both_prim_sets():
    coverage = body_envelope.EnvelopeCoverage(
        source=body_envelope.ENVELOPE_SOURCE_MIXED,
        collision_prim_paths=COLLISION_PATHS,
        visual_prim_paths=VISUAL_PATHS,
        sub_bodies=SUB_BODIES,
        limitations=('world AABB merged over collision and visual prims',))
    record = _record(coverage=coverage)
    assert record['coverage']['collision_prim_paths'] == list(COLLISION_PATHS)
    assert record['coverage']['visual_prim_paths'] == list(VISUAL_PATHS)
    assert set(record['coverage']['prim_paths']) == set(COLLISION_PATHS) | set(VISUAL_PATHS)
    assert any('visual mesh' in limitation.lower()
               for limitation in record['limitations'])


def test_body_envelope_record_unknown_coverage_is_marked_in_limitations():
    record = _record(coverage=body_envelope.EnvelopeCoverage())
    assert record['coverage']['source'] == body_envelope.ENVELOPE_SOURCE_UNKNOWN
    assert any('unknown' in limitation.lower()
               for limitation in record['limitations'])


def test_body_envelope_record_accepts_coverage_mapping():
    record = _record(coverage={
        'source': 'visual_mesh',
        'visual_prim_paths': list(VISUAL_PATHS),
        'sub_bodies': ['body'],
        'limitations': ('visual-only bound',),
    })
    assert record['coverage']['source'] == body_envelope.ENVELOPE_SOURCE_VISUAL_MESH
    assert record['coverage']['visual_prim_paths'] == list(VISUAL_PATHS)
    assert any('collision' in limitation.lower()
               for limitation in record['limitations'])


def test_body_envelope_record_custom_joint_state_scope_is_mirrored():
    coverage = _collision_coverage(joint_state_scope='fixed_rotor_identity_pose')
    record = _record(coverage=coverage)
    assert record['joint_state_scope'] == 'fixed_rotor_identity_pose'
    assert record['coverage']['joint_state_scope'] == 'fixed_rotor_identity_pose'


# --------------------------------------------------------------------------- #
# validator
# --------------------------------------------------------------------------- #

def test_validate_accepts_valid_record():
    record = _record()
    assert body_envelope.validate_body_envelope_record(record) == record


def test_validate_rejects_understated_radius():
    tampered = copy.deepcopy(_record())
    tampered['sphere_about_origin']['radius_m'] *= 0.99
    tampered['production']['radius_m'] = tampered['sphere_about_origin']['radius_m']
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='SPHERE_ABOUT_ORIGIN_TOO_SMALL'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_aabb_center_radius_as_around_origin():
    tampered = copy.deepcopy(_record())
    legacy_radius = tampered['sphere_about_aabb_center']['radius_m']
    tampered['sphere_about_origin']['radius_m'] = legacy_radius
    tampered['production']['radius_m'] = legacy_radius
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='SPHERE_ABOUT_ORIGIN_TOO_SMALL'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_legacy_rule_id_in_around_origin_field():
    tampered = copy.deepcopy(_record())
    tampered['sphere_about_origin']['rule'] = \
        body_envelope.SPHERE_ABOUT_AABB_CENTER_RULE
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='SPHERE_ABOUT_ORIGIN_RULE'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_empty_collision_coverage_claim():
    tampered = copy.deepcopy(_record())
    tampered['coverage']['source'] = body_envelope.ENVELOPE_SOURCE_COLLISION_GEOMETRY
    tampered['coverage']['collision_prim_paths'] = []
    tampered['coverage']['visual_prim_paths'] = []
    tampered['coverage']['prim_paths'] = []
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='COVERAGE_PRIM_PATHS'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_visual_coverage_without_visual_paths():
    tampered = copy.deepcopy(_record())
    tampered['coverage']['source'] = body_envelope.ENVELOPE_SOURCE_VISUAL_MESH
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='COVERAGE_PRIM_PATHS'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_missing_limitations():
    tampered = copy.deepcopy(_record())
    tampered['limitations'] = []
    tampered['coverage']['limitations'] = []
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='COVERAGE_LIMITATIONS'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_missing_non_sweep_limitation():
    tampered = copy.deepcopy(_record())
    tampered['limitations'] = ['short note']
    tampered['coverage']['limitations'] = ['short note']
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='NON_SWEEP_LIMITATION'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_wrong_schema_version():
    tampered = copy.deepcopy(_record())
    tampered['schema_version'] = 'boom_birds.clearance.v1'
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='SCHEMA_VERSION'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_wrong_production_field():
    tampered = copy.deepcopy(_record())
    tampered['production']['envelope_field'] = \
        body_envelope.PRODUCTION_ENVELOPE_FIELD.replace(
            'sphere_about_origin', 'sphere_about_aabb_center')
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='PRODUCTION_RADIUS_FIELD'):
        body_envelope.validate_body_envelope_record(tampered)


def test_validate_rejects_production_radius_mismatch():
    tampered = copy.deepcopy(_record())
    tampered['production']['radius_m'] += 0.01
    with pytest.raises(body_envelope.BodyEnvelopeValidationError,
                       match='PRODUCTION_RADIUS_MISMATCH'):
        body_envelope.validate_body_envelope_record(tampered)


# --------------------------------------------------------------------------- #
# schema constants / enums
# --------------------------------------------------------------------------- #

def test_envelope_source_enum_members():
    assert set(body_envelope.ENVELOPE_SOURCES) == {
        'collision_geometry', 'visual_mesh', 'mixed', 'unknown'}
    with pytest.raises(ValueError):
        body_envelope.EnvelopeCoverage(source='lidar')


def test_coverage_rejects_bare_string_prim_paths():
    with pytest.raises(ValueError):
        body_envelope.EnvelopeCoverage(
            source=body_envelope.ENVELOPE_SOURCE_COLLISION_GEOMETRY,
            collision_prim_paths=COLLISION_PATHS[0])


def test_record_attitude_scope_is_rotation_about_reference_origin():
    record = _record()
    assert record['attitude_scope'] == \
        body_envelope.ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN
    assert record['sphere_about_origin']['attitude_scope'] == \
        record['attitude_scope']


def test_previous_round_constants_are_documented():
    assert body_envelope.PREVIOUS_ROUND_AABB_PRIM == '/World/envs/env_0/Robot'
    assert body_envelope.PREVIOUS_ROUND_HALF_EXTENTS_M == pytest.approx(
        HALF_EXTENTS_M, abs=0.0)
    assert body_envelope.PREVIOUS_ROUND_SPHERE_RADIUS_M == pytest.approx(
        QUOTED_PREVIOUS_RADIUS_M, abs=1e-6)
