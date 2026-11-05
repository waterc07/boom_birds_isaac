"""Two-class landmark consumer evaluation (central tower vs similar structure MS1).

Implements the pre-registered protocol
configs/perception/landmark_two_class_protocol_v1.json and label spec
landmark_two_class_label_spec_v1.json:

- class 0 = central_tower, class 1 = similar_structure_ms1;
- only a class-0 detection with score >= tau_det and no class conflict may map to
  the central-tower landmark_id; class 1 must NEVER be mapped to it;
- per-class confusion/recall plus a confusion matrix with misclassification;
- frozen eval documents are consumed by their explicit canonical flags
  (tower_observable/gt_unobservable/negative/ms1_only/same_frame); loader
  fallbacks only apply to legacy v2.1-derived truth without those flags;
- MS1-only frames with a tower claim are wrong claims;
- same-frame (tower + MS1) frames report whether the TOWER was selected;
- class 0 only may emit the reference keypoint; class 1 keypoint is always
  unavailable (never a bbox-centre substitute);
- reference availability, emission coverage, horizontal bearing and consumer
  success are reported with explicit denominators; UNKNOWN/REJECTED stay in the
  denominator; GT-uncertain / fully-occluded frames must not receive improper
  identity claims;
- the frozen single-class v2 pipeline can be compared on the same definitions.

This module never uses ground-truth position to produce an identity claim: GT is
only used for scoring.  Read-only over labels/predictions (or development model
inference); no training, no Isaac dependency.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from boom_birds.evaluation.landmark_consumer_eval import (
    _error_stats, _rate, _repo_root, _sha256_file, ConsumerEvalError,
)

__all__ = [
    'TwoClassEvalError',
    'TWO_CLASS_PROTOCOL_SCHEMA',
    'TWO_CLASS_SCHEMA',
    'CLASS_NAMES',
    'CENTRAL_TOWER_ID',
    'DEFAULT_PROTOCOL_PATH',
    'DEFAULT_THRESHOLDS',
    'IDENTITY_POLICIES',
    'load_protocol',
    'merge_protocol',
    'truth_from_two_class_annotation',
    'build_truth_from_identity_pool',
    'single_class_predictions_to_observations',
    'decode_detections',
    'evaluate_frame',
    'evaluate_rows',
    'summarize',
    'compare_summaries',
    'evaluate_saved',
    'infer_observations',
    'detections_from_ultralytics_result',
    'load_two_class_labels',
    'load_predictions',
]

TwoClassEvalError = ConsumerEvalError
TWO_CLASS_PROTOCOL_SCHEMA = 'dsh.landmark_two_class_protocol.v1'
TWO_CLASS_SCHEMA = 'dsh.landmark_two_class_eval.v1'
CLASS_NAMES = {0: 'central_tower', 1: 'similar_structure_ms1'}
CENTRAL_TOWER_ID = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
DEFAULT_PROTOCOL_PATH = 'configs/perception/landmark_two_class_protocol_v1.json'
IDENTITY_POLICIES = ('confirmed_only', 'raw_claim_upper_bound', 'strict_unknown')
DEFAULT_THRESHOLDS = {
    'tau_det': 0.25,
    'tau_margin': 0.10,
    'tau_kpt': 0.50,
    'tau_iou': 0.3,
    'tau_bearing_deg': 3.0,
    'tau_conflict': 0.5,
}
DEFAULT_INTRINSICS = {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0}


def _merge(base, overlay):
    result = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


DEFAULT_PROTOCOL = {
    'schema_version': TWO_CLASS_PROTOCOL_SCHEMA,
    'status': 'DEFAULT_IN_MEMORY',
    'classes': {'0': {'name': 'central_tower'},
                '1': {'name': 'similar_structure_ms1'}},
    'identity_output_rules': {
        'tower_claim': 'class0 detection only, score>=tau_det, no class conflict',
        'ms1_claim': 'never mapped to the central-tower landmark_id',
    },
    'evaluation': {'denominator_policy': 'UNKNOWN/REJECTED stay in denominator'},
    'baseline': 'frozen single-class v2',
    'thresholds': dict(DEFAULT_THRESHOLDS),
}


def _validate_protocol(document):
    if not isinstance(document, dict):
        raise TwoClassEvalError('two-class protocol must be a JSON object')
    schema = document.get('schema_version')
    if not (isinstance(schema, str)
            and schema.startswith('dsh.landmark_two_class_protocol')):
        raise TwoClassEvalError('unsupported two-class protocol schema: %r'
                                % (schema,))
    classes = document.get('classes')
    if not isinstance(classes, dict) or '0' not in classes or '1' not in classes:
        raise TwoClassEvalError('two-class protocol needs classes 0 and 1')
    thresholds = document.get('thresholds')
    if thresholds is not None:
        tau = thresholds.get('tau_bearing_deg')
        if tau is not None and (not isinstance(tau, (int, float)) or tau <= 0):
            raise TwoClassEvalError('tau_bearing_deg must be > 0')


def merge_protocol(document):
    _validate_protocol(document)
    merged = _merge(DEFAULT_PROTOCOL, document)
    merged['_source'] = {'path': None, 'sha256': None,
                         'status': document.get('status'),
                         'schema_version': document.get('schema_version')}
    return merged


def load_protocol(path=None):
    target = Path(path) if path is not None else _repo_root() / DEFAULT_PROTOCOL_PATH
    if not target.is_file():
        raise TwoClassEvalError('two-class protocol not found: %s' % target)
    document = json.loads(target.read_text(encoding='utf-8'))
    _validate_protocol(document)
    merged = _merge(DEFAULT_PROTOCOL, document)
    merged['_source'] = {'path': str(target),
                         'sha256': _sha256_file(target),
                         'status': document.get('status'),
                         'schema_version': document.get('schema_version')}
    return merged


# --- ground truth -----------------------------------------------------------

def _xyxy_to_xywh(values):
    x1, y1, x2, y2 = [float(v) for v in values[:4]]
    return [min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)]


def _intrinsics(annotation):
    basis = annotation.get('pixel_basis') or {}
    if basis.get('fx_px') is not None and basis.get('cx_px') is not None:
        return {'fx_px': float(basis['fx_px']),
                'cx_px': float(basis['cx_px']),
                'cy_px': (float(basis['cy_px'])
                          if basis.get('cy_px') is not None else None)}
    return dict(DEFAULT_INTRINSICS)


def _instance_bbox(instance):
    for key in ('bbox_xyxy', 'bbox', 'box_xyxy', 'source_image_pixels_xyxy'):
        value = instance.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return _xyxy_to_xywh(value)
    for key in ('bbox_xywh', 'box_xywh'):
        value = instance.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return [float(v) for v in value]
    return None


def _instance_class(instance):
    for key in ('class', 'class_id', 'cls'):
        if instance.get(key) is not None:
            return int(instance[key])
    return 0


def _instance_keypoint(instance, width, height):
    """Return (keypoint_px, reference_available) for a class-0 instance."""
    if instance.get('keypoint_normalized') is not None:
        value = instance['keypoint_normalized']
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [float(value[0]) * width, float(value[1]) * height], True
    for key in ('keypoint_px', 'keypoint_source_pixels'):
        value = instance.get(key)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [float(value[0]), float(value[1])], True
    for key in ('keypoint', 'kp'):
        value = instance.get(key)
        if isinstance(value, dict):
            if value.get('normalized') is True:
                return ([float(value['x']) * width,
                         float(value['y']) * height], True)
            if value.get('x') is not None and value.get('y') is not None:
                return [float(value['x']), float(value['y'])], True
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            x, y = float(value[0]), float(value[1])
            if x <= 1.0 and y <= 1.0 and width > 2 and height > 2:
                return [x * width, y * height], True
            return [x, y], True
    if instance.get('keypoint_x') is not None and instance.get('keypoint_y') is not None:
        x = float(instance['keypoint_x'])
        y = float(instance['keypoint_y'])
        # dsh.landmark_two_class_annotations.v1 stores class0 keypoints normalised
        # [0,1]; legacy/derived docs store keypoint_px in source pixels.
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and width > 2 and height > 2:
            return [x * width, y * height], True
        return [x, y], True
    return None, False


def truth_from_two_class_annotation(annotation):
    """Truth row from a two-class annotation item.

    Accepts the label-spec v1 item shape and the train-side
    dsh.landmark_two_class_annotations.v1 frame shape (frames[]/instances[],
    bbox in source pixels xyxy, class0 keypoint optionally normalized [0,1]).
    """
    width = int(annotation.get('image_width') or 320)
    height = int(annotation.get('image_height') or 240)
    instances = annotation.get('instances') or []
    tower_bbox = None
    tower_keypoint = None
    tower_reference = None
    ms1_boxes = []
    other_boxes = []
    class0_reference_available = False
    for instance in instances:
        class_id = _instance_class(instance)
        bbox = _instance_bbox(instance)
        if class_id == 1:
            if bbox is not None:
                kind = str(instance.get('structure_kind')
                           or instance.get('confuser_kind') or '').upper()
                if (instance.get('synthetic_injected') is True
                        or 'SYNTHETIC' in kind or 'OTHER' in kind
                        or (kind and 'MAP_NATIVE' not in kind and kind != '')):
                    other_boxes.append([float(v) for v in bbox])
                else:
                    ms1_boxes.append([float(v) for v in bbox])
            continue
        if bbox is not None and tower_bbox is None:
            tower_bbox = [float(v) for v in bbox]
        keypoint_px, has_keypoint = _instance_keypoint(instance, width, height)
        visibility = instance.get('v', instance.get('visible'))
        if visibility is not None and int(visibility) != 1:
            has_keypoint = False
        if instance.get('reference_available') is False:
            has_keypoint = False
        if has_keypoint and tower_keypoint is None:
            tower_keypoint = keypoint_px
            class0_reference_available = True
    tower_present = bool(annotation.get('tower_present', bool(instances)))
    ms1_present = bool(annotation.get('ms1_present', bool(ms1_boxes)))
    occluded = bool(annotation.get('occluded'))
    gt_uncertain = bool(annotation.get('gt_uncertainty')
                        or annotation.get('identity_ambiguity'))
    explicit_unobservable = annotation.get('gt_unobservable')
    if explicit_unobservable is not None:
        gt_unobservable = bool(explicit_unobservable)
    else:
        gt_unobservable = bool((tower_present and tower_bbox is None)
                               or (tower_present and occluded and tower_bbox is None))
    if gt_unobservable:
        tower_bbox = None
        tower_keypoint = None
    explicit_observable = annotation.get('tower_observable')
    if explicit_observable is not None:
        tower_observable = bool(explicit_observable) and tower_present
    else:
        tower_observable = bool(tower_present and not gt_unobservable
                                and not gt_uncertain)
    explicit_negative = annotation.get('negative')
    negative = (bool(explicit_negative) if explicit_negative is not None
                else bool(not tower_present and not gt_unobservable))
    explicit_ms1_only = annotation.get('ms1_only')
    ms1_only = (bool(explicit_ms1_only) if explicit_ms1_only is not None
                else bool(ms1_present and not tower_present))
    explicit_same_frame = annotation.get('same_frame')
    same_frame = (bool(explicit_same_frame) if explicit_same_frame is not None
                  else bool(tower_present and ms1_present and not gt_unobservable))
    if tower_present and not gt_unobservable:
        tower_reference = ('VISIBLE' if class0_reference_available
                           else 'UNAVAILABLE')
    frame_id = annotation.get('frame_id')
    return {
        'frame_id': frame_id,
        'image': annotation.get('image', 'images/' + str(frame_id)),
        'image_width': int(annotation.get('image_width') or 320),
        'image_height': int(annotation.get('image_height') or 240),
        'intrinsics': _intrinsics(annotation),
        'tower_present': tower_present,
        'ms1_present': ms1_present,
        'gt_tower_bbox': tower_bbox,
        'gt_tower_reference': tower_reference,
        'gt_tower_keypoint': tower_keypoint,
        'gt_ms1_boxes': ms1_boxes,
        'gt_other_boxes': other_boxes,
        'tower_observable': tower_observable,
        'gt_uncertain': gt_uncertain,
        'gt_unobservable': gt_unobservable,
        'negative': negative,
        'ms1_only': ms1_only,
        'same_frame': same_frame,
        'family': str(annotation.get('family') or
                      (annotation.get('source') or {}).get('family')
                      or 'UNSPECIFIED'),
        'scale': str(annotation.get('scale') or 'UNKNOWN'),
        'truncation': str(annotation.get('truncation') or 'NOT_TRUNCATED'),
    }


def _route_confuser(confuser, box, ms1_boxes, other_boxes):
    """class1 GT is ONLY verified map-native MS1; everything else is OTHER."""
    source = str(confuser.get('verification_source') or '').upper()
    kind = str(confuser.get('confuser_kind') or confuser.get('kind') or '').upper()
    note = str(confuser.get('verification_note') or '').upper()
    synthetic = ('SYNTHETIC' in note or confuser.get('synthetic_injected') is True
                 or 'SYNTHETIC' in kind)
    map_native = ('MAP_NATIVE' in kind or 'MAP_NATIVE' in note
                  or source == 'WORLD_POSE_OR_MAP_DB')
    if map_native and not synthetic:
        ms1_boxes.append(box)
    else:
        other_boxes.append(box)


def build_truth_from_identity_pool(labels, decisions=None):
    """Build two-class truth from the existing v2.1 identity labels + decisions."""
    labels_doc = (json.loads(Path(labels).read_text(encoding='utf-8'))
                  if not isinstance(labels, dict) else labels)
    decisions_doc = None
    if decisions is not None:
        decisions_doc = (json.loads(Path(decisions).read_text(encoding='utf-8'))
                         if not isinstance(decisions, dict) else decisions)
    decision_by_frame = {}
    if decisions_doc:
        for frame in decisions_doc.get('frames') or []:
            decision_by_frame[frame.get('frame_id')] = frame
    rows = []
    for annotation in labels_doc.get('annotations') or []:
        frame_id = annotation.get('frame_id')
        decision = decision_by_frame.get(frame_id)
        target = annotation.get('target') or {}
        geometry = annotation.get('geometry') or {}
        present = bool(target.get('present'))
        undecidable = bool(target.get('undecidable'))
        ambiguous = bool(target.get('ambiguous'))
        occluded = bool(target.get('occluded'))
        bbox = geometry.get('bbox_xywh')
        tower_bbox = [float(v) for v in bbox] if bbox is not None else None
        ms1_boxes = []
        other_boxes = []
        condition = ''
        target_keypoint = None
        if isinstance(decision, dict):
            condition = str(decision.get('identity_condition') or '')
            if decision.get('target_bbox'):
                tower_bbox = [float(v) for v in decision['target_bbox']]
            if decision.get('target_keypoint'):
                target_keypoint = [float(v) for v in decision['target_keypoint']]
            for confuser in decision.get('confusers') or []:
                if confuser.get('bbox_xywh'):
                    box = [float(v) for v in confuser['bbox_xywh']]
                    _route_confuser(confuser, box, ms1_boxes, other_boxes)
        for confuser in annotation.get('confusers') or []:
            if isinstance(confuser, dict) and confuser.get('bbox_xywh'):
                box = [float(v) for v in confuser['bbox_xywh']]
                if box not in ms1_boxes and box not in other_boxes:
                    _route_confuser(confuser, box, ms1_boxes, other_boxes)
        gt_unobservable = bool(occluded and bbox is None)
        if present and (undecidable or ambiguous):
            gt_unobservable = True
        if gt_unobservable:
            tower_bbox = None
        keypoint = None
        reference = None
        if present and not gt_unobservable:
            if geometry.get('keypoint') and geometry['keypoint'].get('visible'):
                if target_keypoint is None:
                    target_keypoint = [float(geometry['keypoint']['x']),
                                       float(geometry['keypoint']['y'])]
            keypoint = target_keypoint
            reference = ('VISIBLE' if (keypoint is not None
                                       and geometry.get('reference_status')
                                       == 'MANUAL_APPROX')
                         else 'UNAVAILABLE')
        rows.append({
            'frame_id': frame_id,
            'image': annotation.get('image', 'images/' + str(frame_id)),
            'image_width': int(annotation.get('image_width') or 320),
            'image_height': int(annotation.get('image_height') or 240),
            'intrinsics': _intrinsics(annotation),
            'tower_present': present,
            'ms1_present': bool(ms1_boxes),
            'gt_tower_bbox': tower_bbox,
            'gt_tower_reference': reference,
            'gt_tower_keypoint': keypoint,
            'gt_ms1_boxes': ms1_boxes,
            'gt_other_boxes': other_boxes,
            'tower_observable': bool(present and not gt_unobservable
                                     and not (undecidable or ambiguous)),
            'gt_uncertain': bool(undecidable or ambiguous),
            'gt_unobservable': gt_unobservable,
            'negative': bool(not present and not gt_unobservable),
            'ms1_only': bool(ms1_boxes and not present),
            'same_frame': bool(present and ms1_boxes and not gt_unobservable),
            'family': str((annotation.get('source') or {}).get('family')
                          or 'UNSPECIFIED'),
            'scale': 'UNKNOWN',
            'truncation': 'TRUNCATED' if target.get('truncated') else 'NOT_TRUNCATED',
            'identity_condition': condition,
        })
    return rows


# --- observations / decoding ------------------------------------------------

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


def _normalise_detection(detection):
    bbox = detection.get('bbox_xywh')
    if bbox is None and detection.get('bbox_xyxy') is not None:
        bbox = _xyxy_to_xywh(detection['bbox_xyxy'])
    if bbox is None:
        raise TwoClassEvalError('detection without bbox')
    class_id = int(detection.get('class_id', 0))
    keypoint = detection.get('keypoint_px')
    if class_id == 1:
        keypoint = None  # class 1 has no same-semantic reference point
    return {
        'class_id': class_id,
        'bbox_xywh': [float(v) for v in bbox],
        'score': float(detection.get('score') or 0.0),
        'keypoint_px': (None if keypoint is None
                        else [float(v) for v in keypoint]),
        'keypoint_confidence': detection.get('keypoint_confidence'),
        'reference_available': bool(class_id == 0 and keypoint is not None),
    }


def decode_detections(detections, frame_id, protocol, *, thresholds=None):
    """Decode raw two-class detections into a consumer observation record.

    Structural GT isolation: the decoder only receives the frame_id (a name) and
    the detections.  Ground-truth position/bbox/keypoint/class fields are never
    accepted here; GT is used only by evaluate_frame for scoring.  Passing a
    truth row raises instead of silently coupling inference to GT.
    """
    if isinstance(frame_id, dict):
        raise TwoClassEvalError(
            'decode_detections must not receive ground truth; pass frame_id string')
    merged = _merge(DEFAULT_THRESHOLDS, protocol.get('thresholds') or {})
    if thresholds:
        merged.update(thresholds)
    normalised = [_normalise_detection(detection) for detection in detections]
    usable = [detection for detection in normalised
              if detection['score'] >= merged['tau_det']]
    class0 = sorted([d for d in usable if d['class_id'] == 0],
                    key=lambda d: d['score'], reverse=True)
    class1 = [d for d in usable if d['class_id'] == 1]
    conflict = any(_iou(a['bbox_xywh'], b['bbox_xywh']) >= merged['tau_conflict']
                   for a in class0 for b in class1)
    reject_reason = None
    tower_claim = None
    tower_claim_source = None
    if not class0:
        reject_reason = 'NO_TOWER_CLASS'
        if not usable:
            status = 'NOT_DETECTED'
        else:
            status = 'DETECTED'
    else:
        status = 'DETECTED'
        if conflict:
            reject_reason = 'CLASS_CONFLICT'
        elif len(class0) >= 2 and (class0[0]['score'] - class0[1]['score']) < merged['tau_margin']:
            reject_reason = 'MULTIPLE_CANDIDATES'
        else:
            tower_claim = CENTRAL_TOWER_ID
            tower_claim_source = 'CLASS0'
    reference_available = False
    keypoint_px = None
    if tower_claim and class0:
        top = class0[0]
        confident = (top['keypoint_px'] is not None
                     and (top['keypoint_confidence'] is None
                          or float(top['keypoint_confidence']) >= merged['tau_kpt']))
        if confident:
            reference_available = True
            keypoint_px = list(top['keypoint_px'])
    return {
        'frame_id': frame_id,
        'status': status,
        'detections': usable,
        'landmark_id': tower_claim,
        'tower_claim_source': tower_claim_source,
        'reference_available': reference_available,
        'keypoint_px': keypoint_px,
        'reject_reason': reject_reason,
        'thresholds': merged,
    }


def single_class_predictions_to_observations(predictions):
    """Adapt saved single-class metric predictions to two-class observations."""
    observations = {}
    for frame_id, record in predictions.items():
        prediction = record.get('prediction', record)
        detections = []
        if (prediction.get('status') == 'DETECTED'
                and prediction.get('bbox_xywh') is not None):
            detections.append({
                'class_id': 0,
                'bbox_xywh': [float(v) for v in prediction['bbox_xywh']],
                'score': float(prediction.get('score') or 0.0),
                'keypoint_px': (None if prediction.get('keypoint_px') is None
                                else [float(v) for v in prediction['keypoint_px']]),
                'keypoint_confidence': None,
            })
        observations[frame_id] = {
            'frame_id': frame_id,
            'status': prediction.get('status', 'UNKNOWN'),
            'detections': detections,
            'landmark_id': prediction.get('landmark_id'),
            'tower_claim_source': ('CLASS0' if prediction.get('landmark_id')
                                   else None),
            'reference_available': prediction.get('keypoint_px') is not None,
            'keypoint_px': prediction.get('keypoint_px'),
            'reject_reason': prediction.get('reject_reason'),
        }
    return observations


def load_two_class_labels(path):
    """Load a two-class label document (label-spec frames[] or annotations[])."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    annotations = document.get('annotations')
    if annotations is None:
        annotations = document.get('frames')
    if not isinstance(annotations, list):
        raise TwoClassEvalError(
            'two-class labels document has no annotations/frames list')
    return document, [truth_from_two_class_annotation(annotation)
                      for annotation in annotations]


