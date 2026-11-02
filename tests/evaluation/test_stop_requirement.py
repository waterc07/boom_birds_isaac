"""Tests for the stop-requirement boundary contract (2026-11-02 plan section 3).

Field contract (agreed with the runner/verifier work packages):

``{"schema_version", "model_id", "basis", "inputs", "terms",
   "required_clearance_m", "margin_to_threshold_m", "status",
   "status_reasons"}``

The brake model points must be derived from the real measured brake report.
Outside ``supported_speed_range_mps`` the distance/requirement/margin are null
and the status is UNSUPPORTED; no value is extrapolated.
"""
import hashlib
import json
import math
from pathlib import Path

import pytest

from boom_birds.evaluation import stop_requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / 'configs' / 'scenarios' / 'brake_model_v1.json'
SOURCE_PATH = (REPO_ROOT / 'docs' / 'reports' / 'map_eval' / 'brake'
               / 'verify_brake_final.json')
NOMINAL_TIER_SPEEDS_MPS = (0.3, 0.6, 0.9)
RECORD_KEYS = {
    'schema_version', 'model_id', 'basis', 'inputs', 'terms',
    'required_clearance_m', 'margin_to_threshold_m', 'status',
    'status_reasons',
}
INPUT_KEYS = {
    'robot_speed_mps', 'closing_speed_mps', 'observation_age_bound_s',
    'action_delay_s', 'action_ttl_remaining_s', 'robot_radius_m',
    'obstacle_radius_m', 'stop_threshold_m', 'proposed_margin_m',
}
TERM_KEYS = {
    'brake_distance_m', 'transport_reaction_m', 'observation_age_motion_m',
    'envelope_sum_m',
}


def _source_metrics():
    payload = json.loads(SOURCE_PATH.read_text(encoding='utf-8'))
    return payload['brake_metrics']


def _expected_model_points():
    """Independent derivation of the per-tier worst-case model points."""
    groups = {}
    for item in _source_metrics():
        speed = item['initial_speed_mps']
        nominal = min(NOMINAL_TIER_SPEEDS_MPS,
                      key=lambda candidate: abs(candidate - speed))
        groups.setdefault(nominal, []).append(item)
    points = []
    for nominal in sorted(groups):
        items = groups[nominal]
        points.append({
            'speed_mps': max(item['initial_speed_mps'] for item in items),
            'brake_distance_m': max(item['along_m'] for item in items),
            'stop_time_s': max(item['time_s'] for item in items),
        })
    return points


def _config():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def _interpolated_distance(model, speed_mps):
    points = model.points
    if speed_mps <= points[0].robot_speed_mps:
        return points[0].brake_distance_m
    if speed_mps >= points[-1].robot_speed_mps:
        return points[-1].brake_distance_m
    for left, right in zip(points, points[1:]):
        if left.robot_speed_mps <= speed_mps <= right.robot_speed_mps:
            ratio = ((speed_mps - left.robot_speed_mps)
                     / (right.robot_speed_mps - left.robot_speed_mps))
            return left.brake_distance_m + ratio * (
                right.brake_distance_m - left.brake_distance_m)
    raise AssertionError('speed not bracketed')


def _kwargs(**overrides):
    arguments = {
        'robot_speed_mps': 0.6,
        'closing_speed_mps': 0.2,
        'observation_age_bound_s': 0.25,
        'action_delay_s': 0.1,
        'action_ttl_remaining_s': 0.15,
        'robot_radius_m': 0.0677,
        'obstacle_radius_m': 0.3,
        'stop_threshold_m': 1.1,
    }
    arguments.update(overrides)
    return arguments


def test_stop_requirement_schema_constants():
    assert stop_requirement.STOP_REQUIREMENT_SCHEMA_VERSION == \
        'boom_birds.stop_requirement.v1'
    assert stop_requirement.BRAKE_MODEL_SCHEMA_VERSION == \
        'boom_birds.brake_model.v1'
    assert stop_requirement.DEFAULT_PROPOSED_MARGIN_M == 0.2
    assert stop_requirement.BASIS_ACTUATION == 'actuation'
    assert stop_requirement.BASIS_TRIGGER == 'trigger'


