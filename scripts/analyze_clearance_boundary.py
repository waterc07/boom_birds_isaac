"""Summarise the clearance-boundary formal evidence (no Isaac, no verifier trust).

Reads raw steps/episodes/manifest of the pre-frozen boundary segments and the
freeze/expected documents; produces the numbers quoted in
MAP_CLEARANCE_BOUNDARY_REPORT.md.  It deliberately re-derives the produced
clearance metrics from raw rows and labels the evidence domain.
"""
import argparse
import json
import math
from pathlib import Path

SEGMENTS = ('boundary_default', 'boundary_delay_e1', 'boundary_delay_e2',
            'boundary_fast')
SPECIAL_SEGMENTS = ('latency_clock_mapping_recheck',
                    'latency_ttl_over_recheck')
REGRESSION_SEGMENTS = ('regression_dynamic', 'regression_no_obstacle',
                       'regression_fault')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def dist(a, b):
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def episode_summary(rows, episode):
    metrics = episode.get('metrics') or {}
    braking = metrics.get('brake_start')
    first_stop = None
    for row in rows:
        if row.get('supervisor_action') == 'STOP':
            first_stop = row
            break
    inferred = [row for row in rows
                if (row.get('contact_evidence') or {}).get('inferred_contact')]
    first_inferred = (float(inferred[0]['time_s']) if inferred else None)
    stop_time = None
    if first_stop is not None:
        speeds = [(float(row['time_s']), float(row.get('speed_mps', 0.0)))
                  for row in rows if float(row['time_s'])
                  >= float(first_stop['time_s'])]
        window = index = 0
        for index in range(len(speeds)):
            block = speeds[index:index + 10]
            if len(block) < 10:
                break
            if all(speed <= 0.08 for _, speed in block):
                stop_time = block[-1][0]
                break
    post_stop_approach = None
    if stop_time is not None and first_stop is not None:
        after = [row for row in rows if float(row['time_s']) > stop_time]
        if after:
            anchor = [row for row in rows
                      if float(row['time_s']) <= stop_time][-1]
            d0 = dist(anchor['position_world_m'],
                      anchor['obstacle_position_world_m'])
            minimum = min(dist(row['position_world_m'],
                               row['obstacle_position_world_m'])
                          for row in after)
            post_stop_approach = {
                'rows': len(after),
                'distance_at_stop_m': d0,
                'min_after_stop_m': minimum,
                'closer_by_m': d0 - minimum,
                'obstacle_still_moving': any(
                    math.sqrt(sum(float(v) ** 2 for v in
                                  (row.get('obstacle_velocity_world_mps')
                                   or [0, 0, 0]))) > 1e-6 for row in after),
            }
    extremes = metrics.get('stop_requirement_extremes') or {}
    return {
        'episode_id': episode['episode_id'],
        'case_id': episode['case_id'],
        'scenario_class': episode.get('scenario_class'),
        'business_outcome': episode.get('business_outcome'),
        'physical_outcome': episode.get('physical_outcome'),
        'reason': episode.get('reason'),
        'steps': episode.get('steps'),
        'stop_triggered': first_stop is not None,
        'brake_actual_speed_mps': (None if first_stop is None
                                   else float(first_stop.get('speed_mps', 0.0))),
        'brake_max_actual_speed_mps': extremes.get('max_robot_speed_mps'),
        'stop_distance_m': metrics.get('stop_distance_m'),
        'stop_time_s': metrics.get('stop_time_s'),
        'min_path_clearance_m': metrics.get('min_path_clearance_m'),
        'min_path_clearance_gap_sphere_m': metrics.get(
            'min_path_clearance_gap_sphere_m'),
        'min_center_distance_m': metrics.get('min_center_distance_m'),
        'min_envelope_gap_sphere_m': metrics.get('min_envelope_gap_sphere_m'),
        'stop_requirement_min_margin_m': extremes.get('min_margin_m'),
        'unsupported_steps': extremes.get('unsupported_steps'),
        'unsupported_reasons': extremes.get('unsupported_reasons'),
        'contact_evidence': metrics.get('contact_evidence_summary'),
        'first_inferred_contact_time_s': first_inferred,
        'stop_time_s_derived': stop_time,
        'contact_after_stop': (None if (first_inferred is None
                                        or stop_time is None)
                               else first_inferred > stop_time),
        'post_stop_obstacle_motion': post_stop_approach,
        'post_abort': metrics.get('post_abort'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', type=Path,
                        default=Path('configs/scenarios/clearance_boundary_freeze_v1.json'))
    parser.add_argument('--expected', type=Path,
                        default=Path('configs/scenarios/clearance_boundary_expected_v1.json'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    freeze = load(args.freeze)
    expected = load(args.expected)

    payload = {
        'sources': {
            'freeze': str(args.freeze),
            'freeze_sha256': __import__('hashlib').sha256(
                args.freeze.read_bytes()).hexdigest(),
            'freeze_frozen_at': freeze.get('frozen_at'),
            'freeze_code_commit': freeze.get('code_commit'),
            'expected': str(args.expected),
            'evidence_domain': ('SIMULATION_ONLY: Isaac simulated host time base + '
                                'simulated camera clock domain; ORACLE obstacle '
                                'observation; no real device clocks/serial/PX4'),
            'contact_mode': 'sphere_overlap_inference (force sensor unavailable)',
            'stop_threshold_default_m': 1.1,
            'stop_threshold_candidate_m': 1.38,
            'stop_threshold_note': ('1.1 m is the frozen default for this round; '
                                    '1.38 m remains a candidate and was NOT run '
                                    'as default in this boundary set'),
        },
        'segments': {},
        'special': {},
        'regression': {},
    }
    for segment in SEGMENTS + SPECIAL_SEGMENTS + REGRESSION_SEGMENTS:
        run_dir = root / 'outputs/map_eval' / ('bnd_' + segment)
        if not (run_dir / 'episodes.jsonl').exists():
            continue
        episodes = load_jsonl(run_dir / 'episodes.jsonl')
        steps = load_jsonl(run_dir / 'steps.jsonl')
        manifest = load(run_dir / 'manifest.json')
        by_id = {}
        for row in steps:
            by_id.setdefault(row['episode_id'], []).append(row)
        summaries = [episode_summary(by_id.get(episode['episode_id'], []),
                                     episode) for episode in episodes]
        entry = {
            'run_dir': str(run_dir),
            'role': (manifest.get('boundary_plan') or {}).get('role', ''),
            'episodes': summaries,
            'counts': {
                'episodes': len(summaries),
                'business': {},
                'physical': {},
            },
            'manifest': {
                'contact_sensor': manifest.get('contact_sensor'),
                'body_envelope': manifest.get('body_envelope'),
                'vehicle_config': manifest.get('vehicle_config'),
                'freeze': manifest.get('freeze'),
            },
        }
        for summary in summaries:
            entry['counts']['business'][summary['business_outcome']] = (
                entry['counts']['business'].get(summary['business_outcome'], 0) + 1)
            entry['counts']['physical'][summary['physical_outcome']] = (
                entry['counts']['physical'].get(summary['physical_outcome'], 0) + 1)
        if segment in SEGMENTS:
            payload['segments'][segment] = entry
        elif segment in SPECIAL_SEGMENTS:
            payload['special'][segment] = entry
        else:
            payload['regression'][segment] = entry

    # ---- boundary-specific derived numbers ----
    boundary = []
    for segment in SEGMENTS:
        entry = payload['segments'].get(segment)
        if not entry:
            continue
        for summary in entry['episodes']:
            boundary.append(summary)
    boundary_by_class = {}
    for summary in boundary:
        boundary_by_class.setdefault(summary['scenario_class'], []).append(summary)
    payload['boundary'] = {
        'episode_total': len(boundary),
        'by_scenario_class': {
            name: {
                'episodes': len(items),
                'business': {item['business_outcome']: sum(
                    1 for other in items
                    if other['business_outcome'] == item['business_outcome'])
                    for item in items},
                'physical': {item['physical_outcome']: sum(
                    1 for other in items
                    if other['physical_outcome'] == item['physical_outcome'])
                    for item in items},
                'stop_triggered_ratio': (sum(1 for item in items
                                             if item['stop_triggered']) / len(items)),
                'brake_speed_range_mps': [
                    min(item['brake_actual_speed_mps'] for item in items
                        if item['brake_actual_speed_mps'] is not None)
                    if any(item['brake_actual_speed_mps'] is not None
                           for item in items) else None,
                    max(item['brake_actual_speed_mps'] for item in items
                        if item['brake_actual_speed_mps'] is not None)
                    if any(item['brake_actual_speed_mps'] is not None
                           for item in items) else None],
                'min_path_clearance_range_m': [
                    min(item['min_path_clearance_m'] for item in items
                        if item['min_path_clearance_m'] is not None)
                    if any(item['min_path_clearance_m'] is not None
                           for item in items) else None,
                    max(item['min_path_clearance_m'] for item in items
                        if item['min_path_clearance_m'] is not None)
                    if any(item['min_path_clearance_m'] is not None
                           for item in items) else None],
                'min_envelope_gap_range_m': [
                    min(item['min_envelope_gap_sphere_m'] for item in items
                        if item['min_envelope_gap_sphere_m'] is not None)
                    if any(item['min_envelope_gap_sphere_m'] is not None
                           for item in items) else None,
                    max(item['min_envelope_gap_sphere_m'] for item in items
                        if item['min_envelope_gap_sphere_m'] is not None)
                    if any(item['min_envelope_gap_sphere_m'] is not None
                           for item in items) else None],
            }
            for name, items in boundary_by_class.items()
        },
        'unsupported_episode_count': sum(
            1 for item in boundary if (item['unsupported_steps'] or 0) > 0),
        'contact_inferred_episode_count': sum(
            1 for item in boundary
            if item['physical_outcome'] == 'CONTACT_INFERRED'),
    }

    # support-range classification from robot speed vs brake model
    brake_model = load('configs/scenarios/brake_model_v1.json')
    low, high = brake_model['supported_speed_range_mps']
    payload['brake_model'] = {
        'model_id': brake_model['model_id'],
        'speed_support_mps': [low, high],
        'points': brake_model['points'],
        'extrapolation': brake_model.get('extrapolation'),
    }
    payload['support_classification'] = {
        'boundary_episodes_with_speed_above_support': [
            item['episode_id'] for item in boundary
            if (item['brake_max_actual_speed_mps'] or 0.0) > high],
        'boundary_episodes_with_unsupported_steps': [
            item['episode_id'] for item in boundary
            if (item['unsupported_steps'] or 0) > 0],
        'note': ('episodes whose actual speed exceeds the measured brake-model '
                 'support are flagged UNSUPPORTED in raw records and are not '
                 'extrapolated into safety claims'),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({segment: payload['segments'][segment]['counts']['business']
                      for segment in payload['segments']}, indent=2))


if __name__ == '__main__':
    main()
