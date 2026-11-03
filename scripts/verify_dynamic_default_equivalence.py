"""Independent verification of default-vs-explicit single-env mode equivalence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row

CASES = ['dynamic_A_south_0', 'dynamic_C_south_0']
METHODS = ['follow_only', 'supervisor']
DYN_PATH = '/World/envs/env_0/Obstacle'


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


def verify_run(directory, freeze_path, expected_path, expected_source):
    directory = Path(directory)
    freeze = load(freeze_path)
    manifest = load(directory / 'manifest.json')
    summary = load(directory / 'summary.json')
    episodes = load_jsonl(directory / 'episodes.jsonl')
    steps = load_jsonl(directory / 'steps.jsonl')
    checks = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    check('data_integrity', 'freeze_hash',
          manifest.get('freeze', {}).get('sha256') == sha(freeze_path),
          'manifest freeze hash')
    check('data_integrity', 'expected_reference',
          (freeze.get('expected_reference') or {}).get('sha256')
          == sha(expected_path), 'freeze expected reference')
    check('data_integrity', 'pre_run',
          freeze.get('frozen_at') <= manifest.get('started_at'),
          'freeze before run')
    check('data_integrity', 'source_hashes',
          all(logical_sha(expected_source / path) == digest
              for path, digest in freeze.get('source_hashes', {}).items()),
          'source hashes match')
    check('data_integrity', 'single_env',
          manifest.get('single_env_only') is True,
          'single_env_only=' + str(manifest.get('single_env_only')))
    check('data_integrity', 'gui',
          manifest.get('gui_evidence', {}).get('gui_mode') is True
          and manifest.get('gui_evidence', {}).get('headless') is False
          and 'DirectX' in str(manifest.get('renderer')),
          'GUI/DirectX evidence')
    check('data_integrity', 'completion_marker',
          (directory / 'run.complete.json').exists()
          and not (directory / 'summary.error.txt').exists(),
          'completion marker present; error file absent')
    if (directory / 'run.complete.json').exists():
        complete = load(directory / 'run.complete.json')
        check('data_integrity', 'completion_status',
              complete.get('completed') is True
              and complete.get('status') == summary.get('status'),
              'completion/status')
    for name, digest in (manifest.get('outputs_sha256') or {}).items():
        check('data_integrity', 'output_' + name,
              (directory / name).exists() and sha(directory / name) == digest,
              'output hash')
    check('contract', 'summary_status',
          summary.get('status') == 'PASS', 'summary status')
    effective = manifest.get('effective_config') or {}
    check('contract', 'effective_config',
          manifest.get('geometry_policy') == 'reference_origin_v2'
          and manifest.get('contact_mode') == 'measured_hard_reset'
          and effective.get('geometry_policy') == 'reference_origin_v2'
          and effective.get('contact_mode') == 'measured_hard_reset',
          'actual effective config=' + repr(effective))
    sources = (effective.get('argument_sources') or {})
    expected_ids = [case + '-' + method for case in CASES for method in METHODS]
    check('contract', 'episode_denominator',
          len(episodes) == 4 and len({e['episode_id'] for e in episodes}) == 4
          and set(e['episode_id'] for e in episodes) == set(expected_ids),
          'episodes=' + repr([e['episode_id'] for e in episodes]))
    # raw contact recomputation and physical labels
    rows_by = {}
    for row in steps:
        rows_by.setdefault(row['episode_id'], []).append(row)
    for episode in episodes:
        eid = episode['episode_id']
        raw = []
        for row in rows_by.get(eid, []):
            measurement = ((row.get('contact_evidence') or {}).get(
                'measurement') or {})
            if not measurement:
                continue
            audit = audit_row({'contact_readout': measurement.get(
                'contact_readout', {})})
            raw.append((row, audit))
        positive = [x for x in raw if x[1]['max_filtered_force_n'] > 1e-6]
        peak = max((x[1]['max_filtered_force_n'] for x in raw), default=0.0)
        if episode.get('physical_outcome') == 'CONTACT_MEASURED':
            check('capability', 'raw_positive_' + eid, bool(positive),
                  'peak=' + format(peak, '.9f'))
        elif episode.get('physical_outcome') == 'UNKNOWN':
            check('capability', 'raw_unknown_' + eid, peak == 0.0,
                  'peak=' + format(peak, '.9f'))
        else:
            check('capability', 'physical_' + eid, False,
                  'unexpected physical=' + str(episode.get('physical_outcome')))
        check('capability', 'contact_object_' + eid,
              (not positive) or episode.get('contact_prim') == DYN_PATH,
              'contact_prim=' + str(episode.get('contact_prim')))
    return {'checks': checks, 'manifest': manifest, 'summary': summary,
            'episodes': episodes, 'steps': rows_by, 'sources': sources,
            'directory': str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--default-freeze', type=Path, required=True)
    parser.add_argument('--explicit-freeze', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    default = verify_run(args.root / 'default', args.default_freeze,
                         args.expected, args.repo_root)
    explicit = verify_run(args.root / 'explicit', args.explicit_freeze,
                          args.expected, args.repo_root)
    checks = default['checks'] + explicit['checks']
    failures = []
    # source metadata distinction, effective config equality
    checks.append({
        'category': 'equivalence', 'name': 'default_sources',
        'passed': default['sources'] == {
            'geometry_policy': 'default', 'contact_mode': 'default'},
        'detail': repr(default['sources'])})
    checks.append({
        'category': 'equivalence', 'name': 'explicit_sources',
        'passed': explicit['sources'] == {
            'geometry_policy': 'explicit', 'contact_mode': 'explicit'},
        'detail': repr(explicit['sources'])})
    defaults = {e['episode_id']: e for e in default['episodes']}
    explicits = {e['episode_id']: e for e in explicit['episodes']}
    max_duration = max_wait = 0.0
    for eid in sorted(defaults):
        if eid not in explicits:
            failures.append({'issue': 'missing explicit pair', 'episode': eid})
            continue
        d, x = defaults[eid], explicits[eid]
        for key in ('outcome', 'reason', 'business_outcome',
                    'physical_outcome', 'contact_prim', 'contact_max_force_n',
                    'steps', 'duration_s', 'route_active_s', 'wait_total_s'):
            if d.get(key) != x.get(key):
                failures.append({'episode': eid, 'field': key,
                                 'default': d.get(key), 'explicit': x.get(key)})
        max_duration = max(max_duration, abs(float(d.get('duration_s', 0.0))
                                             - float(x.get('duration_s', 0.0))))
        max_wait = max(max_wait, abs(float(d.get('wait_total_s', 0.0))
                                     - float(x.get('wait_total_s', 0.0))))
    checks.append({
        'category': 'equivalence', 'name': 'pair_identity',
        'passed': set(defaults) == set(explicits) and len(failures) == 0,
        'detail': 'pairs=' + str(len(defaults)) + ' field failures='
        + str(len(failures))})
    checks.append({
        'category': 'equivalence', 'name': 'time_differences',
        'passed': max_duration <= 1e-9 and max_wait <= 1e-9,
        'detail': 'max duration diff=' + format(max_duration, '.9f')
        + ' max wait diff=' + format(max_wait, '.9f')})
    # trajectory/step comparison for each episode
    trajectory_max = 0.0
    for eid in defaults:
        d_rows = default['steps'].get(eid, [])
        x_rows = explicit['steps'].get(eid, [])
        if len(d_rows) != len(x_rows):
            failures.append({'episode': eid, 'issue': 'step count differs',
                             'default': len(d_rows), 'explicit': len(x_rows)})
            continue
        for dr, xr in zip(d_rows, x_rows):
            for key in ('step', 'time_s', 'position_world_m',
                        'velocity_world_mps'):
                if key not in dr or key not in xr:
                    continue
                a, b = dr[key], xr[key]
                if isinstance(a, list) and isinstance(b, list):
                    trajectory_max = max(trajectory_max, max(
                        abs(float(ai) - float(bi)) for ai, bi in zip(a, b)))
                elif key == 'time_s':
                    trajectory_max = max(trajectory_max,
                                         abs(float(a) - float(b)))
    checks.append({
        'category': 'equivalence', 'name': 'trajectory_difference',
        'passed': trajectory_max <= 1e-9,
        'detail': 'max numeric position/velocity/time diff='
        + format(trajectory_max, '.12f')})
    # episode boundary/generation equality
    check_reset = True
    for eid in defaults:
        if defaults[eid].get('steps') != explicits[eid].get('steps'):
            check_reset = False
    checks.append({
        'category': 'contract', 'name': 'episode_boundary_equal',
        'passed': check_reset, 'detail': 'steps equal'})
    failures.extend({'name': item['name'], 'detail': item['detail']}
                    for item in checks if not item['passed'])
    status = 'PASS' if not failures else 'FAIL'
    report = {
        'schema_version': 'dsh.dynamic_default_equivalence_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'summary': {'default_manifest': sha(args.root / 'default' / 'manifest.json'),
                    'explicit_manifest': sha(args.root / 'explicit' / 'manifest.json'),
                    'default_freeze': sha(args.default_freeze),
                    'explicit_freeze': sha(args.explicit_freeze),
                    'expected': sha(args.expected)},
        'max_duration_diff_s': max_duration,
        'max_wait_diff_s': max_wait,
        'max_trajectory_diff': trajectory_max,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'checks': len(checks),
                      'failures': failures[:3],
                      'trajectory': trajectory_max}, ensure_ascii=False))
    raise SystemExit(0 if status == 'PASS' else 1)


if __name__ == '__main__':
    main()
