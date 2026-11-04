"""Executable YOLO-pose toolchain for the bounded landmark experiment.

Contents (no model, no training, no Isaac dependency):

- forward/inverse letterbox transforms for bbox and keypoint coordinates;
- v2 / v2.1 annotation -> YOLO 1-keypoint label conversion with an explicit
  sidecar and an explicit exclusion/negative manifest;
- decoding of model output (ultralytics Results objects or ONNX pose tensors)
  into a landmark observation record with conditional landmark_id, reference
  handling, image bearing and the testable reject reasons;
- evaluation-side ground-truth extraction with stratified condition labels.

Label conversion delegates the core mapping to
boom_birds.evaluation.landmark_annotations.yolo_pose_target so that only one
implementation writes YOLO labels.  This module adds the document-level export
(empty labels for confirmed absence, excluded-positive manifest) and the spec
v2.1 rules that the pilot annotation exposed as P1-P3:

- four-edge truncation metadata (target.truncated_edges) recorded in the
  sidecar, inferred from the annotation bbox when the explicit field is absent;
- reference availability criterion green_pixels >= 3: a keypoint marked visible
  but with recorded green pixels below the threshold is downgraded to v=0 with
  the bbox-centre placeholder (never a reference estimate);
- negative_type=TARGET_ABSENT together with candidates[] and
  confuser_verified=false stays a valid empty-label negative; the unverified
  confuser is recorded in the sidecar instead of being silently dropped.

Model-output decoding follows the task/experiment definition: class evidence
(tower + bbox) is reported separately from identity evidence (landmark_id),
which is only claimed under the uniqueness assumptions, a single candidate, a
sufficient score margin, a satisfiable appearance check and correct reference
handling.  Physical conclusions (world bearing, distance, board deployment) are
out of scope here.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from boom_birds.evaluation.landmark_annotations import (
    validate_document,
    yolo_pose_target,
)

__all__ = [
    'LandmarkYoloError',
    'LabelConversionError',
    'DecodeError',
    'TOWER_CLASS_ID',
    'DEFAULT_LANDMARK_ID',
    'DEFAULT_MODEL_SIZE',
    'DEFAULT_THRESHOLDS',
    'DEFAULT_SCALE_BUCKETS',
    'Letterbox',
    'letterbox_params',
    'point_to_model',
    'point_from_model',
    'bbox_to_model',
    'bbox_from_model',
    'format_yolo_pose_line',
    'source_normalized_target',
    'yolo_pose_label',
    'convert_annotation_document',
    'write_yolo_dataset',
    'write_sidecar',
    'merge_thresholds',
    'image_bearing_deg',
    'unknown_observation',
    'decode_candidates',
    'decode_ultralytics_result',
    'decode_onnx_pose_output',
    'observation_to_metric_prediction',
    'ground_truth_from_annotation',
    'pixel_basis_from_annotation',
    'scale_bucket',
    'truncated_edges',
    'main',
]

OBSERVATION_SCHEMA = 'dsh.landmark_observation.v1'
LABELS_SCHEMA = 'dsh.landmark_yolo_labels.v1'
DATASET_SCHEMA = 'dsh.landmark_yolo_dataset.v1'
SUPPORTED_ANNOTATION_SCHEMAS = ('dsh.tower_annotation.v2',
                              'dsh.tower_annotation.v2_1',
                              'dsh.tower_annotation.v2.1')

TOWER_CLASS_ID = 0
TOWER_CLASS_NAME = 'tower'
DEFAULT_LANDMARK_ID = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
DEFAULT_MODEL_SIZE = 640

#: PROPOSED thresholds; tau_conf/tau_px/tau_iou are frozen on the validation set
#: before any final read (see configs/perception/landmark_training_plan_v2.json).
DEFAULT_THRESHOLDS = {
    'tau_det': 0.25,          # minimum class score for a candidate
    'tau_margin': 0.10,       # minimum top1-top2 score margin
    'tau_kpt': 0.50,          # minimum keypoint confidence for a VISIBLE reference
    'tau_trunc_min_side_px': 16.0,  # clipped side below which identity is withheld
    'tau_green_pixels': 3,    # spec v2.1 reference availability pixel criterion
}

#: PROPOSED bbox-area buckets (source-image pixels) for stratified scale reporting.
DEFAULT_SCALE_BUCKETS = (
    ('TINY', 1500.0),
    ('SMALL', 5000.0),
    ('MEDIUM', 15000.0),
    ('LARGE', float('inf')),
)

REJECT_REASONS = (
    'MULTIPLE_CANDIDATES',
    'TARGET_AMBIGUOUS',
    'REFERENCE_UNAVAILABLE',
    'OCCLUDED',
    'TRUNCATED',
    'STALE',
    'DUPLICATE',
    'GENERATION_MISMATCH',
    'MISSING_CALIBRATION',
    'INVALID_IMAGE',
)
REJECT_PRECEDENCE = ('MULTIPLE_CANDIDATES', 'TARGET_AMBIGUOUS', 'TRUNCATED',
                     'OCCLUDED', 'REFERENCE_UNAVAILABLE')
INVALID_OBSERVATION_REASONS = ('MISSING_CALIBRATION', 'INVALID_IMAGE',
                               'STALE', 'DUPLICATE', 'GENERATION_MISMATCH')
TRUNCATED_EDGE_NAMES = ('left', 'top', 'right', 'bottom')


class LandmarkYoloError(ValueError):
    """Base error for the landmark YOLO toolchain."""


class LabelConversionError(LandmarkYoloError):
    """Raised when an annotation document cannot be converted to YOLO labels."""


class DecodeError(LandmarkYoloError):
    """Raised when model output cannot be decoded into an observation record."""


# --- letterbox --------------------------------------------------------------

@dataclass(frozen=True)
class Letterbox:
    """Center-padded letterbox: x_model = x_source * scale + pad."""

    source_width: int
    source_height: int
    model_width: int
    model_height: int
    scale: float
    pad_x: float
    pad_y: float

    def as_dict(self):
        return {'scale': self.scale, 'pad_x': self.pad_x, 'pad_y': self.pad_y,
                'source_width': self.source_width,
                'source_height': self.source_height,
                'model_width': self.model_width,
                'model_height': self.model_height}


def letterbox_params(source_width, source_height, model_width=640,
                     model_height=640):
    """Deterministic center-padded letterbox parameters (inverse is exact)."""
    source_width = int(source_width)
    source_height = int(source_height)
    model_width = int(model_width)
    model_height = int(model_height)
    if min(source_width, source_height, model_width, model_height) <= 0:
        raise LandmarkYoloError('letterbox sizes must be positive')
    scale = min(model_width / float(source_width),
                model_height / float(source_height))
    pad_x = (model_width - source_width * scale) / 2.0
    pad_y = (model_height - source_height * scale) / 2.0
    return Letterbox(source_width, source_height, model_width, model_height,
                     scale, pad_x, pad_y)


def _check_letterbox(letterbox):
    if not isinstance(letterbox, Letterbox):
        raise LandmarkYoloError('letterbox must be a Letterbox instance')


def point_to_model(point, letterbox):
    _check_letterbox(letterbox)
    return (float(point[0]) * letterbox.scale + letterbox.pad_x,
            float(point[1]) * letterbox.scale + letterbox.pad_y)


def point_from_model(point, letterbox):
    _check_letterbox(letterbox)
    return ((float(point[0]) - letterbox.pad_x) / letterbox.scale,
            (float(point[1]) - letterbox.pad_y) / letterbox.scale)


def bbox_to_model(bbox_xywh, letterbox):
    _check_letterbox(letterbox)
    x, y, w, h = [float(v) for v in bbox_xywh]
    return [x * letterbox.scale + letterbox.pad_x,
            y * letterbox.scale + letterbox.pad_y,
            w * letterbox.scale, h * letterbox.scale]


def bbox_from_model(bbox_xywh, letterbox):
    _check_letterbox(letterbox)
    x, y, w, h = [float(v) for v in bbox_xywh]
    return [(x - letterbox.pad_x) / letterbox.scale,
            (y - letterbox.pad_y) / letterbox.scale,
            w / letterbox.scale, h / letterbox.scale]


def _bbox_xyxy_to_xywh(values):
    x1, y1, x2, y2 = [float(v) for v in values[:4]]
    return [min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)]


# --- label conversion -------------------------------------------------------

def source_normalized_target(target, annotation, model_width=DEFAULT_MODEL_SIZE,
                             model_height=DEFAULT_MODEL_SIZE):
    """Rewrite model-canvas-normalized target values into SOURCE-image normalization.

    YOLO txt labels are normalized by the source image size (px / src_w, px /
    src_h); the training loader applies the letterbox itself (ultralytics 8.2.0
    LetterBox._update_labels denormalizes with the source image size, then
    scales/pads).  yolo_pose_target() returns values normalized to the model
    canvas, so the exporter must undo the letterbox here.  Using model-canvas
    normalization shifts y by (pad_y - src_h*(scale-1)/2) and scales bbox h by
    src_w/src_h; this was observed as a real label-coordinate defect (2026-11-04).
    """
    if target.get('label_normalization') == 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE':
        # forward compatibility: the annotation helper may adopt source-image
        # normalization later; never transform twice.
        return dict(target)
    space = target.get('coordinate_space')
    if space not in (None, 'MODEL_CANVAS_NORMALIZED'):
        # fail loud instead of silently mis-scaling labels when the helper's
        # declared coordinate space changes.
        raise LabelConversionError(
            'unsupported yolo_pose_target coordinate_space: %r; the exporter '
            'expects MODEL_CANVAS_NORMALIZED (or an explicit '
            'label_normalization=SOURCE_IMAGE_PX_OVER_SOURCE_SIZE marker)'
            % (space,))
    width, height = _image_size(annotation)
    letterbox = target.get('letterbox')
    if isinstance(letterbox, dict) and all(
            key in letterbox for key in ('scale', 'pad_x', 'pad_y')):
        lb = Letterbox(width, height, model_width, model_height,
                       float(letterbox['scale']), float(letterbox['pad_x']),
                       float(letterbox['pad_y']))
    else:
        lb = letterbox_params(width, height, model_width, model_height)
    cx, cy, bw, bh = [float(v) for v in target['bbox_norm']]
    bbox_model = [cx * model_width - bw * model_width / 2.0,
                  cy * model_height - bh * model_height / 2.0,
                  bw * model_width, bh * model_height]
    x, y, w, h = bbox_from_model(bbox_model, lb)
    kx, ky = [float(v) for v in target['keypoint_norm']]
    px, py = point_from_model((kx * model_width, ky * model_height), lb)
    result = dict(target)
    result['bbox_norm'] = [round((x + w / 2.0) / width, 6),
                           round((y + h / 2.0) / height, 6),
                           round(w / width, 6), round(h / height, 6)]
    result['keypoint_norm'] = [round(px / width, 6), round(py / height, 6)]
    result['label_normalization'] = 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE'
    return result


def format_yolo_pose_line(target):
    """Render a yolo_pose_target() dict as one deterministic YOLO pose line."""
    values = [float(v) for v in target['bbox_norm']]
    values += [float(v) for v in target['keypoint_norm']]
    values.append(float(target['keypoint_visibility']))
    return ' '.join([str(int(target['class_id']))]
                    + ['%.6f' % value for value in values])


def _image_size(annotation):
    try:
        width = int(annotation['image_width'])
        height = int(annotation['image_height'])
    except (KeyError, TypeError, ValueError):
        raise LabelConversionError('annotation %r is missing integer '
                                   'image_width/image_height'
                                   % (annotation.get('frame_id'),))
    if width <= 0 or height <= 0:
        raise LabelConversionError('annotation %r has non-positive image size'
                                   % (annotation.get('frame_id'),))
    return width, height


def _green_pixels(annotation):
    geometry = annotation.get('geometry') or {}
    target = annotation.get('target') or {}
    for container in (geometry, target, annotation):
        value = container.get('green_pixels')
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _confuser_verified(annotation):
    target = annotation.get('target') or {}
    for container in (annotation, target):
        value = container.get('confuser_verified')
        if isinstance(value, bool):
            return value
    confusers = annotation.get('confusers')
    if isinstance(confusers, list) and confusers:
        return any(isinstance(confuser, dict)
                   and confuser.get('verified') is True
                   for confuser in confusers)
    return None


def _confuser_entry(candidate):
    return {
        'kind': 'AMBIGUOUS_CANDIDATE',
        'candidate_id': candidate.get('candidate_id'),
        'bbox_xywh': candidate.get('bbox_xywh'),
        'green_cue': candidate.get('green_cue'),
        'green_pixels': candidate.get('green_pixels'),
        'source': candidate.get('source'),
        'verified': candidate.get('confuser_verified'),
        'note': candidate.get('note'),
    }


def _v2_1_confuser_entry(confuser):
    return {
        'kind': 'CONFUSER',
        'confuser_id': confuser.get('confuser_id'),
        'description': confuser.get('description'),
        'bbox_xywh': confuser.get('bbox_xywh'),
        'green_cue': confuser.get('green_cue'),
        'verified': confuser.get('verified'),
        'verification_source': confuser.get('verification_source'),
        'verification_note': confuser.get('verification_note'),
        'source': confuser.get('source'),
    }


def _confuser_entries(annotation):
    """Combine spec v2.1 confusers[] and v2 ambiguous candidates[]."""
    entries = [_v2_1_confuser_entry(confuser)
               for confuser in (annotation.get('confusers') or [])
               if isinstance(confuser, dict)]
    entries += [_confuser_entry(candidate)
                for candidate in (annotation.get('candidates') or [])
                if isinstance(candidate, dict)]
    return entries


def truncated_edges(annotation):
    """Return the sorted four-edge truncation metadata for one annotation.

    Explicit v2.1 target.truncated_edges wins; otherwise the annotation bbox is
    checked against the image borders (fallback inference).
    """
    target = annotation.get('target') or {}
    explicit = target.get('truncated_edges')
    if isinstance(explicit, dict):
        return sorted(edge for edge in TRUNCATED_EDGE_NAMES
                      if explicit.get(edge) is True)
    if explicit:
        edges = [str(edge).lower() for edge in explicit
                 if str(edge).lower() in TRUNCATED_EDGE_NAMES]
        return sorted(set(edges))
    bbox = (annotation.get('geometry') or {}).get('bbox_xywh')
    if not bbox:
        return []
    width, height = _image_size(annotation)
    x, y, w, h = [float(v) for v in bbox]
    epsilon = 1e-6
    edges = []
    if x <= epsilon:
        edges.append('left')
    if y <= epsilon:
        edges.append('top')
    if x + w >= width - epsilon:
        edges.append('right')
    if y + h >= height - epsilon:
        edges.append('bottom')
    return sorted(edges)


def _truncated_edges_flags(annotation):
    """Return the raw v2.1 four-boolean object when the annotation carries it."""
    target = annotation.get('target') or {}
    explicit = target.get('truncated_edges')
    if isinstance(explicit, dict):
        return {edge: explicit.get(edge) is True for edge in TRUNCATED_EDGE_NAMES}
    return None


def _annotation_gt_unobservable(annotation):
    target = annotation.get('target') or {}
    if target.get('undecidable') is True:
        return True, 'UNDECIDABLE'
    if target.get('present') is True:
        if (annotation.get('geometry') or {}).get('bbox_xywh') is None:
            if target.get('visibility') == 'OCCLUDED':
                return True, 'FULL_OCCLUSION'
            return True, 'NO_VISIBLE_GT_BBOX'
    return False, None


def yolo_pose_label(annotation, *, model_width=DEFAULT_MODEL_SIZE,
                    model_height=DEFAULT_MODEL_SIZE,
                    green_pixels_threshold=DEFAULT_THRESHOLDS['tau_green_pixels']):
    """Map one v2/v2.1 annotation to (label_text, sidecar).

    label_text is a formatted positive line, '' for a confirmed absent target
    (explicit empty label), or None when the frame must be excluded from
    training/evaluation positives (ambiguous / undecidable / GT unobservable).
    """
    _image_size(annotation)
    target, sidecar, _exclusion = yolo_pose_target(
        annotation, model_width, model_height)
    annotation_target = annotation.get('target') or {}
    geometry = annotation.get('geometry') or {}
    present = annotation_target.get('present')
    undecidable = annotation_target.get('undecidable') is True
    ambiguous = annotation_target.get('ambiguous') is True
    gt_unobservable, gt_unobservable_reason = _annotation_gt_unobservable(annotation)

    sidecar.update({
        'schema_version': LABELS_SCHEMA,
        'truncated_edges': truncated_edges(annotation),
        'truncated_edges_flags': _truncated_edges_flags(annotation),
        'truncation_source': (annotation_target.get('truncation_source')
                              if isinstance(annotation_target.get('truncation_source'), dict)
                              else None),
        'truncation_conflicts': annotation_target.get('truncation_conflicts'),
        'confuser_verified': _confuser_verified(annotation),
        'confusers': _confuser_entries(annotation),
        'green_pixels': _green_pixels(annotation),
        'gt_unobservable': gt_unobservable,
        'gt_unobservable_reason': gt_unobservable_reason,
        'reference_usable': False,
        'reference_downgraded': None,
        'included_in_anchor_denominator': False,
        'label_kind': 'EXCLUDED',
        'label_normalization': 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE',
        'source_target_coordinate_space': (target.get('coordinate_space')
                                           if isinstance(target, dict) else None),
        'label_space_note': 'bbox/keypoint are normalized by the SOURCE image '
                            'size; the letterbox is applied by the training '
                            'loader, not by the label',
    })
    if target is None:
        sidecar['letterbox'] = None
        sidecar['included_in_training'] = False
        if present is False and not undecidable and not ambiguous:
            sidecar['label_kind'] = 'EMPTY_NEGATIVE'
            sidecar['included_in_training'] = True
            sidecar['exclusion_reason'] = None
            return '', sidecar
        if present is True and geometry.get('bbox_xywh') is None:
            sidecar['exclusion_reason'] = 'GT_UNOBSERVABLE'
        else:
            sidecar['exclusion_reason'] = sidecar.get('exclusion_reason') or (
                'UNDECIDABLE' if undecidable else 'AMBIGUOUS'
                if ambiguous else 'EXCLUDED')
        return None, sidecar

    sidecar['letterbox'] = target.get('letterbox')
    visibility = int(target['keypoint_visibility'])
    green_pixels = sidecar['green_pixels']
    if (visibility == 1 and green_pixels is not None
            and green_pixels < int(green_pixels_threshold)):
        # spec v2.1 P2: the reference point is not usable; keep the box and use
        # the bbox centre placeholder with v=0 (never a reference estimate).
        bbox_norm = [float(v) for v in target['bbox_norm']]
        target = dict(target)
        target['keypoint_norm'] = [round(bbox_norm[0], 6), round(bbox_norm[1], 6)]
        target['keypoint_visibility'] = 0
        visibility = 0
        sidecar['reference_downgraded'] = 'REFERENCE_TOO_SMALL'
    sidecar['reference_usable'] = visibility == 1
    sidecar['included_in_anchor_denominator'] = visibility == 1
    sidecar['label_kind'] = ('POSITIVE_KEYPOINT' if visibility == 1
                             else 'POSITIVE_NO_REFERENCE')
    sidecar['included_in_training'] = True
    sidecar['exclusion_reason'] = None
    target = source_normalized_target(target, annotation, model_width,
                                      model_height)
    return format_yolo_pose_line(target), sidecar


def convert_annotation_document(document, *, root=None,
                                model_width=DEFAULT_MODEL_SIZE,
                                model_height=DEFAULT_MODEL_SIZE,
                                green_pixels_threshold=DEFAULT_THRESHOLDS['tau_green_pixels'],
                                split=None, validate=None):
    """Convert a v2/v2.1 annotation document into YOLO labels plus a manifest.

    Confirmed-absent frames become explicit empty labels (never silently
    dropped); ambiguous / undecidable / GT-unobservable frames are excluded from
    the positive set but keep a sidecar.  Frames outside split are skipped,
    though counts['frames'] always reports the document size.
    """
    if not isinstance(document, dict):
        raise LabelConversionError('annotation document must be a dict')
    schema = document.get('schema_version')
    if schema not in SUPPORTED_ANNOTATION_SCHEMAS:
        raise LabelConversionError('unsupported annotation schema_version: %r'
                                   % (schema,))
    annotations = document.get('annotations')
    if not isinstance(annotations, list):
        raise LabelConversionError('annotation document has no annotations list')
    should_validate = bool(root is not None) if validate is None else bool(validate)
    if should_validate:
        if root is None:
            raise LabelConversionError('validation requires a root directory')
        errors, _warnings = validate_document(document, Path(root))
        if errors:
            raise LabelConversionError('annotation document failed validation: '
                                       + '; '.join(errors[:5]))

    labels = {}
    negatives = []
    absent_frames = []
    excluded = []
    sidecars = []
    counts = Counter({
        'frames': len(annotations),
        'positive_labels': 0,
        'negative_empty_labels': 0,
        'excluded': 0,
        'reference_available': 0,
        'reference_unavailable': 0,
        'gt_unobservable': 0,
        'truncated': 0,
        'occluded': 0,
        'undecidable': 0,
        'ambiguous': 0,
    })
    families = Counter()
    for annotation in annotations:
        source = annotation.get('source') or {}
        if split is not None and source.get('split') != split:
            continue
        frame_id = annotation.get('frame_id')
        if frame_id in labels or any(item['frame_id'] == frame_id for item in excluded):
            raise LabelConversionError('duplicate frame_id: %r' % (frame_id,))
        text, sidecar = yolo_pose_label(
            annotation, model_width=model_width, model_height=model_height,
            green_pixels_threshold=green_pixels_threshold)
        sidecars.append(sidecar)
        families[str(source.get('family') or 'UNSPECIFIED')] += 1
        target = annotation.get('target') or {}
        if text is None:
            counts['excluded'] += 1
            excluded.append({'frame_id': frame_id,
                             'exclusion_reason': sidecar['exclusion_reason'],
                             'gt_unobservable': sidecar['gt_unobservable']})
        elif text == '':
            counts['negative_empty_labels'] += 1
            labels[frame_id] = ''
            negatives.append(frame_id)
            absent_frames.append(frame_id)
        else:
            counts['positive_labels'] += 1
            labels[frame_id] = text
            if target.get('truncated') is True:
                counts['truncated'] += 1
            if target.get('occluded') is True:
                counts['occluded'] += 1
        present = target.get('present') is True
        undecidable = target.get('undecidable') is True
        ambiguous = target.get('ambiguous') is True
        if present and not undecidable and not ambiguous:
            if sidecar['reference_usable']:
                counts['reference_available'] += 1
            else:
                counts['reference_unavailable'] += 1
        if sidecar['gt_unobservable']:
            counts['gt_unobservable'] += 1
        if undecidable:
            counts['undecidable'] += 1
        if ambiguous:
            counts['ambiguous'] += 1
    return {
        'schema_version': LABELS_SCHEMA,
        'model': {'width': int(model_width), 'height': int(model_height),
                  'letterbox': 'center-padded, per-frame scale/pad in the sidecar'},
        'labels': labels,
        'negatives': negatives,
        'absent_frames': absent_frames,
        'excluded': excluded,
        'sidecars': sidecars,
        'counts': dict(counts),
        'counts_by_family': dict(sorted(families.items())),
        'annotation_schema_version': schema,
    }


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_yolo_dataset(result, labels_dir):
    """Write YOLO txt labels (empty for confirmed absent); return a manifest dict."""
    labels_dir = Path(labels_dir)
    labels_dir.mkdir(parents=True, exist_ok=True)
    labels = result.get('labels') or {}
    stems = {}
    for frame_id in labels:
        stem = Path(frame_id).stem
        if stem in stems:
            raise LabelConversionError('duplicate label stem %r for %r and %r'
                                       % (stem, stems[stem], frame_id))
        stems[stem] = frame_id
    label_sha = {}
    for frame_id, text in labels.items():
        path = labels_dir / (Path(frame_id).stem + '.txt')
        path.write_text(text + ('\n' if text else ''), encoding='utf-8')
        label_sha[frame_id] = _sha256(path)
    manifest = {
        'schema_version': DATASET_SCHEMA,
        'labels_dir': str(labels_dir),
        'label_count': len(label_sha),
        'label_sha256': label_sha,
        'negatives': sorted(result.get('negatives') or []),
        'excluded': sorted(item['frame_id'] for item in result.get('excluded') or []),
        'model': result.get('model'),
        'label_normalization': 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE',
        'counts': result.get('counts'),
    }
    (labels_dir.parent / 'labels_manifest.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    return manifest


def write_sidecar(result, path):
    """Write one JSON line per converted frame; return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        for sidecar in result.get('sidecars') or []:
            stream.write(json.dumps(sidecar, ensure_ascii=False) + '\n')
    return path


