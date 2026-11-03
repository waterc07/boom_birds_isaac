"""Production geometry must not silently reuse legacy, off-center spheres."""
import copy
import math

import pytest

from boom_birds.evaluation import clearance
from boom_birds.sim.body_envelope import body_envelope_record


def body():
    return body_envelope_record((0.05, 0.04, 0.02), (0.0, 0.0, 0.015))


def test_robot_payload_uses_validated_reference_origin_sphere():
    envelope = clearance.build_robot_envelope(body_envelope=body())
    assert envelope['radius_m'] == pytest.approx(math.hypot(0.05, 0.04, 0.035))
    assert envelope['envelope_policy'] == 'reference_origin_v2'
    assert envelope['center_offset_m'] == [0.0, 0.0, 0.015]


def test_invalid_body_radius_is_rejected_instead_of_using_half_extents():
    record = body()
    record['sphere_about_origin']['radius_m'] = 0.001
    with pytest.raises(ValueError):
        clearance.build_robot_envelope(body_envelope=record)


def test_cuboid_diagonal_contains_all_eight_corners():
    envelope = clearance.build_obstacle_envelope(
        (0.4, 0.4, 0.6), envelope_policy='reference_origin_v2')
    assert envelope['radius_m'] == pytest.approx(math.hypot(0.2, 0.2, 0.3))
    assert envelope['radius_m'] > 0.3


def test_v2_clearance_resolver_preserves_full_envelope_policy():
    robot = clearance.build_robot_envelope(body_envelope=body())
    obstacle = clearance.build_obstacle_envelope(
        (0.4, 0.4, 0.6), envelope_policy='reference_origin_v2')
    record = clearance.build_clearance_record(
        (0.0, 0.0, 1.0), (2.0, 0.0, 1.0),
        {'valid': True, 'position_world_m': (1.0, 1.0, 1.0),
         'velocity_world_mps': (0.0, 0.0, 0.0)},
        robot_envelope=robot, obstacle_envelope=obstacle)
    assert record['schema_version'] == 'boom_birds.clearance.v2'
    assert record['envelopes']['robot']['radius_m'] == robot['radius_m']
    assert record['envelopes']['obstacle']['radius_m'] == obstacle['radius_m']
    assert record['metrics']['path_clearance_gap_sphere_m'] == pytest.approx(
        1.0 - robot['radius_m'] - obstacle['radius_m'])


def test_tampered_v2_payload_radius_is_not_silently_accepted():
    payload = clearance.build_robot_envelope(body_envelope=body())
    payload['radius_m'] = 0.001
    with pytest.raises(ValueError):
        clearance.build_clearance_record(
            (0, 0, 1), (2, 0, 1), {}, robot_envelope=payload)


def test_legacy_defaults_still_reproduce_historical_formula():
    assert clearance.build_obstacle_envelope((0.4, 0.4, 0.6))['radius_m'] == 0.3
