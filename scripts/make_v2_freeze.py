"""Freeze one v2 execution evaluation plan."""
import argparse, hashlib, json
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
parser.add_argument('--kind', required=True)
parser.add_argument('--methods', default='supervisor')
args = parser.parse_args()
contract = load_map_contract(args.map_config, args.local_config)
cases = load_map_cases(args.cases, contract)
payload = json.loads(args.cases.read_text(encoding='utf-8'))
methods = [item.strip() for item in args.methods.split(',') if item.strip()]
supervisor = SupervisorConfig()
freeze = {
    'schema_version': 'boom_birds.v2_execution_freeze.v1',
    'evaluation_version': 'boom_birds.dynamic_eval.v2_execution',
    'kind': args.kind,
    'status': 'FROZEN',
    'frozen_at': datetime.now(timezone.utc).isoformat(),
    'code_commit': args.code_commit,
    'execution_path': 'v2',
    'map_asset_id': contract.asset_id,
    'terrain_sha256': contract.terrain_sha256,
    'preview_sha256': contract.preview_sha256,
    'map_config_sha256': hashlib.sha256(args.map_config.read_bytes()).hexdigest(),
    'map_config_file': str(args.map_config),
    'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    'cases_file': str(args.cases),
    'methods': methods,
    'case_ids': [case.case_id for case in cases],
    'counts': {method: len(cases) for method in methods},
    'total_episodes': len(cases) * len(methods),
    'fault_types': sorted({case.fault['type'] for case in cases if case.fault}),
    'supervisor': {
        'stop_distance_m': supervisor.stop_distance_m,
        'release_distance_m': supervisor.release_distance_m,
        'prediction_horizon_s': supervisor.prediction_horizon_s,
        'max_wait_s': supervisor.max_wait_s,
        'observation_max_age_s': supervisor.observation_max_age_s,
    },
    'simulated_px4_identity': True,
    'note': 'Simulation-only v2 gate; not a PX4 Sender or firmware validation.',
}
args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('V2_FREEZE_WRITTEN', args.kind, len(cases), len(cases) * len(methods))
