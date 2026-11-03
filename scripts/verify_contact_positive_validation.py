"""Independent verification of the free-flight contact-positive matrix.

Recomputes filtered/net contact evidence from raw vectors and checks the
production runner's per-episode caches, reset generations, handshakes, object
filtering, geometry approach, episode done signals, pairing/repeats, freeze and
artifact hashes.  It does not trust summary PASS labels or cached measures.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row

CASES = ['dynamic_C_south_0', 'dynamic_C_north_0',
         'dynamic_D_south_0', 'dynamic_D_north_0']
METHODS = ['follow_only', 'supervisor']
REPEATS = ['repeat1', 'repeat2']
DYN_PATH = '/World/envs/env_0/Obstacle'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True,
                        help='parent containing repeat1/repeat2')
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    expected = load(args.expected)
    expected_sha = sha(args.expected)
    checks = []
    failures = []
    missing = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    # freeze / expected / source identity
    check('data_integrity', 'freeze_expected_hash',
          (freeze.get('expected_reference') or {}).get('sha256') == expected_sha,
          'expected reference hash')
    check('data_integrity', 'freeze_schema',
          freeze.get('schema_version') == 'boom_birds.dynamic_migration_freeze.v1',
          'schema=' + str(freeze.get('schema_version')))
    source_ok = all(logical_sha(args.repo_root / path) == digest for path, digest
                    in freeze.get('source_hashes', {}).items())
    config_paths = {
        'cases': (freeze.get('parameters') or {}).get('cases'),
        'map_config': (freeze.get('parameters') or {}).get('map_config'),
        'vehicle_config': (freeze.get('parameters') or {}).get('vehicle_config'),
        'local_config': (freeze.get('parameters') or {}).get('local_config'),
        'brake_model': 'configs/scenarios/brake_model_v1.json',
    }
    config_ok = all(config_paths.get(name) is not None
                    and logical_sha(args.repo_root / config_paths[name]) == digest
                    for name, digest in freeze.get('config_hashes', {}).items())
    check('data_integrity', 'source_hashes', source_ok,
          'source hashes match working tree')
    check('data_integrity', 'config_hashes', config_ok,
          'config hashes match working tree')
    plan = freeze.get('parameters') or {}
    check('data_integrity', 'frozen_identity',
          plan.get('only_cases') == ','.join(CASES)
          and plan.get('methods') == 'follow_only,supervisor'
          and plan.get('geometry_policy') == 'reference_origin_v2'
          and plan.get('contact_mode') == 'measured_hard_reset',
          'frozen cases/methods/policies')
    execution = freeze.get('execution_plan') or {}
    check('data_integrity', 'repeat_plan',
          execution.get('primary_cases') == CASES
          and execution.get('methods') == METHODS
          and execution.get('repeats') == REPEATS
          and execution.get('total_episodes') == 16,
          'pre-frozen repeat plan')
    check('data_integrity', 'expected_cases',
          sorted((expected.get('cases') or {}).keys()) == sorted(CASES),
          'expected cases=' + str(len(expected.get('cases') or {})))

    repeat_reports = {}
    all_follow_positive = []
    supervisor_records = []
    for repeat in REPEATS:
        directory = args.root / repeat
        for name in ('manifest.json', 'summary.json', 'episodes.jsonl',
                     'steps.jsonl'):
            if not (directory / name).exists():
                missing.append(repeat + '/' + name)
        if missing:
            continue
        manifest = load(directory / 'manifest.json')
        episodes = load_jsonl(directory / 'episodes.jsonl')
        steps = load_jsonl(directory / 'steps.jsonl')
        check('data_integrity', 'freeze_hash_' + repeat,
              manifest.get('freeze', {}).get('sha256') == sha(args.freeze),
              'manifest freeze hash')
        check('data_integrity', 'pre_run_freeze_' + repeat,
              freeze.get('frozen_at') <= manifest.get('started_at'),
              'freeze before run')
        check('data_integrity', 'gui_' + repeat,
              manifest.get('gui_evidence', {}).get('gui_mode') is True
              and manifest.get('gui_evidence', {}).get('headless') is False
              and 'DirectX' in str(manifest.get('renderer')),
              'GUI/DirectX evidence')
        expected_ids = [case + '-' + method for case in CASES
                        for method in METHODS]
        got_ids = [item['episode_id'] for item in episodes]
        check('data_integrity', 'denominator_' + repeat,
              len(episodes) == 8 and len(set(got_ids)) == 8
              and sorted(got_ids) == sorted(expected_ids)
              and set(manifest.get('episode_ids') or []) == set(expected_ids),
              'episode denominator/identity=' + repr(sorted(got_ids)))
        for name, digest in (manifest.get('outputs_sha256') or {}).items():
            if not (directory / name).exists() or sha(directory / name) != digest:
                failures.append({'repeat': repeat, 'issue': 'output hash ' + name})
        check('data_integrity', 'output_hashes_' + repeat,
              not [item for item in failures if item.get('repeat') == repeat],
              'output hashes')
        inits = manifest.get('contact_initializations') or []
        generations = [item.get('physics_generation') for item in inits]
        check('reset', 'initialization_count_' + repeat, len(inits) == 8,
              'initializations=' + str(len(inits)))
        check('reset', 'generation_sequence_' + repeat,
              generations == list(range(1, 9)), 'generations=' + repr(generations))
        init_by_id = {item.get('case_id') + '-' + item.get('method'): item
                      for item in inits}
        handshakes_ok = 0
        for init in inits:
            handshake = init.get('handshake') or {}
            samples = handshake.get('samples') or []
            if (handshake.get('ok') is True and samples
                    and samples[0].get('physics_generation')
                    == init.get('physics_generation')
                    and samples[0].get('measure', {}).get('read_ok') is True
                    and samples[0].get('measure', {}).get(
                        'measured_force_n') == 0.0):
                handshakes_ok += 1
        check('reset', 'fresh_zero_handshakes_' + repeat, handshakes_ok == 8,
              'fresh zero=' + str(handshakes_ok) + '/8')
        rows_by_episode = {}
        for row in steps:
            rows_by_episode.setdefault(row['episode_id'], []).append(row)
        for episode in episodes:
            eid = episode['episode_id']
            case_id = episode['case_id']
            method = episode['method']
            rows = rows_by_episode.get(eid, [])
            if not rows:
                missing.append(repeat + '/' + eid + ' rows')
                continue
            generation = init_by_id.get(eid, {}).get('physics_generation')
            raw = []
            raw_errors = []
            target_seen = set()
            physics_steps = []
            for row in rows:
                measurement = ((row.get('contact_evidence') or {}).get(
                    'measurement') or {})
                if not measurement:
                    raw_errors.append('missing measurement')
                    continue
                try:
                    audit = audit_row({'contact_readout': measurement.get(
                        'contact_readout', {})})
                    cached = measurement.get('measure') or {}
                    if not math.isclose(audit['measured_force_n'],
                                        cached.get('measured_force_n', -1),
                                        abs_tol=1e-9, rel_tol=1e-7):
                        raw_errors.append('measurement cache mismatch')
                    for read in (measurement.get('contact_readout') or {}).get(
                            'reads', []):
                        sample = read.get('sample') or {}
                        for target in (sample.get('filtered_by_target_n') or {}):
                            target_seen.add(target)
                    raw.append((row, audit))
                    physics_steps.append(int(measurement.get('physics_step', -1)))
                    if measurement.get('physics_generation') != generation:
                        raw_errors.append('generation changed inside episode')
                except Exception as error:  # noqa: BLE001
                    raw_errors.append(str(error))
            check('contract', 'raw_' + repeat + '_' + eid, not raw_errors,
                  'raw errors=' + repr(raw_errors[:2]))
            check('contract', 'filter_target_' + repeat + '_' + eid,
                  target_seen == {DYN_PATH}, 'targets=' + repr(sorted(target_seen)))
            check('contract', 'generation_' + repeat + '_' + eid,
                  len(physics_steps) == len(rows)
                  and all(value >= 0 for value in physics_steps),
                  'physics steps=' + str(len(physics_steps)))
            positive = [(row, audit) for row, audit in raw
                        if audit['max_filtered_force_n'] > 1e-6]
            net_positive = [(row, audit) for row, audit in raw
                            if audit['max_net_force_n'] > 1e-6]
            first = positive[0] if positive else None
            max_force = max((audit['max_filtered_force_n'] for _, audit in raw),
                            default=0.0)
            if method == 'follow_only':
                check('capability', 'follow_positive_' + repeat + '_' + eid,
                      bool(positive), 'max_filtered=' + format(max_force, '.9f'))
                check('capability', 'follow_positive_geometry_' + repeat + '_' + eid,
                      first is not None
                      and (first[0].get('contact_evidence') or {}).get(
                          'sphere_overlap_m', 0.0) is not None,
                      'first contact row has geometry')
                if positive:
                    row0 = rows[0]
                    evidence0 = row0.get('contact_evidence') or {}
                    first_row = first[0]
                    first_ev = first_row.get('contact_evidence') or {}
                    initial_sep = evidence0.get('center_distance_m', 0.0) - (
                        evidence0.get('radii_sum_m', 0.0))
                    first_measurement = ((first_row.get('contact_evidence') or {})
                                         .get('measurement') or {})
                    first_step = int(first_measurement.get(
                        'physics_step', first_row.get('step', 0)))
                    check('capability', 'follow_not_initial_penetration_'
                          + repeat + '_' + eid, initial_sep > 0.0,
                          'initial_margin=' + format(initial_sep, '.6f'))
                    check('capability', 'follow_contact_after_motion_'
                          + repeat + '_' + eid,
                          first_step > 1 and int(row0.get('step', 0)) == 0,
                          'first_physics_step=' + str(first_step))
                if max_force > 0.02:
                    event_class = 'ABOVE_0.02_N'
                elif max_force > 1e-6:
                    event_class = 'BELOW_0.02_N_REAL_CONTACT'
                else:
                    event_class = 'UNKNOWN'
                check('capability', 'follow_peak_' + repeat + '_' + eid,
                      math.isclose(episode.get('contact_max_force_n') or 0.0,
                                   max_force, abs_tol=1e-9, rel_tol=1e-7)
                      and episode.get('physical_outcome') == 'CONTACT_MEASURED',
                      'episode physical/max=' + str(event_class))
                check('capability', 'follow_object_' + repeat + '_' + eid,
                      episode.get('contact_prim') == DYN_PATH,
                      'contact_prim=' + str(episode.get('contact_prim')))
                all_follow_positive.append(bool(positive))
            elif method == 'supervisor':
                check('capability', 'supervisor_physical_' + repeat + '_' + eid,
                      episode.get('physical_outcome') in ('CONTACT_MEASURED',
                                                         'UNKNOWN'),
                      'physical=' + str(episode.get('physical_outcome')))
                if episode.get('physical_outcome') == 'CONTACT_MEASURED':
                    check('capability', 'supervisor_positive_raw_'
                          + repeat + '_' + eid, bool(positive),
                          'measured but no raw positive')
                supervisor_records.append({
                    'repeat': repeat, 'case_id': case_id,
                    'outcome': episode.get('outcome'),
                    'reason': episode.get('reason'),
                    'business': episode.get('business_outcome'),
                    'physical': episode.get('physical_outcome'),
                    'max_filtered_n': max_force,
                })
            # actual done signals / episode continuity from rows
            last = rows[-1]
            check('contract', 'actual_done_' + repeat + '_' + eid,
                  'episode_length_buf' in last and 'env_terminated' in last
                  and 'env_truncated' in last
                  and last.get('outcome') == episode.get('outcome'),
                  'last_step=' + str(last.get('episode_length_buf'))
                  + ' term=' + str(last.get('env_terminated'))
                  + ' trunc=' + str(last.get('env_truncated'))
                  + ' last_outcome=' + str(last.get('outcome')))
            check('contract', 'boundary_' + repeat + '_' + eid,
                  bool((last.get('boundary_count_ok') is not False)),
                  'boundary_count_ok=' + str(last.get('boundary_count_ok')))
        repeat_reports[repeat] = {'episodes': len(episodes), 'inits': len(inits)}

    # repeat pairing and positivity coverage
    paired = {}
    for repeat in REPEATS:
        for episode in load_jsonl(args.root / repeat / 'episodes.jsonl'):
            paired.setdefault(episode['case_id'] + '-' + episode['method'],
                              {})[repeat] = episode
    check('expected', 'paired_identity',
          all(set(values) == set(REPEATS) for values in paired.values())
          and len(paired) == 8, 'pairs=' + str(len(paired)))
    case_positive = {}
    for case in CASES:
        per_repeat = []
        for repeat in REPEATS:
            episode = paired.get(case + '-follow_only', {}).get(repeat)
            per_repeat.append(bool(episode
                                   and episode.get('physical_outcome')
                                   == 'CONTACT_MEASURED'
                                   and (episode.get('contact_max_force_n') or 0)
                                   > 1e-6))
        case_positive[case] = per_repeat
    check('capability', 'four_cases_positive_in_both_repeats',
          all(all(values) for values in case_positive.values()),
          'case positivity=' + repr(case_positive))
    check('capability', 'at_least_four_distinct_cases',
          sum(1 for values in case_positive.values() if any(values)) >= 4,
          'positive cases=' + str(sum(1 for values in case_positive.values()
                                      if any(values))))
    check('capability', 'methods_retained',
          len(supervisor_records) == 8,
          'supervisor records=' + str(len(supervisor_records)))
    check('capability', 'no_unknown_follow_only',
          all(values for values in case_positive.values()),
          'follow_only zero-read cases=' + repr(
              [case for case, values in case_positive.items()
               if not all(values)]))
    passed = all(item['passed'] for item in checks) and not missing and not failures
    status = ('PASS' if passed else 'INCOMPLETE' if missing else 'FAIL')
    report = {
        'schema_version': 'dsh.contact_positive_validation_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'missing_fields': missing,
        'repeat_reports': repeat_reports,
        'case_positive_follow_only': case_positive,
        'supervisor_records': supervisor_records,
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'git_head': freeze.get('git_head'),
                   'frozen_at': freeze.get('frozen_at')},
        'expected': {'path': str(args.expected), 'sha256': expected_sha},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'checks': len(checks),
                      'failures': len(failures), 'missing': missing,
                      'case_positive_follow_only': case_positive},
                     ensure_ascii=False))
    raise SystemExit(0 if status == 'PASS' else 2 if status == 'INCOMPLETE' else 1)


if __name__ == '__main__':
    main()
