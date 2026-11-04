"""Consumer-protocol evaluation CLI for the landmark experiment (read-only).

Modes:
- --predictions: evaluate already-saved predictions.jsonl (no ML backend);
- --model: run inference on development frames with ultralytics in the isolated
  .venv/landmark-train (never on the historical final, never for training) and
  evaluate the decoded observations;
- --appearance-gate: apply the image-only appearance gate to predicted boxes
  (features computed from the image, no GT position/filename/oracle);
- --parity-evidence: attach .pt/ONNX/raw-ORT decision-flip counts from an
  existing landmark_onnx parity evidence file.

Outputs consumer_metrics.json + rows.jsonl. The pre-registered protocol
(configs/perception/landmark_consumer_protocol_v1.json) is loaded and its sha is
recorded. Existing outputs are never overwritten without --overwrite.
"""
import argparse
import json
import os
from pathlib import Path
import sys

# Resource coordination: keep inference single-threaded unless the caller
# explicitly overrides it; honours the shared training resource budget.
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('NUMEXPR_NUM_THREADS', '1')

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_consumer_eval as ce  # noqa: E402
from boom_birds.evaluation import landmark_yolo as ly  # noqa: E402

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--protocol', type=Path,
                        default=REPO_ROOT / ce.DEFAULT_PROTOCOL_PATH)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, default=None)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument('--decisions', type=Path, default=None,
                        help='identity decisions JSON for identity batches')
    parser.add_argument('--images', type=Path, default=None)
    parser.add_argument('--split', default=None)
    parser.add_argument('--appearance-gate', action='store_true')
    parser.add_argument('--gate-thresholds', type=Path, default=None)
    parser.add_argument('--gate-mode', choices=('v1', 'v2'), default='v1')
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-px', type=float, default=3.0)
    parser.add_argument('--tau-conf', type=float, default=None)
    parser.add_argument('--redecode-thresholds', action='store_true',
                        help='re-decode saved observation candidates with the '
                             'given tau_det/tau_margin/tau_kpt (frozen protocol)')
    parser.add_argument('--identity-policy',
                        choices=ce.IDENTITY_POLICIES,
                        default='confirmed_only')
    parser.add_argument('--parity-evidence', type=Path, default=None)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--conf', type=float, default=0.01)
    parser.add_argument('--device', default='cpu',
                        help='inference device; default cpu (GPU coordination)')
    parser.add_argument('--tau-det', type=float, default=ly.DEFAULT_THRESHOLDS['tau_det'])
    parser.add_argument('--tau-margin', type=float, default=ly.DEFAULT_THRESHOLDS['tau_margin'])
    parser.add_argument('--tau-kpt', type=float, default=ly.DEFAULT_THRESHOLDS['tau_kpt'])
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def _resolve_image(images_dir, truth):
    return ce._resolve_image(images_dir, truth)


def _infer_predictions(model_path, frames, args, gate_enabled):
    try:
        from PIL import Image
        import numpy as np
        from ultralytics import YOLO
    except ImportError as error:  # pragma: no cover - environment dependent
        raise ce.ConsumerEvalError(
            'ultralytics/numpy/PIL are required for --model; run inside '
            '.venv/landmark-train: %r' % (error,))
    try:
        import torch
        torch.set_num_threads(int(os.environ.get('TORCH_NUM_THREADS', '1')))
    except ImportError:
        pass
    model = YOLO(str(model_path))
    thresholds = {'tau_det': args.tau_det, 'tau_margin': args.tau_margin,
                  'tau_kpt': args.tau_kpt}
    predictions = {}
    missing = 0
    for truth in frames:
        frame_id = truth['frame_id']
        image_path = _resolve_image(args.images, truth)
        if image_path is None:
            missing += 1
            predictions[frame_id] = {
                'status': 'UNKNOWN', 'landmark_id': None, 'bbox_xywh': None,
                'score': None, 'keypoint_px': None,
                'reject_reason': 'MISSING_IMAGE', 'candidate_count': 0}
            continue
        results = model.predict(source=str(image_path), imgsz=args.imgsz,
                                conf=args.conf, device=args.device,
                                verbose=False)
        observation = ly.decode_ultralytics_result(
            results[0], image_width=truth['image_width'],
            image_height=truth['image_height'], intrinsics=truth['intrinsics'],
            thresholds=thresholds, frame_id=frame_id, image=str(image_path))
        prediction = ly.observation_to_metric_prediction(observation)
        prediction['candidate_count'] = observation.get('candidate_count', 1)
        if gate_enabled:
            with Image.open(image_path) as image:
                rgb = np.asarray(image.convert('RGB'))
            if prediction.get('bbox_xywh'):
                features = ce.appearance_features(
                    rgb, prediction['bbox_xywh'])
                features['keypoint_emitted'] = (
                    prediction.get('keypoint_px') is not None)
                prediction['appearance_features'] = features
        predictions[frame_id] = prediction
    return predictions, missing


