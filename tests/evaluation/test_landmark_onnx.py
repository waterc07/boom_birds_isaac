"""Regression tests for the ONNX three-path parity tooling.

Written BEFORE the implementation on purpose (2026-11-04): the first run fails
with ImportError, which is the recorded red state for the new
boom_birds.evaluation.landmark_onnx module.  The tests encode the two defects
found in the earlier raw-onnxruntime evaluation path:

D1  the raw-ORT decode path had no NMS, so one object produced several
    overlapping candidates and decode_candidates rejected the frame with
    MULTIPLE_CANDIDATES (identity not claimed) - a decision flip against the
    ultralytics .pt path;
D2  the .pt and .onnx ultralytics predictors build DIFFERENT letterboxes
    (auto/rect mode for .pt vs square mode for the exported graph), so the old
    "4.67 px keypoint difference" is a preprocessing-mode difference, not a
    graph difference.

These tests are numpy/cv2 only so they run in the Isaac venv (no torch /
ultralytics / onnxruntime needed).  The end-to-end run happens in
.venv/landmark-train via scripts/landmark_onnx_parity.py.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_yolo as yolo  # noqa: E402
from boom_birds.evaluation import landmark_onnx as onnx  # noqa: E402

CONFIG = REPO_ROOT / 'configs' / 'perception' / 'landmark_export_v1.json'


def test_letterbox_square_320x240():
    spec = onnx.letterbox_spec(320, 240, 640, 640)
    assert spec.scale == pytest.approx(2.0)
    assert (spec.pad_left, spec.pad_top) == (0, 80)
    assert spec.auto is False
    image = np.full((240, 320, 3), 255, dtype=np.uint8)
    canvas = onnx.letterbox_image(image, spec)
    assert canvas.shape == (640, 640, 3)
    # top/bottom padding is 114 grey
    assert tuple(canvas[0, 0]) == (114, 114, 114)
    assert tuple(canvas[639, 639]) == (114, 114, 114)
    assert tuple(canvas[320, 320]) == (255, 255, 255)


def test_letterbox_non_square_640x240():
    spec = onnx.letterbox_spec(640, 240, 640, 640)
    assert spec.scale == pytest.approx(1.0)
    assert (spec.pad_left, spec.pad_top) == (0, 200)
    canvas = onnx.letterbox_image(np.zeros((240, 640, 3), np.uint8), spec)
    assert canvas.shape == (640, 640, 3)


def test_letterbox_rect_mode_differs_from_square():
    # ultralytics .pt predictor uses LetterBox(auto=True) for a single image:
    # a 320x240 image becomes a 640x480 canvas, while the exported ONNX graph
    # (model.pt=False) gets the square 640x640 canvas.
    square = onnx.letterbox_spec(320, 240, 640, 640)
    rect = onnx.letterbox_spec(320, 240, 640, 640, auto=True, stride=32)
    assert (square.pad_top, square.pad_left) == (80, 0)
    assert (rect.pad_top, rect.pad_left) == (0, 0)
    assert rect.resized_height == 480 and square.resized_height == 480
    assert (square.canvas_height, square.canvas_width) == (640, 640)
    assert (rect.canvas_height, rect.canvas_width) == (480, 640)
    with pytest.raises(onnx.OnnxParityError):
        onnx.letterbox_spec(320, 240, 640, 640, auto=True, stride=32,
                            require_square=True)


def test_letterbox_roundtrip_point_and_bbox():
    spec = onnx.letterbox_spec(300, 240, 640, 640)
    point = (120.5, 33.25)
    model_point = spec.point_to_model(point)
    back = spec.point_from_model(model_point)
    assert back == pytest.approx(point)
    bbox = (10.0, 20.0, 30.0, 40.0)
    model_bbox = spec.bbox_to_model(bbox)
    assert spec.bbox_from_model(model_bbox) == pytest.approx(bbox)
    # the same mapping is used by evaltool's Letterbox dataclass
    lb = spec.as_evaltool_letterbox()
    assert yolo.point_to_model(point, lb) == pytest.approx(model_point)
    assert yolo.point_from_model(model_point, lb) == pytest.approx(point)


def test_letterbox_pixel_centres():
    spec = onnx.letterbox_spec(320, 240, 640, 640)
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[47:53, 97:103] = (255, 255, 255)
    canvas = onnx.letterbox_image(image, spec)
    ys, xs = np.where(canvas[:, :, 0] == 255)
    assert xs.size > 0
    cx = float(xs.mean()) + 0.5
    cy = float(ys.mean()) + 0.5
    assert (cx, cy) == pytest.approx((200.0, 180.0), abs=1.0)


def test_nms_keeps_highest_and_suppresses_overlap():
    rows = np.array([
        [100, 100, 20, 20, 0.90, 100, 100, 0.9],   # cx cy w h score kx ky kconf
        [101, 101, 20, 20, 0.80, 101, 101, 0.8],   # overlaps box 0 -> suppressed
        [300, 300, 20, 20, 0.70, 300, 300, 0.7],   # disjoint -> kept
    ], dtype=np.float32)
    kept = onnx.nms_rows(rows, conf_thres=0.25, iou_thres=0.7)
    assert len(kept) == 2
    assert kept[0][4] == pytest.approx(0.90)
    assert kept[1][4] == pytest.approx(0.70)


def test_nms_is_strict_above_conf_threshold():
    rows = np.array([
        [10, 10, 5, 5, 0.25, 10, 10, 0.25],
        [50, 50, 5, 5, 0.250001, 50, 50, 0.25],
    ], dtype=np.float32)
    kept = onnx.nms_rows(rows, conf_thres=0.25, iou_thres=0.7)
    assert len(kept) == 1
    assert kept[0][4] == pytest.approx(0.250001)


def test_nms_max_det_and_input_validation():
    rows = np.array([[10 + 20 * i, 10, 5, 5, 0.9 - 0.01 * i, 10, 10, 0.9]
                     for i in range(5)], dtype=np.float32)
    kept = onnx.nms_rows(rows, conf_thres=0.25, iou_thres=0.7, max_det=2)
    assert len(kept) == 2
    with pytest.raises(onnx.OnnxParityError):
        onnx.nms_rows(rows[:, :4], conf_thres=0.25, iou_thres=0.7)


def _decode_rows(rows, spec, tau_det=0.5):
    thresholds = yolo.merge_thresholds({'tau_det': tau_det, 'tau_margin': 0.1})
    return onnx.decode_pose_rows(
        rows, spec, image_width=spec.source_width,
        image_height=spec.source_height, intrinsics={'fx_px': 160.0, 'cx_px': 160.0},
        thresholds=thresholds, frame_id='f', image='f.png')


def test_raw_decode_claims_identity_after_nms():
    rows = np.array([
        [320, 320, 40, 40, 0.90, 330, 310, 0.9],
        [321, 321, 40, 40, 0.85, 331, 311, 0.8],
    ], dtype=np.float32)
    spec = onnx.letterbox_spec(320, 240, 640, 640)
    no_nms = _decode_rows(rows, spec, tau_det=0.5)
    assert no_nms['status'] == 'DETECTED'
    assert no_nms['reject_reason'] == 'MULTIPLE_CANDIDATES'
    assert no_nms['identity_claimed'] is False
    with_nms = _decode_rows(onnx.nms_rows(rows, 0.25, 0.7), spec, tau_det=0.5)
    assert with_nms['status'] == 'DETECTED'
    assert with_nms['reject_reason'] is None
    assert with_nms['identity_claimed'] is True
    assert with_nms['keypoint_px'] == pytest.approx([165.0, 115.0])


def test_pose_predictor_box_rounding_is_mirrored():
    # ultralytics PosePredictor.postprocess rounds boxes to integers in its
    # source domain (pred[:, :4] = scale_boxes(...).round()).  The raw path must
    # mirror that clip+round, otherwise a box 0.16 px inside the border is not
    # TRUNCATED here while both ultralytics paths report TRUNCATED (defect D3).
    spec = onnx.letterbox_spec(320, 240, 640, 640)
    # model-space box x2 = 639.68 -> source 319.84 without rounding
    rows = np.array([[580.86, 337.73, 117.62, 111.58, 0.95, 602.05, 296.19, 0.99]],
                    dtype=np.float32)
    rounded = _decode_rows(rows, spec, tau_det=0.5)
    assert rounded['status'] == 'DETECTED'
    assert rounded['truncated'] is True
    assert 'right' in rounded['truncated_edges']
    assert rounded['bbox_xywh'][0] + rounded['bbox_xywh'][2] == pytest.approx(320.0)
    unrounded = onnx.decode_pose_rows(
        rows, spec, image_width=320, image_height=240,
        intrinsics={'fx_px': 160.0, 'cx_px': 160.0},
        thresholds=yolo.merge_thresholds({'tau_det': 0.5}),
        frame_id='f', image='f.png', round_boxes=False)
    assert unrounded['truncated'] is False


def test_decode_below_threshold_is_not_detected():
    rows = np.array([[320, 320, 40, 40, 0.40, 330, 310, 0.9]], dtype=np.float32)
    spec = onnx.letterbox_spec(320, 240, 640, 640)
    observation = _decode_rows(onnx.nms_rows(rows, 0.01, 0.7), spec, tau_det=0.5)
    assert observation['status'] == 'NOT_DETECTED'


def test_observation_decision_and_diff():
    a = {'status': 'DETECTED', 'reference_status': 'VISIBLE',
         'identity_claimed': True, 'keypoint_px': [1.0, 2.0],
         'reject_reason': None}
    b = {'status': 'DETECTED', 'reference_status': 'UNAVAILABLE',
         'identity_claimed': False, 'keypoint_px': None,
         'reject_reason': 'REFERENCE_UNAVAILABLE'}
    da = onnx.observation_decision(a)
    db = onnx.observation_decision(b)
    diff = onnx.decision_diff(a, b)
    assert da['reference_available'] is True
    assert db['reference_available'] is False
    assert diff['changed'] is True
    assert diff['reference_flip'] is True
    assert diff['identity_flip'] is True


def test_match_detections_by_iou_and_keypoint_distance():
    left = [{'bbox_xywh': [10, 10, 20, 20], 'score': 0.9,
             'keypoint_px': [20, 20]}]
    right = [{'bbox_xywh': [11, 10, 20, 20], 'score': 0.9,
              'keypoint_px': [23, 20]}]
    pairs = onnx.match_detections(left, right, iou_thres=0.5)
    assert len(pairs) == 1
    assert pairs[0]['bbox_iou'] > 0.5
    assert pairs[0]['keypoint_distance_px'] == pytest.approx(3.0)
    assert onnx.match_detections(left, [], iou_thres=0.5) == []


def test_export_config_exists_and_is_relocatable():
    assert CONFIG.is_file(), 'missing configs/perception/landmark_export_v1.json'
    document = json.loads(CONFIG.read_text(encoding='utf-8'))
    assert document['schema_version'] == 'dsh.landmark_export.v1'
    assert document['export']['format'] == 'onnx'
    assert document['export']['opset'] == 18
    assert document['parity']['paths'] == ['pt_square', 'onnx_native_square',
                                           'raw_ort_square']
    for text in json.dumps(document).split('"'):
        assert not text.startswith(('E:', 'C:')), 'machine-private path in config'
        assert '\\\\isaac\\\\proj_boom_birds' not in text


@pytest.mark.parametrize('script', ['landmark_export_onnx.py',
                                    'landmark_onnx_parity.py',
                                    'landmark_train_cli.py'])
def test_versioned_cli_help_runs(script):
    path = REPO_ROOT / 'scripts' / script
    assert path.is_file(), 'missing versioned CLI ' + script
    completed = subprocess.run([sys.executable, str(path), '--help'],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert 'usage' in completed.stdout.lower()

VENV_PYTHON = REPO_ROOT / '.venv' / 'landmark-train' / 'Scripts' / 'python.exe'
PARITY_SCRIPT = REPO_ROOT / 'scripts' / 'landmark_onnx_parity.py'
FROZEN_ONNX = REPO_ROOT / 'outputs' / 'landmark_train' / 'runs' / 'onnx_trained_seed1' / 'last_opset18.onnx'
FROZEN_PT = REPO_ROOT / 'outputs' / 'landmark_train' / 'runs' / 'bounded_v2' / 'seed1' / 'bounded_1' / 'weights' / 'last.pt'


@pytest.mark.skipif(not VENV_PYTHON.is_file(), reason='isolated landmark-train venv not available')
@pytest.mark.skipif(not PARITY_SCRIPT.is_file(), reason='parity script not available')
@pytest.mark.skipif(not (FROZEN_ONNX.is_file() and FROZEN_PT.is_file()),
                    reason='frozen pt/onnx artifacts not available')
def test_parity_cli_end_to_end_on_two_frames(tmp_path):
    # Integration guard: the CLI actually runs in the isolated venv and returns
    # PARITY_PASS on a 2-frame val sample with the frozen .pt/.onnx artifacts.
    import os
    evidence = tmp_path / 'evidence.json'
    out_dir = tmp_path / 'run'
    command = [str(VENV_PYTHON), str(PARITY_SCRIPT),
               '--onnx', str(FROZEN_ONNX),
               '--val-frames', '2', '--final-frames', '0',
               '--synthetic-base', '0', '--near-threshold', '0',
               '--no-gpu-path', '--quiet',
               '--out-dir', str(out_dir),
               '--evidence-out', str(evidence), '--overwrite']
    environment = dict(os.environ)
    environment['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'
    environment['YOLO_AUTOINSTALL'] = 'false'
    completed = subprocess.run(command, capture_output=True, text=True,
                               timeout=600, encoding='utf-8',
                               errors='replace', env=environment,
                               cwd=str(REPO_ROOT))
    assert completed.returncode == 0, completed.stderr[-4000:]
    document = json.loads(evidence.read_text(encoding='utf-8'))
    assert document['status'] == 'PARITY_PASS'
    assert document['self_check']['passed'] is True
    assert document['pairwise']['pt_square_vs_onnx_native_square'][
        'observation_decision_flips'] == 0
