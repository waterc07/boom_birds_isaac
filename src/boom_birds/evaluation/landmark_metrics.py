"""Metric definitions for the pre-training landmark experiment (denominator audit).

This module makes the denominator rules from
docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md
executable and auditable.  It contains no model, no training, no detector and no
ground-truth channel into any deployed actor; it only scores already-recorded
predictions against independent annotations.

Corrected denominator rules (see
docs/reports/perception/TRAINING_EVAL_TOOLING_20261104.md for the old/new
comparison):

1. A prediction of UNKNOWN/REJECTED on a GT-observable positive is a MISS.  It
   stays inside the recall, reference-coverage and joint denominators, and is
   additionally listed by prediction status and reject reason.  It is never
   silently dropped and never counted as a true negative.
2. An annotation-side unobservable frame (undecidable=true, fully occluded target
   with no visible GT box, or ambiguous=true) is excluded from the presence
   fourfold and from every denominator.  It is reported separately as
   GT_UNOBSERVABLE with a reason.  GT_UNOBSERVABLE (annotation state) and
   prediction UNKNOWN (model state) are counted in separate buckets.
3. A prediction of UNKNOWN/REJECTED on a GT-absent frame is not credited as TN;
   the frame stays in the negative denominator, so negative coverage cannot be
   inflated by a non-functioning detector.
4. A positive whose GT reference point is annotated UNAVAILABLE is still
   presence/recall material, but it never enters the anchor/bearing error
   denominators.  Emitting a keypoint there is a semantic error (false
   reference), not an accuracy issue.
5. The joint narrow denominator is the set of GT-observable positives with a
   complete bbox+reference label.  A rejected/UNKNOWN prediction is a joint
   failure inside that denominator; an unlabelled reference only lowers joint
   coverage.
6. Stratified reporting exposes the worst condition with numerator and
   denominator (insufficient strata are marked, not ranked as worst).

Units: bbox in pixels (origin top-left, xywh), keypoints in pixels, bearings in
degrees from the image bearing formula atan2(x - cx_px, fx_px).
"""
from collections import Counter
import math

__all__ = [
    'MetricDefinitionError',
    'PRED_STATUSES',
    'REFERENCE_LABELS',
    'GT_UNOBSERVABLE_REASONS',
    'image_bearing_deg',
    'error_stats',
    'evaluate_frame',
    'summarize',
    'stratified_summary',
]

PRED_STATUSES = ('DETECTED', 'NOT_DETECTED', 'UNKNOWN', 'REJECTED')
REFERENCE_LABELS = (None, 'VISIBLE', 'UNAVAILABLE')
GT_UNOBSERVABLE_REASONS = ('UNDECIDABLE', 'FULL_OCCLUSION', 'AMBIGUOUS',
                           'NO_VISIBLE_GT_BBOX')
GT_REQUIRED = ('frame_id', 'present', 'landmark_id', 'bbox_xywh', 'reference')

PRESENCE_TP = 'TP'
PRESENCE_FP = 'FP'
PRESENCE_FN = 'FN'
PRESENCE_TN = 'TN'
PRESENCE_GT_UNOBSERVABLE = 'GT_UNOBSERVABLE'
PRESENCE_NEGATIVE_UNOBSERVABLE = 'NEGATIVE_UNOBSERVABLE'

#: primary metrics used by the stratified "worst condition" report, ordered by
#: priority; each entry is (public name, numerator path, denominator path).
STRATIFIED_METRICS = (
    ('joint_narrow_rate', ('joint', 'narrow_tp'), ('joint', 'narrow_denominator')),
    ('presence_recall', ('presence', 'tp'), None),
    ('reference_coverage', ('reference', 'correct_keypoint_emissions'),
     ('reference', 'available_denominator')),
)


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


def image_bearing_deg(x_px, *, fx_px, cx_px):
    """Image bearing in degrees; an image angle, not a world bearing/distance."""
    return math.degrees(math.atan2(float(x_px) - float(cx_px), float(fx_px)))


