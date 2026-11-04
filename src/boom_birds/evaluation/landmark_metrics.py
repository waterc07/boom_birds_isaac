"""Metric definitions for the pre-training landmark experiment (definition only).

This module makes the denominator rules from
docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md
executable and testable.  It contains no model, no training, no detector and no
ground-truth channel into any deployed actor; it only scores already-recorded
predictions against independent annotations.

Key rules encoded here:

- UNKNOWN/REJECTED observations are never counted as TP/FN/TN/FP; they are
  reported as unobservable and only lower evaluable coverage;
- a target-present frame whose reference point is annotated UNAVAILABLE is a
  reference success when the model declares UNAVAILABLE (no keypoint) and a
  semantic error when it emits a keypoint;
- an unlabelled reference frame is not a joint failure; it only lowers joint
  coverage, and the all-positive lower bound stays explicitly separate;
- identity is evaluated only when claims or negatives exist; a single-landmark
  experiment without similar-structure negatives cannot claim identity results.

Units: bbox in pixels (origin top-left, xywh), keypoints in pixels.
"""
from collections import Counter
import math

__all__ = [
    'MetricDefinitionError',
    'PRED_STATUSES',
    'REFERENCE_LABELS',
    'evaluate_frame',
    'summarize',
]

PRED_STATUSES = ('DETECTED', 'NOT_DETECTED', 'UNKNOWN', 'REJECTED')
REFERENCE_LABELS = (None, 'VISIBLE', 'UNAVAILABLE')
GT_REQUIRED = ('frame_id', 'present', 'landmark_id', 'bbox_xywh', 'reference')

PRESENCE_TP = 'TP'
PRESENCE_FP = 'FP'
PRESENCE_FN = 'FN'
PRESENCE_TN = 'TN'
PRESENCE_UNOBSERVABLE = 'UNOBSERVABLE'


class MetricDefinitionError(ValueError):
    """Raised when an input row cannot be mapped to the frozen definitions."""


def _iou(a, b):
    if not a or not b:
        return 0.0
    ax, ay, aw, ah = [float(v) for v in a]
    bx, by, bw, bh = [float(v) for v in b]
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (aw * ah + bw * bh - inter)


def _check_range(name, value, low, high):
    if not (low <= float(value) <= high):
        raise MetricDefinitionError('%s out of range: %r' % (name, value))


def _validate(gt, pred, tau_iou, tau_px, tau_conf):
    if not isinstance(gt, dict) or not isinstance(pred, dict):
        raise MetricDefinitionError('gt and pred must be dicts')
    missing = [key for key in GT_REQUIRED if key not in gt]
    if missing:
        raise MetricDefinitionError('ground truth missing fields: ' + ', '.join(missing))
    if not isinstance(gt['present'], bool):
        raise MetricDefinitionError('gt.present must be bool')
    if gt['present']:
        bbox = gt['bbox_xywh']
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise MetricDefinitionError('present gt requires bbox_xywh of length 4')
        if not gt['landmark_id']:
            raise MetricDefinitionError('present gt requires landmark_id')
    if gt['reference'] not in REFERENCE_LABELS:
        raise MetricDefinitionError('unsupported gt.reference: %r' % (gt['reference'],))
    status = pred.get('status')
    if status not in PRED_STATUSES:
        raise MetricDefinitionError('unsupported prediction status: %r' % (status,))
    _check_range('tau_iou', tau_iou, 0.0, 1.0)
    _check_range('tau_px', tau_px, 0.0, 1e6)
    _check_range('tau_conf', tau_conf, 0.0, 1.0)


