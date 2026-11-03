"""Run the frozen green+geometry consumer on the independent test set."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_consumer import LandmarkConsumer
from boom_birds.evaluation.tower_geometry import GreenGeometryDetector


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shadow', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    for name, digest in (freeze.get('input_hashes') or {}).items():
        if not Path(name).exists() or sha(name) != digest:
            raise RuntimeError('frozen input hash mismatch: ' + name)
    if not (args.run / 'run.complete.json').exists() or (
            args.run / 'summary.error.txt').exists():
        raise RuntimeError('test run did not complete cleanly')
    params = {k: freeze['algorithm'][k] for k in (
        'green_rgb', 'min_green_area', 'max_green_area', 'sat_min',
        'sat_val_min', 'min_sat_pixels', 'min_bbox_side',
        'min_edge_density', 'max_symmetry', 'max_anchor_top_fraction',
        'ambiguity_ratio')}
    detector = GreenGeometryDetector(**params)
    consumer = LandmarkConsumer(detector=detector)
    rows = [r for r in load_jsonl(args.shadow / 'observations.jsonl')
            if r.get('sensor_key') == 'front_rgb']
    rows.sort(key=lambda r: (r['header']['sync_generation'],
                             r['header']['sequence_id']))
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            result = consumer.process(row)
            result['input_frame_id'] = row['payload']['ref'].split('/')[-1]
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            results.append(result)
    summary = {
        'schema_version': 'dsh.geometry_test_run.v1',
        'shadow_only': True,
        'control_participation': 'NONE',
        'freeze_sha256': sha(args.freeze),
        'input_observations_sha256': sha(args.shadow / 'observations.jsonl'),
        'processed_rgb_records': len(results),
        'status_counts': {s: sum(1 for r in results if r['status'] == s)
                          for s in sorted({r['status'] for r in results})},
        'results_sha256': sha(args.output / 'results.jsonl'),
        'distance': 'UNAVAILABLE',
    }
    (args.output / 'summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
