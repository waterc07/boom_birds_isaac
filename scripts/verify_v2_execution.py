"""Independent verifier for the v2 execution gate, faults and regressions."""
import argparse, hashlib, json, math
from collections import Counter
from pathlib import Path

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dynamic-dir', type=Path, required=True)
parser.add_argument('--dynamic-freeze', type=Path, required=True)
parser.add_argument('--fault-dir', type=Path, required=True)
parser.add_argument('--fault-freeze', type=Path, required=True)
parser.add_argument('--regression-dir', type=Path, required=True)
parser.add_argument('--regression-freeze', type=Path, required=True)
parser.add_argument('--prior-v1-summary', type=Path,
                    default=Path('docs/reports/map_eval/dynamic/evidence/summary.json'))
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()

checks = {}
notes = {}

def load_run(run_dir, freeze):
    summary = load(run_dir / 'summary.json')
    manifest = load(run_dir / 'manifest.json')
    episodes = load_jsonl(run_dir / 'episodes.jsonl')
    steps = load_jsonl(run_dir / 'steps.jsonl')
    steps_by = {}
    for row in steps:
        steps_by.setdefault(row['episode_id'], []).append(row)
    return summary, manifest, episodes, steps_by, freeze

dynamic_summary, dynamic_manifest, dynamic_episodes, dynamic_steps, dynamic_freeze = load_run(
    args.dynamic_dir, load(args.dynamic_freeze))
fault_summary, fault_manifest, fault_episodes, fault_steps, fault_freeze = load_run(
    args.fault_dir, load(args.fault_freeze))
reg_summary, reg_manifest, reg_episodes, reg_steps, reg_freeze = load_run(
    args.regression_dir, load(args.regression_freeze))

checks['dynamic_status'] = dynamic_summary.get('status') == 'PASS'
checks['dynamic_execution_path'] = (dynamic_summary.get('execution_path') == 'v2'
                                    and dynamic_manifest.get('renderer', '').startswith('DirectX'))
checks['dynamic_denominator'] = (len(dynamic_episodes) == dynamic_freeze['total_episodes']
                                 and dynamic_summary.get('methods') == ['supervisor'])
checks['dynamic_gui'] = dynamic_manifest.get('gui_mode') is True
checks['dynamic_commit'] = dynamic_manifest.get('code_commit') not in (None, '', 'WORKTREE')
checks['dynamic_hashes'] = (dynamic_manifest.get('cases_sha256') == dynamic_freeze['cases_sha256']
                            and all(sha(args.dynamic_dir / name) == digest for name, digest in
                                    dynamic_manifest.get('outputs_sha256', {}).items()))

def check_steps(episodes, steps_by, check_v2=True, check_rejected=False):
    result = {'step_count': True, 'admission': True, 'execution': True,
              'trace': True, 'boundary': True, 'time': True, 'action_ttl': True}
    for item in episodes:
        seq = steps_by.get(item['episode_id'], [])
        terminal_extra = (item['outcome'] == 'ABORT' and seq
                          and (seq[-1].get('v2_admission') == 'REJECTED'
                               or seq[-1].get('supervisor_state') == 'ABORT'))
        expected = item['steps'] + (1 if terminal_extra else 0)
        if len(seq) != expected:
            result['step_count'] = False
        previous = None
        for index, row in enumerate(seq):
            if previous is None:
                if abs(row['time_s'] - 0.05) > 1e-6:
                    result['time'] = False
            elif row['time_s'] - previous < -1e-9 or row['time_s'] - previous > 0.0500001:
                result['time'] = False
            previous = row['time_s']
            if not row.get('boundary_count_ok'):
                if not (item['outcome'] == 'ABORT' and row.get('v2_admission') == 'REJECTED'):
                    result['boundary'] = False
            if entry := row.get('v2_admission'):
                if entry not in ('ADMITTED', 'REJECTED'):
                    result['admission'] = False
            if item['outcome'] != 'ABORT' and row.get('v2_admission') != 'ADMITTED':
                result['admission'] = False
            if row.get('v2_admission') == 'ADMITTED':
                if not row.get('v2_executed') or not row.get('v2_action_id'):
                    result['execution'] = False
                if not row.get('v2_observation_id') or not row.get('v2_context'):
                    result['trace'] = False
                if row.get('v2_context_owner') != 'STUDENT':
                    result['trace'] = False
                issued = row.get('v2_issued_at_ns', 0)
                expires = row.get('v2_expires_at_ns', 0)
                if not (0 < expires - issued <= 150_000_000 + 1):
                    result['action_ttl'] = False
                if int(round(row['time_s'] * 1_000_000_000)) < issued:
                    result['trace'] = False
    return result

dynamic_checks = check_steps(dynamic_episodes, dynamic_steps)
for key, value in dynamic_checks.items():
    checks['dynamic_' + key] = value
checks['dynamic_admission_counts'] = all(
    item.get('v2_rejected_count') == 0 for item in dynamic_episodes)
checks['dynamic_outcomes'] = all(
    item['outcome'] in ('SUCCESS', 'ABORT') for item in dynamic_episodes)