def evaluate_frame(gt, pred, *, tau_iou, reference_px, tau_px, tau_conf):
    """Classify one frame against the frozen presence/reference/identity/joint rules."""
    _validate(gt, pred, tau_iou, tau_px, tau_conf)
    status = pred['status']
    bbox = pred.get('bbox_xywh')
    present = bool(gt['present'])
    keypoint = pred.get('keypoint_px')
    gt_bbox = gt['bbox_xywh']
    ref_label = gt['reference']

    unobservable = status in ('UNKNOWN', 'REJECTED')
    counted = not unobservable

    # --- presence -------------------------------------------------------
    if unobservable:
        presence_class = PRESENCE_UNOBSERVABLE
        pred_present = None
    else:
        pred_present = status == 'DETECTED' and bbox is not None and (
            not present or _iou(bbox, gt_bbox) >= float(tau_iou))
        if present:
            presence_class = PRESENCE_TP if pred_present else PRESENCE_FN
        else:
            presence_class = PRESENCE_FP if status == 'DETECTED' else PRESENCE_TN

    # --- reference ------------------------------------------------------
    anchor_error_px = None
    if ref_label is None:
        reference_class = 'NOT_LABELLED'
        reference_correct = None
    elif ref_label == 'VISIBLE':
        if not present:
            raise MetricDefinitionError('VISIBLE reference on an absent target is invalid')
        if keypoint is None:
            reference_class = 'PRESENT_NO_KEYPOINT'
            reference_correct = False
        elif reference_px is None:
            raise MetricDefinitionError('VISIBLE gt reference with an emitted keypoint '
                                        'requires reference_px')
        else:
            anchor_error_px = math.hypot(float(keypoint[0]) - float(reference_px[0]),
                                         float(keypoint[1]) - float(reference_px[1]))
            if anchor_error_px <= float(tau_px):
                reference_class = 'PRESENT_AND_AVAILABLE'
                reference_correct = True
            else:
                reference_class = 'PRESENT_WRONG_ANCHOR'
                reference_correct = False
    else:  # UNAVAILABLE
        if not present:
            raise MetricDefinitionError('UNAVAILABLE reference on an absent target is invalid')
        if keypoint is None:
            reference_class = 'UNAVAILABLE_DECLARED'
            reference_correct = True
        else:
            reference_class = 'UNAVAILABLE_EMITTED_KEYPOINT'
            reference_correct = False

    # --- identity -------------------------------------------------------
    claim = pred.get('landmark_id') is not None
    if claim:
        identity_correct = bool(present and pred.get('landmark_id') == gt['landmark_id'])
    else:
        identity_correct = None
    score = pred.get('score')
    high_conf_false_match = bool(
        (not present) and claim and score is not None
        and float(score) >= float(tau_conf))

    # --- joint ----------------------------------------------------------
    joint_evaluable = bool(present and gt_bbox is not None and ref_label is not None)
    joint_fail_reason = None
    if not joint_evaluable:
        joint_ok = None
    elif presence_class != PRESENCE_TP:
        joint_ok = False
        joint_fail_reason = presence_class
    elif identity_correct is not True:
        joint_ok = False
        joint_fail_reason = 'IDENTITY'
    elif reference_correct is not True:
        joint_ok = False
        joint_fail_reason = 'REFERENCE'
    else:
        joint_ok = True

    return {
        'frame_id': gt['frame_id'],
        'gt_present': present,
        'pred_status': status,
        'counted_in_confusion': counted,
        'presence_class': presence_class,
        'pred_present': pred_present,
        'reference_class': reference_class,
        'reference_correct': reference_correct,
        'anchor_error_px': anchor_error_px,
        'identity_claim': claim,
        'identity_correct': identity_correct,
        'high_confidence_false_match': high_conf_false_match,
        'joint_evaluable': joint_evaluable,
        'joint_ok': joint_ok,
        'joint_fail_reason': joint_fail_reason,
    }


def _rate(numerator, denominator):
    return (float(numerator) / denominator) if denominator else None


def _error_stats(values):
    if not values:
        return {'count': 0, 'median_px': None, 'p90_px': None, 'max_px': None}
    ordered = sorted(values)
    n = len(ordered)
    median = (ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2]))
    p90 = ordered[max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))]
    return {'count': n, 'median_px': median, 'p90_px': p90, 'max_px': ordered[-1]}