# --- decoding ---------------------------------------------------------------

def merge_thresholds(overrides=None):
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides:
        unknown = [key for key in overrides if key not in DEFAULT_THRESHOLDS]
        if unknown:
            raise DecodeError('unknown threshold keys: ' + ', '.join(sorted(unknown)))
        thresholds.update(overrides)
    return thresholds


def image_bearing_deg(x_px, *, fx_px, cx_px):
    """Image bearing in degrees; an image angle, not a world bearing/distance."""
    return math.degrees(math.atan2(float(x_px) - float(cx_px), float(fx_px)))


def _validate_intrinsics(intrinsics):
    if intrinsics is None:
        return None
    if not isinstance(intrinsics, dict):
        raise LandmarkYoloError('intrinsics must be a dict or None')
    for key in ('fx_px', 'cx_px'):
        if key not in intrinsics:
            raise LandmarkYoloError('intrinsics missing ' + key)
    fx = float(intrinsics['fx_px'])
    if fx <= 0:
        raise LandmarkYoloError('intrinsics fx_px must be positive')
    return {'fx_px': fx, 'cx_px': float(intrinsics['cx_px']),
            'cy_px': (float(intrinsics['cy_px'])
                      if intrinsics.get('cy_px') is not None else None)}


def _empty_observation(frame_id=None, image=None, thresholds=None,
                       letterbox=None):
    return {
        'schema_version': OBSERVATION_SCHEMA,
        'frame_id': frame_id,
        'image': image,
        'status': 'UNKNOWN',
        'landmark_class': None,
        'landmark_id': None,
        'identity_claimed': False,
        'bbox_xywh': None,
        'bbox_extent_clipped': False,
        'score': None,
        'keypoint_px': None,
        'keypoint_confidence': None,
        'reference_status': 'UNAVAILABLE',
        'image_bearing_deg': None,
        'visibility': 'UNKNOWN',
        'truncated': False,
        'truncated_edges': [],
        'candidate_count': 0,
        'candidates': [],
        'reject_reason': None,
        'reject_reasons': [],
        'appearance_check': 'NOT_EVALUATED',
        'valid': False,
        'thresholds': dict(thresholds or DEFAULT_THRESHOLDS),
        'letterbox': (letterbox.as_dict()
                      if isinstance(letterbox, Letterbox) else None),
        'uniqueness_assumption': 'U1_U2_U3_PROPOSED_NOT_VERIFIED',
    }


