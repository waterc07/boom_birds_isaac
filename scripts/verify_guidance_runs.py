"""Independently re-derive comparison/fault metrics from episodes.jsonl."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()

summary = json.loads((args.run_dir / 'summary.json').read_text(encoding='utf-8'))
episodes = [json.loads(line) for line in
            (args.run_dir / 'episodes.jsonl').read_text(encoding='utf-8').splitlines()
            if line.strip()]
checks = {}


def close(left, right, tolerance=1e-9):
    if left is None or right is None:
        return left is right
    return abs(left - right) <= tolerance


def wilson(successes, trials, z=1.96):
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


checks['episode_count_matches_summary'] = len(episodes) == summary['total_episodes']
checks['no_duplicate_method_scenario'] = len({
    (item.get('fault', 'none'), item['method'], item['scenario_id'])
    for item in episodes}) == len(episodes)
finite_ok = True
for item in episodes:
    for key in ('duration_s', 'final_distance_m', 'peak_speed_mps', 'min_z_m',
                'start_yaw_rad', 'time_to_goal_s'):
        value = item.get(key)
        if value is not None and not math.isfinite(value):
            finite_ok = False
    for key in ('start_position_world_m', 'goal_position_world_m'):
        if not all(math.isfinite(value) for value in item[key]):
            finite_ok = False
checks['all_numeric_fields_finite'] = finite_ok
checks['scenario_hash_matches'] = (
    summary['scenarios']['content_sha256']
    == json.loads((args.run_dir / 'scenario_manifest.json')
                  .read_text(encoding='utf-8'))['content_sha256'])

methods = summary['methods']
by_method = {name: [item for item in episodes if item['method'] == name]
             for name in methods}
if summary['faults'] == ['none']:
    for name in methods:
        subset = by_method[name]
        expected = summary['methods_summary'][name]
        valid = [item for item in subset if item['outcome'] != 'INVALID']
        success = [item for item in valid if item['outcome'] == 'SUCCESS']
        times = [item['time_to_goal_s'] for item in success
                 if item['time_to_goal_s'] is not None]
        checks['method_' + name + '_counts'] = (
            expected['total_episodes'] == len(subset)
            and expected['valid_episodes'] == len(valid)
            and expected['invalid_episodes'] == len(subset) - len(valid)
            and expected['success'] == len(success)
            and expected['collision'] == sum(1 for item in valid
                                             if item['outcome'] == 'COLLISION')
            and expected['timeout'] == sum(1 for item in valid
                                           if item['outcome'] == 'TIMEOUT'))
        checks['method_' + name + '_rates'] = (
            close(expected['success_rate_of_valid'],
                  len(success) / len(valid) if valid else None)
            and close(expected['mean_time_to_goal_s'],
                      sum(times) / len(times) if times else None)
            and close(expected['mean_final_distance_m'],
                      sum(item['final_distance_m'] for item in subset) / len(subset)))
        computed_ci = wilson(len(success), len(valid))
        checks['method_' + name + '_wilson'] = (
            expected['success_ci95'] is None if computed_ci is None
            else close(expected['success_ci95'][0], computed_ci[0], 1e-9)
            and close(expected['success_ci95'][1], computed_ci[1], 1e-9))
    if len(methods) == 2:
        left = {item['scenario_id']: item for item in by_method[methods[0]]}
        right = {item['scenario_id']: item for item in by_method[methods[1]]}
        shared = sorted(set(left) & set(right))
        pairs = summary['paired']
        both = sum(1 for key in shared
                   if left[key]['outcome'] == 'SUCCESS'
                   and right[key]['outcome'] == 'SUCCESS')
        a_only = sum(1 for key in shared
                     if left[key]['outcome'] == 'SUCCESS'
                     and right[key]['outcome'] != 'SUCCESS')
        b_only = sum(1 for key in shared
                     if right[key]['outcome'] == 'SUCCESS'
                     and left[key]['outcome'] != 'SUCCESS')
        deltas = [right[key]['time_to_goal_s'] - left[key]['time_to_goal_s']
                  for key in shared
                  if left[key]['outcome'] == 'SUCCESS'
                  and right[key]['outcome'] == 'SUCCESS'
                  and left[key]['time_to_goal_s'] is not None
                  and right[key]['time_to_goal_s'] is not None]
        checks['paired_counts'] = (
            pairs['pairs_total'] == len(shared) and pairs['pairs_both_success'] == both
            and pairs['a_only_success'] == a_only
            and pairs['b_only_success'] == b_only)
        checks['paired_deltas'] = close(
            pairs['mean_time_delta_b_minus_a_s'],
            sum(deltas) / len(deltas) if deltas else None)
    checks['natural_status_rule'] = (
        summary['status'] == ('INCOMPLETE'
                              if summary['total_episodes'] < 100 else 'PASS'))
else:
    expected_outcomes = {
        'collision_flag': 'COLLISION', 'collision_contact': 'COLLISION',
        'timeout': 'TIMEOUT', 'invalid_observation': 'INVALID'}
    for kind, expected in expected_outcomes.items():
        subset = [item for item in episodes if item['fault'] == kind]
        counts = {outcome: sum(1 for item in subset if item['outcome'] == outcome)
                  for outcome in ('SUCCESS', 'COLLISION', 'TIMEOUT', 'INVALID')}
        stated = summary['fault_summary'][kind]
        checks['fault_' + kind + '_samples'] = len(subset) >= 1
        checks['fault_' + kind + '_classification'] = (
            counts[expected] == len(subset)
            and all(item['outcome'] == expected for item in subset)
            and stated['counts'] == counts)
        if kind == 'collision_contact':
            checks['fault_collision_contact_is_physx'] = (
                stated['effect_scope'] == 'PHYSX_CONTACT'
                and all(item['contact_observed'] for item in subset))
        if kind == 'collision_flag':
            checks['fault_collision_flag_is_contract_only'] = (
                stated['effect_scope'] == 'CONTRACT_PATH_ONLY'
                and not any(item['contact_observed'] for item in subset))
        if kind == 'invalid_observation':
            checks['fault_invalid_is_interface_layer'] = (
                stated['effect_scope'] == 'INTERFACE_LAYER'
                and all(item['reason'] == 'NONFINITE' for item in subset)
                and all(item['injected_observation_step'] is not None
                        for item in subset))
    checks['fault_natural_rates_excluded'] = summary['natural_performance_rates_excluded']
    checks['fault_status_rule'] = summary['status'] == (
        'PASS' if all(summary['fault_summary'][kind]['classification_ok']
                      for kind in summary['fault_summary']) else 'FAIL')

boundary_present = all(item.get('env_truncated') is not None for item in episodes)
checks['episode_boundary_fields_present'] = boundary_present
if boundary_present:
    checks['no_environment_truncation'] = all(
        not item['env_truncated'] for item in episodes)
    checks['boundary_counter_clean'] = all(
        item['boundary_count_ok'] or item['env_terminated'] for item in episodes)
    checks['duration_matches_steps'] = all(
        abs(item['duration_s'] - item['steps'] * 0.05) < 1e-6 for item in episodes)
    if len(methods) == 2 and summary['faults'] == ['none']:
        checks['paired_scenario_sets_equal'] = (
            {item['scenario_id'] for item in by_method[methods[0]]}
            == {item['scenario_id'] for item in by_method[methods[1]]})

result = {
    'run_dir': str(args.run_dir),
    'episode_count': len(episodes),
    'checks': checks,
    'status': 'PASS' if all(checks.values()) else 'FAIL',
}
text = json.dumps(result, indent=2)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + '\n', encoding='utf-8')
raise SystemExit(0 if result['status'] == 'PASS' else 1)