def summarize(rows):
    """Aggregate evaluated frames with explicit numerators and denominators."""
    rows = list(rows)
    presence = Counter()
    reference = Counter()
    joint_failures = Counter()
    anchors = []

    positives = 0
    negatives = 0
    joint_denominator = 0
    joint_tp = 0
    claims = 0
    correct_claims = 0
    high_conf_false_matches = 0

    for row in rows:
        if row['gt_present']:
            positives += 1
        else:
            negatives += 1
        presence[row['presence_class']] += 1
        reference[row['reference_class']] += 1
        if row['anchor_error_px'] is not None:
            anchors.append(row['anchor_error_px'])
        if row['identity_claim']:
            claims += 1
            if row['identity_correct']:
                correct_claims += 1
        if row['high_confidence_false_match']:
            high_conf_false_matches += 1
        if row['joint_evaluable']:
            joint_denominator += 1
            if row['joint_ok']:
                joint_tp += 1
            else:
                joint_failures[row['joint_fail_reason'] or 'UNKNOWN'] += 1

    tp = presence[PRESENCE_TP]
    fp = presence[PRESENCE_FP]
    fn = presence[PRESENCE_FN]
    tn = presence[PRESENCE_TN]
    unknown = presence[PRESENCE_UNOBSERVABLE]
    accounted = tp + fp + fn + tn + unknown
    if accounted != len(rows):
        raise MetricDefinitionError('frame accounting mismatch: %d != %d'
                                    % (accounted, len(rows)))

    ref_avail = (reference['PRESENT_AND_AVAILABLE']
                 + reference['PRESENT_WRONG_ANCHOR']
                 + reference['PRESENT_NO_KEYPOINT'])
    ref_unavail = reference['UNAVAILABLE_DECLARED'] + reference['UNAVAILABLE_EMITTED_KEYPOINT']
    ref_correct_emissions = reference['PRESENT_AND_AVAILABLE']

    summary = {
        'frames': len(rows),
        'positives': positives,
        'negatives': negatives,
        'presence': {
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'unknown_rejected': unknown,
            'precision': _rate(tp, tp + fp),
            'recall': _rate(tp, tp + fn),
            'evaluable_positive_coverage': _rate(tp + fn, positives),
            'negative_coverage': _rate(fp + tn, negatives),
            'counted_denominator': tp + fp + fn + tn,
        },
        'reference': {
            'available_denominator': ref_avail,
            'unavailable_denominator': ref_unavail,
            'correct_keypoint_emissions': ref_correct_emissions,
            'coverage': _rate(ref_correct_emissions, ref_avail),
            'false_reference_rate': _rate(reference['UNAVAILABLE_EMITTED_KEYPOINT'], ref_unavail),
            'not_labelled': reference['NOT_LABELLED'],
            'anchor_error': _error_stats(anchors),
        },
        'identity': {
            'claims': claims,
            'correct_claims': correct_claims,
            'precision': _rate(correct_claims, claims),
            'recall': _rate(correct_claims, positives),
            'high_confidence_false_matches': high_conf_false_matches,
            'negative_denominator': negatives,
            'false_match_rate': _rate(high_conf_false_matches, negatives),
            'evaluable': claims > 0 or negatives > 0,
        },
        'joint': {
            'narrow_denominator': joint_denominator,
            'narrow_tp': joint_tp,
            'narrow_rate': _rate(joint_tp, joint_denominator),
            'all_positive_lower_bound': _rate(joint_tp, positives),
            'coverage': _rate(joint_denominator, positives),
            'fail_reasons': dict(sorted(joint_failures.items())),
        },
    }
    gaps = [name for name, value in (
        ('presence_tp_plus_fn', tp + fn),
        ('reference_available', ref_avail),
        ('identity_negatives', negatives),
        ('joint_narrow', joint_denominator),
    ) if value == 0]
    summary['metric_status'] = 'INCOMPLETE' if gaps else 'COMPUTED'
    summary['insufficient_denominators'] = gaps
    return summary
