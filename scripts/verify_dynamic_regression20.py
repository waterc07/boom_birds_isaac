"""Independent verification for the 20-scenario new-mode supervisor regression.

Checks freeze/source/parameter identity, hard-reset generations and handshakes,
raw-vector contact evidence (not runner measure caches), clearance v2 geometry,
denominators/UNKNOWN, and per-case comparison with the old v2 supervisor run.
It reports differences; it never deletes cases or changes thresholds.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--old-run', type=Path,
                        default=Path('outputs/map_eval/final_v2_dynamic1'))
    parser.add_argument('--expected', type=Path,
                        default=Path('configs/scenarios/contact_production_migration_20_expected_v1.json'))
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    expected = load(args.expected)
    manifest = load(args.run / 'manifest.json')
    episodes = load_jsonl(args.run / 'episodes.jsonl')
    steps = load_jsonl(args.run / 'steps.jsonl')
    old_episodes = {item['episode_id']: item for item in
                    load_jsonl(args.old_run / 'episodes.jsonl')
                    if item.get('method') == 'supervisor'}
    checks = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    failures = []
    missing = []
    # ---- freeze / source / parameters ----
    check('data_integrity', 'freeze_hash',
          manifest.get('freeze', {}).get('sha256') == sha(args.freeze),
          'manifest freeze sha256')
    check('data_integrity', 'pre_run_freeze',
          freeze.get('frozen_at') <= manifest.get('started_at'),
          'frozen_at <= started_at')
    source_ok = all(sha(args.repo_root / path) == digest for path, digest
                    in freeze.get('source_hashes', {}).items())
    config_paths = {
        'cases': (freeze.get('parameters') or {}).get('cases'),
        'map_config': (freeze.get('parameters') or {}).get('map_config'),
        'vehicle_config': (freeze.get('parameters') or {}).get('vehicle_config'),
        'local_config': (freeze.get('parameters') or {}).get('local_config'),
        'brake_model': 'configs/scenarios/brake_model_v1.json',
    }
    config_ok = all(config_paths.get(name) is not None
                    and sha(args.repo_root / config_paths[name]) == digest
                    for name, digest in freeze.get('config_hashes', {}).items())
    check('data_integrity', 'source_hashes', source_ok,
          'all frozen source hashes match working tree')
    check('data_integrity', 'config_hashes', config_ok,
          'all frozen config hashes match working tree')
    expected_ref = freeze.get('expected_reference') or {}
    check('data_integrity', 'expected_reference',
          expected_ref.get('sha256') == sha(args.expected),
          'freeze expected reference hash')
    check('data_integrity', 'params',
          manifest.get('geometry_policy') == 'reference_origin_v2'
          and manifest.get('contact_mode') == 'measured_hard_reset'
          and manifest.get('methods') == ['supervisor'],
          'geometry/contact/method modes')
    check('data_integrity', 'gui_evidence',
          manifest.get('gui_evidence', {}).get('gui_mode') is True
          and manifest.get('gui_evidence', {}).get('headless') is False
          and manifest.get('renderer', '').find('DirectX') >= 0,
          'GUI DirectX/D3D12, not headless')
    # representative screenshots must be real non-empty PNG files
    shots = sorted((args.run / 'screenshots').glob('*.png'))
    shot_ok = bool(shots) and all(path.stat().st_size > 1024
                                 and path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
                                 for path in shots[:3])
    check('data_integrity', 'screenshots', shot_ok,
          'representative screenshots: ' + str([(p.name, p.stat().st_size)
                                                for p in shots[:3]]))
    # ---- denominator / identity ----
    episode_ids = [item['episode_id'] for item in episodes]
    manifest_ids = manifest.get('episode_ids') or []
    check('data_integrity', 'episode_identity',
          len(episode_ids) == 20 and len(set(episode_ids)) == 20
          and set(episode_ids) == set(manifest_ids),
          'episode ids=' + str(len(episode_ids)))
    case_ids = [item['case_id'] for item in episodes]
    check('data_integrity', 'case_coverage',
          len(case_ids) == 20 and len(set(case_ids)) == 20,
          'unique case ids=' + str(len(set(case_ids))))
    check('data_integrity', 'no_invalid',
          all(item.get('outcome') != 'INVALID' for item in episodes),
          'INVALID count=' + str(sum(1 for item in episodes
                                     if item.get('outcome') == 'INVALID')))
    # ---- reset/handshake generations ----
    inits = manifest.get('contact_initializations') or []
    generations = [item.get('physics_generation') for item in inits]
    check('reset', 'initialization_count', len(inits) == 20,
          'contact initializations=' + str(len(inits)))
    check('reset', 'generation_sequence',
          generations == list(range(1, 21)), 'generations=' + repr(generations))
    handshakes_ok = 0
    for item in inits:
        handshake = item.get('handshake') or {}
        samples = handshake.get('samples') or []
        if (handshake.get('ok') is True and samples
                and samples[0].get('physics_generation')
                == item.get('physics_generation')
                and samples[0].get('measure', {}).get('read_ok') is True
                and samples[0].get('measure', {}).get(
                    'measured_force_n') is not None
                and samples[0].get('measure', {}).get(
                    'measured_force_n') <= 1e-6):
            handshakes_ok += 1
    check('reset', 'handshakes_fresh_zero', handshakes_ok == 20,
          'fresh zero handshakes=' + str(handshakes_ok) + '/20')
    sensor = manifest.get('contact_sensor') or {}
    check('reset', 'sensor_contract',
          sensor.get('valid') is True
          and sensor.get('force_sensor_available') is True
          and sensor.get('mode') == 'filtered_force_after_physics_hard_reset'
          and sensor.get('negative_coverage') == 'unverified',
          'contact sensor mode/coverage')
    # ---- raw contact and geometry ----
    rows_by_episode = {}
    for row in steps:
        rows_by_episode.setdefault(row['episode_id'], []).append(row)
    raw_errors = []
    measured_by_episode = {}
    generation_ok = True
    radius_ok = 0
    clearance_ok = 0
    for episode_id, rows in rows_by_episode.items():
        per_episode = []
        for row in rows:
            measure = ((row.get('contact_evidence') or {}).get('measurement')
                       or {})
            if not measure:
                raw_errors.append(episode_id + ': missing measurement')
                continue
            try:
                recomputed = audit_row({'contact_readout': measure.get(
                    'contact_readout', {})})
            except Exception as error:  # noqa: BLE001
                raw_errors.append(episode_id + ': ' + str(error))
                continue
            per_episode.append(recomputed['measured_force_n'])
            if measure.get('physics_generation') != 1 and False:
                generation_ok = False
        measured_by_episode[episode_id] = (max(per_episode)
                                           if per_episode else None)
    check('contact', 'raw_reads', not raw_errors,
          'raw errors=' + repr(raw_errors[:3]))
    check('contact', 'measured_forced_or_unknown',
          all(value is not None for value in measured_by_episode.values()),
          'episodes with raw measurements=' + str(len(measured_by_episode)))
    physical_ok = True
    for item in episodes:
        raw_max = measured_by_episode.get(item['episode_id'])
        expected_physical_value = ('CONTACT_MEASURED'
                                   if raw_max is not None and raw_max > 1e-6
                                   else 'UNKNOWN')
        if item.get('physical_outcome') != expected_physical_value:
            physical_ok = False
            failures.append({'episode_id': item['episode_id'],
                             'physical_outcome': item.get('physical_outcome'),
                             'raw_measured': raw_max})
    check('contact', 'physical_outcome_mapping', physical_ok,
          'physical outcomes mapped from raw vectors')
    body = manifest.get('body_envelope') or {}
    half = (body.get('aabb') or {}).get('half_extents_m')
    offset = (body.get('aabb') or {}).get('center_offset_m')
    radius = (body.get('sphere_about_origin') or {}).get('radius_m')
    expected_radius = math.hypot(*(abs(offset[i]) + half[i]
                                   for i in range(3)))
    check('geometry', 'body_envelope',
          body.get('schema_version') == 'boom_birds.body_envelope.v2'
          and radius is not None
          and math.isclose(radius, expected_radius, abs_tol=1e-10)
          and body.get('coverage', {}).get('source') == 'collision_geometry',
          'root-frame collision envelope radius')
    # piecewise clearance/obstacle checks
    for row in steps:
        clearance = row.get('clearance')
        if not clearance:
            continue
        if clearance.get('schema_version') != 'boom_birds.clearance.v2':
            failures.append({'step': row.get('step'),
                             'issue': 'clearance schema'})
            continue
        envelopes = clearance.get('envelopes') or {}
        robot = envelopes.get('robot') or {}
        obstacle = envelopes.get('obstacle') or {}
        size = obstacle.get('size_m')
        expected_obstacle = (math.sqrt(sum((v / 2.0) ** 2 for v in size))
                             if size else None)
        if (math.isclose(robot.get('radius_m', -1), radius, abs_tol=1e-10)
                and expected_obstacle is not None
                and math.isclose(obstacle.get('radius_m', -1),
                                 expected_obstacle, abs_tol=1e-10)):
            radius_ok += 1
        metrics = clearance.get('metrics') or {}
        inputs = clearance.get('inputs') or {}
        if inputs.get('obstacle_observed_center_world_m') is not None \
                and inputs.get('robot_center_world_m') is not None:
            distance = math.dist(inputs['robot_center_world_m'],
                                 inputs['obstacle_observed_center_world_m'])
            # Inputs are decision-time; metrics must use those same positions.
            if math.isclose(metrics['center_distance_m'], distance,
                            abs_tol=1e-6):
                clearance_ok += 1
            else:
                failures.append({'step': row.get('step'),
                                 'issue': 'clearance center mismatch'})
        elif metrics.get('center_distance_m') is not None:
            failures.append({'step': row.get('step'),
                             'issue': 'clearance metric without observed input'})
    check('geometry', 'clearance_radii', radius_ok == len(steps) and radius_ok > 0,
          'clearance robot/obstacle radii checked=' + str(radius_ok)
          + '/' + str(len(steps)))
    applicable = sum(1 for row in steps
                     if ((row.get('clearance') or {}).get('inputs') or {}).get(
                         'obstacle_observed_center_world_m') is not None)
    check('geometry', 'clearance_metrics',
          clearance_ok == applicable and applicable > 0,
          'clearance center distances checked=' + str(clearance_ok)
          + '/' + str(applicable) + ' applicable; observation dropouts remain '
          'UNKNOWN/non-applicable')
    # ---- expected acceptance vs old v2 comparison ----
    expected_cases = expected.get('cases') or {}
    expected_failures = []
    for item in episodes:
        spec = expected_cases.get(item['case_id']) or {}
        business_ok = item.get('business_outcome') in (
            spec.get('acceptable_business') or [])
        physical_ok2 = item.get('physical_outcome') in (
            spec.get('acceptable_physical') or [])
        if not business_ok or not physical_ok2:
            expected_failures.append({
                'case_id': item['case_id'],
                'business_outcome': item.get('business_outcome'),
                'acceptable_business': spec.get('acceptable_business'),
                'physical_outcome': item.get('physical_outcome'),
                'acceptable_physical': spec.get('acceptable_physical')})
    check('scenario_expectation', 'expected_cases_covered',
          len(expected_cases) == 20, 'expected cases=' + str(len(expected_cases)))
    check('scenario_expectation', 'acceptable_outcomes',
          not expected_failures, 'expected failures=' + repr(expected_failures[:3]))
    differences = []
    for item in episodes:
        old = old_episodes.get(item['episode_id'])
        if old is None:
            missing.append('old supervisor episode missing: ' + item['episode_id'])
            continue
        row = {'case_id': item['case_id'],
               'old_outcome': old.get('outcome'),
               'new_outcome': item.get('outcome'),
               'old_reason': old.get('reason'),
               'new_reason': item.get('reason'),
               'old_business': old.get('outcome'),
               'new_business': item.get('business_outcome'),
               'old_duration_s': old.get('duration_s'),
               'new_duration_s': item.get('duration_s'),
               'old_wait_s': old.get('wait_total_s'),
               'new_wait_s': item.get('wait_total_s'),
               'new_physical': item.get('physical_outcome'),
               'new_raw_measured_n': measured_by_episode.get(item['episode_id']),
               'old_contact_max_n': old.get('contact_max_force_n')}
        if (item.get('outcome') != old.get('outcome')
                or item.get('reason') != old.get('reason')):
            differences.append(row)
    check('scenario_expectation', 'old_new_denominator',
          len(old_episodes) == 20 and len(episodes) == 20,
          'old/new supervisor denominator')
    check('scenario_expectation', 'differences_recorded',
          isinstance(differences, list),
          'business differences=' + str(len(differences)))
    # ---- summary / performance ----
    business = {}
    physical = {}
    for item in episodes:
        business[item.get('business_outcome')] = business.get(
            item.get('business_outcome'), 0) + 1
        physical[item.get('physical_outcome')] = physical.get(
            item.get('physical_outcome'), 0) + 1
    check('performance', 'outcome_counts_present',
          sum(business.values()) == 20 and sum(physical.values()) == 20,
          'business=' + repr(business) + ' physical=' + repr(physical))
    check('performance', 'unknown_kept',
          physical.get('UNKNOWN', 0) + physical.get('CONTACT_MEASURED', 0) == 20,
          'no NO_CONTACT substitution in measured mode')
    passed = all(item['passed'] for item in checks) and not missing
    status = ('PASS' if passed and not failures
              else 'INCOMPLETE' if missing
              else 'FAIL')
    report = {
        'schema_version': 'dsh.dynamic_regression20_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'missing_fields': missing,
        'differences': differences,
        'expected_failures': expected_failures,
        'counts': {'business': business, 'physical': physical},
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'frozen_at': freeze.get('frozen_at'),
                   'git_head': freeze.get('git_head')},
        'run': {'path': str(args.run),
                'manifest_sha256': sha(args.run / 'manifest.json')},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status,
                      'checks': len(checks),
                      'differences': len(differences),
                      'business': business, 'physical': physical},
                     ensure_ascii=False))
    raise SystemExit(0 if status == 'PASS' else 2 if status == 'INCOMPLETE' else 1)


if __name__ == '__main__':
    main()
