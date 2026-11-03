"""Independent verification of a layered natural-scenario evaluation run."""
import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.evaluation.episodes import EVALUATION_SCHEMA_ID_V2  # noqa: E402
from boom_birds.sim.disturbance import DisturbanceSpec, wrench_at  # noqa: E402
from boom_birds.sim.layered import (  # noqa: E402
    DISTANCE_BINS,
    BEARING_BINS,
    SCENE_CLASSES,
    STRATA_QUOTAS,
    layered_manifest_sha256,
)

CONTACT_THRESHOLD_N = 0.02


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def wilson(successes, trials, z=1.96):
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()

summary = json.loads((args.run_dir / 'summary.json').read_text(encoding='utf-8'))
manifest = json.loads((args.run_dir / 'manifest.json').read_text(encoding='utf-8'))
scenario_manifest = json.loads((args.run_dir / 'scenario_manifest.json')
                               .read_text(encoding='utf-8'))
episodes = load_jsonl(args.run_dir / 'episodes.jsonl')
steps = load_jsonl(args.run_dir / 'steps.jsonl')
checks = {}


def close(left, right, tolerance=1e-9):
    if left is None or right is None:
        return left is right
    return abs(left - right) <= tolerance


checks['episode_count'] = (len(episodes) == summary['overall']['total_episodes']
                          == summary['total_episodes'] == 125)
checks['class_counts'] = Counter(item['scene_class'] for item in episodes) == {
    name: 25 for name in SCENE_CLASSES}
checks['no_duplicate_episodes'] = len({
    (item['method'], item['scenario_id']) for item in episodes}) == len(episodes)
finite_ok = True
for item in episodes:
    for key in ('duration_s', 'final_distance_m', 'peak_speed_mps', 'min_z_m',
                'contact_force_n', 'max_observation_age_s'):
        value = item.get(key)
        if value is not None and not math.isfinite(value):
            finite_ok = False
checks['episode_values_finite'] = finite_ok
step_finite = True
for item in steps:
    for key in ('time_s', 'speed_mps', 'observation_age_s', 'contact_force_n'):
        value = item.get(key)
        if value is not None and not math.isfinite(value):
            step_finite = False
    for key in ('position_world_m', 'velocity_world_mps'):
        if not all(math.isfinite(value) for value in item[key]):
            step_finite = False
checks['step_values_finite'] = step_finite
checks['scenario_manifest_hash'] = (
    scenario_manifest.get('content_sha256') == layered_manifest_sha256(scenario_manifest)
    and scenario_manifest['content_sha256'] == summary['manifest_sha256'])
checks['outputs_hash_match'] = all(
    __import__('hashlib').sha256((args.run_dir / name).read_bytes()).hexdigest()
    == digest for name, digest in manifest['outputs_sha256'].items())
checks['evaluation_version'] = (
    summary['evaluation_version'] == EVALUATION_SCHEMA_ID_V2
    and manifest.get('evaluation_version') == EVALUATION_SCHEMA_ID_V2)
checks['scenario_quota'] = True
for name in SCENE_CLASSES:
    present = [item for item in scenario_manifest['classes'][name]]
    counts = Counter((item['distance_bin'], item['bearing_bin']) for item in present)
    for row, distance_bin in enumerate(DISTANCE_BINS):
        for col, bearing_bin in enumerate(BEARING_BINS):
            if counts[(distance_bin, bearing_bin)] != STRATA_QUOTAS[row][col]:
                checks['scenario_quota'] = False
steps_by_key = defaultdict(list)
for row in steps:
    steps_by_key[(row['method'], row['scenario_id'])].append(row)
silent_reset = []
for item in episodes:
    seq = steps_by_key[(item['method'], item['scenario_id'])]
    for index, row in enumerate(seq):
        if index == 0:
            continue
        position = row['position_world_m']
        velocity = row['velocity_world_mps']
        quat = row['quat_wxyz']
        if (abs(position[0]) < 1e-6 and abs(position[1]) < 1e-6
                and abs(position[2] - 0.5) < 1e-6
                and max(abs(value) for value in velocity) < 1e-6
                and abs(quat[0] - 1.0) < 1e-6
                and max(abs(quat[1]), abs(quat[2]), abs(quat[3])) < 1e-6):
            silent_reset.append(item['episode_id'])
            break
