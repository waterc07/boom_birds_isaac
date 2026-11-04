"""Freeze landmark decision thresholds on a validation split (no final pool).

This is the version-controlled, CLI-driven version of the threshold-freeze step
used by the bounded landmark experiment.  It reads the predictions produced by
scripts/evaluate_landmark_yolo.py plus the validation annotation document and
sweeps candidate score thresholds; it never trains, never reads the final pool
and refuses to overwrite an existing frozen file unless --overwrite is passed.

Method (training plan v2 / task definition section 3.3):
- tau_det: smallest candidate score whose validation presence precision is at
  least the requested minimum (default 0.95);
- tau_conf: same sweep under the single-landmark identity claim (identity
  precision equals presence precision because a claim is made whenever a
  candidate is emitted);
- tau_margin: from validation frames with >=2 candidates, the smallest top1-top2
  margin whose accepted frames are all true positives; if the split has no
  multi-candidate frames it stays PROPOSED (cannot be estimated);
- tau_px: never below the measured blind re-annotation noise (default 2.236 px)
  and frozen at the requested value (default 3.0 px, 1 px = 0.358 deg at fx=160);
- tau_iou: 0.3 diagnostic gate from the plan.

Exit codes: 0 ok, 2 invalid input, 3 refused to overwrite.
"""
import argparse
import hashlib
import json
from pathlib import Path

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3

