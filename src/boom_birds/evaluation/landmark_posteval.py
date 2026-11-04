"""Post-evaluation diagnosis for the bounded landmark experiment (task T13).

This module does NOT rerun the frozen exploratory evaluation. It only reads the
already-saved predictions, the already-saved labels and (optionally) the frame
images, and separates four capabilities that the old single 'joint' number
conflated:

1. presence              -- class detection on a positive / rejection on an
                            absent frame;
2. identity              -- a landmark_id claim exists and is correct; the
                            precision denominator (claims) and the positive
                            recall denominator are different and both reported;
3. reference availability -- the model emits a keypoint only when the ground
                            truth reference point is available, and declares it
                            unavailable when it is not;
4. localization accuracy -- among GT-reference-available positives, how many
                            emitted keypoints are within tau_px of the GT
                            reference point.

Joint is decomposed explicitly:

- LOCALIZED       : joint-ok because the GT reference point is available and
                    the emitted keypoint is within tau_px;
- CORRECT_REFUSAL : joint-ok because the GT reference point is unavailable and
                    the model correctly emits no keypoint. This case is joint-ok
                    but NEVER enters the localization error denominator and is
                    NOT part of reference coverage;
- FAIL_*          : presence / identity / reference failures inside the joint
                    denominator.

The joint composite rate is therefore the sum of two different capabilities and
must never be quoted as a localization rate. The localization rate uses only
the GT-reference-available positive denominator.

Denominators are auditable: prediction-side UNKNOWN/REJECTED on a positive stays
in the presence, reference and joint denominators as a miss; annotation-side
GT_UNOBSERVABLE is excluded from the presence fourfold and every denominator but
is reported separately, including its identity claims; a presence miss on a
positive with an available reference stays in the reference coverage
denominator.

All quantities are image-domain (pixels, image bearing degrees) and are not
world bearings, distances, board measurements or certification evidence.

The module is deterministic, stdlib-only (PIL is imported lazily by the CLI for
image loading and overlays) and contains no model, no training, no detector and
no ground-truth channel into any deployed actor.
"""
from collections import Counter, defaultdict
import json
import math

from boom_birds.evaluation import landmark_metrics as metrics
from boom_birds.evaluation import landmark_yolo as yolo

__all__ = [
    'STAGE_ABSENT', 'STAGE_GT_UNOBSERVABLE', 'STAGE_UNAVAILABLE_CORRECT',
    'STAGE_UNAVAILABLE_EMITTED', 'STAGE_AVAILABLE_CORRECT',
    'STAGE_AVAILABLE_WRONG_ANCHOR', 'STAGE_AVAILABLE_NO_KEYPOINT',
    'STAGE_AVAILABLE_PRESENCE_MISS',
    'JOINT_LOCALIZED', 'JOINT_CORRECT_REFUSAL', 'JOINT_FAIL_PRESENCE',
    'JOINT_FAIL_IDENTITY', 'JOINT_FAIL_REFERENCE',
    'JOINT_FAIL_FALSE_REFERENCE', 'JOINT_NOT_ELIGIBLE',
    'STRATA_DIMENSIONS', 'PRESENCE_GT_UNOBSERVABLE',
    'strict_green_mask', 'green_components',
    'analyze_frame', 'aggregate', 'bearing_flip_counts',
    'green_anchor_audit', 'tiny_reannotation_plan', 'blind_frame_list',
    'reproduction_check', 'build_diagnosis', 'main',
]

SCHEMA_VERSION = 'dsh.landmark_posteval.v1'

STAGE_ABSENT = 'ABSENT'
STAGE_GT_UNOBSERVABLE = 'GT_UNOBSERVABLE'
STAGE_UNAVAILABLE_CORRECT = 'GT_UNAVAILABLE_CORRECT_DECLARATION'
STAGE_UNAVAILABLE_EMITTED = 'GT_UNAVAILABLE_EMITTED_KEYPOINT'
STAGE_AVAILABLE_CORRECT = 'AVAILABLE_CORRECT'
STAGE_AVAILABLE_WRONG_ANCHOR = 'AVAILABLE_WRONG_ANCHOR'
STAGE_AVAILABLE_NO_KEYPOINT = 'AVAILABLE_NO_KEYPOINT'
STAGE_AVAILABLE_PRESENCE_MISS = 'AVAILABLE_PRESENCE_MISS'

JOINT_LOCALIZED = 'LOCALIZED'
JOINT_CORRECT_REFUSAL = 'CORRECT_REFUSAL'
JOINT_FAIL_PRESENCE = 'FAIL_PRESENCE'
JOINT_FAIL_IDENTITY = 'FAIL_IDENTITY'
JOINT_FAIL_REFERENCE = 'FAIL_REFERENCE'
JOINT_FAIL_FALSE_REFERENCE = 'FAIL_FALSE_REFERENCE'
JOINT_NOT_ELIGIBLE = 'NOT_ELIGIBLE'

STRATA_DIMENSIONS = ('family', 'scale', 'truncation', 'visibility',
                     'reference_availability')

PRESENCE_GT_UNOBSERVABLE = metrics.PRESENCE_GT_UNOBSERVABLE

GREEN_ANCHOR_MATCH_RADIUS_PX = 8.0

TINY_CRITERIA = {
    'blind': True,
    'selection_source': 'development labels only (dev train/val); the final '
                        'exploratory predictions/metrics are never used to '
                        'choose frames',
    'annotation_spec': 'configs/perception/landmark_annotation_spec_v2_1.json',
    'bbox_convention': 'spec v2.1 tower box: head/light-rack + tan body + '
                       'attached stepped base, clipped at every true image '
                       'edge; independent visual judgement, no capture '
                       'projection prior, no original label',
    'reference_rule': 'strict green cue only: g >= 90, g - r >= 25, '
                      'g - b >= 25, largest 4-connected component; keypoint '
                      'non-null ONLY when green_pixels >= 3 AND the green '
                      'roof-light is visually confirmed; otherwise keypoint '
                      'null + reference_status=UNAVAILABLE + reason',
    'undecidable_policy': 'presence cannot be decided -> undecidable=true, no '
                          'bbox/keypoint, no negative_type; never guess',
    'ambiguous_policy': 'multiple plausible target candidates -> '
                        'ambiguous=true and candidates[]; never guess a '
                        'keypoint',
    'truncation_policy': 'record all four edges (left/right/top/bottom) with '
                         'truncation_source=ANNOTATOR_VISUAL',
    'independence': 'record annotator.independent_of_model_dev=true, '
                    'independent_of_detector_cue=false when the green '
                    'reference comes from the same strict-green rule; '
                    'agreement with existing anchors is SAME-SOURCE '
                    'reproducibility, not independent physical accuracy',
    'disagreement_metrics': ['presence agreement', 'reference-availability '
                             'agreement', 'bbox IoU', 'keypoint Euclidean px',
                             'image bearing deg', 'truncation-edge agreement'],
    'pre_registered_pass_criteria': {
        'presence_agreement_min': 0.90,
        'reference_availability_agreement_min': 0.90,
        'keypoint_median_px_max': 2.0,
        'keypoint_p90_px_max': 4.0,
        'bbox_iou_median_min': 0.50,
    },
    'size_note': 'development target max-side floor is about 9.3 px; a pure '
                 '4-8 px target range is absent from development, so any '
                 'sub-9.3 px annotatability conclusion is UNKNOWN/extrapolated',
}


