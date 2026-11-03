"""Independent landmark-consumer evaluation and provenance verifier."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


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
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shadow', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    labels_doc = load(args.labels)
    results = load_jsonl(args.results / 'results.jsonl')
    summary = load(args.results / 'summary.json')
    manifest = load(args.run / 'manifest.json')
    observations = load_jsonl(args.shadow / 'observations.jsonl')
    by_frame = {item['payload']['ref'].split('/')[-1]: item
                for item in observations
                if item.get('sensor_key') == 'front_rgb'}
    result_by_frame = {item['input_frame_id']: item for item in results}
    checks = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    failures = []
    # -- freeze/source/input -------------------------------------------------
    check('data_integrity', 'freeze_sha',
          summary.get('freeze_sha256') == sha(args.freeze),
          'summary freeze hash')
    for name, digest in (freeze.get('input_hashes') or {}).items():
        check('data_integrity', 'input_' + Path(name).name,
              Path(name).exists() and sha(name) == digest,
              'input hash ' + name)
    check('data_integrity', 'sensor_completion',
          (args.run / 'run.complete.json').exists()
          and not (args.run / 'summary.error.txt').exists(),
          'sensor run complete, no error')
    check('data_integrity', 'sensor_freeze_lineage',
          manifest.get('freeze', {}).get('sha256')
          == freeze['input']['sensor_freeze_sha256'],
          'sensor freeze lineage')
    check('data_integrity', 'source_hashes',
          all(logical_sha(args.repo_root / path) == digest
              for path, digest in freeze['source_hashes'].items()),
          'consumer source hashes')
    check('data_integrity', 'template_hash',
          sha(freeze['algorithm']['template_path'])
          == freeze['algorithm']['template_sha256'],
          'template hash')
    check('data_integrity', 'labels_hash',
          sha(args.labels) == freeze['labels']['sha256'],
          'evaluation labels hash')
    check('data_integrity', 'no_truth_import',
          all(name not in Path(args.repo_root / source).read_text(
              encoding='utf-8') for source in (
              'src/boom_birds/evaluation/landmark_consumer.py',
              'src/boom_birds/evaluation/landmark_detector.py',
              'scripts/run_landmark_consumer.py')
              for name in ('landmark_labels', 'position_world', 'steps.jsonl')),
          'consumer source does not reference labels/pose/steps')
    check('data_integrity', 'results_count',
          len(results) == summary['processed_rgb_records']
          and summary['results_sha256'] == sha(
              args.results / 'results.jsonl'),
          'results count/hash')
    check('data_integrity', 'shadow_boundary',
          all(item['shadow_only'] is True
              and item['control_participation'] == 'NONE'
              and item['distance']['available'] is False
              for item in results),
          'shadow only, no control, no distance')
    # -- labels/split and provenance ----------------------------------------
    labels = labels_doc['labels']
    train = [item for item in labels if item['split'] == 'train']
    test = [item for item in labels if item['split'] == 'test']
    check('contract', 'split_by_episode',
          {item['episode'] for item in train}.isdisjoint(
              {item['episode'] for item in test}),
          'train episodes=' + repr(sorted({item['episode'] for item in train}))
          + ' test=' + repr(sorted({item['episode'] for item in test})))
    missing = []
    provenance_ok = True
    time_ok = True
    for item in test:
        frame = item['frame_id']
        result = result_by_frame.get(frame)
        if result is None:
            missing.append(frame)
            continue
        source = by_frame.get(frame)
        if source is None or result['source']['payload_sha256'] != source['payload']['sha256']:
            provenance_ok = False
        if result['source']['generation'] != item['generation']:
            provenance_ok = False
        if result['capture_time_semantics']['exposure_time_status'] != 'UNKNOWN':
            time_ok = False
        if result['capture_time_semantics']['capture_time_source'] not in (
                'SIM_UPDATE_SAMPLE_TIME', 'SIM_UPDATE_SAMPLE_TIME_LEGACY_V1'):
            time_ok = False
    check('contract', 'test_frame_results_present', not missing,
          'missing=' + repr(missing[:5]))
    check('contract', 'provenance_and_generation', provenance_ok,
          'payload/generation lineage')
    check('contract', 'time_semantics_unknown_exposure', time_ok,
          'capture source and exposure status')
    check('contract', 'reset_count',
          summary.get('consumer_reset_count') == len(
              {item['generation'] for item in labels}),
          'consumer reset count=' + str(summary.get('consumer_reset_count')))
    # -- metrics -------------------------------------------------------------
    tp = fp = fn = tn = rejected = 0
    per_episode = {}
    detection_boxes = []
    for item in test:
        result = result_by_frame.get(item['frame_id'])
        present = bool(item['present'])
        detected = bool(result and result['status'] == 'DETECTED')
        rejected_here = bool(result and result['status'] == 'REJECTED')
        rejected += int(rejected_here)
        if present and detected:
            tp += 1
        elif present and not detected:
            fn += 1
        elif not present and detected:
            fp += 1
        else:
            tn += 1
        episode = per_episode.setdefault(item['episode'], {
            'positives': 0, 'detected_positives': 0, 'negatives': 0,
            'false_positives': 0, 'rejected': 0})
        if present:
            episode['positives'] += 1
            episode['detected_positives'] += int(detected)
        else:
            episode['negatives'] += 1
            episode['false_positives'] += int(detected)
        episode['rejected'] += int(rejected_here)
        if detected and result.get('extra', {}).get('detection'):
            detection_boxes.append(result['extra']['detection'])
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    rejection_rate = rejected / total if total else None
    check('metrics', 'frame_denominator', total == len(test),
          'test frames=' + str(total) + '/' + str(len(test)))
    check('metrics', 'metrics_computed',
          precision is not None and recall is not None,
          'precision=' + str(precision) + ' recall=' + str(recall))
    check('metrics', 'capture_time_not_claimed_exposure',
          all(result['capture_time_semantics']['exposure_time_status']
              == 'UNKNOWN' for result in results),
          'all results exposure UNKNOWN')
    check('metrics', 'scores_are_correlation',
          all(item['score_definition'].startswith('max_multiscale')
              for item in (r.get('algorithm', {}) for r in results)),
          'score definition')
    # episode-level: positive episode detection and negative episodes with FP
    positive_episodes = [name for name, value in per_episode.items()
                         if value['positives']]
    negative_episodes = [name for name, value in per_episode.items()
                         if value['negatives']]
    check('metrics', 'episode_denominator',
          len(per_episode) == len({item['episode'] for item in test}),
          'episodes=' + repr(sorted(per_episode)))
    failures.extend({'name': item['name'], 'detail': item['detail']}
                    for item in checks if not item['passed'])
    status = 'PASS' if not failures else 'FAIL'
    report = {
        'schema_version': 'dsh.landmark_consumer_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'frame_metrics': {
            'total': total, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': precision, 'recall': recall,
            'rejection_rate': rejection_rate, 'rejected': rejected,
            'pixel_or_bearing_error': 'NOT_AVAILABLE: labels are presence-only; '
                                      'no independent bbox/bearing labels',
        },
        'episode_metrics': per_episode,
        'per_episode': {
            'positive_episodes': positive_episodes,
            'negative_episodes': negative_episodes,
            'positive_episodes_with_detection': [
                name for name in positive_episodes
                if per_episode[name]['detected_positives'] > 0],
            'episodes_with_false_positive': [
                name for name, value in per_episode.items()
                if value['false_positives'] > 0],
        },
        'detections': detection_boxes,
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'git_head': freeze.get('git_head')},
        'labels': {'path': str(args.labels), 'sha256': sha(args.labels),
                   'status': labels_doc.get('status')},
        'scope': 'shadow only; ORACLE route control unchanged; no localization',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'checks': len(checks),
                      'failures': failures[:3],
                      'frame_metrics': report['frame_metrics'],
                      'episode_metrics': per_episode}, ensure_ascii=False))
    raise SystemExit(0 if status == 'PASS' else 1)


if __name__ == '__main__':
    main()
