"""Audit historical evaluation runs for silent episode-auto-reset pollution."""
import argparse
import ast
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-json', type=Path, required=True)
parser.add_argument('--output-md', type=Path, required=True)
args = parser.parse_args()

SPAWN_VELOCITY = (0.0, 0.0, 0.75)
SPAWN_LAYERED = (0.0, 0.0, 0.5)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def spawn_rows(rows, spawn_z, key_position='position_world_m',
               key_velocity='velocity_world_mps'):
    hits = []
    for row in rows:
        position = row[key_position]
        velocity = row[key_velocity]
        if (abs(position[0]) < 1e-6 and abs(position[1]) < 1e-6
                and abs(position[2] - spawn_z) < 1e-6
                and max(abs(value) for value in velocity) < 1e-6):
            hits.append(row)
    return hits


def detect_layered(run_dir):
    steps = read_jsonl(run_dir / 'steps.jsonl')
    hits = spawn_rows(steps, SPAWN_LAYERED[2])
    episodes = sorted({row['scenario_id'] for row in hits})
    return {
        'source': str(run_dir / 'steps.jsonl'),
        'method': 'spawn pose/zero velocity in per-step record (auxiliary)',
        'status': 'CONFIRMED_POLLUTION' if hits else 'CHECKED_NO_EVIDENCE',
        'affected_episodes': episodes,
        'hit_count': len(hits),
        'limitations': 'no episode counter/flags recorded in this historical run',
    }


def detect_velocity(csv_path):
    with csv_path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    hits = []
    for row in rows:
        position = ast.literal_eval(row['position_world_m'])
        velocity = ast.literal_eval(row['velocity_world_mps'])
        if (abs(position[0]) < 1e-6 and abs(position[1]) < 1e-6
                and abs(position[2] - 0.75) < 1e-6
                and max(abs(value) for value in velocity) < 1e-6
                and int(row['step']) > 0):
            hits.append(row)
    unexpected = [row for row in hits
                  if not (row['scenario'] == 'reset_old_epoch'
                          and int(row['step']) in (20, 21))]
    return {
        'source': str(csv_path),
        'method': 'spawn pose/zero velocity at step>0; reset_old_epoch reset at 1.0 s allowed',
        'status': ('CONFIRMED_POLLUTION' if unexpected
                   else 'CHECKED_NO_EVIDENCE'),
        'hit_count': len(hits),
        'unexpected_count': len(unexpected),
        'unexpected_rows': [{'scenario': row['scenario'],
                             'step': int(row['step'])} for row in unexpected],
        'limitations': 'no episode counter/flags recorded; spawn signature is auxiliary',
    }


def detect_reach(csv_path):
    with csv_path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    unexpected = []
    for row in rows:
        position = ast.literal_eval(row['position_world_m'])
        velocity = ast.literal_eval(row['velocity_world_mps'])
        if (int(row['step']) > 0
                and abs(position[0]) < 1e-6 and abs(position[1]) < 1e-6
                and abs(position[2] - 0.75) < 1e-6
                and max(abs(value) for value in velocity) < 1e-6):
            unexpected.append(row)
    return {
        'source': str(csv_path),
        'method': 'spawn pose/zero velocity at step>0',
        'status': ('CONFIRMED_POLLUTION' if unexpected
                   else 'CHECKED_NO_EVIDENCE'),
        'unexpected_count': len(unexpected),
        'unexpected_rows': [{'episode': int(row['episode']),
                             'step': int(row['step'])} for row in unexpected],
        'limitations': 'no episode counter/flags recorded; spawn signature is auxiliary',
    }


def detect_episode_only(run_dir):
    episodes_path = run_dir / 'episodes.jsonl'
    episodes = read_jsonl(episodes_path) if episodes_path.exists() else []
    return {
        'source': str(episodes_path),
        'method': 'episode-level records only',
        'status': 'INSUFFICIENT_DATA',
        'episode_count': len(episodes),
        'limitations': ('no per-step records; cannot prove or exclude a silent '
                        'auto-reset. Run predates the evaluation-boundary fix, '
                        'so its per-episode values are unverified.'),
    }


root = Path('.')
runs = []
for name in ('final_run2', 'final_run3', 'final_run4'):
    path = root / 'outputs/layered_eval' / name
    if path.exists():
        runs.append({'run': 'layered/' + name, **detect_layered(path)})

velocity_csv = root / 'outputs/sim_velocity_chain/full.csv'
if velocity_csv.exists():
    runs.append({'run': 'velocity_chain/full', **detect_velocity(velocity_csv)})

for name in ('run1', 'run2'):
    path = root / 'outputs/sim_reach' / name / 'reach.csv'
    if path.exists():
        runs.append({'run': 'reach/' + name, **detect_reach(path)})

for name in ('tuning_run1', 'tuning_run2', 'final_run1', 'faults_run2',
             'faults_run4'):
    path = root / 'outputs/guidance_compare' / name
    if path.exists():
        runs.append({'run': 'compare/' + name, **detect_episode_only(path)})

# Legacy reproduction evidence from the C-class diagnosis.
legacy = root / 'outputs/c_diagnosis/legacy_original_r3/summary.json'
if legacy.exists():
    data = json.loads(legacy.read_text(encoding='utf-8'))
    runs.append({
        'run': 'c_diagnosis/legacy_original_r3',
        'source': str(legacy),
        'method': 'legacy mode without boundary clearing (3 repeats)',
        'status': 'CONFIRMED_POLLUTION',
        'episodes': [{'scenario_id': item['scenario_id'],
                      'outcome': item['outcome'],
                      'reason': item['reason'],
                      'steps': item['steps']} for item in data['episodes']],
        'limitations': 'intentionally reproduces the old defect for evidence',
    })

payload = {
    'defect_context': ('QuadcopterEnv randomises episode_length_buf on full reset; '
                       'historical runners read only terminated and ignored truncated. '
                       'Runs created before commit c1d7583 are at risk.'),
    'runs': runs,
}
args.output_json.parent.mkdir(parents=True, exist_ok=True)
args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                            encoding='utf-8')
lines = ['# 历史评价运行 episode 边界审计', '',
         '检测方法：逐 step 记录中的出生位姿/零速度突变（辅助证据）；'
         '旧运行未记录 episode 计数或 terminated/truncated 标志，'
         '因此“未检测到”不等于“已证明没有”。', '',
         '| 运行 | 状态 | 受影响/异常 | 方法与限制 |',
         '| --- | --- | --- | --- |']
for item in runs:
    detail = item.get('affected_episodes') or item.get('unexpected_rows') \
        or item.get('unexpected_count') or item.get('episode_count')
    lines.append('| {} | {} | {} | {} |'.format(
        item['run'], item['status'], detail, item.get('limitations', '')))
args.output_md.parent.mkdir(parents=True, exist_ok=True)
args.output_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'runs': len(runs), 'statuses': {item['status'] for item in runs}},
                 indent=2))
