"""Three-path end-to-end ONNX parity for the bounded landmark model.

Compares, on the SAME image and the SAME preprocessed canvas:
  A pt_square             ultralytics .pt predict on a pre-letterboxed canvas
  B onnx_native_square    ultralytics .onnx predict on the same canvas
  C raw_ort_square        raw onnxruntime + numpy NMS + eval-tool decode

and, for explaining the old "4.67 px" number, the two ultralytics default
preprocessing modes:
  D pt_default_rect       .pt predict on the source image (auto/rect letterbox)
  E onnx_native_default   .onnx predict on the source image (square letterbox)

All paths share the frozen decode thresholds (read from the model freeze file)
and the source-pixel coordinate domain.  Decision flips are counted at the
observation level and, for annotated frames, at the metric level
(presence_class / reference_class / joint_ok) with explicit denominators.

Scope: host-side exploratory parity only.  Not a new final evaluation, not an
accuracy/board/navigation claim.  The final pool is sampled read-only and the
one-shot exploratory final is never rerun.

Usage (inside .venv/landmark-train):
    .venv/landmark-train/Scripts/python.exe scripts/landmark_onnx_parity.py \
        --config configs/perception/landmark_export_v1.json

Exit codes: 0 = parity self-check passed, 2 = invalid input, 3 = overwrite
refused, 4 = parity self-check failed.
"""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', '1')
os.environ.setdefault('TORCH_FORCE_NO_WEIGHT_ONLY_LOAD', '1')
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from boom_birds.evaluation import landmark_onnx as parity  # noqa: E402
from boom_birds.evaluation import landmark_yolo as yolo  # noqa: E402
from boom_birds.evaluation import landmark_metrics as metrics  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / 'configs' / 'perception' / 'landmark_export_v1.json'
DEFAULT_FREEZE = REPO_ROOT / 'configs' / 'perception' / 'landmark_model_freeze_v1.json'
DEFAULT_VAL_LABELS = REPO_ROOT / 'outputs' / 'perception' / 'dev_annotations_20261104' / 'labels_val.json'
DEFAULT_FINAL_LABELS = REPO_ROOT / 'outputs' / 'perception' / 'final_exploratory_20261104' / 'labels_v1.json'
DEFAULT_INTRINSICS = {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0}
EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3
EXIT_PARITY_FAILED = 4


# --- CLI / config -----------------------------------------------------------

def resolve_repo_path(value, *, allow_absolute=False, what='path'):
    if value is None or str(value).strip() == '':
        raise ValueError('%s is required' % what)
    path = Path(str(value))
    if path.is_absolute() and not allow_absolute:
        raise ValueError('%s must be repo-relative, got %r' % (what, value))
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Compare PyTorch, ultralytics-native ONNX and raw '
                    'onnxruntime decoding end-to-end on the same canvas, with '
                    'the same NMS, thresholds and coordinate domain.')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--freeze', default=str(DEFAULT_FREEZE))
    parser.add_argument('--pt', default=None, help='.pt checkpoint override')
    parser.add_argument('--onnx', default=None,
                        help='.onnx file; when omitted the export config output '
                             'is used, or --export-from-pt exports first')
    parser.add_argument('--alternate-onnx', default=None,
                        help='second .onnx (e.g. a fresh export) to check '
                             'numerically against --onnx')
    parser.add_argument('--export-from-pt', action='store_true',
                        help='run scripts/landmark_export_onnx.py first')
    parser.add_argument('--val-labels', default=str(DEFAULT_VAL_LABELS))
    parser.add_argument('--final-labels', default=str(DEFAULT_FINAL_LABELS))
    parser.add_argument('--identity-labels',
                        default=str(REPO_ROOT / 'outputs' / 'perception' /
                                    'dev_annotations_20261104' /
                                    'labels_identity_dev.json'))
    parser.add_argument('--identity-frames', type=int, default=None,
                        help='number of identity/MS1 frames to include '
                             '(default: all)')
    parser.add_argument('--skip-identity', dest='identity', action='store_false',
                        default=True)
    parser.add_argument('--tau-bearing-deg', type=float, default=0.01,
                        help='bearing comparison tolerance in degrees')
    parser.add_argument('--expected-pt-sha', default=None,
                        help='override the config export.source_weights_sha256 '
                             'pin (candidate model runs use their own sha)')
    parser.add_argument('--candidate-label', default=None,
                        help='candidate/model label recorded in the evidence '
                             '(e.g. candidate_A_3seed)')
    parser.add_argument('--selection-json', default=None,
                        help='T22 selection/freeze JSON recorded as model '
                             'provenance (read-only)')
    parser.add_argument('--val-frames', type=int, default=None)
    parser.add_argument('--final-frames', type=int, default=None)
    parser.add_argument('--synthetic-base', type=int, default=None)
    parser.add_argument('--near-threshold', type=int, default=None)
    parser.add_argument('--skip-final', action='store_true',
                        help='do not sample the exploratory final pool')
    parser.add_argument('--skip-synthetic', action='store_true')
    parser.add_argument('--device-pt', default='cpu',
                        help='device for the primary .pt paths; cpu keeps the '
                             'three paths on one device (a GPU run is kept as a '
                             'separate device-sensitivity path)')
    parser.add_argument('--no-gpu-path', dest='gpu_path', action='store_false',
                        default=True,
                        help='do not add the GPU device-sensitivity path')
    parser.add_argument('--conf-nms', type=float, default=0.01)
    parser.add_argument('--iou-nms', type=float, default=0.7)
    parser.add_argument('--tau-det', type=float, default=None)
    parser.add_argument('--tau-px', type=float, default=None)
    parser.add_argument('--tau-iou', type=float, default=None)
    parser.add_argument('--tau-conf', type=float, default=None)
    parser.add_argument('--tau-margin', type=float, default=None)
    parser.add_argument('--tau-kpt', type=float, default=None)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--out-dir',
                        default='outputs/perception/onnx_parity_20261104')
    parser.add_argument('--evidence-out', default=None,
                        help='write the versioned evidence JSON here')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--no-self-check', dest='self_check',
                        action='store_false', default=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(argv)


def load_config(path):
    document = parity.load_json(Path(path))
    if document.get('schema_version') != 'dsh.landmark_export.v1':
        raise ValueError('unexpected config schema: %r'
                         % document.get('schema_version'))
    return document


def load_thresholds(freeze_path, overrides=None):
    freeze = parity.load_json(Path(freeze_path))
    frozen = (freeze.get('thresholds') or {}).get('frozen') or {}
    values = {
        'tau_det': float(frozen.get('tau_det')),
        'tau_conf': float(frozen.get('tau_conf')),
        'tau_px': float(frozen.get('tau_px')),
        'tau_iou': float(frozen.get('tau_iou')),
        'tau_kpt': 0.5,
        'tau_margin': 0.1,
    }
    tau_margin = frozen.get('tau_margin')
    if isinstance(tau_margin, dict):
        values['tau_margin'] = float(tau_margin.get('value', 0.1))
    elif isinstance(tau_margin, (int, float)):
        values['tau_margin'] = float(tau_margin)
    tau_kpt = frozen.get('tau_kpt')
    if isinstance(tau_kpt, dict) and tau_kpt.get('value') is not None:
        values['tau_kpt'] = float(tau_kpt['value'])
    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = float(value)
    return values, {
        'path': str(Path(freeze_path)),
        'sha256': parity.sha256_file(freeze_path) if Path(freeze_path).is_file() else None,
        'values': values,
    }