def error_stats(values, unit='px'):
    """median / P90 / max with the sample count as an explicit denominator."""
    values = [float(v) for v in values]
    if not values:
        return {'count': 0, 'median_' + unit: None, 'p90_' + unit: None,
                'max_' + unit: None}
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        median = ordered[n // 2]
    else:
        median = 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
    p90 = ordered[max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))]
    return {'count': n, 'median_' + unit: median, 'p90_' + unit: p90,
            'max_' + unit: ordered[-1]}


def _validate(gt, pred, tau_iou, tau_px, tau_conf, fx_px, cx_px):
    if not isinstance(gt, dict) or not isinstance(pred, dict):
        raise MetricDefinitionError('gt and pred must be dicts')
    missing = [key for key in GT_REQUIRED if key not in gt]
    if missing:
        raise MetricDefinitionError('ground truth missing fields: '
                                    + ', '.join(missing))
    if not isinstance(gt['present'], bool):
        raise MetricDefinitionError('gt.present must be bool')
    undecidable = gt.get('undecidable', False)
    ambiguous = gt.get('ambiguous', False)
    if not isinstance(undecidable, bool) or not isinstance(ambiguous, bool):
        raise MetricDefinitionError('gt.undecidable / gt.ambiguous must be bool')
    if undecidable and gt['present']:
        raise MetricDefinitionError('present=true cannot be combined with '
                                    'undecidable=true')
    if undecidable and gt['bbox_xywh'] is not None:
        raise MetricDefinitionError('undecidable ground truth must not carry a bbox')
    if undecidable and gt['reference'] is not None:
        raise MetricDefinitionError('undecidable ground truth must not carry a '
                                    'reference label')
    if gt['present']:
        bbox = gt['bbox_xywh']
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4):
            raise MetricDefinitionError('present gt requires bbox_xywh of length 4')
        if not gt['landmark_id']:
            raise MetricDefinitionError('present gt requires landmark_id')
        if bbox is None and gt['reference'] == 'VISIBLE':
            raise MetricDefinitionError('present gt without a visible bbox cannot '
                                        'declare a VISIBLE reference')
    else:
        if gt['reference'] is not None:
            raise MetricDefinitionError('absent target must not carry a reference label')
        if gt['bbox_xywh'] is not None:
            raise MetricDefinitionError('absent target must not carry a bbox')
    if gt['reference'] not in REFERENCE_LABELS:
        raise MetricDefinitionError('unsupported gt.reference: %r'
                                    % (gt['reference'],))
    status = pred.get('status')
    if status not in PRED_STATUSES:
        raise MetricDefinitionError('unsupported prediction status: %r' % (status,))
    _check_range('tau_iou', tau_iou, 0.0, 1.0)
    _check_range('tau_px', tau_px, 0.0, 1e6)
    _check_range('tau_conf', tau_conf, 0.0, 1.0)
    if (fx_px is None) != (cx_px is None):
        raise MetricDefinitionError('fx_px and cx_px must be provided together')
    if fx_px is not None:
        if float(fx_px) <= 0:
            raise MetricDefinitionError('fx_px must be positive')
        _check_range('cx_px', cx_px, -1e6, 1e6)


def _gt_observability(gt):
    """Return (observable, reason).  Unobservable GT never enters a denominator."""
    if gt.get('undecidable') is True:
        return False, 'UNDECIDABLE'
    if gt.get('ambiguous') is True:
        return False, 'AMBIGUOUS'
    if gt['present'] and gt['bbox_xywh'] is None:
        if gt.get('visibility') == 'OCCLUDED':
            return False, 'FULL_OCCLUSION'
        return False, 'NO_VISIBLE_GT_BBOX'
    return True, None


