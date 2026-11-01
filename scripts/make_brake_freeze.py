"""Freeze the brake/post-fault experiment contract."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.sim.map_contract import load_map_contract
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--map-config', type=Path, required=True)
parser.add_argument('--local-config', type=Path, required=True)
parser.add_argument('--cases', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--code-commit', required=True)
args = parser.parse_args()
contract = load_map_contract(args.map_config, args.local_config)
payload = json.loads(args.cases.read_text(encoding='utf-8'))
freeze = {
    'schema_version': 'boom_birds.brake_freeze.v1',
    'evaluation_version': 'boom_birds.brake_eval.v1',
    'status': 'FROZEN',
    'frozen_at': datetime.now(timezone.utc).isoformat(),
    'code_commit': args.code_commit,
    'map_asset_id': contract.asset_id,
    'terrain_sha256': contract.terrain_sha256,
    'preview_sha256': contract.preview_sha256,
    'map_config_sha256': hashlib.sha256(args.map_config.read_bytes()).hexdigest(),
    'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    'cases_file': str(args.cases),
    'parameters': payload['parameters'],
    'counts': {'brake': len(payload['brake_cases']), 'fault': len(payload['fault_cases'])},
    'total_episodes': len(payload['brake_cases']) + len(payload['fault_cases']),
    'brake_case_ids': [item['case_id'] for item in payload['brake_cases']],
    'fault_case_ids': [item['case_id'] for item in payload['fault_cases']],
    'fault_types': sorted({item['fault_type'] for item in payload['fault_cases']}),
    'scope': 'CURRENT_SIM_MODEL_ONLY',
    'note': 'Not a real-aircraft safety envelope; not a PX4 failsafe validation.',
}
args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('BRAKE_FREEZE_WRITTEN', len(payload['brake_cases']), len(payload['fault_cases']))