SCHEMA_VERSION = 'dsh.landmark_threshold_freeze.v1'
DEFAULT_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45,
                0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def load_predictions(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def annotation_gt(annotation):
    """Return 'present' / 'absent' / None (GT_UNOBSERVABLE) for one annotation.

    GT_UNOBSERVABLE is an annotation-side state: undecidable frames, missing
    presence information, and present-but-no-bbox frames (HN2 full occlusion).
    They are excluded from the 2x2 exactly like the metrics layer does.
    """
    target = annotation.get('target') or {}
    geometry = annotation.get('geometry') or {}
    present = target.get('present')
    if target.get('undecidable') is True or present is None:
        return None
    if present is True:
        return None if geometry.get('bbox_xywh') is None else 'present'
    return 'absent'


def observable_ground_truth(document):
    gt = {}
    unobservable = []
    for annotation in document.get('annotations', []):
        frame_id = annotation.get('frame_id')
        if not frame_id:
            continue
        label = annotation_gt(annotation)
        if label is None:
            unobservable.append(frame_id)
        else:
            gt[frame_id] = label
    return gt, unobservable


def best_score(row):
    observation = row.get('observation') or {}
    candidates = observation.get('candidates') or []
    scores = []
    for candidate in candidates:
        try:
            scores.append(float(candidate.get('score') or 0.0))
        except (TypeError, ValueError):
            continue
    return max(scores) if scores else 0.0


def presence_confusion(rows, gt, tau):
    tp = fp = 0
    for row in rows:
        truth = gt.get(row.get('frame_id'))
        if truth is None:
            continue
        detected = best_score(row) >= tau
        if truth == 'present' and detected:
            tp += 1
        elif truth == 'absent' and detected:
            fp += 1
    return tp, fp


def sweep_thresholds(rows, gt, grid=DEFAULT_GRID):
    observed = {best_score(row) for row in rows
                if gt.get(row.get('frame_id')) is not None}
    grid = sorted(set(round(float(value), 6) for value in grid) | {round(v, 6) for v in observed})
    sweep = []
    for tau in grid:
        tp, fp = presence_confusion(rows, gt, tau)
        precision = (tp / float(tp + fp)) if (tp + fp) else None
        sweep.append({'tau': tau, 'tp': tp, 'fp': fp, 'precision': precision})
    return sweep


def select_min_score(sweep, min_precision):
    qualifying = [entry for entry in sweep
                  if entry['precision'] is not None and entry['precision'] >= min_precision
                  and entry['tp'] > 0]
    return qualifying[0] if qualifying else None


def margin_analysis(rows, gt):
    frames = []
    for row in rows:
        observation = row.get('observation') or {}
        candidates = observation.get('candidates') or []
        if len(candidates) < 2:
            continue
        scores = []
        for candidate in candidates:
            try:
                scores.append(float(candidate.get('score') or 0.0))
            except (TypeError, ValueError):
                continue
        scores.sort(reverse=True)
        if len(scores) < 2:
            continue
        frames.append({'frame_id': row.get('frame_id'),
                       'gt': gt.get(row.get('frame_id')),
                       'top1': scores[0], 'top2': scores[1],
                       'margin': scores[0] - scores[1]})
    return frames


def select_margin(frames):
    """Smallest margin whose accepted frames are all true positives."""
    margins = sorted({round(frame['margin'], 6) for frame in frames})
    for tau_margin in margins:
        accepted = [frame for frame in frames if frame['margin'] >= tau_margin]
        if accepted and all(frame['gt'] == 'present' for frame in accepted):
            return tau_margin, len(accepted)
    return None, 0


def build_freeze_document(rows, document, *, predictions_path, labels_path,
                          checkpoint_path=None, checkpoint_sha256=None,
                          tau_precision=0.95, tau_px=3.0, tau_iou=0.3,
                          tau_kpt=0.5, tau_green_pixels=3, annotation_noise_px=2.236):
    gt, unobservable = observable_ground_truth(document)
    sweep = sweep_thresholds(rows, gt)
    chosen = select_min_score(sweep, tau_precision)
    margin_frames = margin_analysis(rows, gt)
    tau_margin, accepted = select_margin(margin_frames)
    if tau_px < annotation_noise_px:
        raise ValueError('tau_px %.3f is below the annotation noise floor %.3f px'
                         % (tau_px, annotation_noise_px))
    result = {
        'schema_version': SCHEMA_VERSION,
        'status': 'FROZEN_ON_VALIDATION' if chosen else 'NO_QUALIFYING_THRESHOLD',
        'source': {
            'predictions': {'path': str(predictions_path),
                            'sha256': sha256_file(predictions_path)},
            'labels': {'path': str(labels_path), 'sha256': sha256_file(labels_path)},
            'checkpoint': {'path': (str(checkpoint_path) if checkpoint_path else None),
                           'sha256': (checkpoint_sha256 if checkpoint_sha256
                                      else (sha256_file(checkpoint_path)
                                            if checkpoint_path else None))},
            'selection_context': 'thresholds frozen on the validation split only, after seed/checkpoint '
                                 'selection; the final pool is never read',
        },
        'method': {
            'tau_det': 'smallest score with validation presence precision >= %.4f' % tau_precision,
            'tau_conf': 'smallest score with validation identity precision >= %.4f' % tau_precision,
            'tau_margin': 'smallest top1-top2 margin whose accepted multi-candidate validation frames '
                          'are all true positives',
            'tau_px': '%.3f px (>= blind re-annotation noise %.3f px)' % (tau_px, annotation_noise_px),
            'tau_iou': '%.3f diagnostic gate' % tau_iou,
        },
        'sweep': sweep,
        'gt_observable_frames': len(gt),
        'gt_unobservable_frames': len(unobservable),
        'gt_unobservable_frame_ids': unobservable,
        'multi_candidate_validation': {'frames': len(margin_frames),
                                       'sample': margin_frames[:10]},
        'frozen': {
            'tau_det': chosen['tau'] if chosen else None,
            'tau_conf': chosen['tau'] if chosen else None,
            'tau_margin': (tau_margin if tau_margin is not None
                           else {'value': 0.1,
                                 'status': 'PROPOSED_NO_MULTI_CANDIDATE_FRAMES'}),
            'tau_px': tau_px,
            'tau_iou': tau_iou,
            'tau_kpt': {'value': tau_kpt, 'status': 'PROPOSED_NOT_FROZEN',
                        'note': 'decoder keypoint-confidence default; not in the plan v2 freeze list'},
            'tau_green_pixels': {'value': tau_green_pixels,
                                 'status': 'FROZEN_BY_SPEC_V2_1',
                                 'note': 'annotation-side reference usability rule, not a model threshold'},
        },
        'precision_at_frozen': chosen,
        'margin_selection': ({'tau_margin': tau_margin, 'accepted': accepted}
                             if tau_margin is not None else None),
        'limitations': [
            'validation negative denominator may be far below the certification size; '
            'report the denominator explicitly and mark C4 INCOMPLETE when insufficient',
            'if no score qualifies the thresholds stay null and must be re-derived after more data',
            'the final pool is never read by this script',
        ],
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Freeze landmark decision thresholds on a validation split.')
    parser.add_argument('--predictions', required=True,
                        help='predictions.jsonl produced by scripts/evaluate_landmark_yolo.py')
    parser.add_argument('--labels', required=True,
                        help='validation annotation document (spec v2/v2.1 JSON)')
    parser.add_argument('--checkpoint', default=None,
                        help='selected checkpoint path (.pt/.onnx); its sha256 is recorded')
    parser.add_argument('--checkpoint-sha256', default=None,
                        help='checkpoint sha256 when the file is not available locally')
    parser.add_argument('--out', required=True, help='output frozen thresholds JSON')
    parser.add_argument('--tau-precision', type=float, default=0.95)
    parser.add_argument('--tau-px', type=float, default=3.0)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-kpt', type=float, default=0.5)
    parser.add_argument('--tau-green-pixels', type=int, default=3)
    parser.add_argument('--annotation-noise-px', type=float, default=2.236)
    parser.add_argument('--overwrite', action='store_true',
                        help='allow replacing an existing frozen thresholds file')
    args = parser.parse_args(argv)

    predictions = Path(args.predictions)
    labels = Path(args.labels)
    out = Path(args.out)
    if not predictions.is_file():
        print('invalid input: predictions not found: %s' % predictions)
        return EXIT_INVALID_INPUT
    if not labels.is_file():
        print('invalid input: labels not found: %s' % labels)
        return EXIT_INVALID_INPUT
    if args.checkpoint is not None and not Path(args.checkpoint).is_file():
        print('invalid input: checkpoint not found: %s' % args.checkpoint)
        return EXIT_INVALID_INPUT
    if args.checkpoint is None and not args.checkpoint_sha256:
        print('invalid input: provide --checkpoint or --checkpoint-sha256')
        return EXIT_INVALID_INPUT
    if out.exists() and not args.overwrite:
        print('refusing to overwrite %s (pass --overwrite for an intentional refreeze)' % out)
        return EXIT_OVERWRITE_REFUSED
    try:
        document = load_json(labels)
        rows = load_predictions(predictions)
        result = build_freeze_document(
            rows, document,
            predictions_path=predictions, labels_path=labels,
            checkpoint_path=args.checkpoint,
            checkpoint_sha256=args.checkpoint_sha256,
            tau_precision=args.tau_precision, tau_px=args.tau_px,
            tau_iou=args.tau_iou, tau_kpt=args.tau_kpt,
            tau_green_pixels=args.tau_green_pixels,
            annotation_noise_px=args.annotation_noise_px)
    except (ValueError, KeyError) as error:
        print('invalid input: %s' % error)
        return EXIT_INVALID_INPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'frozen': result['frozen'],
                      'precision_at_frozen': result['precision_at_frozen'],
                      'gt_observable_frames': result['gt_observable_frames'],
                      'gt_unobservable_frames': result['gt_unobservable_frames'],
                      'multi_candidate_frames': result['multi_candidate_validation']['frames']},
                     indent=2))
    print('wrote', out)
    return EXIT_OK if result['frozen']['tau_det'] is not None else EXIT_INVALID_INPUT


if __name__ == '__main__':
    raise SystemExit(main())
