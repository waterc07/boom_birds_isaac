"""Independent verification of clean velocity/reach baseline runs."""
import argparse
import ast
import csv
import json
import math
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--velocity-json', type=Path, default=None)
parser.add_argument('--velocity-csv', type=Path, default=None)
parser.add_argument('--reach-csv', type=Path, action='append', default=[])
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()

checks = {}


def parse_list(value):
    return ast.literal_eval(value) if value else []


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


if args.velocity_json is not None and args.velocity_csv is not None:
    source = json.loads(args.velocity_json.read_text(encoding='utf-8'))
    rows = read_csv(args.velocity_csv)
    checks['velocity_row_count'] = source['row_count'] == len(rows)
    checks['velocity_status_pass'] = source['status'] == 'PASS'
    checks['velocity_checks_all_pass'] = all(source['checks'].values())
    boundary_keys = {'env_terminated', 'env_truncated', 'episode_length_buf',
                     'boundary_count_ok'}
    checks['velocity_boundary_fields_present'] = all(
        boundary_keys.issubset(row.keys()) for row in rows)
    if checks['velocity_boundary_fields_present']:
        checks['velocity_no_truncation'] = all(
            row['env_truncated'].strip().lower() == 'false' for row in rows)
        checks['velocity_no_termination'] = all(
            row['env_terminated'].strip().lower() == 'false' for row in rows)
        groups = {}
        for row in rows:
            groups.setdefault(row['scenario'], []).append(row)
        continuity = True
        time_ok = True
        for scenario, group in groups.items():
            previous = None
            for row in group:
                step = int(row['step'])
                buffer_value = int(row['episode_length_buf'])
                if previous is not None:
                    delta = buffer_value - previous
                    if scenario == 'reset_old_epoch' and delta < 0:
                        continuity = continuity and buffer_value == 1
                    else:
                        continuity = continuity and delta == 1
                previous = buffer_value
            for left, right in zip(group, group[1:]):
                time_ok = time_ok and abs(
                    float(right['time_s']) - float(left['time_s']) - 0.05) < 1e-9
        checks['velocity_counter_continuity'] = continuity
        checks['velocity_time_step'] = time_ok

for reach_path in args.reach_csv:
    rows = read_csv(reach_path)
    groups = {}
    for row in rows:
        groups.setdefault(int(row['episode']), []).append(row)
    name = reach_path.parent.name
    checks['reach_' + name + '_samples'] = len(groups) == 6
    boundary_ok = True
    terminal_ok = True
    time_ok = True
    outcome_ok = True
    for episode, group in groups.items():
        terminal_seen = False
        previous_time = None
        for row in group:
            if str(row.get('env_truncated', '')).strip().lower() == 'true':
                boundary_ok = False
            terminal = str(row.get('env_terminated', '')).strip().lower() == 'true'
            has_terminal_fields = 'env_terminated' in row
            if not has_terminal_fields:
                boundary_ok = False
            if terminal:
                terminal_seen = True
                if row['outcome'] not in ('COLLISION', 'OUT_OF_BOUNDS'):
                    terminal_ok = False
            if previous_time is not None:
                time_ok = time_ok and abs(
                    float(row['time_s']) - previous_time - 0.05) < 1e-9
            previous_time = float(row['time_s'])
        final = group[-1]
        if final['outcome'] not in ('SUCCESS', 'COLLISION', 'TIMEOUT',
                                    'OUT_OF_BOUNDS'):
            outcome_ok = False
    checks['reach_' + name + '_no_truncation'] = boundary_ok
    checks['reach_' + name + '_terminal_classification'] = terminal_ok
    checks['reach_' + name + '_time_step'] = time_ok
    checks['reach_' + name + '_outcomes'] = outcome_ok

result = {
    'velocity_json': None if args.velocity_json is None else str(args.velocity_json),
    'velocity_csv': None if args.velocity_csv is None else str(args.velocity_csv),
    'reach_csv': [str(path) for path in args.reach_csv],
    'checks': checks,
    'status': 'PASS' if checks and all(checks.values()) else 'FAIL',
}
text = json.dumps(result, indent=2)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + '\n', encoding='utf-8')
raise SystemExit(0 if result['status'] == 'PASS' else 1)
