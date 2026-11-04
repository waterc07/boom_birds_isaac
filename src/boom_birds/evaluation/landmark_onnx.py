"""ONNX pose-path parity helpers for the bounded landmark experiment.

Why this module exists
----------------------
The earlier evaluation tooling had a raw-onnxruntime decoding path
(run_onnx_backend in scripts/evaluate_landmark_yolo.py) that was never compared
end-to-end with the ultralytics .pt path.  Two defects were identified on
2026-11-04 and are regression-tested in
tests/evaluation/test_landmark_onnx.py:

D1  the raw-ORT path fed all 8400 anchors to decode_candidates without NMS;
    one object therefore produced several overlapping candidates above the
    detection threshold and the frame was rejected with MULTIPLE_CANDIDATES
    (identity not claimed).  In the recorded eval_onnx run that flipped 51/95
    validation joint decisions.  This module always applies the same NMS as
    ultralytics before decoding.
D2  the ultralytics .pt predictor and the exported-ONNX predictor build
    DIFFERENT letterboxes: BasePredictor.pre_transform uses
    LetterBox(..., auto=same_shapes and model.pt) so a .pt model gets the
    rect/auto mode (a 320x240 image becomes a 640x480 canvas) while an ONNX
    model gets the square mode (640x640).  The old "4.67 px keypoint
    difference" is therefore a preprocessing-mode difference, not a graph
    difference.  This module builds ONE shared square canvas and feeds the same
    tensor/canvas to every path.

The helpers here are numpy/cv2 only (no torch / ultralytics / onnxruntime
imports at module import time) so the unit tests run in the Isaac venv; the
actual model run happens in .venv/landmark-train through
scripts/landmark_onnx_parity.py.

Coordinate contract
-------------------
* source domain: original camera image pixels (x right, y down).
* model domain: the shared square letterbox canvas, coordinates in canvas px.
* LetterboxSpec.point_from_model / bbox_from_model map model -> source.
  The canvas is built with int(round(...)) resize sizes and
  round(pad -/+ 0.1) borders exactly like ultralytics 8.2.0
  LetterBox.__call__.  For source sizes whose scaled size is integral the
  mapping is exact; otherwise rounding_error_px is recorded and the caller must
  not claim sub-pixel parity.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

PAD_VALUE = 114
MODEL_SIZE = 640
NUM_CLASSES = 1
KEYPOINT_COUNT = 1
CHANNELS = 4 + NUM_CLASSES + 3 * KEYPOINT_COUNT


class OnnxParityError(ValueError):
    """Raised when an ONNX parity input or geometry is invalid."""


# --- small io helpers -------------------------------------------------------

def repo_root() -> Path:
    """Repository root, derived from this file (no machine-private paths)."""
    return Path(__file__).resolve().parents[3]


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return path


# --- letterbox geometry -----------------------------------------------------

@dataclass(frozen=True)
class LetterboxSpec:
    """Center-padded letterbox mapping source pixels -> model canvas pixels."""

    source_width: int
    source_height: int
    model_width: int
    model_height: int
    auto: bool
    stride: int
    scale: float
    resized_width: int
    resized_height: int
    pad_left: int
    pad_top: int
    pad_right: int
    pad_bottom: int
    canvas_width: int
    canvas_height: int

    @property
    def rounding_error_px(self) -> float:
        """Largest deviation between the exact ratio and the integer resize."""
        return max(abs(self.resized_width - self.source_width * self.scale),
                   abs(self.resized_height - self.source_height * self.scale))

    def as_dict(self):
        payload = asdict(self)
        payload['rounding_error_px'] = self.rounding_error_px
        return payload

    def _check_point(self, point):
        if point is None:
            raise OnnxParityError('point is None')
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            raise OnnxParityError('point must be (x, y)')
        return x, y

    def point_to_model(self, point):
        x, y = self._check_point(point)
        return (x * self.scale + self.pad_left, y * self.scale + self.pad_top)

    def point_from_model(self, point):
        x, y = self._check_point(point)
        return ((x - self.pad_left) / self.scale,
                (y - self.pad_top) / self.scale)

    def bbox_to_model(self, bbox_xywh):
        x, y, w, h = [float(v) for v in bbox_xywh]
        return [x * self.scale + self.pad_left,
                y * self.scale + self.pad_top,
                w * self.scale, h * self.scale]

    def bbox_from_model(self, bbox_xywh):
        x, y, w, h = [float(v) for v in bbox_xywh]
        return [(x - self.pad_left) / self.scale,
                (y - self.pad_top) / self.scale,
                w / self.scale, h / self.scale]

    def as_evaltool_letterbox(self):
        """Adapt to boom_birds.evaluation.landmark_yolo.Letterbox."""
        from boom_birds.evaluation import landmark_yolo as yolo
        return yolo.Letterbox(self.source_width, self.source_height,
                              self.canvas_width, self.canvas_height,
                              self.scale, self.pad_left, self.pad_top)


def letterbox_spec(source_width, source_height, model_width=MODEL_SIZE,
                   model_height=MODEL_SIZE, *, auto=False, stride=32,
                   require_square=False):
    """Replicate ultralytics 8.2.0 LetterBox geometry (center padding).

    auto=True reproduces the predictor rect mode used for .pt models; the
    exported ONNX graph uses auto=False (square).  require_square=True rejects a
    non-square canvas (use it to prove a path had identical preprocessing).
    """
    source_width = int(source_width)
    source_height = int(source_height)
    model_width = int(model_width)
    model_height = int(model_height)
    stride = int(stride)
    if min(source_width, source_height, model_width, model_height) <= 0:
        raise OnnxParityError('letterbox sizes must be positive')
    if stride <= 0:
        raise OnnxParityError('stride must be positive')
    scale = min(model_width / float(source_width),
                model_height / float(source_height))
    resized_width = int(round(source_width * scale))
    resized_height = int(round(source_height * scale))
    pad_width = model_width - resized_width
    pad_height = model_height - resized_height
    if auto:
        pad_width = pad_width % stride
        pad_height = pad_height % stride
        pad_left = 0
        pad_top = 0
        pad_right = int(pad_width)
        pad_bottom = int(pad_height)
    else:
        pad_width /= 2.0
        pad_height /= 2.0
        pad_left = int(round(pad_width - 0.1))
        pad_right = int(round(pad_width + 0.1))
        pad_top = int(round(pad_height - 0.1))
        pad_bottom = int(round(pad_height + 0.1))
    canvas_width = resized_width + pad_left + pad_right
    canvas_height = resized_height + pad_top + pad_bottom
    if require_square and canvas_width != canvas_height:
        raise OnnxParityError(
            'non-square canvas %dx%d (auto=%s); the parity paths require one '
            'shared square canvas' % (canvas_width, canvas_height, auto))
    return LetterboxSpec(source_width, source_height, model_width, model_height,
                         bool(auto), stride, scale, resized_width,
                         resized_height, pad_left, pad_top, pad_right,
                         pad_bottom, canvas_width, canvas_height)


def letterbox_image(image, spec, pad_value=PAD_VALUE):
    """Build the padded canvas for a BGR uint8 HWC image."""
    if not isinstance(spec, LetterboxSpec):
        raise OnnxParityError('spec must be a LetterboxSpec')
    import cv2
    if image is None:
        raise OnnxParityError('image is None')
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 3:
        raise OnnxParityError('image must be HWC BGR with 3 channels')
    if (array.shape[1], array.shape[0]) != (spec.source_width, spec.source_height):
        raise OnnxParityError(
            'image size %dx%d does not match spec %dx%d'
            % (array.shape[1], array.shape[0], spec.source_width,
               spec.source_height))
    if (array.shape[1], array.shape[0]) != (spec.resized_width,
                                            spec.resized_height):
        array = cv2.resize(array, (spec.resized_width, spec.resized_height),
                           interpolation=cv2.INTER_LINEAR)
    return cv2.copyMakeBorder(
        array, spec.pad_top, spec.pad_bottom, spec.pad_left, spec.pad_right,
        cv2.BORDER_CONSTANT, value=(int(pad_value), int(pad_value),
                                    int(pad_value)))


def preprocess(image, imgsz=MODEL_SIZE, *, auto=False):
    """Read/letterbox an image and return (tensor, spec, canvas).

    tensor is float32 RGB CHW [1, 3, H, W] in 0..1, exactly what the ultralytics
    predictor and the ONNX session consume.  image may be a path or a BGR uint8
    array.
    """
    import cv2
    if isinstance(image, (str, Path)):
        array = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if array is None:
            raise OnnxParityError('cannot read image %s' % (image,))
    else:
        array = np.asarray(image)
    spec = letterbox_spec(array.shape[1], array.shape[0], imgsz, imgsz,
                          auto=auto)
    canvas = letterbox_image(array, spec)
    rgb = canvas[..., ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    tensor = np.ascontiguousarray(rgb[None])
    return tensor, spec, canvas


# --- NMS (same semantics as ultralytics 8.2.0 non_max_suppression) ----------

def _iou_xyxy_one(box, boxes):
    if len(boxes) == 0:
        return np.zeros((0,), dtype=np.float32)
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_a = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    area_b = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(
        0.0, boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(area_a + area_b - inter, 1e-9)


def nms_rows(rows, conf_thres, iou_thres, max_det=300, num_classes=NUM_CLASSES,
             keypoint_count=KEYPOINT_COUNT):
    """Greedy NMS over raw pose rows (cx, cy, w, h, scores..., kpts...).

    Matches ultralytics: strict score > conf_thres, best-class only, class
    offset for NMS (single class here), score-descending greedy suppression with
    IoU > iou_thres removed, then max_det.  Returns the kept rows in NMS order;
    keypoint columns stay in model-canvas pixels.
    """
    array = np.asarray(rows, dtype=np.float32)
    channels = 4 + int(num_classes) + 3 * int(keypoint_count)
    if array.ndim != 2 or array.shape[1] != channels:
        raise OnnxParityError(
            'raw rows must be (N, %d); got %r' % (channels, array.shape))
    if not (0.0 <= float(conf_thres) <= 1.0):
        raise OnnxParityError('conf_thres must be within [0, 1]')
    if not (0.0 <= float(iou_thres) <= 1.0):
        raise OnnxParityError('iou_thres must be within [0, 1]')
    if int(max_det) <= 0:
        raise OnnxParityError('max_det must be positive')
    scores = array[:, 4:4 + int(num_classes)].max(axis=1)
    keep_mask = scores > float(conf_thres)
    if not keep_mask.any():
        return np.zeros((0, channels), dtype=np.float32)
    candidates = array[keep_mask]
    candidate_scores = scores[keep_mask]
    boxes_cxcywh = candidates[:, :4]
    boxes = np.empty_like(boxes_cxcywh)
    boxes[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2.0
    boxes[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2.0
    boxes[:, 2] = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2.0
    boxes[:, 3] = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2.0
    order = np.argsort(-candidate_scores, kind='stable')
    kept = []
    while order.size and len(kept) < int(max_det):
        current = int(order[0])
        kept.append(current)
        if order.size == 1:
            break
        ious = _iou_xyxy_one(boxes[current], boxes[order[1:]])
        order = order[1:][ious <= float(iou_thres)]
    return candidates[kept]


# --- decoding into the evaltool observation contract -----------------------

def clip_bbox_xywh(bbox_xywh, image_width, image_height):
    """Clip an xywh box to the image, like ultralytics scale_boxes does."""
    x, y, w, h = [float(value) for value in bbox_xywh]
    x1 = max(0.0, min(float(image_width), x))
    y1 = max(0.0, min(float(image_height), y))
    x2 = max(0.0, min(float(image_width), x + w))
    y2 = max(0.0, min(float(image_height), y + h))
    if x2 < x1:
        x2 = x1
    if y2 < y1:
        y2 = y1
    return [x1, y1, x2 - x1, y2 - y1]


def decode_pose_rows(rows, spec, *, image_width, image_height, intrinsics,
                     thresholds, frame_id=None, image=None,
                     landmark_id=None, appearance_prior=None,
                     clip_to_source=True, round_boxes=True,
                     num_classes=NUM_CLASSES,
                     keypoint_count=KEYPOINT_COUNT):
    """Decode NMS-kept model-space rows into the evaltool observation record.

    Boxes are mapped to source pixels and clipped to the image before the
    truncation-edge check, matching what ultralytics' post-processing does
    (scale_boxes + clip_boxes).  Without that clip a box that is 1e-4 px outside
    the image would not be reported as TRUNCATED and the raw-ORT path would
    disagree with the two ultralytics paths on edge frames.
    """
    from boom_birds.evaluation import landmark_yolo as yolo
    if not isinstance(spec, LetterboxSpec):
        raise OnnxParityError('spec must be a LetterboxSpec')
    array = np.asarray(rows, dtype=np.float32)
    channels = 4 + int(num_classes) + 3 * int(keypoint_count)
    if array.size:
        if array.ndim != 2 or array.shape[1] != channels:
            raise OnnxParityError(
                'rows must be (N, %d); got %r' % (channels, array.shape))
    else:
        array = np.zeros((0, channels), dtype=np.float32)
    candidates = []
    for row in array:
        cx, cy, bw, bh = [float(value) for value in row[:4]]
        scores = row[4:4 + int(num_classes)]
        class_offset = int(np.argmax(scores)) if len(scores) else 0
        score = float(scores[class_offset]) if len(scores) else 0.0
        x1 = cx - bw / 2.0
        y1 = cy - bh / 2.0
        x2 = cx + bw / 2.0
        y2 = cy + bh / 2.0
        if round_boxes:
            # ultralytics PosePredictor.postprocess does
            # pred[:, :4] = scale_boxes(...).round(): the pose predictor returns
            # INTEGER boxes in its source-image domain.  Our shared canvas is
            # the predictor source, so the same clip+round is applied in model
            # canvas pixels before the inverse letterbox.  Without it a box
            # 0.2 px inside the border would not be TRUNCATED here while the
            # ultralytics paths report it as TRUNCATED.
            x1 = float(np.clip(x1, 0.0, spec.model_width))
            y1 = float(np.clip(y1, 0.0, spec.model_height))
            x2 = float(np.clip(x2, 0.0, spec.model_width))
            y2 = float(np.clip(y2, 0.0, spec.model_height))
            x1, y1, x2, y2 = (float(np.round(x1)), float(np.round(y1)),
                              float(np.round(x2)), float(np.round(y2)))
        bbox = spec.bbox_from_model([x1, y1, x2 - x1, y2 - y1])
        if clip_to_source:
            bbox = clip_bbox_xywh(bbox, image_width, image_height)
        tail = row[4 + int(num_classes):]
        keypoint = None
        keypoint_confidence = None
        if len(tail) >= 3:
            keypoint = list(spec.point_from_model((tail[0], tail[1])))
            keypoint_confidence = float(tail[2])
        candidates.append({'bbox_xywh': bbox, 'score': score,
                           'class_id': class_offset,
                           'keypoint_px': keypoint,
                           'keypoint_confidence': keypoint_confidence,
                           'green_pixels': None})
    kwargs = dict(image_width=image_width, image_height=image_height,
                  intrinsics=intrinsics, thresholds=thresholds,
                  frame_id=frame_id, image=image,
                  appearance_prior=appearance_prior)
    if landmark_id is not None:
        kwargs['landmark_id'] = landmark_id
    return yolo.decode_candidates(candidates, **kwargs)


def channels_of_rows(rows):
    """Channel count of a pose row matrix; 0 for an empty array."""
    array = np.asarray(rows)
    return int(array.shape[1]) if array.ndim == 2 else 0


def candidate_from_observation(observation):
    """Compact candidate record for comparison (source pixel domain)."""
    if observation is None:
        return None
    return {
        'status': observation.get('status'),
        'score': observation.get('score'),
        'bbox_xywh': observation.get('bbox_xywh'),
        'keypoint_px': observation.get('keypoint_px'),
        'reference_status': observation.get('reference_status'),
        'identity_claimed': observation.get('identity_claimed'),
        'reject_reason': observation.get('reject_reason'),
        'candidate_count': observation.get('candidate_count'),
    }


# --- decision comparison ----------------------------------------------------

def observation_decision(observation):
    """Consumer-facing decision tuple of one observation record."""
    observation = observation or {}
    return {
        'status': observation.get('status'),
        'detected': observation.get('status') == 'DETECTED',
        'reference_available': (observation.get('reference_status') == 'VISIBLE'
                                and observation.get('keypoint_px') is not None),
        'identity_claimed': bool(observation.get('identity_claimed')),
        'reject_reason': observation.get('reject_reason'),
    }


def rejection_decision(observation):
    """Consumer-facing rejection decision: emitted reason and whether invalid."""
    observation = observation or {}
    status = observation.get('status')
    return {
        'status': status,
        'rejected': observation.get('reject_reason') is not None,
        'reason': observation.get('reject_reason'),
        'invalid': status in ('UNKNOWN', 'REJECTED'),
        'reference_unavailable': observation.get('reference_status') == 'UNAVAILABLE',
    }


def bearing_deg(observation):
    """Image-domain horizontal bearing recorded by the decoder, or None."""
    observation = observation or {}
    value = observation.get('image_bearing_deg')
    if value is None:
        return None
    return float(value)


def identity_decision(observation):
    """Identity decision without GT: claim flag and claimed landmark id."""
    observation = observation or {}
    return {
        'claimed': bool(observation.get('identity_claimed')),
        'landmark_id': observation.get('landmark_id'),
    }


def decision_diff(left, right, tau_bearing_deg=0.01):
    """Compare two observation decisions; flags are per decision layer.

    Extends the original presence/reference/identity/reject flags with explicit
    identity-claim, rejection-reason and image-bearing layers (T29): a path pair
    can agree on presence yet disagree on identity, on the rejection reason, or
    on the emitted bearing.  tau_bearing_deg is the bearing comparison tolerance
    (degrees); the default 0.01 deg is far below the consumer tolerance and is
    meant to detect any non-numerical disagreement.
    """
    a = observation_decision(left)
    b = observation_decision(right)
    status_flip = a['status'] != b['status']
    reference_flip = a['reference_available'] != b['reference_available']
    identity_flip = a['identity_claimed'] != b['identity_claimed']
    reject_flip = a['reject_reason'] != b['reject_reason']
    bearing_left = bearing_deg(left)
    bearing_right = bearing_deg(right)
    bearing_presence_flip = (bearing_left is None) != (bearing_right is None)
    bearing_delta = None
    bearing_flip = False
    if bearing_left is not None and bearing_right is not None:
        bearing_delta = abs(bearing_left - bearing_right)
        bearing_flip = bearing_delta > float(tau_bearing_deg)
    return {
        'status_flip': status_flip,
        'presence_flip': a['detected'] != b['detected'],
        'reference_flip': reference_flip,
        'identity_flip': identity_flip,
        'identity_claim_flip': identity_flip,
        'reject_flip': reject_flip,
        'rejection_reason_flip': reject_flip,
        'bearing_presence_flip': bearing_presence_flip,
        'bearing_flip': bearing_flip,
        'bearing_delta_deg': bearing_delta,
        'bearing_left_deg': bearing_left,
        'bearing_right_deg': bearing_right,
        'changed': bool(status_flip or reference_flip or identity_flip
                        or reject_flip or bearing_presence_flip or bearing_flip),
        'left': a,
        'right': b,
    }


def metric_decision(row):
    """Extract the metric-layer decision of an evaluate_frame row."""
    row = row or {}
    return {
        'presence_class': row.get('presence_class'),
        'reference_class': row.get('reference_class'),
        'joint_ok': row.get('joint_ok'),
        'joint_fail_reason': row.get('joint_fail_reason'),
        'joint_evaluable': row.get('joint_evaluable'),
        'identity_claim': row.get('identity_claim'),
        'identity_correct': row.get('identity_correct'),
        'high_confidence_false_match': row.get('high_confidence_false_match'),
    }


def metric_decision_diff(left_row, right_row):
    a = metric_decision(left_row)
    b = metric_decision(right_row)
    return {
        'presence_flip': a['presence_class'] != b['presence_class'],
        'reference_flip': a['reference_class'] != b['reference_class'],
        'joint_flip': a['joint_ok'] != b['joint_ok'],
        'joint_fail_reason_flip': a['joint_fail_reason'] != b['joint_fail_reason'],
        'left': a,
        'right': b,
    }


def match_detections(left, right, iou_thres=0.5):
    """Greedy IoU matching of candidate dicts sorted by score."""
    if not left or not right:
        return []
    order = sorted(range(len(left)),
                   key=lambda i: float(left[i].get('score') or 0.0),
                   reverse=True)
    used = set()
    pairs = []
    for index in order:
        item = left[index]
        bbox = item.get('bbox_xywh')
        if bbox is None:
            continue
        box = np.array([bbox[0], bbox[1], bbox[0] + bbox[2],
                        bbox[1] + bbox[3]], dtype=np.float32)
        best = None
        for other_index, other in enumerate(right):
            if other_index in used:
                continue
            other_bbox = other.get('bbox_xywh')
            if other_bbox is None:
                continue
            other_box = np.array([other_bbox[0], other_bbox[1],
                                  other_bbox[0] + other_bbox[2],
                                  other_bbox[1] + other_bbox[3]],
                                 dtype=np.float32)
            iou = float(_iou_xyxy_one(box, other_box[None, :])[0])
            if iou < float(iou_thres):
                continue
            if best is None or iou > best[1]:
                best = (other_index, iou)
        if best is None:
            continue
        used.add(best[0])
        other = right[best[0]]
        keypoint_distance = None
        if item.get('keypoint_px') is not None and \
                other.get('keypoint_px') is not None:
            keypoint_distance = math.hypot(
                float(item['keypoint_px'][0]) - float(other['keypoint_px'][0]),
                float(item['keypoint_px'][1]) - float(other['keypoint_px'][1]))
        pairs.append({
            'left_index': index,
            'right_index': best[0],
            'bbox_iou': best[1],
            'keypoint_distance_px': keypoint_distance,
        })
    return pairs


def summarize_pairs(pairs):
    """Max/median keypoint differences from match pairs."""
    keypoint_diffs = [pair['keypoint_distance_px'] for pair in pairs
                      if pair['keypoint_distance_px'] is not None]
    keypoint_diffs = sorted(keypoint_diffs)
    return {
        'matched_pairs': len(pairs),
        'keypoint_pairs': len(keypoint_diffs),
        'keypoint_max_px': (keypoint_diffs[-1] if keypoint_diffs else None),
        'keypoint_median_px': (keypoint_diffs[len(keypoint_diffs) // 2]
                               if keypoint_diffs else None),
        'bbox_iou_min': (min(pair['bbox_iou'] for pair in pairs)
                         if pairs else None),
        'bbox_iou_median': (sorted(pair['bbox_iou'] for pair in pairs)[
            len(pairs) // 2] if pairs else None),
    }
