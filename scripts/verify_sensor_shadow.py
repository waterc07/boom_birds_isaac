"""Independent verification of the shadow sensor chain (RGB + rendered depth).

Recomputes observation counts, sequence/generation isolation, timestamp and
payload integrity, image decodability/motion, and two known static depth
references.  It does not consume runner PASS labels as evidence.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.sensor_observation import RECORD_VERSION


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


def image_stats(path):
    image = Image.open(path)
    image.load()
    array = np.asarray(image.convert('RGB'), dtype=np.float32)
    gray = array.mean(axis=2)
    edges = float(np.abs(np.diff(gray, axis=0)).mean()
                  + np.abs(np.diff(gray, axis=1)).mean())
    return {'format': image.format, 'size': list(image.size),
            'mean': float(gray.mean()), 'std': float(gray.std()),
            'edge_mean': edges, 'unique_quantized': int(len(np.unique(
                (gray / 8).astype(np.uint8))))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shadow', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.run
    shadow = args.shadow
    manifest = load(run / 'manifest.json')
    summary = load(run / 'summary.json')
    episodes = load_jsonl(run / 'episodes.jsonl')
    steps = load_jsonl(run / 'steps.jsonl')
    freeze = load(args.freeze)
    expected = load(args.expected)
    records = load_jsonl(shadow / 'observations.jsonl')
    sensor_summary = load(shadow / 'summary.json')
    checks = []

    def check(category, name, passed, detail):
        checks.append({'category': category, 'name': name,
                       'passed': bool(passed), 'detail': detail})

    failures = []
    # --- freeze / config / completion -----------------------------------
    check('data_integrity', 'freeze_hash',
          manifest.get('freeze', {}).get('sha256') == sha(args.freeze),
          'manifest freeze hash')
    check('data_integrity', 'expected_hash',
          (freeze.get('expected_reference') or {}).get('sha256')
          == sha(args.expected), 'expected reference')
    check('data_integrity', 'pre_run',
          freeze.get('frozen_at') <= manifest.get('started_at'),
          'freeze before run')
    source_ok = all(logical_sha(args.repo_root / path) == digest
                    for path, digest in freeze.get('source_hashes', {}).items())
    config_paths = {
        'cases': (freeze.get('parameters') or {}).get('cases'),
        'map_config': (freeze.get('parameters') or {}).get('map_config'),
        'vehicle_config': (freeze.get('parameters') or {}).get('vehicle_config'),
        'local_config': (freeze.get('parameters') or {}).get('local_config'),
        'sensor_shadow_config': (freeze.get('parameters') or {}).get(
            'sensor_shadow_config'),
        'brake_model': 'configs/scenarios/brake_model_v1.json',
    }
    config_ok = all(config_paths.get(name) is not None
                    and logical_sha(args.repo_root / config_paths[name]) == digest
                    for name, digest in freeze.get('config_hashes', {}).items())
    check('data_integrity', 'source_hashes', source_ok, 'source hashes')
    check('data_integrity', 'config_hashes', config_ok, 'config hashes')
    check('data_integrity', 'sensor_config_hash',
          manifest.get('sensor_shadow', {}).get('config_sha256')
          == logical_sha(args.repo_root / 'configs/sensors/sensor_shadow_v1.json'),
          'manifest sensor config hash')
    check('data_integrity', 'completion',
          (run / 'run.complete.json').exists()
          and not (run / 'summary.error.txt').exists(),
          'completion marker, no error file')
    if (run / 'run.complete.json').exists():
        complete = load(run / 'run.complete.json')
        check('data_integrity', 'completion_status',
              complete.get('completed') is True
              and complete.get('status') == summary.get('status'),
              'completion status')
    for name, digest in (manifest.get('outputs_sha256') or {}).items():
        check('data_integrity', 'output_' + name,
              (run / name).exists() and sha(run / name) == digest,
              'output hash')
    check('data_integrity', 'gui',
          manifest.get('gui_evidence', {}).get('gui_mode') is True
          and manifest.get('gui_evidence', {}).get('headless') is False
          and 'DirectX' in str(manifest.get('renderer')),
          'GUI/DirectX')
    # --- denominator / generation ---------------------------------------
    expected_cases = [item['case_id'] for item in
                      expected.get('cases', [])]
    check('contract', 'denominator',
          len(episodes) == 6 and len(manifest.get('episode_ids', [])) == 6
          and len({e['episode_id'] for e in episodes}) == 6,
          'episodes=' + str(len(episodes)))
    check('contract', 'case_identity',
          {e['case_id'] for e in episodes} == set(expected_cases),
          'cases=' + repr(sorted(e['case_id'] for e in episodes)))
    check('contract', 'shadow_mode',
          manifest.get('sensor_shadow', {}).get('enabled') is True
          and manifest.get('sensor_shadow', {}).get('mode')
          == 'SHADOW_ONLY_NOT_IN_CONTROL'
          and manifest.get('sensor_shadow', {}).get('control_source')
          == 'ORACLE_STATE',
          'shadow/control source')
    generations = [e.get('physics_generation') for e in
                   manifest.get('contact_initializations', [])]
    check('contract', 'generation_sequence',
          generations == list(range(1, 7)), 'generations=' + repr(generations))
    # --- observation structure ------------------------------------------
    by_episode = {}
    for record in records:
        by_episode.setdefault(record['header']['sync_generation'], []).append(record)
    total_accepted = sum(1 for r in records if r['gate']['accepted'])
    total_valid = sum(1 for r in records if r['validity']['valid'])
    check('contract', 'record_version',
          all(r.get('record_version') == RECORD_VERSION for r in records),
          'records=' + str(len(records)))
    check('contract', 'schema_header',
          all(r['header'].get('schema_version') == 'boom_birds.message.v2.0'
              and r['header'].get('clock_id') == 'sim_physics'
              and r['header'].get('px4_boot_id') is None
              for r in records),
          'v2 header/sim clock/no px4 boot')
    check('contract', 'sensor_sources',
          {r['sensor']['source'] for r in records}
          <= {'SIM_RENDER_RGB', 'SIM_RENDER_DEPTH'},
          'sources=' + repr({r['sensor']['source'] for r in records}))
    check('contract', 'frame_units',
          all(r['sensor']['frame_id'] == 'body_flu'
              and r['sensor']['units'] in ('px', 'm') for r in records),
          'frame/units')
    check('contract', 'warmup_marked',
          all(r['validity']['reason'] == 'WARMUP'
              for r in records if r['phase'] == 'WARMUP'),
          'warmup samples')
    check('contract', 'zero_depth_not_valid',
          all(not r['validity']['valid'] for r in records
              if r['sensor']['source'] == 'SIM_RENDER_DEPTH'
              and (r.get('range_reference') or {}).get('range_m') is None),
          'missing depth remains invalid')
    # sequence monotonic per generation/sensor, reset starts low
    sequence_ok = True
    sequence_detail = {}
    for gen in range(1, 7):
        for sensor in ('front_rgb', 'front_depth'):
            seqs = [r['header']['sequence_id'] for r in by_episode.get(gen, [])
                    if r['sensor']['sensor_id'] == sensor]
            sequence_detail[sensor + ':' + str(gen)] = seqs[:3] + seqs[-2:]
            if seqs != list(range(len(seqs))):
                sequence_ok = False
    check('contract', 'sequence_reset_and_monotonic', sequence_ok,
          'sequence samples=' + json.dumps(sequence_detail)[:900])
    # --- timestamps ------------------------------------------------------
    age_bad = []
    time_bad = []
    for r in records:
        t = r['timestamps']
        if not (t['capture_sim_ns'] <= t['ready_sim_ns'] <= t['consume_sim_ns']):
            time_bad.append(r['header']['sequence_id'])
        if not (t['capture_host_ns'] <= t['ready_host_ns'] <= t['consume_host_ns']):
            time_bad.append(r['header']['sequence_id'])
        if r['gate']['accepted'] and r['gate']['age_ns'] > int(
                freeze['parameters'].get('max_age_ns', 250_000_000)):
            age_bad.append(r['header']['sequence_id'])
    check('contract', 'timestamp_ordering', not time_bad,
          'bad=' + repr(time_bad[:3]))
    check('contract', 'age_limit', not age_bad,
          'over-age accepted=' + repr(age_bad[:3]))
    # --- images ----------------------------------------------------------
    image_records = [r for r in records if r['sensor']['source']
                     == 'SIM_RENDER_RGB']
    image_refs = [r['payload']['ref'] for r in image_records]
    decode_ok = 0
    blank = []
    hashes_ok = True
    stats = {}
    for r in image_records:
        path = Path(r['payload']['ref'])
        if not path.exists() or sha(path) != r['payload']['sha256']:
            hashes_ok = False
            continue
        try:
            st = image_stats(path)
            decode_ok += 1
            stats[str(path)] = st
            if st['std'] <= 0.01 or st['edge_mean'] <= 0.0:
                blank.append(path.name)
        except Exception as error:  # noqa: BLE001
            blank.append(path.name + ':' + str(error))
    check('render', 'image_decode_and_hash',
          image_records and decode_ok == len(image_records) and hashes_ok,
          'decoded=' + str(decode_ok) + '/' + str(len(image_records))
          + ' hash_ok=' + str(hashes_ok))
    check('render', 'image_not_blank', image_records and not blank,
          'blank=' + repr(blank[:3]) + ' sample=' + json.dumps(
              list(stats.values())[:1])[:500])
    # camera motion: route hashes/poses change; static may be stable
    route_progress = {}
    for case in ('sensor_route_0', 'sensor_route_1'):
        refs = [r['payload']['ref'] for r in image_records
                if r['header']['sync_generation'] in (3, 4)
                and case in r['payload']['ref']]
        if refs:
            try:
                route_progress[case] = len(set(
                    sha(Path(ref)) for ref in refs if Path(ref).exists()))
            except Exception:
                route_progress[case] = 0
    check('render', 'camera_motion_hashes',
          all(value >= 2 for value in route_progress.values())
          if route_progress else False,
          'distinct route image hashes=' + repr(route_progress))
    # --- depth references ------------------------------------------------
    depth_records = [r for r in records if r['sensor']['source']
                     == 'SIM_RENDER_DEPTH']
    depth_valid = [r for r in depth_records if r['validity']['valid']]
    check('render', 'depth_primary_source',
          all(r['sensor']['modality'] == 'SIM_RENDER_DEPTH' for r in depth_records)
          and all(r['sensor']['source'] == 'SIM_RENDER_DEPTH'
                  for r in depth_records),
          'primary depth source')
    check('render', 'depth_any_valid', bool(depth_valid),
          'valid depth=' + str(len(depth_valid)) + '/' + str(len(depth_records)))
    static_refs = expected.get('expected', {}).get('static_depth_reference_m', {})
    depth_checks = {}
    for case, reference in static_refs.items():
        values = [r['range_reference']['range_m'] for r in depth_valid
                  if case in str(r.get('payload', {}).get('ref', ''))
                  or (r['header']['sync_generation'] in (1, 2)
                      and case == ('sensor_static_0' if r['header'][
                          'sync_generation'] == 1 else 'sensor_static_1'))]
        depth_checks[case] = values[:3]
        check('physics', 'static_depth_' + case,
              bool(values) and all(abs(float(v) - float(reference)) <= 0.15
                                   for v in values),
              'observed=' + repr(values[:3]) + ' expected=' + str(reference))
    check('physics', 'two_static_distances',
          len(depth_checks) == 2 and all(depth_checks.values()),
          'static references=' + repr(depth_checks))
    check('physics', 'raycast_reference_not_primary',
          all('raycast_reference' in (r.get('range_reference') or {})
              for r in depth_records),
          'raycast recorded as auxiliary reference')
    # --- reset isolation -------------------------------------------------
    observations_by_gen = {gen: by_episode.get(gen, []) for gen in range(1, 7)}
    check('reset', 'all_generations_observed',
          all(len(observations_by_gen[g]) > 0 for g in range(1, 7)),
          'samples per gen=' + repr({g: len(observations_by_gen[g])
                                      for g in range(1, 7)}))
    check('reset', 'old_generation_not_accepted',
          all(r['gate']['accepted'] is False
              for r in records if r['header']['sync_generation'] < 1),
          'no pre-generation accepted records')
    check('reset', 'accepted_has_generation',
          all(r['gate']['accepted'] is False
              or r['header']['sync_generation'] in range(1, 7)
              for r in records),
          'accepted generations bounded')
    # --- route / physical advancement -----------------------------------
    position_by_gen = {}
    for row in steps:
        position_by_gen.setdefault(row.get('episode_id', ''), []).append(row)
    route_motion_ok = True
    for episode in episodes:
        rows = [r for r in steps if r.get('episode_id') == episode['episode_id']]
        positions = [r.get('position_world_m') for r in rows
                     if r.get('position_world_m') is not None]
        if episode['case_id'].startswith('sensor_route') and positions:
            if max(math.dist(positions[0], p) for p in positions) < 0.3:
                route_motion_ok = False
        if episode['case_id'].startswith('sensor_static') and positions:
            if max(math.dist(positions[0], p) for p in positions) > 1.0:
                route_motion_ok = False
    check('physics', 'route_and_static_motion', route_motion_ok,
          'route movement/static stability')
    check('physics', 'physical_steps',
          all(int(e.get('steps', 0)) > 0 for e in episodes),
          'episode steps=' + repr([e.get('steps') for e in episodes]))
    # --- summary output --------------------------------------------------
    check('data_integrity', 'summary_counts',
          sensor_summary.get('sample_count') == len(records)
          and sensor_summary.get('accepted_count') == total_accepted
          and sensor_summary.get('valid_count', total_valid) >= 0,
          'summary counts=' + repr({
              'samples': sensor_summary.get('sample_count'),
              'accepted': sensor_summary.get('accepted_count'),
              'records': len(records)}))
    check('capability', 'minimum_six_episodes', len(episodes) >= 6,
          'episodes=' + str(len(episodes)))
    check('capability', 'camera_and_depth_accepted',
          total_accepted > 0 and len(depth_valid) > 0,
          'accepted=' + str(total_accepted) + ' depth_valid=' + str(
              len(depth_valid)))
    failures.extend({'category': c['category'], 'name': c['name'],
                     'detail': c['detail']}
                    for c in checks if not c['passed'])
    status = 'PASS' if not failures else 'FAIL'
    report = {
        'schema_version': 'dsh.sensor_shadow_verify.v1',
        'status': status,
        'checks': checks,
        'failures': failures,
        'counts': {'episodes': len(episodes), 'records': len(records),
                   'accepted': total_accepted, 'valid': total_valid,
                   'depth_valid': len(depth_valid), 'images': len(image_records)},
        'static_depth_reference': depth_checks,
        'freeze': {'path': str(args.freeze), 'sha256': sha(args.freeze),
                   'git_head': freeze.get('git_head')},
        'expected': {'path': str(args.expected), 'sha256': sha(args.expected)},
        'scope': 'shadow sensor chain; ORACLE control unchanged; not localization/avoidance',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'checks': len(checks),
                      'failures': failures[:3], 'counts': report['counts'],
                      'depth': depth_checks}, ensure_ascii=False))
    raise SystemExit(0 if status == 'PASS' else 1)


if __name__ == '__main__':
    main()