def unknown_observation(frame_id=None, reason='DETECTOR_ERROR', image=None,
                        thresholds=None, letterbox=None):
    """A model-side UNKNOWN record (detector failure), never a negative."""
    record = _empty_observation(frame_id, image, thresholds, letterbox)
    record['status'] = 'UNKNOWN'
    record['reject_reason'] = reason
    record['reject_reasons'] = [reason]
    record['valid'] = False
    return record


def _clip_bbox(bbox_xywh, image_width, image_height):
    x, y, w, h = [float(v) for v in bbox_xywh]
    x1 = max(0.0, min(float(image_width), x))
    y1 = max(0.0, min(float(image_height), y))
    x2 = max(0.0, min(float(image_width), x + w))
    y2 = max(0.0, min(float(image_height), y + h))
    if x2 < x1:
        x2 = x1
    if y2 < y1:
        y2 = y1
    return [x1, y1, x2 - x1, y2 - y1]


def _bbox_truncated_edges(bbox_xywh, image_width, image_height):
    x, y, w, h = [float(v) for v in bbox_xywh]
    epsilon = 1e-6
    edges = []
    if x <= epsilon:
        edges.append('left')
    if y <= epsilon:
        edges.append('top')
    if x + w >= image_width - epsilon:
        edges.append('right')
    if y + h >= image_height - epsilon:
        edges.append('bottom')
    return sorted(edges)


