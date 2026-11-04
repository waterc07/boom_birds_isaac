"""Stratified evaluation entry point for the bounded landmark YOLO experiment.

Runs a trained model (or precomputed predictions) over an annotation document and
writes predictions.jsonl + metrics.json with explicit numerators/denominators.

The metrics layer implements the corrected denominator audit: prediction-side
UNKNOWN/REJECTED on GT-observable positives stays in the recall/coverage/joint
denominators, annotation-side GT_UNOBSERVABLE frames are excluded and reported
separately, and GT reference-unavailable positives never enter the anchor/
bearing error denominators.

No Isaac dependency.  The ML backends (ultralytics / onnxruntime) are optional
imports: the script can always evaluate precomputed --predictions, and reports a
clear error when a requested backend is missing.  It never tunes thresholds,
never writes labels and refuses to overwrite a previous metrics.json unless
--overwrite is passed (one final read, no post-final rerun).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_yolo as yolo  # noqa: E402
from boom_birds.evaluation.landmark_metrics import (  # noqa: E402
    evaluate_frame,
    stratified_summary,
)

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3

STRATA_DIMENSIONS = ('family', 'group_id', 'visibility', 'scale',
                     'negative_type', 'truncation')

LIMITATIONS = [
    'annotation-side GT_UNOBSERVABLE (undecidable / fully occluded without a '
    'visible box / ambiguous) is excluded from the presence fourfold and every '
    'denominator and reported separately; it is NOT a model failure',
    'prediction-side UNKNOWN/REJECTED on GT-observable positives counts as a '
    'miss and is additionally listed by status and reject reason',
    'anchor/bearing errors are image-domain quantities: 1 px is about 0.358 deg '
    'at fx=160 px for the 320x240 front camera; they are not world bearings, '
    'not ranges, and not ToF measurements',
    'bbox IoU is a diagnostic (tau=0.3 is loose relative to the 0.649 blind '
    're-annotation IoU) and is not part of the primary joint decision',
    'a single-landmark experiment without similar-structure negatives cannot '
    'claim identity is evaluated',
    'agent-proxy annotations are not expert or human independent review',
    'no board deployment, navigation or Gate conclusion may be drawn here',
]


class BackendUnavailable(RuntimeError):
    """Raised when the requested inference backend is not installed."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8')
            .splitlines() if line.strip()]


def image_size(path):
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def resolve_image(images_dir, annotation):
    if images_dir is None:
        return None
    candidates = []
    image_field = annotation.get('image')
    if image_field:
        candidates.append(Path(images_dir) / Path(image_field).name)
        candidates.append(Path(images_dir) / image_field)
    candidates.append(Path(images_dir) / annotation['frame_id'])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_evaluation_frames(document, *, split, images_dir):
    """Convert annotation items into metric inputs, keeping excluded frames."""
    annotations = document.get('annotations')
    if not isinstance(annotations, list):
        raise ValueError('annotation document has no annotations list')
    frames = []
    skipped_split = 0
    for annotation in annotations:
        source = annotation.get('source') or {}
        if split is not None and source.get('split') != split:
            skipped_split += 1
            continue
        gt, reference_px, strata = yolo.ground_truth_from_annotation(annotation)
        path = resolve_image(images_dir, annotation)
        intrinsics = yolo.pixel_basis_from_annotation(annotation)
        width = annotation.get('image_width')
        height = annotation.get('image_height')
        if path is not None and (width is None or height is None):
            width, height = image_size(path)
        frames.append({'annotation': annotation, 'gt': gt,
                       'reference_px': reference_px, 'strata': strata,
                       'intrinsics': intrinsics, 'image_path': path,
                       'image_width': width, 'image_height': height})
    return frames, skipped_split


def _prediction_from_row(row):
    if row.get('observation') is not None:
        return yolo.observation_to_metric_prediction(row['observation'])
    return {
        'status': row.get('status', 'UNKNOWN'),
        'landmark_id': row.get('landmark_id'),
        'bbox_xywh': row.get('bbox_xywh'),
        'score': row.get('score'),
        'keypoint_px': row.get('keypoint_px'),
        'reject_reason': row.get('reject_reason'),
    }


def run_ultralytics_backend(model_path, frames, thresholds, imgsz):
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise BackendUnavailable(
            'ultralytics is not installed in this interpreter; run the '
            'evaluation inside .venv/landmark-train (record the version) or '
            'pass --predictions. Original error: %r' % (error,))
    model = YOLO(str(model_path))
    records = []
    for frame in frames:
        if frame['image_path'] is None:
            records.append(yolo.unknown_observation(
                frame_id=frame['gt']['frame_id'], reason='MISSING_IMAGE',
                thresholds=thresholds))
            continue
        results = model.predict(source=str(frame['image_path']),
                                imgsz=imgsz, conf=0.01, verbose=False)
        record = yolo.decode_ultralytics_result(
            results[0], image_width=frame['image_width'],
            image_height=frame['image_height'],
            intrinsics=frame['intrinsics'], thresholds=thresholds,
            frame_id=frame['gt']['frame_id'],
            image=str(frame['image_path']))
        records.append(record)
    return records