def evaluate_frame(gt, pred, *, tau_iou, reference_px, tau_px, tau_conf,
                   fx_px=None, cx_px=None, strata=None):
    """Classify one frame against the frozen presence/reference/identity/joint rules."""
    _validate(gt, pred, tau_iou, tau_px, tau_conf, fx_px, cx_px)
    status = pred['status']
    bbox = pred.get('bbox_xywh')
    keypoint = pred.get('keypoint_px')
    present = bool(gt['present'])
    gt_bbox = gt['bbox_xywh']
    ref_label = gt['reference']
    score = pred.get('score')
    claim = pred.get('landmark_id') is not None
    observable, unobservable_reason = _gt_observability(gt)
    unobservable_pred = status in ('UNKNOWN', 'REJECTED')

    row = {
        'frame_id': gt['frame_id'],
        'gt_present': present,
        'gt_bbox_present': gt_bbox is not None,
        'gt_observable': observable,
        'gt_unobservable_reason': unobservable_reason,
        'pred_status': status,
        'pred_reject_reason': pred.get('reject_reason'),
        'counted_in_confusion': False,
        'presence_class': PRESENCE_GT_UNOBSERVABLE,
        'pred_present': None,
        'bbox_iou': None,
        'reference_class': 'GT_UNOBSERVABLE',
        'reference_correct': None,
        'gt_reference_available': False,
        'gt_reference_unavailable': False,
        'keypoint_emitted': keypoint is not None,
        'anchor_error_px': None,
        'dx_px': None,
        'dy_px': None,
        'gt_bearing_deg': None,
        'pred_bearing_deg': None,
        'bearing_error_deg': None,
        'identity_claim': claim,
        'identity_correct': None,
        'high_confidence_false_match': False,
        'joint_evaluable': False,
        'joint_ok': None,
        'joint_fail_reason': None,
        'joint_branch': None,
        'strata': dict(strata or {}),
    }
    if not observable:
        return row

    row['keypoint_emitted'] = keypoint is not None
    row['gt_reference_available'] = ref_label == 'VISIBLE'
    row['gt_reference_unavailable'] = ref_label == 'UNAVAILABLE'

    # --- presence -------------------------------------------------------
    if unobservable_pred:
        presence_class = PRESENCE_FN if present else PRESENCE_NEGATIVE_UNOBSERVABLE
        pred_present = None
    else:
        pred_present = (status == 'DETECTED' and bbox is not None
                        and (not present or _iou(bbox, gt_bbox) >= float(tau_iou)))
        if present:
            presence_class = PRESENCE_TP if pred_present else PRESENCE_FN
        else:
            presence_class = PRESENCE_FP if pred_present else PRESENCE_TN
    row['presence_class'] = presence_class
    row['pred_present'] = pred_present
    row['counted_in_confusion'] = presence_class in (PRESENCE_TP, PRESENCE_FP,
                                                     PRESENCE_FN, PRESENCE_TN)
    if present and gt_bbox is not None and bbox is not None:
        row['bbox_iou'] = _iou(bbox, gt_bbox)

    # --- reference ------------------------------------------------------
    if ref_label is None:
        reference_class = 'NOT_LABELLED'
        reference_correct = None
    elif ref_label == 'VISIBLE':
        if keypoint is None:
            reference_class = 'PRESENT_NO_KEYPOINT'
            reference_correct = False
        elif reference_px is None:
            raise MetricDefinitionError('VISIBLE gt reference with an emitted '
                                        'keypoint requires reference_px')
        else:
            dx = float(keypoint[0]) - float(reference_px[0])
            dy = float(keypoint[1]) - float(reference_px[1])
            anchor_error = math.hypot(dx, dy)
            row['anchor_error_px'] = anchor_error
            row['dx_px'] = dx
            row['dy_px'] = dy
            reference_correct = anchor_error <= float(tau_px)
            reference_class = ('PRESENT_AND_AVAILABLE' if reference_correct
                               else 'PRESENT_WRONG_ANCHOR')
            if fx_px is not None:
                gt_bearing = image_bearing_deg(reference_px[0], fx_px=fx_px,
                                               cx_px=cx_px)
                pred_bearing = image_bearing_deg(keypoint[0], fx_px=fx_px,
                                                 cx_px=cx_px)
                row['gt_bearing_deg'] = gt_bearing
                row['pred_bearing_deg'] = pred_bearing
                row['bearing_error_deg'] = abs(pred_bearing - gt_bearing)
    else:  # UNAVAILABLE: GT reference point is not visible
        if keypoint is None:
            reference_class = 'UNAVAILABLE_DECLARED'
            reference_correct = True
        else:
            reference_class = 'UNAVAILABLE_EMITTED_KEYPOINT'
            reference_correct = False
    row['reference_class'] = reference_class
    row['reference_correct'] = reference_correct

    # --- identity -------------------------------------------------------
    identity_correct = None
    if claim:
        identity_correct = bool(present and pred.get('landmark_id') == gt['landmark_id'])
    row['identity_correct'] = identity_correct
    row['high_confidence_false_match'] = bool(
        (not present) and claim and score is not None
        and float(score) >= float(tau_conf))

    # --- joint ----------------------------------------------------------
    joint_evaluable = bool(gt_bbox is not None and ref_label is not None)
    row['joint_evaluable'] = joint_evaluable
    if joint_evaluable:
        row['joint_branch'] = ('AVAILABILITY_DECLARATION'
                               if ref_label == 'UNAVAILABLE' else 'LOCALIZATION')
    if joint_evaluable:
        if presence_class != PRESENCE_TP:
            joint_ok = False
            joint_fail_reason = 'PRESENCE'
        elif identity_correct is not True:
            joint_ok = False
            joint_fail_reason = 'IDENTITY'
        elif reference_correct is not True:
            joint_ok = False
            joint_fail_reason = 'REFERENCE'
        else:
            joint_ok = True
            joint_fail_reason = None
        row['joint_ok'] = joint_ok
        row['joint_fail_reason'] = joint_fail_reason
    return row


