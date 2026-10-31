"""Freeze the RMUC2027 map dynamics cases and thresholds."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.sim.map_contract import load_map_cases, load_map_contract

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--map-config', type=Path, required=True)
parser.add_argument('--local-config', type=Path, required=True)
parser.add_argument('--cases', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--frozen-at', default=None)
args = parser.parse_args()

contract = load_map_contract(args.map_config, args.local_config)
cases = load_map_cases(args.cases, contract)
counts = {kind: sum(case.repeats for case in cases if case.kind == kind)
          for kind in ('reach', 'takeoff_landing', 'contact')}
payload = {
    'schema_version': 'boom_birds.map_freeze.v1',
    'map_asset_id': contract.asset_id,
    'terrain_sha256': contract.terrain_sha256,
    'preview_sha256': contract.preview_sha256,
    'map_config_sha256': hashlib.sha256(args.map_config.read_bytes()).hexdigest(),
    'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    'case_ids': [case.case_id for case in cases],
    'counts': counts,
    'total_episodes': sum(counts.values()),
    'evaluation': {
        'version': contract.evaluator_version,
        'success_distance_m': 0.2,
        'success_speed_mps': 0.2,
        'hold_time_s': 0.5,
        'contact_force_threshold_n': 0.02,
        'takeoff_landing': {'hover_altitude_m': 1.0, 'hover_time_s': 1.0,
                            'landing_speed_max_mps': 0.25},
    },
    'code_commit': args.code_commit,
    'frozen_at': (args.frozen_at if args.frozen_at is not None
                  else datetime.now().astimezone().isoformat()),
    'notes': 'Frozen map dynamics cases; failures remain valid evidence.',
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                       encoding='utf-8')
print('MAP_FREEZE_WRITTEN ' + str(args.output))
print(json.dumps({'counts': counts, 'total_episodes': payload['total_episodes']}))
