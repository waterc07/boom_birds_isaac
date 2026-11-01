"""Independent verification for brake and post-fault experiments."""
import argparse, hashlib, json, math
from collections import Counter
from pathlib import Path

def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def load_jsonl(p): return [json.loads(l) for l in Path(p).read_text(encoding='utf-8').splitlines() if l.strip()]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--freeze', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
freeze = load(args.freeze); summary = load(args.run_dir/'summary.json')
manifest = load(args.run_dir/'manifest.json'); episodes = load_jsonl(args.run_dir/'episodes.jsonl')
steps = load_jsonl(args.run_dir/'steps.jsonl')
steps_by = {}
for row in steps: steps_by.setdefault(row['case_id'], []).append(row)
checks = {}
brake = [x for x in episodes if x['kind'] == 'brake']
fault = [x for x in episodes if x['kind'] == 'fault']
checks['counts'] = (len(brake) == 36 and len(fault) == 8
                    and summary['counts'] == {'brake': 36, 'fault': 8})
checks['status'] = summary.get('status') == 'PASS'
checks['gui'] = manifest.get('gui_mode') is True
checks['commit'] = manifest.get('code_commit') not in (None, '', 'WORKTREE')
checks['hashes'] = (manifest.get('cases_sha256') == freeze['cases_sha256']
                    and all(sha(args.run_dir/name) == digest
                            for name, digest in manifest.get('outputs_sha256', {}).items()))
checks['freeze_cases'] = sha(Path(freeze['cases_file'])) == freeze['cases_sha256']

# Coverage: 3 speeds x 2 headings x 3 directions x 2 repeats.
coverage = Counter()
for item in brake:
    coverage[(item['speed_mps'], round(item['heading_rad'], 2),
              tuple(round(v, 3) for v in item['direction_world']))] += 1
checks['coverage'] = (len(coverage) == 18 and all(v == 2 for v in coverage.values()))

def recompute(item):
    rows = steps_by.get(item['case_id'], [])
    if item['kind'] == 'brake':
        start = item['brake_start']; rows = [r for r in rows if r['phase'] == 'BRAKE']
    else:
        start = item['fault_start']; rows = [r for r in rows if r['phase'] == 'FAULT_OBSERVE']
    if not start or not rows:
        return None
    final = rows[-1]['position_world_m']
    v = start['velocity']; norm = math.sqrt(sum(x*x for x in v))
    unit = [x/norm for x in v] if norm > 1e-9 else [0,0,0]
    delta = [final[i]-start['position'][i] for i in range(3)]
    along = sum(delta[i]*unit[i] for i in range(3))
    lateral = math.sqrt(max(0.0, sum(x*x for x in delta) - along*along))
    return {'along_m': along, 'lateral_m': lateral,
            'time_s': rows[-1]['time_s'] - start['time_s'],
            'initial_speed_mps': start['speed_mps'],
            'final_speed_mps': rows[-1]['speed_mps']}

metrics_ok = True; physical_ok = True; ttl_ok = True; degraded_ok = True
brake_metrics = []; fault_metrics = []
all_speeds = []
for item in brake:
    rec = recompute(item)
    if rec is None: metrics_ok = False; continue
    stored = item['metrics']
    if abs(rec['along_m'] - stored['stop_distance_m']) > 1e-3 \
       or abs(rec['time_s'] - stored['stop_time_s']) > 1e-3:
        metrics_ok = False
    if item['physical_outcome'] != 'STOPPED': physical_ok = False
    if item['business_outcome'] != 'SUCCESS': metrics_ok = False
    if abs(rec['initial_speed_mps'] - item['speed_mps']) > 0.12:
        metrics_ok = False
    rows = steps_by[item['case_id']]
    if not all(r['v2_admission'] in ('ADMITTED', '') for r in rows if r['phase'] in ('ACCEL','BRAKE')):
        ttl_ok = False
    if any(r['degraded'] for r in rows if r['phase']=='BRAKE'):
        ttl_ok = False
    all_speeds.append(rec['initial_speed_mps'])
    brake_metrics.append({'case_id': item['case_id'], **rec})
for item in fault:
    rec = recompute(item)
    if rec is None: metrics_ok = False; continue
    if item['business_outcome'] != 'ABORT': physical_ok = False
    if item['physical_outcome'] not in ('STOPPED','COLLISION','OUT_OF_BOUNDS','OBS_TIMEOUT'):
        physical_ok = False
    rows = steps_by[item['case_id']]
    before = [r for r in rows if r['phase'] == 'ACCEL']
    after = [r for r in rows if r['phase'] == 'FAULT_OBSERVE']
    if not before or not after:
        physical_ok = False
    if not any(r['degraded'] for r in after):
        degraded_ok = False
    if item['fault_type'] == 'A' and not any(r['v2_admission'] == 'NO_NEW_ACTION' for r in after):
        physical_ok = False
    if item['fault_type'] == 'B' and not any(r['v2_admission'] == 'REJECTED' for r in after):
        physical_ok = False
    if item['fault_type'] == 'C' and not any(r['v2_admission'] == 'REJECTED' for r in after):
        physical_ok = False
    if item['fault_type'] == 'D' and not any(r['v2_admission'] == 'REVOKED' for r in after):
        physical_ok = False
    fault_metrics.append({'case_id': item['case_id'], 'fault_type': item['fault_type'],
                          'physical_outcome': item['physical_outcome'], **rec})
checks['brake_metrics'] = metrics_ok
checks['physical_outcomes'] = physical_ok
checks['v2_ttl_no_degrade_normal'] = ttl_ok
checks['post_fault_degraded'] = degraded_ok
checks['fault_types'] = sorted({x['fault_type'] for x in fault}) == ['A','B','C','D']
checks['status_final'] = all(checks.values())
valid = [x for x in brake if x['physical_outcome']=='STOPPED']
dist = [x['metrics']['stop_distance_m'] for x in valid]
times = [x['metrics']['stop_time_s'] for x in valid]
speeds = [x['metrics']['initial_speed_mps'] for x in valid]
result = {'status': 'PASS' if checks['status_final'] else 'FAIL', 'checks': checks,
          'ranges': {'brake_stop_distance_m': [min(dist), max(dist)],
                     'brake_stop_time_s': [min(times), max(times)],
                     'brake_initial_speed_mps': [min(speeds), max(speeds)],
                     'brake_episodes': len(valid)},
          'fault_metrics': fault_metrics, 'brake_metrics': brake_metrics,
          'coverage': {'cells': len(coverage), 'episodes': len(brake)},
          'command_latency_note': 'No separate command/actuation latency probe; setpoint issued and stepped at the same 0.05 s tick.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
print(json.dumps({'status': result['status'], 'failed': [k for k,v in checks.items() if not v],
                  'ranges': result['ranges']}, indent=2))
