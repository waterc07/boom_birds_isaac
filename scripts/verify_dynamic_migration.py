"""Independent record checks for the opt-in production contact/geometry path."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def logical_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def verify(directory, freeze_path):
    directory = Path(directory)
    manifest = load(directory / 'manifest.json')
    freeze = load(freeze_path)
    checks = []

    def check(name, passed):
        checks.append({'name': name, 'passed': bool(passed)})

    check('freeze_hash', manifest['freeze']['sha256'] == sha(freeze_path))
    check('pre_run_freeze', datetime.fromisoformat(freeze['frozen_at'])
          <= datetime.fromisoformat(manifest['started_at']))
    check('source_hashes', all(logical_sha(p) == value for p, value in freeze['source_hashes'].items()))
    check('output_hashes', all(sha(directory / name) == value for name, value
                               in manifest['outputs_sha256'].items()))
    check('gui_mode', manifest['gui_evidence']['gui_mode'] is True
          and manifest['gui_evidence']['headless'] is False)
    check('new_modes', manifest['geometry_policy'] == 'reference_origin_v2'
          and manifest['contact_mode'] == 'measured_hard_reset')
    body = manifest['body_envelope']
    half = body['aabb']['half_extents_m']
    offset = body['aabb']['center_offset_m']
    radius = math.hypot(*(abs(offset[i]) + half[i] for i in range(3)))
    check('reference_origin_radius', math.isclose(radius,
          body['sphere_about_origin']['radius_m'], abs_tol=1e-10))
    rows = [json.loads(line) for line in (directory / 'steps.jsonl').read_text(
        encoding='utf-8').splitlines() if line.strip()]
    episodes = [json.loads(line) for line in (directory / 'episodes.jsonl').read_text(
        encoding='utf-8').splitlines() if line.strip()]
    check('episode_denominator', len(episodes) == len(manifest['episode_ids'])
          == len(set(manifest['episode_ids'])) == len(manifest['contact_initializations']))
    sample_count, raw_errors = 0, []
    geometry_flags, radius_flags, gap_flags = [], [], []
    for row in rows:
        evidence = row.get('contact_evidence') or {}
        sample = evidence.get('measurement')
        if not sample:
            raw_errors.append('missing measurement')
            continue
        try:
            measured = audit_row(sample)
            if not math.isclose(measured['max_filtered_force_n'],
                                sample['measure']['max_filtered_force_n'], abs_tol=1e-9):
                raise ValueError('measurement cache mismatch')
            sample_count += 1
        except (ValueError, KeyError, TypeError) as error:
            raw_errors.append(str(error))
        clearance = row.get('clearance') or {}
        geometry_flags.append(clearance.get('schema_version') == 'boom_birds.clearance.v2')
        robot = (clearance.get('envelopes') or {}).get('robot') or {}
        obstacle = (clearance.get('envelopes') or {}).get('obstacle') or {}
        robot_radius = robot.get('radius_m')
        size = obstacle.get('size_m')
        obstacle_radius = math.hypot(*(v / 2.0 for v in size)) if size else None
        radius_flags.append(robot_radius is not None
              and obstacle_radius is not None
              and math.isclose(robot_radius, radius, abs_tol=1e-9)
              and math.isclose(obstacle['radius_m'], obstacle_radius, abs_tol=1e-9))
        metrics = clearance.get('metrics') or {}
        if metrics.get('center_distance_m') is not None:
            obs = clearance['inputs']['obstacle_observed_center_world_m']
            # Clearance is a PRE-step decision; use its original input, not post-step p.
            pre = clearance['inputs']['robot_center_world_m']
            distance = math.dist(pre, obs)
            gap_flags.append(math.isclose(
                metrics['envelope_gap_sphere_m'], distance - radius - obstacle_radius,
                abs_tol=1e-9))
    check('raw_vectors', bool(rows) and sample_count == len(rows) and not raw_errors)
    check('all_row_geometry_versions', bool(geometry_flags) and all(geometry_flags))
    check('all_row_radii', bool(radius_flags) and all(radius_flags))
    check('all_valid_row_gaps', bool(gap_flags) and all(gap_flags))
    for index, init in enumerate(manifest['contact_initializations'], 1):
        handshake = init['handshake']
        raw = [audit_row(s) for s in handshake['samples']]
        check('generation_' + str(index), init['physics_generation'] == index
              and handshake['physics_generation'] == index)
        check('handshake_' + str(index), handshake['ok'] is True
              and 0 < len(raw) <= handshake['max_steps']
              and raw[-1]['measured_force_n'] <= handshake['zero_tolerance_n'])
    for episode in episodes:
        selected = [r for r in rows if r['episode_id'] == episode['episode_id']]
        forces = [r['contact_evidence']['measurement']['measure']['max_filtered_force_n']
                  for r in selected]
        peak = max(forces, default=0.0)
        check('physical_' + episode['episode_id'], episode['physical_outcome']
              == ('CONTACT_MEASURED' if peak > 1e-6 else 'UNKNOWN'))
    failures = [c for c in checks if not c['passed']]
    return {'status': 'PASS' if not failures else 'FAIL', 'checks': checks,
            'failures': failures, 'raw_errors': raw_errors, 'rows': len(rows),
            'episodes': len(episodes),
            'scope': 'source/record consistency and positive force; negative contact coverage unverified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run, args.freeze)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'rows', 'episodes', 'failures', 'raw_errors')}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