def load_predictions(path):
    predictions = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        frame_id = record.get('frame_id') or record.get('gt_frame_id')
        if not frame_id:
            raise TwoClassEvalError('prediction without frame_id')
        predictions[frame_id] = record
    return predictions


# --- per-frame evaluation ---------------------------------------------------

def _match_instances(pred_detections, gt_boxes, tau_iou):
    """Greedy IoU matching; returns (pairs, unmatched_pred, unmatched_gt)."""
    pairs = []
    used_pred = set()
    used_gt = set()
    candidates = []
    for pred_index, detection in enumerate(pred_detections):
        for gt_index, box in enumerate(gt_boxes):
            iou = _iou(detection['bbox_xywh'], box)
            if iou >= tau_iou:
                candidates.append((iou, pred_index, gt_index))
    candidates.sort(reverse=True)
    for _iou_value, pred_index, gt_index in candidates:
        if pred_index in used_pred or gt_index in used_gt:
            continue
        used_pred.add(pred_index)
        used_gt.add(gt_index)
        pairs.append((pred_index, gt_index))
    unmatched_pred = [i for i in range(len(pred_detections)) if i not in used_pred]
    unmatched_gt = [i for i in range(len(gt_boxes)) if i not in used_gt]
    return pairs, unmatched_pred, unmatched_gt


