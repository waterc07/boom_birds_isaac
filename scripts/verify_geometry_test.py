"""Independent verifier for the frozen green+geometry test."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def iou(a, b):
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def bearing(p, intr):
    return math.atan2(float(p[0]) - float(intr[0][2]), float(intr[0][0]))


def angle_err(a, b):
    return abs(math.degrees((a - b + math.pi) % (2 * math.pi) - math.pi))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shadow', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    labels_doc = load(args.labels)
    labels = labels_doc['labels']
    results = load_jsonl(args.results / 'results.jsonl')
    by_frame = {r['input_frame_id']: r for r in results}
    checks = []
    failures = []

    def check(name, ok, detail):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})
        if not ok:
            failures.append({'name': name, 'detail': detail})

    for name, digest in (freeze.get('input_hashes') or {}).items():
        check('input:' + Path(name).name, Path(name).exists() and sha(name) == digest,
              name)
    check('labels_hash', sha(args.labels) == freeze['input']['labels_sha256'],
          'labels')
    check('plan_hash', sha('configs/perception/geometry_test_plan_v1.json')
          == freeze['input']['test_plan_sha256'], 'test plan')
    check('cases_hash', sha('configs/scenarios/geometry_test_cases_v1.json')
          == freeze['input']['cases_sha256'], 'cases')
    check('source_hashes', all(logical_sha(args.repo_root / p) == h
                               for p, h in freeze['source_hashes'].items()),
          'source hashes')
    check('completion', (args.run / 'run.complete.json').exists()
          and not (args.run / 'summary.error.txt').exists(), 'run completion')
    check('shadow_boundary',
          all(r['shadow_only'] and r['control_participation'] == 'NONE'
              for r in results), 'shadow/control')
    check('distance_unavailable',
          all(r['distance']['available'] is False for r in results), 'distance')
    check('time_unknown',
          all(r['capture_time_semantics']['exposure_time_status'] == 'UNKNOWN'
              for r in results), 'time')
    check('provenance',
          all(r['source']['payload_sha256'] and r['source']['generation']
              for r in results), 'provenance')
    check('test_frames_present',
          {x['frame_id'] for x in labels}.issubset(by_frame.keys()),
          'all test labels have results')
    check('test_split', all(x['split'] == 'sealed_test' for x in labels),
          'all labels sealed test')
    check('denominators',
          len(labels) == freeze['data']['sealed_test_frames']
          and sum(x['present'] for x in labels) == freeze['data']['positives']
          and sum(x['localization_subset'] for x in labels)
          == freeze['data']['localization_subset'], 'label denominators')

    tp = fp = fn = tn = unk = rej = 0
    per_family = {}
    localization = []
    for label in labels:
        result = by_frame[label['frame_id']]
        status = result['status']
        detected = status == 'DETECTED'
        unk += int(status == 'UNKNOWN')
        rej += int(status == 'REJECTED')
        fam = per_family.setdefault(label['family'], {
            'frames': 0, 'positives': 0, 'negatives': 0,
            'detected_positives': 0, 'false_positives': 0,
            'unknown': 0, 'rejected': 0})
        fam['frames'] += 1
        if label['present'] and detected:
            tp += 1; fam['detected_positives'] += 1
        elif label['present']:
            fn += 1
        elif detected:
            fp += 1; fam['false_positives'] += 1
        else:
            tn += 1
        fam['positives'] += int(label['present'])
        fam['negatives'] += int(not label['present'])
        fam['unknown'] += int(status == 'UNKNOWN')
        fam['rejected'] += int(status == 'REJECTED')
        if label.get('localization_subset') and label.get('bbox_xywh'):
            detection = result.get('extra', {}).get('detection', {})
            bbox = detection.get('bbox_xywh') if detected else None
            intr = result.get('camera_intrinsics')
            ref = label.get('reference_point_px')
            ref_bearing = bearing(ref, intr) if ref and intr else None
            pred_bearing = detection.get('bearing_rad') if detected else None
            berr = (angle_err(pred_bearing, ref_bearing)
                    if pred_bearing is not None and ref_bearing is not None else None)
            i = iou(bbox, label['bbox_xywh']) if bbox else 0.0
            bbox_tp = detected and i >= freeze['evaluation']['iou_threshold']
            joint = (bbox_tp and berr is not None
                     and berr <= freeze['evaluation']['bearing_error_threshold_deg'])
            localization.append({
                'frame_id': label['frame_id'], 'family': label['family'],
                'status': status, 'bbox': bbox, 'bbox_iou': i,
                'bearing_error_deg': berr, 'bbox_tp': bbox_tp,
                'joint_tp': joint, 'reference_available': ref is not None})
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    positives = sum(x['present'] for x in labels)
    bbox_rows = [x for x in localization if x['reference_available']]
    bbox_tp = sum(x['bbox_tp'] for x in bbox_rows)
    joint_tp = sum(x['joint_tp'] for x in bbox_rows)
    bearing_errors = [x['bearing_error_deg'] for x in bbox_rows
                      if x['bearing_error_deg'] is not None]
    report = {
        'schema_version': 'dsh.geometry_test_verify.v1',
        'status': 'PASS' if not failures else 'FAIL',
        'checks': checks,
        'failures': failures,
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'code_commit': freeze['code_commit']},
        'frame_metrics': {
            'total': total, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': precision, 'recall': recall,
            'unknown': unk, 'rejected': rej,
            'positive_success_coverage': (tp / positives if positives else None),
            'bbox_subset': len(bbox_rows), 'bbox_tp': bbox_tp,
            'joint_tp': joint_tp,
            'joint_all_positive_rate': (joint_tp / positives if positives else None),
            'bearing_error_mean_deg': (sum(bearing_errors) / len(bearing_errors)
                                       if bearing_errors else None),
            'bearing_error_median_deg': (sorted(bearing_errors)[len(bearing_errors) // 2]
                                         if bearing_errors else None),
            'bearing_error_max_deg': max(bearing_errors) if bearing_errors else None,
            'reference_unavailable': sum(not x['reference_available']
                                         for x in localization),
        },
        'per_family': per_family,
        'localization_rows': localization,
        'scope': 'shadow only; no region/localization/distance/control claim',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks),
                      'failures': failures[:3],
                      'metrics': report['frame_metrics'],
                      'per_family': per_family}, ensure_ascii=False))
    raise SystemExit(0 if not failures else 1)


if __name__ == '__main__':
    main()