def _median(ordered):
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def _p90(ordered):
    n = len(ordered)
    return ordered[max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))]


def _stats(values, unit):
    values = [float(v) for v in values]
    if not values:
        return {'count': 0, 'median_' + unit: None, 'p90_' + unit: None,
                'max_' + unit: None}
    ordered = sorted(values)
    return {'count': len(ordered), 'median_' + unit: _median(ordered),
            'p90_' + unit: _p90(ordered), 'max_' + unit: ordered[-1]}


def _signed_stats(values, unit='px'):
    values = [float(v) for v in values]
    if not values:
        return {'count': 0, 'mean_' + unit: None, 'median_' + unit: None,
                'mean_abs_' + unit: None, 'positive': 0, 'negative': 0,
                'zero': 0}
    ordered = sorted(values)
    return {
        'count': len(values),
        'mean_' + unit: sum(values) / len(values),
        'median_' + unit: _median(ordered),
        'mean_abs_' + unit: sum(abs(v) for v in values) / len(values),
        'positive': sum(1 for v in values if v > 0),
        'negative': sum(1 for v in values if v < 0),
        'zero': sum(1 for v in values if v == 0),
    }


def _rate(numerator, denominator):
    return (float(numerator) / denominator) if denominator else None


def _threshold_key(value):
    text = '%.3f' % float(value)
    text = text.rstrip('0')
    if text.endswith('.'):
        text += '0'
    return text


def _green_pixel(rgb, g_min, g_minus_r, g_minus_b):
    r, g, b = rgb
    return (g >= g_min and (g - r) >= g_minus_r and (g - b) >= g_minus_b)


def strict_green_mask(pixels, *, g_min=90.0, g_minus_r=25.0, g_minus_b=25.0):
    """Boolean mask of the frozen spec v2.1 strict-green cue.

    pixels is a sequence of rows of (r, g, b) tuples/lists. The rule is
    g >= g_min and g - r >= g_minus_r and g - b >= g_minus_b.
    """
    mask = []
    for row in pixels:
        mask.append([_green_pixel(tuple(int(c) for c in px), g_min, g_minus_r,
                                  g_minus_b) for px in row])
    return mask


def green_components(pixels, *, g_min=90.0, g_minus_r=25.0, g_minus_b=25.0,
                     min_area=1):
    """4-connected strict-green components, sorted by area (descending).

    Each component: area, centroid_x, centroid_y, u_min, u_max, v_min, v_max.
    Deterministic order: area desc, then v_min, then u_min.
    """
    mask = strict_green_mask(pixels, g_min=g_min, g_minus_r=g_minus_r,
                             g_minus_b=g_minus_b)
    height = len(mask)
    width = len(mask[0]) if height else 0
    seen = [[False] * width for _ in range(height)]
    components = []
    for v in range(height):
        for u in range(width):
            if not mask[v][u] or seen[v][u]:
                continue
            stack = [(u, v)]
            seen[v][u] = True
            area = 0
            sum_u = 0
            sum_v = 0
            u_min = u_max = u
            v_min = v_max = v
            while stack:
                cu, cv = stack.pop()
                area += 1
                sum_u += cu
                sum_v += cv
                if cu < u_min:
                    u_min = cu
                if cu > u_max:
                    u_max = cu
                if cv < v_min:
                    v_min = cv
                if cv > v_max:
                    v_max = cv
                for du, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nu, nv = cu + du, cv + dv
                    if 0 <= nu < width and 0 <= nv < height:
                        if mask[nv][nu] and not seen[nv][nu]:
                            seen[nv][nu] = True
                            stack.append((nu, nv))
            if area >= min_area:
                components.append({
                    'area': area,
                    'centroid_x': sum_u / area,
                    'centroid_y': sum_v / area,
                    'u_min': u_min, 'u_max': u_max,
                    'v_min': v_min, 'v_max': v_max,
                })
    components.sort(key=lambda c: (-c['area'], c['v_min'], c['u_min']))
    return components


def analyze_frame(annotation, observation, *, tau_px, tau_iou, tau_conf,
                  tau_kpt=0.5, fx_px=None, cx_px=None):
    """Classify one saved (annotation, observation) pair into explicit stages.

    The base presence/identity/reference/joint classification is delegated to
    landmark_metrics.evaluate_frame (same code path as the frozen evaluation);
    this function adds the reference stage, signed localization error and the
    joint decomposition on top.
    """
    gt, reference_px, strata = yolo.ground_truth_from_annotation(annotation)
    pred = yolo.observation_to_metric_prediction(observation)
    base = metrics.evaluate_frame(
        gt, pred, tau_iou=tau_iou, reference_px=reference_px, tau_px=tau_px,
        tau_conf=tau_conf, fx_px=fx_px, cx_px=cx_px, strata=strata)
    row = dict(base)
    geometry = annotation.get('geometry') or {}
    row['strata'] = dict(strata)
    row['family'] = strata['family']
    row['group_id'] = strata['group_id']
    row['image'] = annotation.get('image')
    row['gt_reference_source'] = geometry.get('reference_source')
    row['gt_bbox_source'] = geometry.get('bbox_source')
    row['gt_bbox_xywh'] = (list(gt['bbox_xywh'])
                           if gt['bbox_xywh'] is not None else None)
    row['gt_reference_px'] = (list(reference_px)
                              if reference_px is not None else None)
    row['pred_bbox_xywh'] = (list(observation.get('bbox_xywh'))
                             if observation.get('bbox_xywh') is not None
                             else None)
    row['pred_keypoint_px'] = (list(observation.get('keypoint_px'))
                               if observation.get('keypoint_px') is not None
                               else None)
    confusers = annotation.get('confusers') or []
    row['confuser_count'] = len(confusers)
    row['verified_confuser_count'] = sum(
        1 for item in confusers if item.get('verified') is True)

    kpt = observation.get('keypoint_px')
    kpt_conf = observation.get('keypoint_confidence')
    row['keypoint_confidence'] = (None if kpt_conf is None else float(kpt_conf))
    gt_present = bool(gt['present'])
    observable = bool(base['gt_observable'])
    reference_available = (gt['reference'] == 'VISIBLE') if gt_present else None
    row['gt_reference_available'] = reference_available
    row['visible_confuser_count'] = sum(
        1 for item in confusers if item.get('verified') is not True)

    suppressed = (kpt is None and kpt_conf is not None
                  and float(kpt_conf) < float(tau_kpt))
    row['kpt_suppressed_by_confidence'] = bool(suppressed)

    if not observable:
        stage = STAGE_GT_UNOBSERVABLE
    elif not gt_present:
        stage = STAGE_ABSENT
    elif not reference_available:
        stage = (STAGE_UNAVAILABLE_CORRECT if kpt is None
                 else STAGE_UNAVAILABLE_EMITTED)
    elif base['presence_class'] != metrics.PRESENCE_TP:
        stage = STAGE_AVAILABLE_PRESENCE_MISS
    elif kpt is None:
        stage = STAGE_AVAILABLE_NO_KEYPOINT
    elif base['reference_class'] == 'PRESENT_AND_AVAILABLE':
        stage = STAGE_AVAILABLE_CORRECT
    else:
        stage = STAGE_AVAILABLE_WRONG_ANCHOR
    row['reference_stage'] = stage

    row['signed_dx_px'] = None
    row['signed_dy_px'] = None
    row['signed_bearing_deg'] = None
    row['abs_bearing_deg'] = None
    if reference_available and kpt is not None and reference_px is not None:
        gx, gy = float(reference_px[0]), float(reference_px[1])
        kx, ky = float(kpt[0]), float(kpt[1])
        row['signed_dx_px'] = kx - gx
        row['signed_dy_px'] = ky - gy
        if fx_px is not None:
            gt_bearing = metrics.image_bearing_deg(gx, fx_px=fx_px,
                                                   cx_px=cx_px)
            pred_bearing = metrics.image_bearing_deg(kx, fx_px=fx_px,
                                                     cx_px=cx_px)
            row['signed_bearing_deg'] = pred_bearing - gt_bearing
            row['abs_bearing_deg'] = abs(pred_bearing - gt_bearing)

    if stage in (STAGE_ABSENT, STAGE_GT_UNOBSERVABLE,
                 STAGE_UNAVAILABLE_CORRECT, STAGE_UNAVAILABLE_EMITTED):
        row['localization_status'] = 'NOT_APPLICABLE'
    elif stage == STAGE_AVAILABLE_CORRECT:
        row['localization_status'] = 'CORRECT'
    elif stage == STAGE_AVAILABLE_WRONG_ANCHOR:
        row['localization_status'] = 'WRONG_ANCHOR'
    elif stage == STAGE_AVAILABLE_NO_KEYPOINT:
        row['localization_status'] = 'NO_KEYPOINT'
    else:
        row['localization_status'] = 'PRESENCE_MISS'

    joint_evaluable = bool(base['joint_evaluable'])
    if not joint_evaluable:
        joint_class = JOINT_NOT_ELIGIBLE
    elif base['joint_ok']:
        joint_class = (JOINT_LOCALIZED if stage == STAGE_AVAILABLE_CORRECT
                       else JOINT_CORRECT_REFUSAL)
    elif base['presence_class'] != metrics.PRESENCE_TP:
        joint_class = JOINT_FAIL_PRESENCE
    elif base['identity_correct'] is not True:
        joint_class = JOINT_FAIL_IDENTITY
    elif stage == STAGE_UNAVAILABLE_EMITTED:
        joint_class = JOINT_FAIL_FALSE_REFERENCE
    else:
        joint_class = JOINT_FAIL_REFERENCE
    row['joint_class'] = joint_class
    return row