def evaluate_frame(truth_row, observation, protocol, *,
                   identity_policy='confirmed_only'):
    merged = _merge(DEFAULT_THRESHOLDS, protocol.get('thresholds') or {})
    tau_iou = float(merged['tau_iou'])
    tau_bearing = float(merged['tau_bearing_deg'])
    detections = [_normalise_detection(d) for d in observation.get('detections') or []]
    raw_claim = observation.get('landmark_id') is not None
    policy = identity_policy or 'confirmed_only'
    if policy not in IDENTITY_POLICIES:
        raise TwoClassEvalError('unsupported identity_policy: %r' % (policy,))
    tower_present = bool(truth_row['tower_present'])
    unobservable = bool(truth_row.get('gt_unobservable'))
    uncertain = bool(truth_row.get('gt_uncertain'))
    observable = bool(truth_row.get(
        'tower_observable',
        tower_present and not unobservable and not uncertain))
    same_frame = bool(truth_row.get('same_frame'))
    ms1_only = bool(truth_row.get(
        'ms1_only', bool(truth_row.get('ms1_present')) and not tower_present))

    class0 = [d for d in detections if d['class_id'] == 0]
    class1 = [d for d in detections if d['class_id'] == 1]
    gt_tower_boxes = ([truth_row['gt_tower_bbox']]
                      if truth_row.get('gt_tower_bbox') is not None else [])
    gt_ms1_boxes = list(truth_row.get('gt_ms1_boxes') or [])
    gt_other_boxes = list(truth_row.get('gt_other_boxes') or [])
    tower_pairs, tower_fp, tower_fn = _match_instances(class0, gt_tower_boxes, tau_iou)
    ms1_pairs, ms1_fp, ms1_fn = _match_instances(class1, gt_ms1_boxes, tau_iou)
    matched_tower_pred = [pair[0] for pair in tower_pairs]
    matched_ms1_pred = [pair[0] for pair in ms1_pairs]
    # misclassification: an unmatched prediction geometrically matching a GT of
    # the other class
    other_structure_hits = 0
    for pred_index in tower_fp:
        for box in gt_other_boxes:
            if _iou(class0[pred_index]['bbox_xywh'], box) >= tau_iou:
                other_structure_hits += 1
                break
    misclassified = 0
    for pred_index in tower_fp:
        for box in gt_ms1_boxes:
            if _iou(class0[pred_index]['bbox_xywh'], box) >= tau_iou:
                misclassified += 1
                break
    for pred_index in ms1_fp:
        for box in gt_tower_boxes:
            if _iou(class1[pred_index]['bbox_xywh'], box) >= tau_iou:
                misclassified += 1
                break
    class_confusion = {
        'tp': {'0': len(tower_pairs), '1': len(ms1_pairs)},
        'fp': {'0': len(tower_fp), '1': len(ms1_fp)},
        'fn': {'0': len(tower_fn), '1': len(ms1_fn)},
        'misclassified': misclassified,
    }
    tower_detected = bool(observable and tower_pairs)
    class1_mapped_violation = bool(raw_claim and not class0)
    # tower identity claim
    claim = False
    correct_claim = False
    wrong_claim = False
    wrong_category = None
    improper_claim = False
    if raw_claim:
        if policy == 'strict_unknown':
            claim = False
        elif policy == 'raw_claim_upper_bound':
            claim = True
        else:
            claim = True
        if unobservable:
            improper_claim = True
            wrong_category = 'GT_UNOBSERVABLE'
        elif uncertain:
            improper_claim = True
            wrong_category = 'GT_UNCERTAIN'
        elif tower_present and observable:
            correct_claim = claim and tower_detected
            if not correct_claim:
                wrong_category = ('SAME_FRAME' if same_frame else 'WRONG_TARGET')
        else:
            if truth_row['ms1_present']:
                wrong_category = 'MS1_ONLY'
            elif gt_other_boxes:
                wrong_category = 'OTHER_STRUCTURE'
            else:
                wrong_category = 'NEGATIVE'
        if claim and not correct_claim and wrong_category is None:
            wrong_category = 'WRONG_TARGET'
    correct_claim = bool(claim and correct_claim)
    if unobservable or uncertain:
        correct_claim = False
    wrong_claim = bool(claim and not correct_claim)

    # reference handling (class 0 only)
    reference = truth_row.get('gt_tower_reference')
    reference_correct = None
    false_reference = False
    keypoint_emitted = False
    class1_keypoint_emitted = bool(class1_kpt_emitted(class1))
    if observable:
        if reference == 'VISIBLE':
            if tower_pairs:
                top = class0[tower_pairs[0][0]]
                keypoint_emitted = top['keypoint_px'] is not None
            reference_correct = keypoint_emitted
        elif reference == 'UNAVAILABLE':
            emitted_any = any(d['keypoint_px'] is not None for d in class0)
            keypoint_emitted = emitted_any
            reference_correct = not emitted_any
            false_reference = emitted_any
    bearing_error = None
    bearing_ok = None
    px_2d_error = None
    if (observable and reference == 'VISIBLE' and tower_pairs
            and truth_row.get('gt_tower_keypoint') is not None):
        top = class0[tower_pairs[0][0]]
        if top['keypoint_px'] is not None:
            gt_keypoint = truth_row['gt_tower_keypoint']
            dx = float(top['keypoint_px'][0]) - float(gt_keypoint[0])
            dy = float(top['keypoint_px'][1]) - float(gt_keypoint[1])
            px_2d_error = math.hypot(dx, dy)
            intrinsics = truth_row.get('intrinsics') or {}
            fx = intrinsics.get('fx_px')
            cx = intrinsics.get('cx_px')
            if fx:
                pred_bearing = math.degrees(math.atan2(
                    float(top['keypoint_px'][0]) - cx, fx))
                gt_bearing = math.degrees(math.atan2(
                    float(gt_keypoint[0]) - cx, fx))
                bearing_error = abs(pred_bearing - gt_bearing)
                bearing_ok = bearing_error <= tau_bearing
            else:
                bearing_ok = False
    elif observable and reference == 'VISIBLE':
        bearing_ok = False

    status = observation.get('status')
    valid = status in ('DETECTED', 'NOT_DETECTED') and observation.get(
        'reject_reason') not in ('STALE', 'DUPLICATE', 'GENERATION_MISMATCH',
                                 'MISSING_CALIBRATION', 'INVALID_IMAGE')
    domain_all = bool(tower_present)
    domain_observable = observable
    domain_reference = bool(observable and reference == 'VISIBLE')
    domain_negative = bool(truth_row.get('negative', not tower_present and not unobservable))
    if domain_observable:
        success = bool(valid and tower_detected and correct_claim
                       and reference_correct is True
                       and (bearing_ok is not False))
    elif domain_all:
        success = False
    elif domain_negative:
        success = bool(valid and not claim)
    else:
        success = False
    improper_keypoint = bool((unobservable or uncertain)
                             and (keypoint_emitted or class1_keypoint_emitted))
    return {
        'frame_id': truth_row['frame_id'],
        'identity_policy': policy,
        'valid': valid,
        'status': status,
        'tower_present': tower_present,
        'ms1_present': bool(truth_row['ms1_present']),
        'other_present': bool(gt_other_boxes),
        'other_structure_hits': other_structure_hits,
        'gt_uncertain': uncertain,
        'gt_unobservable': unobservable,
        'same_frame': same_frame,
        'ms1_only': ms1_only,
        'negative': bool(truth_row.get('negative', False)),
        'class_confusion': class_confusion,
        'tower_detected': tower_detected,
        'tower_claim': claim,
        'raw_claim': raw_claim,
        'tower_claim_correct': correct_claim,
        'wrong_claim': wrong_claim,
        'wrong_claim_category': wrong_category,
        'improper_claim': improper_claim,
        'class1_mapped_violation': class1_mapped_violation,
        'reference': reference,
        'reference_correct': reference_correct,
        'false_reference': false_reference,
        'keypoint_emitted': keypoint_emitted,
        'class1_keypoint_emitted': class1_keypoint_emitted,
        'improper_keypoint': improper_keypoint,
        'bearing_error_deg': bearing_error,
        'bearing_ok': bearing_ok,
        'px_2d_error': px_2d_error,
        'domain_flags': {
            'all_positive': domain_all,
            'observable_positive': domain_observable,
            'reference_available': domain_reference,
            'negatives': domain_negative,
        },
        'success': success,
        'family': truth_row.get('family', 'UNSPECIFIED'),
        'scale': truth_row.get('scale', 'UNKNOWN'),
        'truncation': truth_row.get('truncation', 'NOT_TRUNCATED'),
    }


