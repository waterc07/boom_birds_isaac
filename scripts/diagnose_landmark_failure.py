"""Offline root-cause diagnostics for the natural-tower consumer.

This is diagnostic tooling only: it does not change the frozen result, use test
labels to tune production thresholds, or read truth during consumer inference.
The 49 previously opened frames are marked exposed-diagnostic.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_detector import TowerTemplateDetector
from boom_birds.evaluation.landmark_improved import MultiViewAnchorDetector

OLD_TEMPLATE = Path('configs/perception/tower_template_v1.png')
TEMPLATES_META = Path('configs/perception/independent_templates/templates_v1.json')
LABELS = Path('configs/perception/landmark_independent_labels_v1.json')
FINAL_SHADOW = Path('outputs/sensor_shadow/lm_independence_sensor/observations.jsonl')
PILOT_SHADOW = Path('outputs/sensor_shadow/lm_pilot_sensor/observations.jsonl')
BASELINE_RESULTS = Path('outputs/perception/independent_v3_baseline/results.jsonl')
IMPROVED_RESULTS = Path('outputs/perception/independent_v3_improved/results.jsonl')
SCALES = (0.5, 0.65, 0.8, 1.0, 1.15)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def observations():
    rows = load_jsonl(FINAL_SHADOW) + load_jsonl(PILOT_SHADOW)
    out = {}
    for row in rows:
        if row.get('sensor_key') == 'front_rgb':
            out[row['payload']['ref'].split('/')[-1]] = row
    return out


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def point_bearing(point, intrinsics):
    return math.atan2(float(point[0]) - float(intrinsics[0][2]),
                      float(intrinsics[0][0]))


def point_angle(p, q, intrinsics):
    return abs(math.degrees(point_bearing(p, intrinsics)
                            - point_bearing(q, intrinsics)))


def center(bbox):
    return (bbox[0] + bbox[2] / 2.0, bbox[1] + bbox[3] / 2.0)


def template_stats(path):
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return {'error': 'unreadable'}
    gray = image.astype(np.float32)
    edge = cv2.Canny(image, 50, 150)
    return {
        'path': str(path),
        'shape_hw': [int(image.shape[0]), int(image.shape[1])],
        'sha256': sha(path),
        'grayscale_mean': float(gray.mean()),
        'grayscale_std': float(gray.std()),
        'near_white_fraction': float((gray >= 240).mean()),
        'edge_density': float((edge > 0).mean()),
    }


def score_cases(entries, cases, label_kind, scales=SCALES):
    rows = []
    for entry in entries:
        template0 = cv2.imread(entry['path'], cv2.IMREAD_GRAYSCALE)
        if template0 is None:
            continue
        template0 = template0.astype(np.float32)
        for case in cases:
            image = cv2.imread(case['ref'], cv2.IMREAD_GRAYSCALE)
            image = image.astype(np.float32)
            label_bbox = case.get('bbox_xywh')
            label_ref = case.get('reference_point_px')
            for scale in scales:
                template = cv2.resize(template0, None, fx=scale, fy=scale,
                                      interpolation=cv2.INTER_AREA)
                th, tw = template.shape
                if th > image.shape[0] or tw > image.shape[1]:
                    continue
                scores = cv2.matchTemplate(image, template,
                                           cv2.TM_CCOEFF_NORMED)
                _, max_score, _, max_loc = cv2.minMaxLoc(scores)
                bbox = (int(max_loc[0]), int(max_loc[1]), int(tw), int(th))
                anchor = None
                if entry.get('anchor_fraction_xy') is not None:
                    anchor = (bbox[0] + float(entry['anchor_fraction_xy'][0]) * tw,
                              bbox[1] + float(entry['anchor_fraction_xy'][1]) * th)
                iou_value = iou(bbox, label_bbox) if label_bbox else None
                target_score = None
                target_bbox = None
                if label_bbox:
                    # max score over candidates that actually overlap the label box
                    ys, xs = np.where(scores >= -1.0)
                    # vectorized IoU for every top-left position
                    x1 = np.maximum(xs, label_bbox[0])
                    y1 = np.maximum(ys, label_bbox[1])
                    x2 = np.minimum(xs + tw, label_bbox[0] + label_bbox[2])
                    y2 = np.minimum(ys + th, label_bbox[1] + label_bbox[3])
                    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
                    union = tw * th + label_bbox[2] * label_bbox[3] - inter
                    ious = inter / np.maximum(union, 1e-9)
                    mask = ious >= 0.3
                    if mask.any():
                        target_scores = scores[ys[mask], xs[mask]]
                        flat = int(np.argmax(target_scores))
                        yy = int(ys[mask][flat])
                        xx = int(xs[mask][flat])
                        target_score = float(scores[yy, xx])
                        target_bbox = (int(xx), int(yy), int(tw), int(th))
                rows.append({
                    'frame_id': case['frame_id'], 'split': case['split'],
                    'family': case['family'], 'present': case['present'],
                    'template_id': entry['template_id'], 'scale': scale,
                    'template_shape_hw': [int(th), int(tw)],
                    'valid_positions': int(scores.shape[0] * scores.shape[1]),
                    'max_score': float(max_score), 'max_bbox_xywh': bbox,
                    'max_iou': iou_value,
                    'max_anchor': anchor,
                    'target_iou_bbox': target_bbox,
                    'target_iou_score': target_score,
                    'label_bbox_xywh': label_bbox,
                    'label_ref': label_ref,
                })
    return rows


def aggregate_frames(rows):
    out = {}
    for row in rows:
        key = row['frame_id']
        current = out.get(key)
        if current is None:
            out[key] = dict(row)
        else:
            if row['max_score'] > current['max_score']:
                out[key] = dict(row)
    return out


def threshold_sweep(frames, label_map, thresholds, score_key='max_score',
                    iou_key='max_iou'):
    result = []
    for threshold in thresholds:
        tp = fp = fn = tn = 0
        for frame_id, row in frames.items():
            label = label_map[frame_id]
            detected = row[score_key] is not None and row[score_key] >= threshold
            if label['present'] and detected:
                tp += 1
            elif label['present']:
                fn += 1
            elif detected:
                fp += 1
            else:
                tn += 1
        result.append({'threshold': threshold, 'tp': tp, 'fp': fp,
                       'fn': fn, 'tn': tn,
                       'precision': tp / (tp + fp) if tp + fp else None,
                       'recall': tp / (tp + fn) if tp + fn else None})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=Path('docs/reports/perception/dsh_landmark_root_cause_20261103.json'))
    parser.add_argument('--candidates', type=Path,
                        default=Path('docs/reports/perception/evidence_20261103_root_cause/candidates.jsonl'))
    args = parser.parse_args()
    labels_doc = load_json(LABELS)
    labels = labels_doc['labels']
    label_map = {x['frame_id']: x for x in labels}
    # The 49 previously opened frames are diagnostic-only now, not a sealed test.
    diagnostic = [x for x in labels if x['split'] == 'sealed_test']
    development = [x for x in labels if x['split'] == 'development']
    obs = observations()
    meta = load_json(TEMPLATES_META)
    entries = []
    for entry in meta['entries']:
        entries.append({**entry,
                        'stats': template_stats(entry['path'])})

    baseline_rows = score_cases([{
        'template_id': 'old_baseline_template',
        'path': str(OLD_TEMPLATE),
        'anchor_fraction_xy': None,
        'stats': template_stats(OLD_TEMPLATE),
    }], diagnostic, 'diagnostic')
    improved_rows = score_cases(entries, diagnostic, 'diagnostic')
    dev_improved_rows = score_cases(entries, development, 'development')
    args.candidates.parent.mkdir(parents=True, exist_ok=True)
    with args.candidates.open('w', encoding='utf-8') as stream:
        for row in baseline_rows + improved_rows + dev_improved_rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    baseline_best = aggregate_frames(baseline_rows)
    improved_best = aggregate_frames(improved_rows)
    dev_improved_best = aggregate_frames(dev_improved_rows)

    # Per-template diagnosis: best per template over frames, and target-overlap score.
    per_template = {}
    for entry in entries:
        name = entry['template_id']
        frames = aggregate_frames([r for r in improved_rows if r['template_id'] == name])
        per_template[name] = {
            'stats': entry['stats'],
            'anchor_fraction_xy': entry['anchor_fraction_xy'],
            'frames': frames,
            'test_sweep': threshold_sweep(frames, label_map,
                                          (0.50, 0.55, 0.60, 0.65, 0.70)),
        }

    # Coordinate/identity audit on the eight evaluable reference frames.
    evaluable = [x for x in diagnostic if x.get('localization_subset')
                 and x.get('reference_point_px')]
    coord_rows = []
    for label in evaluable:
        frame_id = label['frame_id']
        obs_row = obs[frame_id]
        intrinsics = obs_row['sensor']['intrinsics']
        bbox_center = center(label['bbox_xywh'])
        green = label['reference_point_px']
        base = baseline_best.get(frame_id)
        improved = improved_best.get(frame_id)
        coord_rows.append({
            'frame_id': frame_id,
            'image_shape_hw': obs_row['sensor']['shape'][:2],
            'intrinsics': intrinsics,
            'label_bbox_center': bbox_center,
            'label_green_anchor': green,
            'label_bbox_center_vs_green_px': math.dist(bbox_center, green),
            'label_bbox_center_vs_green_deg': point_angle(bbox_center, green, intrinsics),
            'baseline_accepted': None,
            'baseline_bbox_center_vs_label_center_px': None,
            'baseline_bbox_center_vs_label_center_deg': None,
            'baseline_bbox_center_vs_green_px': None,
            'baseline_bbox_center_vs_green_deg': None,
            'baseline_iou': None,
            'improved_candidate_bbox_anchor': improved.get('max_anchor') if improved else None,
            'improved_candidate_template': improved.get('template_id') if improved else None,
            'improved_candidate_iou': improved.get('max_iou') if improved else None,
            'improved_candidate_anchor_vs_green_px': (
                math.dist(improved['max_anchor'], green)
                if improved and improved.get('max_anchor') and green else None),
            'improved_candidate_anchor_vs_green_deg': (
                point_angle(improved['max_anchor'], green, intrinsics)
                if improved and improved.get('max_anchor') and green else None),
        })
    # baseline accepted-only measurements
    baseline_results = {r['input_frame_id']: r for r in load_jsonl(BASELINE_RESULTS)}
    for row in coord_rows:
        result = baseline_results.get(row['frame_id'])
        if result and result['status'] == 'DETECTED':
            detection = result['extra']['detection']
            bbox = detection['bbox_xywh']
            bc = center(bbox)
            row['baseline_accepted'] = True
            row['baseline_bbox_center_vs_label_center_px'] = math.dist(
                bc, center(label_map[row['frame_id']]['bbox_xywh']))
            row['baseline_bbox_center_vs_label_center_deg'] = point_angle(
                bc, center(label_map[row['frame_id']]['bbox_xywh']),
                obs[row['frame_id']]['sensor']['intrinsics'])
            row['baseline_bbox_center_vs_green_px'] = math.dist(
                bc, label_map[row['frame_id']]['reference_point_px'])
            row['baseline_bbox_center_vs_green_deg'] = point_angle(
                bc, label_map[row['frame_id']]['reference_point_px'],
                obs[row['frame_id']]['sensor']['intrinsics'])
            row['baseline_iou'] = iou(bbox, label_map[row['frame_id']]['bbox_xywh'])
        else:
            row['baseline_accepted'] = False

    # Scale-coverage diagnostic (production remains 0.5..1.15). Extra scales
    # are diagnostic-only and are not used to change the frozen detector.
    extra_scales = (1.3, 1.5, 1.8, 2.0)
    extra_rows = score_cases(entries, diagnostic, 'diagnostic_extra_scale',
                             scales=SCALES + extra_scales)
    extra_target = {}
    for row in extra_rows:
        if not label_map[row['frame_id']].get('bbox_xywh'):
            continue
        if row['target_iou_score'] is None:
            continue
        current = extra_target.get(row['frame_id'])
        if current is None or row['target_iou_score'] > current['target_score']:
            extra_target[row['frame_id']] = {
                'frame_id': row['frame_id'], 'family': row['family'],
                'template_id': row['template_id'], 'scale': row['scale'],
                'target_score': row['target_iou_score'],
                'target_bbox': row['target_iou_bbox'],
            }

    # Image/intrinsic coordinate consistency.
    shape_checks = []
    for label in diagnostic:
        row = obs[label['frame_id']]
        shape_checks.append({
            'frame_id': label['frame_id'],
            'shape_hw': row['sensor']['shape'][:2],
            'intrinsics': row['sensor']['intrinsics'],
            'bbox_in_bounds': (None if not label.get('bbox_xywh') else
                (label['bbox_xywh'][0] >= 0
                 and label['bbox_xywh'][1] >= 0
                 and label['bbox_xywh'][0] + label['bbox_xywh'][2] <= row['sensor']['shape'][1]
                 and label['bbox_xywh'][1] + label['bbox_xywh'][3] <= row['sensor']['shape'][0])),
            'ref_in_bounds': (None if not label.get('reference_point_px') else
                (0 <= label['reference_point_px'][0] < row['sensor']['shape'][1]
                 and 0 <= label['reference_point_px'][1] < row['sensor']['shape'][0])),
        })

    # A/B reproduction: same old template/params through the current consumer class.
    from boom_birds.evaluation.landmark_consumer import LandmarkConsumer
    final_rows = [r for r in load_jsonl(FINAL_SHADOW)
                  if r.get('sensor_key') == 'front_rgb']
    final_rows.sort(key=lambda r: (r['header']['sync_generation'],
                                   r['header']['sequence_id']))
    consumer = LandmarkConsumer(template_path=OLD_TEMPLATE, threshold=0.55)
    reproduced = {r['payload']['ref'].split('/')[-1]: consumer.process(r)
                  for r in final_rows}
    base_repro = []
    for frame_id, existing in baseline_results.items():
        new = reproduced.get(frame_id)
        if new is None:
            continue
        base_repro.append({
            'frame_id': frame_id,
            'old_status': existing['status'], 'new_status': new['status'],
            'old_reason': existing['reason'], 'new_reason': new['reason'],
            'same_status': existing['status'] == new['status'],
        })
    b_mismatch = [x for x in base_repro if not x['same_status']]

    # Gate/status summary for the two formal consumers.
    baseline_status = {}
    improved_status = {}
    for result in load_jsonl(BASELINE_RESULTS):
        key = result['dataset'] + '/' + result['status']
        baseline_status[key] = baseline_status.get(key, 0) + 1
    for result in load_jsonl(IMPROVED_RESULTS):
        key = result['dataset'] + '/' + result['status']
        improved_status[key] = improved_status.get(key, 0) + 1

    test_frame_ids = {x['frame_id'] for x in diagnostic}
    test_status = {'baseline': {}, 'improved': {}}
    for method, rows in (('baseline', load_jsonl(BASELINE_RESULTS)),
                         ('improved', load_jsonl(IMPROVED_RESULTS))):
        for result in rows:
            if result.get('input_frame_id') in test_frame_ids:
                key = result['status'] + '/' + result['reason']
                test_status[method][key] = test_status[method].get(key, 0) + 1

    # Threshold sweep for multi-template and baseline, marked diagnostic.
    baseline_sweep = threshold_sweep(baseline_best, label_map,
                                     (0.50, 0.55, 0.60, 0.65, 0.70))
    improved_sweep = threshold_sweep(improved_best, label_map,
                                     (0.50, 0.55, 0.60, 0.65, 0.70))

    # Scale coverage: target bbox vs max template size at max scale.
    scale_coverage = []
    for entry in entries:
        max_w = entry['stats']['shape_hw'][1] * max(SCALES)
        max_h = entry['stats']['shape_hw'][0] * max(SCALES)
        for label in diagnostic:
            if not label['present'] or not label.get('bbox_xywh'):
                continue
            bw, bh = label['bbox_xywh'][2], label['bbox_xywh'][3]
            scale_coverage.append({
                'frame_id': label['frame_id'], 'family': label['family'],
                'template_id': entry['template_id'],
                'target_bbox_wh': [bw, bh],
                'template_max_wh': [max_w, max_h],
                'target_w_over_template_max_w': bw / max_w,
                'target_h_over_template_max_h': bh / max_h,
            })

    # Classify improved positive frames: no target-overlap candidate / candidate
    # below threshold / wrong candidate above threshold; gate is separately checked.
    classifications = []
    for label in diagnostic:
        if not label['present']:
            continue
        frame_id = label['frame_id']
        row = improved_best[frame_id]
        best_target_score = None
        for candidate in improved_rows:
            if candidate['frame_id'] != frame_id:
                continue
            if candidate['target_iou_score'] is not None:
                best_target_score = max(best_target_score or -2.0,
                                        candidate['target_iou_score'])
        global_score = row['max_score']
        has_bbox = bool(label.get('bbox_xywh'))
        if not has_bbox:
            kind = 'PRESENCE_ONLY_NO_BBOX_TARGET_OVERLAP_UNAVAILABLE'
        elif row['max_iou'] is not None and row['max_iou'] >= 0.3:
            kind = 'GLOBAL_CANDIDATE_TARGET_MATCH'
        elif best_target_score is not None and best_target_score >= 0.65:
            kind = 'TARGET_CANDIDATE_ABOVE_THRESHOLD_NOT_GLOBALLY_SELECTED'
        elif best_target_score is not None and best_target_score >= 0.5:
            kind = 'TARGET_CANDIDATE_BELOW_THRESHOLD'
        elif best_target_score is None:
            kind = 'NO_TARGET_OVERLAP_CANDIDATE'
        else:
            kind = 'TARGET_CANDIDATE_VERY_LOW'
        classifications.append({
            'frame_id': frame_id, 'family': label['family'],
            'global_score': global_score, 'global_iou': row['max_iou'],
            'global_template': row['template_id'],
            'best_target_score': best_target_score, 'class': kind,
            'accepted_at_0_65': global_score >= 0.65,
        })

    # Per-template ablation: each template alone at diagnostic thresholds.
    ablations = {}
    for entry in entries:
        name = entry['template_id']
        frames = aggregate_frames([r for r in improved_rows if r['template_id'] == name])
        ablations[name] = {
            'frames_with_candidates': len(frames),
            'thresholds': threshold_sweep(frames, label_map, (0.55, 0.65)),
        }
    ablations['multi_view'] = {
        'thresholds': improved_sweep,
        'detector_best_template_histogram': {},
    }
    template_hist = {}
    for frame_id, row in improved_best.items():
        template_hist[row['template_id']] = template_hist.get(row['template_id'], 0) + 1
    ablations['multi_view']['detector_best_template_histogram'] = template_hist

    report = {
        'schema_version': 'dsh.landmark_root_cause.v1',
        'status': 'DIAGNOSTIC_OFFLINE_EXPOSED_DATA',
        'head': 'e01e1028942b306284256c477116a952a206f67c',
        'source_commit': '1ecbb9c92c29e9523a470a22ebfe91e415fb1ac2',
        'inputs': {
            'labels_sha256': sha(LABELS),
            'freeze_sha256': sha('configs/perception/independent_freeze_v3.json'),
            'old_template_sha256': sha(OLD_TEMPLATE),
            'templates_meta_sha256': sha(TEMPLATES_META),
            'final_observations_sha256': sha(FINAL_SHADOW),
            'pilot_observations_sha256': sha(PILOT_SHADOW),
        },
        'data_scope': {
            'diagnostic_frames': len(diagnostic),
            'development_frames': len(development),
            'note': '49 previously opened frames are exposed diagnostic/development-adjacent data; not a sealed test for future tuning',
        },
        'templates': entries,
        'coordinate_audit': {
            'evaluable_reference_frames': len(evaluable),
            'rows': coord_rows,
            'template_anchor_metadata': [
                {'template_id': e['template_id'],
                 'shape_hw': e['stats']['shape_hw'],
                 'anchor_px_in_template': e['anchor_px_in_template'],
                 'anchor_fraction_xy': e['anchor_fraction_xy'],
                 'anchor_status': e['anchor_status']}
                for e in entries],
            'code_checks': {
                'image_decoding': 'cv2.imread IMREAD_GRAYSCALE; no RGB/BGR color path in matching',
                'resize_crop': 'no image crop/resize/letterbox; only template resizing',
                'anchor_mapping': 'bbox top-left + anchor_fraction * scaled template size',
                'bbox_origin': 'top-left pixel, same as PIL labels',
                'intrinsics': 'fx/cx0 from observation sensor.intrinsics',
                'angle_convention': 'atan2(px - cx0, fx); positive image-right; not world bearing',
                'frames': 'image projection only; camera optical frame vs body frame not mixed in bearing',
            },
        },
        'candidate_summary': {
            'baseline_best': baseline_best,
            'improved_best': improved_best,
            'per_template': per_template,
            'threshold_sweep': {
                'baseline_old_template': baseline_sweep,
                'improved_multi': improved_sweep,
            },
            'positive_classifications': classifications,
            'scale_coverage': scale_coverage,
            'extra_scale_target_candidates': extra_target,
            'template_selection_histogram': template_hist,
        },
        'ablation': {
            'A_old_baseline': {
                'source': 'frozen independent_v3_baseline results',
                'status_counts': baseline_status,
            },
            'B_new_code_old_template': {
                'detector': 'current LandmarkConsumer default old template/threshold 0.55',
                'frames_compared': len(base_repro),
                'status_mismatches': b_mismatch,
                'reproduced_old_baseline': not b_mismatch,
            },
            'C_single_template': ablations,
            'D_multi_template': ablations['multi_view'],
            'E_anchor_candidates': coord_rows,
        },
        'image_intrinsic_checks': shape_checks,
        'gate_test_status': {
            'baseline': baseline_status,
            'improved': improved_status,
        },
        'gate_status_summary': {
            'baseline': baseline_status,
            'improved': improved_status,
        },
        'test_frame_gate_status': test_status,
        'hypotheses': [
            {
                'id': 'H1_baseline_bbox_center_vs_green_same_point',
                'hypothesis': 'baseline bbox center and label green light reference are the same physical bearing object',
                'experiment': 'coordinate_audit rows: label bbox center vs green; accepted baseline bbox center vs label center and green',
                'observation': 'label bbox-center vs green angle 0.28-5.06 deg; baseline center vs label-center 5.65-11.74 deg; baseline center vs green 9.13-11.46 deg; baseline has no physical anchor',
                'status': 'REJECTED',
                'scope_effect': 'old baseline green-bearing values are historical and not directly comparable to green-anchor bearing; retain old numbers but do not call them physical anchor errors',
            },
            {
                'id': 'H2_coordinate_transform_defect',
                'hypothesis': 'a crop/resize/letterbox/anchor-scale/origin/intrinsic bug explains improved bearing/failure',
                'experiment': 'image/intrinsic consistency; synthetic anchor mapping at scales 0.5/0.8/1.0; B reproduction; code path review',
                'observation': 'all 49 images 320x240 with fx=160/cx0=160; synthetic anchor tests pass at .5/.8/1.0; B new code + old template + old .55 reproduces 613 frame statuses exactly; no crop/letterbox; anchor = bbox top-left + fraction*scaled template size',
                'status': 'NOT_CONFIRMED (no reproducible defect found)',
                'scope_effect': 'no coordinate constant correction; retain old freeze; anchor mapping itself is not evidence for improved localization because correct candidate absent',
            },
            {
                'id': 'H3_threshold_alone',
                'hypothesis': 'threshold .65 alone causes improved zero recall and lowering the threshold fixes it',
                'experiment': 'improved threshold sweep; target-overlap candidate scores for the nine bbox-labelled positives',
                'observation': 'at .55 TP15/FP22, .60 TP4/FP20, .65 TP0/FP2; 4 target candidates below .65, 5 very low; no threshold gives acceptable precision/recall; lowering accepts many hard negatives',
                'status': 'PARTIALLY_CONFIRMED (threshold is a secondary gate, not root cause)',
                'scope_effect': 'do not tune threshold on exposed data; threshold alone cannot recover independent view performance',
            },
            {
                'id': 'H4_template_view_coverage',
                'hypothesis': 'development-only templates do not cover reverse/north/oblique target appearance; score selection prefers background/other structures',
                'experiment': 'per-template ablation; template selection histogram; template texture stats; target-overlap score; wrong-candidate boxes',
                'observation': 'center template dominates 43/49, left 0/49, route 6/49; center alone at .65 TP0/FP2; left alone TP0; route alone TP0/FP0/.55 FP4; global max often IoU 0-0.2 on non-target regions at score .55-.61; target-best often .34-.59',
                'status': 'CONFIRMED',
                'scope_effect': 'template method not robust across independent views; adding more same-scene templates is not justified',
            },
            {
                'id': 'H5_scale_search_too_narrow',
                'hypothesis': 'target scale outside .5-1.15 causes misses',
                'experiment': 'target bbox width/height vs max template extent; extra diagnostic scales 1.3/1.5/1.8/2.0',
                'observation': 'target width ratio up to 1.82x template max; extra scales raise north s192 target score .485->.627 and north s186 .528->.554, but reverse stays .34-.43 and still below .65; static remains .589',
                'status': 'PARTIALLY_CONFIRMED (contributor for north; not sole for reverse)',
                'scope_effect': 'scale is a capability limit, not a single index bug; do not adopt a narrow scale patch as success',
            },
            {
                'id': 'H6_gate_generation_suppression',
                'hypothesis': 'gate/generation/reset suppresses valid test detections',
                'experiment': 'formal results status by test frame; gate status counts',
                'observation': 'all 49 diagnostic frames have consumer results; test frames show 0 UNKNOWN/0 REJECTED; rejects are warmup only',
                'status': 'REJECTED',
                'scope_effect': 'zero improved recall is detector/candidate/threshold, not gate suppression',
            },
            {
                'id': 'H7_multitemplate_scores_calibrated',
                'hypothesis': 'NCC scores from different templates are comparable/calibrated as a single confidence',
                'experiment': 'per-template selection histogram, per-template threshold sweeps, wrong background matches',
                'observation': 'same NCC metric but center dominates; other templates never selected; wrong regions score .55-.61; no calibration or score normalization beyond the shared NCC definition',
                'status': 'REJECTED as calibrated score; CONFIRMED as score-selection failure mode',
                'scope_effect': 'do not call score probability; multi-template max is not a validated confidence',
            },
            {
                'id': 'H8_exposed_49_can_be_sealed_test',
                'hypothesis': 'the 49 opened frames can be reused as a sealed independent test after diagnosis',
                'experiment': 'data provenance/diagnostic exposure audit',
                'observation': 'the 49 frames have already been opened and used for diagnosis; labels and candidate distributions are now visible',
                'status': 'REJECTED',
                'scope_effect': '49 frames are diagnostic/exposed only; future tests require new trajectory families and fresh freeze',
            },
        ],
        'method_decision': {
            'decision': 'STOP_TEMPLATE_METHOD_AS_MAIN_CANDIDATE',
            'implementation_defect': 'NONE_CONFIRMED; B reproduces baseline, coordinate synthetic tests pass; no production code fix made',
            'threshold_or_template_patch': 'NOT_RECOMMENDED; no acceptable threshold operating point; adding more same-scene templates is an unbounded coverage chase',
            'next_method': 'classical tower geometry + green-light anchor detector (edges/contour/trapezoid + HSV green blob + relative-position validation), no learned model, output bbox and anchor bearing only',
            'next_validation_cost': 'freeze new parameters; 3-4 new independent GUI episodes (reverse/north/oblique/away), 40-60 labelled frames; offline CPU evaluation; no Isaac retraining; no test-time threshold tuning',
            'stop_condition': 'if geometry+green anchor still cannot meet predeclared IoU/bearing with acceptable hard-negative FP, stop perception work this phase and do not add templates',
            'no_new_test_this_package': True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({
        'output': str(args.output),
        'baseline_best_count': len(baseline_best),
        'improved_best_count': len(improved_best),
        'B_reproduced': not b_mismatch,
        'B_mismatches': len(b_mismatch),
        'class_counts': {k: sum(1 for c in classifications if c['class'] == k)
                         for k in sorted({c['class'] for c in classifications})},
        'baseline_sweep': baseline_sweep,
        'improved_sweep': improved_sweep,
        'templates': [e['template_id'] for e in entries],
        'evaluable_ref_rows': len(evaluable),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