def _group_metrics(rows):
    positives = [r for r in rows if r['gt_observable'] and r['gt_present']]
    available = [r for r in positives if r['gt_reference_available'] is True]
    unavailable = [r for r in positives if r['gt_reference_available'] is False]
    emitted = [r for r in available
               if r['reference_stage'] in (STAGE_AVAILABLE_CORRECT,
                                           STAGE_AVAILABLE_WRONG_ANCHOR)]
    correct = [r for r in emitted
               if r['reference_stage'] == STAGE_AVAILABLE_CORRECT]
    wrong = [r for r in emitted
             if r['reference_stage'] == STAGE_AVAILABLE_WRONG_ANCHOR]
    no_keypoint = [r for r in available
                   if r['reference_stage'] == STAGE_AVAILABLE_NO_KEYPOINT]
    presence_miss = [r for r in available
                     if r['reference_stage'] == STAGE_AVAILABLE_PRESENCE_MISS]
    joint = [r for r in rows if r['joint_evaluable']]
    joint_ok = [r for r in joint if r['joint_ok']]
    refusal = [r for r in joint if r['joint_class'] == JOINT_CORRECT_REFUSAL]
    return {
        'frames': len(rows),
        'positives': len(positives),
        'negatives': sum(1 for r in rows
                         if r['gt_observable'] and not r['gt_present']),
        'gt_unobservable': sum(1 for r in rows if not r['gt_observable']),
        'reference_available': len(available),
        'reference_unavailable': len(unavailable),
        'presence_tp': sum(1 for r in positives
                           if r['presence_class'] == metrics.PRESENCE_TP),
        'presence_fn': sum(1 for r in positives
                           if r['presence_class'] == metrics.PRESENCE_FN),
        'presence_fp': sum(1 for r in rows
                           if r['presence_class'] == metrics.PRESENCE_FP),
        'presence_tn': sum(1 for r in rows
                           if r['presence_class'] == metrics.PRESENCE_TN),
        'localized': len(correct),
        'wrong_anchor': len(wrong),
        'no_keypoint': len(no_keypoint),
        'presence_miss_available': len(presence_miss),
        'correct_refusal': len(refusal),
        'joint_evaluable': len(joint),
        'joint_ok': len(joint_ok),
        'localization_coverage': _rate(len(correct), len(available)),
        'localization_rate': _rate(len(correct), len(available)),
        'joint_composite_rate': _rate(len(joint_ok), len(joint)),
        'refusal_rate': _rate(len(refusal), len(unavailable)),
        'anchor_error_px_correct': _stats(
            [r['anchor_error_px'] for r in correct], 'px'),
        'anchor_error_px_wrong': _stats(
            [r['anchor_error_px'] for r in wrong], 'px'),
        'bearing_error_deg_correct': _stats(
            [r['abs_bearing_deg'] for r in correct
             if r['abs_bearing_deg'] is not None], 'deg'),
        'bearing_error_deg_wrong': _stats(
            [r['abs_bearing_deg'] for r in wrong
             if r['abs_bearing_deg'] is not None], 'deg'),
    }


