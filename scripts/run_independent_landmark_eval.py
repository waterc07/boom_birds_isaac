"""Run baseline or improved landmark consumer on the independent dataset."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_consumer import LandmarkConsumer
from boom_birds.evaluation.landmark_improved import MultiViewAnchorDetector


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def consumer_for(freeze, method):
    algorithm = freeze['algorithms'][method]
    if method == 'baseline':
        return LandmarkConsumer(template_path=Path(algorithm['template_path']),
                                threshold=float(algorithm['threshold']),
                                allowed_age_ns=int(algorithm['allowed_age_ns']))
    detector = MultiViewAnchorDetector(
        Path(algorithm['templates_meta']),
        threshold=float(algorithm['threshold']),
        scales=tuple(algorithm['scales']))
    return LandmarkConsumer(detector=detector,
                            allowed_age_ns=int(algorithm['allowed_age_ns']))


def run_dataset(consumer, run_dir, shadow_dir, dataset, output_rows):
    manifest = load(run_dir / 'manifest.json')
    if not (run_dir / 'run.complete.json').exists() or (
            run_dir / 'summary.error.txt').exists():
        raise RuntimeError('run incomplete: ' + str(run_dir))
    rows = [r for r in load_jsonl(shadow_dir / 'observations.jsonl')
            if r.get('sensor_key') == 'front_rgb']
    rows.sort(key=lambda r: (r['header']['sync_generation'],
                             r['header']['sequence_id']))
    for row in rows:
        result = consumer.process(row)
        result['dataset'] = dataset
        result['input_frame_id'] = row['payload']['ref'].split('/')[-1]
        result['input_run'] = str(run_dir)
        output_rows.append(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--method', choices=('baseline', 'improved'), required=True)
    parser.add_argument('--final-run', type=Path, required=True)
    parser.add_argument('--final-shadow', type=Path, required=True)
    parser.add_argument('--pilot-run', type=Path, required=True)
    parser.add_argument('--pilot-shadow', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    for name, digest in (freeze.get('input_hashes') or {}).items():
        if not Path(name).exists() or sha(name) != digest:
            raise RuntimeError('frozen input hash mismatch: ' + name)
    rows = []
    final_consumer = consumer_for(freeze, args.method)
    pilot_consumer = consumer_for(freeze, args.method)
    run_dataset(final_consumer, args.final_run, args.final_shadow, 'final', rows)
    run_dataset(pilot_consumer, args.pilot_run, args.pilot_shadow, 'pilot_dev', rows)
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / 'results.jsonl'
    with result_path.open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    counts = {}
    for row in rows:
        key = (row['dataset'], row['status'])
        counts[str(key)] = counts.get(str(key), 0) + 1
    summary = {
        'schema_version': 'dsh.independent_landmark_run.v1',
        'method': args.method,
        'shadow_only': True,
        'control_participation': 'NONE',
        'freeze_sha256': sha(args.freeze),
        'inputs': {
            'final_observations': sha(args.final_shadow / 'observations.jsonl'),
            'pilot_observations': sha(args.pilot_shadow / 'observations.jsonl'),
        },
        'result_count': len(rows),
        'status_counts': counts,
        'results_sha256': sha(result_path),
        'distance': 'UNAVAILABLE for arbitrary detection boxes',
    }
    (args.output / 'summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