def run_onnx_backend(model_path, frames, thresholds, imgsz):
    try:
        import numpy as np
        import onnxruntime
    except ImportError as error:
        raise BackendUnavailable(
            'onnxruntime (and numpy) are required for --model *.onnx; install '
            'them in .venv/landmark-train (record the version) or pass '
            '--predictions. Original error: %r' % (error,))
    from PIL import Image
    session = onnxruntime.InferenceSession(str(model_path))
    input_name = session.get_inputs()[0].name
    records = []
    for frame in frames:
        if frame['image_path'] is None:
            records.append(yolo.unknown_observation(
                frame_id=frame['gt']['frame_id'], reason='MISSING_IMAGE',
                thresholds=thresholds))
            continue
        width, height = frame['image_width'], frame['image_height']
        letterbox = yolo.letterbox_params(width, height, imgsz, imgsz)
        image = Image.open(frame['image_path']).convert('RGB')
        scale = letterbox.scale
        resized = image.resize((max(1, int(round(width * scale))),
                                max(1, int(round(height * scale)))))
        canvas = Image.new('RGB', (imgsz, imgsz), (114, 114, 114))
        canvas.paste(resized, (int(round(letterbox.pad_x)),
                               int(round(letterbox.pad_y))))
        array = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)
        array = np.expand_dims(array / 255.0, 0)
        output = session.run(None, {input_name: array})[0]
        record = yolo.decode_onnx_pose_output(
            output, image_width=width, image_height=height, letterbox=letterbox,
            intrinsics=frame['intrinsics'], thresholds=thresholds,
            frame_id=frame['gt']['frame_id'],
            image=str(frame['image_path']))
        records.append(record)
    return records


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True,
                        help='v2/v2.1 annotation document JSON (ground truth)')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--split', default=None,
                        help="filter source.split, e.g. val / train / test")
    parser.add_argument('--images', type=Path, default=None,
                        help='image directory (required with --model)')
    parser.add_argument('--model', type=Path, default=None,
                        help='.pt (ultralytics) or .onnx (onnxruntime) model')
    parser.add_argument('--predictions', type=Path, default=None,
                        help='precomputed predictions.jsonl (no ML backend)')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-px', type=float, default=3.0)
    parser.add_argument('--tau-conf', type=float, default=0.5)
    parser.add_argument('--tau-det', type=float, default=0.25)
    parser.add_argument('--tau-margin', type=float, default=0.10)
    parser.add_argument('--tau-kpt', type=float, default=0.50)
    parser.add_argument('--overwrite', action='store_true',
                        help='allow overwriting an existing metrics.json '
                             '(disabled by default to prevent post-final reruns)')
    return parser.parse_args(argv)