def class1_kpt_emitted(class1_detections):
    return [d for d in class1_detections if d['keypoint_px'] is not None]


# --- aggregation ------------------------------------------------------------

def _domain_summary(rows, key):
    members = [row for row in rows if row['domain_flags'][key]]
    successes = sum(1 for row in members if row['success'])
    return {'denominator': len(members), 'success': successes,
            'success_rate': _rate(successes, len(members)),
            'unknown_or_rejected': sum(1 for row in members if not row['valid']),
            'tower_claim': sum(1 for row in members if row['tower_claim']),
            'no_keypoint': sum(1 for row in members
                               if not row['keypoint_emitted'])}


def summarize(rows, *, protocol, identity_policy='confirmed_only'):
    rows = list(rows)
    policy = identity_policy or 'confirmed_only'
    tau_bearing = float(_merge(DEFAULT_THRESHOLDS,
                               protocol.get('thresholds') or {})['tau_bearing_deg'])
    classes = {}
    for class_id in (0, 1):
        tp = sum(row['class_confusion']['tp'][str(class_id)] for row in rows)
        fp = sum(row['class_confusion']['fp'][str(class_id)] for row in rows)
        fn = sum(row['class_confusion']['fn'][str(class_id)] for row in rows)
        classes[str(class_id)] = {
            'name': CLASS_NAMES[class_id],
            'tp': tp, 'fp': fp, 'fn': fn,
            'gt_instances': tp + fn,
            'precision': _rate(tp, tp + fp),
            'recall': _rate(tp, tp + fn),
        }
    confusion = Counter()
    for row in rows:
        for class_id in (0, 1):
            confusion['gt_%d_pred_%d' % (class_id, class_id)] += \
                row['class_confusion']['tp'][str(class_id)]
    misclassified = sum(row['class_confusion']['misclassified'] for row in rows)

    observable = [row for row in rows if row['domain_flags']['observable_positive']]
    negatives = [row for row in rows if row['domain_flags']['negatives']]
    ms1_only_rows_all = [row for row in rows if row.get('ms1_only')]
    wrong_claim_denominator_rows = [row for row in rows
                                    if row['domain_flags']['negatives']
                                    or row.get('ms1_only')]
    reference_rows = [row for row in rows if row['domain_flags']['reference_available']]
    claims = [row for row in rows if row['tower_claim']]
    correct = [row for row in claims if row['tower_claim_correct']]
    wrong_categories = Counter()
    for row in claims:
        if not row['tower_claim_correct']:
            wrong_categories[row['wrong_claim_category'] or 'UNSPECIFIED'] += 1
    ms1_only_rows = [row for row in rows
                     if not row['tower_present'] and row['ms1_present']]
    ms1_wrong = [row for row in ms1_only_rows if row['tower_claim']]
    same_frame_rows = [row for row in rows if row['same_frame']]
    same_selected = sum(1 for row in same_frame_rows if row['tower_claim_correct'])
    same_ms1 = sum(1 for row in same_frame_rows
                   if row['tower_claim'] and not row['tower_claim_correct']
                   and row['wrong_claim_category'] == 'SAME_FRAME')
    same_none = len(same_frame_rows) - same_selected - same_ms1
    reference_emitted = [row for row in observable
                         if row['reference'] == 'VISIBLE' and row['keypoint_emitted']]
    unavailable_rows = [row for row in observable
                        if row['reference'] == 'UNAVAILABLE']
    bearing_rows = [row for row in reference_rows
                    if row['bearing_error_deg'] is not None]
    bearing_pass = [row for row in bearing_rows
                    if row['bearing_error_deg'] <= tau_bearing]
    px_rows = [row for row in observable if row['px_2d_error'] is not None]
    unobservable_rows = [row for row in rows if row['gt_unobservable']]
    uncertain_rows = [row for row in rows if row['gt_uncertain']]
    summary = {
        'schema_version': TWO_CLASS_SCHEMA,
        'protocol': {
            'schema_version': protocol.get('schema_version'),
            'status': protocol.get('status'),
            'sha256': protocol['_source']['sha256'],
            'path': protocol['_source']['path'],
            'tau_bearing_deg': tau_bearing,
        },
        'identity_policy': policy,
        'classes': classes,
        'tower_class_recall': classes['0']['recall'],
        'confusion_matrix': dict(sorted(confusion.items())),
        'misclassified_instances': misclassified,
        'identity': {
            'claims': len(claims),
            'raw_claims': sum(1 for row in rows if row['raw_claim']),
            'correct_claims': len(correct),
            'wrong_claims': len(claims) - len(correct),
            'precision': _rate(len(correct), len(claims)),
            'recall': _rate(len(correct), len(observable)),
            'wrong_claim_denominator': len(wrong_claim_denominator_rows),
            'false_match_rate': _rate(
                sum(1 for row in wrong_claim_denominator_rows
                    if row['tower_claim']),
                len(wrong_claim_denominator_rows)),
            'wrong_claim_categories': dict(sorted(wrong_categories.items())),
            'ms1_only_frames': len(ms1_only_rows),
            'ms1_only_wrong_claims': len(ms1_wrong),
            'class1_mapped_violations': sum(
                1 for row in rows if row['class1_mapped_violation']),
        },
        'other_structures': {
            'frames': sum(1 for row in rows if row.get('other_present')),
            'class0_hits': sum(row.get('other_structure_hits', 0) for row in rows),
            'tower_claims': sum(1 for row in rows
                                if row.get('other_present') and row['tower_claim']),
            'wrong_claims': sum(1 for row in rows
                                if row.get('other_present') and row['tower_claim']
                                and not row['tower_claim_correct']),
            'note': 'class1 GT is ONLY verified map-native MS1; synthetic HN1 / '
                    'other structures are excluded from the class1 denominator '
                    'and reported here separately',
        },
        'same_frame': {
            'denominator': len(same_frame_rows),
            'tower_selected': same_selected,
            'ms1_selected': same_ms1,
            'not_selected': same_none,
            'tower_selection_rate': _rate(same_selected, len(same_frame_rows)),
        },
        'reference': {
            'available_denominator': len(reference_rows),
            'unavailable_denominator': len(unavailable_rows),
            'emitted': len(reference_emitted),
            'coverage': _rate(len(reference_emitted), len(reference_rows)),
            'declared_correct': sum(1 for row in unavailable_rows
                                    if row['reference_correct'] is True),
            'declaration_rate': _rate(
                sum(1 for row in unavailable_rows if row['reference_correct'] is True),
                len(unavailable_rows)),
            'false_reference': sum(1 for row in unavailable_rows
                                   if row['false_reference']),
            'false_reference_rate': _rate(
                sum(1 for row in unavailable_rows if row['false_reference']),
                len(unavailable_rows)),
            'class1_keypoint_emissions': sum(
                1 for row in rows if row['class1_keypoint_emitted']),
            'bearing': {
                'count': len(bearing_rows),
                'tau_bearing_deg': tau_bearing,
                'pass': len(bearing_pass),
                'pass_rate_of_emitted': _rate(len(bearing_pass), len(bearing_rows)),
                **_error_stats([row['bearing_error_deg'] for row in bearing_rows],
                               unit='deg'),
            },
        },
        'domains': {
            'all_positive': _domain_summary(rows, 'all_positive'),
            'observable_positive': _domain_summary(rows, 'observable_positive'),
            'reference_available': _domain_summary(rows, 'reference_available'),
            'negatives': _domain_summary(rows, 'negatives'),
        },
        'gt_unobservable': {
            'frames': len(unobservable_rows),
            'tower_claims': sum(1 for row in unobservable_rows if row['tower_claim']),
            'keypoints': sum(1 for row in unobservable_rows
                             if row['keypoint_emitted']),
            'improper_claims': sum(1 for row in unobservable_rows
                                   if row['improper_claim']),
            'correct_abstentions': sum(
                1 for row in unobservable_rows
                if not row['tower_claim'] and not row['keypoint_emitted']),
        },
        'gt_uncertain': {
            'frames': len(uncertain_rows),
            'tower_claims': sum(1 for row in uncertain_rows if row['tower_claim']),
            'keypoints': sum(1 for row in uncertain_rows if row['keypoint_emitted']),
            'improper_claims': sum(1 for row in uncertain_rows
                                   if row['improper_claim']),
        },
        'diagnostics_only': {
            'px_2d_error': _error_stats([row['px_2d_error'] for row in px_rows],
                                        unit='px'),
            'note': '2D pixel error is diagnostic only; consumer success uses '
                    'the horizontal bearing tolerance',
        },
        'counts': {'frames': len(rows),
                   'all_positive': sum(1 for row in rows
                                       if row['domain_flags']['all_positive']),
                   'observable_positive': len(observable),
                   'reference_available': len(reference_rows),
                   'negatives': len(negatives)},
    }
    return summary