def decode_candidates(candidates, *, image_width, image_height, intrinsics,
                      thresholds=None, frame_id=None, image=None,
                      landmark_id=DEFAULT_LANDMARK_ID,
                      appearance_prior=None):
    """Decode source-pixel candidates into one landmark observation record.

    candidates are dicts with bbox_xywh (source pixels), score, class_id
    (default 0 = tower), optional keypoint_px, keypoint_confidence and optional
    green_pixels (from an explicit green-cue probe; None means the appearance
    check is not evaluated).
    """
    thresholds = merge_thresholds(thresholds)
    record = _empty_observation(frame_id, image, thresholds)
    if (image_width is None or image_height is None
            or float(image_width) <= 0 or float(image_height) <= 0):
        record['status'] = 'REJECTED'
        record['reject_reason'] = 'INVALID_IMAGE'
        record['reject_reasons'] = ['INVALID_IMAGE']
        record['valid'] = False
        return record
    intrinsics = _validate_intrinsics(intrinsics)
    if intrinsics is None:
        record['status'] = 'REJECTED'
        record['reject_reason'] = 'MISSING_CALIBRATION'
        record['reject_reasons'] = ['MISSING_CALIBRATION']
        record['valid'] = False
        return record
    width = float(image_width)
    height = float(image_height)

    usable = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            raise DecodeError('candidate must be a dict')
        if candidate.get('bbox_xywh') is None:
            raise DecodeError('candidate missing bbox_xywh')
        if int(candidate.get('class_id', TOWER_CLASS_ID)) != TOWER_CLASS_ID:
            continue
        score = float(candidate.get('score', 0.0))
        if score < thresholds['tau_det']:
            continue
        usable.append(dict(candidate, score=score))
    usable.sort(key=lambda item: item['score'], reverse=True)
    record['candidate_count'] = len(usable)
    record['candidates'] = [
        {'bbox_xywh': [float(v) for v in item['bbox_xywh']],
         'score': item['score'],
         'keypoint_px': (None if item.get('keypoint_px') is None
                         else [float(v) for v in item['keypoint_px']]),
         'keypoint_confidence': item.get('keypoint_confidence'),
         'green_pixels': item.get('green_pixels')}
        for item in usable[:5]
    ]
    if not usable:
        record['status'] = 'NOT_DETECTED'
        record['valid'] = True
        return record

    top = usable[0]
    raw_bbox = [float(v) for v in top['bbox_xywh']]
    truncated_by = _bbox_truncated_edges(raw_bbox, width, height)
    clipped = _clip_bbox(raw_bbox, width, height)
    record['bbox_xywh'] = clipped
    record['bbox_extent_clipped'] = any(
        abs(a - b) > 1e-9 for a, b in zip(clipped, raw_bbox))
    record['score'] = top['score']
    record['status'] = 'DETECTED'
    record['landmark_class'] = TOWER_CLASS_NAME
    record['truncated_edges'] = truncated_by
    record['truncated'] = bool(truncated_by)
    record['visibility'] = 'PARTIAL' if truncated_by else 'FULL'

    reject_reasons = []
    identity_allowed = True
    appearance_check = 'NOT_EVALUATED'
    if len(usable) >= 2:
        margin = usable[0]['score'] - usable[1]['score']
        if margin < thresholds['tau_margin']:
            reject_reasons.append('MULTIPLE_CANDIDATES')
            identity_allowed = False
    green_pixels = top.get('green_pixels')
    if isinstance(green_pixels, (int, float)):
        if int(green_pixels) < int(thresholds['tau_green_pixels']):
            reject_reasons.append('TARGET_AMBIGUOUS')
            identity_allowed = False
            appearance_check = 'GREEN_LIGHT_BELOW_MINIMUM'
        else:
            appearance_check = 'GREEN_LIGHT_OK'
    if appearance_prior and identity_allowed:
        aspect = (clipped[2] / clipped[3]) if clipped[3] > 0 else 0.0
        minimum = float(appearance_prior.get('min_aspect_ratio', 0.0))
        maximum = float(appearance_prior.get('max_aspect_ratio', float('inf')))
        if not (minimum <= aspect <= maximum):
            reject_reasons.append('TARGET_AMBIGUOUS')
            identity_allowed = False
            appearance_check = 'ASPECT_RATIO_OUT_OF_PRIOR'
    if truncated_by:
        reject_reasons.append('TRUNCATED')
        minimum_side = float(thresholds['tau_trunc_min_side_px'])
        if clipped[2] < minimum_side or clipped[3] < minimum_side:
            identity_allowed = False

    keypoint = top.get('keypoint_px')
    keypoint_conf = top.get('keypoint_confidence')
    reference_visible = (keypoint is not None
                         and (keypoint_conf is None
                              or float(keypoint_conf) >= thresholds['tau_kpt']))
    if not reference_visible:
        reject_reasons.append('REFERENCE_UNAVAILABLE')
        record['reference_status'] = 'UNAVAILABLE'
        record['keypoint_px'] = None
        record['keypoint_confidence'] = (None if keypoint_conf is None
                                         else float(keypoint_conf))
    else:
        kx = max(0.0, min(width, float(keypoint[0])))
        ky = max(0.0, min(height, float(keypoint[1])))
        record['reference_status'] = 'VISIBLE'
        record['keypoint_px'] = [kx, ky]
        record['keypoint_confidence'] = (None if keypoint_conf is None
                                         else float(keypoint_conf))
        record['image_bearing_deg'] = image_bearing_deg(
            kx, fx_px=intrinsics['fx_px'], cx_px=intrinsics['cx_px'])

    record['reject_reasons'] = list(reject_reasons)
    record['reject_reason'] = next(
        (reason for reason in REJECT_PRECEDENCE if reason in reject_reasons),
        None)
    record['appearance_check'] = appearance_check
    record['identity_claimed'] = bool(identity_allowed)
    record['landmark_id'] = landmark_id if identity_allowed else None
    record['valid'] = record['reject_reason'] not in INVALID_OBSERVATION_REASONS
    return record