def evaluate(args):
    if args.model is None and args.predictions is None:
        raise ValueError('one of --model or --predictions is required')
    if args.model is not None and args.images is None:
        raise ValueError('--images is required with --model')
    output_dir = Path(args.output_dir)
    metrics_path = output_dir / 'metrics.json'
    if metrics_path.exists() and not args.overwrite:
        raise FileExistsError(
            'refusing to overwrite existing ' + str(metrics_path)
            + '; a final evaluation must be read once. Pass --overwrite only '
              'for a deliberate new run with a new pre-registration.')

    thresholds = {
        'tau_iou': args.tau_iou, 'tau_px': args.tau_px, 'tau_conf': args.tau_conf,
        'tau_det': args.tau_det, 'tau_margin': args.tau_margin,
        'tau_kpt': args.tau_kpt,
    }
    decode_thresholds = yolo.merge_thresholds({
        'tau_det': args.tau_det, 'tau_margin': args.tau_margin,
        'tau_kpt': args.tau_kpt,
    })
    document = load_json(args.labels)
    frames, skipped_split = build_evaluation_frames(
        document, split=args.split,
        images_dir=Path(args.images) if args.images else None)

    observations = {}
    predictions = {}
    if args.predictions is not None:
        for row in load_jsonl(args.predictions):
            if 'observation' in row:
                observations[row['frame_id']] = row['observation']
            elif 'prediction' in row:
                predictions[row['frame_id']] = _prediction_from_row(
                    {'observation': row['prediction']})
            else:
                predictions[row['frame_id']] = _prediction_from_row(row)
    else:
        model_path = Path(args.model)
        if model_path.suffix.lower() == '.onnx':
            records = run_onnx_backend(model_path, frames, decode_thresholds,
                                       args.imgsz)
        elif model_path.suffix.lower() in ('.pt', '.pth'):
            records = run_ultralytics_backend(model_path, frames,
                                              decode_thresholds, args.imgsz)
        else:
            raise ValueError('unsupported model suffix: ' + model_path.suffix)
        observations = {record['frame_id']: record for record in records}

    frame_ids = {frame['gt']['frame_id'] for frame in frames}
    predictions_without_gt = [frame_id for frame_id in
                              set(observations) | set(predictions)
                              if frame_id not in frame_ids]
    rows = []
    output_rows = []
    missing_images = 0
    missing_predictions = 0
    for frame in frames:
        frame_id = frame['gt']['frame_id']
        if frame['image_path'] is None:
            missing_images += 1
        observation = observations.get(frame_id)
        prediction = predictions.get(frame_id)
        if observation is not None:
            prediction = yolo.observation_to_metric_prediction(observation)
        if prediction is None:
            missing_predictions += 1
            observation = yolo.unknown_observation(
                frame_id=frame_id, reason='MISSING_PREDICTION',
                thresholds=decode_thresholds,
                image=(str(frame['image_path'])
                       if frame['image_path'] is not None else None))
            prediction = yolo.observation_to_metric_prediction(observation)
        intrinsics = frame['intrinsics'] or {}
        row = evaluate_frame(
            frame['gt'], prediction,
            tau_iou=args.tau_iou, reference_px=frame['reference_px'],
            tau_px=args.tau_px, tau_conf=args.tau_conf,
            fx_px=intrinsics.get('fx_px'), cx_px=intrinsics.get('cx_px'),
            strata=frame['strata'])
        rows.append(row)
        output_rows.append({
            'frame_id': frame_id,
            'gt_frame_id': frame_id,
            'image': (str(frame['image_path'])
                      if frame['image_path'] is not None else None),
            'observation': observation,
            'prediction': prediction,
            'strata': frame['strata'],
            'presence_class': row['presence_class'],
            'reference_class': row['reference_class'],
            'joint_evaluable': row['joint_evaluable'],
            'joint_ok': row['joint_ok'],
            'joint_fail_reason': row['joint_fail_reason'],
        })

    report = stratified_summary(rows, STRATA_DIMENSIONS)
    overall = report['overall']
    counts = {
        'label_frames': len(document.get('annotations') or []),
        'split_frames': len(frames),
        'skipped_by_split': skipped_split,
        'evaluated_frames': len(rows),
        'missing_images': missing_images,
        'missing_predictions': missing_predictions,
        'predictions_without_gt': len(predictions_without_gt),
    }
    inputs = {
        'labels': str(args.labels),
        'labels_sha256': sha256(args.labels),
        'split': args.split,
        'images': str(args.images) if args.images else None,
        'model': str(args.model) if args.model else None,
        'model_sha256': (sha256(args.model) if args.model else None),
        'predictions': (str(args.predictions) if args.predictions else None),
        'predictions_sha256': (sha256(args.predictions)
                               if args.predictions else None),
    }
    metrics = {
        'schema_version': 'dsh.landmark_yolo_eval.v1',
        'status': overall['metric_status'],
        'split': args.split,
        'inputs': inputs,
        'counts': counts,
        'thresholds': {
            'values': thresholds,
            'status': 'PROPOSED_NOT_FROZEN',
            'freeze_rule': 'tau_conf/tau_px/tau_iou must be frozen on the '
                           'validation set before any final read; this script '
                           'never changes thresholds or labels',
        },
        'overall': overall,
        'strata': report['strata'],
        'worst_conditions': report['worst_conditions'],
        'limitations': LIMITATIONS,
        'denominator_audit': {
            'prediction_unknown_rejected_on_positive': (
                overall['presence']['unknown_rejected']['on_positive']),
            'gt_unobservable': overall['denominators']['gt_unobservable'],
            'gt_unobservable_by_reason': overall['gt_unobservable_by_reason'],
            'note': 'GT_UNOBSERVABLE (annotation state) and prediction UNKNOWN '
                    '(model state) are separate buckets and are never merged',
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
        for output_row in output_rows:
            stream.write(json.dumps(output_row, ensure_ascii=False) + '\n')
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False)
                            + '\n', encoding='utf-8')
    print(json.dumps({
        'status': metrics['status'],
        'frames': counts['evaluated_frames'],
        'positives': overall['denominators']['positives'],
        'negatives': overall['denominators']['negatives'],
        'gt_unobservable': overall['denominators']['gt_unobservable'],
        'recall': overall['presence']['recall'],
        'joint_narrow_rate': overall['joint']['narrow_rate'],
        'output_dir': str(output_dir),
    }, ensure_ascii=False))
    return EXIT_OK


def main(argv=None):
    args = parse_args(argv)
    try:
        return evaluate(args)
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except BackendUnavailable as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID_INPUT
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT


if __name__ == '__main__':
    raise SystemExit(main())