def aggregate(rows):
    """Aggregate per-frame stage rows with explicit denominators."""
    rows = list(rows)
    old_metrics_recomputed = metrics.summarize(rows)

    localization_denominator = [r for r in rows
                                if r['gt_observable'] and r['gt_present']
                                and r['gt_reference_available'] is True]
    refusal_denominator = [r for r in rows
                           if r['gt_observable'] and r['gt_present']
                           and r['gt_reference_available'] is False]
    emitted = [r for r in rows
               if r['reference_stage'] in (STAGE_AVAILABLE_CORRECT,
                                           STAGE_AVAILABLE_WRONG_ANCHOR)]
    correct = [r for r in emitted
               if r['reference_stage'] == STAGE_AVAILABLE_CORRECT]
    wrong = [r for r in emitted
             if r['reference_stage'] == STAGE_AVAILABLE_WRONG_ANCHOR]
    no_keypoint = [r for r in localization_denominator
                   if r['reference_stage'] == STAGE_AVAILABLE_NO_KEYPOINT]
    presence_miss = [r for r in localization_denominator
                     if r['reference_stage'] == STAGE_AVAILABLE_PRESENCE_MISS]

    stage_counts = Counter(r['reference_stage'] for r in rows)
    joint_counts = Counter(r['joint_class'] for r in rows)
    status_counts = Counter(r['pred_status'] for r in rows)
    joint_evaluable = [r for r in rows if r['joint_evaluable']]
    joint_ok = [r for r in joint_evaluable if r['joint_ok']]
    localized = [r for r in joint_evaluable
                 if r['joint_class'] == JOINT_LOCALIZED]
    refusal = [r for r in joint_evaluable
               if r['joint_class'] == JOINT_CORRECT_REFUSAL]

    uncertain = [r for r in rows
                 if r['pred_status'] in ('UNKNOWN', 'REJECTED')]
    uncertain_on_positive = [r for r in uncertain
                             if r['gt_observable'] and r['gt_present']]
    uncertain_on_negative = [r for r in uncertain
                             if r['gt_observable'] and not r['gt_present']]
    uncertain_on_gt_unobservable = [r for r in uncertain
                                    if not r['gt_observable']]
    fn_with_available_reference = [
        r for r in localization_denominator
        if r['presence_class'] == metrics.PRESENCE_FN]
    wrong_lateral = [r for r in wrong
                     if abs(r['signed_dx_px'] or 0.0)
                     > abs(r['signed_dy_px'] or 0.0)]
    wrong_vertical = [r for r in wrong
                      if abs(r['signed_dy_px'] or 0.0)
                      >= abs(r['signed_dx_px'] or 0.0)]

    presence = old_metrics_recomputed['presence']
    identity = old_metrics_recomputed['identity']
    reference = old_metrics_recomputed['reference']

    summary = {
        'frames': len(rows),
        'audit': {
            'frames': len(rows),
            'presence_tp': presence['tp'],
            'presence_fp': presence['fp'],
            'presence_fn': presence['fn'],
            'presence_tn': presence['tn'],
            'counted_in_confusion': (presence['tp'] + presence['fp']
                                     + presence['fn'] + presence['tn']),
            'gt_unobservable': presence['gt_unobservable'],
            'negative_unobservable': presence['negative_unobservable'],
            'pred_status_counts': dict(sorted(status_counts.items())),
            'uncertain_on_positive': len(uncertain_on_positive),
            'uncertain_on_negative': len(uncertain_on_negative),
            'uncertain_on_gt_unobservable': len(uncertain_on_gt_unobservable),
            'uncertain_by_status': dict(sorted(Counter(
                r['pred_status'] for r in uncertain).items())),
            'uncertain_by_reason': dict(sorted(Counter(
                r['pred_reject_reason'] or 'UNSPECIFIED'
                for r in uncertain).items())),
            'fn_with_available_reference': len(fn_with_available_reference),
            'gt_reference_source_counts': dict(sorted(Counter(
                r['gt_reference_source'] for r in rows).items())),
            'gt_bbox_source_counts': dict(sorted(Counter(
                r['gt_bbox_source'] for r in rows).items())),
            'frames_with_confusers': sum(1 for r in rows
                                         if r['confuser_count']),
            'frames_with_verified_confusers': sum(
                1 for r in rows if r['verified_confuser_count']),
        },
        'presence': dict(presence),
        'identity': dict(identity),
        'reference_availability': {
            'available_denominator': len(localization_denominator),
            'unavailable_denominator': len(refusal_denominator),
            'correct_keypoint_emissions': len(correct),
            'wrong_anchor_emissions': len(wrong),
            'no_keypoint_emissions': len(no_keypoint),
            'presence_miss_emissions': len(presence_miss),
            'correct_declarations': stage_counts[STAGE_UNAVAILABLE_CORRECT],
            'false_reference_emissions': stage_counts[STAGE_UNAVAILABLE_EMITTED],
            'coverage': _rate(len(correct),
                              reference['available_denominator']),
            'false_reference_rate': _rate(
                stage_counts[STAGE_UNAVAILABLE_EMITTED],
                len(refusal_denominator)),
        },
        'localization': {
            'denominator': len(localization_denominator),
            'correct': len(correct),
            'wrong_anchor': len(wrong),
            'no_keypoint': len(no_keypoint),
            'presence_miss': len(presence_miss),
            'error_denominator': len(emitted),
            'coverage': _rate(len(correct), len(localization_denominator)),
            'wrong_anchor_rate': _rate(len(wrong),
                                       len(localization_denominator)),
            'no_keypoint_rate': _rate(len(no_keypoint),
                                      len(localization_denominator)),
            'presence_miss_rate': _rate(len(presence_miss),
                                        len(localization_denominator)),
            'wrong_anchor_lateral': len(wrong_lateral),
            'wrong_anchor_vertical': len(wrong_vertical),
            'anchor_error_px': _stats(
                [r['anchor_error_px'] for r in emitted], 'px'),
            'anchor_error_px_correct_only': _stats(
                [r['anchor_error_px'] for r in correct], 'px'),
            'anchor_error_px_wrong_only': _stats(
                [r['anchor_error_px'] for r in wrong], 'px'),
            'signed_dx_px': _signed_stats(
                [r['signed_dx_px'] for r in emitted
                 if r['signed_dx_px'] is not None]),
            'signed_dy_px': _signed_stats(
                [r['signed_dy_px'] for r in emitted
                 if r['signed_dy_px'] is not None]),
            'bearing_error_deg': _stats(
                [r['abs_bearing_deg'] for r in emitted
                 if r['abs_bearing_deg'] is not None], 'deg'),
            'bearing_error_deg_correct_only': _stats(
                [r['abs_bearing_deg'] for r in correct
                 if r['abs_bearing_deg'] is not None], 'deg'),
            'bearing_error_deg_wrong_only': _stats(
                [r['abs_bearing_deg'] for r in wrong
                 if r['abs_bearing_deg'] is not None], 'deg'),
            'signed_bearing_deg': _signed_stats(
                [r['signed_bearing_deg'] for r in emitted
                 if r['signed_bearing_deg'] is not None], 'deg'),
        },
        'joint': {
            'narrow_denominator': len(joint_evaluable),
            'localized': len(localized),
            'correct_refusal': len(refusal),
            'composite_tp': len(joint_ok),
            'composite_rate': _rate(len(joint_ok), len(joint_evaluable)),
            'localization_rate': _rate(len(localized),
                                       len(localization_denominator)),
            'refusal_rate': _rate(len(refusal), len(refusal_denominator)),
            'fail_presence': joint_counts[JOINT_FAIL_PRESENCE],
            'fail_identity': joint_counts[JOINT_FAIL_IDENTITY],
            'fail_reference': joint_counts[JOINT_FAIL_REFERENCE],
            'fail_false_reference': joint_counts[JOINT_FAIL_FALSE_REFERENCE],
            'not_eligible': joint_counts[JOINT_NOT_ELIGIBLE],
            'stage_counts': dict(sorted(stage_counts.items())),
            'joint_class_counts': dict(sorted(joint_counts.items())),
            'decomposition_check': (
                len(joint_ok) == len(localized) + len(refusal)),
        },
        'strata': {},
        'worst_conditions': {},
        'old_metrics_recomputed': old_metrics_recomputed,
    }

    for dimension in STRATA_DIMENSIONS:
        groups = defaultdict(list)
        for row in rows:
            if dimension == 'reference_availability':
                value = ('AVAILABLE' if row['gt_reference_available'] is True
                         else 'UNAVAILABLE'
                         if row['gt_reference_available'] is False
                         else 'NOT_APPLICABLE')
            else:
                value = (row.get('strata') or {}).get(dimension, 'UNSPECIFIED')
            groups[str(value)].append(row)
        summaries = {name: _group_metrics(items)
                     for name, items in sorted(groups.items())}
        summary['strata'][dimension] = summaries
        worst = {}
        for metric in ('localization_coverage', 'joint_composite_rate'):
            best = None
            insufficient = None
            for name, entry in summaries.items():
                numerator = (entry['localized']
                             if metric == 'localization_coverage'
                             else entry['joint_ok'])
                denominator = (entry['reference_available']
                               if metric == 'localization_coverage'
                               else entry['joint_evaluable'])
                record = {'stratum': name, 'numerator': numerator,
                          'denominator': denominator,
                          'rate': entry[metric]}
                if denominator == 0:
                    record['status'] = 'INSUFFICIENT_DENOMINATOR'
                    if insufficient is None:
                        insufficient = record
                    continue
                if denominator < 5:
                    record['status'] = 'INSUFFICIENT_DENOMINATOR'
                    if insufficient is None:
                        insufficient = record
                    continue
                record['status'] = 'WORST'
                rank = (entry[metric], -denominator, name)
                if best is None or rank < best[0]:
                    best = (rank, record)
            if best is not None:
                worst[metric] = best[1]
            elif insufficient is not None:
                worst[metric] = insufficient
            else:
                worst[metric] = {'stratum': None, 'numerator': None,
                                 'denominator': 0, 'rate': None,
                                 'status': 'NO_STRATA'}
        summary['worst_conditions'][dimension] = worst

    summary['old_definition_issues'] = _old_definition_issues(summary)
    return summary


