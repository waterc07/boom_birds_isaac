"""Tests for scripts/verify_clearance_boundary_runs.py.

The fixtures are synthetic raw-record directories that mimic the contract fixed
by docs/superpowers/plans/2026-11-02-clearance-boundary.md (sections 2, 3, 4 and
6).  The positive fixture is generated with the verifier's own recompute helpers
(clearance prediction, stop requirement, episode metrics) so that a clean run is
self-consistent; negative tests then tamper exactly one recorded value and assert
that the intended check branch fires.

Coverage: every check category (data_integrity / contract_invariant /
scenario_expectation / performance_boundary), the "deviation is not a PASS"
rule, "missing field => INCOMPLETE", and "freeze lineage / hash mismatch => FAIL".
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'verify_clearance_boundary_runs.py'


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'verify_clearance_boundary_runs_ut', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()

DT = 0.05
BODY_HALF = [0.05454223374277353, 0.03820826672017574, 0.013588040310423821]
BODY_RADIUS = math.sqrt(sum(value * value for value in BODY_HALF))
OBSTACLE_SIZE = [0.4, 0.4, 0.6]
OBSTACLE_RADIUS = 0.3
OBS_DELAY_S = 0.15
ACTION_DELAY_S = 0.10
TTL_MS = 150.0
STOP_DISTANCE_M = 1.1
PROPOSED_MARGIN_M = 0.2
POST_ABORT_OBSERVE_S = 3.0
OFFSET_NS = 20_000_000
UNCERTAINTY_NS = 5_000_000
DRIFT_PPM = 200.0
CODE_COMMIT = 'a' * 40
FROZEN_AT = '2026-11-02T00:00:00+00:00'
STARTED_AT = '2026-11-02T00:10:00+00:00'
OBSTACLE_POSITION = [1.5, 0.0, 0.5]
WAYPOINTS = [[5.0, 0.0, 0.5]]
BRAKE_MODEL = {
    'schema_version': MODULE.BRAKE_MODEL_SCHEMA,
    'model_id': 'brake_final4.v1',
    'source': {'path': 'docs/reports/map_eval/verify_brake_final.json',
               'sha256': 'b' * 64},
    'supported_speed_range_mps': [0.0, 0.9],
    'points': [
        {'speed_mps': 0.0, 'brake_distance_m': 0.0, 'stop_time_s': 0.5},
        {'speed_mps': 0.25, 'brake_distance_m': 0.09, 'stop_time_s': 1.0},
        {'speed_mps': 0.5, 'brake_distance_m': 0.21, 'stop_time_s': 1.25},
        {'speed_mps': 0.9, 'brake_distance_m': 0.60, 'stop_time_s': 1.3},
    ],
    'interpolation': 'piecewise_linear_in_speed',
    'extrapolation': 'forbidden',
}
SUPERVISOR = {'prediction_horizon_s': 1.0, 'prediction_step_s': 0.1,
              'stop_distance_m': STOP_DISTANCE_M}


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')


def _write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def _read_jsonl(path):
    return [json.loads(line) for line in
            Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _refresh_outputs(run_dir):
    manifest_path = Path(run_dir) / 'manifest.json'
    manifest = _read_json(manifest_path)
    manifest['outputs_sha256'] = {
        name: _sha(Path(run_dir) / name)
        for name in ('episodes.jsonl', 'steps.jsonl')}
    _write_json(manifest_path, manifest)


def _clock(host_ns, obs_delay_ns=150_000_000):
    capture_host = max(0, host_ns - obs_delay_ns)
    capture_clock = round(capture_host + OFFSET_NS
                          + capture_host * DRIFT_PPM / 1e6)
    mapped = round((capture_clock - OFFSET_NS) / (1.0 + DRIFT_PPM / 1e6))
    error = (abs(OFFSET_NS) + UNCERTAINTY_NS
             + math.ceil(abs(DRIFT_PPM) * 1e-6 * abs(host_ns)))
    point = max(0.0, (host_ns - mapped) / 1e9)
    return {
        'host_now_ns': host_ns, 'capture_host_ns': capture_host,
        'capture_clock_ns': capture_clock, 'camera_clock_id': 'camera_sim',
        'mapping_host_ns': mapped, 'mapping_error_ns': error,
        'mapping_sync_generation': 0, 'mapping_usable': True,
        'mapping_reason': 'ACCEPT', 'age_point_s': point,
        'age_bound_s': point + error / 1e9}


def _speed(index, brake_step, v0):
    if index < brake_step:
        return v0
    return max(0.0, v0 * (1.0 - (index - brake_step + 1) / 17.0))


def _state(index, brake_step):
    speed = _speed(index, brake_step, 1.0)
    if index < brake_step:
        return 'FOLLOW', 'ROUTE'
    if speed > 0.12:
        return 'BRAKE', 'STOP'
    if index < brake_step + 23:
        return 'HOLD', 'STOP'
    return 'WAIT', 'STOP'


def _clearance_record(row, robot, velocity, obstacle_center,
                      obstacle_velocity, clock):
    inputs = {
        'robot_center_world_m': list(robot),
        'robot_velocity_world_mps': list(velocity),
        'target_waypoint_world_m': list(WAYPOINTS[0]),
        'waypoint_index': 0,
        'obstacle_observed_center_world_m': list(obstacle_center),
        'obstacle_observed_velocity_world_mps': list(obstacle_velocity),
        'observation_age_point_s': clock['age_point_s'],
        'observation_age_bound_s': clock['age_bound_s'],
        'observation_valid': True,
        'observation_reason': 'ACCEPT',
    }
    recomputed = MODULE._recompute_clearance(inputs, 1.0, 0.1)
    center = recomputed['center_distance_m']
    path = recomputed['path_clearance_m']
    sum_radii = BODY_RADIUS + OBSTACLE_RADIUS
    return {
        'schema_version': MODULE.CLEARANCE_SCHEMA_VERSION,
        'algorithm': {
            'id': MODULE.CLEARANCE_ALGORITHM_ID,
            'version': MODULE.CLEARANCE_ALGORITHM_VERSION,
            'units': 'm', 'frame': 'world_ENU_Z_up',
            'time_base': 'simulation_time_s',
            'prediction_horizon_s': 1.0, 'prediction_step_s': 0.1},
        'inputs': inputs,
        'prediction': {
            'obstacle_predicted_centers_world_m': recomputed['centers'],
            'point_distances_m': recomputed['distances'],
            'min_index': recomputed['min_index']},
        'metrics': {
            'center_distance_m': center,
            'envelope_gap_sphere_m': center - sum_radii,
            'path_clearance_m': path,
            'path_clearance_gap_sphere_m': path - sum_radii},
        'envelopes': {
            'robot': {
                'kind': 'sphere_over_spawn_aabb_half_diagonal',
                'radius_m': BODY_RADIUS,
                'aabb_half_extents_m': list(BODY_HALF),
                'measured_prim': '/World/envs/env_0/Robot',
                'source': 'measured_usd_aabb_at_runtime',
                'attitude_scope': 'any_rigid_rotation_about_center',
                'limitation': 'AABB approximation; not a mesh sweep'},
            'obstacle': {
                'kind': 'sphere_over_case_cuboid',
                'radius_m': OBSTACLE_RADIUS,
                'size_m': list(OBSTACLE_SIZE),
                'source': 'case_obstacle_size'}},
        'validity': {'valid': True, 'reasons': []},
        'applicability': {
            'status': 'SUPPORTED', 'reasons': [],
            'notes': ['path clearance is not center distance or surface gap']},
    }


def _stop_requirement_record(model, row, clock, age_override=None):
    speed = float(row['speed_mps'])
    closing = float(row.get('closing_speed_mps') or 0.0)
    age = clock['age_bound_s'] if age_override is None else age_override
    inputs = {
        'robot_speed_mps': speed,
        'closing_speed_mps': closing,
        'observation_age_bound_s': age,
        'action_delay_s': ACTION_DELAY_S,
        'action_ttl_remaining_s': TTL_MS / 1000.0,
        'robot_radius_m': BODY_RADIUS,
        'obstacle_radius_m': OBSTACLE_RADIUS,
        'stop_threshold_m': STOP_DISTANCE_M,
        'proposed_margin_m': PROPOSED_MARGIN_M,
    }
    expected = MODULE._expected_stop_requirement(
        inputs, 'actuation', STOP_DISTANCE_M, PROPOSED_MARGIN_M, model,
        SUPERVISOR)
    reasons = list(expected['blocking_reasons']) + list(expected['marker_reasons'])
    return {
        'schema_version': MODULE.STOP_REQUIREMENT_SCHEMA_VERSION,
        'model_id': 'brake_final4.v1',
        'basis': 'actuation',
        'inputs': inputs,
        'terms': {
            'brake_distance_m': expected['brake_distance_m'],
            'transport_reaction_m': expected['transport_reaction_m'],
            'observation_age_motion_m': expected['observation_age_motion_m'],
            'envelope_sum_m': expected['envelope_sum_m']},
        'required_clearance_m': expected['required_clearance_m'],
        'margin_to_threshold_m': expected['margin_to_threshold_m'],
        'status': expected['status'],
        'status_reasons': reasons,
    }


def _none_transport():
    return {
        'status': 'NONE', 'action_id': '', 'executed_action_id': '',
        'issued_at_ns': 0, 'expires_at_ns': 0, 'scheduled_arrival_ns': 0,
        'arrival_ns': 0, 'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
        'reason': 'REJECT_NO_CACHED_ACTION', 'executed': False,
        'rejections_this_step': []}


def _zero_applied():
    return {
        'vx_forward_mps': 0.0, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
        'yaw_rate_ccw_world_radps': 0.0, 'action_id': '',
        'issued_at_ns': 0, 'expires_at_ns': 0, 'age_s': 0.0,
        'is_held': False}


def _base_row(episode_id, case_id, scenario_class, step, time_s, phase,
              position, speed, state, action, outcome, reason,
              transport=None, applied=None, clock=None,
              obstacle_position=None):
    host = round(time_s * 1e9)
    if clock is None:
        clock = _clock(host)
    row = {
        'episode_id': episode_id, 'case_id': case_id, 'method': 'supervisor',
        'scenario_class': scenario_class, 'step': step, 'time_s': time_s,
        'phase': phase, 'position_world_m': list(position),
        'velocity_world_mps': [speed, 0.0, 0.0], 'speed_mps': speed,
        'command': [speed, 0.0, 0.0, 0.0], 'execution_path': 'v2',
        'clock': clock,
        'observation_age_s': clock['age_bound_s']
        if phase == 'RUN' else None,
        'observation_valid': phase == 'RUN',
        'observation_reason': 'ACCEPT' if phase == 'RUN' else 'DROPOUT',
        'transport': transport or _none_transport(),
        'applied': applied or _zero_applied(),
        'obstacle_position_world_m': list(obstacle_position
                                          or OBSTACLE_POSITION),
        'obstacle_velocity_world_mps': [0.0, 0.0, 0.0],
        'supervisor_state': state, 'supervisor_action': action,
        'supervisor_wait_s': 0.0, 'route_active_s': time_s,
        'contact_force_n': 0.0, 'contact_prim': '',
        'outcome': outcome, 'reason': reason,
        'env_terminated': False, 'env_truncated': False,
        'episode_length_buf': step + 1, 'boundary_count_ok': True,
        'v2_admission': 'ADMITTED' if phase == 'RUN' else '',
        'v2_action_id': 'ACT-%s-%d' % (episode_id, step)
        if phase == 'RUN' else '',
        'v2_reject_reason': '', 'v2_executed': phase == 'RUN',
        'v2_fault_type': None,
    }
    return row


RADII_SUM = BODY_RADIUS + OBSTACLE_RADIUS


def _contact_evidence(robot_position, obstacle_position, speed, time_s,
                      measured_force=0.0, force_available=False):
    center = math.dist([float(value) for value in robot_position],
                       [float(value) for value in obstacle_position])
    overlap = max(0.0, RADII_SUM - center)
    inferred = overlap > MODULE.CONTACT_OVERLAP_M
    return {
        'sensor_force_n': measured_force,
        'force_sensor_available': force_available,
        'center_distance_m': center,
        'radii_sum_m': RADII_SUM,
        'sphere_overlap_m': overlap,
        'inferred_contact': inferred,
        'inferred_contact_time_s': time_s,
        'command_all_zero': speed == 0.0,
        'robot_speed_mps': speed,
    }


def _build_rows(episode_id, case_id, scenario_class, v0, brake_step,
                n_physical, contacts, business_outcome, post_abort_rows):
    model = MODULE.BrakeModel(BRAKE_MODEL, None)
    model.load(MODULE.Verifier())
    rows = []
    position = [0.0, 0.0, 0.5]
    previous_center = None
    for index in range(n_physical):
        time_s = round((index + 1) * DT, 6)
        speed = _speed(index, brake_step, v0)
        state, action = _state(index, brake_step)
        if index < brake_step:
            state, action = 'FOLLOW', 'ROUTE'
        host = round(time_s * 1e9)
        ticket = {
            'status': 'DIRECT',
            'action_id': 'ACT-%s-%d' % (episode_id, index),
            'executed_action_id': 'ACT-%s-%d' % (episode_id, index),
            'issued_at_ns': host, 'expires_at_ns': host + int(TTL_MS * 1e6),
            'scheduled_arrival_ns': host, 'arrival_ns': host,
            'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
            'reason': 'ACCEPT', 'executed': True,
            'rejections_this_step': []}
        applied = {
            'vx_forward_mps': speed, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
            'yaw_rate_ccw_world_radps': 0.0,
            'action_id': ticket['action_id'],
            'issued_at_ns': ticket['issued_at_ns'],
            'expires_at_ns': ticket['expires_at_ns'],
            'age_s': 0.0, 'is_held': False}
        overlap_target = contacts.get(index)
        if overlap_target is not None:
            obstacle_position = [position[0] + (RADII_SUM - overlap_target),
                                 0.0, 0.5]
        else:
            obstacle_position = list(OBSTACLE_POSITION)
        row = _base_row(episode_id, case_id, scenario_class, index, time_s,
                        'RUN', position, speed, state, action, 'RUNNING',
                        'RUNNING', transport=ticket, applied=applied,
                        obstacle_position=obstacle_position)
        evidence = _contact_evidence(position, obstacle_position, speed,
                                     time_s)
        row['contact_evidence'] = evidence
        row['contact_prim'] = ('INFERRED_OBSTACLE_OVERLAP'
                               if evidence['inferred_contact'] else '')
        center = evidence['center_distance_m']
        if previous_center is None:
            closing = 0.0
        else:
            closing = max(0.0, (previous_center - center) / DT)
        previous_center = center
        row['closing_speed_mps'] = closing
        row['clearance'] = _clearance_record(
            row, position, [speed, 0.0, 0.0], obstacle_position,
            [0.0, 0.0, 0.0], row['clock'])
        row['stop_requirement'] = _stop_requirement_record(
            model, row, row['clock'])
        rows.append(row)
        position = [position[0] + speed * DT, position[1], position[2]]
    decision_time = round(n_physical * DT + DT, 6)
    host = round(decision_time * 1e9)
    decision = _base_row(episode_id, case_id, scenario_class, n_physical,
                         decision_time, 'RUN', position, 0.0, 'ABORT', 'ABORT',
                         business_outcome, 'MAX_WAIT_EXCEEDED')
    decision['clock'] = _clock(host)
    decision['observation_age_s'] = decision['clock']['age_bound_s']
    decision['observation_valid'] = True
    decision['observation_reason'] = 'ACCEPT'
    decision['v2_admission'] = ''
    decision['v2_action_id'] = ''
    decision['v2_executed'] = False
    decision['closing_speed_mps'] = 0.0
    decision['contact_evidence'] = _contact_evidence(
        position, OBSTACLE_POSITION, 0.0, decision_time)
    decision['clearance'] = _clearance_record(
        decision, position, [0.0, 0.0, 0.0], OBSTACLE_POSITION,
        [0.0, 0.0, 0.0], decision['clock'])
    decision['stop_requirement'] = _stop_requirement_record(
        model, decision, decision['clock'])
    rows.append(decision)
    for jump in range(1, post_abort_rows + 1):
        time_s = round(decision_time + jump * DT, 6)
        post = _base_row(
            episode_id, case_id, scenario_class, n_physical + jump - 1,
            time_s, 'POST_ABORT', position, 0.0, 'ABORT', 'ABORT',
            business_outcome, 'MAX_WAIT_EXCEEDED')
        post['contact_evidence'] = _contact_evidence(
            position, OBSTACLE_POSITION, 0.0, time_s)
        rows.append(post)
    return rows


def _build_episode(episode_id, case_id, scenario_class, business_outcome,
                   rows, contacts, scenario_class_recorded=None,
                   segment_id='boundary_default'):
    episode = {
        'episode_id': episode_id, 'case_id': case_id,
        'segment_id': segment_id, 'method': 'supervisor',
        'scenario_class': scenario_class_recorded or scenario_class,
        'business_outcome': business_outcome,
        'physical_outcome': 'NO_CONTACT',
        'steps': len([row for row in rows if row.get('phase') != 'POST_ABORT']) - 1,
        'duration_s': None,
        'obstacle': {'obstacle_id': 'obs_A', 'size_m': list(OBSTACLE_SIZE),
                     'kind': 'linear'},
        'waypoints': [list(point) for point in WAYPOINTS],
    }
    episode['duration_s'] = round(episode['steps'] * DT, 6)
    # Recompute the recorded metrics with the verifier's own helpers so the
    # positive fixture is self-consistent; negative tests tamper one value.
    stop_stats = {
        'unsupported_steps': 0, 'unsupported_reasons': {},
        'max_robot_speed_mps': 0.0, 'min_margin_m': None,
    }
    for row in rows:
        record = row.get('stop_requirement')
        if not isinstance(record, dict):
            continue
        if record.get('status') == 'UNSUPPORTED':
            stop_stats['unsupported_steps'] += 1
            for reason in record.get('status_reasons') or []:
                stop_stats['unsupported_reasons'][reason] = \
                    stop_stats['unsupported_reasons'].get(reason, 0) + 1
        speed = record['inputs']['robot_speed_mps']
        stop_stats['max_robot_speed_mps'] = max(
            stop_stats['max_robot_speed_mps'], speed)
        margin = record.get('margin_to_threshold_m')
        if margin is not None:
            stop_stats['min_margin_m'] = margin \
                if stop_stats['min_margin_m'] is None \
                else min(stop_stats['min_margin_m'], margin)
    ctx = {'dt': DT, 'analysis_ref': {'stop_requirement': stop_stats}}
    rebuilt = MODULE._rebuild_metrics(rows, episode, ctx)
    episode['physical_outcome'] = rebuilt['physical_outcome']
    contact_rows = [row['contact_evidence'] for row in rows
                    if isinstance(row.get('contact_evidence'), dict)]
    inferred_rows = [entry for entry in contact_rows
                     if entry.get('inferred_contact')]
    inferred_time = min((entry['inferred_contact_time_s']
                         for entry in inferred_rows), default=None)
    episode['metrics'] = {
        'brake_start': rebuilt['brake_start'],
        'initial_speed_mps': rebuilt['initial_speed_mps'],
        'stop_distance_m': rebuilt['stop_distance_m'],
        'stop_time_s': rebuilt['stop_time_s'],
        'stop_definition': rebuilt['stop_definition'],
        'min_path_clearance_m': rebuilt['min_path_clearance_m'],
        'min_path_clearance_gap_sphere_m':
            rebuilt['min_path_clearance_gap_sphere_m'],
        'min_center_distance_m': rebuilt['min_center_distance_m'],
        'min_envelope_gap_sphere_m': rebuilt['min_envelope_gap_sphere_m'],
        'conservative_envelope': {
            'robot_radius_m': BODY_RADIUS,
            'robot_aabb_half_extents_m': list(BODY_HALF),
            'robot_source': 'measured_usd_aabb_at_runtime',
            'robot_measurement': '/World/envs/env_0/Robot',
            'obstacle_radius_m': OBSTACLE_RADIUS,
            'obstacle_size_m': list(OBSTACLE_SIZE),
            'obstacle_source': 'case_obstacle_size',
            'attitude_scope': 'any_rigid_rotation_about_center'},
        'stop_requirement_extremes': {
            'min_margin_m': stop_stats['min_margin_m'],
            'unsupported_steps': stop_stats['unsupported_steps'],
            'unsupported_reasons': stop_stats['unsupported_reasons'],
            'max_robot_speed_mps': stop_stats['max_robot_speed_mps']},
        'max_closing_speed_mps': rebuilt['max_closing_speed_mps'],
        'max_relative_speed_mps': rebuilt['max_relative_speed_mps'],
        'contact_max_force_n': rebuilt['contact_max_force_n'],
        'contact_prim': rebuilt['contact_prim'],
        'contact_evidence_summary': {
            'max_sensor_force_n': max((entry.get('sensor_force_n') or 0.0
                                       for entry in contact_rows),
                                      default=0.0),
            'max_sphere_overlap_m': max((entry.get('sphere_overlap_m') or 0.0
                                         for entry in contact_rows),
                                        default=0.0),
            'inferred_contact': bool(inferred_rows),
            'first_inferred_contact_time_s': inferred_time,
            'radii_sum_m': RADII_SUM,
        },
        'post_abort': rebuilt['post_abort'],
    }
    episode['phase_summary'] = {
        'RUN': len([row for row in rows if row.get('phase') == 'RUN']),
        'POST_ABORT': len([row for row in rows
                           if row.get('phase') == 'POST_ABORT']),
    }
    return episode


def _plan(case_ids, segment_id='boundary_default', role='boundary',
          expected_sha256=None, brake_sha256=None, cases_sha256=None,
          vehicle_sha256='c' * 64):
    return {
        'role': role, 'segment_id': segment_id, 'config_id': '',
        'cases_file': 'fixture_cases.json',
        'cases_sha256': cases_sha256,
        'case_ids': list(case_ids), 'methods': ['supervisor'],
        'execution_path': 'v2', 'obs_delay_s': OBS_DELAY_S,
        'action_delay_s': ACTION_DELAY_S, 'ttl_ms': TTL_MS,
        'max_age_ms': 150.0, 'allowed_observation_age_ms': 300.0,
        'stop_distance_m': STOP_DISTANCE_M,
        'post_abort_observe_s': POST_ABORT_OBSERVE_S,
        'clock_offset_ms': 20.0, 'clock_drift_ppm': DRIFT_PPM,
        'clock_uncertainty_ms': 5.0, 'sync_fail_step': -1,
        'obs_mapping_fail_step': -1, 'transport_stall_step': -1,
        'transport_stall_delay_s': OBS_DELAY_S,
        'expected_sha256': expected_sha256,
        'brake_model_sha256': brake_sha256,
        'vehicle_config_file': 'fixture_vehicle.json',
        'vehicle_config_sha256': vehicle_sha256,
        'control_step_s': DT,
    }


def _manifest(run_dir, plan, freeze_path, body_half, case_ids,
              frozen_at=FROZEN_AT):
    return {
        'schema_version': 'boom_birds.manifest.v1',
        'code_commit': CODE_COMMIT,
        'gui_mode': True,
        'renderer': 'DirectX (--/app/vulkan=false)',
        'command': 'scripts/run_dynamic_eval.py --segment-id %s'
                   % plan['segment_id'],
        'started_at': STARTED_AT,
        'methods': ['supervisor'],
        'episode_ids': list(case_ids),
        'cases_sha256': plan['cases_sha256'],
        'clearance_schema_version': MODULE.CLEARANCE_SCHEMA_VERSION,
        'stop_requirement_schema_version':
            MODULE.STOP_REQUIREMENT_SCHEMA_VERSION,
        'clearance_algorithm': {'id': MODULE.CLEARANCE_ALGORITHM_ID,
                                'version': MODULE.CLEARANCE_ALGORITHM_VERSION},
        'brake_model': {'model_id': 'brake_final4.v1',
                        'sha256': plan['brake_model_sha256']},
        'vehicle_config': {'path': plan['vehicle_config_file'],
                           'sha256': plan['vehicle_config_sha256']},
        'body_envelope': {'half_extents_m': list(body_half),
                          'source': 'measured_usd_aabb_at_runtime',
                          'measured_prim': '/World/envs/env_0/Robot'},
        'envelope_policy': {
            'robot_envelope': 'sphere_over_spawn_aabb_half_diagonal',
            'obstacle_envelope': 'sphere_over_case_cuboid'},
        'freeze': {'path': str(freeze_path), 'sha256': _sha(freeze_path),
                   'schema_version': MODULE.BOUNDARY_FREEZE_SCHEMA,
                   'frozen_at': frozen_at, 'code_commit': CODE_COMMIT},
        'boundary_plan': plan,
        'gui_evidence': {'gui_mode': True,
                         'renderer': 'DirectX (--/app/vulkan=false)',
                         'headless': False, 'window_required': True,
                         'screenshots': False},
        'outputs_sha256': {},
    }


def _expected_payload(case_id, scenario_class, acceptable, must_conditions,
                      unsupported_allowed, repeats=1,
                      status='EXPECTED_NOT_CONCLUSION',
                      segments=None):
    payload = {
        'schema_version': MODULE.BOUNDARY_EXPECTED_SCHEMA,
        'status': status,
        'cases_file': 'fixture_cases.json',
        'brake_model_file': 'fixture_brake_model.json',
        'supervisor': dict(SUPERVISOR),
        'proposed_margin_m': PROPOSED_MARGIN_M,
        'cases': {
            case_id: {
                'scenario_class': scenario_class,
                'acceptable_outcomes': list(acceptable),
                'must_conditions': list(must_conditions),
                'unsupported_allowed': unsupported_allowed,
                'repeats': repeats,
            },
        },
    }
    if segments is not None:
        payload['segments'] = segments
    return payload


def _freeze_payload(plan, case_ids, expected_sha, brake_sha, cases_sha):
    return {
        'schema_version': MODULE.BOUNDARY_FREEZE_SCHEMA,
        'artifact': 'fixture',
        'status': 'PRE_RUN_FROZEN',
        'frozen_at': FROZEN_AT,
        'code_commit': CODE_COMMIT,
        'worktree_state': {'tracked_paths': [], 'status_text_sha256': 'd' * 64,
                           'clean': True},
        'cases_file': 'fixture_cases.json',
        'cases_sha256': cases_sha,
        'expected_file': 'fixture_expected.json',
        'expected_sha256': expected_sha,
        'brake_model_file': 'fixture_brake_model.json',
        'brake_model_sha256': brake_sha,
        'body_envelope': {'half_extents_m': list(BODY_HALF),
                          'source': 'measured_usd_aabb_at_runtime',
                          'measured_prim': '/World/envs/env_0/Robot'},
        'segments': {
            plan['segment_id']: {
                'segment_id': plan['segment_id'],
                'case_ids': list(case_ids),
                'run_plan': plan,
            },
        },
    }


def build_fixture(tmp_path, *, case_id='boundary_A_static_far_r0',
                  scenario_class='BLOCKED_EXIT',
                  business_outcome='ABORT', acceptable=('ABORT',),
                  must_conditions=('no_contact', 'stop_started'),
                  unsupported_allowed=False, repeats=1, v0=0.5,
                  brake_step=0, n_physical=45, contacts=None,
                  post_abort_rows=12, expected_status='EXPECTED_NOT_CONCLUSION',
                  frozen_at=FROZEN_AT, started_at=STARTED_AT,
                  renderer=None, freeze_schema=None, episode_scenario_class=None,
                  role='boundary', segment_id='boundary_default',
                  expected_segments=None, contact_sensor_valid=True,
                  contact_sensor_present=True, modify=None):
    """Build one synthetic boundary run directory and return its parts."""
    tmp_path = Path(tmp_path)
    contacts = dict(contacts or {})
    run_dir = tmp_path / 'run_default'
    run_dir.mkdir(parents=True, exist_ok=True)
    cases_path = tmp_path / 'fixture_cases.json'
    _write_json(cases_path, {'schema_version': 'fixture.cases.v1',
                             'cases': []})
    brake_path = tmp_path / 'fixture_brake_model.json'
    _write_json(brake_path, BRAKE_MODEL)
    expected_payload = _expected_payload(case_id, scenario_class, acceptable,
                                         must_conditions, unsupported_allowed,
                                         repeats, expected_status,
                                         segments=expected_segments)
    expected_path = tmp_path / 'fixture_expected.json'
    _write_json(expected_path, expected_payload)
    plan = _plan([case_id], segment_id=segment_id, role=role,
                 cases_sha256=_sha(cases_path),
                 expected_sha256=_sha(expected_path),
                 brake_sha256=_sha(brake_path))
    freeze = _freeze_payload(plan, [case_id], _sha(expected_path),
                             _sha(brake_path), _sha(cases_path))
    if freeze_schema is not None:
        freeze['schema_version'] = freeze_schema
    freeze['frozen_at'] = frozen_at
    freeze_path = tmp_path / 'fixture_freeze.json'
    _write_json(freeze_path, freeze)
    rows = _build_rows(case_id + '-supervisor', case_id, scenario_class, v0,
                       brake_step, n_physical, contacts, business_outcome,
                       post_abort_rows)
    episode = _build_episode(case_id + '-supervisor', case_id, scenario_class,
                             business_outcome, rows, contacts,
                             scenario_class_recorded=episode_scenario_class,
                             segment_id=segment_id)
    if modify is not None:
        modify(rows, episode, plan)
    manifest = _manifest(run_dir, plan, freeze_path, BODY_HALF,
                         [episode['episode_id']], frozen_at=frozen_at)
    manifest['started_at'] = started_at
    if renderer is not None:
        manifest['renderer'] = renderer
    if contact_sensor_present:
        manifest['contact_sensor'] = {
            'valid': bool(contact_sensor_valid),
            'mode': 'sphere_overlap_inference',
            'force_sensor_available': False,
            'reason': 'contact_force_sensor_not_reporting_in_this_environment',
            'inference_rule': {
                'sphere_overlap_m_gt': MODULE.CONTACT_OVERLAP_M,
                'conservative_radii': 'half_diagonal + obstacle max(size)/2',
            }}
    _write_json(run_dir / 'manifest.json', manifest)
    _write_jsonl(run_dir / 'episodes.jsonl', [episode])
    _write_jsonl(run_dir / 'steps.jsonl', rows)
    _refresh_outputs(run_dir)
    return {
        'tmp': tmp_path, 'run_dir': run_dir, 'cases': cases_path,
        'brake_model': brake_path, 'expected': expected_path,
        'freeze': freeze_path, 'plan': plan, 'episode': episode, 'rows': rows,
        'manifest': manifest,
    }


def run_verify(fixture, extra_runs=None):
    run_specs = extra_runs if extra_runs is not None else [
        '%s=%s' % (fixture['plan']['segment_id'], fixture['run_dir'])]
    parser = MODULE.build_parser()
    args = parser.parse_args([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--brake-model', str(fixture['brake_model']),
        '--repo-root', str(fixture['tmp']),
    ] + sum([['--run', spec] for spec in run_specs], []))
    return MODULE.run_verification(args, parser)


def _check(result, name):
    return result['checks'][name]


def _rewrite_steps(fixture, mutate):
    rows = _read_jsonl(fixture['run_dir'] / 'steps.jsonl')
    mutate(rows)
    _write_jsonl(fixture['run_dir'] / 'steps.jsonl', rows)
    _refresh_outputs(fixture['run_dir'])
    return rows


def _rewrite_episodes(fixture, mutate):
    episodes = _read_jsonl(fixture['run_dir'] / 'episodes.jsonl')
    mutate(episodes)
    _write_jsonl(fixture['run_dir'] / 'episodes.jsonl', episodes)
    _refresh_outputs(fixture['run_dir'])


def _find_row(rows, step, phase='RUN'):
    for row in rows:
        if row.get('step') == step and row.get('phase') == phase:
            return row
    raise AssertionError('row %s/%s not found' % (step, phase))


# ---------------------------------------------------------------------------
# positive fixture: every check category passes
# ---------------------------------------------------------------------------

def test_positive_fixture_passes(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])
    assert result['deviations'] == []
    assert result['failures'] == []
    categories = {entry['category'] for entry in result['checks'].values()}
    assert categories == set(MODULE.CATEGORIES)
    for name, entry in result['checks'].items():
        assert entry['passed'] is True, (name, entry)
    assert result['recomputed']['clearance']['records'] > 0
    assert result['recomputed']['stop_requirement']['records'] > 0
    assert result['performance']['boundary_episode_total'] == 1
    assert result['performance']['boundary_episode_expected'] == 1
    assert result['performance']['boundary_episodes_by_segment'][
        'boundary_default'] == {'expected': 1, 'observed': 1}
    assert result['freeze']['schema_version'] == MODULE.BOUNDARY_FREEZE_SCHEMA


def test_positive_fixture_has_no_unsupported_steps(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    assert result['unsupported']['stop_requirement']['step_count'] == 0
    assert result['recomputed']['stop_requirement']['by_reason'] == {}


def test_recorded_metrics_are_recomputed_not_trusted(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['metrics']['stop_distance_m'] = 999.0

    _rewrite_episodes(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'metrics_match_recorded')['passed'] is False


# ---------------------------------------------------------------------------
# data integrity
# ---------------------------------------------------------------------------

def test_missing_clearance_field_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        row = _find_row(rows, 5)
        del row['clearance']

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('clearance' in item for item in result['missing_fields'])
    assert _check(result, 'schema_completeness')['passed'] is False


def test_missing_episode_metric_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        del episodes[0]['metrics']['min_path_clearance_m']

    _rewrite_episodes(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('min_path_clearance_m' in item
               for item in result['missing_fields'])


def test_artifact_hash_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    # Tamper steps without refreshing outputs_sha256 -> artifact hash mismatch.
    rows = _read_jsonl(fixture['run_dir'] / 'steps.jsonl')
    rows[0]['speed_mps'] = 0.123
    _write_jsonl(fixture['run_dir'] / 'steps.jsonl', rows)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'artifact_hashes')['passed'] is False


def test_gui_renderer_must_be_directx(tmp_path):
    fixture = build_fixture(tmp_path, renderer='Vulkan')
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'gui_evidence')['passed'] is False


def test_step_time_must_be_monotonic(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        _find_row(rows, 3)['time_s'] = _find_row(rows, 2)['time_s']

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'step_time_monotonicity')['passed'] is False


def test_freeze_must_precede_the_run(tmp_path):
    fixture = build_fixture(tmp_path, frozen_at='2026-11-02T00:20:00+00:00',
                            started_at='2026-11-02T00:10:00+00:00')
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'freeze_lineage')['passed'] is False


def test_freeze_cases_hash_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    freeze = _read_json(fixture['freeze'])
    freeze['cases_sha256'] = '0' * 64
    _write_json(fixture['freeze'], freeze)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'artifact_hashes')['passed'] is False


def test_wrong_freeze_schema_fails(tmp_path):
    fixture = build_fixture(tmp_path, freeze_schema='boom_birds.latency_freeze.v2')
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'freeze_lineage')['passed'] is False


def test_declared_segment_without_run_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    # The frozen boundary_default run is not supplied, so the verification is
    # incomplete even though another declared segment directory exists.
    result = run_verify(fixture, extra_runs=[
        'boundary_fast=%s' % (fixture['tmp'] / 'missing_run')])
    assert result['status'] == 'INCOMPLETE'
    assert any('boundary_default' in item for item in result['missing_fields'])


def test_missing_expected_case_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    expected = _read_json(fixture['expected'])
    expected['cases']['boundary_second_case_r0'] = dict(
        expected['cases']['boundary_A_static_far_r0'])
    _write_json(fixture['expected'], expected)
    # The freeze is not updated, so this also proves the expected hash is checked;
    # the missing episode itself must make the status INCOMPLETE.
    result = run_verify(fixture)
    assert result['status'] in ('FAIL', 'INCOMPLETE')
    assert any('boundary_second_case_r0' in item
               for item in result['missing_fields'])


def test_missing_brake_model_file_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    parser = MODULE.build_parser()
    args = parser.parse_args([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--brake-model', str(fixture['tmp'] / 'no_such_brake_model.json'),
        '--repo-root', str(fixture['tmp']),
        '--run', '%s=%s' % (fixture['plan']['segment_id'], fixture['run_dir'])])
    result = MODULE.run_verification(args, parser)
    assert result['status'] == 'INCOMPLETE'
    assert any('brake' in item for item in result['missing_fields'])


# ---------------------------------------------------------------------------
# contract invariants: clearance geometry
# ---------------------------------------------------------------------------

def test_clearance_rebuild_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        _find_row(rows, 10)['clearance']['metrics']['path_clearance_m'] += 0.01

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_recompute')['passed'] is False


def test_prediction_point_count_must_match_horizon(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        record = _find_row(rows, 7)['clearance']
        record['prediction']['obstacle_predicted_centers_world_m'].pop()
        record['prediction']['point_distances_m'].pop()

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_prediction_structure')['passed'] is False


def test_robot_radius_must_be_half_diagonal_not_max_half_extent(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        robot = _find_row(rows, 4)['clearance']['envelopes']['robot']
        robot['radius_m'] = max(robot['aabb_half_extents_m'])

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_envelope_rules')['passed'] is False


def test_obstacle_radius_must_be_max_size_over_two(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        obstacle = _find_row(rows, 4)['clearance']['envelopes']['obstacle']
        obstacle['radius_m'] = max(obstacle['size_m'])

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_envelope_rules')['passed'] is False


def test_metric_aliasing_center_distance_as_envelope_gap_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        metrics = _find_row(rows, 9)['clearance']['metrics']
        metrics['envelope_gap_sphere_m'] = metrics['center_distance_m']

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_metric_semantics')['passed'] is False


def test_observation_age_bound_must_match_clock(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        row = _find_row(rows, 6)
        row['clearance']['inputs']['observation_age_bound_s'] += 0.01

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_observation_age')['passed'] is False


def test_supervisor_must_not_stay_following_below_threshold(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        row = _find_row(rows, 20)
        row['supervisor_state'] = 'FOLLOW'
        row['supervisor_action'] = 'ROUTE'

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'clearance_decision_consistency')['passed'] is False


# ---------------------------------------------------------------------------
# contract invariants: stop requirement / TTL / post abort
# ---------------------------------------------------------------------------

def test_stop_requirement_terms_are_recomputed(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        _find_row(rows, 20)['stop_requirement']['terms'][
            'brake_distance_m'] += 0.05

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'stop_requirement_recompute')['passed'] is False


def test_stop_requirement_no_extrapolation_above_support(tmp_path):
    fixture = build_fixture(tmp_path, v0=1.0)
    result = run_verify(fixture)
    # The recorded requirement was built by the verifier itself and correctly
    # returns UNSUPPORTED above 0.9 m/s, but the expected file does not allow it.
    assert _check(result, 'stop_requirement_support_boundary')['passed'] is True
    assert result['unsupported']['stop_requirement']['step_count'] > 0
    assert any(item['kind'] == 'unsupported_not_allowed'
               for item in result['deviations'])
    assert result['status'] == 'FAIL'


def test_unsupported_can_be_declared_allowed(tmp_path):
    fixture = build_fixture(tmp_path, v0=1.0, unsupported_allowed=True)
    result = run_verify(fixture)
    assert _check(result, 'stop_requirement_support_boundary')['passed'] is True
    assert _check(result, 'unsupported_allowed_scope')['passed'] is True
    assert result['deviations'] == []
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])


def test_extrapolated_brake_distance_is_rejected(tmp_path):
    fixture = build_fixture(tmp_path, v0=1.0, unsupported_allowed=True)

    def mutate(rows):
        record = _find_row(rows, 0)['stop_requirement']
        record['status'] = 'SUPPORTED'
        record['terms']['brake_distance_m'] = 0.71
        record['required_clearance_m'] = 1.0
        record['margin_to_threshold_m'] = 0.1

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'stop_requirement_support_boundary')['passed'] is False


def test_ttl_renewal_is_rejected(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        transport = _find_row(rows, 8)['transport']
        transport['expires_at_ns'] = transport['issued_at_ns'] + int(2 * TTL_MS * 1e6)

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'ttl_no_renewal')['passed'] is False


def test_rejected_action_must_never_be_executed(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        row = _find_row(rows, 12)
        rejected_id = row['transport']['executed_action_id']
        row['transport']['rejections_this_step'] = [{
            'action_id': rejected_id, 'reason': 'ACTION_EXPIRED',
            'arrival_age_s': 0.2}]

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'rejection_never_executed')['passed'] is False


def test_post_abort_new_setpoint_is_rejected(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        post = [row for row in rows if row.get('phase') == 'POST_ABORT'][0]
        post['transport'] = {
            'status': 'APPLIED', 'action_id': 'ACT-LATE',
            'executed_action_id': 'ACT-LATE',
            'issued_at_ns': round(post['time_s'] * 1e9),
            'expires_at_ns': round(post['time_s'] * 1e9) + 150_000_000,
            'scheduled_arrival_ns': round(post['time_s'] * 1e9),
            'arrival_ns': round(post['time_s'] * 1e9),
            'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
            'reason': 'ACCEPT', 'executed': True,
            'rejections_this_step': []}
        post['applied'] = {
            'vx_forward_mps': 0.2, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
            'yaw_rate_ccw_world_radps': 0.0, 'action_id': 'ACT-LATE',
            'issued_at_ns': post['transport']['issued_at_ns'],
            'expires_at_ns': post['transport']['expires_at_ns'],
            'age_s': 0.0, 'is_held': False}

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'post_abort_old_setpoint')['passed'] is False


def test_post_abort_window_must_have_rows(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        rows[:] = [row for row in rows if row.get('phase') != 'POST_ABORT']

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'post_abort_old_setpoint')['passed'] is False


# ---------------------------------------------------------------------------
# scenario expectations: deviations are separate from PASS
# ---------------------------------------------------------------------------

def test_scenario_class_mismatch_is_a_deviation_not_a_pass(tmp_path):
    fixture = build_fixture(tmp_path, episode_scenario_class='BLOCKED_EXIT_TIGHT')
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'scenario_class_match')['passed'] is False
    assert any(item['kind'] == 'scenario_class_mismatch'
               for item in result['deviations'])


def test_business_outcome_not_acceptable_is_a_deviation(tmp_path):
    fixture = build_fixture(tmp_path, acceptable=('TIMEOUT',))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'acceptable_outcomes')['passed'] is False
    assert any(item['kind'] == 'business_outcome_not_acceptable'
               for item in result['deviations'])


def test_failed_must_condition_is_a_deviation(tmp_path):
    fixture = build_fixture(tmp_path, must_conditions=('contact',))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'must_conditions')['passed'] is False
    assert any(item['kind'] == 'must_condition_failed'
               for item in result['deviations'])


def test_insufficient_margin_success_is_a_deviation(tmp_path):
    fixture = build_fixture(
        tmp_path, scenario_class='INSUFFICIENT_MARGIN',
        business_outcome='SUCCESS', acceptable=('SUCCESS',),
        must_conditions=(), unsupported_allowed=False)
    # The final RUN row must also carry the business outcome.
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'insufficient_margin_success_ban')['passed'] is False
    kinds = {item['kind'] for item in result['deviations']}
    assert 'insufficient_margin_success' in kinds


def test_post_stop_collision_requires_contact_after_stop(tmp_path):
    # Contact happens on the first row, long before the robot stop completes.
    fixture = build_fixture(
        tmp_path, scenario_class='POST_STOP_COLLISION',
        business_outcome='ABORT', acceptable=('ABORT',),
        must_conditions=('contact_after_business_stop',),
        unsupported_allowed=False, contacts={1: 0.5})
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'post_stop_collision_ordering')['passed'] is False
    kinds = {item['kind'] for item in result['deviations']}
    assert 'post_stop_collision_contact_before_stop' in kinds


def test_post_stop_collision_contact_after_stop_passes(tmp_path):
    # Contact after the stop window (stop completes near step 26 / 1.3 s).
    fixture = build_fixture(
        tmp_path, scenario_class='POST_STOP_COLLISION',
        business_outcome='ABORT', acceptable=('ABORT',),
        must_conditions=('contact_after_business_stop',),
        unsupported_allowed=False, contacts={43: 0.4})
    result = run_verify(fixture)
    assert _check(result, 'post_stop_collision_ordering')['passed'] is True
    assert result['deviations'] == []
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])


def test_no_stop_expected_case_that_stops_is_a_deviation(tmp_path):
    fixture = build_fixture(
        tmp_path, scenario_class='NO_STOP_EXPECTED',
        business_outcome='SUCCESS', acceptable=('SUCCESS',),
        must_conditions=(), unsupported_allowed=False)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'must_conditions')['passed'] is False
    assert any(item['kind'] == 'unexpected_stop'
               for item in result['deviations'])


def test_expected_status_must_be_pre_run_not_conclusion(tmp_path):
    fixture = build_fixture(tmp_path, expected_status='CONCLUSION')
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'expected_config_coverage')['passed'] is False


def test_repeat_count_shortfall_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path, repeats=2)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('expected case' in item for item in result['missing_fields'])


# ---------------------------------------------------------------------------
# contact-sensing validity (no NO_CONTACT conclusion from a broken sensor)
# ---------------------------------------------------------------------------

def test_contact_sensor_invalid_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path, contact_sensor_valid=False)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('contact_sensor' in item for item in result['missing_fields'])
    assert _check(result, 'contact_sensor_evidence')['passed'] is not True


def test_contact_sensor_missing_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path, contact_sensor_present=False)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('contact_sensor' in item for item in result['missing_fields'])


def test_zero_contact_force_with_pushed_robot_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path, contact_sensor_valid=False)

    def mutate(rows):
        position = [0.0, 0.0, 0.5]
        for row in rows:
            if row.get('phase') != 'RUN':
                continue
            row['speed_mps'] = 0.0
            row['velocity_world_mps'] = [0.0, 0.0, 0.0]
            position = [position[0] + 0.1, position[1], position[2]]
            row['position_world_m'] = list(position)

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('NO_CONTACT' in item or 'displacement' in item
               for item in result['missing_fields'])


# ---------------------------------------------------------------------------
# special recheck segments: pre-declared paths / (c) criteria
# ---------------------------------------------------------------------------

def _mapping_mutator(rows, episode, plan):
    row = _find_row(rows, 5)
    row['v2_reject_reason'] = 'REJECT_STALE_OBSERVATION'
    row['observation_valid'] = False
    row['observation_reason'] = 'CLOCK_MAPPING_UNUSABLE'
    row['clock']['mapping_usable'] = False
    row['clock']['mapping_reason'] = 'CLOCK_MAPPING_UNUSABLE'
    row['clock']['mapping_host_ns'] = None
    row['clock']['mapping_error_ns'] = None
    row['clock']['age_point_s'] = None
    row['clock']['age_bound_s'] = None
    row['observation_age_s'] = None
    del row['clearance']
    episode['reason'] = 'OBSERVATION_STALE'
    for candidate in rows:
        if candidate.get('phase') == 'RUN':
            candidate['reason'] = 'OBSERVATION_STALE'
            candidate['supervisor_state'] = 'ABORT'
            candidate['supervisor_action'] = 'ABORT'


def test_clock_mapping_recheck_declared_path_hit(tmp_path):
    defaults = {
        'acceptable_paths': [
            {'admission_reject_reason': 'REJECT_STALE_OBSERVATION',
             'observation_reason': 'CLOCK_MAPPING_UNUSABLE',
             'supervisor_reason': 'OBSERVATION_STALE'},
        ],
        'must_hit_declared_path': True,
    }
    fixture = build_fixture(
        tmp_path, case_id='special_stop_north', scenario_class='B',
        role='special', segment_id='latency_clock_mapping_recheck',
        expected_segments={'latency_clock_mapping_recheck':
                           {'defaults': defaults}},
        modify=_mapping_mutator)
    result = run_verify(fixture)
    assert _check(result, 'special_clock_mapping_paths')['passed'] is True
    assert _check(result, 'special_clock_mapping_paths')['passed'] is not None


def test_clock_mapping_undeclared_path_fails(tmp_path):
    defaults = {
        'acceptable_paths': [
            {'observation_reason': 'SOME_OTHER_REASON'},
        ],
        'must_hit_declared_path': True,
    }
    fixture = build_fixture(
        tmp_path, case_id='special_stop_north', scenario_class='B',
        role='special', segment_id='latency_clock_mapping_recheck',
        expected_segments={'latency_clock_mapping_recheck':
                           {'defaults': defaults}},
        modify=_mapping_mutator)
    result = run_verify(fixture)
    assert _check(result, 'special_clock_mapping_paths')['passed'] is False
    assert result['status'] == 'FAIL'


def _ttl_over_mutator(rows, episode, plan):
    for index, row in enumerate(rows):
        if row.get('phase') != 'RUN':
            continue
        transport = row['transport']
        host = row['clock']['host_now_ns']
        if 5 <= index <= 9:
            transport['status'] = 'APPLIED'
            transport['reason'] = 'ACCEPT'
            transport['executed'] = True
        if index == 10:
            issued = host - 160_000_000
            row['transport'] = {
                'status': 'REJECTED', 'action_id': 'ACT-EXPIRED',
                'executed_action_id': '', 'issued_at_ns': issued,
                'expires_at_ns': issued + 150_000_000,
                'scheduled_arrival_ns': host, 'arrival_ns': host,
                'dispatch_delay_s': 0.16, 'arrival_age_s': 0.16,
                'reason': 'ACTION_EXPIRED', 'executed': False,
                'rejections_this_step': []}
            row['applied'] = _zero_applied()
            row['v2_admission'] = ''
        if index > 10:
            row['transport'] = _none_transport()
            row['transport']['reason'] = 'ACTION_EXPIRED'
            row['applied'] = _zero_applied()
            row['v2_admission'] = ''
            row['speed_mps'] = 0.0
            row['velocity_world_mps'] = [0.0, 0.0, 0.0]
            row['position_world_m'] = [0.2, 0.0, 0.5]


def test_ttl_over_recheck_criteria_c_pass(tmp_path):
    defaults = {'criteria_id': '(c)',
                'acceptable_outcomes': ['ABORT', 'TIMEOUT']}
    fixture = build_fixture(
        tmp_path, case_id='special_stop_north', scenario_class='B',
        role='special', segment_id='latency_ttl_over_recheck',
        expected_segments={'latency_ttl_over_recheck':
                           {'defaults': defaults}},
        modify=_ttl_over_mutator)
    result = run_verify(fixture)
    assert _check(result, 'special_ttl_over_criteria')['passed'] is True, (
        result['failures'])


def test_ttl_over_recheck_missing_expiry_to_none_fails(tmp_path):
    defaults = {'criteria_id': '(c)',
                'acceptable_outcomes': ['ABORT', 'TIMEOUT']}

    def mutate(rows, episode, plan):
        _ttl_over_mutator(rows, episode, plan)
        for row in rows:
            if row.get('phase') != 'RUN':
                continue
            transport = row.get('transport') or {}
            if transport.get('status') == 'NONE':
                transport['reason'] = 'REJECT_NO_CACHED_ACTION'

    fixture = build_fixture(
        tmp_path, case_id='special_stop_north', scenario_class='B',
        role='special', segment_id='latency_ttl_over_recheck',
        expected_segments={'latency_ttl_over_recheck':
                           {'defaults': defaults}},
        modify=mutate)
    result = run_verify(fixture)
    assert _check(result, 'special_ttl_over_criteria')['passed'] is False
    assert result['status'] == 'FAIL'


def test_regression_segment_does_not_require_expected_entry(tmp_path):
    fixture = build_fixture(
        tmp_path, case_id='dynamic_A_south_0', business_outcome='SUCCESS',
        acceptable=('SUCCESS',), role='regression',
        segment_id='regression_dynamic', must_conditions=())
    result = run_verify(fixture)
    assert _check(result, 'expected_config_coverage')['passed'] is True


class _StubEvidence:
    def __init__(self, segment_id, episodes):
        self.segment_id = segment_id
        self.episodes = episodes


def test_boundary_denominator_uses_frozen_case_ids():
    analyses = {
        'boundary_default': {
            'evidence': _StubEvidence('boundary_default', [
                {'case_id': 'boundary_A_r0'}, {'case_id': 'boundary_A_r1'}]),
            'plan': {'role': 'boundary',
                     'case_ids': ['boundary_A_r0', 'boundary_A_r1']}},
        'boundary_fast': {
            'evidence': _StubEvidence('boundary_fast', [
                {'case_id': 'boundary_D_r0'}]),
            'plan': {'role': 'boundary', 'case_ids': ['boundary_D_r0']}},
    }
    expected = MODULE.ExpectedIndex()
    expected.add_config({
        'schema_version': MODULE.BOUNDARY_EXPECTED_SCHEMA,
        'cases': {
            'boundary_A_r0': {'repeats': 1},
            'boundary_A_r1': {'repeats': 1},
            'boundary_D_r0': {'repeats': 1}}})
    verifier = MODULE.Verifier()
    MODULE._check_boundary_denominator(analyses, expected, verifier)
    assert verifier.checks['boundary_episode_coverage']['passed'] is True
    assert not verifier.missing


def test_expected_boundary_case_outside_freeze_is_flagged():
    analyses = {
        'boundary_default': {
            'evidence': _StubEvidence('boundary_default',
                                      [{'case_id': 'boundary_A_r0'}]),
            'plan': {'role': 'boundary', 'case_ids': ['boundary_A_r0']}},
    }
    expected = MODULE.ExpectedIndex()
    expected.add_config({
        'schema_version': MODULE.BOUNDARY_EXPECTED_SCHEMA,
        'cases': {
            'boundary_A_r0': {'repeats': 1},
            'boundary_ghost_r0': {'repeats': 1}}})
    verifier = MODULE.Verifier()
    MODULE._check_boundary_denominator(analyses, expected, verifier)
    assert verifier.checks['boundary_episode_coverage']['passed'] is False


def test_out_of_bounds_physical_outcome_is_not_contact_aliased(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['physical_outcome'] = 'OUT_OF_BOUNDS'

    _rewrite_episodes(fixture, mutate)
    result = run_verify(fixture)
    # No contact evidence is misread as collision: OUT_OF_BOUNDS is recorded as
    # a positional physical result and the contact-only recomputation is not
    # used to overwrite it.
    assert _check(result, 'business_physical_outcome')['passed'] is not False
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])


def test_recorded_contact_without_evidence_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['physical_outcome'] = 'CONTACT_INFERRED'

    _rewrite_episodes(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'business_physical_outcome')['passed'] is False


def test_inference_mode_recorded_in_json(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])
    assert result['contact_evidence_mode'] == 'kinematic_inference'
    assert result['contact_evidence_limitation']
    recomputed = result['recomputed']['contact_evidence']
    assert recomputed['mode'] == 'sphere_overlap_inference'
    assert recomputed['force_sensor_available'] is False


def test_contact_evidence_overlap_is_recomputed(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        evidence = _find_row(rows, 7)['contact_evidence']
        evidence['sphere_overlap_m'] += 0.01

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_sensor_evidence')['passed'] is False


def test_inferred_contact_must_follow_the_overlap_threshold(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        evidence = _find_row(rows, 6)['contact_evidence']
        evidence['sphere_overlap_m'] = 0.01
        evidence['inferred_contact'] = True

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_sensor_evidence')['passed'] is False


def test_missing_contact_evidence_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(rows):
        del _find_row(rows, 5)['contact_evidence']

    _rewrite_steps(fixture, mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('contact_evidence' in item for item in result['missing_fields'])


def test_post_stop_collision_without_any_contact_evidence_fails(tmp_path):
    fixture = build_fixture(
        tmp_path, scenario_class='POST_STOP_COLLISION',
        business_outcome='ABORT', acceptable=('ABORT',),
        must_conditions=(), unsupported_allowed=False)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'post_stop_collision_ordering')['passed'] is False
    assert any(item['kind'] == 'post_stop_collision_missing_contact'
               for item in result['deviations'])


# ---------------------------------------------------------------------------
# CLI / output
# ---------------------------------------------------------------------------

def test_main_writes_output_json(tmp_path):
    fixture = build_fixture(tmp_path)
    output = tmp_path / 'reports' / 'verify.json'
    exit_code = MODULE.main([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--brake-model', str(fixture['brake_model']),
        '--repo-root', str(fixture['tmp']),
        '--run', '%s=%s' % (fixture['plan']['segment_id'], fixture['run_dir']),
        '--output', str(output)])
    assert exit_code == 0
    payload = _read_json(output)
    assert payload['status'] == 'PASS'
    assert set(payload) >= {'status', 'checks', 'failures', 'deviations',
                            'unsupported', 'performance', 'recomputed',
                            'freeze'}


def test_cli_rejects_malformed_run_spec(tmp_path):
    fixture = build_fixture(tmp_path)
    parser = MODULE.build_parser()
    args = parser.parse_args([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--brake-model', str(fixture['brake_model']),
        '--repo-root', str(fixture['tmp']),
        '--run', 'not-a-segment-spec'])
    with pytest.raises(SystemExit):
        MODULE.run_verification(args, parser)
