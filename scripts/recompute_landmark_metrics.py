"""Recompute landmark metrics + the four-way evaluation-definition audit.

Read-only over already-saved predictions.jsonl + v2/v2.1 labels: no model
inference, no training, no Isaac dependency, no rewriting of historical final
outputs.  The recompute writes a fresh output directory containing:

- metrics.json: the existing landmark_metrics.summarize() result (so the old
  denominators can be cross-checked against the saved historical file);
- audit.json: the four-way audit (presence / identity / reference availability /
  localization), explicit joint branches (localization vs correct UNAVAILABLE
  declaration), GT_UNOBSERVABLE accounting, denominator-loss audit and the
  historical-3px vs consumer-bearing split.

Exit codes: 0 ok, 2 invalid input, 3 refusing to overwrite an existing output.
"""
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_eval_definitions as audit  # noqa: E402

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, required=True,
                        help='saved predictions.jsonl (read only)')
    parser.add_argument('--labels', type=Path, required=True,
                        help='v2/v2.1 annotation document used as ground truth')
    parser.add_argument('--split', default=None,
                        help='filter source.split, e.g. test / val / train')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--tau-px', type=float, default=3.0)
    parser.add_argument('--tau-conf', type=float, default=0.605476)
    parser.add_argument('--px-tolerance', type=float, default=3.0,
                        help='historical 2D placement tolerance (legacy proxy)')
    parser.add_argument('--drop-missing-predictions', action='store_true',
                        help='only score label frames that have a saved '
                             'prediction (dataset-scope reproduction); dropped '
                             'frames are recorded in inputs')
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        result = audit.recompute(
            args.predictions, args.labels, split=args.split,
            output_dir=args.output_dir, tau_iou=args.tau_iou,
            tau_px=args.tau_px, tau_conf=args.tau_conf,
            px_tolerance=args.px_tolerance, overwrite=args.overwrite,
            drop_missing_predictions=args.drop_missing_predictions)
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT
    metrics = result['metrics']
    report = result['audit']
    summary = {
        'status': metrics['metric_status'],
        'frames': report['denominator_loss_audit']['frames']['total'],
        'positives': report['presence']['denominators']['positives'],
        'negatives': report['presence']['denominators']['negatives'],
        'presence': {'tp': report['presence']['tp'],
                     'fp': report['presence']['fp'],
                     'fn': report['presence']['fn'],
                     'tn': report['presence']['tn']},
        'reference_availability': report['reference_availability']['denominators'],
        'localization': report['localization']['denominators'],
        'localization_within_tolerance': report['localization']['within_tolerance'],
        'joint': {'tp': report['joint']['narrow_tp'],
                  'denominator': report['joint']['narrow_denominator'],
                  'availability_branch_ok': report['joint']['branches']['availability']['ok']},
        'gt_unobservable': report['gt_unobservable']['frames'],
        'px_vs_bearing_flips': report['placement']['verdict_flips'],
        'output_dir': str(args.output_dir),
        'audit_schema': audit.AUDIT_SCHEMA,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return EXIT_OK


if __name__ == '__main__':
    raise SystemExit(main())