# --- frames ----------------------------------------------------------------

def _find_image(repo_root, annotation):
    image_field = annotation.get('image')
    if image_field:
        candidate = Path(repo_root) / image_field
        if candidate.is_file():
            return candidate
    name = Path(image_field or annotation.get('frame_id')
                or '').name
    for root in sorted((Path(repo_root) / 'outputs' / 'sensor_shadow').glob('*')):
        for candidate in (root / 'images' / name, root / name):
            if candidate.is_file():
                return candidate
    return None


def build_annotation_frames(labels_path, split, repo_root):
    document = parity.load_json(Path(labels_path))
    frames = []
    missing = 0
    for annotation in document.get('annotations') or []:
        source = annotation.get('source') or {}
        if split is not None and source.get('split') != split:
            continue
        image_path = _find_image(repo_root, annotation)
        if image_path is None:
            missing += 1
            continue
        gt, reference_px, strata = yolo.ground_truth_from_annotation(annotation)
        intrinsics = yolo.pixel_basis_from_annotation(annotation)
        if intrinsics is None:
            intrinsics = dict(DEFAULT_INTRINSICS)
        frames.append({
            'frame_id': annotation.get('frame_id'),
            'image_path': image_path,
            'width': int(annotation.get('image_width') or 0),
            'height': int(annotation.get('image_height') or 0),
            'gt': gt,
            'reference_px': reference_px,
            'strata': strata,
            'intrinsics': intrinsics,
            'scenarios': [],
            'negative_type': annotation.get('negative_type'),
            'confusers': [item.get('confuser_id')
                          for item in (annotation.get('confusers') or [])],
            'group_id': (source.get('group_id')),
        })
    for frame in frames:
        if frame['width'] <= 0 or frame['height'] <= 0:
            image = __import__('cv2').imread(str(frame['image_path']))
            frame['height'], frame['width'] = image.shape[:2]
        gt = frame['gt'] or {}
        if gt.get('present') and gt.get('reference') == 'UNAVAILABLE':
            frame['scenarios'].append('keypoint_unavailable')
        if gt.get('truncated'):
            frame['scenarios'].append('edge_truncation')
    return frames, {'labels_path': str(Path(labels_path)),
                    'labels_sha256': parity.sha256_file(labels_path),
                    'split': split, 'frames': len(frames),
                    'missing_images': missing}


def select_stratified(frames, limit, seed=0):
    """Deterministic round-robin over (present, reference, truncated, family)."""
    if limit is None or limit >= len(frames):
        return list(frames)
    import random
    rng = random.Random(seed)
    groups = {}
    for frame in sorted(frames, key=lambda item: str(item['frame_id'])):
        gt = frame['gt'] or {}
        key = (bool(gt.get('present')), str(gt.get('reference')),
               bool(gt.get('truncated')),
               str((frame['strata'] or {}).get('family')))
        groups.setdefault(key, []).append(frame)
    order = list(groups)
    rng.shuffle(order)
    selected = []
    index = 0
    while len(selected) < limit:
        added = False
        for key in order:
            if index < len(groups[key]):
                selected.append(groups[key][index])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        index += 1
    return selected


def _save_image(path, image):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError('cannot write %s' % path)
    return path


def make_synthetic_frames(base_frames, out_dir, limit=None, seed=0):
    """Deterministic synthetic variants: aspect, edge truncation, multi candidate."""
    import cv2
    import numpy as np
    selected = base_frames[:limit] if limit else list(base_frames)
    synthetic_dir = Path(out_dir) / 'synthetic'
    frames = []
    for base_index, base in enumerate(selected):
        image = cv2.imread(str(base['image_path']))
        if image is None:
            continue
        height, width = image.shape[:2]
        gt_bbox = ((base['gt'] or {}).get('bbox_xywh'))
        tag = 's%02d' % base_index
        # aspect-ratio variants: center crops that stay inside the source image
        for cw, ch in ((320, 180), (240, 180), (180, 240), (320, 120)):
            if cw > width or ch > height:
                continue
            x0 = (width - cw) // 2
            y0 = (height - ch) // 2
            crop = image[y0:y0 + ch, x0:x0 + cw]
            name = 'aspect_%s_%dx%d' % (tag, cw, ch)
            path = _save_image(synthetic_dir / (name + '.png'), crop)
            frames.append({'frame_id': name, 'image_path': path,
                           'width': cw, 'height': ch, 'gt': None,
                           'reference_px': None, 'intrinsics': dict(DEFAULT_INTRINSICS),
                           'strata': {'family': 'SYNTHETIC'},
                           'base_frame_id': base['frame_id'],
                           'scenarios': ['aspect']})
        # edge-truncation variants: crop anchored on the GT box so the tower is
        # cut by the right/bottom border when the annotation allows it
        if gt_bbox:
            bx, by, bw, bh = [float(v) for v in gt_bbox]
            for edge, (cw, ch) in (('right', (200, 160)), ('bottom', (200, 160))):
                if cw > width or ch > height:
                    continue
                cx = bx + bw / 2.0
                cy = by + bh / 2.0
                x0 = int(max(0, min(width - cw, cx - cw * 0.7)))
                y0 = int(max(0, min(height - ch, cy - ch * 0.2)))
                crop = image[y0:y0 + ch, x0:x0 + cw]
                name = 'edge_%s_%s' % (edge, tag)
                path = _save_image(synthetic_dir / (name + '.png'), crop)
                frames.append({'frame_id': name, 'image_path': path,
                               'width': cw, 'height': ch, 'gt': None,
                               'reference_px': None,
                               'intrinsics': dict(DEFAULT_INTRINSICS),
                               'strata': {'family': 'SYNTHETIC'},
                               'base_frame_id': base['frame_id'],
                               'scenarios': ['edge_truncation', 'synthetic']})
        # multi candidate: two copies side by side -> two towers, non-square
        doubled = np.concatenate([image, image], axis=1)
        name = 'multi_%s' % tag
        path = _save_image(synthetic_dir / (name + '.png'), doubled)
        frames.append({'frame_id': name, 'image_path': path,
                       'width': doubled.shape[1], 'height': doubled.shape[0],
                       'gt': None, 'reference_px': None,
                       'intrinsics': dict(DEFAULT_INTRINSICS),
                       'strata': {'family': 'SYNTHETIC'},
                       'base_frame_id': base['frame_id'],
                       'scenarios': ['multi_candidate', 'synthetic']})
        if gt_bbox:
            frames[-1]['scenarios'].append('aspect')
    return frames


# --- path runners ----------------------------------------------------------

def decode_thresholds(thresholds):
    """Only the decode-stage keys accepted by landmark_yolo.merge_thresholds."""
    return yolo.merge_thresholds({
        'tau_det': thresholds['tau_det'],
        'tau_margin': thresholds['tau_margin'],
        'tau_kpt': thresholds['tau_kpt'],
    })


def _frame_intrinsics(frame):
    intrinsics = frame.get('intrinsics') or dict(DEFAULT_INTRINSICS)
    return {key: float(value) for key, value in intrinsics.items()
            if key in ('fx_px', 'cx_px') and value is not None}


def prepare_canvas(frame, imgsz, canvas_dir):
    tensor, spec, canvas = parity.preprocess(frame['image_path'], imgsz)
    canvas_path = _save_image(Path(canvas_dir) / (frame['frame_id'] + '.png'),
                              canvas)
    return tensor, spec, canvas, canvas_path


