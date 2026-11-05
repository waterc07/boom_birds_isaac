"""Two-class landmark consumer evaluation CLI (read-only over predictions).

Modes:
- --predictions: saved two-class predictions.jsonl (records with detections /
  landmark_id); single-class metric predictions are adapted as class-0 only;
- --model: development-frame inference with an ultralytics two-class model in the
  isolated .venv/landmark-train (CPU by default; never training/final);
- --baseline-predictions: frozen single-class v2 predictions for the same
  definitions/denominators (same-frame/class1 recall will be 0 by construction).

Outputs two_class_metrics.json + rows.jsonl (and predictions.jsonl in model mode).
The pre-registered two-class protocol is loaded and its sha recorded.
"""
import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_two_class_eval as tc  # noqa: E402

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--protocol', type=Path,
                        default=REPO_ROOT / tc.DEFAULT_PROTOCOL_PATH)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, default=None)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument('--images', type=Path, default=None)
    parser.add_argument('--baseline-predictions', type=Path, default=None)
    parser.add_argument('--baseline-policy', default='raw_claim_upper_bound',
                        choices=tc.IDENTITY_POLICIES)
    parser.add_argument('--identity-policy', default='confirmed_only',
                        choices=tc.IDENTITY_POLICIES)
    parser.add_argument('--split', default=None)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--conf', type=float, default=0.01)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--tau-det', type=float, default=None)
    parser.add_argument('--tau-margin', type=float, default=None)
    parser.add_argument('--tau-kpt', type=float, default=None)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-bearing-deg', type=float, default=None)
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def _resolve_image(images_dir, truth_row):
    images_dir = Path(images_dir)
    candidates = [images_dir / Path(truth_row['image']).name,
                  images_dir / truth_row['image'],
                  images_dir / truth_row['frame_id']]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _normalise_prediction_record(record):
    if 'detections' in record:
        return record
    if record.get('observation') is not None:
        record = record['observation']
    if 'detections' in record:
        return record
    adapted = tc.single_class_predictions_to_observations(
        {record.get('frame_id', 'frame'): record})
    return next(iter(adapted.values()))


def _run_model(args, truth_rows):
    try:
        from ultralytics import YOLO
    except ImportError as error:  # pragma: no cover
        raise tc.TwoClassEvalError(
            'ultralytics is required for --model; run inside '
            '.venv/landmark-train: %r' % (error,))
    model = YOLO(str(args.model))
    thresholds = {}
    for key, value in (('tau_det', args.tau_det), ('tau_margin', args.tau_margin),
                       ('tau_kpt', args.tau_kpt), ('tau_iou', args.tau_iou),
                       ('tau_bearing_deg', args.tau_bearing_deg)):
        if value is not None:
            thresholds[key] = value
    protocol = tc.load_protocol(args.protocol)
    return tc.infer_observations(model, truth_rows, args.images, protocol,
                                 thresholds=thresholds or None,
                                 imgsz=args.imgsz, device=args.device,
                                 conf=args.conf)


def main(argv=None):
    args = parse_args(argv)
    if (args.predictions is None) == (args.model is None):
        print('exactly one of --predictions or --model is required', file=sys.stderr)
        return EXIT_INVALID_INPUT
    if args.model is not None and args.images is None:
        print('--images is required with --model', file=sys.stderr)
        return EXIT_INVALID_INPUT
    output_dir = Path(args.output_dir)
    metrics_path = output_dir / 'two_class_metrics.json'
    if metrics_path.exists() and not args.overwrite:
        print('refusing to overwrite ' + str(metrics_path), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    try:
        protocol = tc.load_protocol(args.protocol)
        _document, truth_rows = tc.load_two_class_labels(args.labels)
        if args.model is not None:
            observations = _run_model(args, truth_rows)
        else:
            raw = tc.load_predictions(args.predictions)
            observations = {frame_id: _normalise_prediction_record(record)
                            for frame_id, record in raw.items()}
        result = tc.evaluate_rows(truth_rows, observations, protocol,
                                  identity_policy=args.identity_policy)
        summary = result['summary']
        if args.baseline_predictions is not None:
            baseline_raw = tc.load_predictions(args.baseline_predictions)
            baseline_obs = {frame_id: _normalise_prediction_record(record)
                            for frame_id, record in baseline_raw.items()}
            baseline = tc.evaluate_rows(truth_rows, baseline_obs, protocol,
                                        identity_policy=args.baseline_policy)
            summary['baseline_comparison'] = tc.compare_summaries(
                baseline['summary'], summary)
        summary['inputs'] = {
            'labels': str(args.labels),
            'labels_sha256': tc._sha256_file(args.labels),
            'predictions': str(args.predictions) if args.predictions else None,
            'predictions_sha256': (tc._sha256_file(args.predictions)
                                   if args.predictions else None),
            'model': str(args.model) if args.model else None,
            'model_sha256': (tc._sha256_file(args.model) if args.model else None),
            'baseline_predictions': (str(args.baseline_predictions)
                                     if args.baseline_predictions else None),
            'identity_policy': args.identity_policy,
            'thresholds': {key: value for key, value in summary['protocol'].items()
                           if key in ('tau_bearing_deg',)},
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False)
                                + '\n', encoding='utf-8')
        with (output_dir / 'rows.jsonl').open('w', encoding='utf-8') as stream:
            for row in result['rows']:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        if args.model is not None:
            with (output_dir / 'predictions.jsonl').open('w', encoding='utf-8') as stream:
                for frame_id, observation in observations.items():
                    record = dict(observation)
                    record['frame_id'] = frame_id
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(json.dumps({
            'status': 'OK',
            'frames': summary['counts']['frames'],
            'tower_class_recall': summary['tower_class_recall'],
            'ms1_class_recall': summary['classes']['1']['recall'],
            'identity_claims': summary['identity']['claims'],
            'wrong_claims': summary['identity']['wrong_claims'],
            'same_frame_rate': summary['same_frame']['tower_selection_rate'],
            'bearing_median_deg': summary['reference']['bearing']['median_deg'],
            'bearing_n': summary['reference']['bearing']['count'],
            'success_all_positive': summary['domains']['all_positive']['success_rate'],
            'output_dir': str(output_dir),
        }, ensure_ascii=False))
        return EXIT_OK
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except (tc.TwoClassEvalError, ValueError, KeyError,
            json.JSONDecodeError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT


if __name__ == '__main__':
    raise SystemExit(main())