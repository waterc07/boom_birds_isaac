"""Deterministic randomization, manifest hashing and stratification of scenarios."""
import json
import math

import pytest

from boom_birds.sim.scenarios import (
    SCENARIO_SCHEMA_ID,
    RandomizationSpec,
    Scenario,
    bearing_bin_for,
    build_scenario_manifest,
    distance_bin_for,
    generate_scenarios,
    load_scenario_manifest,
    manifest_sha256,
    scenarios_from_manifest,
    write_scenario_manifest,
)


def test_generation_is_deterministic_and_prefix_stable():
    ten = generate_scenarios(10, base_seed=2026)
    again = generate_scenarios(10, base_seed=2026)
    five = generate_scenarios(5, base_seed=2026)
    assert ten == again
    assert five == ten[:5]
    other = generate_scenarios(10, base_seed=2027)
    assert other != ten


def test_generated_scenarios_respect_ranges_and_constraints():
    spec = RandomizationSpec()
    scenarios = generate_scenarios(30, base_seed=3000, spec=spec)
    assert len(scenarios) == 30
    assert len({item.scenario_id for item in scenarios}) == 30
    for item in scenarios:
        assert spec.start_xy_range_m[0] <= item.start_position_world_m[0] <= spec.start_xy_range_m[1]
        assert spec.start_xy_range_m[0] <= item.start_position_world_m[1] <= spec.start_xy_range_m[1]
        assert spec.start_z_range_m[0] <= item.start_position_world_m[2] <= spec.start_z_range_m[1]
        assert -math.pi <= item.start_yaw_rad <= math.pi
        assert spec.goal_xy_range_m[0][0] <= item.goal_position_world_m[0] <= spec.goal_xy_range_m[0][1]
        assert spec.goal_xy_range_m[1][0] <= item.goal_position_world_m[1] <= spec.goal_xy_range_m[1][1]
        assert spec.goal_z_range_m[0] <= item.goal_position_world_m[2] <= spec.goal_z_range_m[1]
        assert spec.min_goal_distance_m <= item.distance_m <= spec.max_goal_distance_m
        assert item.distance_bin in ('short', 'medium', 'long')
        assert item.bearing_bin in ('front', 'side', 'rear')


def test_bins_follow_documented_thresholds():
    assert distance_bin_for(1.19) == 'short'
    assert distance_bin_for(1.25) == 'medium'
    assert distance_bin_for(1.85) == 'long'
    assert bearing_bin_for(0.0) == 'front'
    assert bearing_bin_for(math.pi / 2) == 'side'
    assert bearing_bin_for(math.pi) == 'rear'


def test_scenario_manifest_roundtrip_and_tamper_detection(tmp_path):
    spec = RandomizationSpec()
    scenarios = generate_scenarios(3, base_seed=4000, spec=spec)
    manifest = build_scenario_manifest(scenarios, spec=spec, base_seed=4000,
                                       generated_at='2026-10-31T17:00:00+08:00')
    assert manifest['schema_version'] == SCENARIO_SCHEMA_ID
    assert manifest['content_sha256'] == manifest_sha256(manifest)
    path = write_scenario_manifest(tmp_path / 'scenarios.json', manifest)
    loaded = load_scenario_manifest(path)
    assert scenarios_from_manifest(loaded) == scenarios
    tampered = json.loads(path.read_text(encoding='utf-8'))
    tampered['scenarios'][0]['goal_position_world_m'][0] += 0.5
    path.write_text(json.dumps(tampered), encoding='utf-8')
    with pytest.raises(ValueError):
        load_scenario_manifest(path)


@pytest.mark.parametrize('kwargs', [
    {'count': 0}, {'count': -1},
])
def test_invalid_generation_arguments(kwargs):
    with pytest.raises(ValueError):
        generate_scenarios(base_seed=1, **kwargs)


def test_invalid_randomization_specs_rejected():
    with pytest.raises(ValueError):
        RandomizationSpec(min_goal_distance_m=3.0, max_goal_distance_m=1.0)
    with pytest.raises(ValueError):
        RandomizationSpec(start_xy_range_m=(1.0, -1.0))
    with pytest.raises(ValueError):
        RandomizationSpec(max_goal_distance_m=0.0)


def test_scenario_record_validates_fields():
    with pytest.raises(ValueError):
        Scenario(scenario_id='', seed=0, start_position_world_m=(0, 0, 0.75),
                 start_yaw_rad=0.0, goal_position_world_m=(1, 0, 0.75),
                 distance_m=1.0, bearing_rad=0.0, distance_bin='short',
                 bearing_bin='front')
    with pytest.raises(ValueError):
        Scenario(scenario_id='s', seed=-1, start_position_world_m=(0, 0, 0.75),
                 start_yaw_rad=0.0, goal_position_world_m=(1, 0, 0.75),
                 distance_m=1.0, bearing_rad=0.0, distance_bin='short',
                 bearing_bin='front')
