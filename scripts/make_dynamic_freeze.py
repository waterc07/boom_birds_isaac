"""Write the frozen dynamic-obstacle evaluation contract."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.supervisor import SupervisorConfig
from boom_birds.sim.map_contract import load_map_cases, load_map_contract

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--map-config', type=Path, required=True)
parser.add_argument('--local-config', type=Path, required=True)
parser.add_argument('--cases', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--code-commit', required=True)
args = parser.parse_args()

contract = load_map_contract(args.map_config, args.local_config)
cases = load_map_cases(args.cases, contract)
payload = json.loads(args.cases.read_text(encoding='utf-8'))
methods = ['follow_only', 'supervisor']
supervisor = SupervisorConfig()
freeze = {
    'schema_version': 'boom_birds.dynamic_freeze.v1',
    'evaluation_version': 'boom_birds.dynamic_eval.v1',
    'status': 'FROZEN',
    'frozen_at': datetime.now(timezone.utc).isoformat(),
    'code_commit': args.code_commit,
    'map_asset_id': contract.asset_id,
    'terrain_sha256': contract.terrain_sha256,
    'preview_sha256': contract.preview_sha256,
    'map_config_sha256': hashlib.sha256(args.map_config.read_bytes()).hexdigest(),
    'map_config_file': str(args.map_config),
    'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    'cases_file': str(args.cases),
    'methods': methods,
    'case_ids': [case.case_id for case in cases],
    'scenario_classes': {name: [case.case_id for case in cases
                                if case.scenario_class == name]
                         for name in ('A', 'B', 'C', 'D', 'E')},
    'counts': {method: len(cases) for method in methods},
    'total_episodes': len(cases) * len(methods),
    'supervisor': {
        'stop_distance_m': supervisor.stop_distance_m,
        'release_distance_m': supervisor.release_distance_m,
        'prediction_horizon_s': supervisor.prediction_horizon_s,
        'prediction_step_s': supervisor.prediction_step_s,
        'observation_max_age_s': supervisor.observation_max_age_s,
        'max_stale_s': supervisor.max_stale_s,
        'max_wait_s': supervisor.max_wait_s,
        'min_hold_s': supervisor.min_hold_s,
        'release_hold_s': supervisor.release_hold_s,
        'resume_hold_s': supervisor.resume_hold_s,
        'stop_speed_mps': supervisor.stop_speed_mps,
        'scope': 'PROPOSED_ORACLE_SIM',
    },
    'routes': payload.get('routes', []),
    'obstacle_model': 'KINEMATIC_CUBOID_WITH_REAL_COLLISION',
    'observation_model': 'ORACLE_POSITION_VELOCITY_WITH_DELAY_AND_DROPOUT',
    'regression': {
        'cases_file': 'configs/scenarios/map_cases_v2.json',
        'case_ids': ['route_south_R1', 'route_south_R2', 'route_south_R3',
                     'route_south_R4', 'route_north_R1', 'route_north_R2',
                     'route_north_R3', 'route_north_R4'],
        'episodes': 8,
    },
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + '\n',
                       encoding='utf-8')
print('DYNAMIC_FREEZE_WRITTEN ' + str(args.output), flush=True)
print(json.dumps({'cases': len(cases), 'methods': methods,
                  'total_episodes': freeze['total_episodes'],
                  'classes': {key: len(value) for key, value in
                              freeze['scenario_classes'].items()}}), flush=True)
