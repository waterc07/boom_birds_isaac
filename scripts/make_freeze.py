"""Freeze guidance parameters, thresholds and scenario hashes before a final run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.sim.reach import ReachSpec  # noqa: E402
from boom_birds.sim.scenarios import load_scenario_manifest  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--final-scenarios', type=Path, required=True)
parser.add_argument('--tuning-scenarios', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--frozen-at', required=True)
parser.add_argument('--timeout-s', type=float, default=20.0)
parser.add_argument('--tuning-evidence', default='')
parser.add_argument('--selected-candidate', required=True)
parser.add_argument('--selection-criterion', required=True)
args = parser.parse_args()

config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
guidance = {
    name: {key: float(value) for key, value in values.items()}
    for name, values in config['guidance'].items()
}
spec = ReachSpec()
thresholds = {
    'success_distance_m': float(spec.success_distance_m),
    'success_speed_mps': float(spec.success_speed_mps),
    'hold_time_s': float(spec.hold_time_s),
    'timeout_s': float(args.timeout_s),
    'collision_height_m': float(spec.collision_height_m),
    'max_abs_position_m': float(spec.max_abs_position_m),
}
final_manifest = load_scenario_manifest(args.final_scenarios)
tuning_manifest = load_scenario_manifest(args.tuning_scenarios)
tuning_evidence = []
for path in [item for item in args.tuning_evidence.split(',') if item.strip()]:
    summary = json.loads(Path(path).read_text(encoding='utf-8'))
    tuning_evidence.append({
        'summary': path,
        'methods': {
            name: {
                'success': value['success'],
                'total_episodes': value['total_episodes'],
                'valid_episodes': value['valid_episodes'],
                'mean_time_to_goal_s': value['mean_time_to_goal_s'],
                'mean_final_distance_m': value['mean_final_distance_m'],
            }
            for name, value in summary['methods_summary'].items()
        },
    })
freeze = {
    'schema_version': 'boom_birds.freeze.v1',
    'frozen_at': args.frozen_at,
    'config': str(args.config),
    'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
    'final_scenarios': str(args.final_scenarios),
    'scenario_sha256': final_manifest['content_sha256'],
    'scenario_count': final_manifest['count'],
    'tuning_scenarios': str(args.tuning_scenarios),
    'tuning_scenario_sha256': tuning_manifest['content_sha256'],
    'guidance': guidance,
    'thresholds': thresholds,
    'tuning_evidence': tuning_evidence,
    'selected_candidate': args.selected_candidate,
    'selection_criterion': args.selection_criterion,
    'notes': ('PROPOSED parameters frozen before the final comparison; '
              'not a BB22:G4 acceptance freeze'),
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + '\n',
                       encoding='utf-8')
print('FREEZE_WRITTEN', args.output)
print('config_sha256', freeze['config_sha256'])
print('scenario_sha256', freeze['scenario_sha256'], 'count', freeze['scenario_count'])