def _old_definition_issues(summary):
    joint = summary['joint']
    localization = summary['localization']
    presence = summary['presence']
    identity = summary['identity']
    audit = summary['audit']
    issues = []
    if joint['correct_refusal'] or joint['composite_tp']:
        issues.append({
            'issue': 'joint_composite_includes_correct_refusals',
            'detail': ('the joint numerator counts %d GT-reference-unavailable '
                       'positives where the model correctly emitted no '
                       'keypoint; these are joint-ok but are NOT localization '
                       'successes and do not enter the anchor/bearing error '
                       'denominator'
                       % joint['correct_refusal']),
            'composite_tp': joint['composite_tp'],
            'localized': joint['localized'],
            'correct_refusal': joint['correct_refusal'],
        })
    if joint['narrow_denominator'] != localization['denominator']:
        issues.append({
            'issue': 'joint_denominator_differs_from_localization_denominator',
            'detail': ('joint uses %d GT-observable positives with a complete '
                       'bbox+reference label; localization accuracy can only '
                       'use the %d positives whose GT reference point is '
                       'available. The rates are not interchangeable.'
                       % (joint['narrow_denominator'],
                          localization['denominator'])),
            'joint_denominator': joint['narrow_denominator'],
            'localization_denominator': localization['denominator'],
            'joint_composite_rate': joint['composite_rate'],
            'localization_rate': joint['localization_rate'],
        })
    issues.append({
        'issue': 'identity_precision_denominator_is_claims_not_positives',
        'detail': ('identity precision uses the %d identity claims as '
                   'denominator; identity recall uses the %d positives. Both '
                   'are reported; precision must not be quoted as detection '
                   'recall.'
                   % (identity['claims'], presence['tp'] + presence['fn'])),
        'claims': identity['claims'],
        'precision': identity['precision'],
        'recall': identity['recall'],
        'positive_denominator': presence['tp'] + presence['fn'],
    })
    issues.append({
        'issue': 'reference_coverage_denominator_is_reference_available_positives',
        'detail': ('reference coverage denominator is %d positives with an '
                   'available GT reference point; it includes presence misses '
                   '(%d) and confidence-suppressed keypoints (%d), which are '
                   'retained as failures rather than dropped.'
                   % (localization['denominator'],
                      localization['presence_miss'],
                      localization['no_keypoint'])),
        'available_denominator': localization['denominator'],
        'presence_miss_retained': localization['presence_miss'],
        'no_keypoint_retained': localization['no_keypoint'],
    })
    issues.append({
        'issue': 'anchor_accuracy_conditional_on_correct_subset',
        'detail': ('the correct-subset anchor/bearing statistics are '
                   'conditional on success (%d of %d emitted keypoints). The '
                   'all-emitted error distribution and the wrong-anchor '
                   'distribution are reported separately; the correct-subset '
                   'median is not an unconditional accuracy.'
                   % (localization['correct'],
                      localization['error_denominator'])),
        'correct_subset': localization['correct'],
        'emitted': localization['error_denominator'],
        'all_emitted_median_px':
            localization['anchor_error_px'].get('median_px'),
        'correct_only_median_px':
            localization['anchor_error_px_correct_only'].get('median_px'),
    })
    issues.append({
        'issue': 'gt_reference_is_same_cue_source_as_the_model_cue',
        'detail': ('the GT reference point is derived from the strict-green '
                   'component; the model keypoint is trained on the same cue. '
                   'Agreement is same-source reproducibility, not independent '
                   'physical accuracy.'),
        'gt_reference_source_counts': audit['gt_reference_source_counts'],
    })
    if audit['gt_unobservable'] == 0:
        issues.append({
            'issue': 'gt_unobservable_branch_unexercised',
            'detail': ('this pool has 0 annotation-side GT_UNOBSERVABLE '
                       'frames; the exclusion rule is implemented and tested '
                       'but was not exercised by the exploratory data. That is '
                       'INCOMPLETE coverage, not a pass.'),
        })
    if audit['uncertain_on_positive'] + audit['uncertain_on_negative'] == 0:
        issues.append({
            'issue': 'model_unknown_rejected_branch_unexercised',
            'detail': ('all saved predictions are DETECTED or NOT_DETECTED; '
                       'the UNKNOWN/REJECTED retention rule is implemented and '
                       'tested but not exercised by this pool.'),
        })
    if audit['frames_with_verified_confusers'] == 0:
        issues.append({
            'issue': 'no_verified_confuser_in_pool',
            'detail': ('no frame carries a verified similar-structure '
                       'confuser (HN1); identity precision is conditional on a '
                       'pool without a verified identity-negative, so it '
                       'cannot certify identity.'),
        })
    return issues