def evaluate_rows(truth_rows, observations, protocol, *, identity_policy='confirmed_only'):
    if isinstance(observations, dict):
        observations_by_frame = observations
    else:
        observations_by_frame = {observation['frame_id']: observation
                                 for observation in observations}
    rows = []
    for truth_row in truth_rows:
        observation = observations_by_frame.get(truth_row['frame_id'])
        if observation is None:
            observation = {'frame_id': truth_row['frame_id'],
                           'status': 'UNKNOWN', 'detections': [],
                           'landmark_id': None, 'reject_reason': 'MISSING_PREDICTION'}
        rows.append(evaluate_frame(truth_row, observation, protocol,
                                   identity_policy=identity_policy))
    return {'summary': summarize(rows, protocol=protocol,
                                 identity_policy=identity_policy),
            'rows': rows}


def compare_summaries(single_class, two_class):
    def pick(summary):
        return {
            'domains': summary['domains'],
            'classes': {'tower_class_recall': summary['classes']['0']['recall'],
                        'ms1_class_recall': summary['classes']['1']['recall'],
                        'tower_class_precision': summary['classes']['0']['precision'],
                        'ms1_class_precision': summary['classes']['1']['precision']},
            'identity': summary['identity'],
            'same_frame': summary['same_frame'],
            'reference': summary['reference'],
            'confusion_matrix': summary['confusion_matrix'],
        }
    single = pick(single_class)
    both = pick(two_class)
    domains = {}
    for domain in single['domains']:
        domains[domain] = {
            'single_class_rate': single['domains'][domain]['success_rate'],
            'two_class_rate': both['domains'][domain]['success_rate'],
            'delta': ((both['domains'][domain]['success_rate'] or 0.0)
                      - (single['domains'][domain]['success_rate'] or 0.0)),
            'denominator_same': (single['domains'][domain]['denominator']
                                 == both['domains'][domain]['denominator']),
        }
    return {'single_class': single, 'two_class': both,
            'delta': {'domains': domains,
                      'tower_class_recall': ((both['classes']['tower_class_recall'] or 0.0)
                                             - (single['classes']['tower_class_recall'] or 0.0))},
            'note': 'same definitions/denominators; only the model differs'}


