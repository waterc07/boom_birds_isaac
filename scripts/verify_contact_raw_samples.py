"""Recompute lifecycle force measurements from raw vectors, not cached measure."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reports, errors = [], []
    for directory in args.run:
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['outputs_sha256'].items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
                errors.append(str(directory / name) + ': hash mismatch')
        rows = [json.loads(line) for line in (directory / 'steps.jsonl').read_text(
            encoding='utf-8').splitlines() if line.strip()]
        episodes = [json.loads(line) for line in (directory / 'episodes.jsonl').read_text(
            encoding='utf-8').splitlines() if line.strip()]
        per_episode = {}
        production_nested = False
        for index, row in enumerate(rows):
            try:
                if row.get('phase') in ('RUN', 'HANDSHAKE') and row.get('contact_readout'):
                    measured = audit_row(row)
                    group = per_episode.setdefault(row['episode_id'], {'run': [], 'handshake': []})
                    if row['phase'] == 'RUN':
                        group['run'].append(measured['measured_force_n'])
                    else:
                        group['handshake'].append(measured['measured_force_n'])
                        if row.get('fresh_zero') and measured['measured_force_n'] > manifest['handshake']['zero_tolerance_n']:
                            raise ValueError('fresh-zero claim disagrees with raw force')
                else:
                    evidence = row.get('contact_evidence') or {}
                    measurement = evidence.get('measurement')
                    if not measurement:
                        raise ValueError('missing raw sensor reads')
                    production_nested = True
                    measured = audit_row({'contact_readout': measurement['contact_readout']})
                    group = per_episode.setdefault(row['episode_id'], {'run': [], 'handshake': []})
                    group['run'].append(measured['measured_force_n'])
                    cached = measurement.get('measure') or {}
                    if not math.isclose(measured['measured_force_n'],
                                        cached.get('measured_force_n', -1),
                                        abs_tol=1e-9, rel_tol=1e-7):
                        raise ValueError('measurement cache mismatch')
            except (ValueError, KeyError, TypeError) as error:
                errors.append(f'{directory}: row {index}: {error}')
        if production_nested:
            inits = manifest.get('contact_initializations') or []
            for init in inits:
                hs = init.get('handshake') or {}
                for sample in hs.get('samples') or []:
                    try:
                        measured = audit_row({'contact_readout': sample.get(
                            'contact_readout', {})})
                        group = per_episode.setdefault(
                            init.get('case_id'), {'run': [], 'handshake': []})
                        group['handshake'].append(measured['measured_force_n'])
                    except Exception as error:  # noqa: BLE001
                        errors.append(str(directory) + ': handshake ' + str(error))
        for episode in episodes:
            group = per_episode.get(episode['episode_id'], {})
            forces = group.get('run', [])
            if not forces:
                errors.append(str(directory) + ': missing RUN samples')
                continue
            if not production_nested and not group.get('handshake'):
                errors.append(str(directory) + ': missing HANDSHAKE samples')
                continue
            expected_max = episode.get('max_measured_force_n')
            if expected_max is None:
                expected_max = episode.get('contact_max_force_n')
            if expected_max is not None and not math.isclose(
                    max(forces), expected_max, abs_tol=1e-9, rel_tol=1e-7):
                errors.append(str(directory) + ': episode maximum mismatch')
        reports.append({'directory': directory.as_posix(), 'rows': len(rows),
                        'episodes': len(episodes), 'recomputed': per_episode})
    result = {'status': 'PASS' if not errors else 'FAIL',
              'scope': 'raw-vector/cache/hash consistency; not physical coverage or absence-of-contact proof',
              'runs': reports, 'errors': errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'rows': sum(r['rows'] for r in reports),
                      'errors': errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
