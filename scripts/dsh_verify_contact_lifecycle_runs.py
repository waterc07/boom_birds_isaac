"""Independent verifier for the DSH minimal contact-freshness matrix.

Checks the pre-run freeze, per-episode physics hard reset / generation,
separated-pose freshness handshake, raw contact evidence (zero / unknown /
measured, including below-0.02 N low-amplitude real contact), wall geometry and
episode boundary.  It does not trust summary/episode verdicts; it re-derives
them from the raw step rows.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

SEGMENTS = {'contact_W_wall3': 'wall', 'contact_S_static3': 'obstacle'}
LOW_FORCE = 'PHYSX_CONTACT_FORCE_MEASURED_BELOW_THRESHOLD'
MEASURED = 'PHYSX_CONTACT_FORCE_MEASURED'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def hypot(value):
    return math.hypot(*(float(v) for v in value))


def raw_measure(row):
    readout = row.get('contact_readout') or {}
    measure = readout.get('measure') or {}
    if 'measured_force_n' not in measure:
        values = []
        for read in readout.get('reads') or []:
            sample = read.get('sample') or {}
            vectors = sample.get('net_vectors_n') or []
            filtered = sample.get('filtered_by_target_n') or {}
            values.extend(hypot(v) for v in vectors)
            values.extend(hypot(v) for v in filtered.values())
        measure = {'measured_force_n': max(values, default=0.0),
                   'read_ok': all((r.get('error') is None)
                                  and (r.get('sample') is not None)
                                  for r in readout.get('reads') or [])}
    return measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--run', action='append', default=[],
                        help='SEGMENT=DIR')
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze = load(args.freeze)
    expected = load(args.expected)
    run_dirs = dict(item.split('=', 1) for item in args.run)
    checks = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    failures = []
    missing = []

    # freeze lineage and versions
    check('data_integrity', 'freeze_schema',
          freeze.get('schema_version') == 'boom_birds.dsh_contact_lifecycle_freeze.v1',
          'freeze schema=' + str(freeze.get('schema_version')))
    check('data_integrity', 'freeze_hash_and_files',
          freeze.get('cases_sha256') == sha256(freeze['cases_file'])
          and freeze.get('expected_sha256') == sha256(freeze['expected_file'])
          and freeze.get('expected_sha256') == sha256(args.expected),
          'cases/expected hashes match freeze')
    reader = args.repo_root / 'src/boom_birds/evaluation/contact_readout.py'
    check('data_integrity', 'readout_source_hash',
          freeze.get('contact_readout', {}).get('source_sha256') == sha256(reader),
          'readout source hash matches freeze')
    check('data_integrity', 'versions',
          freeze.get('contact_evidence_version') == expected.get(
              'contact_contract_version')
          and freeze.get('physics_reset_mode') == 'hard'
          and freeze.get('handshake', {}).get('max_steps', 0) > 0,
          'contact evidence version/reset mode/handshake frozen')
    check('data_integrity', 'expected_status',
          expected.get('status') == 'EXPECTED_NOT_CONCLUSION'
          and expected.get('schema_version') == 'dsh.contact_lifecycle_expected.v2',
          'expected is pre-frozen expectation')

    segment_reports = {}
    for segment_id, role in SEGMENTS.items():
        directory = Path(run_dirs.get(segment_id, ''))
        entry = freeze.get('segments', {}).get(segment_id)
        if entry is None:
            missing.append('freeze segment missing: ' + segment_id)
            continue
        for name in ('manifest.json', 'summary.json', 'episodes.jsonl',
                     'steps.jsonl'):
            if not (directory / name).exists():
                missing.append(segment_id + '/' + name)
        if missing:
            continue
        manifest = load(directory / 'manifest.json')
        summary = load(directory / 'summary.json')
        episodes = {item['episode_id']: item for item in
                    load_jsonl(directory / 'episodes.jsonl')}
        steps = load_jsonl(directory / 'steps.jsonl')
        by_episode = {}
        for row in steps:
            by_episode.setdefault(row['episode_id'], []).append(row)
        case_ids = entry['case_ids']
        expected_ids = [cid + '-r' + str(index) + '-' + segment_id
                        for index, cid in enumerate(case_ids)]
        check('data_integrity', 'episode_identity_' + segment_id,
              sorted(episodes) == sorted(expected_ids)
              and manifest.get('episode_ids') == expected_ids,
              'episode ids/denominator ' + repr(expected_ids))
        check('data_integrity', 'manifest_versions_' + segment_id,
              manifest.get('physics_reset_mode') == 'hard'
              and manifest.get('contact_readout', {}).get('source_sha256')
              == freeze['contact_readout']['source_sha256']
              and manifest.get('contact_evidence_version')
              == freeze['contact_evidence_version'],
              'manifest reset/readout/evidence versions')
        check('data_integrity', 'gui_evidence_' + segment_id,
              manifest.get('gui_mode') is True
              and 'DirectX' in str(manifest.get('renderer'))
              and 'vulkan=false' in str(manifest.get('renderer')),
              'GUI DirectX evidence recorded')
        wall_geometry = manifest.get('wall_geometry')
        if role == 'wall':
            ray = (wall_geometry or {}).get('raycast') or {}
            check('geometry', 'wall_geometry_' + segment_id,
                  (wall_geometry or {}).get('collision_api') is True
                  and (wall_geometry or {}).get('contact_report_api') is True
                  and ray.get('hit') is True
                  and str(ray.get('collision', '')).find(
                      (wall_geometry or {}).get('target_prim', '')) >= 0,
                  'wall prim geometry/raycast: ' + json.dumps(
                      {'raycast': ray, 'bbox': (wall_geometry or {}).get(
                          'world_bbox_min_m')}))
        expected_seg = expected.get('segments', {}).get(segment_id, {})
        check('data_integrity', 'summary_' + segment_id,
              len(summary.get('episodes', [])) == 3,
              'summary episodes=' + str(len(summary.get('episodes', []))))

        episode_reports = {}
        for index, episode_id in enumerate(expected_ids):
            episode = episodes.get(episode_id)
            rows = by_episode.get(episode_id, [])
            handshake_rows = [row for row in rows
                              if row.get('phase') == 'HANDSHAKE']
            run_rows = [row for row in rows if row.get('phase') == 'RUN']
            generation = index + 1
            report = {'generation_expected': generation}
            checks_ok = True
            if episode is None:
                missing.append('episode missing: ' + episode_id)
                continue
            # hard reset generation and handshake
            generation_ok = (int(episode.get('physics_generation', -1))
                             == generation)
            handshake = episode.get('handshake') or {}
            success_rows = [row for row in handshake_rows
                            if row.get('fresh_zero')]
            handshake_ok = (handshake.get('ok') is True
                            and int(handshake.get('success_step') or -1) >= 1
                            and len(success_rows) >= 1
                            and all(row.get('physics_generation') == generation
                                    for row in handshake_rows)
                            and all((row.get('read_ok') is True)
                                    and (row.get('measured_force_n') or 0.0)
                                    <= freeze['handshake']['zero_tolerance_n']
                                    for row in success_rows))
            check('freshness', 'generation_' + episode_id, generation_ok,
                  'episode generation=' + str(episode.get('physics_generation')))
            check('freshness', 'handshake_' + episode_id, handshake_ok,
                  'handshake rows=' + str(len(handshake_rows))
                  + ' success=' + json.dumps(
                      [{'step': row.get('handshake_step'),
                        'measured': row.get('measured_force_n')}
                       for row in success_rows]))
            check('freshness', 'no_mid_episode_reset_' + episode_id,
                  all(row.get('physics_generation') == generation
                      for row in run_rows) and len(run_rows) > 0,
                  'RUN generations constant')
            # raw contact evidence
            measured = [raw_measure(row) for row in run_rows]
            max_measured = max((item.get('measured_force_n') or 0.0)
                               for item in measured) if measured else 0.0
            read_ok = all(item.get('read_ok') is True for item in measured) \
                if measured else False
            contact_observed = max_measured > 0.0
            expected_physical = (MEASURED if max_measured
                                 > expected.get('contact_threshold_n', 0.02)
                                 else LOW_FORCE if contact_observed
                                 else 'UNKNOWN')
            physical_ok = episode.get('physical_outcome') == expected_physical
            allowed = expected_seg.get('acceptable_physical') or []
            check('contact_evidence', 'measured_contact_' + episode_id,
                  contact_observed and read_ok,
                  'max_measured_n=' + format(max_measured, '.9f')
                  + ' read_ok=' + str(read_ok))
            check('contact_evidence', 'low_force_not_no_contact_' + episode_id,
                  (max_measured > 0.0) and (
                      episode.get('physical_outcome') in allowed),
                  'physical=' + str(episode.get('physical_outcome'))
                  + ' allowed=' + repr(allowed))
            check('contact_evidence', 'physical_matches_raw_' + episode_id,
                  physical_ok,
                  'expected_physical=' + expected_physical)
            check('contact_evidence', 'episode_observed_field_' + episode_id,
                  bool(episode.get('contact_observed'))
                  and (episode.get('max_measured_force_n') or 0.0)
                  >= max_measured - 1e-9,
                  'episode contact_observed/max_measured')
            if role == 'wall':
                attributed = any(
                    row.get('contact_record', {}).get(
                        'layers', {}).get('attribution', {}).get('status')
                    == 'ATTRIBUTED'
                    and expected_seg.get('wall_target_prim', '') in (
                        row.get('contact_record', {}).get(
                            'layers', {}).get('attribution', {}).get(
                                'prim_paths') or [])
                    for row in run_rows)
                check('contact_evidence', 'wall_attribution_' + episode_id,
                      attributed, 'wall prim attribution present')
            # sensor reinit / boundary / time monotonicity
            sensor_reinit = episode.get('sensor_reinit') or {}
            sensors = sensor_reinit.get('sensors') or []
            check('boundary', 'sensor_reinit_' + episode_id,
                  bool(sensors) and all(
                      item.get('created') is True
                      and item.get('error') is None
                      and item.get('filter_count') == 1
                      and item.get('body_names')
                      for item in sensors),
                  'sensor reinit=' + json.dumps(sensor_reinit.get('sensors')))
            check('boundary', 'episode_boundary_' + episode_id,
                  bool(handshake_rows) and bool(run_rows)
                  and max(row.get('handshake_step', 0) for row in handshake_rows)
                  <= freeze['handshake']['max_steps'],
                  'handshake before RUN, bounded steps')
            times = [float(row.get('time_s', 0.0)) for row in run_rows]
            check('boundary', 'time_monotonic_' + episode_id,
                  all(b >= a for a, b in zip(times, times[1:])),
                  'RUN time non-decreasing')
            episode_reports[episode_id] = report
        segment_reports[segment_id] = episode_reports

    passed = all(item['passed'] for item in checks)
    status = ('PASS' if passed and not missing
              else 'INCOMPLETE' if missing else 'FAIL')
    report = {
        'schema_version': 'dsh.contact_lifecycle_verify.v1',
        'status': status,
        'checks': checks,
        'checks_by_category': {},
        'failures': [item for item in checks if not item['passed']],
        'missing_fields': missing,
        'segments': segment_reports,
        'freeze': {
            'path': str(args.freeze),
            'sha256': sha256(args.freeze),
            'code_commit': freeze.get('code_commit'),
            'frozen_at': freeze.get('frozen_at'),
            'physics_reset_mode': freeze.get('physics_reset_mode'),
            'contact_readout_source_sha256': freeze.get(
                'contact_readout', {}).get('source_sha256'),
        },
    }
    for item in checks:
        report['checks_by_category'].setdefault(item['category'], []).append(item)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status,
                      'checks': len(checks),
                      'failures': len(report['failures']),
                      'missing': missing}, indent=2))
    raise SystemExit(0 if status == 'PASS' else 2 if status == 'INCOMPLETE' else 1)


if __name__ == '__main__':
    main()