# --- inference adapter (GT-isolated) ----------------------------------------

def _to_list(value):
    if value is None:
        return []
    if hasattr(value, 'detach'):
        value = value.detach()
    if hasattr(value, 'tolist'):
        return value.tolist()
    return list(value)


def detections_from_ultralytics_result(result):
    """Convert an ultralytics two-class result into raw detections.

    Only model outputs are read (boxes/keypoints); class 1 keypoints are dropped.
    """
    boxes = result.boxes
    keypoints = result.keypoints
    detections = []
    if boxes is None:
        return detections
    xyxy = _to_list(boxes.xyxy) if len(boxes) else []
    conf = _to_list(boxes.conf) if len(boxes) else []
    cls = _to_list(boxes.cls) if len(boxes) else []
    kxy = _to_list(keypoints.xy) if keypoints is not None and len(keypoints) else []
    kconf = (_to_list(keypoints.conf)
             if keypoints is not None and len(keypoints) else [])
    for index, box in enumerate(xyxy):
        class_id = int(cls[index]) if index < len(cls) else 0
        keypoint = None
        keypoint_confidence = None
        if class_id == 0 and index < len(kxy) and kxy[index]:
            keypoint = [float(v) for v in kxy[index][0]]
            if index < len(kconf) and kconf[index]:
                keypoint_confidence = float(kconf[index][0])
        detections.append({'class_id': class_id,
                           'bbox_xyxy': [float(v) for v in box],
                           'score': float(conf[index]) if index < len(conf) else 0.0,
                           'keypoint_px': keypoint,
                           'keypoint_confidence': keypoint_confidence})
    return detections


