"""Freeze the independent landmark evaluation before opening test results."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

INPUT_FILES = {
    'final': ('outputs/sensor_shadow/lm_independence',
              ('manifest.json', 'summary.json', 'run.complete.json')),
    'final_shadow': ('outputs/sensor_shadow/lm_independence_sensor',
                     ('observations.jsonl', 'summary.json')),
    'pilot_dev': ('outputs/sensor_shadow/lm_pilot',
                  ('manifest.json', 'summary.json', 'run.complete.json')),
    'pilot_shadow': ('outputs/sensor_shadow/lm_pilot_sensor',
                     ('observations.jsonl', 'summary.json')),
}
SOURCE_FILES = (
    'scripts/run_independent_landmark_eval.py',
    'scripts/verify_independent_landmark.py',
    'scripts/run_landmark_consumer.py',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path('configs/perception/independent_freeze_v1.json'))
    parser.add_argument('--code-commit', default=None)
    parser.add_argument('--working-tree', default='operator recorded')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('refusing overwrite: ' + str(args.output))
    labels_path = Path('configs/perception/landmark_independent_labels_v1.json')
    plan_path = Path('configs/perception/independence_plan_v2.json')
    baseline_template = Path('configs/perception/tower_template_v1.png')
    improved_meta = Path('configs/perception/independent_templates/templates_v1.json')
    improved_dir = improved_meta.parent
    labels = json.loads(labels_path.read_text(encoding='utf-8'))
    source = {}
    for path in sorted(Path('src').rglob('*.py')):
        source[path.as_posix()] = logical_sha(path)
    for name in SOURCE_FILES:
        source[name] = logical_sha(name)
    input_hashes = {}
    for key, (root, files) in INPUT_FILES.items():
        for name in files:
            path = Path(root) / name
            input_hashes[path.as_posix()] = sha(path)
    improved_meta_doc = json.loads(improved_meta.read_text(encoding='utf-8'))
    templates = []
    for entry in improved_meta_doc['entries']:
        templates.append({
            'template_id': entry['template_id'],
            'path': entry['path'],
            'sha256': sha(entry['path']),
            'source_image': entry['source_image'],
            'source_split': 'development',
            'anchor_fraction_xy': entry['anchor_fraction_xy'],
            'anchor_status': entry['anchor_status'],
        })
    payload = {
        'schema_version': 'dsh.independent_landmark_freeze.v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'code_commit': args.code_commit or subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'working_tree': args.working_tree,
        'source_hashes': source,
        'input': {
            'final_run': INPUT_FILES['final'][0],
            'final_shadow': INPUT_FILES['final_shadow'][0],
            'pilot_dev_run': INPUT_FILES['pilot_dev'][0],
            'pilot_shadow': INPUT_FILES['pilot_shadow'][0],
            'sensor_freeze_sources': 'formal sensor freeze + independent collection plan',
        },
        'input_hashes': input_hashes,
        'labels': {
            'path': labels_path.as_posix(),
            'sha256': sha(labels_path),
            'plan_path': plan_path.as_posix(),
            'plan_sha256': sha(plan_path),
            'train_episodes': sorted({x['family'] for x in labels['labels']
                                      if x['split'] == 'development'}),
            'test_families': sorted({x['family'] for x in labels['labels']
                                     if x['split'] == 'sealed_test'}),
            'development_frames': sum(1 for x in labels['labels']
                                      if x['split'] == 'development'),
            'test_frames': sum(1 for x in labels['labels']
                               if x['split'] == 'sealed_test'),
            'test_positives': sum(1 for x in labels['labels']
                                  if x['split'] == 'sealed_test' and x['present']),
            'test_negatives': sum(1 for x in labels['labels']
                                  if x['split'] == 'sealed_test' and not x['present']),
            'localization_subset': sum(1 for x in labels['labels']
                                       if x['localization_subset']),
            'iou_threshold': labels['iou_threshold_proposed'],
            'bearing_error_threshold_deg': labels['bearing_error_threshold_deg_proposed'],
        },
        'algorithms': {
            'baseline': {
                'name': 'old_single_template',
                'template_path': baseline_template.as_posix(),
                'template_sha256': sha(baseline_template),
                'threshold': 0.55,
                'scales': [0.5, 0.65, 0.8, 1.0, 1.15],
                'bearing_source': 'BBOX_CENTER',
                'allowed_age_ns': 250_000_000,
            },
            'improved': {
                'name': 'dev_multiview_anchor',
                'templates_meta': improved_meta.as_posix(),
                'templates_meta_sha256': sha(improved_meta),
                'templates': templates,
                'threshold': 0.65,
                'scales': [0.5, 0.65, 0.8, 1.0, 1.15],
                'bearing_source': 'TEMPLATE_ANCHOR_GREEN_LIGHT',
                'allowed_age_ns': 250_000_000,
                'improvements': ['multi_view_template_library',
                                 'template_anchor_bearing'],
            },
        },
        'templates_development_only': all(
            x['source_split'] == 'development' for x in templates),
        'test_not_used_for_templates_or_threshold': True,
        'expected': {
            'test_frame_denominator': 49,
            'test_positive_denominator': 27,
            'test_negative_denominator': 22,
            'localization_subset': 9,
            'shadow_only': True,
            'control_participation': 'NONE',
            'distance_available': False,
            'exposure_status': 'UNKNOWN',
            'algorithm_effect_may_fail': True,
            'no_post_test_threshold_change': True,
        },
        'scope': 'natural tower; offline shadow; no control/localization; no Gate claim',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print('FREEZE', args.output, sha(args.output))
    print('code_commit', payload['code_commit'])
    print('test frames', payload['labels']['test_frames'],
          'positives', payload['labels']['test_positives'],
          'localization', payload['labels']['localization_subset'])
    print('templates_dev_only', payload['templates_development_only'])


if __name__ == '__main__':
    main()