def bearing_flip_counts(rows, thresholds_deg=(0.414, 1.074, 5.0)):
    """Count 2D-pixel vs horizontal-bearing decision flips per threshold.

    Rows considered are emitted keypoints on GT-reference-available positives
    (the localization denominator). tau_px was 3.0 px (1.074 deg at fx=160);
    0.414 deg is the 1.155 px blind re-annotation noise; 5.0 deg is the legacy
    geometry/independence PROPOSED threshold.
    """
    emitted = [r for r in rows
               if r['reference_stage'] in (STAGE_AVAILABLE_CORRECT,
                                           STAGE_AVAILABLE_WRONG_ANCHOR)
               and r['anchor_error_px'] is not None
               and r['abs_bearing_deg'] is not None]
    result = {'denominator': len(emitted)}
    for threshold in thresholds_deg:
        key = _threshold_key(threshold)
        both_pass = 0
        pixel_pass_bearing_fail = 0
        pixel_fail_bearing_pass = 0
        both_fail = 0
        for row in emitted:
            pixel_pass = row['reference_stage'] == STAGE_AVAILABLE_CORRECT
            bearing_pass = float(row['abs_bearing_deg']) <= float(threshold)
            if pixel_pass and bearing_pass:
                both_pass += 1
            elif pixel_pass and not bearing_pass:
                pixel_pass_bearing_fail += 1
            elif not pixel_pass and bearing_pass:
                pixel_fail_bearing_pass += 1
            else:
                both_fail += 1
        result[key] = {
            'threshold_deg': float(threshold),
            'both_pass': both_pass,
            'pixel_pass_bearing_fail': pixel_pass_bearing_fail,
            'pixel_fail_bearing_pass': pixel_fail_bearing_pass,
            'both_fail': both_fail,
            'flips': pixel_pass_bearing_fail + pixel_fail_bearing_pass,
            'pixel_pass': both_pass + pixel_pass_bearing_fail,
            'bearing_pass': both_pass + pixel_fail_bearing_pass,
        }
    return result


def green_anchor_audit(annotations, image_loader,
                       radius_px=GREEN_ANCHOR_MATCH_RADIUS_PX):
    """Compare recorded label keypoints with strict-green components.

    This is a same-source annotation self-consistency check: both the label
    keypoint and the model keypoint target the strict-green cue, so agreement
    here is not independent physical accuracy. image_loader(path) must return a
    pixel array (rows of (r, g, b)).
    """
    distances = []
    evaluated = 0
    largest_is_nearest = 0
    without_component = 0
    distance_gt_1_5 = 0
    area_pairs = []
    per_frame = []
    for annotation in annotations:
        geometry = annotation.get('geometry') or {}
        keypoint = geometry.get('keypoint')
        target = annotation.get('target') or {}
        if target.get('present') is not True or not keypoint:
            continue
        path = annotation.get('image')
        if not path:
            continue
        evaluated += 1
        components = green_components(image_loader(path))
        if not components:
            without_component += 1
            per_frame.append({'frame_id': annotation['frame_id'],
                              'nearest_distance_px': None,
                              'reason': 'NO_STRICT_GREEN_COMPONENT'})
            continue
        gx, gy = float(keypoint['x']), float(keypoint['y'])
        ranked = sorted(
            components,
            key=lambda comp: math.hypot(comp['centroid_x'] - gx,
                                        comp['centroid_y'] - gy))
        nearest = ranked[0]
        distance = math.hypot(nearest['centroid_x'] - gx,
                              nearest['centroid_y'] - gy)
        if distance > radius_px:
            without_component += 1
            per_frame.append({'frame_id': annotation['frame_id'],
                              'nearest_distance_px': distance,
                              'reason': 'NO_COMPONENT_WITHIN_RADIUS'})
            continue
        distances.append(distance)
        if nearest is components[0]:
            largest_is_nearest += 1
        if distance > 1.5:
            distance_gt_1_5 += 1
        recorded = geometry.get('green_pixels')
        if recorded is not None:
            area_pairs.append((int(recorded), int(nearest['area'])))
        per_frame.append({'frame_id': annotation['frame_id'],
                          'nearest_distance_px': distance,
                          'nearest_area': nearest['area'],
                          'recorded_green_pixels': recorded,
                          'largest_component_area': components[0]['area']})
    return {
        'count': evaluated,
        'matched_count': len(distances),
        'radius_px': float(radius_px),
        'distance_px': _stats(distances, 'px'),
        'frames_without_component_within_radius': without_component,
        'frames_distance_gt_1_5_px': distance_gt_1_5,
        'largest_component_is_nearest': largest_is_nearest,
        'recorded_green_pixels_vs_measured_area': {
            'count': len(area_pairs),
            'exact_match': sum(1 for a, b in area_pairs if a == b),
            'max_abs_diff': (max(abs(a - b) for a, b in area_pairs)
                             if area_pairs else None),
        },
        'limit': ('same-source check: the label keypoint is derived from the '
                  'same strict-green rule as the model cue target; agreement '
                  'is reproducibility, not independent physical accuracy'),
        'per_frame': per_frame,
    }


def _annotation_size(annotation):
    bbox = (annotation.get('geometry') or {}).get('bbox_xywh')
    if not bbox:
        return float('inf')
    return max(float(bbox[2]), float(bbox[3]))


def _frame_record(annotation, role):
    size = _annotation_size(annotation)
    return {
        'frame_id': annotation['frame_id'],
        'image': annotation.get('image'),
        'image_sha256': annotation.get('image_sha256'),
        'image_width': annotation.get('image_width'),
        'image_height': annotation.get('image_height'),
        'family': (annotation.get('source') or {}).get('family'),
        'role': role,
        'target_size_px': (None if size == float('inf')
                           else round(size, 2)),
    }