# Prior v1 comparison.
prior = load(args.prior_v1_summary)
prior_supervisor = {item['case_id']: item for item in prior['episodes']
                    if item['method'] == 'supervisor'}
v2_by_case = {item['case_id']: item for item in dynamic_episodes}
comparison = {'cases': 0, 'outcome_differences': [], 'duration_differences': []}
for case_id, item in sorted(v2_by_case.items()):
    comparison['cases'] += 1
    old = prior_supervisor.get(case_id)
    if old is None:
        comparison['outcome_differences'].append({'case_id': case_id, 'v1': 'MISSING'})
        continue
    if old['outcome'] != item['outcome']:
        comparison['outcome_differences'].append({'case_id': case_id,
                                                  'v1': old['outcome'],
                                                  'v2': item['outcome']})
    comparison['duration_differences'].append({
        'case_id': case_id, 'v1_s': old['duration_s'], 'v2_s': item['duration_s'],
        'delta_s': round(item['duration_s'] - old['duration_s'], 3)})
checks['v1_parity'] = (comparison['cases'] == 20
                       and not comparison['outcome_differences'])
notes['v1_comparison'] = comparison

# Fault checks.
fault_checks = check_steps(fault_episodes, fault_steps)
for key, value in fault_checks.items():
    checks['fault_' + key] = value
expected_reason = {
    'ttl_expiry': {'REJECT_TTL_EXPIRED'},
    'cache_resend': {'ACTION_EXPIRED'},
    'out_of_order': {'REJECT_SUPERSEDED', 'REJECT_OUT_OF_ORDER',
                     'REJECT_SEQUENCE_REUSE'},
    'context_reset': {'REJECT_MISSION_EPOCH'},
    'px4_boot_change': {'REJECT_SYNC_OR_PX4_BOOT'},
    'clock_sync_mismatch': {'REJECT_CLOCK_DOMAIN'},
    'ownership_revoke': {'REJECT_OWNER', 'REJECT_CONTROL_EPOCH'},
}
fault_ok = True
fault_table = []
for item in fault_episodes:
    seq = fault_steps.get(item['episode_id'], [])
    last = seq[-1] if seq else {}
    allowed = expected_reason.get(item.get('fault_type'), set())
    reason = item.get('v2_reject_reason', '')
    table = {'episode_id': item['episode_id'], 'fault_type': item.get('fault_type'),
             'outcome': item['outcome'], 'reason': reason,
             'executed': last.get('v2_executed'),
             'admission': last.get('v2_admission')}
    fault_table.append(table)
    if item['outcome'] != 'ABORT':
        fault_ok = False
    if reason not in allowed:
        fault_ok = False
    if last.get('v2_admission') != 'REJECTED' or last.get('v2_executed'):
        fault_ok = False
checks['fault_expected'] = fault_ok
checks['fault_denominator'] = (len(fault_episodes) == fault_freeze['total_episodes']
                               and len({item.get('fault_type') for item in fault_episodes}) >= 6)
checks['fault_no_execution_after_reject'] = all(
    (not fault_steps.get(item['episode_id'], []))
    or not fault_steps[item['episode_id']][-1].get('v2_executed')
    for item in fault_episodes)
checks['fault_status'] = fault_summary.get('status') == 'PASS'
checks['fault_gui'] = fault_manifest.get('gui_mode') is True
checks['fault_commit'] = fault_manifest.get('code_commit') not in (None, '', 'WORKTREE')
checks['fault_hashes'] = (fault_manifest.get('cases_sha256') == fault_freeze['cases_sha256']
                          and all(sha(args.fault_dir / name) == digest
                                  for name, digest in fault_manifest.get('outputs_sha256', {}).items()))
checks['regression_status'] = reg_summary.get('status') == 'PASS'
checks['regression_gui'] = reg_manifest.get('gui_mode') is True
checks['regression_commit'] = reg_manifest.get('code_commit') not in (None, '', 'WORKTREE')
notes['fault_table'] = fault_table

# Regression checks.
reg_checks = check_steps(reg_episodes, reg_steps)
for key, value in reg_checks.items():
    checks['regression_' + key] = value
checks['regression_success'] = (len(reg_episodes) == 8
                                and all(item['outcome'] == 'SUCCESS' for item in reg_episodes)
                                and all(item.get('v2_rejected_count') == 0
                                        for item in reg_episodes))
checks['regression_hashes'] = (reg_manifest.get('cases_sha256') == reg_freeze['cases_sha256'])

checks['status'] = all(checks.values())
result = {
    'status': 'PASS' if checks['status'] else 'FAIL',
    'checks': checks,
    'notes': notes,
    'dynamic_outcomes': dynamic_summary.get('outcomes'),
    'fault_outcomes': fault_summary.get('outcomes'),
    'regression_outcomes': reg_summary.get('outcomes'),
    'fault_table': fault_table,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({'status': result['status'], 'failed': [k for k, v in checks.items() if not v],
                  'notes': notes.get('v1_comparison')}, indent=2))