def _rate(numerator, denominator):
    return (float(numerator) / denominator) if denominator else None


def _metric_entries(summary):
    """Flat numerator/denominator view used by the worst-condition report."""
    presence = summary['presence']
    entries = {}
    for name, num_path, den_path in STRATIFIED_METRICS:
        numerator = summary[num_path[0]][num_path[1]]
        if name == 'presence_recall':
            denominator = presence['tp'] + presence['fn']
        else:
            denominator = summary[den_path[0]][den_path[1]]
        if name == 'joint_narrow_rate':
            rate = summary['joint']['narrow_rate']
        elif name == 'presence_recall':
            rate = presence['recall']
        else:
            rate = summary['reference']['coverage']
        entries[name] = {'numerator': numerator, 'denominator': denominator,
                         'rate': rate}
    return entries


def summarize(rows):
    """Aggregate evaluated frames with explicit numerators and denominators."""
    rows = list(rows)
    presence = Counter()
    reference = Counter()
    joint_failures = Counter()
    fn_by_pred_status = Counter()
    unknown_by_status = Counter()
    unknown_by_reason = Counter()
    gt_unobservable_reasons = Counter()
    anchors = []
    bearings = []
    anchors_correct = []
    bearings_correct = []
    bbox_ious = []

    positives = 0
    negatives = 0
    gt_unobservable = 0
    negative_unobservable = 0
    bbox_denominator = 0
    unknown_on_positive = 0
    unknown_on_negative = 0
    unknown_on_gt_unobservable = 0
    joint_denominator = 0
    joint_tp = 0
    claims = 0
    correct_claims = 0
    claims_on_gt_unobservable = 0
    high_conf_false_matches = 0
    ref_available = 0
    ref_unavailable = 0
    ref_not_labelled = 0
    ref_correct_emissions = 0

    for row in rows:
        presence[row['presence_class']] += 1
        if row['presence_class'] == PRESENCE_GT_UNOBSERVABLE:
            gt_unobservable += 1
            gt_unobservable_reasons[row['gt_unobservable_reason']
                                    or 'UNSPECIFIED'] += 1
        if row['presence_class'] == PRESENCE_NEGATIVE_UNOBSERVABLE:
            negative_unobservable += 1
        if row['gt_observable']:
            if row['gt_present']:
                positives += 1
            else:
                negatives += 1
        if row['bbox_iou'] is not None:
            bbox_ious.append(row['bbox_iou'])
        if row['gt_observable'] and row['gt_present'] and row['presence_class'] == PRESENCE_FN:
            fn_by_pred_status[row['pred_status']] += 1
        if row['gt_observable'] and row['gt_present'] and row['gt_bbox_present']:
            bbox_denominator += 1
        if row['pred_status'] in ('UNKNOWN', 'REJECTED'):
            unknown_by_status[row['pred_status']] += 1
            unknown_by_reason[row['pred_reject_reason'] or 'UNSPECIFIED'] += 1
            if row['presence_class'] == PRESENCE_GT_UNOBSERVABLE:
                unknown_on_gt_unobservable += 1
            elif row['gt_present']:
                unknown_on_positive += 1
            else:
                unknown_on_negative += 1
        reference[row['reference_class']] += 1
        if row['gt_observable'] and row['gt_present']:
            if row['reference_class'] == 'NOT_LABELLED':
                ref_not_labelled += 1
            elif row['reference_class'].startswith('PRESENT_'):
                ref_available += 1
                if row['reference_class'] == 'PRESENT_AND_AVAILABLE':
                    ref_correct_emissions += 1
            elif row['reference_class'].startswith('UNAVAILABLE_'):
                ref_unavailable += 1
        if row['anchor_error_px'] is not None:
            anchors.append(row['anchor_error_px'])
            if row['reference_correct']:
                anchors_correct.append(row['anchor_error_px'])
        if row['bearing_error_deg'] is not None:
            bearings.append(row['bearing_error_deg'])
            if row['reference_correct']:
                bearings_correct.append(row['bearing_error_deg'])
        if row['gt_observable']:
            if row['identity_claim']:
                claims += 1
                if row['identity_correct']:
                    correct_claims += 1
            if row['high_confidence_false_match']:
                high_conf_false_matches += 1
        elif row['identity_claim']:
            claims_on_gt_unobservable += 1
        if row['joint_evaluable']:
            joint_denominator += 1
            if row['joint_ok']:
                joint_tp += 1
            else:
                joint_failures[row['joint_fail_reason'] or 'UNSPECIFIED'] += 1

    tp = presence[PRESENCE_TP]
    fp = presence[PRESENCE_FP]
    fn = presence[PRESENCE_FN]
    tn = presence[PRESENCE_TN]
    accountable = (tp + fp + fn + tn + presence[PRESENCE_GT_UNOBSERVABLE]
                   + presence[PRESENCE_NEGATIVE_UNOBSERVABLE])
    if accountable != len(rows):
        raise MetricDefinitionError('frame accounting mismatch: %d != %d'
                                    % (accountable, len(rows)))

    iou_count = len(bbox_ious)
    iou_ordered = sorted(bbox_ious)
    iou_stats = {
        'count': iou_count,
        'denominator': bbox_denominator,
        'median': (_median(iou_ordered) if iou_ordered else None),
        'p90': (_p90(iou_ordered) if iou_ordered else None),
        'max': (iou_ordered[-1] if iou_ordered else None),
    }

    summary = {
        'frames': len(rows),
        'denominators': {
            'frames': len(rows),
            'positives': positives,
            'negatives': negatives,
            'gt_unobservable': gt_unobservable,
            'negative_unobservable': negative_unobservable,
            'reference_available': ref_available,
            'reference_unavailable': ref_unavailable,
            'reference_not_labelled': ref_not_labelled,
            'joint_evaluable': joint_denominator,
            'positive_frames_with_gt_bbox': bbox_denominator,
            'identity_claims': claims,
        },
        'gt_unobservable_by_reason': dict(sorted(gt_unobservable_reasons.items())),
        'presence': {
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'gt_unobservable': presence[PRESENCE_GT_UNOBSERVABLE],
            'negative_unobservable': presence[PRESENCE_NEGATIVE_UNOBSERVABLE],
            'precision': _rate(tp, tp + fp),
            'recall': _rate(tp, tp + fn),
            'negative_coverage': _rate(tn, negatives),
            'fn_by_pred_status': dict(sorted(fn_by_pred_status.items())),
            'unknown_rejected': {
                'total': sum(unknown_by_status.values()),
                'on_positive': unknown_on_positive,
                'on_negative': unknown_on_negative,
                'on_gt_unobservable': unknown_on_gt_unobservable,
                'by_status': dict(sorted(unknown_by_status.items())),
                'by_reason': dict(sorted(unknown_by_reason.items())),
            },
            'bbox_iou_diagnostic': iou_stats,
        },
        'reference': {
            'available_denominator': ref_available,
            'unavailable_denominator': ref_unavailable,
            'not_labelled': ref_not_labelled,
            'correct_keypoint_emissions': ref_correct_emissions,
            'wrong_anchor_emissions': _count_reference(rows, ('PRESENT_WRONG_ANCHOR',)),
            'no_keypoint_emissions': _count_reference(rows, ('PRESENT_NO_KEYPOINT',)),
            'coverage': _rate(ref_correct_emissions, ref_available),
            'false_reference_rate': _rate(
                reference['UNAVAILABLE_EMITTED_KEYPOINT'], ref_unavailable),
            'anchor_error_px': error_stats(anchors, unit='px'),
            'anchor_error_px_correct_only': error_stats(anchors_correct, unit='px'),
            'bearing_error_deg': error_stats(bearings, unit='deg'),
            'bearing_error_deg_correct_only': error_stats(bearings_correct,
                                                          unit='deg'),
        },
        'identity': {
            'claims': claims,
            'correct_claims': correct_claims,
            'claims_on_gt_unobservable': claims_on_gt_unobservable,
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
        ('reference_available', ref_available),
        ('identity_negatives', negatives),
        ('joint_narrow', joint_denominator),
    ) if value == 0]
    summary['metric_status'] = 'INCOMPLETE' if gaps else 'COMPUTED'
    summary['insufficient_denominators'] = gaps
    return summary