checks['no_silent_auto_reset'] = not silent_reset

checks['expected_outcomes'] = all(
    item['outcome'] in ('SUCCESS', 'COLLISION', 'TIMEOUT', 'OUT_OF_BOUNDS', 'INVALID')
    for item in episodes)
checks['invalid_reasons_present'] = all(
    item['reason'] for item in episodes if item['outcome'] == 'INVALID')

# Recomputed per-class statistics.
classes_ok = True
for name in SCENE_CLASSES:
    subset = [item for item in episodes if item['scene_class'] == name]
    stated = summary['classes'][name]
    valid = [item for item in subset if item['outcome'] != 'INVALID']
    successful = [item for item in valid if item['outcome'] == 'SUCCESS']
    times = [item['time_to_goal_s'] for item in successful
             if item['time_to_goal_s'] is not None]
    recomputed = {
        'total_episodes': len(subset),
        'valid_episodes': len(valid),
        'invalid_episodes': len(subset) - len(valid),
        'success': len(successful),
        'collision': sum(1 for item in valid if item['outcome'] == 'COLLISION'),
        'timeout': sum(1 for item in valid if item['outcome'] == 'TIMEOUT'),
        'out_of_bounds': sum(1 for item in valid
                             if item['outcome'] == 'OUT_OF_BOUNDS'),
        'success_rate_of_valid': len(successful) / len(valid) if valid else None,
        'mean_time_to_goal_s': sum(times) / len(times) if times else None,
    }
    for key, value in recomputed.items():
        if not close(stated[key], value):
            classes_ok = False
    if stated['success_ci95'] is not None:
        expected_ci = wilson(len(successful), len(valid))
        if not (expected_ci and close(stated['success_ci95'][0], expected_ci[0])
                and close(stated['success_ci95'][1], expected_ci[1])):
            classes_ok = False
checks['class_statistics_recompute'] = classes_ok
checks['overall_statistics_recompute'] = (
    summary['overall']['total_episodes'] == len(episodes)
    and summary['overall']['valid_denominator']
    == sum(1 for item in episodes if item['outcome'] != 'INVALID'))
checks['coverage_claim'] = (
    summary['coverage']['total_valid_episodes'] >= 100
    and summary['coverage']['classes_below_minimum'] == []
    and summary['coverage']['total_meets_requested_minimum'] is True)
checks['status_consistent'] = summary['status'] == 'PASS'
checks['gate_scope'] = summary.get('gate') == 'SIMULATION_EVALUATION_EXTENSION_ONLY_NOT_G4'

# PhysX contact evidence for obstacle collisions.
steps_by_key = defaultdict(list)
for item in steps:
    steps_by_key[(item['method'], item['scenario_id'])].append(item)
contact_ok = True
for item in episodes:
    if item['scene_class'] not in ('B_static', 'C_dynamic'):
        continue
    if item['outcome'] != 'COLLISION':
        continue
    if not item['contact_evidence'] or item['contact_force_n'] < CONTACT_THRESHOLD_N:
        contact_ok = False
    if item.get('contact_step') is None:
        contact_ok = False
        continue
    rows = steps_by_key[(item['method'], item['scenario_id'])]
    row = next((record for record in rows
                if record['step'] == item['contact_step']), None)
    if row is None or not row['contact_evidence'] \
            or row['contact_force_n'] < CONTACT_THRESHOLD_N:
        contact_ok = False
    allowed = (('obs0', 'obs1') if item['scene_class'] == 'B_static'
               else ('mover', 'ball'))
    if not set(row['contacting_obstacles']) & set(allowed):
        contact_ok = False
checks['obstacle_contact_evidence'] = contact_ok

