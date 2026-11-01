"""Independent verification for the dynamic-obstacle paired evaluation."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.sim.dynamic_obstacle import load_obstacle_spec


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--freeze', type=Path, required=True)
parser.add_argument('--regression-dir', type=Path, default=None)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()

freeze = load_json(args.freeze)
summary = load_json(args.run_dir / 'summary.json')
manifest = load_json(args.run_dir / 'manifest.json')
episodes = load_jsonl(args.run_dir / 'episodes.jsonl')
steps = load_jsonl(args.run_dir / 'steps.jsonl')
cases_payload = load_json(Path(freeze['cases_file']))
case_specs = {item['case_id']: item for item in cases_payload['cases']}
steps_by_episode = {}
for row in steps:
    steps_by_episode.setdefault(row['episode_id'], []).append(row)

checks = {}
checks['summary_pass'] = summary.get('status') == 'PASS'
checks['episode_count'] = len(episodes) == freeze['total_episodes']
checks['methods_match'] = summary.get('methods') == freeze['methods']
checks['counts_match'] = summary.get('counts') == freeze['counts']
checks['case_denominator'] = sorted({item['case_id'] for item in episodes}) == sorted(freeze['case_ids'])
checks['pairs_complete'] = all(
    sum(1 for item in episodes if item['case_id'] == case_id and item['method'] == method) == 1
    for case_id in freeze['case_ids'] for method in freeze['methods'])
checks['class_denominator'] = all(
    sum(1 for case_id in freeze['case_ids']
        if case_specs[case_id].get('scenario_class') == name) == 4
    for name in ('A', 'B', 'C', 'D', 'E'))
checks['manifest_commit'] = manifest.get('code_commit') not in (None, '', 'WORKTREE')
checks['gui_mode'] = manifest.get('gui_mode') is True
checks['map_hash'] = (manifest.get('terrain_sha256') == freeze['terrain_sha256']
                      and manifest.get('preview_sha256') == freeze['preview_sha256'])
checks['cases_hash'] = manifest.get('cases_sha256') == freeze['cases_sha256']
checks['outputs_hash'] = all(
    sha(args.run_dir / name) == digest
    for name, digest in manifest.get('outputs_sha256', {}).items())
checks['freeze_files'] = (sha(Path(freeze['cases_file'])) == freeze['cases_sha256']
                          and sha(Path(freeze['map_config_file'])) == freeze['map_config_sha256'])
checks['summary_outcomes_match'] = all(
    summary['outcomes'][method][outcome] ==
    sum(1 for item in episodes if item['method'] == method and item['outcome'] == outcome)
    for method in freeze['methods'] for outcome in summary['outcomes'][method])

step_count_ok = True
boundary_ok = True
time_ok = True
obstacle_ok = True
observation_ok = True
state_ok = True
contact_ok = True
min_distances = {}
for item in episodes:
    seq = steps_by_episode.get(item['episode_id'], [])
    if len(seq) != item['steps']:
        step_count_ok = False
    previous = None
    for index, row in enumerate(seq):
        if previous is None:
            if abs(row['time_s'] - 0.05) > 1e-6:
                time_ok = False
        elif abs(row['time_s'] - previous - 0.05) > 1e-6:
            # ABORT rows can be emitted before a physics step; allow equal/next dt.
            if not (row['time_s'] - previous <= 0.0500001):
                time_ok = False
        previous = row['time_s']
        if not row.get('boundary_count_ok'):
            if not (item['method'] == 'supervisor' and row.get('outcome') == 'ABORT'
                    and row.get('supervisor_state') == 'ABORT'):
                boundary_ok = False
        if row.get('env_terminated') or row.get('env_truncated'):
            boundary_ok = False
        if not (item['method'] == 'supervisor' and row.get('outcome') == 'ABORT'
                and row.get('episode_length_buf') == 0):
            if row.get('episode_length_buf') != index + 1:
                boundary_ok = False
        spec = load_obstacle_spec(case_specs[item['case_id']]['obstacle'])
        expected_position, _ = spec.pose_at(row['time_s'])
        if math.dist(expected_position, row['obstacle_position_world_m']) > 1e-3:
            obstacle_ok = False
        expected_obs = spec.observation_at(row['time_s'])
        if bool(expected_obs['valid']) != bool(row['observation_valid']):
            observation_ok = False
        if expected_obs['valid'] and abs(expected_obs['age_s'] - row['observation_age_s']) > 1e-6:
            observation_ok = False
        if item['method'] == 'supervisor':
            allowed = {'FOLLOW', 'BRAKE', 'HOLD', 'WAIT', 'RESUME',
                       'DEGRADED', 'ABORT', 'SUCCESS'}
            if row['supervisor_state'] not in allowed:
                state_ok = False
        if row['contact_force_n'] > 0.02 and 'Obstacle' not in row.get('contact_prim', ''):
            contact_ok = False
        distance = math.dist(row['position_world_m'], row['obstacle_position_world_m'])
        min_distances[item['episode_id']] = min(
            min_distances.get(item['episode_id'], 1e9), distance)
    if item['method'] == 'supervisor':
        state_rows = [row['supervisor_state'] for row in seq]
        transitions = sum(1 for left, right in zip(state_rows, state_rows[1:])
                          if left != right)
        if transitions != item.get('state_transitions'):
            state_ok = False
        if sorted(set(state_rows)) != item.get('states'):
            state_ok = False
    if item['outcome'] == 'COLLISION':
        if item.get('contact_max_force_n', 0.0) <= 0.02 or not item.get('contact_prim'):
            contact_ok = False
    if item['outcome'] not in ('SUCCESS', 'COLLISION', 'TIMEOUT',
                               'OUT_OF_BOUNDS', 'ABORT', 'INVALID'):
        contact_ok = False
checks['step_count'] = step_count_ok
checks['episode_boundary'] = boundary_ok
checks['time_continuity'] = time_ok
checks['obstacle_trajectory'] = obstacle_ok
checks['observation_contract'] = observation_ok
checks['supervisor_states'] = state_ok
checks['contact_evidence'] = contact_ok

# Expected behavior by scenario class (defined before the run).
behavior = {}
for name in ('A', 'B', 'C', 'D', 'E'):
    subset = [item for item in episodes if item['scenario_class'] == name]
    supervisor = [item for item in subset if item['method'] == 'supervisor']
    if name == 'A':
        behavior[name] = all(item['wait_total_s'] <= 0.5
                             and not ({'BRAKE', 'HOLD', 'WAIT'} & set(item['states']))
                             for item in supervisor)
    elif name == 'B':
        behavior[name] = any(item['wait_total_s'] > 0.5
                             and 'RESUME' in item['states']
                             and item['outcome'] == 'SUCCESS'
                             for item in supervisor)
    elif name == 'C':
        behavior[name] = all(item['outcome'] == 'ABORT'
                             and item['reason'] == 'MAX_WAIT_EXCEEDED'
                             for item in supervisor)
    elif name == 'D':
        behavior[name] = all(item['state_transitions'] <= 8 for item in supervisor)
    else:
        behavior[name] = all(item['outcome'] == 'ABORT'
                             and item['reason'] in ('OBSERVATION_STALE',
                                                    'MAX_WAIT_EXCEEDED')
                             and 'DEGRADED' in item['states']
                             for item in supervisor)
checks['expected_behaviors'] = behavior

# Paired consistency: same case, same route/start/goal/obstacle contract.
paired_ok = True
pair_table = []
by_case = {}
for item in episodes:
    by_case.setdefault(item['case_id'], {})[item['method']] = item
for case_id, methods in by_case.items():
    if set(methods) != set(freeze['methods']):
        paired_ok = False
        continue
    left = methods['follow_only']
    right = methods['supervisor']
    for key in ('start_position_world_m', 'goal_position_world_m', 'waypoints'):
        if left[key] != right[key]:
            paired_ok = False
    if case_specs[case_id].get('obstacle') != left.get('obstacle'):
        paired_ok = False
    pair_table.append({
        'case_id': case_id, 'class': left['scenario_class'],
        'route_id': left['route_id'],
        'follow_only': {'outcome': left['outcome'],
                        'wait_s': left['wait_total_s'],
                        'transitions': left['state_transitions']},
        'supervisor': {'outcome': right['outcome'], 'reason': right['reason'],
                       'wait_s': right['wait_total_s'],
                       'transitions': right['state_transitions'],
                       'states': right['states']},
        'min_center_distance_m': min_distances.get(
            left['episode_id'], min_distances.get(right['episode_id'])),
    })
checks['paired_consistency'] = paired_ok

# Regression: the original no-dynamic 8 route episodes.
regression_ok = True
regression_info = None
if args.regression_dir is not None:
    reg_summary = load_json(args.regression_dir / 'summary.json')
    reg_episodes = load_jsonl(args.regression_dir / 'episodes.jsonl')
    regression_ok = (
        len(reg_episodes) == 8
        and all(item['outcome'] == 'SUCCESS' for item in reg_episodes)
        and all(item.get('contact_max_force_n', 0.0) <= 0.02 for item in reg_episodes)
        and reg_summary.get('status') == 'PASS')
    regression_info = {'episodes': len(reg_episodes),
                       'outcomes': Counter(item['outcome'] for item in reg_episodes)}
checks['regression_routes'] = regression_ok

checks['status'] = all(checks.values())
result = {
    'run_dir': str(args.run_dir),
    'freeze': str(args.freeze),
    'checks': checks,
    'behavior': behavior,
    'pairs': pair_table,
    'min_center_distance_note': 'center-to-center distance; not body surface clearance',
    'min_center_distances_m': min_distances,
    'regression': regression_info,
    'status': 'PASS' if checks['status'] else 'FAIL',
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n',
                       encoding='utf-8')
print(json.dumps({key: result[key] for key in
                  ('status', 'checks', 'behavior', 'regression')}, indent=2))
