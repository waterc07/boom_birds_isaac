"""Consumer-protocol evaluation for the landmark experiment (pre-registered).

The consumer (landmark relay to region bearing) does not consume 2D pixel error or
world position from perception.  It consumes, per GT-present frame:

- a correct presence decision;
- a CONFIRMED central-tower identity (appearance gate pass + exactly one
  candidate surviving score/margin; otherwise UNKNOWN/candidate and no region
  update);
- correct reference handling (GT-visible reference -> keypoint emission;
  GT-unavailable reference -> correct refusal);
- a horizontal image bearing error <= tau_bearing (PROPOSED 3 deg, pre-registered
  in configs/perception/landmark_consumer_protocol_v1.json);
- a valid observation (stale/duplicate/generation-mismatch = rejection).

2D pixel error and bbox IoU are diagnostics only.  UNKNOWN/REJECTED/no-keypoint
samples stay in the applicable success denominator.  GT_UNOBSERVABLE frames are
kept in the all-positive denominator but not scored for the observable domain,
and their claims/keypoints are counted separately.

All evaluation here is read-only over labels/predictions (or model inference for
development frames only); no training, no final rerun, no Isaac dependency.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from boom_birds.evaluation import landmark_yolo

__all__ = [
    'ConsumerEvalError',
    'redecode_predictions',
    'PROTOCOL_SCHEMA',
    'CONSUMER_EVAL_SCHEMA',
    'CENTRAL_TOWER_ID',
    'DEFAULT_PROTOCOL_PATH',
    'IDENTITY_POLICIES',
    'DEFAULT_PROTOCOL',
    'INVALID_REJECT_REASONS',
    'DEFAULT_GATE_THRESHOLDS',
    'load_protocol',
    'merge_protocol',
    'truth_from_annotation',
    'build_frames',
    'normalize_prediction',
    'load_predictions',
    'evaluate_frame',
    'summarize_consumer',
    'green_mask',
    'appearance_features',
    'appearance_gate',
    'make_appearance_gate',
    'sweep_appearance_gate',
    'measure_feature_cost',
    'evaluate_saved',
    'parse_parity_evidence',
]

PROTOCOL_SCHEMA = 'dsh.landmark_consumer_protocol.v1'
CONSUMER_EVAL_SCHEMA = 'dsh.landmark_consumer_eval.v1'
CENTRAL_TOWER_ID = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
DEFAULT_PROTOCOL_PATH = 'configs/perception/landmark_consumer_protocol_v1.json'
IDENTITY_POLICIES = ('confirmed_only', 'raw_claim_upper_bound', 'strict_unknown')
INVALID_REJECT_REASONS = ('STALE', 'DUPLICATE', 'GENERATION_MISMATCH',
                          'MISSING_CALIBRATION', 'INVALID_IMAGE')

DEFAULT_PROTOCOL = {
    'schema_version': PROTOCOL_SCHEMA,
    'status': 'DEFAULT_IN_MEMORY',
    'consumer_contract': {
        'observation_valid': 'stale/duplicate/generation-mismatch invalid',
        'identity_policy': 'confirmed id only with appearance gate pass and '
                           'exactly one candidate',
        'reference_policy': 'GT visible -> keypoint; GT unavailable -> refusal',
        'bearing_definition': 'atan2(kx - cx0, fx)',
    },
    'success_definition': {
        'per_gt_present_frame': 'presence AND identity AND reference AND bearing',
        'per_gt_absent_frame': 'no confirmed central-tower claim',
    },
    'thresholds': {
        'tau_bearing_deg': 3.0,
        'tau_px_diagnostic': 3.0,
        'tau_iou_diagnostic': 0.3,
    },
    'denominators': {
        'all_positive': 'all GT-present frames',
        'observable_positive': 'GT-present excluding GT_UNOBSERVABLE',
        'reference_available': 'GT-present with visible annotated reference',
        'negatives': 'GT-absent frames, MS1-only and similar-structure frames',
        'unknown_policy': 'kept in the applicable success denominator',
    },
}

DEFAULT_GATE_THRESHOLDS = {
    'max_aspect_ratio': 2.2,
    'min_aspect_ratio': 0.30,
    'min_green_pixels': 0,
    'max_green_rel_x_offset': 0.30,
    'min_green_top_band_ratio': 0.35,
    'min_silhouette_symmetry': 0.30,
    'min_height_px': 0.0,
}


class ConsumerEvalError(ValueError):
    """Raised when the protocol or an input row cannot be evaluated."""


def _repo_root():
    return Path(__file__).resolve().parents[3]


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_protocol(document, source_path=None):
    if not isinstance(document, dict):
        raise ConsumerEvalError('protocol must be a JSON object')
    schema = document.get('schema_version')
    if not (isinstance(schema, str) and schema.startswith('dsh.landmark_consumer_protocol')):
        raise ConsumerEvalError('unsupported protocol schema_version: %r' % (schema,))
    thresholds = document.get('thresholds')
    if not isinstance(thresholds, dict):
        raise ConsumerEvalError('protocol.thresholds must be an object')
    tau = thresholds.get('tau_bearing_deg')
    if not isinstance(tau, (int, float)) or float(tau) <= 0:
        raise ConsumerEvalError('protocol.thresholds.tau_bearing_deg must be > 0')
    for key in ('success_definition', 'consumer_contract', 'denominators'):
        if not isinstance(document.get(key), dict):
            raise ConsumerEvalError('protocol.%s must be an object' % key)


def _merge(base, overlay):
    result = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_protocol(document):
    """Merge a protocol document over the in-memory defaults."""
    _validate_protocol(document)
    merged = _merge(DEFAULT_PROTOCOL, document)
    merged['_source'] = {
        'path': None,
        'sha256': None,
        'status': document.get('status'),
        'schema_version': document.get('schema_version'),
    }
    return merged


def load_protocol(path=None):
    """Load and validate the pre-registered consumer protocol, record its sha."""
    target = Path(path) if path is not None else _repo_root() / DEFAULT_PROTOCOL_PATH
    if not target.is_file():
        raise ConsumerEvalError('consumer protocol not found: %s' % target)
    document = json.loads(target.read_text(encoding='utf-8'))
    _validate_protocol(document, target)
    merged = _merge(DEFAULT_PROTOCOL, document)
    merged['_source'] = {
        'path': str(target),
        'sha256': _sha256_file(target),
        'status': document.get('status'),
        'schema_version': document.get('schema_version'),
    }
    return merged


# --- frame truth ------------------------------------------------------------

def _box_iou_xywh(a, b):
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


def truth_from_annotation(annotation, decision=None):
    """Consumer truth for one 62/163-frame development annotation."""
    gt, reference_px, strata = landmark_yolo.ground_truth_from_annotation(annotation)
    intrinsics = landmark_yolo.pixel_basis_from_annotation(annotation)
    present = bool(gt['present'])
    unobservable = bool(gt['undecidable'] or gt['ambiguous']
                        or (present and gt['bbox_xywh'] is None))
    ms1_boxes = []
    same_frame = False
    full_occlusion = False
    if isinstance(decision, dict):
        for confuser in decision.get('confusers') or []:
            if isinstance(confuser, dict) and confuser.get('bbox_xywh'):
                ms1_boxes.append([float(v) for v in confuser['bbox_xywh']])
        condition = str(decision.get('identity_condition') or '')
        same_frame = condition.startswith('both_in_frame')
        full_occlusion = condition == 'full_occlusion'
    for confuser in annotation.get('confusers') or []:
        if isinstance(confuser, dict) and confuser.get('bbox_xywh'):
            box = [float(v) for v in confuser['bbox_xywh']]
            if box not in ms1_boxes:
                ms1_boxes.append(box)
    gt_bbox = (list(gt['bbox_xywh']) if gt['bbox_xywh'] is not None else None)
    gt_keypoint = list(reference_px) if reference_px is not None else None
    if isinstance(decision, dict):
        if decision.get('target_bbox'):
            gt_bbox = [float(v) for v in decision['target_bbox']]
        if decision.get('target_keypoint'):
            gt_keypoint = [float(v) for v in decision['target_keypoint']]
    ms1_only = bool(not present and ms1_boxes)
    return {
        'frame_id': annotation.get('frame_id'),
        'image': annotation.get('image'),
        'image_width': annotation.get('image_width'),
        'image_height': annotation.get('image_height'),
        'intrinsics': intrinsics,
        'present': present,
        'observable': present and not unobservable,
        'gt_unobservable': unobservable,
        'reference': gt['reference'],
        'gt_bbox': gt_bbox,
        'gt_keypoint': gt_keypoint,
        'ms1_boxes': ms1_boxes,
        'ms1_only': ms1_only,
        'same_frame': same_frame,
        'full_occlusion': full_occlusion or (present and gt['visibility'] == 'OCCLUDED'),
        'family': strata['family'],
        'scale': strata['scale'],
        'truncation': strata['truncation'],
        'negative_type': strata['negative_type'],
    }


def build_frames(labels_path, decisions_path=None, split=None):
    """Load labels (+ optional identity decisions) into consumer truth frames."""
    labels_path = Path(labels_path)
    document = json.loads(labels_path.read_text(encoding='utf-8'))
    annotations = document.get('annotations')
    if not isinstance(annotations, list):
        raise ConsumerEvalError('labels document has no annotations list')
    decisions = {}
    if decisions_path is not None:
        decisions_doc = json.loads(Path(decisions_path).read_text(encoding='utf-8'))
        for frame in decisions_doc.get('frames') or []:
            decisions[frame.get('frame_id')] = frame
    frames = []
    skipped = 0
    for annotation in annotations:
        source = annotation.get('source') or {}
        if split is not None and source.get('split') != split:
            skipped += 1
            continue
        frames.append(truth_from_annotation(
            annotation, decisions.get(annotation.get('frame_id'))))
    meta = {
        'labels': str(labels_path),
        'labels_sha256': _sha256_file(labels_path),
        'decisions': str(decisions_path) if decisions_path is not None else None,
        'decisions_sha256': (_sha256_file(decisions_path)
                             if decisions_path is not None else None),
        'split': split,
        'frames': len(frames),
        'skipped_by_split': skipped,
    }
    return frames, meta


# --- predictions and scoring ------------------------------------------------

def normalize_prediction(record):
    """Normalize a saved prediction / observation record to the metric contract."""
    if not isinstance(record, dict):
        raise ConsumerEvalError('prediction record must be an object')
    if record.get('observation') is not None:
        return landmark_yolo.observation_to_metric_prediction(record['observation'])
    if record.get('prediction') is not None:
        record = record['prediction']
    prediction = {
        'status': record.get('status', 'UNKNOWN'),
        'landmark_id': record.get('landmark_id'),
        'bbox_xywh': record.get('bbox_xywh'),
        'score': record.get('score'),
        'keypoint_px': record.get('keypoint_px'),
        'reject_reason': record.get('reject_reason'),
    }
    candidate_count = record.get('candidate_count')
    if candidate_count is None:
        candidates = record.get('candidates')
        candidate_count = len(candidates) if isinstance(candidates, list) else 1
    prediction['candidate_count'] = int(candidate_count)
    return prediction


def load_predictions(path):
    predictions = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        frame_id = record.get('frame_id') or record.get('gt_frame_id')
        if not frame_id:
            raise ConsumerEvalError('saved prediction without frame_id')
        predictions[frame_id] = normalize_prediction(record)
    return predictions


def evaluate_frame(prediction, truth, protocol, *, gate=None,
                   appearance_features=None, identity_policy=None):
    """Consumer-protocol decision for one frame."""
    thresholds = protocol['thresholds']
    policy = identity_policy or protocol.get('identity_policy') or 'confirmed_only'
    if policy not in IDENTITY_POLICIES:
        raise ConsumerEvalError('unsupported identity_policy: %r' % (policy,))
    tau_bearing = float(thresholds['tau_bearing_deg'])
    tau_iou = float(thresholds.get('tau_iou_diagnostic', 0.3))
    status = prediction.get('status')
    reject_reason = prediction.get('reject_reason')
    valid = (status in ('DETECTED', 'NOT_DETECTED')
             and reject_reason not in INVALID_REJECT_REASONS)
    detected = status == 'DETECTED' and prediction.get('bbox_xywh') is not None
    bbox = prediction.get('bbox_xywh')
    keypoint = prediction.get('keypoint_px')
    claim = prediction.get('landmark_id') is not None
    candidate_count = int(prediction.get('candidate_count', 1) or 1)

    present = bool(truth['present'])
    observable = bool(truth['observable'])
    reference = truth['reference']
    gt_bbox = truth['gt_bbox']
    gt_keypoint = truth['gt_keypoint']

    iou_target = _box_iou_xywh(bbox, gt_bbox) if (bbox and gt_bbox) else None
    if present and observable:
        presence_correct = bool(detected and iou_target is not None
                                and iou_target >= tau_iou)
    elif truth['gt_unobservable']:
        presence_correct = None
    else:
        presence_correct = (not detected)

    gate_result = None
    gate_accepted = True
    if gate is not None and claim:
        gate_result = gate(appearance_features) if callable(gate) else gate
        gate_accepted = bool(gate_result.get('accepted'))
    raw_claim = claim
    identity_correct_by_target = bool(
        raw_claim and prediction.get('landmark_id') == CENTRAL_TOWER_ID
        and present and observable and detected
        and iou_target is not None and iou_target >= tau_iou
        and candidate_count == 1)
    if policy == 'strict_unknown':
        # no confirmed identity channel: every model claim is UNKNOWN for the
        # consumer, so no GT-present frame can succeed; raw claims are recorded
        confirmed_claim = False
        identity_correct = False
        wrong_claim = False
        gate_blocked = False
        gate_blocked_correct_target = False
        identity_claim_unvalidated = raw_claim
    elif policy == 'raw_claim_upper_bound':
        # upper bound: treat the raw model claim as an (unvalidated) identity
        # claim; correctness is only measured against GT for reporting
        confirmed_claim = raw_claim
        identity_correct = identity_correct_by_target
        wrong_claim = bool(raw_claim and not identity_correct_by_target)
        gate_blocked = False
        gate_blocked_correct_target = False
        identity_claim_unvalidated = raw_claim
    else:
        confirmed_claim = bool(raw_claim and gate_accepted)
        identity_correct = bool(confirmed_claim and identity_correct_by_target)
        wrong_claim = bool(confirmed_claim and not identity_correct)
        gate_blocked = bool(raw_claim and not gate_accepted)
        gate_blocked_correct_target = bool(
            gate_blocked and present and observable and detected
            and iou_target is not None and iou_target >= tau_iou)
        identity_claim_unvalidated = False
    wrong_claim_category = None
    if wrong_claim:
        if truth['gt_unobservable']:
            wrong_claim_category = 'FULL_OCCLUSION'
        elif candidate_count > 1:
            wrong_claim_category = 'MULTI_CANDIDATE'
        elif not present:
            wrong_claim_category = 'MS1_ONLY' if truth['ms1_only'] else 'NEGATIVE'
        elif truth['same_frame']:
            wrong_claim_category = 'SAME_FRAME'
        else:
            wrong_claim_category = 'WRONG_TARGET'

    reference_correct = None
    false_reference = False
    gt_unobservable_keypoint = False
    if truth['gt_unobservable']:
        gt_unobservable_keypoint = keypoint is not None
    elif present and observable:
        if reference == 'VISIBLE':
            reference_correct = keypoint is not None
        elif reference == 'UNAVAILABLE':
            reference_correct = keypoint is None
            false_reference = keypoint is not None
        else:
            reference_correct = None

    bearing_error = None
    bearing_ok = None
    px_2d_error = None
    if (present and observable and reference == 'VISIBLE'
            and keypoint is not None and gt_keypoint is not None):
        dx = float(keypoint[0]) - float(gt_keypoint[0])
        dy = float(keypoint[1]) - float(gt_keypoint[1])
        px_2d_error = math.hypot(dx, dy)
        intrinsics = truth.get('intrinsics') or {}
        fx = intrinsics.get('fx_px')
        cx = intrinsics.get('cx_px')
        if fx:
            pred_bearing = math.degrees(math.atan2(float(keypoint[0]) - cx, fx))
            gt_bearing = math.degrees(math.atan2(float(gt_keypoint[0]) - cx, fx))
            bearing_error = abs(pred_bearing - gt_bearing)
            bearing_ok = bearing_error <= tau_bearing
        else:
            bearing_ok = False
    elif present and observable and reference == 'VISIBLE':
        bearing_ok = False

    domain_all = bool(present)
    domain_observable = bool(present and observable)
    domain_reference = bool(present and observable and reference == 'VISIBLE')
    domain_negative = bool(not present and not truth['gt_unobservable'])

    if domain_all and truth['gt_unobservable']:
        success = False
        correct_abstention = (not claim and keypoint is None)
    elif domain_observable:
        success = bool(valid and presence_correct and identity_correct
                       and reference_correct is True
                       and (bearing_ok is not False))
        correct_abstention = None
    elif domain_negative:
        success = bool(valid and not confirmed_claim)
        correct_abstention = None
    else:
        success = False
        correct_abstention = None

    return {
        'frame_id': truth['frame_id'],
        'valid': valid,
        'status': status,
        'reject_reason': reject_reason,
        'detected': detected,
        'presence_correct': presence_correct,
        'iou_diagnostic': iou_target,
        'identity_policy': policy,
        'identity_claimed': confirmed_claim,
        'identity_claim_raw': raw_claim,
        'identity_claim_unvalidated': identity_claim_unvalidated,
        'gate_pass': gate_accepted,
        'gate_blocked': gate_blocked,
        'gate_blocked_correct_target': gate_blocked_correct_target,
        'identity_correct': identity_correct,
        'wrong_claim': wrong_claim,
        'wrong_claim_category': wrong_claim_category,
        'candidate_count': candidate_count,
        'gate_result': gate_result,
        'reference': reference,
        'reference_correct': reference_correct,
        'false_reference': false_reference,
        'gt_unobservable_keypoint': gt_unobservable_keypoint,
        'keypoint_emitted': keypoint is not None,
        'bearing_error_deg': bearing_error,
        'bearing_ok': bearing_ok,
        'px_2d_error': px_2d_error,
        'diagnostics_only': {'px_2d_error': px_2d_error, 'iou': iou_target},
        'domain_flags': {
            'all_positive': domain_all,
            'observable_positive': domain_observable,
            'reference_available': domain_reference,
            'negatives': domain_negative,
        },
        'success': success,
        'correct_abstention': correct_abstention,
        'family': truth['family'],
        'scale': truth['scale'],
        'truncation': truth['truncation'],
        'negative_type': truth['negative_type'],
        'same_frame': truth['same_frame'],
        'ms1_only': truth['ms1_only'],
        'gt_unobservable': truth['gt_unobservable'],
    }


def _rate(numerator, denominator):
    return (float(numerator) / denominator) if denominator else None


def _error_stats(values, unit='deg'):
    values = sorted(float(v) for v in values)
    if not values:
        return {'count': 0, 'median_' + unit: None, 'p90_' + unit: None,
                'max_' + unit: None}
    n = len(values)
    median = (values[n // 2] if n % 2
              else 0.5 * (values[n // 2 - 1] + values[n // 2]))
    p90 = values[max(0, min(n - 1, int(math.ceil(0.9 * n)) - 1))]
    return {'count': n, 'median_' + unit: median, 'p90_' + unit: p90,
            'max_' + unit: values[-1]}


def _domain_summary(rows, key):
    members = [row for row in rows if row['domain_flags'][key]]
    successes = sum(1 for row in members if row['success'])
    return {
        'denominator': len(members),
        'success': successes,
        'success_rate': _rate(successes, len(members)),
        'unknown_or_rejected': sum(1 for row in members if not row['valid']),
        'identity_withheld': sum(1 for row in members if not row['identity_claimed']),
        'no_keypoint': sum(1 for row in members if not row['keypoint_emitted']),
    }


def summarize_consumer(rows, *, protocol, identity_policy=None):
    rows = list(rows)
    policy = identity_policy or protocol.get('identity_policy') or 'confirmed_only'
    tau_bearing = float(protocol['thresholds']['tau_bearing_deg'])
    wrong_categories = Counter()
    for row in rows:
        if row['wrong_claim']:
            wrong_categories[row['wrong_claim_category'] or 'UNSPECIFIED'] += 1

    observable = [row for row in rows if row['domain_flags']['observable_positive']]
    negatives = [row for row in rows if row['domain_flags']['negatives']]
    reference_rows = [row for row in rows if row['domain_flags']['reference_available']]
    claims = [row for row in rows if row['identity_claimed']]
    correct_claims = [row for row in claims if row['identity_correct']]
    emitted = [row for row in observable if row['keypoint_emitted']]
    unavailable_ref = [row for row in observable
                       if row['reference'] == 'UNAVAILABLE']
    false_reference = [row for row in unavailable_ref if row['false_reference']]
    refusal_correct = [row for row in unavailable_ref
                       if row['reference_correct'] is True]
    bearing_rows = [row for row in reference_rows
                    if row['bearing_error_deg'] is not None]
    bearing_pass = sum(1 for row in bearing_rows
                       if row['bearing_error_deg'] <= tau_bearing)

    presence_tp = sum(1 for row in observable if row['presence_correct'] is True)
    presence_fn = sum(1 for row in observable if row['presence_correct'] is False)
    presence_fp = sum(1 for row in negatives if row['detected'])
    presence_tn = sum(1 for row in negatives if not row['detected'])

    strata = {'family': {}, 'scale': {}, 'truncation': {}, 'negative_type': {}}
    for dimension in strata:
        groups = {}
        for row in rows:
            if not row['domain_flags']['all_positive']:
                continue
            key = str(row.get(dimension) or 'UNSPECIFIED')
            groups.setdefault(key, []).append(row)
        for key, members in sorted(groups.items()):
            successes = sum(1 for row in members if row['success'])
            strata[dimension][key] = {'denominator': len(members),
                                      'success': successes,
                                      'success_rate': _rate(successes, len(members))}

    px_rows = [row for row in observable if row['px_2d_error'] is not None]
    gt_unobservable = [row for row in rows if row['gt_unobservable']]
    rejection_reasons = Counter(row['reject_reason'] or row['status']
                                for row in rows
                                if not row['valid'] or row['status'] == 'REJECTED')

    summary = {
        'schema_version': CONSUMER_EVAL_SCHEMA,
        'identity_policy': policy,
        'identity_claim_unvalidated': policy == 'raw_claim_upper_bound',
        'protocol': {
            'schema_version': protocol.get('schema_version'),
            'status': protocol.get('status'),
            'sha256': protocol['_source']['sha256'],
            'path': protocol['_source']['path'],
            'tau_bearing_deg': tau_bearing,
            'tau_bearing_status': protocol['thresholds'].get('tau_bearing_status'),
        },
        'counts': {'frames': len(rows), 'all_positive': sum(
            1 for row in rows if row['domain_flags']['all_positive']),
            'observable_positive': len(observable),
            'reference_available': len(reference_rows),
            'negatives': len(negatives)},
        'domains': {
            'all_positive': _domain_summary(rows, 'all_positive'),
            'observable_positive': _domain_summary(rows, 'observable_positive'),
            'reference_available': _domain_summary(rows, 'reference_available'),
            'negatives': _domain_summary(rows, 'negatives'),
        },
        'presence': {
            'observable_domain': {
                'tp': presence_tp, 'fn': presence_fn, 'fp': presence_fp,
                'tn': presence_tn,
                'precision': _rate(presence_tp, presence_tp + presence_fp),
                'recall': _rate(presence_tp, presence_tp + presence_fn),
            },
            'all_positive_domain': {
                # GT_UNOBSERVABLE present frames cannot satisfy a presence
                # decision; they are reported as not-successful rather than
                # deleted from the all-positive denominator
                'tp': presence_tp,
                'miss_or_unobservable': (len(observable) - presence_tp
                                         + sum(1 for row in rows
                                               if row['gt_unobservable'])),
                'recall': _rate(presence_tp,
                                sum(1 for row in rows
                                    if row['domain_flags']['all_positive'])),
            },
        },
        'identity': {
            'claims': len(claims),
            'confirmed_claims': len(claims),
            'raw_claims': sum(1 for row in rows if row.get('identity_claim_raw')),
            'gate_blocked_claims': sum(1 for row in rows if row.get('gate_blocked')),
            'gate_blocked_correct_targets': sum(
                1 for row in rows if row.get('gate_blocked_correct_target')),
            'gate_accepted_wrong_claims': len(claims) - len(correct_claims),
            'correct_claims': len(correct_claims),
            'wrong_claims': len(claims) - len(correct_claims),
            'precision': _rate(len(correct_claims), len(claims)),
            'recall': _rate(len(correct_claims), len(observable)),
            'wrong_claim_categories': dict(sorted(wrong_categories.items())),
            'claims_on_negatives': sum(1 for row in negatives
                                       if row['identity_claimed']),
            'wrong_claim_rate_on_negatives': _rate(
                sum(1 for row in negatives if row['identity_claimed']),
                len(negatives)),
            'ms1_only_denominator': sum(1 for row in rows
                                        if row['domain_flags']['negatives']
                                        and row['ms1_only']),
            'ms1_only_claims': sum(1 for row in rows
                                   if row['domain_flags']['negatives']
                                   and row['ms1_only']
                                   and row['identity_claimed']),
        },
        'reference': {
            'emitted': len(emitted),
            'emission_rate': _rate(len(emitted), len(observable)),
            'unavailable_denominator': len(unavailable_ref),
            'declared_correct': len(refusal_correct),
            'declaration_rate': _rate(len(refusal_correct), len(unavailable_ref)),
            'false_reference': len(false_reference),
            'false_reference_rate': _rate(len(false_reference), len(unavailable_ref)),
        },
        'rejection': {
            'unknown_or_rejected': sum(1 for row in rows if not row['valid']),
            'identity_withheld': sum(1 for row in rows
                                     if not row['identity_claimed']),
            'rejection_rate_of_all_positive': _rate(
                sum(1 for row in rows
                    if row['domain_flags']['all_positive'] and not row['valid']),
                sum(1 for row in rows if row['domain_flags']['all_positive'])),
            'by_reason': dict(sorted(rejection_reasons.items())),
        },
        'bearing': {
            'count': len(bearing_rows),
            'tau_bearing_deg': tau_bearing,
            'pass': bearing_pass,
            'pass_rate_of_emitted': _rate(bearing_pass, len(bearing_rows)),
            'pass_rate_of_reference_domain': _rate(bearing_pass, len(reference_rows)),
            **_error_stats([row['bearing_error_deg'] for row in bearing_rows]),
        },
        'gt_unobservable': {
            'frames': len(gt_unobservable),
            'claims': sum(1 for row in gt_unobservable if row['identity_claimed']),
            'keypoints': sum(1 for row in gt_unobservable
                             if row['gt_unobservable_keypoint']),
            'correct_abstentions': sum(1 for row in gt_unobservable
                                       if row['correct_abstention']),
        },
        'diagnostics_only': {
            'px_2d_error': _error_stats(
                [row['px_2d_error'] for row in px_rows], unit='px'),
            'iou': _error_stats([row['iou_diagnostic'] for row in observable
                                 if row['iou_diagnostic'] is not None], unit='iou'),
            'note': '2D pixel error and bbox IoU are diagnostics only; the '
                    'consumer success uses the horizontal bearing tolerance',
        },
        'identity_policy_note': (
            'strict_unknown: no confirmed identity channel -> GT-present consumer '
            'success ceiling is 0; raw claims are recorded but not counted as '
            'identity' if policy == 'strict_unknown' else
            ('raw_claim_upper_bound: raw model claims are treated as '
             'unvalidated identity (upper bound, not confirmed identity)'
             if policy == 'raw_claim_upper_bound' else
             'confirmed_only: confirmed identity requires one candidate and a '
             'passing appearance gate when a gate is supplied')),
        'strata': strata,
        'accounting': {
            'frames': len(rows),
            'all_positive': sum(1 for row in rows
                                if row['domain_flags']['all_positive']),
            'observable_positive': len(observable),
            'gt_unobservable': len([row for row in rows if row['gt_unobservable']]),
            'negatives': len(negatives),
            'consistent': (
                sum(1 for row in rows if row['domain_flags']['all_positive'])
                == len(observable)
                + sum(1 for row in rows
                      if row['gt_unobservable'] and row['domain_flags']['all_positive'])),
        },
    }
    return summary


# --- image-only appearance gate --------------------------------------------

def green_mask(rgb):
    """Strict green-cue mask (g>=90, g-r>=25, g-b>=25), image-only."""
    array = np.asarray(rgb, dtype=np.int16)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ConsumerEvalError('image must be HxWx3')
    red = array[:, :, 0]
    green = array[:, :, 1]
    blue = array[:, :, 2]
    return ((green >= 90) & ((green - red) >= 25) & ((green - blue) >= 25))


def _bbox_slice(bbox_xywh, width, height):
    x, y, w, h = [float(v) for v in bbox_xywh]
    x1 = max(0, min(width, int(round(x))))
    y1 = max(0, min(height, int(round(y))))
    x2 = max(0, min(width, int(round(x + w))))
    y2 = max(0, min(height, int(round(y + h))))
    return x1, y1, x2, y2


def appearance_features(rgb, bbox_xywh, *, green=None):
    """Image-only appearance features for one candidate bbox.

    No ground-truth position, oracle region, filename or label field is used:
    only the image pixels inside/around the candidate box.
    """
    array = np.asarray(rgb)
    height, width = array.shape[:2]
    if green is None:
        green = green_mask(array)
    x1, y1, x2, y2 = _bbox_slice(bbox_xywh, width, height)
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    crop_green = green[y1:y2, x1:x2]
    green_pixels = int(crop_green.sum())
    crop = array[y1:y2, x1:x2].astype(np.float32)
    if green_pixels:
        ys, xs = np.nonzero(crop_green)
        green_cx = float(xs.mean()) + x1
        green_cy = float(ys.mean()) + y1
        green_rel_x = (green_cx - (x1 + box_w / 2.0)) / box_w
        green_rel_y = (green_cy - y1) / box_h
        top_band = crop_green[:max(1, int(round(box_h * 0.30))), :]
        top_band_ratio = float(top_band.sum()) / float(green_pixels)
    else:
        green_rel_x = None
        green_rel_y = None
        top_band_ratio = 0.0
    gray = crop.mean(axis=2)
    gradient_x = np.abs(np.diff(gray, axis=1)) if gray.shape[1] > 1 else np.zeros((1, 1))
    silhouette = (gradient_x > 8.0).astype(np.float32)
    if silhouette.shape[1] > 1:
        flipped = silhouette[:, ::-1]
        symmetry = 1.0 - float(np.abs(silhouette - flipped).mean())
    else:
        symmetry = 0.0
    fill = float((gray > float(np.median(array)) + 12).mean())
    return {
        'aspect_ratio': box_h / float(box_w),
        'aspect_ratio_w_over_h': box_w / float(box_h),
        'height_px': float(box_h),
        'width_px': float(box_w),
        'green_pixels': green_pixels,
        'green_rel_x_offset': (abs(green_rel_x)
                               if green_rel_x is not None else None),
        'green_rel_y': green_rel_y,
        'green_top_band_ratio': top_band_ratio,
        'silhouette_symmetry': symmetry,
        'fill_ratio': fill,
    }


def appearance_gate(features, thresholds=None):
    """Decide whether an image-only candidate is the central tower."""
    thresholds = dict(DEFAULT_GATE_THRESHOLDS if thresholds is None else thresholds)
    reasons = []
    if features is None:
        return {'accepted': False, 'reason': 'NO_FEATURES', 'thresholds': thresholds}
    aspect = features.get('aspect_ratio')
    if aspect is None or aspect > thresholds['max_aspect_ratio']:
        reasons.append('ASPECT_TOO_SLENDER')
    if aspect is not None and aspect < thresholds['min_aspect_ratio']:
        reasons.append('ASPECT_TOO_WIDE')
    green_pixels = int(features.get('green_pixels') or 0)
    if green_pixels < thresholds['min_green_pixels']:
        reasons.append('GREEN_TOO_SMALL')
    if green_pixels > 0:
        # Green-light geometry is evidence only when the cue is actually
        # present.  Far targets can have zero strict green pixels; rejecting
        # them for missing green would destroy availability with no identity
        # benefit (MS1 is separated by aspect/silhouette).
        offset = features.get('green_rel_x_offset')
        if offset is not None and offset > thresholds['max_green_rel_x_offset']:
            reasons.append('GREEN_OFF_CENTRE')
        if (features.get('green_top_band_ratio') or 0) < \
                thresholds['min_green_top_band_ratio']:
            reasons.append('GREEN_NOT_TOP')
    if (features.get('silhouette_symmetry') or 0) < \
            thresholds['min_silhouette_symmetry']:
        reasons.append('SILHOUETTE_ASYMMETRIC')
    if (features.get('height_px') or 0) < thresholds['min_height_px']:
        reasons.append('TOO_SMALL')
    return {'accepted': not reasons, 'reasons': reasons, 'thresholds': thresholds}


def make_appearance_gate(thresholds=None):
    thresholds = dict(DEFAULT_GATE_THRESHOLDS if thresholds is None else thresholds)
    def gate(features):
        return appearance_gate(features, thresholds)
    return gate


def appearance_gate_v2(features, keypoint_emitted=None, thresholds=None):
    """Diag-T24 image-only gate: bbox aspect (w/h), green relative height, size."""
    thresholds = dict(DEFAULT_GATE_V2_THRESHOLDS
                      if thresholds is None else thresholds)
    if features is None:
        return {'accepted': False, 'reasons': ['NO_FEATURES'],
                'thresholds': thresholds}
    reasons = []
    height = float(features.get('height_px') or 0.0)
    if height < float(thresholds['min_height_px']):
        reasons.append('TOO_SMALL_UNANNOTATABLE')
    aspect = features.get('aspect_ratio_w_over_h')
    if aspect is None:
        reasons.append('NO_ASPECT')
    elif aspect < float(thresholds['min_aspect_ratio_wh']):
        reasons.append('ASPECT_TOO_SLENDER_MS1')
    if keypoint_emitted is None:
        keypoint_emitted = features.get('keypoint_emitted')
    if keypoint_emitted:
        green_rel_y = features.get('green_rel_y')
        if green_rel_y is None:
            if thresholds['green_rel_y_required_when_keypoint']:
                reasons.append('GREEN_REL_Y_UNAVAILABLE')
        elif green_rel_y < float(thresholds['min_green_rel_y']):
            reasons.append('GREEN_TOO_HIGH_ON_BBOX_MS1')
    return {'accepted': not reasons, 'reasons': reasons,
            'thresholds': thresholds, 'keypoint_emitted': keypoint_emitted}


def make_appearance_gate_v2(thresholds=None):
    thresholds = dict(DEFAULT_GATE_V2_THRESHOLDS
                      if thresholds is None else thresholds)
    def gate(features):
        return appearance_gate_v2(features,
                                  keypoint_emitted=(features or {}).get(
                                      'keypoint_emitted'),
                                  thresholds=thresholds)
    return gate


DEFAULT_GATE_V2_THRESHOLDS = {
    # Diag T24 design (62-frame dev identity pool): target aspect w/h median
    # 1.46 (min 0.63) vs MS1 0.33 (max 0.44); target green_rel_y median 0.24 vs
    # MS1 0.09.  PROPOSED_NOT_FROZEN; the pool may only be used to design the
    # bandwidth/denominators, not to freeze a certification threshold.
    'min_aspect_ratio_wh': 0.50,
    'min_green_rel_y': 0.18,
    'min_height_px': 20.0,
    'green_rel_y_required_when_keypoint': True,
}

GATE_GRID = tuple(
    {'max_aspect_ratio': max_aspect,
     'min_green_pixels': min_green,
     'max_green_rel_x_offset': max_offset}
    for max_aspect in (1.8, 2.0, 2.2, 2.4, 2.6)
    for min_green in (0, 1, 3)
    for max_offset in (0.30, 0.50)
)


def sweep_appearance_gate(proposals):
    """Sweep gate thresholds; report false-block (target rejected) and miss-block
    (MS1 accepted).  Proposals are image-only feature dicts with a kind label."""
    points = []
    for overrides in GATE_GRID:
        thresholds = dict(DEFAULT_GATE_THRESHOLDS)
        thresholds.update(overrides)
        false_block = miss_block = target_total = ms1_total = 0
        for proposal in proposals:
            kind = proposal['kind']
            result = appearance_gate(proposal['features'], thresholds)
            if kind == 'TARGET':
                target_total += 1
                if not result['accepted']:
                    false_block += 1
            elif kind == 'MS1':
                ms1_total += 1
                if result['accepted']:
                    miss_block += 1
        points.append({
            'thresholds': thresholds,
            'target_proposals': target_total,
            'ms1_proposals': ms1_total,
            'false_block': false_block,
            'false_block_rate': _rate(false_block, target_total),
            'miss_block': miss_block,
            'miss_block_rate': _rate(miss_block, ms1_total),
        })
    # Operating-point rule: keep the MS1 miss-block rate low first (identity
    # safety), then minimise false-blocks (availability).  If no point reaches a
    # low miss-block rate, report a weak-separation status instead of pretending
    # the gate works.
    strict = [point for point in points
              if point['miss_block_rate'] is not None
              and point['miss_block_rate'] <= 0.05]
    if strict:
        best = min(strict, key=lambda point: (point['false_block_rate'],
                                              point['miss_block_rate']))
    else:
        best = min(points, key=lambda point: (
            (point['false_block_rate'] or 1.0)
            + (point['miss_block_rate'] or 1.0),
            point['miss_block']))
    strong = (best['false_block_rate'] is not None
              and best['false_block_rate'] <= 0.10
              and best['miss_block_rate'] is not None
              and best['miss_block_rate'] <= 0.10)
    return {
        'points': points,
        'recommended': {
            'status': 'PROPOSED' if strong else 'PROPOSED_WEAK_SEPARATION',
            'thresholds': best['thresholds'],
            'false_block': best['false_block'],
            'false_block_rate': best['false_block_rate'],
            'miss_block': best['miss_block'],
            'miss_block_rate': best['miss_block_rate'],
        },
        'note': 'thresholds are image-only and PROPOSED; they must be frozen on '
                'an independent validation set before any certification claim',
    }


def measure_feature_cost(images, bbox_xywh, repeats=None):
    frames = list(images)
    if repeats is None:
        repeats = max(1, int(round(200.0 / max(1, len(frames)))))
    times = []
    for _ in range(repeats):
        for image in frames:
            start = time.perf_counter()
            appearance_features(image, bbox_xywh)
            times.append((time.perf_counter() - start) * 1000.0)
    times.sort()
    return {'frames': len(frames), 'repeats': repeats,
            'median_ms': times[len(times) // 2] if times else None,
            'max_ms': times[-1] if times else None}


# --- saved-prediction evaluation -------------------------------------------

def evaluate_saved(labels_path, predictions_path, protocol_path, *,
                   decisions_path=None, split=None, gate=None,
                   gate_thresholds=None, images_dir=None):
    """Read-only consumer evaluation from saved predictions + labels."""
    protocol = load_protocol(protocol_path)
    frames, meta = build_frames(labels_path, decisions_path, split=split)
    predictions = load_predictions(predictions_path)
    rows = []
    missing = 0
    gate_enabled = bool(gate)
    for truth in frames:
        prediction = predictions.get(truth['frame_id'])
        if prediction is None:
            missing += 1
            prediction = {'status': 'UNKNOWN', 'landmark_id': None,
                          'bbox_xywh': None, 'score': None,
                          'keypoint_px': None,
                          'reject_reason': 'MISSING_PREDICTION',
                          'candidate_count': 0}
        features = None
        if gate_enabled:
            features = prediction.get('appearance_features')
            if features is None and images_dir is not None:
                image_path = _resolve_image(images_dir, truth)
                if image_path is not None:
                    from PIL import Image
                    with Image.open(image_path) as image:
                        features = appearance_features(
                            np.asarray(image.convert('RGB')),
                            prediction.get('bbox_xywh')
                            or truth.get('gt_bbox') or [0, 0, 1, 1])
        rows.append(evaluate_frame(prediction, truth, protocol,
                                   gate=gate, appearance_features=features))
    summary = summarize_consumer(rows, protocol=protocol)
    summary['inputs'] = dict(meta, predictions=str(predictions_path),
                             predictions_sha256=_sha256_file(predictions_path),
                             missing_predictions=missing,
                             gate_enabled=gate_enabled)
    return {'summary': summary, 'rows': rows, 'protocol': protocol}


def _resolve_image(images_dir, truth):
    images_dir = Path(images_dir)
    image_field = truth.get('image')
    candidates = []
    if image_field:
        candidates.append(images_dir / Path(image_field).name)
        candidates.append(images_dir / image_field)
    candidates.append(images_dir / truth['frame_id'])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def redecode_predictions(records, frames_by_id, *, tau_det, tau_margin,
                         tau_kpt):
    """Re-decode saved observations at a different decoder threshold set.

    Saved predictions were produced with the training evaluation thresholds; the
    frozen consumer protocol may use different tau_det/tau_margin/tau_kpt.  If the
    saved record keeps its observation candidates, the decision can be re-derived
    exactly for score thresholds (candidates below the old tau_det were not
    emitted, so the re-decode is conservative).  Frames without observation
    candidates are returned unchanged.
    """
    thresholds = {'tau_det': float(tau_det), 'tau_margin': float(tau_margin),
                  'tau_kpt': float(tau_kpt),
                  'tau_trunc_min_side_px': 16.0, 'tau_green_pixels': 3}
    predictions = {}
    for record in records:
        frame_id = record.get('frame_id') or record.get('gt_frame_id')
        if not frame_id:
            raise ConsumerEvalError('saved prediction without frame_id')
        observation = record.get('observation')
        truth = frames_by_id.get(frame_id)
        if observation is None or truth is None:
            predictions[frame_id] = normalize_prediction(record)
            continue
        candidates = []
        for candidate in observation.get('candidates') or []:
            if candidate.get('bbox_xywh') is None:
                continue
            candidates.append({
                'bbox_xywh': [float(v) for v in candidate['bbox_xywh']],
                'score': float(candidate.get('score') or 0.0),
                'class_id': 0,
                'keypoint_px': (None if candidate.get('keypoint_px') is None
                                else [float(v) for v in candidate['keypoint_px']]),
                'keypoint_confidence': candidate.get('keypoint_confidence'),
                'green_pixels': candidate.get('green_pixels'),
            })
        redecoded = landmark_yolo.decode_candidates(
            candidates, image_width=truth['image_width'],
            image_height=truth['image_height'],
            intrinsics=truth.get('intrinsics'), thresholds=thresholds,
            frame_id=frame_id)
        prediction = landmark_yolo.observation_to_metric_prediction(redecoded)
        prediction['candidate_count'] = int(
            redecoded.get('candidate_count') or 0)
        predictions[frame_id] = prediction
    return predictions


def parse_parity_evidence(path):
    """Summarize .pt vs ONNX vs raw-ORT decision flips from parity evidence."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    pairs = document.get('pairs')
    if not isinstance(pairs, dict):
        raise ConsumerEvalError('parity evidence has no pairs object')
    layers = Counter()
    frames = 0
    detail = {}
    for name, payload in pairs.items():
        detail[name] = {}
        for key in ('observation_flips', 'joint_flips', 'identity_flips',
                    'rejection_flips', 'bearing_flips_over_tau',
                    'presence_flips', 'reference_flips'):
            value = payload.get(key)
            if value is None:
                value = 0
            layers[key] += int(value)
            detail[name][key] = int(value)
        frames += int(payload.get('frames') or 0)
    return {'layers': dict(sorted(layers.items())), 'frames': frames,
            'pairs': detail,
            'status': document.get('status') or document.get('decision')}