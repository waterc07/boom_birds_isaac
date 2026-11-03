"""Freeze the geometry+green independent test before running detection."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

FILES = {
    'run': ('outputs/sensor_shadow/geo_test',
            ('manifest.json', 'summary.json', 'run.complete.json')),
    'shadow': ('outputs/sensor_shadow/geo_test_sensor',
               ('observations.jsonl', 'summary.json')),
}
SOURCE = ('scripts/run_geometry_test.py', 'scripts/verify_geometry_test.py')
ALGO = {
    'green_rgb': [100.0, 1.25, 1.15],
    'min_green_area': 10,
    'max_green_area': 300,
    'sat_min': 70,
    'sat_val_min': 35,
    'min_sat_pixels': 20,
    'min_bbox_side': 30,
    'min_edge_density': 0.03,
    'max_symmetry': 0.97,
    'max_anchor_top_fraction': 0.45,
    'ambiguity_ratio': 0.97,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path('configs/perception/geometry_test_freeze_v1.json'))
    parser.add_argument('--code-commit', default=None)
    parser.add_argument('--working-tree', default='operator recorded')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('refusing overwrite: ' + str(args.output))
    labels = Path('configs/perception/geometry_test_labels_v1.json')
    plan = Path('configs/perception/geometry_test_plan_v1.json')
    cases = Path('configs/scenarios/geometry_test_cases_v1.json')
    source = {}
    for path in sorted(Path('src').rglob('*.py')):
        source[path.as_posix()] = logical_sha(path)
    for name in SOURCE:
        source[name] = logical_sha(name)
    input_hashes = {}
    for root, names in FILES.values():
        for name in names:
            p = Path(root) / name
            input_hashes[p.as_posix()] = sha(p)
    labels_doc = json.loads(labels.read_text(encoding='utf-8'))
    labels_list = labels_doc['labels']
    payload = {
        'schema_version': 'dsh.geometry_test_freeze.v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'code_commit': args.code_commit or subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'working_tree': args.working_tree,
        'source_hashes': source,
        'input': {
            'run': FILES['run'][0], 'shadow': FILES['shadow'][0],
            'test_plan': plan.as_posix(), 'test_plan_sha256': sha(plan),
            'cases': cases.as_posix(), 'cases_sha256': sha(cases),
            'labels': labels.as_posix(), 'labels_sha256': sha(labels),
        },
        'input_hashes': input_hashes,
        'algorithm': {'name': 'green_light_seeded_tower_geometry',
                      'version': 'dsh.tower_green_geometry.v1',
                      **ALGO,
                      'score_is_probability': False,
                      'distance': 'UNAVAILABLE',
                      'anchor': 'green roof-light centroid',
                      'bbox': 'saturation-supported structure region'},
        'data': {
            'episodes': 4,
            'sealed_test_frames': len(labels_list),
            'positives': sum(x['present'] for x in labels_list),
            'negatives': sum(not x['present'] for x in labels_list),
            'localization_subset': sum(x['localization_subset'] for x in labels_list),
            'reference_evaluable': sum(bool(x.get('reference_point_px'))
                                       for x in labels_list
                                       if x['localization_subset']),
            'families': sorted({x['family'] for x in labels_list}),
            'sample_rule': 'route every20th + last12; static all accepted',
        },
        'evaluation': {
            'iou_threshold': 0.3,
            'bearing_error_threshold_deg': 5.0,
            'presence_tp': 'DETECTED on positive label',
            'bbox_tp': 'IoU>=0.3 on localization subset',
            'joint_tp': 'presence+bbox+anchor error<=5 where reference available',
            'success_coverage': 'detected positives / all positives',
            'joint_all_positive_rate': 'joint_tp / all positives',
            'unavailable_reference': 'retained in presence; reported separately',
            'old_baseline_anchor': 'not compared as same anchor',
        },
        'expected': {'no_post_test_tuning': True, 'failure_allowed': True,
                     'shadow_only': True, 'gate': False},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print('FREEZE', args.output, sha(args.output))
    print('code', payload['code_commit'])
    print('data', payload['data'])


if __name__ == '__main__':
    main()
