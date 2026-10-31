"""Independent verification of RMUC2027 map dynamics runs."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--freeze', type=Path, required=True)
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


summary = load(args.run_dir / 'summary.json')
manifest = load(args.run_dir / 'manifest.json')
freeze = load(args.freeze)
episodes = load_jsonl(args.run_dir / 'episodes.jsonl')
steps = load_jsonl(args.run_dir / 'steps.jsonl')
checks = {}
checks['summary_status_pass'] = summary.get('status') == 'PASS'
checks['episode_count'] = len(episodes) == freeze['total_episodes']
checks['counts_match_freeze'] = summary['counts'] == freeze['counts']
expected_cases = freeze['case_ids']
per_case = Counter(item['case_id'] for item in episodes)
checks['case_repeats'] = (sorted(per_case) == sorted(expected_cases)
                          and all(count == 2 for count in per_case.values()))
checks['manifest_commit_recorded'] = (
    manifest.get('code_commit') not in (None, '', 'WORKTREE'))
checks['gui_mode'] = manifest.get('gui_mode') is True
checks['map_hash_matches_freeze'] = (
    manifest.get('terrain_sha256') == freeze['terrain_sha256']
    and manifest.get('preview_sha256') == freeze['preview_sha256'])
checks['config_hash_matches_freeze'] = (
    manifest.get('map_config_sha256') == freeze['map_config_sha256'])
checks['cases_hash_matches_freeze'] = (
    manifest.get('cases_sha256') == freeze['cases_sha256'])
checks['outputs_hash_match'] = all(
    sha(args.run_dir / name) == digest
    for name, digest in manifest['outputs_sha256'].items())
checks['freeze_files_hash_match'] = (
    sha(Path('configs/maps/rmuc2027.yaml')) == freeze['map_config_sha256']
    and sha(Path('configs/scenarios/map_cases_v1.json')) == freeze['cases_sha256'])

steps_by_episode = {}
for row in steps:
    steps_by_episode.setdefault(row['episode_id'], []).append(row)
checks['step_record_count'] = all(
    len(steps_by_episode.get(item['episode_id'], [])) == item['steps']
    for item in episodes)

boundary_ok = True
time_ok = True
phase_ok = True
for item in episodes:
    seq = steps_by_episode[item['episode_id']]
    duration_ok = abs(item['duration_s'] - item['steps'] * 0.05) < 1e-6
    time_ok = time_ok and duration_ok
    previous = -0.05
    for index, row in enumerate(seq):
        if row.get('env_truncated') or row.get('env_terminated'):
            boundary_ok = False
        if row.get('episode_length_buf') != index + 1:
            boundary_ok = False
        if not row.get('boundary_count_ok'):
            boundary_ok = False
        if abs(row['time_s'] - previous - 0.05) > 1e-6:
            time_ok = False
        previous = row['time_s']
    phases = [row['phase'] for row in seq]
    if item['kind'] == 'takeoff_landing':
        for required in ('GROUND', 'HOVER', 'DESCEND', 'LANDED'):
            if required not in phases:
                phase_ok = False
        if item['outcome'] != 'SUCCESS':
            phase_ok = False
        if item['contact_max_force_n'] <= 0.02 or not item['contact_prim']:
            phase_ok = False
    if item['kind'] == 'contact':
        if item['outcome'] != 'COLLISION':
            phase_ok = False
        if item['contact_max_force_n'] <= 0.02 or 'Collisions' not in item['contact_prim']:
            phase_ok = False
    if item['kind'] == 'reach' and item['outcome'] not in (
            'SUCCESS', 'COLLISION', 'TIMEOUT', 'OUT_OF_BOUNDS', 'INVALID'):
        phase_ok = False
checks['episode_boundary_clean'] = boundary_ok
checks['step_time_continuity'] = time_ok
checks['phase_and_contact_rules'] = phase_ok
checks['outcome_counts_match_summary'] = all(
    summary['outcomes'][kind][outcome] ==
    sum(1 for item in episodes if item['kind'] == kind and item['outcome'] == outcome)
    for kind in summary['outcomes'] for outcome in summary['outcomes'][kind])

# Deterministic repeats: same case, same final state and outcome.
repeat_ok = True
by_case = {}
for item in episodes:
    by_case.setdefault(item['case_id'], []).append(item)
for case_id, items in by_case.items():
    if len(items) < 2:
        repeat_ok = False
        continue
    first = items[0]
    for other in items[1:]:
        if other['outcome'] != first['outcome']:
            repeat_ok = False
        if math.dist(other['final_position_world_m'],
                     first['final_position_world_m']) > 1e-9:
            repeat_ok = False
checks['repeats_deterministic'] = repeat_ok
screenshots = list((args.run_dir / 'screenshots').glob('*.png')) \
    if (args.run_dir / 'screenshots').exists() else []
checks['screenshots_present'] = len(screenshots) >= 3
checks['screenshots_nonempty'] = all(path.stat().st_size > 1000 for path in screenshots)

# Asset hash check when the local machine config is available.
local_path = Path('configs/maps/rmuc2027.local.yaml')
if local_path.exists():
    local = yaml.safe_load(local_path.read_text(encoding='utf-8'))
    root = Path(local['asset_root'])
    config = yaml.safe_load(Path('configs/maps/rmuc2027.yaml').read_text(encoding='utf-8'))
    terrain = root / config['assets']['terrain_rel']
    checks['asset_hash_on_disk'] = sha(terrain) == freeze['terrain_sha256']

result = {'run_dir': str(args.run_dir), 'checks': checks,
          'screenshots': [str(path) for path in screenshots],
          'status': 'PASS' if all(checks.values()) else 'FAIL'}
text = json.dumps(result, indent=2)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + '\n', encoding='utf-8')
raise SystemExit(0 if result['status'] == 'PASS' else 1)