def main(argv=None):
    args = parse_args(argv)
    if (args.predictions is None) == (args.model is None):
        print('exactly one of --predictions or --model is required', file=sys.stderr)
        return EXIT_INVALID_INPUT
    if args.model is not None and args.images is None:
        print('--images is required with --model', file=sys.stderr)
        return EXIT_INVALID_INPUT
    output_dir = Path(args.output_dir)
    metrics_path = output_dir / 'consumer_metrics.json'
    if metrics_path.exists() and not args.overwrite:
        print('refusing to overwrite ' + str(metrics_path) + '; pass --overwrite '
              'only for a deliberate new evaluation', file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    try:
        protocol = ce.load_protocol(args.protocol)
        protocol['thresholds']['tau_iou_diagnostic'] = args.tau_iou
        frames, meta = ce.build_frames(args.labels, args.decisions,
                                       split=args.split)
        gate = None
        if args.appearance_gate:
            thresholds = None
            if args.gate_thresholds is not None:
                thresholds = json.loads(
                    Path(args.gate_thresholds).read_text(encoding='utf-8'))
            if args.gate_mode == 'v2':
                gate = ce.make_appearance_gate_v2(thresholds)
            else:
                gate = ce.make_appearance_gate(thresholds)
        if args.predictions is not None:
            if args.redecode_thresholds:
                records = [json.loads(line) for line in
                           args.predictions.read_text(encoding='utf-8').splitlines()
                           if line.strip()]
                frames_by_id = {truth['frame_id']: truth for truth in frames}
                predictions = ce.redecode_predictions(
                    records, frames_by_id, tau_det=args.tau_det,
                    tau_margin=args.tau_margin, tau_kpt=args.tau_kpt)
            else:
                predictions = ce.load_predictions(args.predictions)
            missing = sum(1 for truth in frames
                          if truth['frame_id'] not in predictions)
        else:
            predictions, missing = _infer_predictions(
                args.model, frames, args, gate is not None)
        rows = []
        for truth in frames:
            prediction = predictions.get(truth['frame_id'])
            if prediction is None:
                prediction = {'status': 'UNKNOWN', 'landmark_id': None,
                              'bbox_xywh': None, 'score': None,
                              'keypoint_px': None,
                              'reject_reason': 'MISSING_PREDICTION',
                              'candidate_count': 0}
            features = prediction.get('appearance_features')
            if features is None and gate is not None and args.images is not None:
                image_path = _resolve_image(args.images, truth)
                if image_path is not None:
                    from PIL import Image
                    import numpy as np
                    with Image.open(image_path) as image:
                        rgb = np.asarray(image.convert('RGB'))
                    box = prediction.get('bbox_xywh') or truth.get('gt_bbox')
                    if box:
                        features = ce.appearance_features(rgb, box)
                        features['keypoint_emitted'] = (
                            prediction.get('keypoint_px') is not None)
            rows.append(ce.evaluate_frame(
                prediction, truth, protocol, gate=gate,
                appearance_features=features,
                identity_policy=args.identity_policy))
        summary = ce.summarize_consumer(rows, protocol=protocol,
                                        identity_policy=args.identity_policy)
        summary['inputs'] = dict(
            meta,
            predictions=(str(args.predictions) if args.predictions else None),
            predictions_sha256=(ce._sha256_file(args.predictions)
                                if args.predictions else None),
            model=(str(args.model) if args.model else None),
            model_sha256=(ce._sha256_file(args.model) if args.model else None),
            missing_predictions=missing,
            gate_enabled=gate is not None,
            identity_policy=args.identity_policy,
            thresholds_recorded={
                'tau_iou': args.tau_iou, 'tau_px': args.tau_px,
                'tau_conf': args.tau_conf, 'tau_det': args.tau_det,
                'tau_margin': args.tau_margin, 'tau_kpt': args.tau_kpt,
                'source': 'landmark_model_freeze_v1 (frozen; NOT retuned on '
                          'the 3-seed val)',
                'redecode_thresholds': args.redecode_thresholds,
            },
            gate_thresholds=(gate(None)['thresholds'] if gate else None),
        )
        if args.parity_evidence is not None:
            summary['onnx_parity'] = ce.parse_parity_evidence(args.parity_evidence)
        output_dir.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False)
                                + '\n', encoding='utf-8')
        with (output_dir / 'rows.jsonl').open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        if args.model is not None:
            with (output_dir / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
                for truth in frames:
                    prediction = predictions.get(truth['frame_id'])
                    if prediction is None:
                        continue
                    record = dict(prediction)
                    record['frame_id'] = truth['frame_id']
                    record.pop('appearance_features', None)
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(json.dumps({
            'status': 'OK',
            'frames': summary['counts']['frames'],
            'all_positive': summary['counts']['all_positive'],
            'observable_positive': summary['counts']['observable_positive'],
            'reference_available': summary['counts']['reference_available'],
            'success_all_positive': summary['domains']['all_positive']['success_rate'],
            'success_observable': summary['domains']['observable_positive']['success_rate'],
            'bearing_median_deg': summary['bearing']['median_deg'],
            'bearing_p90_deg': summary['bearing']['p90_deg'],
            'bearing_n': summary['bearing']['count'],
            'wrong_claims': summary['identity']['wrong_claims'],
            'output_dir': str(output_dir),
        }, ensure_ascii=False))
        return EXIT_OK
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except (ce.ConsumerEvalError, ValueError, KeyError,
            json.JSONDecodeError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT


if __name__ == '__main__':
    raise SystemExit(main())