def _get(container, name):
    if container is None:
        return None
    if isinstance(container, dict):
        return container.get(name)
    return getattr(container, name, None)


def _as_list(value):
    if value is None:
        return []
    if hasattr(value, 'tolist'):
        value = value.tolist()
    return list(value)


def _unletterbox_bbox(bbox_xywh, letterbox, coordinates):
    if coordinates == 'model':
        if letterbox is None:
            raise DecodeError("coordinates='model' requires letterbox parameters")
        return bbox_from_model(bbox_xywh, letterbox)
    if coordinates != 'source':
        raise DecodeError("coordinates must be 'source' or 'model'")
    return [float(v) for v in bbox_xywh]


def _unletterbox_point(point, letterbox, coordinates):
    if point is None:
        return None
    if coordinates == 'model':
        if letterbox is None:
            raise DecodeError("coordinates='model' requires letterbox parameters")
        return list(point_from_model(point, letterbox))
    return [float(v) for v in point]


def decode_ultralytics_result(result, *, image_width, image_height,
                              letterbox=None, coordinates='source',
                              intrinsics, thresholds=None, frame_id=None,
                              image=None, landmark_id=DEFAULT_LANDMARK_ID,
                              appearance_prior=None):
    """Adapt an ultralytics Results-like object into candidates and decode.

    By default ultralytics returns boxes/keypoints already mapped back to the
    source image, so coordinates='source'.  Use coordinates='model' with the
    letterbox parameters when the values are still in 640-input space.
    """
    boxes = _get(result, 'boxes')
    keypoints = _get(result, 'keypoints')
    xyxy = _as_list(_get(boxes, 'xyxy')) if boxes is not None else []
    conf = _as_list(_get(boxes, 'conf')) if boxes is not None else []
    classes = _as_list(_get(boxes, 'cls')) if boxes is not None else []
    kpt_xy = _as_list(_get(keypoints, 'xy')) if keypoints is not None else []
    kpt_conf = _as_list(_get(keypoints, 'conf')) if keypoints is not None else []
    candidates = []
    for index, box in enumerate(xyxy):
        bbox = _bbox_xyxy_to_xywh(box)
        bbox = _unletterbox_bbox(bbox, letterbox, coordinates)
        score = float(conf[index]) if index < len(conf) else 0.0
        class_id = int(classes[index]) if index < len(classes) else TOWER_CLASS_ID
        keypoint = None
        keypoint_confidence = None
        if index < len(kpt_xy):
            points = _as_list(kpt_xy[index])
            if points:
                keypoint = _unletterbox_point(points[0], letterbox, coordinates)
                if index < len(kpt_conf):
                    confidences = _as_list(kpt_conf[index])
                    if confidences:
                        keypoint_confidence = float(confidences[0])
        candidates.append({'bbox_xywh': bbox, 'score': score,
                           'class_id': class_id, 'keypoint_px': keypoint,
                           'keypoint_confidence': keypoint_confidence,
                           'green_pixels': None})
    return decode_candidates(candidates, image_width=image_width,
                             image_height=image_height, intrinsics=intrinsics,
                             thresholds=thresholds, frame_id=frame_id,
                             image=image, landmark_id=landmark_id,
                             appearance_prior=appearance_prior)


