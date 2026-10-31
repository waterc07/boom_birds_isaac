"""Audit historical evaluation runs for silent episode-auto-reset pollution."""
import argparse
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-json', type=Path, required=True)
parser.add_argument('--output-md', type=Path, required=True)
args = parser.parse_args()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip()]


def split_broken_csv_line(line):
    """Split a legacy CSV line whose list columns were written without quoting."""
    parts = []
    buffer = ''
    depth = 0
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if in_quotes:
            buffer += char
            continue
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
        if char == ',' and depth == 0:
            parts.append(buffer)
            buffer = ''
        else:
            buffer += char
    parts.append(buffer)
    return parts


def read_legacy_rows(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    header = [item.strip().strip('"') for item in lines[0].split(',')]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = split_broken_csv_line(line)
        if len(parts) != len(header):
            raise ValueError('column count mismatch')
        rows.append(dict(zip(header, parts)))
    return rows


def parse_records(path):
    try:
        with path.open(encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            json.loads(row['position_world_m'])
            json.loads(row['velocity_world_mps'])
        return rows, 'csv module (quoted columns)'
    except (KeyError, ValueError, TypeError):
        return read_legacy_rows(path), 'bracket-aware legacy parser'


def spawn_rows(rows, spawn_z, position_key='position_world_m',
               velocity_key='velocity_world_mps'):
    hits = []
    for row in rows:
        position = row[position_key]
        velocity = row[velocity_key]
        if isinstance(position, str):
            position = json.loads(position)
        if isinstance(velocity, str):
            velocity = json.loads(velocity)
        if not isinstance(position, (list, tuple)) or len(position) < 3:
            continue
        if not isinstance(velocity, (list, tuple)) or len(velocity) < 3:
            continue
        if (abs(position[0]) < 1e-6 and abs(position[1]) < 1e-6
                and abs(position[2] - spawn_z) < 1e-6
                and max(abs(value) for value in velocity) < 1e-6):
            hits.append(row)
    return hits


def detect_layered(run_dir):
    steps = read_jsonl(run_dir / 'steps.jsonl')
    hits = spawn_rows(steps, 0.5)
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
    try:
        rows, parser_name = parse_records(csv_path)
        hits = spawn_rows(rows, 0.75)
        unexpected = [row for row in hits
                      if not (row['scenario'] == 'reset_old_epoch'
                              and int(row['step']) in (20, 21))]
        return {
            'source': str(csv_path),
            'method': parser_name + '; spawn pose/zero velocity at step>0; '
                      'reset_old_epoch reset at 1.0 s allowed',
            'status': ('CONFIRMED_POLLUTION' if unexpected
                       else 'CHECKED_NO_EVIDENCE'),
            'hit_count': len(hits),
            'unexpected_count': len(unexpected),
            'unexpected_rows': [{'scenario': row['scenario'],
                                 'step': int(row['step'])} for row in unexpected],
            'limitations': ('no episode counter/flags recorded; spawn signature '
                            'is auxiliary'),
        }
    except Exception as error:
        return {
            'source': str(csv_path),
            'method': 'per-step CSV parse',
            'status': 'INSUFFICIENT_DATA',
            'limitations': 'cannot parse historical CSV: ' + repr(error),
        }


def detect_reach(csv_path):
    try:
        rows, parser_name = parse_records(csv_path)
        unexpected = [row for row in spawn_rows(rows, 0.75)
                      if int(row['step']) > 0]
        return {
            'source': str(csv_path),
            'method': parser_name + '; spawn pose/zero velocity at step>0',
            'status': ('CONFIRMED_POLLUTION' if unexpected
                       else 'CHECKED_NO_EVIDENCE'),
            'unexpected_count': len(unexpected),
            'unexpected_rows': [{'episode': int(row['episode']),
                                 'step': int(row['step'])} for row in unexpected],
            'limitations': ('no episode counter/flags recorded; spawn signature '
                            'is auxiliary'),
        }
    except Exception as error:
        return {
            'source': str(csv_path),
            'method': 'per-step CSV parse',
            'status': 'INSUFFICIENT_DATA',
            'limitations': 'cannot parse historical CSV: ' + repr(error),
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

legacy_summary = root / 'outputs/c_diagnosis/legacy_original_r3/summary.json'
if legacy_summary.exists():
    data = json.loads(legacy_summary.read_text(encoding='utf-8'))
    runs.append({
        'run': 'c_diagnosis/legacy_original_r3',
        'source': str(legacy_summary),
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
                       'historical runners read only terminated and ignored '
                       'truncated. Runs created before commit c1d7583 are at risk.'),
    'runs': runs,
}
args.output_json.parent.mkdir(parents=True, exist_ok=True)
args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                            encoding='utf-8')
lines = ['# 历史评价运行 episode 边界审计', '',
         '检测方法：逐 step 记录中的出生位姿/零速度突变（辅助证据）；'
         '旧运行未记录 episode 计数或 terminated/truncated 标志，'
         '因此“未检测到”不等于“已证明没有”。',
         '历史 velocity/reach CSV 的列表列未按 CSV 引号写出，'
         '使用括号感知的兼容解析器恢复逐 step 字段。', '',
         '| 运行 | 状态 | 受影响/异常 | 方法与限制 |',
         '| --- | --- | --- | --- |']
for item in runs:
    detail = (item.get('affected_episodes') or item.get('unexpected_rows')
              or item.get('unexpected_count') or item.get('episode_count')
              or item.get('episodes'))
    lines.append('| {} | {} | {} | {} |'.format(
        item['run'], item['status'], detail, item.get('limitations', '')))
args.output_md.parent.mkdir(parents=True, exist_ok=True)
args.output_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'runs': len(runs),
                  'statuses': sorted({item['status'] for item in runs})},
                 indent=2))
