"""Layered scenario contract v2: class specs, controlled strata, manifest."""
import json
import math

import pytest

from boom_birds.sim.layered import (
    LAYERED_SCENARIO_SCHEMA_ID,
    SCENE_CLASSES,
    ClassSpec,
    DegradationSpec,
    DisturbanceSpec,
    DynamicEntitySpec,
    LayeredScenario,
    ObstacleSpec,
    RandomizationSpecV2,
    CLASS_SPECS,
    STRATA_QUOTAS,
    bearing_bin_for_v2,
    build_layered_manifest,
    distance_bin_for_v2,
    generate_layered_scenarios,
    layered_manifest_sha256,
    layered_scenarios_from_manifest,
    load_layered_manifest,
    write_layered_manifest,
)


def test_scene_class_contract_is_complete():
    assert SCENE_CLASSES == ('A_clear', 'B_static', 'C_dynamic', 'D_observation',
                             'E_disturbance')
    for name in SCENE_CLASSES:
        spec = CLASS_SPECS[name]
        assert isinstance(spec, ClassSpec)
        assert spec.scene_class == name
        assert spec.capability_requirement
        assert spec.input_permission
        assert spec.expected_outcomes
        assert spec.boundary


def test_strata_quota_covers_all_cells_and_sums_to_25():
    assert sum(sum(row) for row in STRATA_QUOTAS) == 25
    assert len(STRATA_QUOTAS) == 3
    assert all(len(row) == 3 for row in STRATA_QUOTAS)
    assert all(value >= 2 for row in STRATA_QUOTAS for value in row)


def test_v2_bins_have_no_overlap_and_cover_edges():
    assert distance_bin_for_v2(0.79) == 'near'
    assert distance_bin_for_v2(1.19) == 'near'
    assert distance_bin_for_v2(1.2) == 'mid'
    assert distance_bin_for_v2(1.59) == 'mid'
    assert distance_bin_for_v2(1.6) == 'far'
    assert distance_bin_for_v2(2.0) == 'far'
    assert bearing_bin_for_v2(0.0) == 'front'
    assert bearing_bin_for_v2(math.radians(44)) == 'front'
    assert bearing_bin_for_v2(math.radians(46)) == 'side'
    assert bearing_bin_for_v2(math.radians(134)) == 'side'
    assert bearing_bin_for_v2(math.radians(136)) == 'rear'
    assert bearing_bin_for_v2(math.radians(-179)) == 'rear'


def test_generation_is_deterministic_and_quota_exact():
    first = generate_layered_scenarios('A_clear', 25, base_seed=7000)
    again = generate_layered_scenarios('A_clear', 25, base_seed=7000)
    assert first == again
    assert len(first) == 25
    assert len({item.scenario_id for item in first}) == 25
    counts = {}
    for item in first:
        key = (item.distance_bin, item.bearing_bin)
        counts[key] = counts.get(key, 0) + 1
    for row in range(3):
        for col in range(3):
            key = (('near', 'mid', 'far')[row], ('front', 'side', 'rear')[col])
            assert counts[key] == STRATA_QUOTAS[row][col]
    other = generate_layered_scenarios('A_clear', 25, base_seed=7001)
    assert other != first


@pytest.mark.parametrize('scene_class', SCENE_CLASSES)
def test_each_class_generates_valid_contract(scene_class):
    scenarios = generate_layered_scenarios(scene_class, 25, base_seed=7100)
    assert len(scenarios) == 25
    for item in scenarios:
        assert item.scene_class == scene_class
        assert 0.8 <= item.distance_m <= 2.0
        assert item.distance_bin == distance_bin_for_v2(item.distance_m)
        assert item.bearing_bin == bearing_bin_for_v2(item.bearing_rad)
        if scene_class == 'A_clear':
            assert not item.obstacles and item.kinematic_entity is None \
                and item.dynamic_entity is None and item.degradation is None \
                and item.disturbance is None
        if scene_class == 'B_static':
            assert len(item.obstacles) == 2
            assert all(obstacle.kind == 'static' for obstacle in item.obstacles)
        if scene_class == 'C_dynamic':
            assert item.kinematic_entity is not None
            assert item.dynamic_entity is not None
        if scene_class == 'D_observation':
            assert item.degradation is not None
            assert item.degradation.delay_steps >= 1
        if scene_class == 'E_disturbance':
            assert item.disturbance is not None
            assert item.disturbance.duration_s > 0


def test_initial_states_are_legal_and_do_not_penetrate_obstacles():
    for scene_class in ('B_static', 'C_dynamic'):
        for item in generate_layered_scenarios(scene_class, 25, base_seed=7200):
            for obstacle in item.obstacles:
                horizontal = math.dist(item.start_position_world_m[:2],
                                       obstacle.center_world_m[:2])
                assert horizontal > 0.35
            if item.dynamic_entity is not None:
                assert math.dist(item.start_position_world_m,
                                 item.dynamic_entity.center_world_m) > 0.35


def test_manifest_roundtrip_and_tamper_detection(tmp_path):
    by_class = {name: generate_layered_scenarios(name, 25, base_seed=7300)
                for name in SCENE_CLASSES}
    manifest = build_layered_manifest(by_class, spec=RandomizationSpecV2(),
                                      generated_at='2026-10-31T18:00:00+08:00')
    assert manifest['schema_version'] == LAYERED_SCENARIO_SCHEMA_ID
    assert manifest['content_sha256'] == layered_manifest_sha256(manifest)
    path = write_layered_manifest(tmp_path / 'layered.json', manifest)
    loaded = load_layered_manifest(path)
    assert layered_scenarios_from_manifest(loaded) == by_class
    tampered = json.loads(path.read_text(encoding='utf-8'))
    tampered['classes']['A_clear'][0]['goal_position_world_m'][0] += 0.1
    path.write_text(json.dumps(tampered), encoding='utf-8')
    with pytest.raises(ValueError):
        load_layered_manifest(path)


@pytest.mark.parametrize('kwargs', [
    {'position_noise_std_m': -1.0},
    {'velocity_noise_std_mps': math.nan},
    {'delay_steps': -1},
    {'dropout_probability': 1.5},
])
def test_degradation_spec_validation(kwargs):
    with pytest.raises(ValueError):
        DegradationSpec(**kwargs)


@pytest.mark.parametrize('kwargs', [
    {'force_body_n': (0.0, 0.0)},
    {'force_body_n': (math.nan, 0.0, 0.0)},
    {'duration_s': 0.0},
    {'start_s': -0.1},
])
def test_disturbance_spec_validation(kwargs):
    values = dict(force_body_n=(0.0, 0.0, 0.0), torque_body_nm=(0.0, 0.0, 0.0),
                  start_s=0.2, duration_s=1.0)
    values.update(kwargs)
    with pytest.raises(ValueError):
        DisturbanceSpec(**values)


def test_scenario_rejects_missing_class_payload():
    base = dict(scenario_id='x', seed=1,
                start_position_world_m=(0.0, 0.0, 0.75), start_yaw_rad=0.0,
                goal_position_world_m=(1.0, 0.0, 0.75), distance_m=1.0,
                bearing_rad=0.0, distance_bin='near', bearing_bin='front',
                obstacles=(), kinematic_entity=None, dynamic_entity=None,
                degradation=None, disturbance=None)
    with pytest.raises(ValueError):
        LayeredScenario(scene_class='B_static', **base)
    with pytest.raises(ValueError):
        LayeredScenario(scene_class='unknown', **base)
    assert LayeredScenario(scene_class='A_clear', **base).scene_class == 'A_clear'
