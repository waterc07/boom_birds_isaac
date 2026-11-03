"""Offline shadow consumer runner; reads only frozen sensor observations."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_consumer import LandmarkConsumer


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(
        Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--sensor-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    # Verify the frozen input record before consuming it.
    for name, digest in (freeze.get('input_hashes') or {}).items():
        path = Path(name)
        if not path.exists() or sha(path) != digest:
            raise RuntimeError('input hash mismatch: ' + name)
    manifest = load(args.sensor_dir / 'manifest.json')
    if not (args.sensor_dir / 'run.complete.json').exists() or (
            args.sensor_dir / 'summary.error.txt').exists():
        raise RuntimeError('sensor input did not complete cleanly')
    if manifest.get('freeze', {}).get('sha256') != freeze['input']['sensor_freeze_sha256']:
        raise RuntimeError('sensor freeze lineage mismatch')
    observations = load_jsonl(args.sensor_dir / 'observations.jsonl')
    rgb = [item for item in observations
           if item.get('sensor_key') == 'front_rgb']
    rgb.sort(key=lambda item: (item['header']['sync_generation'],
                               item['header']['sequence_id']))
    consumer = LandmarkConsumer(
        template_path=Path(freeze['algorithm']['template_path']),
        threshold=float(freeze['algorithm']['threshold']),
        allowed_age_ns=int(freeze['algorithm']['allowed_age_ns']),
        capture_interval_ns=int(freeze['algorithm']['capture_interval_ns']))
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as stream:
        for item in rgb:
            result = consumer.process(item)
            result['input_frame_id'] = item['payload']['ref'].split('/')[-1]
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            results.append(result)
    counts = {}
    reasons = {}
    generations = {}
    for result in results:
        counts[result['status']] = counts.get(result['status'], 0) + 1
        reasons[result['reason']] = reasons.get(result['reason'], 0) + 1
        gen = result['source']['generation']
        generations[gen] = generations.get(gen, 0) + 1
    summary = {
        'schema_version': 'dsh.landmark_consumer_run.v1',
        'shadow_only': True,
        'control_participation': 'NONE',
        'consumer_version': 'dsh.landmark_consumer.v1',
        'input_observations_sha256': sha(args.sensor_dir / 'observations.jsonl'),
        'freeze_sha256': sha(args.freeze),
        'processed_rgb_records': len(results),
        'status_counts': counts,
        'reason_counts': reasons,
        'generations': generations,
        'consumer_reset_count': consumer.reset_count,
        'results_sha256': sha(args.output / 'results.jsonl'),
        'time_semantics': {
            'capture_time_source': 'SIM_UPDATE_SAMPLE_TIME_LEGACY_V1',
            'exposure_time_status': 'UNKNOWN',
            'age_semantics': 'SIM_SAMPLE_TIME_NOT_FULL_LATENCY',
            'note': 'legacy v1 capture_host was taken after camera update; '
                    'it is not an exposure timestamp; full latency unknown',
        },
        'distance': 'UNAVAILABLE for arbitrary detection boxes',
    }
    (args.output / 'summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
