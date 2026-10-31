"""Freeze layered evaluation config, scenario hashes and thresholds."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.evaluation.episodes import EVALUATION_SCHEMA_ID_V2  # noqa: E402
from boom_birds.sim.layered import load_layered_manifest  # noqa: E402
from boom_birds.sim.reach import ReachSpec  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--manifest', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--frozen-at', required=True)
parser.add_argument('--timeout-s', type=float, default=20.0)
parser.add_argument('--min-valid-per-class', type=int, default=20)
parser.add_argument('--min-valid-total', type=int, default=100)
args = parser.parse_args()

config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
manifest = load_layered_manifest(args.manifest)
spec = ReachSpec()
freeze = {
    'schema_version': 'boom_birds.layered_freeze.v1',
    'frozen_at': args.frozen_at,
    'config': str(args.config),
    'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
    'scenario_manifest': str(args.manifest),
    'scenario_sha256': manifest['content_sha256'],
    'evaluation_version': EVALUATION_SCHEMA_ID_V2,
    'guidance': {
        name: {key: float(value) for key, value in values.items()}
        for name, values in config['guidance'].items()},
    'thresholds': {
        'success_distance_m': float(spec.success_distance_m),
        'success_speed_mps': float(spec.success_speed_mps),
        'hold_time_s': float(spec.hold_time_s),
        'timeout_s': float(args.timeout_s),
        'collision_height_m': float(spec.collision_height_m),
        'max_abs_position_m': float(spec.max_abs_position_m),
        'contact_threshold_n': 0.02,
        'evaluation_version': EVALUATION_SCHEMA_ID_V2,
    },
    'class_counts': {name: len(items) for name, items in manifest['classes'].items()},
    'min_valid_per_class': args.min_valid_per_class,
    'min_valid_total': args.min_valid_total,
    'notes': ('PROPOSED layered simulation evaluation; not a BB22:G4 acceptance freeze'),
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + '\n',
                       encoding='utf-8')
print('LAYERED_FREEZE_WRITTEN', args.output)
print('config_sha256', freeze['config_sha256'])
print('scenario_sha256', freeze['scenario_sha256'])
