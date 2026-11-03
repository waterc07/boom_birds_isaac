"""Independent verifier for baseline/improved landmark evaluation."""
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
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def bearing_from_point(point, intrinsics):
    if point is None or intrinsics is None:
        return None
    return math.atan2(float(point[0]) - float(intrinsics[0][2]), float(intrinsics[0][0]))


def angle_error_deg(a, b):
    if a is None or b is None:
        return None
    diff = (a - b + math.pi) % (2 * math.pi) - math.pi
    return abs(math.degrees(diff))


def evaluate(method, labels, results, freeze):
    result_by_frame = {r['input_frame_id']: r for r in results}
    test = [x for x in labels if x['split'] == 'sealed_test']
    tp = fp = fn = tn = rejected = unknown = 0
    per_family = {}
    localization_rows = []
    bearings = []
    for item in test:
        result = result_by_frame.get(item['frame_id'])
        status = result['status'] if result else 'MISSING'
        detected = status == 'DETECTED'
        rejected += int(status == 'REJECTED')
        unknown += int(status == 'UNKNOWN')
        if item['present'] and detected:
            tp += 1
        elif item['present']:
            fn += 1
        elif detected:
            fp += 1
        else:
            tn += 1
        fam = per_family.setdefault(item['family'], {
            'frames': 0, 'positives': 0, 'negatives': 0,
            'detected_positives': 0, 'false_positives': 0,
            'unknown': 0, 'rejected': 0})
        fam['frames'] += 1
        if item['present']:
            fam['positives'] += 1
            fam['detected_positives'] += int(detected)
        else:
            fam['negatives'] += 1
            fam['false_positives'] += int(detected)
        fam['unknown'] += int(status == 'UNKNOWN')
        fam['rejected'] += int(status == 'REJECTED')
        if item.get('localization_subset') and item.get('bbox_xywh'):
            pred_box = None
            pred_bearing = None
            if result and result.get('extra', {}).get('detection'):
                detection = result['extra']['detection']
                pred_box = detection.get('bbox_xywh')
                pred_bearing = detection.get('bearing_rad')
            iou_value = iou(pred_box, item['bbox_xywh']) if pred_box else 0.0
            ref_bearing = bearing_from_point(item.get('reference_point_px'),
                                             _intrinsics_for(result))
            err = (angle_error_deg(pred_bearing, ref_bearing)
                   if ref_bearing is not None else None)
            if err is not None:
                bearings.append(err)
            localization_rows.append({
                'frame_id': item['frame_id'], 'family': item['family'],
                'status': status, 'iou': iou_value,
                'bearing_error_deg': err,
                'ref_available': ref_bearing is not None,
                'localization_tp': bool(detected and iou_value >= freeze['labels']['iou_threshold']
                                       and err is not None
                                       and err <= freeze['labels']['bearing_error_threshold_deg']),
            })
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    loc_evaluable = [x for x in localization_rows if x['ref_available']]
    loc_tp = sum(1 for x in loc_evaluable if x['localization_tp'])
    loc_fn = len(loc_evaluable) - loc_tp
    bearing_errors = [x['bearing_error_deg'] for x in loc_evaluable
                      if x['bearing_error_deg'] is not None]
    return {
        'presence': {'total': total, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                     'precision': precision, 'recall': recall,
                     'rejected': rejected, 'unknown': unknown,
                     'rejection_rate': rejected / total if total else None},
        'localization': {
            'subset_with_bbox': len(localization_rows),
            'evaluable_with_reference': len(loc_evaluable),
            'tp': loc_tp, 'fn': loc_fn,
            'iou_threshold': freeze['labels']['iou_threshold'],
            'bearing_error_threshold_deg': freeze['labels']['bearing_error_threshold_deg'],
            'bearing_errors_deg': bearing_errors,
            'bearing_mean_deg': (sum(bearing_errors) / len(bearing_errors)
                                 if bearing_errors else None),
            'bearing_median_deg': (sorted(bearing_errors)[len(bearing_errors) // 2]
                                   if bearing_errors else None),
            'bearing_max_deg': max(bearing_errors) if bearing_errors else None,
            'rows': localization_rows,
        },
        'per_family': per_family,
        'method': method,
    }


def _intrinsics_for(result):
    if not result:
        return None
    return result.get('camera_intrinsics')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--baseline-results', type=Path, required=True)
    parser.add_argument('--improved-results', type=Path, required=True)
    parser.add_argument('--final-run', type=Path, required=True)
    parser.add_argument('--final-shadow', type=Path, required=True)
    parser.add_argument('--pilot-run', type=Path, required=True)
    parser.add_argument('--pilot-shadow', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    labels_doc = load(args.labels)
    labels = labels_doc['labels']
    baseline = load_jsonl(args.baseline_results / 'results.jsonl')
    improved = load_jsonl(args.improved_results / 'results.jsonl')
    checks = []
    failures = []

    def check(name, ok, detail):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})
        if not ok:
            failures.append({'name': name, 'detail': detail})

    check('freeze_hash', sha(args.freeze) == sha(args.freeze), 'freeze bytes')
    for name, digest in (freeze.get('input_hashes') or {}).items():
        check('input:' + Path(name).name, Path(name).exists() and sha(name) == digest,
              'input hash ' + name)
    check('labels_hash', sha(args.labels) == freeze['labels']['sha256'],
          'labels hash')
    check('source_hash', all(logical_sha(args.repo_root / p) == h
                             for p, h in freeze['source_hashes'].items()),
          'consumer/verifier source hashes')
    check('completion', (args.final_run / 'run.complete.json').exists()
          and not (args.final_run / 'summary.error.txt').exists(),
          'final run completion/error')
    check('templates_dev_only',
          freeze['templates_development_only'] is True,
          'all new templates from development split')
    test_frames = {x['frame_id'] for x in labels if x['split'] == 'sealed_test'}
    for method, rows in (('baseline', baseline), ('improved', improved)):
        check(method + '_result_count', len(rows) > 0, str(len(rows)))
        check(method + '_shadow', all(r['shadow_only'] and
                                      r['control_participation'] == 'NONE'
                                      for r in rows),
              'shadow/control boundary')
        check(method + '_distance_unavailable',
              all(r['distance']['available'] is False for r in rows),
              'distance unavailable')
        check(method + '_time_unknown',
              all(r['capture_time_semantics']['exposure_time_status'] == 'UNKNOWN'
                  for r in rows), 'exposure UNKNOWN')
        check(method + '_provenance',
              all(r.get('input_frame_id') and r['source']['payload_sha256']
                  for r in rows), 'frame/payload provenance')
        check(method + '_test_frames',
              test_frames.issubset({r['input_frame_id'] for r in rows}),
              'test label frames present in results')
    base_eval = evaluate('baseline', labels, baseline, freeze)
    imp_eval = evaluate('improved', labels, improved, freeze)
    check('baseline_denominator',
          base_eval['presence']['total'] == freeze['expected']['test_frame_denominator'],
          str(base_eval['presence']['total']))
    check('improved_denominator',
          imp_eval['presence']['total'] == freeze['expected']['test_frame_denominator'],
          str(imp_eval['presence']['total']))
    dev_families = {x['family'] for x in labels if x['split'] == 'development'}
    test_families = {x['family'] for x in labels if x['split'] == 'sealed_test'}
    check('split_by_family', dev_families.isdisjoint(test_families),
          'dev=' + repr(sorted(dev_families)) + ' test=' + repr(sorted(test_families)))
    report = {
        'schema_version': 'dsh.independent_landmark_verify.v1',
        'status': 'PASS' if not failures else 'FAIL',
        'checks': checks,
        'failures': failures,
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'code_commit': freeze['code_commit']},
        'baseline': base_eval,
        'improved': imp_eval,
        'delta': {
            'presence_tp': imp_eval['presence']['tp'] - base_eval['presence']['tp'],
            'presence_fp': imp_eval['presence']['fp'] - base_eval['presence']['fp'],
            'presence_fn': imp_eval['presence']['fn'] - base_eval['presence']['fn'],
            'recall': (None if None in (base_eval['presence']['recall'],
                                        imp_eval['presence']['recall'])
                       else imp_eval['presence']['recall'] - base_eval['presence']['recall']),
            'localization_tp': imp_eval['localization']['tp'] - base_eval['localization']['tp'],
        },
        'scope': 'shadow only; no control/Gate claim; small independent sample',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({'status': report['status'],
                      'checks': len(checks), 'failures': failures[:3],
                      'baseline': base_eval['presence'],
                      'improved': imp_eval['presence'],
                      'baseline_loc': {k: v for k, v in base_eval['localization'].items() if k != 'rows'},
                      'improved_loc': {k: v for k, v in imp_eval['localization'].items() if k != 'rows'}},
                     ensure_ascii=False))
    raise SystemExit(0 if not failures else 1)


if __name__ == '__main__':
    main()
