"""Pre-run freeze for the shadow landmark consumer (no Isaac import)."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'dsh.landmark_consumer_freeze.v1'
TEMPLATE = Path('configs/perception/tower_template_v1.png')
LABELS = Path('configs/perception/landmark_labels_v1.json')
SENSOR_RUN = Path('outputs/sensor_shadow/formal6')
SHADOW_RUN = Path('outputs/sensor_shadow/formal6_sensor')
INPUT_FILES = ('manifest.json', 'summary.json', 'run.complete.json')
SOURCE_FILES = ('scripts/run_landmark_consumer.py',
                'scripts/verify_landmark_consumer.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(
        Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def git_head():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                          text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path('configs/perception/landmark_freeze_v1.json'))
    parser.add_argument('--code-commit', default=None)
    parser.add_argument('--working-tree', default='recorded by operator')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('refusing to overwrite existing freeze: ' + str(args.output))
    source = {}
    for path in sorted(Path('src').rglob('*.py')):
        source[path.as_posix()] = logical_sha(path)
    for name in SOURCE_FILES:
        source[name] = logical_sha(name)
    manifest = json.loads((SENSOR_RUN / 'manifest.json').read_text(
        encoding='utf-8'))
    input_hashes = {str((SENSOR_RUN / name).as_posix()): sha(SENSOR_RUN / name)
                    for name in INPUT_FILES}
    for name in ('observations.jsonl', 'summary.json'):
        input_hashes[str((SHADOW_RUN / name).as_posix())] = sha(SHADOW_RUN / name)
    labels = json.loads(LABELS.read_text(encoding='utf-8'))
    payload = {
        'schema_version': SCHEMA,
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'code_commit': args.code_commit or git_head(),
        'working_tree': args.working_tree,
        'hash_algorithm': {
            'name': 'sha256',
            'source_canonicalization': 'crlf_to_lf_v1',
            'payload_hash': 'raw_bytes',
        },
        'source_hashes': source,
        'input': {
            'sensor_run': SENSOR_RUN.as_posix(),
            'sensor_shadow_dir': SHADOW_RUN.as_posix(),
            'sensor_freeze_sha256': manifest.get('freeze', {}).get('sha256', ''),
            'sensor_code_commit': manifest.get('code_commit'),
            'sensor_completion': True,
            'sensor_error_file': False,
        },
        'input_hashes': input_hashes,
        'algorithm': {
            'name': 'tower_template_ncc',
            'detector_version': 'dsh.tower_template.v1',
            'template_path': TEMPLATE.as_posix(),
            'template_sha256': sha(TEMPLATE),
            'threshold': 0.55,
            'scales': [0.5, 0.65, 0.8, 1.0, 1.15],
            'score_definition': 'max_multiscale_TM_CCOEFF_NORMED_grayscale',
            'score_is_probability': False,
            'allowed_age_ns': 250_000_000,
            'capture_interval_ns': 250_000_000,
            'distance': 'UNAVAILABLE for detection boxes from one center depth',
        },
        'labels': {
            'path': LABELS.as_posix(),
            'sha256': sha(LABELS),
            'status': labels.get('status'),
            'train_episodes': sorted({item['episode'] for item in labels['labels']
                                      if item['split'] == 'train'}),
            'test_episodes': sorted({item['episode'] for item in labels['labels']
                                     if item['split'] == 'test'}),
            'train_frames': sum(1 for item in labels['labels']
                                if item['split'] == 'train'),
            'test_frames': sum(1 for item in labels['labels']
                               if item['split'] == 'test'),
            'pixel_or_bearing_labels': 'NOT_AVAILABLE_PRESENCE_ONLY',
        },
        'expected': {
            'test_frame_denominator': 36,
            'split_by_episode': True,
            'frame_denominator':'all labelled test frames, no deletion',
            'shadow_only': True,
            'control_participation': 'NONE',
            'exposure_status': 'UNKNOWN',
            'distance_available': False,
            'algorithm_effect': 'report TP/FP/FN/precision/recall; no minimum '
                                'recall is fabricated for PASS',
        },
        'scope': 'natural RoboMaster tower template, offline consumer; not '
                 'localization/avoidance/control',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print('LANDMARK_FREEZE_WRITTEN', args.output)
    print('code_commit', payload['code_commit'])
    print('freeze_sha', sha(args.output))
    print('template_sha', payload['algorithm']['template_sha256'])
    print('labels_sha', payload['labels']['sha256'])


if __name__ == '__main__':
    main()
