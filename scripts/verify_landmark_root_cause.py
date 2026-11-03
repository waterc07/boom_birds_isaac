"""Independent verifier for the offline landmark root-cause diagnostic.

Recomputes candidate selection, target-overlap candidates, threshold sweeps and
coordinate deltas from the exported candidates + labels + detector parameters.
It does not treat these 49 exposed frames as a sealed test.
"""
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


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def bearing(p, intr):
    return math.atan2(float(p[0]) - float(intr[0][2]), float(intr[0][0]))


def angle_deg(a, b, intr):
    return abs(math.degrees(bearing(a, intr) - bearing(b, intr)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic', type=Path, required=True)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--baseline-results', type=Path, required=True)
    parser.add_argument('--final-shadow', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    diag = load(args.diagnostic)
    labels = {x['frame_id']: x for x in load(args.labels)['labels']}
    rows = load_jsonl(args.candidates)
    checks = []
    failures = []

    def check(name, ok, detail):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})
        if not ok:
            failures.append({'name': name, 'detail': detail})

    check('diagnostic_scope', diag.get('status') ==
          'DIAGNOSTIC_OFFLINE_EXPOSED_DATA',
          diag.get('status'))
    check('input_hash_labels', diag['inputs']['labels_sha256'] == sha(args.labels),
          'labels hash')
    check('input_hash_old_template',
          Path('configs/perception/tower_template_v1.png').exists()
          and diag['inputs']['old_template_sha256'] == sha(
              'configs/perception/tower_template_v1.png'),
          'old template hash')
    check('input_hash_templates_meta',
          diag['inputs']['templates_meta_sha256'] == sha(
              'configs/perception/independent_templates/templates_v1.json'),
          'templates meta hash')
    check('input_hash_observations',
          diag['inputs']['final_observations_sha256'] == sha(args.final_shadow),
          'observations hash')
    # Reconstruct best candidate per method and frame from exported rows.
    best_by_method = {'baseline': {}, 'improved': {}}
    for row in rows:
        if row['split'] != 'sealed_test':
            continue
        method = 'baseline' if row['template_id'] == 'old_baseline_template' else 'improved'
        current = best_by_method[method].get(row['frame_id'])
        if current is None or row['max_score'] > current['max_score']:
            best_by_method[method][row['frame_id']] = row
    check('candidate_frames',
          all(len(best_by_method[m]) == diag['data_scope']['diagnostic_frames']
              for m in best_by_method), str({k: len(v) for k, v in best_by_method.items()}))
    for method, target in (('baseline', diag['candidate_summary']['threshold_sweep']['baseline_old_template']),
                           ('improved', diag['candidate_summary']['threshold_sweep']['improved_multi'])):
        for item in target:
            threshold = item['threshold']
            tp = fp = fn = tn = 0
            for frame_id, row in best_by_method[method].items():
                label = labels[frame_id]
                detected = row['max_score'] >= threshold
                if label['present'] and detected:
                    tp += 1
                elif label['present']:
                    fn += 1
                elif detected:
                    fp += 1
                else:
                    tn += 1
            check(method + '_sweep_%.2f' % threshold,
                  (tp, fp, fn, tn) == (item['tp'], item['fp'],
                                       item['fn'], item['tn']),
                  'recomputed=%r frozen=%r' % ((tp, fp, fn, tn),
                                                (item['tp'], item['fp'],
                                                 item['fn'], item['tn'])))
    # Recompute coordinate metadata: label bbox center vs green point.
    for item in diag['coordinate_audit']['rows']:
        frame_id = item['frame_id']
        label = labels[frame_id]
        row = best_by_method['improved'][frame_id]
        center = (label['bbox_xywh'][0] + label['bbox_xywh'][2] / 2.0,
                  label['bbox_xywh'][1] + label['bbox_xywh'][3] / 2.0)
        green = label['reference_point_px']
        intr = item['intrinsics']
        check('label_center_green_px:' + frame_id,
              abs(math.dist(center, green) - item['label_bbox_center_vs_green_px']) < 0.05,
              'label bbox center to green')
        check('label_center_green_deg:' + frame_id,
              abs(angle_deg(center, green, intr)
                  - item['label_bbox_center_vs_green_deg']) < 0.05,
              'label bbox center vs green angle')
        check('improved_candidate_iou:' + frame_id,
              row['max_iou'] is not None
              and abs(row['max_iou'] - item['improved_candidate_iou']) < 0.01,
              'candidate IoU')
    # B reproduction: current consumer with old template/params against frozen baseline.
    from boom_birds.evaluation.landmark_consumer import LandmarkConsumer
    template = Path('configs/perception/tower_template_v1.png')
    consumer = LandmarkConsumer(template_path=template, threshold=0.55)
    observations = [r for r in load_jsonl(args.final_shadow)
                    if r.get('sensor_key') == 'front_rgb']
    observations.sort(key=lambda r: (r['header']['sync_generation'],
                                     r['header']['sequence_id']))
    reproduced = {r['payload']['ref'].split('/')[-1]: consumer.process(r)
                  for r in observations}
    old = {r['input_frame_id']: r for r in load_jsonl(args.baseline_results)}
    mismatches = [frame for frame, result in old.items()
                  if frame in reproduced
                  and result['status'] != reproduced[frame]['status']]
    check('B_reproduces_old_baseline', not mismatches, repr(mismatches[:5]))
    check('image_shape_intrinsics',
          all(x['shape_hw'] == [240, 320] and
              x['intrinsics'] == [[160.0, 0.0, 160.0],
                                  [0.0, 160.0, 120.0],
                                  [0.0, 0.0, 1.0]]
              for x in diag['image_intrinsic_checks']),
          'all diagnostic observations 320x240 with fx=160/cx=160')
    check('template_source_hashes',
          all(Path(x['path']).exists()
              and x['sha256'] == sha(x['path'])
              for x in diag['templates']),
          'template files/hash')
    status = 'PASS' if not failures else 'FAIL'
    report = {
        'schema_version': 'dsh.landmark_root_cause_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'scope': 'offline diagnostic only; 49 frames are exposed, not a sealed test',
        'recomputed_candidate_frames': sum(len(v) for v in best_by_method.values()),
        'B_reproduction_mismatches': len(mismatches),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({'status': status, 'checks': len(checks),
                      'failures': failures[:3],
                      'B_mismatches': len(mismatches)},
                     ensure_ascii=False))
    raise SystemExit(0 if not failures else 1)


if __name__ == '__main__':
    main()
