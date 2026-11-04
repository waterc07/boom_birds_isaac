"""Executable evaluation-definition audit for the landmark experiment.

This module turns the post-evaluation definition audit into code so that the
diagnosis work can consume one authoritative implementation instead of
re-deriving denominators by hand.

Four quantities are kept separate, each with its own denominator:

1. presence: GT-observable positives/negatives -> TP/FP/FN/TN; a prediction of
   UNKNOWN/REJECTED on an observable positive is a MISS and stays in the recall
   denominator;
2. identity: claims / positives / negatives are three different denominators; a
   single-class tower output is class evidence, not identity evidence;
3. reference availability: N_avail (GT reference point visible) and N_unavail
   (GT reference point annotated unavailable) are separate denominators; the
   correct UNAVAILABLE declaration is its own success count;
4. localization accuracy: restricted to GT-visible-reference positives; the
   PASS-RATE denominator is all applicable frames (missed detections / no
   keypoint stay misses), while the ERROR-DISTRIBUTION denominator is only the
   frames that actually emitted a keypoint.  2D pixel error (historical 3 px
   rule) and horizontal image-bearing error (the downstream consumer quantity)
   are reported separately, with explicit verdict-flip counts.

Joint rule (explicit):

- localization branch (GT reference visible): joint-ok requires presence TP,
  identity correct and an emitted keypoint within the frozen tau_px;
- availability branch (GT reference unavailable): joint-ok requires presence TP,
  identity correct and a correct UNAVAILABLE declaration (no keypoint).  This
  branch is joint-ok but is NEVER part of the localization error denominator;
  it is counted separately so that "correctly rejected reference" cannot inflate
  or deflate reference coverage / localization accuracy.

GT-unobservable frames (undecidable / fully occluded without a visible box /
ambiguous) are not scored for localization or identity, but their identity
claims and keypoint emissions are counted so they cannot silently disappear.

All numbers in the audit come from already-saved predictions + labels; no model
inference, no training, no Isaac dependency.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from boom_birds.evaluation import landmark_yolo
from boom_birds.evaluation.landmark_metrics import (
    error_stats,
    evaluate_frame,
    summarize,
)

__all__ = [
    'AUDIT_SCHEMA',
    'HISTORICAL_PLACEMENT_TOLERANCE_PX',
    'CONSUMER_QUANTITY',
    'BEARING_BUDGET_DEG',
    'DEFINITIONS',
    'consumer_requirement',
    'placement_split',
    'audit',
    'load_saved_predictions',
    'build_rows',
    'recompute',
]

AUDIT_SCHEMA = 'dsh.landmark_eval_definition_audit.v1'
HISTORICAL_PLACEMENT_TOLERANCE_PX = 3.0
HISTORICAL_PLACEMENT_STATUS = 'LEGACY_2D_PROXY_NOT_CONSUMER_UNIT'
CONSUMER_QUANTITY = 'IMAGE_BEARING_DEG'
DEFAULT_FX_PX = 160.0
BEARING_BUDGET_DEG = {
    'median': 3.0,
    'p90': 5.0,
    'status': 'PROPOSED_NOT_FROZEN',
    'source': 'LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md section 2.2',
}

DEFINITIONS = {
    'presence': 'GT-observable positives/negatives; UNKNOWN/REJECTED predictions '
                'are misses inside the recall denominator; GT_UNOBSERVABLE '
                'frames are excluded from the fourfold and reported separately.',
    'identity': 'claims / GT-observable positives / GT-observable negatives are '
                'three denominators; landmark_id is identity evidence and a '
                'single-class tower output must not be mapped to an identity '
                'without the uniqueness assumptions.',
    'reference_availability': 'N_avail (GT reference point visible) and '
                               'N_unavail (GT reference point annotated '
                               'unavailable) are separate denominators; a '
                               'correct UNAVAILABLE declaration is success on '
                               'N_unavail and is not a localization result.',
    'localization': 'Only GT-visible-reference positives.  The pass-rate '
                    'denominator is every applicable frame (missed detections '
                    'and non-emitted keypoints stay misses); the error-'
                    'distribution denominator is only the frames that emitted a '
                    'keypoint.  2D pixel error (historical 3 px) and horizontal '
                    'image-bearing error are reported separately.',
    'joint': 'Two explicit branches: localization branch (GT reference visible: '
             'presence TP + identity correct + emitted keypoint within tau_px) '
             'and availability branch (GT reference unavailable: presence TP + '
             'identity correct + correct UNAVAILABLE declaration).  The '
             'availability branch is joint-ok but never enters the localization '
             'error denominator.',
    'placement': 'Downstream consumption uses the image bearing (an image angle, '
                 'not a world bearing).  The 3 px 2D rule is the historical '
                 'metric and is reported as a legacy proxy only.',
}


def consumer_requirement():
    """What the downstream consumer actually needs from the reference point."""
    return {
        'quantity': CONSUMER_QUANTITY,
        'unit': 'degree',
        'formula': 'atan2(x_px - cx_px, fx_px)',
        'historical_pixel_tolerance_px': HISTORICAL_PLACEMENT_TOLERANCE_PX,
        'historical_status': HISTORICAL_PLACEMENT_STATUS,
        'history_note': 'the 3 px 2D rule is a legacy annotation-noise proxy '
                        '(blind re-annotation keypoint difference max 2.236 px); '
                        'it is not the consumer unit and must not be reported as '
                        'a bearing capability',
        'bearing_budget_deg': dict(BEARING_BUDGET_DEG),
        'caveat': 'image bearing is an image angle, not a world bearing and not '
                  'a distance; a 3 px threshold is about 1.074 deg at fx=160 px',
    }


def _localization_applicable(row):
    return bool(row.get('gt_observable') and row.get('gt_present')
                and row.get('gt_reference_available'))


def _px_to_bearing_deg(px, fx_px):
    return math.degrees(math.atan2(float(px), float(fx_px)))


def placement_split(rows, *, px_tolerance=HISTORICAL_PLACEMENT_TOLERANCE_PX,
                    fx_px=DEFAULT_FX_PX, bearing_tolerance_deg=None):
    """Separate the historical 2D pixel rule from the consumed bearing quantity."""
    rows = list(rows)
    applicable = [row for row in rows if _localization_applicable(row)]
    emitted = [row for row in applicable
               if row.get('keypoint_emitted') and row.get('anchor_error_px') is not None]
    tolerance = (float(bearing_tolerance_deg)
                 if bearing_tolerance_deg is not None
                 else _px_to_bearing_deg(px_tolerance, fx_px))
    px_errors, horizontal, vertical, bearings = [], [], [], []
    flips = Counter({'both_ok': 0, 'px_ok_bearing_fail': 0,
                     'px_fail_bearing_ok': 0, 'both_fail': 0})
    for row in emitted:
        px_error = float(row['anchor_error_px'])
        dx = abs(float(row.get('dx_px') or 0.0))
        dy = abs(float(row.get('dy_px') or 0.0))
        bearing_error = row.get('bearing_error_deg')
        px_errors.append(px_error)
        horizontal.append(dx)
        vertical.append(dy)
        if bearing_error is not None:
            bearings.append(float(bearing_error))
        px_ok = px_error <= float(px_tolerance)
        bearing_ok = (bearing_error is not None
                      and float(bearing_error) <= tolerance)
        if px_ok and bearing_ok:
            flips['both_ok'] += 1
        elif px_ok and not bearing_ok:
            flips['px_ok_bearing_fail'] += 1
        elif not px_ok and bearing_ok:
            flips['px_fail_bearing_ok'] += 1
        else:
            flips['both_fail'] += 1
    return {
        'px_tolerance': float(px_tolerance),
        'bearing_tolerance_deg': tolerance,
        'historical_status': HISTORICAL_PLACEMENT_STATUS,
        'denominators': {
            'applicable': len(applicable),
            'emitted': len(emitted),
            'not_emitted': len(applicable) - len(emitted),
        },
        'verdict_flips': dict(flips),
        'pixel_error_px': error_stats(px_errors, unit='px'),
        'horizontal_error_px': error_stats(horizontal, unit='px'),
        'vertical_error_px': error_stats(vertical, unit='px'),
        'bearing_error_deg': error_stats(bearings, unit='deg'),
        'note': 'verdicts compare the historical 2D rule (pixel_error_px <= '
                'px_tolerance) with the bearing rule (bearing_error_deg <= '
                'the 3 px equivalent angle).  px_fail_bearing_ok frames have a '
                'vertical-only error and pass the consumer quantity; '
                'px_ok_bearing_fail is impossible while the tolerance is the '
                'exact single-axis equivalent, and is kept for generality.',
    }


def audit(rows, *, px_tolerance=HISTORICAL_PLACEMENT_TOLERANCE_PX,
          fx_px=DEFAULT_FX_PX, thresholds=None, inputs=None):
    """Aggregate the four-way audit from evaluate_frame rows."""
    rows = list(rows)
    presence = Counter()
    presence_class_counts = Counter()
    fn_by_pred_status = Counter()
    unknown_by_status = Counter()
    unknown_by_reason = Counter()
    gt_unobservable_reasons = Counter()
    gt_unobs_claims = 0
    gt_unobs_keypoints = 0
    gt_unobs_detected = 0
    positives = 0
    negatives = 0
    gt_unobservable = 0
    negatives_unobservable = 0
    unknown_on_positive = 0
    unknown_on_negative = 0
    unknown_on_gt_unobservable = 0
    claims = 0
    correct_claims = 0
    wrong_claims = 0
    claims_on_gt_unobservable = 0
    claims_on_negatives = 0
    high_conf_false_matches = 0
    ref_available = 0
    ref_unavailable = 0
    ref_not_labelled = 0
    declared_unavailable = 0
    false_reference = 0
    avail_emitted = []
    avail_not_emitted = 0
    localization_applicable = 0
    localization_emitted = 0
    localization_within = 0
    localization_px = []
    localization_bearing = []
    localization_horizontal = []
    localization_vertical = []
    joint_denominator = 0
    joint_tp = 0
    joint_branch = {'LOCALIZATION': {'evaluable': 0, 'ok': 0},
                    'AVAILABILITY_DECLARATION': {'evaluable': 0, 'ok': 0}}
    joint_failures = Counter()
    missed_detections = 0
    fn_reference = Counter()
    fn_unavailable_reasons = Counter()

    for row in rows:
        presence_class = row['presence_class']
        presence[presence_class] += 1
        presence_class_counts[presence_class] += 1
        if presence_class == 'GT_UNOBSERVABLE':
            gt_unobservable += 1
            gt_unobservable_reasons[row.get('gt_unobservable_reason')
                                    or 'UNSPECIFIED'] += 1
        if presence_class == 'NEGATIVE_UNOBSERVABLE':
            negatives_unobservable += 1
        if row.get('gt_observable'):
            if row.get('gt_present'):
                positives += 1
            else:
                negatives += 1
        if row.get('gt_observable') and row.get('gt_present') \
                and presence_class == 'FN':
            fn_by_pred_status[row['pred_status']] += 1
            if row.get('gt_reference_available'):
                fn_reference['REFERENCE_AVAILABLE'] += 1
            elif row.get('gt_reference_unavailable'):
                fn_reference['REFERENCE_UNAVAILABLE'] += 1
                fn_unavailable_reasons[row.get('gt_reference_unavailable_reason')
                                       or 'UNSPECIFIED'] += 1
            else:
                fn_reference['REFERENCE_NOT_LABELLED'] += 1
            if row['pred_status'] == 'NOT_DETECTED':
                missed_detections += 1
        if row['pred_status'] in ('UNKNOWN', 'REJECTED'):
            unknown_by_status[row['pred_status']] += 1
            unknown_by_reason[row.get('pred_reject_reason') or 'UNSPECIFIED'] += 1
            if presence_class == 'GT_UNOBSERVABLE':
                unknown_on_gt_unobservable += 1
            elif row.get('gt_present'):
                unknown_on_positive += 1
            else:
                unknown_on_negative += 1

        # --- identity ---------------------------------------------------
        if row.get('gt_observable'):
            if row.get('identity_claim'):
                claims += 1
                if row.get('identity_correct'):
                    correct_claims += 1
                else:
                    wrong_claims += 1
                    if not row.get('gt_present'):
                        claims_on_negatives += 1
            if row.get('high_confidence_false_match'):
                high_conf_false_matches += 1
        else:
            if row.get('identity_claim'):
                claims_on_gt_unobservable += 1
                gt_unobs_claims += 1
            if row.get('pred_status') == 'DETECTED':
                gt_unobs_detected += 1
            if row.get('keypoint_emitted'):
                gt_unobs_keypoints += 1

        # --- reference availability ------------------------------------
        if row.get('gt_observable') and row.get('gt_present'):
            reference_class = row.get('reference_class')
            if reference_class == 'NOT_LABELLED':
                ref_not_labelled += 1
            elif reference_class in ('PRESENT_AND_AVAILABLE',
                                     'PRESENT_WRONG_ANCHOR',
                                     'PRESENT_NO_KEYPOINT'):
                ref_available += 1
                if row.get('keypoint_emitted'):
                    avail_emitted.append(row)
                else:
                    avail_not_emitted += 1
            elif reference_class == 'UNAVAILABLE_DECLARED':
                ref_unavailable += 1
                declared_unavailable += 1
            elif reference_class == 'UNAVAILABLE_EMITTED_KEYPOINT':
                ref_unavailable += 1
                false_reference += 1

        # --- localization accuracy -------------------------------------
        if _localization_applicable(row):
            localization_applicable += 1
            if row.get('keypoint_emitted') and row.get('anchor_error_px') is not None:
                localization_emitted += 1
                error = float(row['anchor_error_px'])
                localization_px.append(error)
                localization_horizontal.append(abs(float(row.get('dx_px') or 0.0)))
                localization_vertical.append(abs(float(row.get('dy_px') or 0.0)))
                if row.get('bearing_error_deg') is not None:
                    localization_bearing.append(float(row['bearing_error_deg']))
                if error <= float(px_tolerance):
                    localization_within += 1

        # --- joint ------------------------------------------------------
        if row.get('joint_evaluable'):
            joint_denominator += 1
            branch = row.get('joint_branch')
            if branch in joint_branch:
                joint_branch[branch]['evaluable'] += 1
            if row.get('joint_ok'):
                joint_tp += 1
                if branch in joint_branch:
                    joint_branch[branch]['ok'] += 1
            else:
                reason = row.get('joint_fail_reason') or 'UNSPECIFIED'
                if reason == 'REFERENCE':
                    reason = ('REFERENCE_AVAILABILITY'
                              if row.get('gt_reference_unavailable')
                              else 'REFERENCE_LOCALIZATION')
                joint_failures[reason] += 1

    accounted = (presence['TP'] + presence['FP'] + presence['FN'] + presence['TN']
                 + presence['GT_UNOBSERVABLE']
                 + presence['NEGATIVE_UNOBSERVABLE'])
    unknown_total = sum(unknown_by_status.values())
    report = {
        'schema_version': AUDIT_SCHEMA,
        'inputs': inputs or {},
        'thresholds': {
            'tau_iou': (thresholds or {}).get('tau_iou'),
            'tau_px': (thresholds or {}).get('tau_px'),
            'tau_conf': (thresholds or {}).get('tau_conf'),
            'px_tolerance_historical': float(px_tolerance),
            'fx_px': float(fx_px),
        },
        'definitions': dict(DEFINITIONS),
        'presence': {
            'tp': presence['TP'], 'fp': presence['FP'],
            'fn': presence['FN'], 'tn': presence['TN'],
            'precision': (presence['TP'] / (presence['TP'] + presence['FP'])
                          if (presence['TP'] + presence['FP']) else None),
            'recall': (presence['TP'] / (presence['TP'] + presence['FN'])
                       if (presence['TP'] + presence['FN']) else None),
            'negative_coverage': (presence['TN'] / negatives
                                  if negatives else None),
            'denominators': {'positives': positives, 'negatives': negatives,
                             'gt_unobservable': gt_unobservable},
            'fn_by_pred_status': dict(sorted(fn_by_pred_status.items())),
            'fn_by_reference_status': dict(sorted(fn_reference.items())),
            'fn_unavailable_reasons': dict(sorted(fn_unavailable_reasons.items())),
            'unknown_rejected': {
                'total': unknown_total,
                'on_positive': unknown_on_positive,
                'on_negative': unknown_on_negative,
                'on_gt_unobservable': unknown_on_gt_unobservable,
                'by_status': dict(sorted(unknown_by_status.items())),
                'by_reason': dict(sorted(unknown_by_reason.items())),
            },
        },
        'identity': {
            'claims': claims,
            'correct_claims': correct_claims,
            'wrong_identity_claims': wrong_claims,
            'claims_on_negatives': claims_on_negatives,
            'claims_on_gt_unobservable': claims_on_gt_unobservable,
            'precision': (correct_claims / claims if claims else None),
            'recall': (correct_claims / positives if positives else None),
            'high_confidence_false_matches': high_conf_false_matches,
            'false_match_rate': (high_conf_false_matches / negatives
                                 if negatives else None),
            'evaluable': claims > 0 or negatives > 0,
            'denominators': {'claims': claims, 'positives': positives,
                             'negatives': negatives},
        },
        'reference_availability': {
            'denominators': {'available': ref_available,
                             'unavailable': ref_unavailable},
            'declared_unavailable_correct': declared_unavailable,
            'false_reference_emissions': false_reference,
            'available_emitted': len(avail_emitted),
            'available_not_emitted': avail_not_emitted,
            'not_labelled': ref_not_labelled,
            'coverage': ((len(avail_emitted) - sum(
                1 for row in avail_emitted
                if row.get('reference_class') != 'PRESENT_AND_AVAILABLE'))
                / ref_available if ref_available else None),
            'declaration_rate': (declared_unavailable / ref_unavailable
                                 if ref_unavailable else None),
            'false_reference_rate': (false_reference / ref_unavailable
                                     if ref_unavailable else None),
        },
        'localization': {
            'denominators': {'applicable': localization_applicable,
                             'emitted': localization_emitted},
            'not_emitted': localization_applicable - localization_emitted,
            'within_tolerance': localization_within,
            'within_tolerance_rate': (localization_within / localization_applicable
                                      if localization_applicable else None),
            'pixel_error_px': error_stats(localization_px, unit='px'),
            'horizontal_error_px': error_stats(localization_horizontal, unit='px'),
            'vertical_error_px': error_stats(localization_vertical, unit='px'),
            'bearing_error_deg': error_stats(localization_bearing, unit='deg'),
            'bearing_budget_deg': dict(BEARING_BUDGET_DEG),
            'note': 'within_tolerance uses the historical 3 px 2D rule; the '
                    'pass-rate denominator includes non-emitted keypoints, the '
                    'error-distribution denominator is the emitted subset',
        },
        'joint': {
            'narrow_denominator': joint_denominator,
            'narrow_tp': joint_tp,
            'narrow_rate': (joint_tp / joint_denominator
                            if joint_denominator else None),
            'all_positive_lower_bound': (joint_tp / positives if positives else None),
            'coverage': (joint_denominator / positives if positives else None),
            'branches': {
                'localization': dict(joint_branch['LOCALIZATION'],
                                     enters_localization_error=True),
                'availability': dict(joint_branch['AVAILABILITY_DECLARATION'],
                                     enters_localization_error=False),
            },
            'fail_reasons': dict(sorted(joint_failures.items())),
            'note': 'the availability branch counts as joint-ok when the model '
                    'correctly declares UNAVAILABLE; it is reported separately '
                    'and never enters the localization error denominator',
        },
        'gt_unobservable': {
            'frames': gt_unobservable,
            'by_reason': dict(sorted(gt_unobservable_reasons.items())),
            'identity_claims': gt_unobs_claims,
            'keypoint_emissions': gt_unobs_keypoints,
            'detected': gt_unobs_detected,
            'excluded_from_denominators': True,
            'note': 'GT-unobservable frames are not scored for localization or '
                    'identity; their claims/emissions are counted here so they '
                    'cannot disappear',
        },
        'denominator_loss_audit': {
            'frames': {'total': len(rows), 'accounted': accounted},
            'accounting_ok': accounted == len(rows),
            'presence_class_counts': dict(sorted(presence_class_counts.items())),
            'prediction_unknown_rejected': {
                'total': unknown_total,
                'on_positive': unknown_on_positive,
                'on_negative': unknown_on_negative,
                'on_gt_unobservable': unknown_on_gt_unobservable,
                'by_status': dict(sorted(unknown_by_status.items())),
                'by_reason': dict(sorted(unknown_by_reason.items())),
                'where_counted': 'on_positive -> presence FN / recall; '
                                 'on_negative -> negative denominator (not TN); '
                                 'on_gt_unobservable -> GT_UNOBSERVABLE bucket',
            },
            'missed_detections': {
                'total': missed_detections,
                'where_counted': 'presence FN + localization applicable miss',
            },
            'wrong_identity_claims': {
                'total': wrong_claims,
                'where_counted': 'identity claims denominator + GT-observable '
                                 'positives recall denominator',
            },
            'claims_on_negatives': claims_on_negatives,
            'claims_on_gt_unobservable': claims_on_gt_unobservable,
        },
        'placement': placement_split(rows, px_tolerance=px_tolerance,
                                     fx_px=fx_px),
        'consumer_requirement': consumer_requirement(),
    }
    return report


# --- saved predictions + labels recompute -----------------------------------

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalise_prediction(record):
    if isinstance(record, dict) and record.get('observation') is not None:
        return landmark_yolo.observation_to_metric_prediction(record['observation'])
    if isinstance(record, dict) and record.get('prediction') is not None:
        record = record['prediction']
    if not isinstance(record, dict):
        raise ValueError('unsupported saved prediction record')
    return {
        'status': record.get('status', 'UNKNOWN'),
        'landmark_id': record.get('landmark_id'),
        'bbox_xywh': record.get('bbox_xywh'),
        'score': record.get('score'),
        'keypoint_px': record.get('keypoint_px'),
        'reject_reason': record.get('reject_reason'),
    }


def load_saved_predictions(path):
    """Load a saved predictions.jsonl into {frame_id: metric prediction}."""
    predictions = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        frame_id = record.get('frame_id') or record.get('gt_frame_id')
        if not frame_id:
            raise ValueError('saved prediction without frame_id')
        predictions[frame_id] = _normalise_prediction(record)
    return predictions


def build_rows(predictions_path, labels_path, *, split=None,
               tau_iou=0.3, tau_px=3.0, tau_conf=0.5, fx_px=None,
               drop_missing_predictions=False):
    """Rebuild evaluate_frame rows from saved predictions + v2/v2.1 labels.

    drop_missing_predictions=False keeps label frames without a saved
    prediction as model-side UNKNOWN/MISSING_PREDICTION (they stay in the
    applicable denominators).  Set True only to reproduce the original
    dataset-evaluation scope, i.e. when the labels file contains frames that
    were never part of the evaluated dataset; dropped frames are recorded in
    inputs['dropped_without_prediction'] and are not scored.
    """
    document = json.loads(Path(labels_path).read_text(encoding='utf-8'))
    annotations = document.get('annotations')
    if not isinstance(annotations, list):
        raise ValueError('labels document has no annotations list')
    predictions = load_saved_predictions(predictions_path)
    rows = []
    used = 0
    dropped = []
    for annotation in annotations:
        source = annotation.get('source') or {}
        if split is not None and source.get('split') != split:
            continue
        used += 1
        frame_id = annotation.get('frame_id')
        gt, reference_px, strata = landmark_yolo.ground_truth_from_annotation(
            annotation)
        prediction = predictions.get(frame_id)
        if prediction is None and drop_missing_predictions:
            dropped.append(frame_id)
            continue
        if prediction is None:
            prediction = {'status': 'UNKNOWN', 'landmark_id': None,
                          'bbox_xywh': None, 'score': None,
                          'keypoint_px': None,
                          'reject_reason': 'MISSING_PREDICTION'}
        intrinsics = landmark_yolo.pixel_basis_from_annotation(annotation) or {}
        geometry = annotation.get('geometry') or {}
        row = evaluate_frame(
            gt, prediction, tau_iou=tau_iou, reference_px=reference_px,
            tau_px=tau_px, tau_conf=tau_conf,
            fx_px=(fx_px if fx_px is not None else intrinsics.get('fx_px')),
            cx_px=intrinsics.get('cx_px'), strata=strata)
        row['gt_reference_unavailable_reason'] = geometry.get(
            'reference_unavailable_reason')
        row['green_pixels'] = geometry.get('green_pixels')
        row['dataset_role'] = annotation.get('dataset_role')
        rows.append(row)
    inputs = {
        'predictions': str(predictions_path),
        'predictions_sha256': _sha256(predictions_path),
        'labels': str(labels_path),
        'labels_sha256': _sha256(labels_path),
        'labels_schema_version': document.get('schema_version'),
        'split': split,
        'frames': used,
        'dropped_without_prediction': dropped,
        'predictions_without_label': sorted(set(predictions) - {
            annotation.get('frame_id') for annotation in annotations
            if (split is None or (annotation.get('source') or {}).get('split') == split)}),
    }
    return rows, inputs


def recompute(predictions_path, labels_path, *, split=None, output_dir,
              tau_iou=0.3, tau_px=3.0, tau_conf=0.5, fx_px=None,
              px_tolerance=HISTORICAL_PLACEMENT_TOLERANCE_PX, overwrite=False,
              drop_missing_predictions=False):
    """Recompute old-style metrics + the four-way audit from saved files."""
    output_dir = Path(output_dir)
    metrics_path = output_dir / 'metrics.json'
    audit_path = output_dir / 'audit.json'
    if not overwrite and (metrics_path.exists() or audit_path.exists()):
        raise FileExistsError(
            'refusing to overwrite existing ' + str(metrics_path) + ' / '
            + str(audit_path) + '; pass overwrite=True only for a deliberate '
              'new output directory')
    rows, inputs = build_rows(predictions_path, labels_path, split=split,
                              tau_iou=tau_iou, tau_px=tau_px,
                              tau_conf=tau_conf, fx_px=fx_px,
                              drop_missing_predictions=drop_missing_predictions)
    thresholds = {'tau_iou': tau_iou, 'tau_px': tau_px, 'tau_conf': tau_conf}
    metrics = summarize(rows)
    audit_doc = audit(rows, px_tolerance=px_tolerance,
                      fx_px=(fx_px or DEFAULT_FX_PX), thresholds=thresholds,
                      inputs=inputs)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + '\n',
                            encoding='utf-8')
    audit_path.write_text(json.dumps(audit_doc, indent=2, ensure_ascii=False) + '\n',
                          encoding='utf-8')
    return {'metrics': metrics, 'audit': audit_doc, 'inputs': inputs}