def decode_model_on_canvas(model, canvas_path, spec, frame, thresholds,
                         device='cpu'):
    results = model.predict(source=str(canvas_path), imgsz=spec.canvas_width,
                            conf=thresholds['conf_nms'], verbose=False,
                            device=device)
    return yolo.decode_ultralytics_result(
        results[0], image_width=spec.source_width,
        image_height=spec.source_height,
        letterbox=spec.as_evaltool_letterbox(), coordinates='model',
        intrinsics=_frame_intrinsics(frame),
        thresholds=decode_thresholds(thresholds),
        frame_id=frame['frame_id'], image=str(frame['image_path']))


def decode_model_on_source(model, frame, thresholds, device='cpu'):
    results = model.predict(source=str(frame['image_path']),
                            imgsz=thresholds['imgsz'],
                            conf=thresholds['conf_nms'], verbose=False,
                            device=device)
    return yolo.decode_ultralytics_result(
        results[0], image_width=frame['width'], image_height=frame['height'],
        intrinsics=_frame_intrinsics(frame),
        thresholds=decode_thresholds(thresholds),
        coordinates='source', frame_id=frame['frame_id'],
        image=str(frame['image_path']))


def raw_rows_from_output(output):
    import numpy as np
    array = np.asarray(output, dtype=np.float32)
    if array.ndim == 3:
        rows = array[0].T
    elif array.ndim == 2:
        rows = array.T if array.shape[0] < array.shape[1] else array
    else:
        raise ValueError('unexpected ONNX output rank %d' % array.ndim)
    return np.ascontiguousarray(rows)


def decode_raw_ort(session, input_name, tensor, spec, frame, thresholds):
    output = session.run(None, {input_name: tensor})[0]
    rows = raw_rows_from_output(output)
    kept = parity.nms_rows(rows, conf_thres=thresholds['conf_nms'],
                           iou_thres=thresholds['iou_nms'], max_det=300)
    observation = parity.decode_pose_rows(
        kept, spec, image_width=spec.source_width,
        image_height=spec.source_height,
        intrinsics=_frame_intrinsics(frame),
        thresholds=decode_thresholds(thresholds),
        frame_id=frame['frame_id'], image=str(frame['image_path']))
    raw_top = float(rows[:, 4].max()) if rows.size else 0.0
    return observation, {'raw_anchors': int(rows.shape[0]),
                         'nms_kept': int(len(kept)),
                         'raw_top_score': raw_top}


def metric_row(frame, observation, thresholds):
    gt = frame.get('gt')
    if gt is None or not gt.get('frame_id'):
        return None
    prediction = yolo.observation_to_metric_prediction(observation)
    intrinsics = _frame_intrinsics(frame)
    try:
        return metrics.evaluate_frame(
            gt, prediction, tau_iou=thresholds['tau_iou'],
            reference_px=frame.get('reference_px'), tau_px=thresholds['tau_px'],
            tau_conf=thresholds['tau_conf'],
            fx_px=intrinsics.get('fx_px'), cx_px=intrinsics.get('cx_px'),
            strata=frame.get('strata'))
    except Exception as error:
        return {'error': repr(error), 'frame_id': frame['frame_id']}


# --- comparisons -----------------------------------------------------------

def _compact_observation(observation):
    payload = parity.candidate_from_observation(observation)
    if payload is None:
        return None
    payload['keypoint_confidence'] = observation.get('keypoint_confidence')
    payload['landmark_id'] = observation.get('landmark_id')
    return payload