def decode_onnx_pose_output(output, *, image_width, image_height, letterbox,
                            num_classes=1, keypoint_count=1, intrinsics,
                            thresholds=None, frame_id=None, image=None,
                            landmark_id=DEFAULT_LANDMARK_ID,
                            appearance_prior=None):
    """Decode a YOLOv8-pose ONNX output tensor into an observation record.

    Expected layout: (batch, 4 + num_classes + 3*keypoint_count, anchors) in
    model-input pixels (cx, cy, w, h, class scores..., keypoint x/y/conf...).
    Both (N, C) and (C, N) are accepted.
    """
    if letterbox is None:
        raise DecodeError('ONNX decoding requires letterbox parameters')
    channels = 4 + int(num_classes) + 3 * int(keypoint_count)
    batch = _as_list(output)
    while batch and isinstance(batch[0], list) and len(batch) == 1:
        batch = batch[0]
    if not isinstance(batch, list) or not batch:
        return decode_candidates([], image_width=image_width,
                                 image_height=image_height,
                                 intrinsics=intrinsics,
                                 thresholds=thresholds, frame_id=frame_id,
                                 image=image, landmark_id=landmark_id)
    rows_source = batch
    first = _as_list(rows_source[0])
    if len(first) == channels:
        rows = [[float(value) for value in _as_list(row)] for row in rows_source]
    elif len(rows_source) == channels:
        columns = [[float(value) for value in _as_list(column)]
                   for column in rows_source]
        rows = [list(row) for row in zip(*columns)]
    else:
        raise DecodeError('ONNX output shape is not (N, %d) or (%d, N)'
                          % (channels, channels))
    candidates = []
    for row in rows:
        cx, cy, bw, bh = row[0], row[1], row[2], row[3]
        scores = row[4:4 + int(num_classes)]
        class_offset = max(range(len(scores)), key=lambda i: scores[i])
        score = float(scores[class_offset])
        bbox_model = [cx - bw / 2.0, cy - bh / 2.0, bw, bh]
        bbox = bbox_from_model(bbox_model, letterbox)
        keypoint = None
        keypoint_confidence = None
        tail = row[4 + int(num_classes):]
        if len(tail) >= 3:
            keypoint = list(point_from_model((tail[0], tail[1]), letterbox))
            keypoint_confidence = float(tail[2])
        candidates.append({'bbox_xywh': bbox, 'score': score,
                           'class_id': class_offset,
                           'keypoint_px': keypoint,
                           'keypoint_confidence': keypoint_confidence,
                           'green_pixels': None})
    return decode_candidates(candidates, image_width=image_width,
                             image_height=image_height, intrinsics=intrinsics,
                             thresholds=thresholds, frame_id=frame_id,
                             image=image, landmark_id=landmark_id,
                             appearance_prior=appearance_prior)