def _default_image(images_dir, truth_row):
    images_dir = Path(images_dir)
    candidates = [images_dir / Path(str(truth_row.get('image', ''))).name,
                  images_dir / str(truth_row.get('image', '')),
                  images_dir / str(truth_row['frame_id'])]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def infer_observations(model, truth_rows, images_dir, protocol, *,
                       thresholds=None, imgsz=640, device='cpu', conf=0.01,
                       image_resolver=None):
    """Run a two-class model and decode observations WITHOUT reading GT fields.

    Only frame_id and image path resolution touch the truth row; class/bbox/
    keypoint/position ground truth is never passed to the decoder (structurally
    GT-isolated inference).
    """
    resolver = image_resolver or (lambda row: _default_image(images_dir, row))
    observations = {}
    for truth_row in truth_rows:
        frame_id = truth_row['frame_id']
        image_path = resolver(truth_row)
        if image_path is None:
            observations[frame_id] = {
                'frame_id': frame_id, 'status': 'UNKNOWN', 'detections': [],
                'landmark_id': None, 'reject_reason': 'MISSING_IMAGE'}
            continue
        results = model.predict(source=str(image_path), imgsz=imgsz,
                                conf=conf, device=device, verbose=False)
        detections = detections_from_ultralytics_result(results[0])
        observations[frame_id] = decode_detections(
            detections, frame_id, protocol, thresholds=thresholds or None)
    return observations


# --- saved-file evaluation --------------------------------------------------

def evaluate_saved(labels_path, predictions_path, protocol_path, *,
                   identity_policy='confirmed_only', baseline_predictions=None,
                   baseline_policy='raw_claim_upper_bound'):
    protocol = load_protocol(protocol_path)
    _document, truth_rows = load_two_class_labels(labels_path)
    observations = load_predictions(predictions_path)
    result = evaluate_rows(truth_rows, observations, protocol,
                           identity_policy=identity_policy)
    if baseline_predictions is not None:
        baseline_obs = load_predictions(baseline_predictions)
        baseline = evaluate_rows(truth_rows, baseline_obs, protocol,
                                 identity_policy=baseline_policy)
        result['baseline_comparison'] = compare_summaries(
            baseline['summary'], result['summary'])
        result['summary']['baseline_comparison'] = result['baseline_comparison']
    result['summary']['inputs'] = {
        'labels': str(labels_path),
        'labels_sha256': _sha256_file(labels_path),
        'predictions': str(predictions_path),
        'predictions_sha256': _sha256_file(predictions_path),
        'baseline_predictions': (str(baseline_predictions)
                                 if baseline_predictions is not None else None),
        'identity_policy': identity_policy,
    }
    return result