def test_brake_model_file_is_derived_from_the_measured_brake_report():
    payload = _config()
    source_bytes = SOURCE_PATH.read_bytes()
    assert payload['schema_version'] == stop_requirement.BRAKE_MODEL_SCHEMA_VERSION
    assert payload['model_id'] == 'brake_final4.v1'
    assert payload['source']['path'] == \
        'docs/reports/map_eval/brake/verify_brake_final.json'
    assert payload['source']['sha256'] == hashlib.sha256(source_bytes).hexdigest()
    assert payload['source']['measured_episode_count'] == 36
    assert len(_source_metrics()) == 36
    assert payload['interpolation'] == 'piecewise_linear_in_speed'
    assert payload['extrapolation'] == 'forbidden'
    expected = _expected_model_points()
    points = payload['points']
    assert len(points) == len(expected) == 3
    for stored, derived in zip(points, expected):
        assert stored['speed_mps'] == derived['speed_mps']
        assert stored['brake_distance_m'] == derived['brake_distance_m']
        assert stored['stop_time_s'] == derived['stop_time_s']
    speeds = [point['speed_mps'] for point in points]
    assert speeds == sorted(speeds)
    assert payload['supported_speed_range_mps'] == [speeds[0], speeds[-1]]
    assert payload['supported_speed_range_mps'][-1] == pytest.approx(
        0.8514284648524023, abs=1e-12)
    assert payload['supported_speed_range_mps'][0] == pytest.approx(
        0.24804050960284207, abs=1e-12)
    measured_speeds = [item['initial_speed_mps'] for item in _source_metrics()]
    assert payload['source']['measured_ranges']['speed_mps'] == [
        min(measured_speeds), max(measured_speeds)]


def test_brake_model_loads_from_the_default_repository_path():
    model = stop_requirement.load_brake_model()
    assert model.model_id == 'brake_final4.v1'
    assert model.schema_version == stop_requirement.BRAKE_MODEL_SCHEMA_VERSION
    assert len(model.points) == 3
    assert model.support_min_speed_mps == model.points[0].robot_speed_mps
    assert model.support_max_speed_mps == model.points[-1].robot_speed_mps
    assert model.support_min_speed_mps == pytest.approx(0.24804050960284207)
    assert model.support_max_speed_mps == pytest.approx(0.8514284648524023)
    assert model.source_sha256 == hashlib.sha256(
        SOURCE_PATH.read_bytes()).hexdigest()
    assert model.measured_episode_count == 36
    assert model.source_path == \
        'docs/reports/map_eval/brake/verify_brake_final.json'


def test_brake_distance_is_piecewise_linear_inside_the_supported_interval():
    model = stop_requirement.load_brake_model()
    for point in model.points:
        value, reason = model.brake_distance(point.robot_speed_mps)
        assert value == point.brake_distance_m
        assert reason is None
    middle = (model.points[0].robot_speed_mps
              + model.points[1].robot_speed_mps) / 2.0
    assert model.brake_distance(middle)[0] == pytest.approx(
        _interpolated_distance(model, middle), abs=1e-12)
    low = model.points[0].robot_speed_mps
    high = model.points[-1].robot_speed_mps
    speeds = [low + (high - low) * index / 60.0 for index in range(61)]
    distances = [model.brake_distance(speed)[0] for speed in speeds]
    assert all(left <= right for left, right in zip(distances, distances[1:]))


def test_above_supported_interval_is_unsupported_null_and_not_extrapolated():
    model = stop_requirement.load_brake_model()
    above = model.support_max_speed_mps + 0.001
    value, reason = model.brake_distance(above)
    assert value is None
    assert reason == 'ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT'
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(robot_speed_mps=0.9))
    assert result['status'] == 'UNSUPPORTED'
    assert 'ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT' in result['status_reasons']
    assert result['terms']['brake_distance_m'] is None
    assert result['required_clearance_m'] is None
    assert result['margin_to_threshold_m'] is None


def test_below_supported_interval_is_unsupported_null_and_not_extrapolated():
    model = stop_requirement.load_brake_model()
    below = model.support_min_speed_mps - 0.001
    value, reason = model.brake_distance(below)
    assert value is None
    assert reason == 'ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT'
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(robot_speed_mps=0.2))
    assert result['status'] == 'UNSUPPORTED'
    assert 'ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT' in result['status_reasons']
    assert result['terms']['brake_distance_m'] is None
    assert result['required_clearance_m'] is None
    assert result['margin_to_threshold_m'] is None