def _select_stratified(candidates, count, size_getter, family_getter):
    if count <= 0:
        return []
    groups = defaultdict(list)
    for candidate in candidates:
        groups[str(family_getter(candidate))].append(candidate)
    for family in groups:
        groups[family].sort(key=lambda c: (size_getter(c), c['frame_id']))
    selected = []
    families = sorted(groups)
    while len(selected) < count:
        progressed = False
        for family in families:
            if len(selected) >= count:
                break
            if groups[family]:
                selected.append(groups[family].pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def tiny_reannotation_plan(train_document, val_document, *, max_side_px=14.0,
                           n_tiny=12, n_small_green=6, n_control=4):
    """Deterministically select development frames for blind re-annotation.

    Strata (the role mapping is internal; the blind list hides it):
    - tiny_positive: GT-present, bbox max side <= max_side_px;
    - small_green_cue: GT-present, reference visible, 3 <= green_pixels <= 49,
      bbox max side > max_side_px (reference legibility floor);
    - control_absent: GT-absent confirmed negative.

    Selection is round-robin across families, each family ordered by target
    size then frame_id, so the plan is deterministic and not size-biased
    toward one family.
    """
    annotations = []
    for document in (train_document, val_document):
        annotations.extend((document or {}).get('annotations') or [])
    tiny_pool = []
    small_green_pool = []
    control_pool = []
    for annotation in annotations:
        target = annotation.get('target') or {}
        geometry = annotation.get('geometry') or {}
        present = target.get('present') is True
        if not present:
            if (target.get('undecidable') is not True
                    and annotation.get('negative_type') == 'TARGET_ABSENT'):
                control_pool.append(annotation)
            continue
        if geometry.get('bbox_xywh') is None:
            continue
        size = _annotation_size(annotation)
        if size <= max_side_px:
            tiny_pool.append(annotation)
            continue
        keypoint = geometry.get('keypoint')
        green_pixels = geometry.get('green_pixels') or 0
        if (keypoint is not None and keypoint.get('visible') is True
                and 3 <= int(green_pixels) <= 49):
            small_green_pool.append(annotation)

    def family(annotation):
        return (annotation.get('source') or {}).get('family') or 'UNSPECIFIED'

    tiny = _select_stratified(tiny_pool, n_tiny, _annotation_size, family)
    small_green = _select_stratified(small_green_pool, n_small_green,
                                     _annotation_size, family)
    controls = _select_stratified(control_pool, n_control,
                                  lambda a: a['frame_id'], family)
    frames = ([_frame_record(a, 'tiny_positive') for a in tiny]
              + [_frame_record(a, 'small_green_cue') for a in small_green]
              + [_frame_record(a, 'control_absent') for a in controls])
    return {
        'schema_version': 'dsh.landmark_tiny_blind_plan.v1',
        'created_at': '2026-11-04',
        'max_side_px': float(max_side_px),
        'sampling': {
            'tiny_pool': len(tiny_pool),
            'small_green_pool': len(small_green_pool),
            'control_pool': len(control_pool),
            'selected_tiny': len(tiny),
            'selected_small_green': len(small_green),
            'selected_control': len(controls),
            'note': 'roles are withheld from the blind frame list; the role '
                    'mapping is recomputable from the frozen development '
                    'annotations',
        },
        'selection_rule': 'round-robin across families (sorted), each family '
                          'ordered by (target max side, frame_id); controls '
                          'ordered by frame_id',
        'criteria': dict(TINY_CRITERIA),
        'frames': frames,
    }


def blind_frame_list(plan):
    """Strip the internal role/strata mapping for the blind annotator list."""
    frames = [{'frame_id': frame['frame_id'],
               'image': frame['image'],
               'image_sha256': frame['image_sha256'],
               'image_width': frame['image_width'],
               'image_height': frame['image_height']}
              for frame in plan['frames']]
    return {
        'schema_version': 'dsh.landmark_tiny_blind_frames.v1',
        'blind': True,
        'criteria': plan['criteria'],
        'selection_rule': plan['selection_rule'],
        'sampling': {'total': len(frames),
                     'note': 'stratified development sample; per-frame '
                             'strata are withheld to preserve blindness'},
        'frames': frames,
    }


_REPRODUCTION_FIELDS = (
    'presence.tp', 'presence.fp', 'presence.fn', 'presence.tn',
    'presence.precision', 'presence.recall',
    'reference.available_denominator', 'reference.unavailable_denominator',
    'reference.correct_keypoint_emissions',
    'reference.wrong_anchor_emissions', 'reference.no_keypoint_emissions',
    'reference.coverage', 'reference.false_reference_rate',
    'reference.anchor_error_px.count', 'reference.anchor_error_px.median_px',
    'reference.anchor_error_px.p90_px', 'reference.anchor_error_px.max_px',
    'reference.anchor_error_px_correct_only.count',
    'reference.anchor_error_px_correct_only.median_px',
    'reference.bearing_error_deg.count',
    'reference.bearing_error_deg.median_deg',
    'identity.claims', 'identity.correct_claims', 'identity.precision',
    'joint.narrow_denominator', 'joint.narrow_tp', 'joint.narrow_rate',
    'denominators.positives', 'denominators.negatives',
    'denominators.gt_unobservable', 'denominators.reference_available',
    'denominators.reference_unavailable', 'denominators.joint_evaluable',
)

_MISSING = object()


def _get_path(value, path):
    current = value
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _numbers_equal(left, right, tolerance=1e-9):
    if left is _MISSING or right is _MISSING:
        return False
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return left == right


def reproduction_check(summary, old_metrics, tolerance=1e-9):
    """Verify the post-eval rows reproduce the frozen numbers before splitting."""
    recomputed = summary['old_metrics_recomputed']
    old_overall = (old_metrics or {}).get('overall', old_metrics or {})
    mismatches = []
    checked = 0
    for path in _REPRODUCTION_FIELDS:
        left = _get_path(recomputed, path)
        right = _get_path(old_overall, path)
        checked += 1
        if not _numbers_equal(left, right, tolerance):
            mismatches.append('%s: recomputed=%r frozen=%r'
                              % (path, left, right))
    return {'match': not mismatches, 'checked_fields': checked,
            'tolerance': tolerance, 'mismatches': mismatches}


def build_diagnosis(annotations, observations_by_id, *, tau_px=3.0,
                    tau_iou=0.3, tau_conf=0.605476, tau_kpt=0.5,
                    fx_px=160.0, cx_px=160.0, old_metrics=None,
                    rows_sink=None):
    """Run the full post-evaluation diagnosis over saved rows."""
    rows = []
    missing = []
    for annotation in annotations:
        frame_id = annotation.get('frame_id')
        observation = observations_by_id.get(frame_id)
        if observation is None:
            missing.append(frame_id)
            continue
        rows.append(analyze_frame(
            annotation, observation, tau_px=tau_px, tau_iou=tau_iou,
            tau_conf=tau_conf, tau_kpt=tau_kpt, fx_px=fx_px, cx_px=cx_px))
    if rows_sink is not None:
        rows_sink.extend(rows)
    summary = aggregate(rows)
    summary['inputs'] = {
        'annotations': len(annotations),
        'predictions': len(observations_by_id),
        'matched_frames': len(rows),
        'missing_predictions': missing,
    }
    summary['thresholds'] = {
        'tau_px': tau_px, 'tau_iou': tau_iou, 'tau_conf': tau_conf,
        'tau_kpt': tau_kpt, 'fx_px': fx_px, 'cx_px': cx_px,
    }
    if old_metrics is not None:
        summary['reproduction'] = reproduction_check(summary, old_metrics)
    return summary


def _load_json(path):
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)


