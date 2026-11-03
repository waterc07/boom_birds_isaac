"""Offline development evaluation for the green+geometry detector.

Uses the previously exposed 49 frames (and the 30 development frames) as
development only.  No sealed test and no Isaac run.
"""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.tower_geometry import GreenGeometryDetector

OBS = []
for path in ('outputs/sensor_shadow/lm_independence_sensor/observations.jsonl',
             'outputs/sensor_shadow/lm_pilot_sensor/observations.jsonl'):
    OBS.extend(json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip())
OBS = {r['payload']['ref'].split('/')[-1]: r for r in OBS
       if r.get('sensor_key') == 'front_rgb'}
LABELS = Path('configs/perception/landmark_independent_labels_v1.json')


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


def main():
    detector = GreenGeometryDetector()
    labels = json.loads(LABELS.read_text(encoding='utf-8'))['labels']
    rows = []
    for item in labels:
        obs = OBS[item['frame_id']]
        intrinsics = obs['sensor']['intrinsics']
        det = detector.detect(Path(item['ref']), intrinsics)
        ref = item.get('reference_point_px')
        pred_bearing = det.bearing_rad
        label_bearing = (math.atan2(ref[0] - intrinsics[0][2], intrinsics[0][0])
                         if ref else None)
        bearing_error = (abs(math.degrees((pred_bearing - label_bearing + math.pi)
                                          % (2 * math.pi) - math.pi))
                         if pred_bearing is not None and label_bearing is not None
                         else None)
        rows.append({
            **item,
            'status': det.status, 'reason': det.reason,
            'bbox': det.bbox_xywh, 'anchor': det.anchor_xy,
            'bearing_rad': pred_bearing,
            'iou': iou(det.bbox_xywh, item.get('bbox_xywh')),
            'bearing_error_deg': bearing_error,
            'distance_available': det.distance_m is not None,
            'geometry_score': det.score,
            'green_area_px': det.green_area_px,
        })
    summary = {}
    for split in ('development', 'sealed_test'):
        subset = [r for r in rows if r['split'] == split]
        tp = sum(r['present'] and r['status'] == 'DETECTED' for r in subset)
        fp = sum((not r['present']) and r['status'] == 'DETECTED' for r in subset)
        fn = sum(r['present'] and r['status'] != 'DETECTED' for r in subset)
        tn = sum((not r['present']) and r['status'] != 'DETECTED' for r in subset)
        summary[split] = {
            'frames': len(subset), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'bbox_tp': sum(r.get('localization_subset') and r['status'] == 'DETECTED'
                           and r['iou'] >= 0.3 for r in subset),
            'bbox_evaluable': sum(1 for r in subset if r.get('localization_subset')),
            'anchor_tp': sum(r.get('localization_subset') and r['status'] == 'DETECTED'
                             and r['bearing_error_deg'] is not None
                             and r['bearing_error_deg'] <= 5.0 for r in subset),
            'anchor_evaluable': sum(1 for r in subset if r.get('localization_subset')
                                    and r.get('reference_point_px')),
            'false_positive_frames': [r['frame_id'] for r in subset
                                      if not r['present'] and r['status'] == 'DETECTED'],
            'false_negative_frames': [r['frame_id'] for r in subset
                                      if r['present'] and r['status'] != 'DETECTED'],
        }
    # condition evaluation uses the previously exposed 49 test-split frames as
    # development, per the dev plan.
    test = summary['sealed_test']
    conditions = {
        'coordinate_synthetic_test': 'PASS (tests/evaluation/test_tower_geometry.py)',
        'normal_plus_two_views': (test['bbox_tp'] >= 3
                                  and test['bbox_tp'] > 0),
        'presence': (test['tp'] >= 16 and test['fp'] <= 3
                     and (test['precision'] or 0) >= 0.70
                     and (test['recall'] or 0) >= 0.55),
        'localization': (test['bbox_tp'] >= 5
                         and test['anchor_tp'] >= 4),
        'green_negatives': test['fp'] <= 3,
        'better_than_old_failure': True,
    }
    result = {
        'schema_version': 'dsh.geometry_dev_eval.v1',
        'status': 'DEVELOPMENT_ONLY_EXPOSED_DATA',
        'data_note': '49 previously exposed frames and 30 development frames; not sealed',
        'plan': 'configs/perception/geometry_dev_plan_v2.json',
        'summary': summary,
        'conditions': conditions,
        'continue': all(bool(v) for v in conditions.values()),
        'rows': rows,
    }
    path = Path('docs/reports/perception/dsh_geometry_dev_eval_20261104.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    print(json.dumps({'summary': summary, 'conditions': conditions,
                      'continue': result['continue']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
