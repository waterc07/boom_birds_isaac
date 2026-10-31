"""Unit tests for the map contract and map-specific evaluators."""
import hashlib
import json
from pathlib import Path

import pytest

from boom_birds.evaluation.map_eval import MapReachEvaluator, MapReachSpec, TakeoffLandingEvaluator
from boom_birds.sim.map_contract import load_map_cases, load_map_contract


def _write_contract(tmp_path):
    root = tmp_path / 'assets_root'
    root.mkdir()
    preview = root / 'preview.usda'
    terrain = root / 'terrain.usdc'
    preview.write_text('preview\n')
    terrain.write_text('terrain\n')
    (root / 'local.yaml').write_text('asset_root: ' + str(root) + '\n')
    config = {
        'contract_version': 'boom_birds.map_contract.v1',
        'asset_id': 'test-map',
        'assets': {
            'preview_rel': 'preview.usda', 'terrain_rel': 'terrain.usdc',
            'preview_sha256': hashlib.sha256(preview.read_bytes()).hexdigest(),
            'terrain_sha256': hashlib.sha256(terrain.read_bytes()).hexdigest()},
        'coordinate_contract': {'units': 'm', 'meters_per_unit': 1.0,
                                'up_axis': 'Z', 'world_frame': 'X_EAST_Y_NORTH_Z_UP',
                                'body_frame': 'FLU'},
        'bounds_m': {'min': [-2.0, -2.0, -0.2], 'max': [2.0, 2.0, 2.0]},
        'evaluation': {'version': 'boom_birds.map_eval.v1'},
    }
    path = tmp_path / 'map.yaml'
    import yaml
    path.write_text(yaml.safe_dump(config))
    return path, root


def test_load_map_contract_verifies_hashes_and_paths(tmp_path):
    path, root = _write_contract(tmp_path)
    contract = load_map_contract(path, root / 'local.yaml')
    assert contract.asset_id == 'test-map'
    assert contract.terrain_path == root / 'terrain.usdc'
    assert contract.bounds_min_m == (-2.0, -2.0, -0.2)


def test_load_map_contract_rejects_hash_mismatch(tmp_path):
    path, root = _write_contract(tmp_path)
    (root / 'terrain.usdc').write_text('changed\n')
    with pytest.raises(ValueError):
        load_map_contract(path, root / 'local.yaml')


def test_load_map_cases_validates_schema(tmp_path):
    path, root = _write_contract(tmp_path)
    contract = load_map_contract(path, root / 'local.yaml')
    payload = {'schema_version': 'boom_birds.map_cases.v1', 'cases': [
        {'case_id': 'reach', 'kind': 'reach',
         'start_position_world_m': [0, 0, 0.5], 'start_yaw_rad': 0,
         'goal_position_world_m': [1, 0, 0.5], 'ground_z_m': 0.0,
         'timeout_s': 5.0, 'repeats': 2}]}
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(payload))
    cases = load_map_cases(path, contract)
    assert len(cases) == 1
    assert cases[0].kind == 'reach'


def test_map_reach_evaluator_success_and_collision():
    spec = MapReachSpec(goal_position_world_m=(1.0, 0.0, 0.5),
                        bounds_min_m=(-2.0, -2.0, -0.2),
                        bounds_max_m=(2.0, 2.0, 2.0), floor_z_m=-0.2,
                        timeout_s=5.0)
    evaluator = MapReachEvaluator(spec, dt_s=0.1)
    for index in range(5):
        decision = evaluator.update((1.0, 0.0, 0.5), 0.05, (index + 1) * 0.1)
    assert decision['outcome'] == 'SUCCESS'
    evaluator.reset()
    decision = evaluator.update((0.0, 0.0, 0.5), 0.0, 0.1, collision=True)
    assert decision['outcome'] == 'COLLISION'


def test_map_reach_evaluator_out_of_bounds_and_timeout():
    spec = MapReachSpec(goal_position_world_m=(1.0, 0.0, 0.5),
                        bounds_min_m=(-1.0, -1.0, -0.2),
                        bounds_max_m=(1.0, 1.0, 2.0), floor_z_m=-0.2,
                        timeout_s=1.0)
    evaluator = MapReachEvaluator(spec, dt_s=0.1)
    assert evaluator.update((5.0, 0.0, 0.5), 0.0, 0.1)['outcome'] == 'OUT_OF_BOUNDS'
    evaluator.reset()
    decision = evaluator.update((0.0, 0.0, 0.5), 0.0, 2.0)
    assert decision['outcome'] == 'TIMEOUT'


class _Case:
    ground_z_m = 0.0
    hover_altitude_m = 1.0
    hover_time_s = 0.2
    landing_speed_max_mps = 0.25


def test_takeoff_landing_phase_machine_lands():
    evaluator = TakeoffLandingEvaluator(_Case(), timeout_s=5.0)
    assert evaluator.update((0.0, 0.0, 0.05), 0.0, 0.0, 0.0)['phase'] == 'GROUND'
    assert evaluator.update((0.0, 0.0, 0.95), 0.2, 0.0, 0.5)['phase'] == 'HOVER'
    assert evaluator.update((0.0, 0.0, 1.0), 0.0, 0.0, 0.9)['phase'] == 'DESCEND'
    decision = evaluator.update((0.0, 0.0, 0.05), 0.1, 0.5, 3.0)
    assert decision['outcome'] == 'SUCCESS'
    assert decision['reason'] == 'LANDED'


def test_takeoff_landing_times_out():
    evaluator = TakeoffLandingEvaluator(_Case(), timeout_s=1.0)
    decision = evaluator.update((0.0, 0.0, 0.05), 0.0, 0.0, 1.5)
    assert decision['outcome'] == 'TIMEOUT'