def _load_jsonl(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _pil_loader(path, root='.'):
    import os
    from PIL import Image
    resolved = path
    if not os.path.isabs(str(path)):
        resolved = os.path.join(root, str(path))
    with Image.open(resolved) as image:
        rgb = image.convert('RGB')
        width, height = rgb.size
        pixels = list(rgb.getdata())
    return [pixels[row * width:(row + 1) * width] for row in range(height)]


def write_overlays(rows, root, out_dir, *, max_count=12, scale=3):
    """Write a small set of representative overlays (PNG, 3x nearest zoom).

    Selection is deliberately small (about 10 files): at most two frames per
    stage, preferring different families, so the artifacts stay reviewable and
    do not confuse a per-stage representative with a dataset sample.
    """
    import os
    from PIL import Image, ImageDraw

    os.makedirs(out_dir, exist_ok=True)
    selected = []
    seen_frames = set()

    def pick(rows_in, tag, rank, limit=2):
        chosen = []
        families = set()
        for row in rows_in:
            if len(chosen) >= limit:
                break
            if row['frame_id'] in seen_frames or row['family'] in families:
                continue
            chosen.append(row)
            families.add(row['family'])
        for row in rows_in:
            if len(chosen) >= limit:
                break
            if row['frame_id'] in seen_frames:
                continue
            if any(row is item for item in chosen):
                continue
            chosen.append(row)
        for row in chosen:
            seen_frames.add(row['frame_id'])
            selected.append((rank, tag, row))

    wrong_rows = [r for r in rows
                  if r['reference_stage'] == STAGE_AVAILABLE_WRONG_ANCHOR]
    pick(sorted(wrong_rows, key=lambda r: -(r['anchor_error_px'] or 0)),
         'worst_anchor', 0, 2)
    pick(wrong_rows, 'wrong_anchor', 1, 2)
    pick([r for r in rows
          if r['reference_stage'] == STAGE_AVAILABLE_NO_KEYPOINT],
         'no_keypoint', 2, 2)
    pick([r for r in rows
          if r['reference_stage'] == STAGE_AVAILABLE_PRESENCE_MISS],
         'presence_miss', 3, 2)
    pick([r for r in rows
          if r['reference_stage'] == STAGE_UNAVAILABLE_CORRECT],
         'correct_refusal', 4, 1)
    pick([r for r in rows
          if r['reference_stage'] == STAGE_AVAILABLE_CORRECT],
         'correct', 5, 2)
    pick([r for r in rows
          if r['presence_class'] == metrics.PRESENCE_FP],
         'false_positive', 6, 1)

    selected.sort(key=lambda item: (item[0], item[1], item[2]['frame_id']))
    written = []
    for index, (rank, tag, row) in enumerate(selected[:max_count]):
        path = os.path.join(root, (row['image'] or '').replace('\\', '/'))
        if not os.path.isfile(path):
            continue
        with Image.open(path) as source:
            image = source.convert('RGB')
        draw = ImageDraw.Draw(image)
        bbox = row.get('gt_bbox_xywh')
        if bbox:
            x, y, w, h = bbox
            draw.rectangle([x, y, x + w, y + h], outline=(0, 200, 0))
        reference = row.get('gt_reference_px')
        if reference:
            draw.ellipse([reference[0] - 2, reference[1] - 2,
                          reference[0] + 2, reference[1] + 2],
                         outline=(0, 255, 0))
        pred_bbox = row.get('pred_bbox_xywh')
        if pred_bbox:
            x, y, w, h = pred_bbox
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0))
        pred_kpt = row.get('pred_keypoint_px')
        if pred_kpt:
            draw.line([pred_kpt[0] - 3, pred_kpt[1], pred_kpt[0] + 3,
                       pred_kpt[1]], fill=(255, 0, 0))
            draw.line([pred_kpt[0], pred_kpt[1] - 3, pred_kpt[0],
                       pred_kpt[1] + 3], fill=(255, 0, 0))
        draw.text((2, 2), ('%s | %s' % (tag, row['frame_id']))[:58],
                  fill=(0, 0, 0))
        enlarged = image.resize((image.width * scale, image.height * scale),
                                Image.NEAREST)
        out_path = os.path.join(out_dir, '%02d_%s.png' % (index, tag))
        enlarged.save(out_path)
        written.append({'path': out_path, 'tag': tag,
                        'frame_id': row['frame_id']})
    return written


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', required=True)
    parser.add_argument('--predictions', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--old-metrics', default=None)
    parser.add_argument('--images-root', default='.')
    parser.add_argument('--overlays-dir', default=None)
    parser.add_argument('--max-overlays', type=int, default=12)
    parser.add_argument('--no-green-audit', action='store_true')
    parser.add_argument('--tiny-train-labels', default=None)
    parser.add_argument('--tiny-val-labels', default=None)
    parser.add_argument('--tiny-plan-out', default=None)
    parser.add_argument('--tiny-blind-out', default=None)
    parser.add_argument('--tau-px', type=float, default=3.0)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-conf', type=float, default=0.605476)
    parser.add_argument('--tau-kpt', type=float, default=0.5)
    parser.add_argument('--fx', type=float, default=160.0)
    parser.add_argument('--cx', type=float, default=160.0)
    return parser.parse_args(argv)


def main(argv=None):
    import datetime
    import os
    args = parse_args(argv)
    labels = _load_json(args.labels)
    annotations = labels.get('annotations') or []
    predictions = _load_jsonl(args.predictions)
    observations = {row['frame_id']: row.get('observation')
                    for row in predictions if row.get('frame_id')}
    old_metrics = _load_json(args.old_metrics) if args.old_metrics else None
    overlay_rows = []
    summary = build_diagnosis(
        annotations, observations, tau_px=args.tau_px, tau_iou=args.tau_iou,
        tau_conf=args.tau_conf, tau_kpt=args.tau_kpt, fx_px=args.fx,
        cx_px=args.cx, old_metrics=old_metrics, rows_sink=overlay_rows)
    summary['schema_version'] = SCHEMA_VERSION
    summary['generated_at'] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    summary['inputs']['labels_sha256'] = _sha256(args.labels)
    summary['inputs']['predictions_sha256'] = _sha256(args.predictions)
    if args.old_metrics:
        summary['inputs']['old_metrics_sha256'] = _sha256(args.old_metrics)
    summary['definitions'] = {
        'presence': 'TP if DETECTED with bbox IoU >= tau_iou (or any DETECTED '
                    'on an absent frame is FP); NOT_DETECTED/UNKNOWN/REJECTED '
                    'on a positive is FN.',
        'identity': 'precision = correct claims / claims; recall = correct '
                    'claims / positives; negative false-match rate = '
                    'high-confidence claims on absent frames / negatives.',
        'reference_availability': 'available GT reference (VISIBLE) vs '
                                  'unavailable GT reference (keypoint null). '
                                  'coverage = correct keypoints / available; '
                                  'false-reference rate = keypoints emitted on '
                                  'unavailable / unavailable.',
        'localization_accuracy': 'emitted keypoint within tau_px of the GT '
                                 'reference point, among available-reference '
                                 'positives only; presence misses and '
                                 'confidence-suppressed keypoints stay in the '
                                 'denominator.',
        'joint': 'denominator = GT-observable positives with bbox+reference '
                 'label; LOCALIZED = joint-ok via available reference; '
                 'CORRECT_REFUSAL = joint-ok via correctly declaring an '
                 'unavailable reference (never a localization success); '
                 'composite_rate = (localized + correct_refusal) / joint '
                 'denominator, NOT a localization rate.',
    }
    summary['bearing_flip_counts'] = bearing_flip_counts(overlay_rows)
    if args.images_root and not args.no_green_audit:
        summary['green_anchor_audit'] = green_anchor_audit(
            annotations,
            lambda path: _pil_loader(path, root=args.images_root))
    if args.tiny_plan_out and args.tiny_train_labels and args.tiny_val_labels:
        plan = tiny_reannotation_plan(
            _load_json(args.tiny_train_labels),
            _load_json(args.tiny_val_labels))
        with open(args.tiny_plan_out, 'w', encoding='utf-8') as stream:
            json.dump(plan, stream, indent=2, ensure_ascii=False)
        if args.tiny_blind_out:
            with open(args.tiny_blind_out, 'w', encoding='utf-8') as stream:
                json.dump(blind_frame_list(plan), stream, indent=2,
                          ensure_ascii=False)
        summary['tiny_blind_plan'] = {
            'path': args.tiny_plan_out,
            'selected': len(plan['frames']),
            'sampling': plan['sampling'],
        }
    if args.overlays_dir:
        summary['overlays'] = write_overlays(
            overlay_rows, args.images_root, args.overlays_dir,
            max_count=args.max_overlays)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False)
    print(json.dumps({
        'out': args.out,
        'frames': summary['frames'],
        'presence_tp': summary['presence']['tp'],
        'localization_coverage': summary['localization']['coverage'],
        'joint_composite_rate': summary['joint']['composite_rate'],
        'joint_localization_rate': summary['joint']['localization_rate'],
        'joint_refusal_rate': summary['joint']['refusal_rate'],
        'reproduction_match': (summary.get('reproduction') or {}).get('match'),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