def observation_to_metric_prediction(observation):
    """Map an observation record to the metric module prediction contract."""
    return {
        'status': observation.get('status'),
        'landmark_id': observation.get('landmark_id'),
        'bbox_xywh': observation.get('bbox_xywh'),
        'score': observation.get('score'),
        'keypoint_px': observation.get('keypoint_px'),
        'reject_reason': observation.get('reject_reason'),
    }


# --- evaluation-side ground truth -------------------------------------------

def scale_bucket(bbox_xywh, buckets=DEFAULT_SCALE_BUCKETS):
    """Bucket a source-pixel bbox by area; None bbox -> NO_BBOX."""
    if bbox_xywh is None:
        return 'NO_BBOX'
    try:
        area = abs(float(bbox_xywh[2])) * abs(float(bbox_xywh[3]))
    except (TypeError, ValueError, IndexError):
        return 'NO_BBOX'
    for name, limit in buckets:
        if area < limit:
            return name
    return buckets[-1][0]


def ground_truth_from_annotation(annotation):
    """Extract (gt, reference_px, strata) for the metric module."""
    target = annotation.get('target') or {}
    geometry = annotation.get('geometry') or {}
    source = annotation.get('source') or {}
    present = target.get('present') is True
    undecidable = target.get('undecidable') is True
    ambiguous = target.get('ambiguous') is True
    bbox = geometry.get('bbox_xywh')
    keypoint = geometry.get('keypoint')
    reference_status = geometry.get('reference_status')
    reference = None
    reference_px = None
    if present:
        visible = (keypoint is not None and keypoint.get('visible') is True
                   and reference_status == 'MANUAL_APPROX')
        reference = 'VISIBLE' if visible else 'UNAVAILABLE'
        if visible:
            reference_px = [float(keypoint['x']), float(keypoint['y'])]
    gt = {
        'frame_id': annotation.get('frame_id'),
        'present': present,
        'landmark_id': target.get('landmark_id'),
        'bbox_xywh': ([float(v) for v in bbox] if bbox is not None else None),
        'reference': reference,
        'visibility': target.get('visibility'),
        'truncated': target.get('truncated') is True,
        'occluded': target.get('occluded') is True,
        'ambiguous': ambiguous,
        'undecidable': undecidable,
        'negative_type': annotation.get('negative_type'),
    }
    strata = {
        'family': str(source.get('family') or 'UNSPECIFIED'),
        'group_id': str(source.get('group_id') or 'UNSPECIFIED'),
        'visibility': str(target.get('visibility') or 'UNKNOWN'),
        'scale': scale_bucket(gt['bbox_xywh']),
        'truncation': 'TRUNCATED' if gt['truncated'] else 'NOT_TRUNCATED',
        'negative_type': str(gt['negative_type'] or 'NONE'),
    }
    return gt, reference_px, strata