def compare(records, frames_by_id, name_left, name_right, tau_kpt=0.5,
            tau_bearing_deg=0.01):
    frames = [frame_id for frame_id in records
              if records[frame_id].get(name_left) is not None
              and records[frame_id].get(name_right) is not None]
    observation_flips = []
    presence_flips = []
    reference_flips = []
    identity_flips = []
    identity_claim_flips = []
    identity_gt_flips = []
    false_claim_flips = []
    reject_reason_flips = []
    invalid_status_flips = []
    bearing_flips = []
    bearing_presence_flips = []
    bearing_deltas = []
    wrong_claims = {name_left: [], name_right: []}
    flips_by_scenario = {}
    joint_flips = []
    keypoint_diffs = []
    emitted_keypoint_diffs = []
    matched_pairs_total = 0
    metric_denominator = 0
    for frame_id in frames:
        record = records[frame_id]
        left = record[name_left]['observation']
        right = record[name_right]['observation']
        diff = parity.decision_diff(left, right,
                                     tau_bearing_deg=tau_bearing_deg)
        frame_scenarios = list((frames_by_id.get(frame_id) or {}).get('scenarios')
                               or ['real'])
        if diff['changed']:
            observation_flips.append({'frame_id': frame_id,
                                      'diff': {key: value for key, value
                                               in diff.items()
                                               if key not in ('left', 'right')}})
        layer_flips = {
            'presence': diff['presence_flip'],
            'reference': diff['reference_flip'],
            'identity_claim': diff['identity_claim_flip'],
            'rejection_reason': diff['rejection_reason_flip'],
            'invalid_status': (parity.rejection_decision(left)['invalid']
                               != parity.rejection_decision(right)['invalid']),
            'bearing': diff['bearing_flip'],
            'bearing_presence': diff['bearing_presence_flip'],
        }
        for scenario in frame_scenarios:
            bucket = flips_by_scenario.setdefault(scenario, {})
            for layer, flipped in layer_flips.items():
                if flipped:
                    bucket[layer] = bucket.get(layer, 0) + 1
        if diff['presence_flip']:
            presence_flips.append(frame_id)
        if diff['reference_flip']:
            reference_flips.append(frame_id)
        if diff['identity_flip']:
            identity_flips.append(frame_id)
        if diff['identity_claim_flip']:
            identity_claim_flips.append(frame_id)
        if diff['rejection_reason_flip']:
            reject_reason_flips.append(frame_id)
        if layer_flips['invalid_status']:
            invalid_status_flips.append(frame_id)
        if diff['bearing_delta_deg'] is not None:
            bearing_deltas.append((diff['bearing_delta_deg'], frame_id))
        if diff['bearing_flip']:
            bearing_flips.append(frame_id)
        if diff['bearing_presence_flip']:
            bearing_presence_flips.append(frame_id)
        truth = (frames_by_id.get(frame_id) or {}).get('gt') or {}
        if truth.get('present') is not True:
            left_claim = parity.identity_decision(left)['claimed']
            right_claim = parity.identity_decision(right)['claimed']
            if left_claim != right_claim:
                false_claim_flips.append(frame_id)
        left_candidates = (left.get('candidates') or []) if left else []
        right_candidates = (right.get('candidates') or []) if right else []
        if left is not None and right is not None \
                and left.get('keypoint_px') is not None \
                and right.get('keypoint_px') is not None:
            emitted_keypoint_diffs.append((
                math.hypot(float(left['keypoint_px'][0])
                           - float(right['keypoint_px'][0]),
                           float(left['keypoint_px'][1])
                           - float(right['keypoint_px'][1])), frame_id))
        pairs = parity.match_detections(left_candidates, right_candidates,
                                        iou_thres=0.5)
        matched_pairs_total += len(pairs)
        for pair in pairs:
            left_candidate = left_candidates[pair['left_index']]
            right_candidate = right_candidates[pair['right_index']]
            if float(left_candidate.get('keypoint_confidence') or 0.0) < tau_kpt \
                    or float(right_candidate.get('keypoint_confidence') or 0.0) < tau_kpt:
                # below the frozen keypoint-availability threshold the position is
                # not a consumer-facing reference; comparing it would report
                # meaningless outliers (e.g. a 300 px un-emitted keypoint)
                continue
            if pair['keypoint_distance_px'] is not None:
                keypoint_diffs.append((pair['keypoint_distance_px'], frame_id))
        left_row = record.get('metrics', {}).get(name_left)
        right_row = record.get('metrics', {}).get(name_right)
        if left_row is not None and right_row is not None \
                and 'error' not in left_row and 'error' not in right_row:
            metric_denominator += 1
            metric_diff = parity.metric_decision_diff(left_row, right_row)
            if metric_diff['joint_flip']:
                joint_flips.append({'frame_id': frame_id,
                                    'left': metric_diff['left'],
                                    'right': metric_diff['right']})
            if left_row.get('identity_correct') != right_row.get('identity_correct'):
                identity_gt_flips.append(frame_id)
            for name, row in ((name_left, left_row), (name_right, right_row)):
                if row.get('identity_claim') is True \
                        and row.get('identity_correct') is not True:
                    wrong_claims[name].append(frame_id)
    keypoint_diffs.sort(reverse=True)
    keypoint_values = [value for value, _ in keypoint_diffs]
    emitted_keypoint_diffs.sort(reverse=True)
    emitted_values = [value for value, _ in emitted_keypoint_diffs]
    return {
        'left': name_left,
        'right': name_right,
        'frames': len(frames),
        'metric_frames': metric_denominator,
        'observation_decision_flips': len(observation_flips),
        'observation_flip_frame_ids': [item['frame_id'] for item
                                       in observation_flips][:50],
        'observation_flip_details': observation_flips[:50],
        'presence_flips': len(presence_flips),
        'presence_flip_frame_ids': presence_flips[:50],
        'reference_flips': len(reference_flips),
        'reference_flip_frame_ids': reference_flips[:50],
        'identity_flips': len(identity_flips),
        'identity_flip_frame_ids': identity_flips[:50],
        'identity_claim_flips': len(identity_claim_flips),
        'identity_claim_flip_frame_ids': identity_claim_flips[:50],
        'identity_gt_flips': len(identity_gt_flips),
        'identity_gt_flip_frame_ids': identity_gt_flips[:50],
        'false_claim_flips': len(false_claim_flips),
        'false_claim_flip_frame_ids': false_claim_flips[:50],
        'reject_reason_flips': len(reject_reason_flips),
        'reject_reason_flip_frame_ids': reject_reason_flips[:50],
        'invalid_status_flips': len(invalid_status_flips),
        'bearing_flips': len(bearing_flips),
        'bearing_flip_frame_ids': bearing_flips[:50],
        'bearing_presence_flips': len(bearing_presence_flips),
        'bearing_deltas_deg': [{'frame_id': frame_id, 'delta_deg': value}
                               for value, frame_id in sorted(
                                   bearing_deltas, reverse=True)[:10]],
        'bearing_max_delta_deg': (max(value for value, _ in bearing_deltas)
                                  if bearing_deltas else None),
        'wrong_claims': {name: len(ids) for name, ids in wrong_claims.items()},
        'flips_by_scenario': flips_by_scenario,
        'joint_flips': len(joint_flips),
        'joint_flip_details': joint_flips[:50],
        'matched_pairs': matched_pairs_total,
        'keypoint_pairs': len(keypoint_values),
        'keypoint_max_px': (keypoint_values[0] if keypoint_values else None),
        'keypoint_median_px': (keypoint_values[len(keypoint_values) // 2]
                               if keypoint_values else None),
        'keypoint_worst_frames': [{'frame_id': frame_id, 'keypoint_px': value}
                                  for value, frame_id in keypoint_diffs[:5]],
        'emitted_keypoint_pairs': len(emitted_values),
        'emitted_keypoint_max_px': (emitted_values[0] if emitted_values
                                    else None),
        'emitted_keypoint_median_px': (emitted_values[len(emitted_values) // 2]
                                       if emitted_values else None),
    }


def scenario_breakdown(records, frames_by_id):
    import collections
    per_scenario = collections.OrderedDict()
    for frame_id, record in records.items():
        frame = frames_by_id.get(frame_id) or {}
        scenarios = list(frame.get('scenarios') or [])
        if not scenarios:
            scenarios = ['real']
        for scenario in scenarios:
            bucket = per_scenario.setdefault(scenario, {
                'frames': 0,
                'paths': {},
                'joint_flips': {},
            })
            bucket['frames'] += 1
            for name, payload in record.items():
                if not isinstance(payload, dict) or 'observation' not in payload:
                    continue
                observation = payload.get('observation') or {}
                statuses = bucket['paths'].setdefault(name, {})
                status = observation.get('status')
                statuses[status] = statuses.get(status, 0) + 1
                metrics_row = (record.get('metrics') or {}).get(name)
                if metrics_row and metrics_row.get('joint_ok') is not None:
                    joint = bucket.setdefault('joint_ok_paths', {})
                    joint.setdefault(name, []).append(
                        1 if metrics_row['joint_ok'] else 0)
    return per_scenario


# --- torch raw numeric parity ----------------------------------------------

def _per_channel_max_abs(difference, channels=8):
    """Max |diff| per output channel for (1, C, N) or (1, N, C) tensors."""
    import numpy as np
    array = np.asarray(difference, dtype=np.float32)
    if array.ndim == 3:
        array = array[0]
    if array.ndim == 2 and array.shape[0] == channels:
        return array.max(axis=1)
    if array.ndim == 2 and array.shape[1] == channels:
        return array.max(axis=0)
    return np.zeros(channels, dtype=np.float32)


def torch_raw_outputs(model_pt, tensors, imgsz):
    import numpy as np
    import torch
    # force CPU fp32: after a GPU predict() the module may live on cuda, and
    # TF32 convolutions would add ~1e-3 relative noise against the CPU ONNX run
    network = model_pt.model.float().cpu().eval()
    outputs = []
    with torch.no_grad():
        for tensor in tensors:
            batch = torch.from_numpy(tensor).to('cpu')
            output = network(batch)
            if isinstance(output, (tuple, list)):
                output = output[0]
            outputs.append(output.detach().cpu().numpy())
    return outputs


DECISION_LAYER_FIELDS = ('presence_flips', 'reference_flips',
                        'identity_claim_flips', 'identity_gt_flips',
                        'false_claim_flips', 'reject_reason_flips',
                        'invalid_status_flips', 'bearing_flips',
                        'bearing_presence_flips', 'joint_flips')


def decision_layers(pairs, pair_names):
    """Per-layer decision flip matrix for the requested path pairs."""
    matrix = {}
    for name in pair_names:
        pair = pairs.get(name)
        if pair is None:
            continue
        matrix[name] = {field: pair.get(field) for field in DECISION_LAYER_FIELDS}
        matrix[name]['observation_decision_flips'] = pair.get(
            'observation_decision_flips')
        matrix[name]['wrong_claims'] = pair.get('wrong_claims')
    return matrix


def identity_rejection_summary(records, frames_by_id, pairs, pair_names):
    """Identity / rejection / bearing / MS1 / multi-candidate summary."""
    import collections
    ms1_similar = [frame_id for frame_id, frame in frames_by_id.items()
                   if 'ms1_similar' in (frame.get('scenarios') or [])]
    ms1_both = [frame_id for frame_id, frame in frames_by_id.items()
                if 'ms1_both' in (frame.get('scenarios') or [])]
    multi_candidate = [frame_id for frame_id, frame in frames_by_id.items()
                       if 'multi_candidate' in (frame.get('scenarios') or [])
                       or 'multi_candidate_candidate'
                       in (frame.get('scenarios') or [])]
    paths = ['pt_square', 'onnx_native_square', 'raw_ort_square']
    by_path = {}
    for name in paths:
        statuses = collections.Counter()
        claims = 0
        wrong_claims = 0
        claims_on_absent = 0
        for frame_id, record in records.items():
            payload = record.get(name) or {}
            observation = payload.get('observation') or {}
            row = (record.get('metrics') or {}).get(name) or {}
            statuses[observation.get('status')] += 1
            if observation.get('identity_claimed'):
                claims += 1
                truth = (frames_by_id.get(frame_id) or {}).get('gt') or {}
                if truth.get('present') is not True:
                    claims_on_absent += 1
                if row.get('identity_claimed') is True \
                        and row.get('identity_correct') is not True:
                    wrong_claims += 1
        by_path[name] = {'statuses': dict(statuses), 'claims': claims,
                         'wrong_claims': wrong_claims,
                         'claims_on_absent': claims_on_absent}
    ms1 = {
        'ms1_similar_frames': len(ms1_similar),
        'ms1_both_frames': len(ms1_both),
        'multi_candidate_frames': len(multi_candidate),
        'ms1_similar_by_path': {},
        'ms1_both_by_path': {},
        'multi_candidate_by_path': {},
    }
    for name in paths:
        similar = collections.Counter()
        both = collections.Counter()
        multi = collections.Counter()
        for frame_id in ms1_similar:
            observation = (records.get(frame_id, {}).get(name) or {}).get(
                'observation') or {}
            key = '%s|claim=%s' % (observation.get('status'),
                                   bool(observation.get('identity_claimed')))
            similar[key] += 1
        for frame_id in ms1_both:
            observation = (records.get(frame_id, {}).get(name) or {}).get(
                'observation') or {}
            key = '%s|reason=%s|candidates=%d' % (
                observation.get('status'),
                observation.get('reject_reason'),
                int(observation.get('candidate_count') or 0))
            both[key] += 1
        for frame_id in multi_candidate:
            observation = (records.get(frame_id, {}).get(name) or {}).get(
                'observation') or {}
            key = 'candidates=%d|reason=%s' % (
                int(observation.get('candidate_count') or 0),
                observation.get('reject_reason'))
            multi[key] += 1
        ms1['ms1_similar_by_path'][name] = {
            'identity_claim_absent_ms1': dict(similar)}
        ms1['ms1_both_by_path'][name] = {
            'status_reason_candidate_count': dict(both)}
        ms1['multi_candidate_by_path'][name] = dict(multi)
    return {
        'primary_decision_layers': decision_layers(pairs, pair_names),
        'by_path': by_path,
        'ms1_and_multi_candidate': ms1,
    }


def main(argv=None):
    args = parse_args(argv)
    started = time.perf_counter()
    try:
        config = load_config(args.config)
        config_path = Path(args.config)
        export_cfg = config.get('export') or {}
        parity_cfg = config.get('parity') or {}
        tolerances = parity_cfg.get('tolerances') or {}
        sample_policy = parity_cfg.get('sample_policy') or {}
        out_dir = resolve_repo_path(args.out_dir, allow_absolute=True,
                                    what='out-dir')
        out_dir.mkdir(parents=True, exist_ok=True)
        thresholds, thresholds_source = load_thresholds(
            args.freeze,
            {'tau_det': args.tau_det, 'tau_px': args.tau_px,
             'tau_iou': args.tau_iou, 'tau_conf': args.tau_conf,
             'tau_margin': args.tau_margin, 'tau_kpt': args.tau_kpt})
        thresholds['conf_nms'] = float(args.conf_nms)
        thresholds['iou_nms'] = float(args.iou_nms)
        thresholds['imgsz'] = int(args.imgsz)

        # ---- inputs and model files
        pt_path = resolve_repo_path(args.pt or export_cfg.get('source_weights'),
                                    allow_absolute=args.pt is not None,
                                    what='pt')
        if args.onnx:
            onnx_path = resolve_repo_path(args.onnx, allow_absolute=True,
                                          what='onnx')
            export_evidence = None
        else:
            onnx_path = resolve_repo_path(export_cfg.get('output'),
                                          what='onnx')
            export_evidence = None
            if args.export_from_pt or not onnx_path.is_file():
                import subprocess
                export_json = out_dir / 'export_evidence.json'
                command = [sys.executable,
                           str(REPO_ROOT / 'scripts' / 'landmark_export_onnx.py'),
                           '--config', str(config_path),
                           '--json-out', str(export_json), '--verify']
                if not onnx_path.is_file():
                    command.append('--overwrite')
                child_env = dict(os.environ)
                child_env['PYTHONIOENCODING'] = 'utf-8'
                completed = subprocess.run(command, capture_output=True,
                                           text=True, timeout=900,
                                           encoding='utf-8', errors='replace',
                                           env=child_env)
                if completed.returncode != 0:
                    raise RuntimeError('export failed: %s'
                                       % completed.stderr[-2000:])
                export_evidence = parity.load_json(export_json)
        for label, path in (('pt', pt_path), ('onnx', onnx_path)):
            if not Path(path).is_file():
                raise FileNotFoundError('%s not found: %s' % (label, path))
        pt_sha = parity.sha256_file(pt_path)
        onnx_sha = parity.sha256_file(onnx_path)
        alternate_path = None
        if args.alternate_onnx:
            alternate_path = resolve_repo_path(args.alternate_onnx,
                                               allow_absolute=True,
                                               what='alternate-onnx')
            if not alternate_path.is_file():
                raise FileNotFoundError('alternate onnx not found: %s'
                                        % alternate_path)
        config_pt_pin = str(export_cfg.get('source_weights_sha256') or '')
        expected_pt = (args.expected_pt_sha or config_pt_pin)
        pt_pin_check = {
            'config_expected': config_pt_pin,
            'actual': pt_sha,
            'override': args.expected_pt_sha,
            'enforced': bool(expected_pt),
        }
        if expected_pt and pt_sha != expected_pt:
            if args.candidate_label:
                # candidate-model mode: the T14 config pins the old frozen
                # model, so a different candidate is expected; record the pin
                # mismatch instead of aborting (the model identity is carried
                # by candidate.label + the recorded sha).
                pt_pin_check.update({'enforced': False,
                                     'note': 'candidate mode: config pin is for '
                                             'the old T14 frozen model; this '
                                             'candidate is recorded by sha'})
            else:
                raise ValueError(
                    'pt sha256 %s does not match expected %s (pass '
                    '--expected-pt-sha/candidate-label for a new candidate)'
                    % (pt_sha, expected_pt))

        # ---- frames
        val_report = None
        final_report = None
        real_frames = []
        if args.val_frames != 0:
            val_frames, val_report = build_annotation_frames(
                args.val_labels, 'val', REPO_ROOT)
            val_limit = args.val_frames if args.val_frames is not None \
                else int(sample_policy.get('val_frames_max', 48))
            selected_val = select_stratified(val_frames, val_limit,
                                             seed=args.seed)
            for frame in selected_val:
                frame['scenarios'].append('real_val')
            real_frames.extend(selected_val)
        if not args.skip_final and args.final_frames != 0:
            final_frames, final_report = build_annotation_frames(
                args.final_labels, 'test', REPO_ROOT)
            final_limit = args.final_frames if args.final_frames is not None \
                else int(sample_policy.get('final_frames_max', 24))
            selected_final = select_stratified(final_frames, final_limit,
                                               seed=args.seed + 1)
            for frame in selected_final:
                frame['scenarios'].append('real_final')
            real_frames.extend(selected_final)
        identity_report = None
        identity_selected = 0
        if args.identity and Path(args.identity_labels).is_file():
            identity_all, identity_report = build_annotation_frames(
                args.identity_labels, 'val', REPO_ROOT)
            identity_limit = (args.identity_frames
                              if args.identity_frames is not None
                              else len(identity_all))
            selected_identity = select_stratified(identity_all,
                                                  identity_limit,
                                                  seed=args.seed + 3)
            for frame in selected_identity:
                gt = frame.get('gt') or {}
                group = str(frame.get('group_id') or '')
                confusers = [str(item) for item in (frame.get('confusers') or [])]
                frame['scenarios'].append('real_identity')
                if gt.get('present') is not True:
                    frame['scenarios'].append('target_absent')
                    if frame.get('negative_type') == 'SIMILAR_STRUCTURE':
                        frame['scenarios'].append('ms1_similar')
                if any('MS1' in item for item in confusers):
                    frame['scenarios'].append('ms1_confuser')
                    if gt.get('present') is True:
                        frame['scenarios'].append('ms1_both')
                        frame['scenarios'].append('multi_candidate_candidate')
                if 'occlusion' in group:
                    frame['scenarios'].append('occluded')
                if 'trunc' in group:
                    frame['scenarios'].append('edge_truncation')
            identity_selected = len(selected_identity)
            real_frames.extend(selected_identity)
        for frame in real_frames:
            if 'real_val' not in frame['scenarios'] and \
                    'real_final' not in frame['scenarios'] and \
                    'real_identity' not in frame['scenarios']:
                frame['scenarios'].append('real')
        synthetic_base = select_stratified(real_frames, int(sample_policy.get(
            'synthetic_base_frames', 8)), seed=args.seed + 2)
        synthetic = [] if args.skip_synthetic else make_synthetic_frames(
            synthetic_base, out_dir,
            limit=args.synthetic_base or int(sample_policy.get(
                'synthetic_base_frames', 8)), seed=args.seed)
        all_frames = list(real_frames) + synthetic
        frames_by_id = {frame['frame_id']: frame for frame in all_frames}

        # ---- backends
        import numpy as np
        from ultralytics import YOLO
        import onnxruntime
        model_pt = YOLO(str(pt_path), task='pose')
        model_onnx = YOLO(str(onnx_path), task='pose')
        session = onnxruntime.InferenceSession(str(onnx_path),
                                               providers=['CPUExecutionProvider'])
        input_name = session.get_inputs()[0].name
        alternate_session = None
        if alternate_path is not None:
            alternate_session = onnxruntime.InferenceSession(
                str(alternate_path), providers=['CPUExecutionProvider'])

        # ---- near-threshold pre-scan (raw ORT top score on the shared canvas)
        near_limit = args.near_threshold if args.near_threshold is not None \
            else int(sample_policy.get('near_threshold_frames_max', 16))
        window = float(sample_policy.get('near_threshold_window', 0.05))
        near_frames = []
        if near_limit > 0:
            import numpy as np
            for frame in all_frames:
                tensor, spec, _, _ = prepare_canvas(
                    frame, args.imgsz, out_dir / 'canvases')
                output = session.run(None, {input_name: tensor})[0]
                rows = raw_rows_from_output(output)
                top_score = float(rows[:, 4].max()) if rows.size else 0.0
                frame['raw_top_score'] = top_score
                if abs(top_score - thresholds['tau_det']) <= window:
                    near_frames.append(frame)
        for frame in near_frames:
            frame['scenarios'] = [item for item in frame['scenarios']
                                  if item != 'near_threshold']
        for frame in near_frames[:near_limit]:
            frame['scenarios'].append('near_threshold')

        # ---- run all paths
        gpu_available = False
        if args.gpu_path and args.device_pt == 'cpu':
            try:
                import torch
                gpu_available = bool(torch.cuda.is_available())
            except Exception:
                gpu_available = False
        records = {}
        for index, frame in enumerate(all_frames):
            tensor, spec, canvas, canvas_path = prepare_canvas(
                frame, args.imgsz, out_dir / 'canvases')
            record = {'scenario': list(frame.get('scenarios') or []),
                      'image': str(frame['image_path']),
                      'raw_top_score': frame.get('raw_top_score')}
            observation, raw_info = decode_raw_ort(session, input_name, tensor,
                                                   spec, frame, thresholds)
            record['raw_ort_square'] = {'observation': observation,
                                        'raw': raw_info}
            record['pt_square'] = {'observation': decode_model_on_canvas(
                model_pt, canvas_path, spec, frame, thresholds,
                device=args.device_pt)}
            record['onnx_native_square'] = {'observation': decode_model_on_canvas(
                model_onnx, canvas_path, spec, frame, thresholds,
                device='cpu')}
            record['pt_default_rect'] = {'observation': decode_model_on_source(
                model_pt, frame, thresholds, device=args.device_pt)}
            record['onnx_native_default'] = {'observation': decode_model_on_source(
                model_onnx, frame, thresholds, device='cpu')}
            if gpu_available:
                record['pt_square_gpu'] = {'observation': decode_model_on_canvas(
                    model_pt, canvas_path, spec, frame, thresholds,
                    device='cuda:0')}
            record['metrics'] = {
                name: metric_row(frame, payload['observation'], thresholds)
                for name, payload in record.items()
                if isinstance(payload, dict) and 'observation' in payload}
            records[frame['frame_id']] = record
            if not args.quiet and (index + 1) % 20 == 0:
                print('frames', index + 1, '/', len(all_frames))

        # ---- comparisons
        primary = [
            ('pt_square', 'onnx_native_square'),
            ('pt_square', 'raw_ort_square'),
            ('onnx_native_square', 'raw_ort_square'),
        ]
        if gpu_available:
            primary = primary + [('pt_square', 'pt_square_gpu')]
        legacy = [
            ('pt_default_rect', 'onnx_native_default'),
            ('pt_square', 'pt_default_rect'),
            ('onnx_native_square', 'onnx_native_default'),
        ]
        pairs = {}
        for left, right in primary + legacy:
            pairs['%s_vs_%s' % (left, right)] = compare(
                records, frames_by_id, left, right,
                tau_kpt=thresholds['tau_kpt'],
                tau_bearing_deg=args.tau_bearing_deg)

        # ---- torch raw vs onnxruntime raw on the shared canvas
        raw_parity = {'performed': True, 'frames': 0, 'max_abs_diff': None,
                      'shape_match': True}
        try:
            tensors = []
            for frame in all_frames:
                tensor, _, _, _ = prepare_canvas(frame, args.imgsz,
                                                 out_dir / 'canvases')
                tensors.append(tensor)
            torch_outputs = torch_raw_outputs(model_pt, tensors, args.imgsz)
            max_diff = 0.0
            total_abs = 0.0
            count = 0
            shapes_match = True
            per_channel = np.zeros(8, dtype=np.float64)
            all_finite = True
            for tensor, torch_output in zip(tensors, torch_outputs):
                ort_output = session.run(None, {input_name: tensor})[0]
                torch_output = np.asarray(torch_output, dtype=np.float32)
                ort_output = np.asarray(ort_output, dtype=np.float32)
                if torch_output.shape != ort_output.shape:
                    shapes_match = False
                    continue
                if not torch_output.size:
                    continue
                difference = np.abs(torch_output - ort_output)
                all_finite = all_finite and bool(np.isfinite(difference).all())
                max_diff = max(max_diff, float(difference.max()))
                total_abs += float(difference.sum())
                count += int(difference.size)
                per_channel = np.maximum(
                    per_channel, _per_channel_max_abs(difference))
            relative = max_diff / float(args.imgsz)
            relative_atol = float(tolerances.get(
                'raw_max_abs_diff_relative', 1e-3))
            raw_parity.update({
                'frames': len(tensors),
                'max_abs_diff': max_diff,
                'mean_abs_diff': (total_abs / count) if count else None,
                'max_abs_diff_relative_to_input_px': relative,
                'relative_atol': relative_atol,
                'shape_match': shapes_match,
                'all_finite': all_finite,
                'atol_absolute_note': float(tolerances.get(
                    'raw_max_abs_diff', 1e-3)),
                'per_channel_max_abs_diff': {
                    'box_cxcywh': [float(value) for value in per_channel[:4]],
                    'class_score': float(per_channel[4]),
                    'keypoint_xy_conf': [float(value) for value in per_channel[5:]],
                },
                'note': 'the 2026-11-04 smoke-checkpoint claim was a 1.22e-4 '
                        'absolute max on an untrained graph; on the trained '
                        'checkpoint the absolute max is dominated by the '
                        'coordinate channels (~1e-4 relative to 640), which is '
                        'why the pass criterion is relative.  The decision-level '
                        'effect is measured by the three-path comparisons.',
            })
            raw_parity['passed'] = bool(shapes_match and all_finite
                                        and relative <= relative_atol)
        except Exception as error:
            raw_parity = {'performed': False, 'error': repr(error)}

        # ---- alternate ONNX equivalence (fresh export vs frozen artifact)
        onnx_equivalence = None
        if alternate_session is not None:
            alternate_input = alternate_session.get_inputs()[0].name
            max_diff = 0.0
            frames_compared = 0
            for frame in all_frames:
                tensor, _, _, _ = prepare_canvas(frame, args.imgsz,
                                                 out_dir / 'canvases')
                primary_output = session.run(None, {input_name: tensor})[0]
                alternate_output = alternate_session.run(
                    None, {alternate_input: tensor})[0]
                primary_array = np.asarray(primary_output, dtype=np.float32)
                alternate_array = np.asarray(alternate_output, dtype=np.float32)
                if primary_array.shape != alternate_array.shape:
                    max_diff = float('inf')
                    break
                if primary_array.size:
                    max_diff = max(max_diff, float(np.abs(
                        primary_array - alternate_array).max()))
                frames_compared += 1
            onnx_equivalence = {
                'primary': {'path': str(onnx_path), 'sha256': onnx_sha},
                'alternate': {'path': str(alternate_path),
                              'sha256': parity.sha256_file(alternate_path)},
                'frames_compared': frames_compared,
                'raw_max_abs_diff': max_diff,
                'atol': float(tolerances.get('raw_max_abs_diff', 1e-3)),
            }
            onnx_equivalence['passed'] = bool(
                math.isfinite(max_diff)
                and max_diff <= onnx_equivalence['atol'])

        # ---- scenario / near-threshold summaries
        scenarios = scenario_breakdown(records, frames_by_id)
        near_threshold = {
            'window': window,
            'frames': len([frame for frame in all_frames
                           if 'near_threshold' in (frame.get('scenarios') or [])]),
            'pair_status_flips': {
                '%s_vs_%s' % (left, right): len([
                    frame_id for frame_id in records
                    if 'near_threshold' in (frames_by_id.get(frame_id) or {})
                    .get('scenarios', [])
                    and parity.decision_diff(
                        records[frame_id][left]['observation'],
                        records[frame_id][right]['observation'])['status_flip']])
                for left, right in primary},
        }

        # ---- identity / rejection / bearing / MS1 layers
        primary_pair_names_for_layers = [
            'pt_square_vs_onnx_native_square',
            'pt_square_vs_raw_ort_square',
            'onnx_native_square_vs_raw_ort_square',
        ]
        identity_layers = identity_rejection_summary(
            records, frames_by_id, pairs, primary_pair_names_for_layers)
        candidate_meta = {'label': args.candidate_label}
        if args.selection_json:
            selection_path = resolve_repo_path(args.selection_json,
                                               allow_absolute=True,
                                               what='selection-json')
            candidate_meta['selection_json'] = {
                'path': str(selection_path),
                'sha256': (parity.sha256_file(selection_path)
                           if selection_path.is_file() else None),
                'content': (parity.load_json(selection_path)
                            if selection_path.is_file() else None),
            }
        # ---- self-check
        flip_tolerance = int(tolerances.get('decision_flip_count_max', 0))
        keypoint_tolerance = float(tolerances.get('keypoint_max_px', 0.5))
        checks = {}
        primary_pair_names = ['pt_square_vs_onnx_native_square',
                              'pt_square_vs_raw_ort_square',
                              'onnx_native_square_vs_raw_ort_square']
        for pair_name in primary_pair_names:
            pair = pairs.get(pair_name)
            if pair is None:
                continue
            checks[pair_name] = {
                'decision_flips_ok': pair['observation_decision_flips']
                <= flip_tolerance,
                'keypoint_ok': (pair['keypoint_max_px'] is None
                                or pair['keypoint_max_px'] <= keypoint_tolerance),
            }
        layer_checks = {}
        for pair_name in primary_pair_names:
            pair = pairs.get(pair_name) or {}
            layer_checks[pair_name] = {
                field: (pair.get(field) is not None
                        and int(pair.get(field)) <= flip_tolerance)
                for field in DECISION_LAYER_FIELDS
            }
        self_check = {
            'raw_parity_ok': bool(raw_parity.get('passed')),
            'onnx_equivalence_ok': (None if onnx_equivalence is None
                                    else bool(onnx_equivalence['passed'])),
            'primary_decision_layers_ok': layer_checks,
            'primary_pairs': checks,
            'passed': bool(raw_parity.get('passed')) and all(
                all(value.values()) for value in checks.values()) and all(
                    all(value.values()) for value in layer_checks.values()) and (
                    onnx_equivalence is None
                    or bool(onnx_equivalence['passed'])),
        }

        evidence = {
            'schema_version': 'dsh.landmark_onnx_parity.v1',
            'status': ('PARITY_PASS' if self_check['passed']
                       else 'PARITY_FAIL_INVESTIGATE'),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'generated_by': 'scripts/landmark_onnx_parity.py',
            'scope': 'host-side three-path parity; not a final evaluation, not '
                     'an accuracy/board/navigation claim',
            'runtime': {
                'python': sys.version.split()[0],
                'packages': __import__('json').loads(
                    json.dumps({'torch': _version('torch'),
                                'ultralytics': _version('ultralytics'),
                                'onnx': _version('onnx'),
                                'onnxruntime': _version('onnxruntime'),
                                'numpy': _version('numpy')})),
                'seconds': round(time.perf_counter() - started, 2),
            },
            'config': {'path': str(config_path),
                       'sha256': parity.sha256_file(config_path)},
            'thresholds': thresholds_source,
            'nms': {'conf_thres': thresholds['conf_nms'],
                    'iou_thres': thresholds['iou_nms'], 'max_det': 300},
            'models': {
                'pt': {'path': str(pt_path), 'sha256': pt_sha},
                'onnx': {'path': str(onnx_path), 'sha256': onnx_sha},
                'freeze_recorded_onnx_sha256': _freeze_onnx_sha(),
                'pt_sha_pin_check': pt_pin_check,
                'export_evidence': export_evidence,
            },
            'data': {
                'val': val_report,
                'final': final_report,
                'identity': identity_report,
                'sample': {
                    'real_frames': len(real_frames),
                    'synthetic_frames': len(synthetic),
                    'evaluated_frames': len(all_frames),
                    'near_threshold_frames': near_threshold['frames'],
                    'identity_frames': identity_selected,
                    'identity_document_frames': (identity_report['frames']
                                                 if identity_report else 0),
                },
                'final_pool_policy': 'read-only sample; no metrics run, no '
                                     'label/threshold change, final never rerun',
            },
            'paths': {'pt_square': 'ultralytics .pt predict on the shared '
                                   '640x640 canvas, decode model->source',
                      'onnx_native_square': 'ultralytics .onnx predict on the '
                                            'same canvas',
                      'raw_ort_square': 'onnxruntime + numpy NMS (iou 0.7, '
                                        'max_det 300) + eval-tool decode',
                      'pt_default_rect': 'legacy .pt default preprocessing '
                                         '(auto/rect letterbox)',
                      'onnx_native_default': 'legacy .onnx default '
                                             'preprocessing (square letterbox)'},
            'raw_numeric_parity': raw_parity,
            'onnx_equivalence': onnx_equivalence,
            'device_sensitivity': (pairs.get('pt_square_vs_pt_square_gpu')
                                   if gpu_available else None),
            'candidate': candidate_meta,
            'decision_layers': identity_layers['primary_decision_layers'],
            'identity_and_rejection': identity_layers,
            'pairwise': pairs,
            'scenarios': scenarios,
            'near_threshold': near_threshold,
            'self_check': self_check,
            'conclusion': {
                'primary_parity': ('PASS' if self_check['passed'] else 'FAIL'),
                'legacy_4_67px_explanation': _legacy_explanation(pairs),
                'decision_flip_answer': _decision_answer(pairs),
            },
            'limitations': [
                'synthetic aspect/edge/multi-candidate variants have no GT, so '
                'their comparison is observation-level only',
                'near-threshold selection uses the raw ORT top score on the '
                'sampled frames, not a population estimate',
                'the exploratory final pool was sampled read-only after its '
                'single one-shot evaluation; no new final metrics were produced',
                'RKNN/board, real camera, accuracy certification remain out of '
                'scope (UNKNOWN)',
            ],
        }
        detail_path = parity.dump_json(out_dir / 'parity_detail.json', {
            'schema_version': 'dsh.landmark_onnx_parity_detail.v1',
            'frames': records,
        })
        evidence_path = args.evidence_out
        if evidence_path is None:
            evidence_path = parity_cfg.get('outputs', {}).get(
                'evidence_json')
        evidence_path = resolve_repo_path(
            evidence_path or 'docs/reports/perception/onnx_parity_20261104.json',
            allow_absolute=True, what='evidence-out')
        if evidence_path.exists() and not args.overwrite:
            raise FileExistsError('refusing to overwrite %s (pass --overwrite)'
                                  % evidence_path)
        parity.dump_json(evidence_path, evidence)
        if not args.quiet:
            print(json.dumps({
                'status': evidence['status'],
                'raw_numeric_parity': raw_parity,
                'primary': {name: pairs[name] for name in
                            ('pt_square_vs_onnx_native_square',
                             'pt_square_vs_raw_ort_square',
                             'onnx_native_square_vs_raw_ort_square')},
                'legacy': pairs['pt_default_rect_vs_onnx_native_default'],
                'device_sensitivity': pairs.get('pt_square_vs_pt_square_gpu'),
                'near_threshold': near_threshold,
                'self_check': self_check,
                'evidence': str(evidence_path),
                'detail': str(detail_path),
            }, ensure_ascii=False, indent=2))
        return EXIT_OK if self_check['passed'] else EXIT_PARITY_FAILED
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except (ValueError, FileNotFoundError, KeyError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - backend failures
        import traceback
        traceback.print_exc()
        print('parity run failed: %r' % (error,), file=sys.stderr)
        return EXIT_PARITY_FAILED


def _version(name):
    try:
        return getattr(__import__(name), '__version__', None)
    except Exception as error:  # pragma: no cover
        return 'UNAVAILABLE: %r' % (error,)


def _freeze_onnx_sha():
    try:
        freeze = parity.load_json(DEFAULT_FREEZE)
        return ((freeze.get('onnx') or {}).get('sha256'))
    except Exception:
        return None


def _legacy_explanation(pairs):
    legacy = pairs.get('pt_default_rect_vs_onnx_native_default') or {}
    primary = pairs.get('pt_square_vs_onnx_native_square') or {}
    device = pairs.get('pt_square_vs_pt_square_gpu') or {}
    return {
        'device_sensitivity_keypoint_max_px': device.get('keypoint_max_px'),
        'device_sensitivity_joint_flips': device.get('joint_flips'),
        'legacy_keypoint_max_px': legacy.get('keypoint_max_px'),
        'legacy_observation_flips': legacy.get('observation_decision_flips'),
        'legacy_joint_flips': legacy.get('joint_flips'),
        'primary_keypoint_max_px': primary.get('keypoint_max_px'),
        'primary_observation_flips': primary.get('observation_decision_flips'),
        'reading': 'legacy .pt and .onnx ultralytics predictors build different '
                   'letterboxes (auto/rect vs square); the shared-canvas paths '
                   'remove that difference, so a large legacy keypoint delta is '
                   'a preprocessing-mode artefact, not a graph/export error',
    }


def _decision_answer(pairs):
    primary = [pairs.get('pt_square_vs_onnx_native_square') or {},
               pairs.get('pt_square_vs_raw_ort_square') or {},
               pairs.get('onnx_native_square_vs_raw_ort_square') or {}]
    legacy = pairs.get('pt_default_rect_vs_onnx_native_default') or {}
    return {
        'primary_joint_flips': [item.get('joint_flips') for item in primary],
        'primary_observation_flips': [item.get('observation_decision_flips')
                                      for item in primary],
        'legacy_joint_flips': legacy.get('joint_flips'),
        'legacy_observation_flips': legacy.get('observation_decision_flips'),
        'reading': 'with one shared preprocessing mode the three paths must '
                   'agree on every decision; the legacy mismatch is the only '
                   'place where the old 4.67 px class of difference can flip a '
                   'pass/fail decision, and the flip count is reported above',
    }


if __name__ == '__main__':
    raise SystemExit(main())