def _median(ordered):
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def _p90(ordered):
    n = len(ordered)
    return ordered[max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))]


def _count_reference(rows, classes):
    return sum(1 for row in rows if row['reference_class'] in classes)


def stratified_summary(rows, dimensions=('family',)):
    """Per-dimension summaries plus the worst condition of each dimension.

    Ties are broken toward the larger denominator (more evidence), then toward
    the lexicographically smaller stratum name.  Strata whose primary
    denominator is zero are reported as INSUFFICIENT_DENOMINATOR and are never
    ranked as the worst condition.
    """
    rows = list(rows)
    dimensions = list(dimensions)
    report = {'overall': summarize(rows), 'strata': {}, 'worst_conditions': {}}
    for dimension in dimensions:
        groups = {}
        for row in rows:
            key = (row.get('strata') or {}).get(dimension)
            if key is None:
                key = 'UNSPECIFIED'
            groups.setdefault(str(key), []).append(row)
        summaries = {name: summarize(items)
                     for name, items in sorted(groups.items())}
        report['strata'][dimension] = summaries
        worst = {}
        for name, _, _ in STRATIFIED_METRICS:
            best = None
            insufficient = None
            for stratum_name, summary in summaries.items():
                entry = _metric_entries(summary)[name]
                record = {
                    'stratum': stratum_name,
                    'numerator': entry['numerator'],
                    'denominator': entry['denominator'],
                    'rate': entry['rate'],
                }
                if not entry['denominator']:
                    record['status'] = 'INSUFFICIENT_DENOMINATOR'
                    if insufficient is None:
                        insufficient = record
                    continue
                record['status'] = 'WORST'
                rank = (entry['rate'], -entry['denominator'], stratum_name)
                if best is None or rank < best[0]:
                    best = (rank, record)
            if best is not None:
                worst[name] = best[1]
            elif insufficient is not None:
                worst[name] = insufficient
            else:
                worst[name] = {'stratum': None, 'numerator': None,
                               'denominator': 0, 'rate': None,
                               'status': 'NO_STRATA'}
        report['worst_conditions'][dimension] = worst
    return report