def pixel_basis_from_annotation(annotation):
    """Return the recorded intrinsics as decoder input, or None."""
    basis = annotation.get('pixel_basis')
    if not isinstance(basis, dict):
        return None
    if basis.get('fx_px') is None or basis.get('cx_px') is None:
        return None
    return {'fx_px': float(basis['fx_px']), 'cx_px': float(basis['cx_px']),
            'cy_px': (float(basis['cy_px'])
                      if basis.get('cy_px') is not None else None)}


# --- small CLI: annotation -> YOLO dataset ----------------------------------

def _cli_export(args):
    document = json.loads(Path(args.annotations).read_text(encoding='utf-8'))
    result = convert_annotation_document(
        document, root=Path(args.root), model_width=args.model_size,
        model_height=args.model_size, split=args.split)
    output_dir = Path(args.output_dir)
    label_dir = output_dir / 'labels'
    manifest = write_yolo_dataset(result, label_dir)
    write_sidecar(result, output_dir / 'sidecar.jsonl')
    summary = {
        'schema_version': 'dsh.landmark_yolo_export.v1',
        'annotations': str(args.annotations),
        'annotations_sha256': _sha256(args.annotations),
        'output_dir': str(output_dir),
        'counts': result['counts'],
        'counts_by_family': result['counts_by_family'],
        'label_count': manifest['label_count'],
        'label_normalization': 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE',
        'status': 'PASS' if result['counts']['frames'] > 0 else 'EMPTY',
        'limits': 'label export only; no model, no training, no board '
                  'deployment; an empty label means confirmed absence and the '
                  'separate excluded manifest keeps ambiguous/undecidable '
                  'frames out of training positives',
    }
    (output_dir / 'export_manifest.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description='YOLO pose label export for the landmark experiment '
                    '(no model inference).')
    subparsers = parser.add_subparsers(dest='command', required=True)
    export = subparsers.add_parser('export',
                                   help='annotation document -> YOLO labels')
    export.add_argument('--annotations', required=True)
    export.add_argument('--root', required=True,
                        help='root directory for annotation validation')
    export.add_argument('--output-dir', required=True)
    export.add_argument('--model-size', type=int, default=DEFAULT_MODEL_SIZE)
    export.add_argument('--split', default=None)
    args = parser.parse_args(argv)
    if args.command == 'export':
        return _cli_export(args)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())