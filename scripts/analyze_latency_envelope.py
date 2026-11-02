"""Parameter analysis for the latency-envelope formal evidence (no Isaac).

Reads only raw `steps.jsonl` / `episodes.jsonl` / `manifest.json` of the formal
runs, the pre-run freeze, the expected-classification config and the previously
frozen brake evidence.  Outputs a JSON summary of the numbers quoted in
MAP_LATENCY_ENVELOPE_REPORT.md.  Every number is labelled measured / derived /
approximate / unconfirmed in the output labels.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from boom_birds.evaluation.supervisor import _distance_point_segment
from boom_birds.evaluation.waypoints import WaypointConfig, WaypointRunner
from boom_birds.sim.dynamic_obstacle import load_obstacle_spec

MOVE_OR_STOP = 0.08
STOP_WINDOW_S = 0.5


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def dist(a, b):
    return math.sqrt(sum((float(a[index]) - float(b[index])) ** 2
                         for index in range(3)))


def episode_rows(steps, episode_id):
    return [row for row in steps if row.get('episode_id') == episode_id]


def brake_evidence_points(repo_root):
    """Formal pre-frozen brake evidence from the previous work package."""
    path = repo_root / 'docs/reports/map_eval/brake/verify_brake_final.json'
    points = []
    if path.exists():
        payload = load_json(path)
        for item in payload.get('brake_metrics', []):
            speed = float(item['initial_speed_mps'])
            distance = float(item['along_m'])
            if speed > 0:
                points.append({'initial_speed_mps': speed,
                               'stop_distance_m': distance})
    points.sort(key=lambda item: item['initial_speed_mps'])
    return points


def interp_distance(points, speed):
    """Piecewise-linear interpolation/extrapolation of measured stop distance."""
    if not points:
        return None
    if speed <= points[0]['initial_speed_mps']:
        return speed / points[0]['initial_speed_mps'] * points[0]['stop_distance_m']
    for left, right in zip(points, points[1:]):
        if left['initial_speed_mps'] <= speed <= right['initial_speed_mps']:
            span = right['initial_speed_mps'] - left['initial_speed_mps']
            ratio = (speed - left['initial_speed_mps']) / span
            return (left['stop_distance_m']
                    + ratio * (right['stop_distance_m'] - left['stop_distance_m']))
    left = points[-1]
    return left['stop_distance_m'] * speed / left['initial_speed_mps']




def reconstruct_supervisor_clearance(run_rows, trigger_index, case):
    """Replay the waypoint runner and recompute the supervisor risk quantity.

    Derived / reconstructed: uses recorded positions, speeds and route_active_s,
    the observation age point estimate and the case obstacle trajectory.  It is
    not a substitute for the recorded (absent) clearance field; the report labels
    it as reconstructed.
    """
    try:
        runner = WaypointRunner(
            tuple(tuple(point) for point in case['waypoints']),
            WaypointConfig(arrival_radius_m=0.25, arrival_speed_mps=0.2,
                           intermediate_hold_s=0.2, final_hold_s=0.5,
                           segment_timeout_s=60.0, dt_s=0.05),
            timeout_s=float(case['timeout_s']))
        for row in run_rows[:trigger_index + 1]:
            runner.update(row['position_world_m'], float(row['speed_mps']),
                          float(row.get('route_active_s', 0.0)), contact=False)
        trigger = run_rows[trigger_index]
        target = runner.waypoints[runner.index]
        spec = load_obstacle_spec(case['obstacle'])
        elapsed = float(trigger['time_s'])
        age = float(trigger.get('observation_age_point_s') or 0.0)
        sample_t = max(0.0, elapsed - age)
        position, velocity = spec.pose_at(sample_t)
        predicted = [[position[i] + velocity[i] * (0.1 * step)
                      for i in range(3)] for step in range(11)]
        clearance = min(_distance_point_segment(point, trigger['position_world_m'],
                                                target) for point in predicted)
        return {
            'clearance_reconstructed_m': clearance,
            'target_waypoint_m': list(target),
            'waypoint_index': runner.index,
            'observation_sample_time_s': sample_t,
            'prediction_steps': 11,
            'label': 'reconstructed_from_raw (not a recorded field)',
        }
    except Exception as error:
        return {'error': type(error).__name__ + ': ' + str(error)}

def envelope_radii(manifest, case):
    body = manifest.get('body_envelope') or {}
    half = body.get('half_extents_m') or []
    body_radius = max(float(value) for value in half) if half else 0.0
    obstacle = case.get('obstacle') or {}
    size = obstacle.get('size_m') or []
    obstacle_radius = max(float(value) / 2.0 for value in size) if size else 0.0
    return body_radius, obstacle_radius, body.get('source'), half


def analyse_episode(row_list, manifest, case, brake_points, action_delay_s):
    run_rows = [row for row in row_list if row.get('phase', 'RUN') == 'RUN']
    body_radius, obstacle_radius, body_source, body_half = envelope_radii(manifest, case)
    trigger = None
    trigger_index = None
    for index, row in enumerate(run_rows):
        if row.get('supervisor_action') == 'STOP':
            trigger = row
            trigger_index = index
            break
    result = {
        'episode_id': row_list[0].get('episode_id'),
        'case_id': row_list[0].get('case_id'),
        'scenario_class': row_list[0].get('scenario_class'),
        'outcome': row_list[-1].get('outcome'),
        'reason': row_list[-1].get('reason'),
        'body_radius_m': body_radius,
        'obstacle_radius_m': obstacle_radius,
        'body_source': body_source,
        'body_half_extents_m': body_half,
        'brake_trigger': None,
        'min_center_distance_m': None,
        'min_envelope_gap_m': None,
        'min_gap_time_s': None,
        'max_relative_speed_mps': 0.0,
        'max_closing_speed_mps': 0.0,
        'stop_distance_m': None,
        'stop_time_s': None,
        'post_stop': None,
        'executed_action_count': 0,
        'arrival_rejections': 0,
        'observation_age_bound_s': None,
        'mapping_error_ns': None,
    }
    if not row_list:
        return result
    distances = []
    previous = None
    for row in row_list:
        center = dist(row['position_world_m'], row['obstacle_position_world_m'])
        gap = center - body_radius - obstacle_radius
        distances.append((row, center, gap))
        if result['min_center_distance_m'] is None or center < result['min_center_distance_m']:
            result['min_center_distance_m'] = center
        if result['min_envelope_gap_m'] is None or gap < result['min_envelope_gap_m']:
            result['min_envelope_gap_m'] = gap
            result['min_gap_time_s'] = float(row.get('time_s', 0.0))
        velocity = row.get('velocity_world_mps')
        obstacle_velocity = row.get('obstacle_velocity_world_mps')
        if velocity and obstacle_velocity:
            relative = [obstacle_velocity[i] - velocity[i] for i in range(3)]
            result['max_relative_speed_mps'] = max(
                result['max_relative_speed_mps'],
                math.sqrt(sum(value * value for value in relative)))
        if previous is not None:
            delta_t = float(row.get('time_s', 0.0)) - float(
                previous[0].get('time_s', 0.0))
            if delta_t > 1e-9:
                result['max_closing_speed_mps'] = max(
                    result['max_closing_speed_mps'],
                    (previous[1] - center) / delta_t)
        previous = (row, center)
    transport = [row.get('transport') or {} for row in row_list]
    result['executed_action_count'] = len({item.get('executed_action_id')
                                           for item in transport
                                           if item.get('executed')
                                           and item.get('executed_action_id')})
    result['arrival_rejections'] = sum(
        1 for item in transport if item.get('status') == 'REJECTED')
    if trigger is not None:
        speed = float(trigger.get('speed_mps', 0.0))
        center = dist(trigger['position_world_m'],
                      trigger['obstacle_position_world_m'])
        clock = trigger.get('clock') or {}
        velocity = trigger.get('velocity_world_mps') or [0.0, 0.0, 0.0]
        obstacle_velocity = trigger.get('obstacle_velocity_world_mps') or [0.0, 0.0, 0.0]
        relative = [obstacle_velocity[i] - velocity[i] for i in range(3)]
        result['observation_age_bound_s'] = float(trigger.get('observation_age_s', 0.0))
        result['mapping_error_ns'] = clock.get('mapping_error_ns')
        result['brake_trigger'] = {
            'step': int(trigger.get('step', 0)),
            'time_s': float(trigger.get('time_s', 0.0)),
            'actual_speed_mps': speed,
            'observation_age_bound_s': float(trigger.get('observation_age_s', 0.0)),
            'observation_age_point_s': float(trigger.get('observation_age_point_s', 0.0)),
            'mapping_error_ns': clock.get('mapping_error_ns'),
            'center_distance_m': center,
            'envelope_gap_m': center - body_radius - obstacle_radius,
            'relative_speed_mps': math.sqrt(sum(value * value for value in relative)),
            'action_delay_s': action_delay_s,
            'brake_distance_estimate_m': interp_distance(brake_points, speed),
        }
        # Independent stop distance/time from raw positions: from trigger to the
        # first END of a 0.5 s window whose speeds are all <= 0.08 m/s.
        tail = [row for row in row_list
                if float(row.get('time_s', 0.0)) >= float(trigger.get('time_s', 0.0))]
        speeds = [float(row.get('speed_mps', 0.0)) for row in tail]
        window = max(1, int(math.ceil(STOP_WINDOW_S / 0.05)))
        stop_row = None
        for index in range(0, len(tail)):
            block = speeds[index:index + window]
            if len(block) < window:
                break
            if all(value <= MOVE_OR_STOP for value in block):
                stop_row = tail[index + window - 1]
                break
        if stop_row is None and tail:
            stop_row = tail[-1]
        if stop_row is not None:
            delta = [float(stop_row['position_world_m'][i])
                     - float(trigger['position_world_m'][i]) for i in range(3)]
            if speed > 1e-9:
                unit = [float(velocity[i]) / speed for i in range(3)]
                along = sum(delta[i] * unit[i] for i in range(3))
            else:
                along = math.sqrt(sum(value * value for value in delta))
            result['stop_distance_m'] = along
            result['stop_time_s'] = (float(stop_row.get('time_s', 0.0))
                                     - float(trigger.get('time_s', 0.0)))
            stop_speed = float(stop_row.get('speed_mps', 0.0))
            # Post-stop obstacle motion: rows after stop_row with speed <= stop
            # threshold; report whether the obstacle kept approaching.
            after = [row for row in row_list
                     if float(row.get('time_s', 0.0))
                     > float(stop_row.get('time_s', 0.0))
                     and float(row.get('speed_mps', 0.0)) <= MOVE_OR_STOP]
            if after:
                d0 = dist(stop_row['position_world_m'],
                          stop_row['obstacle_position_world_m'])
                minimum = min(dist(row['position_world_m'],
                                   row['obstacle_position_world_m'])
                              for row in after)
                result['post_stop'] = {
                    'rows': len(after),
                    'speed_at_stop_mps': stop_speed,
                    'distance_at_stop_m': d0,
                    'min_distance_after_stop_m': minimum,
                    'approached_m': d0 - minimum,
                    'obstacle_still_moving': any(
                        math.sqrt(sum(float(value) ** 2 for value in
                                      row.get('obstacle_velocity_world_mps') or [0, 0, 0]))
                        > 1e-6 for row in after),
                }
    return result


def analyse_ttl(run_dirs):
    accepted = []
    rejected = []
    for run_dir in run_dirs:
        steps_path = Path(run_dir) / 'steps.jsonl'
        if not steps_path.exists():
            continue
        for row in load_jsonl(steps_path):
            transport = row.get('transport') or {}
            status = transport.get('status')
            if status == 'APPLIED':
                accepted.append({
                    'run': Path(run_dir).name,
                    'episode_id': row.get('episode_id'),
                    'step': row.get('step'),
                    'arrival_age_s': transport.get('arrival_age_s'),
                })
            elif status == 'REJECTED':
                rejected.append({
                    'run': Path(run_dir).name,
                    'episode_id': row.get('episode_id'),
                    'step': row.get('step'),
                    'reason': transport.get('reason'),
                    'arrival_age_s': transport.get('arrival_age_s'),
                    'nested': transport.get('rejections_this_step') or [],
                })
    ages = [item['arrival_age_s'] for item in accepted
            if isinstance(item['arrival_age_s'], (int, float))]
    rejected_ages = [item['arrival_age_s'] for item in rejected
                     if isinstance(item['arrival_age_s'], (int, float))]
    return {
        'accepted_count': len(accepted),
        'accepted_age_s': {'min': min(ages) if ages else None,
                           'max': max(ages) if ages else None},
        'rejected_count': len(rejected),
        'rejected_age_s': {'min': min(rejected_ages) if rejected_ages else None,
                           'max': max(rejected_ages) if rejected_ages else None},
        'rejected_reasons': sorted({item['reason'] for item in rejected}),
        'samples': {'accepted': accepted[:5], 'rejected': rejected[:5]},
    }


def summarise_run(run_dir):
    manifest = load_json(Path(run_dir) / 'manifest.json')
    episodes = load_jsonl(Path(run_dir) / 'episodes.jsonl')
    steps = load_jsonl(Path(run_dir) / 'steps.jsonl')
    return manifest, episodes, steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--freeze', type=Path,
                        default=Path('configs/scenarios/latency_pair_freeze_v2.json'))
    parser.add_argument('--expected', type=Path,
                        default=Path('configs/scenarios/latency_expected_v1.json'))
    parser.add_argument('--run-a', type=Path,
                        default=Path('outputs/map_eval/latency_formal2_A'))
    parser.add_argument('--run-b', type=Path,
                        default=Path('outputs/map_eval/latency_formal2_B'))
    parser.add_argument('--special', action='append', default=[])
    parser.add_argument('--regression', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root

    freeze = load_json(args.freeze)
    expected = load_json(args.expected)
    cases_payload = load_json(root / 'configs/scenarios/map_dynamic_cases_v1.json')
    cases = {item['case_id']: item for item in cases_payload['cases']}
    action_delay_s = float(freeze['main_run_plans']['A']['action_delay_s'])
    obs_delay_s = float(freeze['main_run_plans']['A']['obs_delay_s'])
    ttl_ms = int(freeze['main_run_plans']['A']['ttl_ms'])
    brake_points = brake_evidence_points(root)

    payload = {
        'sources': {
            'pair_freeze': str(args.freeze),
            'freeze_frozen_at': freeze.get('frozen_at'),
            'freeze_code_commit': freeze.get('code_commit'),
            'brake_evidence': 'docs/reports/map_eval/brake/verify_brake_final.json',
            'label': 'measured / derived / approximate / unconfirmed as noted',
        },
        'distance_definition': {
            'supervisor_risk_quantity': (
                'clearance = min over obstacle-center positions predicted for the '
                'next 1.0 s (0.1 s steps, observed velocity) of the point-to-segment '
                'distance to the segment [robot current position -> current route '
                'target]; risk when clearance < stop_distance_m'),
            'is_center_distance': False,
            'is_surface_gap': False,
            'source': 'src/boom_birds/evaluation/supervisor.py RouteSupervisor._risk',
            'consequence': ('stop_distance_m=1.1/1.38 are thresholds on a predicted '
                            'center-to-path clearance, not on robot-obstacle center '
                            'distance or surface gap'),
        },
        'brake_envelope_measured': {
            'points': brake_points,
            'source': 'brake_final4 formal evidence (pre-frozen, 36 episodes)',
            'note': 'piecewise-linear interpolation used for approximate estimates',
        },
        'execution_plan': {
            'obs_delay_s': obs_delay_s,
            'action_delay_s': action_delay_s,
            'ttl_ms': ttl_ms,
            'control_tick_s': 0.05,
        },
        'runs': {},
        'ttl': {},
        'specials': {},
        'regressions': {},
    }

    for label, run_dir in (('A', args.run_a), ('B', args.run_b)):
        manifest, episodes, steps = summarise_run(run_dir)
        trigger_events = []
        for episode in episodes:
            case = cases[episode['case_id']]
            rows = episode_rows(steps, episode['episode_id'])
            analysed = analyse_episode(rows, manifest, case, brake_points,
                                       action_delay_s)
            if analysed['brake_trigger'] is not None:
                trigger = analysed['brake_trigger']
                body_radius = analysed['body_radius_m']
                obstacle_radius = analysed['obstacle_radius_m']
                brake_distance = trigger.get('brake_distance_estimate_m')
                reaction = (trigger['actual_speed_mps'] * action_delay_s)
                # Conservative observation-age term: relative motion during the
                # observation age; the supervisor predicts with observed velocity,
                # but the position itself is aged.
                relative = trigger['relative_speed_mps']
                age = trigger['observation_age_bound_s']
                closing_age = None
                rows_near = [row for row in rows
                             if abs(float(row.get('time_s', 0.0))
                                    - trigger['time_s']) <= 0.15]
                if len(rows_near) >= 2:
                    deltas = []
                    for left, right in zip(rows_near, rows_near[1:]):
                        dt = (float(right.get('time_s', 0.0))
                              - float(left.get('time_s', 0.0)))
                        if dt <= 0:
                            continue
                        d0 = dist(left['position_world_m'],
                                  left['obstacle_position_world_m'])
                        d1 = dist(right['position_world_m'],
                                  right['obstacle_position_world_m'])
                        deltas.append((d0 - d1) / dt)
                    closing_age = max(deltas) if deltas else None
                measured_stop = analysed['stop_distance_m']
                measured_required = (None if measured_stop is None else
                                     measured_stop
                                     + (0.0 if closing_age is None else closing_age * age)
                                     + body_radius + obstacle_radius)
                envelope_required = (None if brake_distance is None else
                                     brake_distance + reaction
                                     + (0.0 if closing_age is None else closing_age * age)
                                     + body_radius + obstacle_radius)
                threshold = float(
                    freeze['main_run_plans'][label]['stop_distance_m'])
                run_rows = [row for row in rows
                            if row.get('phase', 'RUN') == 'RUN']
                trigger_index = next(
                    (index for index, row in enumerate(run_rows)
                     if row.get('supervisor_action') == 'STOP'), None)
                closure = (reconstruct_supervisor_clearance(
                    run_rows, trigger_index, case)
                    if trigger_index is not None else {'error': 'no trigger'})
                trigger['derived'] = {
                    'definition': ('threshold applies to the reconstructed predicted '
                                   'path clearance, not to center distance or surface gap'),
                    'clearance_reconstructed': closure,
                    'measured_stop_distance_m': measured_stop,
                    'observation_age_s': age,
                    'closing_speed_near_trigger_mps': closing_age,
                    'measured_basis_required_clearance_m': measured_required,
                    'measured_basis_margin_m': (None if measured_required is None
                                                else threshold - measured_required),
                    'brake_final4_basis_required_clearance_m': envelope_required,
                    'brake_final4_basis_margin_m': (None if envelope_required is None
                                                    else threshold - envelope_required),
                    'measured_envelope_gap_at_trigger_m': trigger['envelope_gap_m'],
                    'envelope_gap_at_trigger_derived_from_threshold_m': (
                        threshold - body_radius - obstacle_radius),
                    'threshold_m': threshold,
                    'note': ('two decompositions kept separate to avoid double '
                             'counting: (i) measured stop distance from the STOP '
                             'trigger already contains the transport delay; '
                             '(ii) brake_final4 distance starts at actuation, so '
                             'v0*action_delay is added explicitly.  Both add '
                             'closing*age + envelope radii.  Not strict worst cases.'),
                }
                trigger_events.append(analysed)
        payload['runs'][label] = {
            'run_dir': str(run_dir),
            'manifest_freeze': manifest.get('freeze'),
            'outcomes': {item['outcome']: sum(
                1 for episode in episodes if episode['outcome'] == item['outcome'])
                for item in [{'outcome': name} for name in
                            ('SUCCESS', 'ABORT', 'TIMEOUT', 'COLLISION',
                             'OUT_OF_BOUNDS', 'INVALID')]},
            'episodes': [{key: value for key, value in analysed.items()
                          if key not in ('body_half_extents_m',)}
                         for analysed in
                         [analyse_episode(episode_rows(steps, episode['episode_id']),
                                          manifest, cases[episode['case_id']],
                                          brake_points, action_delay_s)
                          for episode in episodes]],
            'brake_events': trigger_events,
        }

    payload['ttl'] = analyse_ttl([args.run_a, args.run_b])

    for item in args.special:
        label, directory = item.split('=', 1)
        run_dir = Path(directory)
        manifest, episodes, steps = summarise_run(run_dir)
        entry = {
            'run_dir': directory,
            'outcomes': [{'episode_id': episode['episode_id'],
                          'outcome': episode['outcome'],
                          'reason': episode['reason'],
                          'post_abort': (episode.get('metrics') or {}).get('post_abort')}
                         for episode in episodes],
            'ttl': analyse_ttl([run_dir]),
        }
        rejections = []
        mapping_unusable = 0
        stale_rejections = 0
        for row in steps:
            transport = row.get('transport') or {}
            if transport.get('status') == 'REJECTED':
                rejections.append({
                    'episode_id': row.get('episode_id'),
                    'step': row.get('step'),
                    'reason': transport.get('reason'),
                    'arrival_age_s': transport.get('arrival_age_s'),
                    'applied_action_id': (transport.get('applied') or {}).get('action_id'),
                })
            clock = row.get('clock') or {}
            if clock.get('mapping_usable') is False:
                mapping_unusable += 1
            if row.get('v2_admission') == 'REJECTED' and \
                    row.get('v2_reject_reason') == 'REJECT_STALE_OBSERVATION':
                stale_rejections += 1
        entry['arrival_rejections'] = rejections[:10]
        entry['mapping_unusable_steps'] = mapping_unusable
        entry['stale_observation_admission_rejections'] = stale_rejections
        entry['phase_counts'] = {
            phase: sum(1 for row in steps if row.get('phase', 'RUN') == phase)
            for phase in ('RUN', 'POST_ABORT')
        }
        run_rows = [row for row in steps if row.get('phase', 'RUN') == 'RUN']
        first_rejection = None
        for row in run_rows:
            transport = row.get('transport') or {}
            if transport.get('status') == 'REJECTED':
                first_rejection = row
                break
        ttl_criterion = None
        if first_rejection is not None:
            first_transport = first_rejection.get('transport') or {}
            before = [row for row in run_rows
                      if int(row.get('step', 0)) < int(first_rejection.get('step', 0))
                      and (row.get('transport') or {}).get('status') == 'APPLIED']
            last_active = before[-1] if before else None
            rejected_id = first_transport.get('action_id')
            executed_after = [
                (row.get('transport') or {}).get('executed_action_id')
                for row in steps
                if (row.get('transport') or {}).get('executed_action_id')]
            last_row = steps[-1]
            residual = dist(first_rejection['position_world_m'],
                            last_row['position_world_m'])
            ttl_criterion = {
                'first_rejection': {
                    'step': first_rejection.get('step'),
                    'time_s': first_rejection.get('time_s'),
                    'reason': first_transport.get('reason'),
                    'arrival_age_s': first_transport.get('arrival_age_s'),
                    'executed': first_transport.get('executed'),
                    'speed_mps': first_rejection.get('speed_mps'),
                },
                'last_valid_active_before_rejection': (
                    None if last_active is None else {
                        'step': last_active.get('step'),
                        'action_id': (last_active.get('transport') or {}).get(
                            'applied', {}).get('action_id')
                        if (last_active.get('transport') or {}).get('applied')
                        else None,
                        'applied_expires_at_ns': (
                            (last_active.get('transport') or {}).get('applied') or {}
                        ).get('expires_at_ns'),
                        'host_now_ns': (last_active.get('clock') or {}).get(
                            'host_now_ns'),
                    }),
                'rejected_action_id_never_executed': (
                    rejected_id is None or rejected_id not in executed_after),
                'expiry_to_none_row': next(
                    ({'step': row.get('step'),
                      'reason': (row.get('transport') or {}).get('reason')}
                     for row in reversed(run_rows)
                     if int(row.get('step', 0)) <= int(first_rejection.get('step', 0))
                     and (row.get('transport') or {}).get('status') == 'NONE'
                     and (row.get('transport') or {}).get('reason')
                     == 'ACTION_EXPIRED'),
                    None),
                'residual_distance_from_first_rejection_m': residual,
                'queue_order_note': (
                    'monotonic dispatch: an expired arrival is always issued after '
                    'the current active setpoint, so the active has necessarily '
                    'expired too; simultaneous applied residual on the rejection row '
                    'is impossible. Residual evidence is the APPLIED rows immediately '
                    'before the first rejection plus the expiry->NONE transition.'),
            }
        entry['ttl_over_criterion_c'] = ttl_criterion
        payload['specials'][label] = entry

    for item in args.regression:
        label, directory = item.split('=', 1)
        manifest, episodes, steps = summarise_run(Path(directory))
        payload['regressions'][label] = {
            'run_dir': directory,
            'outcomes': [{'episode_id': episode['episode_id'],
                          'outcome': episode['outcome'],
                          'reason': episode['reason']} for episode in episodes],
            'clock_plan': manifest.get('clock_plan'),
            'latency_plan': {key: manifest.get('latency_plan', {}).get(key)
                             for key in ('obs_delay_s', 'action_delay_s',
                                         'ttl_ms', 'clock_offset_ms',
                                         'clock_drift_ppm',
                                         'clock_uncertainty_ms')},
        }

    summary = {
        'main_outcomes': payload['runs'],
        'trigger_clearance_reconstructed_m': {
            label: [{'episode_id': event['episode_id'],
                     'reconstructed_m': (event['brake_trigger']['derived']
                                         ['clearance_reconstructed'] or {}).get(
                                             'clearance_reconstructed_m'),
                     'threshold_m': event['brake_trigger']['derived']['threshold_m'],
                     'scenario_class': event['scenario_class']}
                    for event in payload['runs'][label]['brake_events']]
            for label in payload['runs']},
        'required_clearance_measured_basis': {
            label: [{'episode_id': event['episode_id'],
                     'required_m': event['brake_trigger']['derived']
                     ['measured_basis_required_clearance_m'],
                     'margin_m': event['brake_trigger']['derived']
                     ['measured_basis_margin_m'],
                     'threshold_m': event['brake_trigger']['derived']['threshold_m']}
                    for event in payload['runs'][label]['brake_events']]
            for label in payload['runs']},
        'required_clearance_brake_final4_basis': {
            label: [{'episode_id': event['episode_id'],
                     'required_m': event['brake_trigger']['derived']
                     ['brake_final4_basis_required_clearance_m'],
                     'margin_m': event['brake_trigger']['derived']
                     ['brake_final4_basis_margin_m']}
                    for event in payload['runs'][label]['brake_events']]
            for label in payload['runs']},
        'ttl_applicability': {
            'control_tick_s': 0.05,
            'ttl_ms': ttl_ms,
            'accepted_arrival_age_s': payload['ttl']['accepted_age_s'],
            'rejected_arrival_age_s': payload['ttl']['rejected_age_s'],
            'max_tolerable_delay_quantized_s': 0.10,
            'note': ('with a 50 ms control tick the arrival age quantizes to '
                     '0/50/100/150 ms; 150 ms equals the TTL and is rejected, so only '
                     '<=100 ms transport delay is usable at TTL=150 ms.'),
        },
        'labels': {
            'reconstructed_clearance': 'derived from raw rows (replay + case trajectory)',
            'required_clearance': 'derived; conservative combination, not strict bound',
            'brake_envelope': 'measured in brake_final4 (prior formal evidence)',
            'post_stop_obstacle_motion': 'measured',
        },
    }
    payload['summary'] = summary
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({
        'runs': {label: payload['runs'][label]['outcomes']
                 for label in payload['runs']},
        'ttl': payload['ttl'],
        'brake_events': {label: len(payload['runs'][label]['brake_events'])
                         for label in payload['runs']},
    }, indent=2))


if __name__ == '__main__':
    main()