def test_record_field_contract_and_margin_formula():
    model = stop_requirement.load_brake_model()
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(), brake_model=model)
    assert set(result) == RECORD_KEYS
    assert set(result['inputs']) == INPUT_KEYS
    assert set(result['terms']) == TERM_KEYS
    assert result['schema_version'] == \
        stop_requirement.STOP_REQUIREMENT_SCHEMA_VERSION
    assert result['model_id'] == 'brake_final4.v1'
    assert result['basis'] == 'actuation'
    brake_distance = _interpolated_distance(model, 0.6)
    transport = 0.6 * 0.1
    observation_motion = 0.2 * 0.25
    envelope = 0.0677 + 0.3
    required = brake_distance + transport + observation_motion + envelope
    assert result['terms']['brake_distance_m'] == pytest.approx(
        brake_distance, abs=1e-12)
    assert result['terms']['transport_reaction_m'] == pytest.approx(
        transport, abs=1e-12)
    assert result['terms']['observation_age_motion_m'] == pytest.approx(
        observation_motion, abs=1e-12)
    assert result['terms']['envelope_sum_m'] == pytest.approx(envelope,
                                                              abs=1e-12)
    assert result['inputs']['proposed_margin_m'] == 0.2
    assert result['required_clearance_m'] == pytest.approx(required, abs=1e-12)
    assert result['margin_to_threshold_m'] == pytest.approx(
        1.1 - required - 0.2, abs=1e-12)
    assert result['status'] == 'SUPPORTED'


def test_non_blocking_markers_keep_status_supported():
    result = stop_requirement.evaluate_stop_requirement(**_kwargs())
    assert result['status'] == 'SUPPORTED'
    assert 'PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME' in \
        result['status_reasons']
    assert 'CLOSING_SPEED_NOT_MODELLED' not in result['status_reasons']
    assert result['required_clearance_m'] is not None


def test_missing_closing_speed_is_a_non_blocking_marker():
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(closing_speed_mps=None))
    assert result['status'] == 'SUPPORTED'
    assert result['status_reasons'] == [
        'CLOSING_SPEED_NOT_MODELLED',
        'PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME']
    assert result['inputs']['closing_speed_mps'] is None
    assert result['terms']['observation_age_motion_m'] is None
    assert result['required_clearance_m'] is None
    assert result['margin_to_threshold_m'] is None


def test_unknown_ttl_remaining_does_not_block():
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(action_ttl_remaining_s=None))
    assert not any('TTL' in reason for reason in result['status_reasons'])
    assert result['status'] == 'SUPPORTED'


def test_invalid_or_unknown_observation_age_is_unsupported():
    for overrides in ({'observation_valid': False},
                      {'observation_age_bound_s': None}):
        result = stop_requirement.evaluate_stop_requirement(
            **_kwargs(**overrides))
        assert result['status'] == 'UNSUPPORTED'
        assert 'OBSERVATION_AGE_UNKNOWN' in result['status_reasons']
        assert result['inputs']['observation_age_bound_s'] is None
        assert result['required_clearance_m'] is None
        assert result['margin_to_threshold_m'] is None


def test_expired_action_ttl_before_arrival_is_unsupported():
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(action_ttl_remaining_s=0.05))
    assert result['status'] == 'UNSUPPORTED'
    assert 'ACTION_TTL_EXPIRED_BEFORE_ARRIVAL' in result['status_reasons']
    # A UNSUPPORTED record carries no certified requirement value.
    assert result['required_clearance_m'] is None
    assert result['margin_to_threshold_m'] is None


def test_trigger_basis_does_not_add_transport_reaction_twice():
    measured = 0.5
    result = stop_requirement.evaluate_stop_requirement(
        **_kwargs(), basis='trigger', measured_stop_distance_m=measured)
    assert result['basis'] == 'trigger'
    assert result['terms']['brake_distance_m'] == measured
    assert result['terms']['transport_reaction_m'] == 0.0
    required = measured + 0.2 * 0.25 + 0.0677 + 0.3
    assert result['required_clearance_m'] == pytest.approx(required, abs=1e-12)
    assert result['margin_to_threshold_m'] == pytest.approx(
        1.1 - required - 0.2, abs=1e-12)
    alias = stop_requirement.evaluate_stop_requirement(
        **_kwargs(), basis='trigger_basis', measured_stop_distance_m=measured)
    assert alias['basis'] == 'trigger'
    with pytest.raises(ValueError):
        stop_requirement.evaluate_stop_requirement(**_kwargs(), basis='trigger')


def test_center_distance_is_never_used_as_path_clearance():
    result = stop_requirement.evaluate_stop_requirement(**_kwargs())
    serialized = json.dumps(result)
    assert 'center_distance' not in serialized
    assert 'path_clearance' not in serialized
    # The record only carries the clearance requirement terms above; no
    # center-distance alias exists in either the inputs or the terms.
    assert set(result['terms']) == TERM_KEYS


def test_missing_required_inputs_raise_value_errors():
    for overrides in ({'robot_radius_m': None},
                      {'obstacle_radius_m': None},
                      {'stop_threshold_m': None},
                      {'action_delay_s': None},
                      {'robot_speed_mps': -0.1}):
        with pytest.raises(ValueError):
            stop_requirement.evaluate_stop_requirement(**_kwargs(**overrides))