# Degradation: invalid steps counted from raw step records.
degradation_ok = True
for item in episodes:
    if item['scene_class'] != 'D_observation':
        continue
    rows = steps_by_key[(item['method'], item['scenario_id'])]
    invalid_steps = sum(1 for row in rows if not row['observation_valid'])
    if invalid_steps != item['degradation_invalid_steps']:
        degradation_ok = False
    for row in rows:
        if not row['observation_valid']:
            if row['observation_reason'] not in ('DROPOUT', 'STALE'):
                degradation_ok = False
            if row['observation_age_s'] <= 0.0:
                degradation_ok = False
            if tuple(row['position_world_m']) == (0.0, 0.0, 0.0):
                degradation_ok = False
checks['degradation_interface_evidence'] = degradation_ok

# Disturbance: recorded only through the wrench interface and inside its window.
disturbance_ok = True
for item in episodes:
    if item['scene_class'] != 'E_disturbance':
        continue
    rows = steps_by_key[(item['method'], item['scenario_id'])]
    nonzero = [row for row in rows
               if any(abs(value) > 0.0 for value in
                      row['disturbance_force_body_n'] + row['disturbance_torque_body_nm'])]
    if bool(nonzero) != bool(item['disturbance_applied']):
        disturbance_ok = False
    if item['disturbance_applied'] and not nonzero:
        disturbance_ok = False
    for row in nonzero:
        if not math.isfinite(row['observation_age_s']):
            disturbance_ok = False
    scenario = next((entry for entry in scenario_manifest['classes']['E_disturbance']
                     if entry['scenario_id'] == item['scenario_id']), None)
    if scenario is None:
        disturbance_ok = False
        continue
    spec = scenario['disturbance']
    spec_obj = DisturbanceSpec(force_body_n=tuple(spec['force_body_n']),
                               torque_body_nm=tuple(spec['torque_body_nm']),
                               start_s=spec['start_s'], duration_s=spec['duration_s'],
                               ramp_s=spec.get('ramp_s', 0.1))
    for row in rows:
        expected_force, expected_torque = wrench_at(spec_obj, row['time_s'] - 0.05)
        if not (close(row['disturbance_force_body_n'][0], expected_force[0], 1e-9)
                and close(row['disturbance_force_body_n'][1], expected_force[1], 1e-9)
                and close(row['disturbance_force_body_n'][2], expected_force[2], 1e-9)):
            disturbance_ok = False
checks['disturbance_interface_evidence'] = disturbance_ok

# Kinematic and dynamic entity motion evidence for class C.
entity_ok = True
for item in episodes:
    if item['scene_class'] != 'C_dynamic':
        continue
    rows = steps_by_key[(item['method'], item['scenario_id'])]
    if len(rows) < 2:
        entity_ok = False
        continue
    mover_first = rows[0]['entity_poses']['mover']
    mover_last = rows[-1]['entity_poses']['mover']
    ball_first = rows[0]['entity_poses']['ball']
    ball_last = rows[-1]['entity_poses']['ball']
    if math.dist(mover_first, mover_last) < 0.1:
        entity_ok = False
    if math.dist(ball_first, ball_last) < 0.05:
        entity_ok = False
checks['entity_motion_evidence'] = entity_ok

# Freeze consistency.
if args.freeze is not None:
    freeze = json.loads(args.freeze.read_text(encoding='utf-8'))
    import hashlib
    checks['freeze_config_hash'] = (
        freeze['config_sha256']
        == hashlib.sha256(Path(freeze['config']).read_bytes()).hexdigest())
    checks['freeze_scenario_hash'] = (
        freeze['scenario_sha256'] == scenario_manifest['content_sha256'])
    checks['freeze_sample_minimums'] = (
        freeze['min_valid_per_class'] == 20 and freeze['min_valid_total'] == 100)
    checks['freeze_evaluation_version'] = (
        freeze['evaluation_version'] == EVALUATION_SCHEMA_ID_V2)

result = {
    'run_dir': str(args.run_dir),
    'episode_count': len(episodes),
    'step_count': len(steps),
    'checks': checks,
    'status': 'PASS' if all(checks.values()) else 'FAIL',
}
text = json.dumps(result, indent=2, ensure_ascii=False)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + '\n', encoding='utf-8')
raise SystemExit(0 if result['status'] == 'PASS' else 1)