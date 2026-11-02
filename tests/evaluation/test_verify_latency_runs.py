"""Tests for scripts/verify_latency_runs.py using synthetic raw-record fixtures.

The fixtures mimic the record schema fixed by the plan (section 3), including the
post-abort rows and same-step rejection lists produced by the runner.  Recorded
``metrics`` are generated with the verifier's own recompute helpers for the
positive fixtures (so the positive case is self-consistent) and then tampered in
the negative tests to prove that each check branch actually fires.
"""
import hashlib
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'verify_latency_runs.py'


def _load_module():
    spec = importlib.util.spec_from_file_location('verify_latency_runs_ut',
                                                  SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()

DT = 0.05
BODY_HALF = [0.25, 0.20, 0.10]
CLOCK_PLAN = {'camera_clock_id': 'camera_sim', 'offset_ms': 20.0,
              'drift_ppm': 200.0, 'uncertainty_ms': 5.0}
OFFSET_NS = 20_000_000
UNC_NS = 5_000_000
DRIFT_PPM = 200.0
CODE_COMMIT = 'a' * 40
FROZEN_AT = '2026-11-02T00:00:00+00:00'
STARTED_AT = '2026-11-02T00:10:00+00:00'
MAP_HASHES = {
    'map_asset_id': 'fixture-map',
    'terrain_sha256': 't' * 64,
    'preview_sha256': 'p' * 64,
    'map_config_sha256': 'm' * 64,
}
OBSTACLE = {
    'obstacle_id': 'obs_x', 'size_m': [0.4, 0.4, 0.6], 'kind': 'linear',
    'start_position_world_m': [2.0, 0.0, 0.5],
    'velocity_world_mps': [0.0, 0.0, 0.0],
    'start_time_s': 0, 'end_time_s': 1000,
    'observation_delay_s': 0.05,
}
CASE_OBS_NS = 50_000_000


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


def _refresh_manifest(run_dir):
    manifest_path = Path(run_dir) / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['outputs_sha256'] = {
        name: _sha(Path(run_dir) / name)
        for name in ('episodes.jsonl', 'steps.jsonl')}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n',
                             encoding='utf-8')


def _plan(role='main', config_id='A', segment_id='', case_ids=('case_x',),
          stop=1.1, obs=0.15, action=0.1, ttl_ms=150.0, post_abort=0.0,
          sync_fail_step=-1, mapping_fail_step=-1, stall_step=-1,
          stall_delay=0.15):
    return {
        'role': role, 'segment_id': segment_id, 'config_id': config_id,
        'obs_delay_s': round(obs, 6), 'action_delay_s': round(action, 6),
        'ttl_ms': round(ttl_ms, 6), 'max_age_ms': 150,
        'allowed_observation_age_ms': 300, 'stop_distance_m': round(stop, 6),
        'post_abort_observe_s': round(post_abort, 6),
        'sync_fail_step': sync_fail_step,
        'obs_mapping_fail_step': mapping_fail_step,
        'transport_stall_step': stall_step,
        'transport_stall_delay_s': round(stall_delay, 6),
        'execution_path': 'v2', 'methods': ['supervisor'],
        'case_ids': list(case_ids),
    }


def _clock(host_ns, usable=True, sync_gen=0, obs_ns=None,
           case_obs_ns=CASE_OBS_NS, zero=False):
    if obs_ns is None:
        obs_ns = 150_000_000
    if zero:
        offset_ns, uncertainty_ns, drift = 0, 0, 0.0
    else:
        offset_ns, uncertainty_ns, drift = OFFSET_NS, UNC_NS, DRIFT_PPM
    capture_host = max(0, host_ns - obs_ns - case_obs_ns)
    capture_clock = round(capture_host + offset_ns
                          + capture_host * drift / 1e6)
    if not usable:
        return {
            'host_now_ns': host_ns, 'capture_host_ns': capture_host,
            'capture_clock_ns': capture_clock, 'camera_clock_id': 'camera_sim',
            'mapping_host_ns': None, 'mapping_error_ns': None,
            'mapping_sync_generation': sync_gen, 'mapping_usable': False,
            'mapping_reason': 'CLOCK_MAPPING_UNUSABLE',
            'age_point_s': None, 'age_bound_s': None}
    mapped = round((capture_clock - offset_ns) / (1.0 + drift / 1e6))
    error = (abs(offset_ns) + uncertainty_ns
             + math.ceil(abs(drift) * 1e-6 * abs(host_ns)))
    point = max(0.0, (host_ns - mapped) / 1e9)
    return {
        'host_now_ns': host_ns, 'capture_host_ns': capture_host,
        'capture_clock_ns': capture_clock, 'camera_clock_id': 'camera_sim',
        'mapping_host_ns': mapped, 'mapping_error_ns': error,
        'mapping_sync_generation': sync_gen, 'mapping_usable': True,
        'mapping_reason': 'ACCEPT', 'age_point_s': point,
        'age_bound_s': point + error / 1e9}


def _v2(dispatch_id, host_ns, ttl_ns, sync_gen, admission='ADMITTED',
        reject_reason='', episode_id='fixture', step=0):
    fields = {
        'v2_admission': admission, 'v2_action_id': dispatch_id,
        'v2_reject_reason': reject_reason,
        'v2_executed': admission == 'ADMITTED',
        'v2_fault_type': None,
    }
    if dispatch_id:
        fields.update({
            'v2_issued_at_ns': host_ns,
            'v2_expires_at_ns': host_ns + ttl_ns,
            'v2_context': {
                'system_boot_id': 1, 'mission_epoch': 0,
                'localization_epoch': 0, 'control_epoch': 0,
                'clock_id': 'host_monotonic', 'px4_boot_id': 100,
                'sync_generation': sync_gen},
            'v2_context_owner': 'STUDENT',
            'v2_pending_owner': None,
            'v2_action_source': 'STUDENT',
            'v2_observation_id': 'state-%s-%d' % (episode_id, step),
        })
    return fields


def _speed_profile(index, brake_step):
    if index < brake_step:
        return 1.0
    return max(0.0, 1.0 - (index - brake_step + 1) / 17.0)


def _transport_record(status, ticket=None, reason='ACCEPT', executed=True,
                      executed_id=None, replayed=None, arrival_age=None,
                      dispatch_delay=None):
    if status == 'NONE':
        return {
            'status': 'NONE', 'action_id': '', 'executed_action_id': '',
            'issued_at_ns': 0, 'expires_at_ns': 0,
            'scheduled_arrival_ns': 0, 'arrival_ns': 0,
            'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
            'reason': reason, 'executed': False, 'rejections_this_step': []}
    return {
        'status': status, 'action_id': ticket['id'],
        'executed_action_id': executed_id if executed_id is not None
        else ticket['id'],
        'issued_at_ns': ticket['issued'], 'expires_at_ns': ticket['expires'],
        'scheduled_arrival_ns': ticket.get('scheduled'),
        'arrival_ns': ticket.get('arrival'),
        'dispatch_delay_s': dispatch_delay if dispatch_delay is not None else
        (ticket.get('scheduled', ticket['issued']) - ticket['issued']) / 1e9,
        'arrival_age_s': arrival_age if arrival_age is not None else
        (ticket.get('arrival', ticket['issued']) - ticket['issued']) / 1e9,
        'reason': reason, 'executed': executed, 'rejections_this_step': []}


def _applied(ticket, host_ns, held=False):
    if ticket is None:
        return {
            'vx_forward_mps': 0.0, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
            'yaw_rate_ccw_world_radps': 0.0, 'action_id': '',
            'issued_at_ns': 0, 'expires_at_ns': 0, 'age_s': 0.0,
            'is_held': False}
    return {
        'vx_forward_mps': ticket['command'], 'vy_left_mps': 0.0,
        'vz_up_mps': 0.0, 'yaw_rate_ccw_world_radps': 0.0,
        'action_id': ticket['id'], 'issued_at_ns': ticket['issued'],
        'expires_at_ns': ticket['expires'],
        'age_s': (host_ns - ticket['issued']) / 1e9, 'is_held': held}


def _base_step_row(episode_id, case_id, plan, step, time_s, host_ns, speed,
                   position, usable, sync_gen, outcome, reason,
                   supervisor_state, supervisor_action, episode_length_buf,
                   phase='RUN', v2_fields=None, transport=None, applied=None,
                   obstacle=OBSTACLE, clock_zero=False):
    if clock_zero:
        clock = _clock(
            host_ns, usable=usable, sync_gen=sync_gen, zero=True,
            obs_ns=int(round(float(plan.get('obs_delay_s') or 0.0) * 1e9)),
            case_obs_ns=CASE_OBS_NS if obstacle else 0)
    else:
        clock = _clock(host_ns, usable=usable, sync_gen=sync_gen)
    row = {
        'episode_id': episode_id, 'case_id': case_id, 'method': 'supervisor',
        'step': step, 'time_s': time_s, 'phase': phase,
        'position_world_m': list(position),
        'velocity_world_mps': [speed, 0.0, 0.0], 'speed_mps': speed,
        'command': [speed, 0.0, 0.0, 0.0],
        'clock': clock,
        'observation_age_s': None if not usable else clock['age_bound_s'],
        'observation_valid': usable,
        'observation_reason': ('ACCEPT' if usable
                               else 'CLOCK_MAPPING_UNUSABLE'),
        'transport': transport if transport is not None
        else _transport_record('NONE', reason='REJECT_NO_CACHED_ACTION'),
        'applied': applied if applied is not None else _applied(None, host_ns),
        'obstacle_position_world_m': list(obstacle['start_position_world_m'])
        if obstacle else None,
        'obstacle_velocity_world_mps': list(obstacle['velocity_world_mps'])
        if obstacle else None,
        'supervisor_state': supervisor_state,
        'supervisor_action': supervisor_action,
        'supervisor_wait_s': 0.0, 'route_active_s': time_s,
        'contact_force_n': 0.0, 'contact_prim': '',
        'outcome': outcome, 'reason': reason,
        'env_terminated': False, 'env_truncated': False,
        'episode_length_buf': episode_length_buf,
        'boundary_count_ok': True, 'execution_path': 'v2',
    }
    row.update(v2_fields if v2_fields is not None
               else _v2('', host_ns, 0, sync_gen, admission='',
                        episode_id=episode_id, step=step))
    return row


def _build_episode(episode_id, case_id, plan, *, outcome='SUCCESS',
                   reason='ROUTE_COMPLETE', n_physical=40, brake_step=12,
                   abort=False, abort_reason=None, mapping_fail_step=-1,
                   sync_fail_step=-1, post_abort=0, injections=None,
                   transport_mode='delay', obstacle=OBSTACLE):
    ttl_ns = int(round(plan['ttl_ms'] * 1e6))
    delay_ns = int(round(plan['action_delay_s'] * 1e9))
    obs_ns = int(round(plan['obs_delay_s'] * 1e9))
    clock_zero = transport_mode == 'direct'
    stall_step = plan.get('transport_stall_step')
    stall_delay_ns = int(round(float(plan.get('transport_stall_delay_s') or 0.0)
                              * 1e9))
    stall_active = isinstance(stall_step, int) and stall_step >= 0
    pending = []
    active = None
    sync_gen = 0
    rows = []
    position = [0.0, 0.0, 0.5]
    last_time = 0.0
    for index in range(n_physical):
        time_s = round((index + 1) * DT, 6)
        host = round(time_s * 1e9)
        last_time = time_s
        usable = not (mapping_fail_step >= 0 and index >= mapping_fail_step)
        speed = _speed_profile(index, brake_step)
        state = 'FOLLOW' if index < brake_step else (
            'BRAKE' if speed > 0.12 else 'HOLD')
        if mapping_fail_step >= 0 and index >= mapping_fail_step:
            state = 'DEGRADED'
        action = 'STOP' if index >= brake_step else 'ROUTE'
        dispatch_id = '%s-%d' % (episode_id, index)
        ticket_delay = (stall_delay_ns
                        if stall_active and index >= stall_step else delay_ns)
        ticket = {'id': dispatch_id, 'issued': host,
                  'expires': host + ttl_ns, 'scheduled': host + ticket_delay,
                  'arrival': None, 'sync': sync_gen, 'command': speed}
        transport = None
        applied = None
        if transport_mode == 'direct':
            ticket['scheduled'] = host
            ticket['arrival'] = host
            active = ticket
            transport = {
                'status': 'DIRECT', 'action_id': ticket['id'],
                'executed_action_id': ticket['id'],
                'issued_at_ns': ticket['issued'],
                'expires_at_ns': ticket['expires'],
                'scheduled_arrival_ns': host, 'arrival_ns': host,
                'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
                'reason': 'ACCEPT', 'executed': True,
                'rejections_this_step': []}
            applied = _applied(active, host, held=False)
        else:
            pending.append(ticket)
            if sync_fail_step >= 0 and index == sync_fail_step:
                sync_gen += 1
            due = [item for item in pending if item['scheduled'] <= host]
            for item in due:
                pending.remove(item)
            accepted = None
            rejected_at_step = []
            for item in due:
                age = (host - item['issued']) / 1e9
                reject = None
                if item['sync'] != sync_gen:
                    reject = 'REJECT_SYNC_OR_PX4_BOOT'
                elif age + 1e-9 >= ttl_ns / 1e9:
                    reject = 'ACTION_EXPIRED'
                if reject:
                    rejected_at_step.append({
                        'action_id': item['id'], 'reason': reject,
                        'arrival_s': host / 1e9, 'arrival_age_s': age,
                        'ticket': item})
                else:
                    item['arrival'] = host
                    accepted = item
                    active = item
            if accepted is not None:
                transport = _transport_record('APPLIED', accepted)
                transport['rejections_this_step'] = [{
                    'action_id': item['action_id'], 'reason': item['reason'],
                    'arrival_age_s': item['arrival_age_s']}
                    for item in rejected_at_step]
                applied = _applied(active, host, held=False)
            elif rejected_at_step:
                rejected = rejected_at_step[-1]
                ticket = rejected['ticket']
                if active is not None \
                        and host >= active['expires'] - 1e-9:
                    active = None
                transport = {
                    'status': 'REJECTED',
                    'action_id': '', 'executed_action_id': '',
                    'issued_at_ns': ticket['issued'],
                    'expires_at_ns': ticket['expires'],
                    'scheduled_arrival_ns': ticket['scheduled'],
                    'arrival_ns': host,
                    'dispatch_delay_s': (ticket['scheduled']
                                         - ticket['issued']) / 1e9,
                    'arrival_age_s': (host - ticket['issued']) / 1e9,
                    'reason': rejected['reason'], 'executed': False,
                    'rejections_this_step': [{
                        'action_id': item['action_id'],
                        'reason': item['reason'],
                        'arrival_age_s': item['arrival_age_s']}
                        for item in rejected_at_step],
                    'applied': None}
                if active is not None:
                    applied = _applied(active, host, held=True)
                else:
                    applied = _applied(None, host)
            elif active is not None and host < active['expires']:
                transport = _transport_record('HOLDING', active)
                applied = _applied(active, host, held=True)
            else:
                expired_active = (active is not None
                                  and host >= active['expires'] - 1e-9)
                active = None
                transport = _transport_record(
                    'NONE', reason='ACTION_EXPIRED' if expired_active
                    else 'REJECT_NO_CACHED_ACTION')
                applied = _applied(None, host)
        row = _base_step_row(
            episode_id, case_id, plan, index, time_s, host, speed, position,
            usable, sync_gen, 'RUNNING', 'RUNNING', state, action,
            index + 1, v2_fields=_v2(dispatch_id, host, ttl_ns, sync_gen,
                                     episode_id=episode_id, step=index),
            transport=transport, applied=applied, obstacle=obstacle,
            clock_zero=clock_zero)
        if mapping_fail_step >= 0 and index == mapping_fail_step:
            row.update(_v2('', host, ttl_ns, sync_gen, admission='REJECTED',
                           reject_reason='REJECT_STALE_OBSERVATION',
                           episode_id=episode_id, step=index))
        rows.append(row)
        position = [position[0] + speed * DT, position[1], position[2]]
    if abort:
        decision_time = round(last_time + DT, 6)
        host = round(decision_time * 1e9)
        usable = not (mapping_fail_step >= 0)
        rows.append(_base_step_row(
            episode_id, case_id, plan, n_physical, decision_time, host,
            rows[-1]['speed_mps'], position, usable, sync_gen, outcome,
            abort_reason or reason, 'ABORT', 'ABORT', 0,
            v2_fields=_v2('', host, ttl_ns, sync_gen, admission='',
                          episode_id=episode_id, step=n_physical),
            obstacle=obstacle, clock_zero=clock_zero))
        for jump in range(1, post_abort + 1):
            time_s = round(decision_time + jump * DT, 6)
            host = round(time_s * 1e9)
            speed = max(0.0, rows[-2]['speed_mps'] * (0.9 ** jump))
            usable = not (mapping_fail_step >= 0)
            if active is not None and host < active['expires']:
                transport = _transport_record('APPLIED', active)
                applied = _applied(active, host, held=False)
            else:
                active = None
                ended = jump == 1 and active is None
                transport = _transport_record(
                    'NONE', reason='ACTION_EXPIRED' if jump == 1
                    else 'REJECT_NO_CACHED_ACTION')
                applied = _applied(None, host)
            rows.append(_base_step_row(
                episode_id, case_id, plan, n_physical + jump - 1, time_s,
                host, speed, position, usable, sync_gen, outcome,
                abort_reason or reason, 'ABORT', 'ABORT',
                n_physical + jump, phase='POST_ABORT',
                v2_fields=_v2('', host, ttl_ns, sync_gen, admission='',
                              episode_id=episode_id,
                              step=n_physical + jump - 1),
                transport=transport, applied=applied, obstacle=obstacle,
                clock_zero=clock_zero))
    else:
        rows[-1]['outcome'] = outcome
        rows[-1]['reason'] = reason
        for jump in range(1, post_abort + 1):
            time_s = round(last_time + jump * DT, 6)
            host = round(time_s * 1e9)
            usable = not (mapping_fail_step >= 0)
            rows.append(_base_step_row(
                episode_id, case_id, plan, n_physical + jump - 1, time_s,
                host, 0.0, position, usable, sync_gen, outcome, reason,
                'ABORT', 'ABORT', n_physical + jump, phase='POST_ABORT',
                v2_fields=_v2('', host, ttl_ns, sync_gen, admission='',
                              episode_id=episode_id,
                              step=n_physical + jump - 1),
                transport=_transport_record('NONE',
                                            reason='REJECT_NO_CACHED_ACTION'),
                applied=_applied(None, host), obstacle=obstacle,
                clock_zero=clock_zero))
    for row_index, extra in (injections or {}).items():
        rows[row_index]['transport']['rejections_this_step'].extend(extra)
    phase_summary = Counter(row.get('phase') for row in rows)
    episode = {
        'episode_id': episode_id, 'case_id': case_id, 'method': 'supervisor',
        'outcome': outcome, 'reason': abort_reason or reason,
        'steps': n_physical, 'duration_s': round(n_physical * DT, 6),
        'config_id': plan['config_id'], 'segment_id': plan['segment_id'],
        'pair_key': case_id,
        'phase_summary': {str(key): int(value)
                          for key, value in phase_summary.items()},
        'obstacle': dict(obstacle) if obstacle else None,
    }
    return episode, rows


def _record_metrics(plan, episode, rows):
    evidence = MODULE.RunEvidence(label='fixture', role='main',
                                  run_dir=Path('.'))
    verifier = MODULE.Verifier()
    clock_plan = plan.get('_clock_plan') or CLOCK_PLAN
    case_obs_ns = (CASE_OBS_NS if episode.get('obstacle') else 0)
    ctx = {
        'plan': plan, 'clock_plan': clock_plan,
        'ttl_ns': int(round(plan['ttl_ms'] * 1e6)),
        'action_delay_ns': int(round(plan['action_delay_s'] * 1e9)),
        'obs_delay_ns': int(round(plan['obs_delay_s'] * 1e9)),
        'body_half_extents': BODY_HALF,
        'case_obs_delay_ns': case_obs_ns, 'dt': DT,
    }
    structure = MODULE._check_episode_structure(evidence, episode, rows, ctx,
                                                verifier)
    analysis = {'accepted': [], 'rejected': [], 'mapping_unusable': [],
                'ttl_deltas': [], 'arrival_ages': [],
                'observation_bounds': [], 'status_counts': Counter(),
                'rejection_reasons': Counter()}
    transport = MODULE._check_episode_transport(evidence, episode, rows, ctx,
                                                verifier, analysis)
    metrics = MODULE._recompute_episode_metrics(evidence, episode, rows, ctx,
                                                verifier, analysis, structure)
    metrics['executed_action_count'] = transport['executed_action_count']
    metrics['arrival_rejection_count'] = transport['arrival_rejection_count']
    metrics['arrival_reject_reasons'] = transport['arrival_reject_reasons']
    assert verifier.failures == [], verifier.failures
    episode['metrics'] = metrics
    return metrics


def _manifest(plan, *, run_dir, freeze_path, freeze_sha, cases_file,
              cases_sha, episode_ids, started_at=STARTED_AT,
              gui_evidence=True):
    return {
        'schema_version': 'boom_birds.manifest.v1',
        'evaluation_version': 'boom_birds.latency_eval.v1',
        'code_commit': CODE_COMMIT, 'working_tree': 'synthetic fixture',
        'gui_mode': True, 'renderer': 'DirectX (--/app/vulkan=false)',
        'gpu_driver': 'NOT RECORDED', **MAP_HASHES,
        'cases_file': cases_file, 'cases_sha256': cases_sha,
        'methods': ['supervisor'], 'started_at': started_at,
        'latency_plan': plan,
        'clock_plan': dict(plan.get('_clock_plan') or CLOCK_PLAN),
        'freeze': {'path': str(freeze_path) if freeze_path else '',
                   'sha256': freeze_sha or '', 'schema_version':
                   'boom_birds.latency_freeze.v2' if freeze_path else '',
                   'frozen_at': FROZEN_AT if freeze_path else '',
                   'code_commit': CODE_COMMIT if freeze_path else ''},
        'body_envelope': {'half_extents_m': BODY_HALF,
                          'source': 'measured_usd_aabb_at_runtime',
                          'measured_prim': '/World/envs/env_0/Robot'},
        'episode_ids': episode_ids,
        'gui_evidence': ({'gui_mode': True, 'renderer':
                          'DirectX (--/app/vulkan=false)', 'headless': False,
                          'window_required': True}
                         if gui_evidence else None),
        'command': 'scripts/run_dynamic_eval.py --synthetic-fixture',
    }


def _write_run(root, label, plan, episodes_rows, *, freeze_path, freeze_sha,
               cases_file, cases_sha):
    run_dir = Path(root) / 'runs' / label
    run_dir.mkdir(parents=True, exist_ok=True)
    episodes = []
    steps = []
    for episode, rows in episodes_rows:
        episodes.append(episode)
        steps.extend(rows)
    for episode, rows in episodes_rows:
        _record_metrics(plan, episode, rows)
    _write_jsonl(run_dir / 'episodes.jsonl', episodes)
    _write_jsonl(run_dir / 'steps.jsonl', steps)
    manifest = _manifest(
        plan, run_dir=run_dir, freeze_path=freeze_path, freeze_sha=freeze_sha,
        cases_file=cases_file, cases_sha=cases_sha,
        episode_ids=[episode['episode_id'] for episode in episodes])
    manifest['outputs_sha256'] = {
        name: _sha(run_dir / name)
        for name in ('episodes.jsonl', 'steps.jsonl')}
    _write_json(run_dir / 'manifest.json', manifest)
    return run_dir


def _freeze_common(cases_file, cases_sha):
    return {
        'schema_version': 'boom_birds.latency_freeze.v2',
        'status': 'PRE_RUN_FROZEN', 'frozen_at': FROZEN_AT,
        'code_commit': CODE_COMMIT,
        'worktree_state': {'tracked_paths': ['src', 'scripts', 'tests',
                                             'configs'],
                           'status_text_sha256': 'b' * 64, 'clean': False},
        'evaluation_version': 'boom_birds.latency_eval.v1',
        **MAP_HASHES, 'cases_file': str(cases_file),
        'cases_sha256': cases_sha,
        'clock_plan': dict(CLOCK_PLAN),
        'body_envelope': {'source': 'measured_usd_aabb_at_runtime',
                          'half_extents_m': None, 'measured_prim': None},
        'evaluation': {
            'status': 'EXPECTED_NOT_CONCLUSION',
            'thresholds': {'stop_speed_max_mps': 0.08, 'stop_hold_s': 0.5,
                           'contact_force_threshold_n': 0.02},
        },
    }


def _expected_segment(segment_id, case_ids, outcome, reason=None,
                      extra=None):
    cases = {case_id: {'expected_outcome': outcome} for case_id in case_ids}
    payload = {'expected_outcome': outcome, 'case_ids': list(case_ids),
               'cases': cases}
    if reason:
        payload['expected_reason'] = reason
    payload.update(extra or {})
    return payload


def build_fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pair_cases = root / 'cases_pair.json'
    _write_json(pair_cases, {'cases': [{'case_id': 'case_x'},
                                       {'case_id': 'case_y'}]})
    special_cases = root / 'cases_special.json'
    _write_json(special_cases, {'cases': [{'case_id': 'special_case'}]})
    pair_cases_sha = _sha(pair_cases)
    special_cases_sha = _sha(special_cases)

    plan_a = _plan('main', 'A', '', ('case_x', 'case_y'), stop=1.1)
    plan_b = _plan('main', 'B', '', ('case_x', 'case_y'), stop=1.38)
    pair_freeze_path = root / 'latency_pair_freeze_v2.json'
    pair_freeze = _freeze_common(pair_cases, pair_cases_sha)
    pair_freeze.update({
        'artifact': 'main_pair',
        'case_ids': ['case_x', 'case_y'],
        'episodes_per_config': 2, 'total_episodes': 4,
        'latency_plan_defaults': {'obs_delay_s': 0.15, 'action_delay_s': 0.1,
                                  'ttl_ms': 150, 'max_age_ms': 150,
                                  'allowed_observation_age_ms': 300,
                                  'post_abort_observe_s': 0.0},
        'main_run_plans': {'A': plan_a, 'B': plan_b},
        'configs': {'A': {'stop_distance_m': 1.1},
                    'B': {'stop_distance_m': 1.38}},
    })
    pair_freeze['evaluation']['expected'] = {
        'main': {
            'A': {'case_x': {'expected_outcome': 'SUCCESS'},
                  'case_y': {'expected_outcome': 'SUCCESS'}},
            'B': {'case_x': {'expected_outcome': 'SUCCESS'},
                  'case_y': {'expected_outcome': 'SUCCESS'}},
        },
        'special': {},
    }
    _write_json(pair_freeze_path, pair_freeze)
    pair_freeze_sha = _sha(pair_freeze_path)

    ttl_near_plan = _plan('special', '', 'ttl_near', ('special_case',),
                          stop=1.1, ttl_ms=120.0)
    ttl_over_plan = _plan('special', '', 'ttl_over', ('special_case',),
                          stop=1.1, ttl_ms=150.0, post_abort=0.1,
                          stall_step=10, stall_delay=0.15)
    clock_sync_plan = _plan('special', '', 'clock_sync', ('special_case',),
                            stop=1.1, ttl_ms=150.0, post_abort=0.1,
                            sync_fail_step=10)
    clock_mapping_plan = _plan('special', '', 'clock_mapping',
                               ('special_case',), stop=1.1, ttl_ms=150.0,
                               post_abort=0.1, mapping_fail_step=10)
    regression_no_obstacle_plan = _plan('regression', '', 'regression_no_obstacle',
                                        ('reg_case',), stop=1.1, obs=0.0,
                                        action=0.0, ttl_ms=150.0)
    regression_dynamic_plan = _plan('regression', '', 'regression_dynamic',
                                    ('reg_case',), stop=1.1, obs=0.0,
                                    action=0.0, ttl_ms=150.0)
    zero_clock_plan = {'camera_clock_id': 'camera_sim', 'offset_ms': 0.0,
                       'drift_ppm': 0.0, 'uncertainty_ms': 0.0}
    regression_no_obstacle_plan['_clock_plan'] = dict(zero_clock_plan)
    regression_dynamic_plan['_clock_plan'] = dict(zero_clock_plan)

    segments = {
        'ttl_near': {
            'segment_id': 'ttl_near', 'cases_file': str(special_cases),
            'cases_sha256': special_cases_sha, 'run_plan': ttl_near_plan,
            'expected': _expected_segment(
                'ttl_near', ['special_case'], 'SUCCESS', 'ROUTE_COMPLETE',
                {'arrival_accept_age_s': 0.1, 'ttl_margin_s': 0.02}),
        },
        'ttl_over': {
            'segment_id': 'ttl_over', 'cases_file': str(special_cases),
            'cases_sha256': special_cases_sha, 'run_plan': ttl_over_plan,
            'expected': _expected_segment(
                'ttl_over', ['special_case'], 'ABORT', 'ACTION_EXPIRED',
                {'arrival_reject_reason': 'ACTION_EXPIRED',
                 'brake_command_executed': False,
                 'expected_outcome_alternatives':
                 ['TIMEOUT', 'COLLISION', 'ABORT']}),
        },
        'clock_sync': {
            'segment_id': 'clock_sync', 'cases_file': str(special_cases),
            'cases_sha256': special_cases_sha, 'run_plan': clock_sync_plan,
            'expected': _expected_segment(
                'clock_sync', ['special_case'], 'ABORT',
                'REJECT_SYNC_OR_PX4_BOOT',
                {'admission_reject_reason': 'REJECT_SYNC_OR_PX4_BOOT',
                 'inflight_arrival_reject_reason':
                 'REJECT_SYNC_OR_PX4_BOOT'}),
        },
        'clock_mapping': {
            'segment_id': 'clock_mapping', 'cases_file': str(special_cases),
            'cases_sha256': special_cases_sha,
            'run_plan': clock_mapping_plan,
            'expected': _expected_segment(
                'clock_mapping', ['special_case'], 'ABORT',
                'OBSERVATION_STALE',
                {'observation_reason': 'CLOCK_MAPPING_UNUSABLE',
                 'admission_reject_reason': 'REJECT_STALE_OBSERVATION'}),
        },
    }
    special_freeze_path = root / 'latency_special_freeze_v2.json'
    special_freeze = _freeze_common(special_cases, special_cases_sha)
    special_freeze.update({
        'artifact': 'special_segments',
        'case_ids': ['special_case'],
        'special_segments': segments,
        'latency_plan_defaults': {'obs_delay_s': 0.15, 'action_delay_s': 0.1,
                                  'ttl_ms': 150, 'max_age_ms': 150,
                                  'allowed_observation_age_ms': 300,
                                  'post_abort_observe_s': 0.0},
    })
    special_freeze['evaluation']['expected'] = {
        'main': {},
        'special': {segment_id: dict(entry['expected'])
                    for segment_id, entry in segments.items()},
    }
    _write_json(special_freeze_path, special_freeze)
    special_freeze_sha = _sha(special_freeze_path)

    expected_config = {
        'schema_version': 'boom_birds.latency_expected.v1',
        'evaluation_version': 'boom_birds.latency_eval.v1',
        'status': 'EXPECTED_NOT_CONCLUSION',
        'cases': {'case_x': {'expected_outcome': 'SUCCESS'},
                  'case_y': {'expected_outcome': 'SUCCESS'}},
        'segments': {segment_id: dict(entry['expected'])
                     for segment_id, entry in segments.items()},
    }
    expected_config['segments'].update({
        'regression_no_obstacle': {'reg_case': {'expected_outcome': 'SUCCESS'}},
        'regression_dynamic': {'reg_case': {'expected_outcome': 'SUCCESS'}},
    })
    expected_path = root / 'latency_expected_v1.json'
    _write_json(expected_path, expected_config)

    def pair_episodes(config_id):
        episodes = []
        for case_id in ('case_x', 'case_y'):
            episode, rows = _build_episode(
                '%s-%s-supervisor' % (case_id, config_id), case_id,
                plan_a if config_id == 'A' else plan_b)
            episodes.append((episode, rows))
        return episodes

    run_a = _write_run(root, 'main_A', plan_a, pair_episodes('A'),
                       freeze_path=pair_freeze_path,
                       freeze_sha=pair_freeze_sha, cases_file=str(pair_cases),
                       cases_sha=pair_cases_sha)
    run_b = _write_run(root, 'main_B', plan_b, pair_episodes('B'),
                       freeze_path=pair_freeze_path,
                       freeze_sha=pair_freeze_sha, cases_file=str(pair_cases),
                       cases_sha=pair_cases_sha)

    ttl_near_episode, ttl_near_rows = _build_episode(
        'special_case-supervisor', 'special_case', ttl_near_plan,
        n_physical=14, brake_step=12)
    ttl_over_episode, ttl_over_rows = _build_episode(
        'special_case-supervisor', 'special_case', ttl_over_plan,
        n_physical=30, brake_step=12, abort=False, post_abort=2,
        outcome='TIMEOUT', reason='WALL_TIMEOUT')
    clock_sync_episode, clock_sync_rows = _build_episode(
        'special_case-supervisor', 'special_case', clock_sync_plan,
        n_physical=13, brake_step=12, abort=True, post_abort=2,
        outcome='ABORT', abort_reason='REJECT_SYNC_OR_PX4_BOOT',
        sync_fail_step=10)
    mapping_episode, mapping_rows = _build_episode(
        'special_case-supervisor', 'special_case', clock_mapping_plan,
        n_physical=11, brake_step=12, abort=True, post_abort=2,
        outcome='ABORT', abort_reason='OBSERVATION_STALE',
        mapping_fail_step=10)
    regression_episode_no_obstacle, regression_rows_no_obstacle = \
        _build_episode('reg_case-supervisor', 'reg_case',
                       regression_no_obstacle_plan, n_physical=14,
                       transport_mode='direct', obstacle=None)
    regression_episode_dynamic, regression_rows_dynamic = _build_episode(
        'reg_case-supervisor', 'reg_case', regression_dynamic_plan,
        n_physical=14, transport_mode='direct')

    ttl_near_dir = _write_run(
        root, 'ttl_near', ttl_near_plan, [(ttl_near_episode, ttl_near_rows)],
        freeze_path=special_freeze_path, freeze_sha=special_freeze_sha,
        cases_file=str(special_cases), cases_sha=special_cases_sha)

    ttl_over_dir = _write_run(
        root, 'ttl_over', ttl_over_plan, [(ttl_over_episode, ttl_over_rows)],
        freeze_path=special_freeze_path, freeze_sha=special_freeze_sha,
        cases_file=str(special_cases), cases_sha=special_cases_sha)
    clock_sync_dir = _write_run(
        root, 'clock_sync', clock_sync_plan,
        [(clock_sync_episode, clock_sync_rows)],
        freeze_path=special_freeze_path, freeze_sha=special_freeze_sha,
        cases_file=str(special_cases), cases_sha=special_cases_sha)
    clock_mapping_dir = _write_run(
        root, 'clock_mapping', clock_mapping_plan,
        [(mapping_episode, mapping_rows)],
        freeze_path=special_freeze_path, freeze_sha=special_freeze_sha,
        cases_file=str(special_cases), cases_sha=special_cases_sha)
    regression_no_obstacle_dir = _write_run(
        root, 'regression_no_obstacle', regression_no_obstacle_plan,
        [(regression_episode_no_obstacle, regression_rows_no_obstacle)],
        freeze_path=None, freeze_sha=None, cases_file=str(pair_cases),
        cases_sha=pair_cases_sha)
    regression_dynamic_dir = _write_run(
        root, 'regression_dynamic', regression_dynamic_plan,
        [(regression_episode_dynamic, regression_rows_dynamic)],
        freeze_path=None, freeze_sha=None, cases_file=str(pair_cases),
        cases_sha=pair_cases_sha)
    return {
        'root': root,
        'pair_freeze': pair_freeze_path,
        'special_freeze': special_freeze_path,
        'expected_config': expected_path,
        'run_a': run_a, 'run_b': run_b,
        'ttl_near': ttl_near_dir, 'ttl_over': ttl_over_dir,
        'clock_sync': clock_sync_dir, 'clock_mapping': clock_mapping_dir,
        'regression_no_obstacle': regression_no_obstacle_dir,
        'regression_dynamic': regression_dynamic_dir,
        'pair_cases': pair_cases, 'special_cases': special_cases,
    }


def _verify(fixture, *, include_special=True, extra_args=None,
            include_run_b=True):
    args = ['--pair-freeze', str(fixture['pair_freeze']),
            '--run-a', str(fixture['run_a']),
            '--special-freeze', str(fixture['special_freeze']),
            '--expected-config', str(fixture['expected_config']),
            '--repo-root', str(fixture['root'])]
    if include_run_b:
        args += ['--run-b', str(fixture['run_b'])]
    if include_special:
        for segment_id in ('ttl_near', 'ttl_over', 'clock_sync',
                           'clock_mapping'):
            args += ['--special-run',
                     '%s=%s' % (segment_id, fixture[segment_id])]
        for segment_id in ('regression_no_obstacle', 'regression_dynamic'):
            args += ['--regression-run',
                     '%s=%s' % (segment_id, fixture[segment_id])]
    args += list(extra_args or [])
    parser = MODULE.build_parser()
    parsed = parser.parse_args(args)
    return MODULE.run_verification(parsed, parser)


def _failed_checks(result):
    return {name for name, check in result['checks'].items()
            if check['passed'] is False}


def _mutate_run(run_dir, mutator):
    run_dir = Path(run_dir)
    steps = _read_jsonl(run_dir / 'steps.jsonl')
    episodes = _read_jsonl(run_dir / 'episodes.jsonl')
    manifest = json.loads((run_dir / 'manifest.json').read_text(
        encoding='utf-8'))
    mutator(steps, episodes, manifest)
    _write_jsonl(run_dir / 'steps.jsonl', steps)
    _write_jsonl(run_dir / 'episodes.jsonl', episodes)
    (run_dir / 'manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    if 'outputs_sha256' in manifest:
        _refresh_manifest(run_dir)


# ---------------------------------------------------------------------------
# positive fixture
# ---------------------------------------------------------------------------

def test_synthetic_fixture_passes(tmp_path):
    fixture = build_fixture(tmp_path)
    result = _verify(fixture)
    assert result['status'] == 'PASS', (result['status'],
                                        result['failures'],
                                        result['missing_fields'])
    assert result['failures'] == []
    assert result['missing_fields'] == []
    failed = [name for name, check in result['checks'].items()
              if check['passed'] is not True]
    assert failed == []
    assert set(result) >= {'status', 'checks', 'recomputed', 'failures',
                           'missing_fields', 'run_dirs', 'freeze'}
    episodes = result['recomputed']['runs']['main_A']['episodes']
    assert len(episodes) == 2
    assert result['recomputed']['runs']['main_A']['ttl_ns_observed'] == [150_000_000]
    assert result['recomputed']['pair']['stop_a'] == 1.1
    assert result['recomputed']['pair']['stop_b'] == 1.38
    queue_note = result['recomputed']['notes']['ttl_over_queue_timing']
    assert 'publish queue' in queue_note.lower()
    special_detail = result['checks']['special_segments']['detail']
    assert 'ttl_over' in special_detail
    assert 'contiguous APPLIED/HOLDING' in special_detail


def test_single_run_is_incomplete_not_pass(tmp_path):
    fixture = build_fixture(tmp_path)
    result = _verify(fixture, include_special=False, include_run_b=False)
    assert result['status'] == 'INCOMPLETE'
    assert any('run_b' in item for item in result['missing_fields'])


def test_cli_writes_output_and_exit_code(tmp_path):
    fixture = build_fixture(tmp_path)
    output = tmp_path / 'verify.json'
    argv = ['--pair-freeze', str(fixture['pair_freeze']),
            '--run-a', str(fixture['run_a']),
            '--run-b', str(fixture['run_b']),
            '--special-freeze', str(fixture['special_freeze']),
            '--expected-config', str(fixture['expected_config']),
            '--repo-root', str(fixture['root']),
            '--output', str(output)]
    for segment_id in ('ttl_near', 'ttl_over', 'clock_sync', 'clock_mapping'):
        argv += ['--special-run', '%s=%s' % (segment_id, fixture[segment_id])]
    for segment_id in ('regression_no_obstacle', 'regression_dynamic'):
        argv += ['--regression-run',
                 '%s=%s' % (segment_id, fixture[segment_id])]
    assert MODULE.main(argv) == 0
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['status'] == 'PASS'
    assert set(payload['checks']) == set(MODULE.CHECK_NAMES)
    assert payload['freeze']['sha256'] == _sha(fixture['pair_freeze'])


# ---------------------------------------------------------------------------
# tamper tests: one per required branch
# ---------------------------------------------------------------------------

def test_tampered_ttl_renewal_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            transport = row.get('transport') or {}
            if transport.get('status') == 'APPLIED':
                transport['expires_at_ns'] = transport['issued_at_ns'] \
                    + 100_000_000
                break

    _mutate_run(fixture['run_a'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'ttl_no_renewal' in _failed_checks(result)


def test_tampered_rejected_action_executed_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        target = None
        for index, row in enumerate(steps):
            if (row.get('transport') or {}).get('status') == 'APPLIED':
                target = index
                break
        assert target is not None
        row = steps[target]
        transport = row['transport']
        transport.update({
            'status': 'REJECTED', 'executed': False,
            'action_id': 'poisoned-action',
            'executed_action_id': '',
            'reason': 'REJECT_OWNER'})
        row['applied'] = _applied(None, row['clock']['host_now_ns'])
        steps[target + 1]['transport']['executed_action_id'] = 'poisoned-action'
        steps[target + 1]['applied']['action_id'] = 'poisoned-action'
        steps[target + 1]['transport']['status'] = 'APPLIED'
        steps[target + 1]['transport']['executed'] = True

    _mutate_run(fixture['run_a'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'rejection_never_executed' in _failed_checks(result)


def test_tampered_holding_after_expiry_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for index, row in enumerate(steps):
            if (row.get('transport') or {}).get('status') == 'APPLIED' \
                    and index > 4:
                previous = steps[index - 1]['applied']
                host = row['clock']['host_now_ns']
                issued = previous['issued_at_ns']
                expires = issued + 150_000_000
                if expires <= host:
                    transport = row['transport']
                    transport.update({
                        'status': 'HOLDING', 'executed': True,
                        'action_id': previous['action_id'],
                        'executed_action_id': previous['action_id'],
                        'issued_at_ns': issued,
                        'expires_at_ns': expires})
                    row['applied'] = {
                        'vx_forward_mps': previous['vx_forward_mps'],
                        'vy_left_mps': previous['vy_left_mps'],
                        'vz_up_mps': previous['vz_up_mps'],
                        'yaw_rate_ccw_world_radps':
                            previous['yaw_rate_ccw_world_radps'],
                        'action_id': previous['action_id'],
                        'issued_at_ns': issued,
                        'expires_at_ns': expires,
                        'age_s': (host - issued) / 1e9, 'is_held': True}
                    return
        pytest.fail('no suitable row found for HOLDING tamper')

    _mutate_run(fixture['run_a'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'hold_until_expiry_then_none' in _failed_checks(result)


def test_tampered_brake_distance_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        episodes[0]['metrics']['stop_distance_m'] += 0.5

    _mutate_run(fixture['run_a'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'metrics_match_recorded' in _failed_checks(result)
    fields = {failure.get('field') for failure in result['failures']}
    assert 'metrics.stop_distance_m' in fields


def test_tampered_pair_delay_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    manifest_path = Path(fixture['run_b']) / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['latency_plan']['action_delay_s'] = 0.12
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n',
                             encoding='utf-8')
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'pair_consistency' in _failed_checks(result)


def test_tampered_artifact_hash_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    steps_path = Path(fixture['run_a']) / 'steps.jsonl'
    with steps_path.open('a', encoding='utf-8') as handle:
        handle.write('\n')
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'artifact_hashes' in _failed_checks(result)


def test_missing_fields_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            row.pop('clock', None)

    _mutate_run(fixture['run_a'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('steps[].clock' in item for item in result['missing_fields'])
    assert result['checks']['schema_completeness']['passed'] is not True


def test_expected_classification_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        episodes[0]['outcome'] = 'TIMEOUT'
        episodes[0]['reason'] = 'WALL_TIMEOUT'

    _mutate_run(fixture['run_b'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'expected_classification' in _failed_checks(result)


def test_ttl_near_margin_tamper_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            transport = row.get('transport') or {}
            if transport.get('status') == 'APPLIED':
                issued = transport['issued_at_ns']
                transport['arrival_ns'] = issued + 50_000_000
                transport['scheduled_arrival_ns'] = issued + 50_000_000
                transport['arrival_age_s'] = 0.05
                transport['dispatch_delay_s'] = 0.05

    _mutate_run(fixture['ttl_near'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'special_segments' in _failed_checks(result)


def test_ttl_over_rejection_missing_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            transport = row.get('transport') or {}
            transport['rejections_this_step'] = []
            if transport.get('status') == 'REJECTED':
                transport['status'] = 'NONE'
                transport['executed'] = False
                transport['reason'] = 'REJECT_NO_CACHED_ACTION'
                transport['action_id'] = ''
                transport['executed_action_id'] = ''

    _mutate_run(fixture['ttl_over'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'special_segments' in _failed_checks(result)


def test_ttl_over_residual_missing_fails(tmp_path):
    """Criterion (c): no pre-rejection APPLIED/HOLDING residue -> FAIL."""
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        first_rejection = None
        for index, row in enumerate(steps):
            if (row.get('transport') or {}).get('status') == 'REJECTED':
                first_rejection = index
                break
        assert first_rejection is not None
        for row in steps[:first_rejection]:
            transport = row.get('transport') or {}
            if transport.get('status') in ('APPLIED', 'HOLDING'):
                transport.update({
                    'status': 'NONE', 'reason': 'REJECT_NO_CACHED_ACTION',
                    'executed': False, 'action_id': '',
                    'executed_action_id': '', 'issued_at_ns': 0,
                    'expires_at_ns': 0, 'scheduled_arrival_ns': 0,
                    'arrival_ns': 0, 'dispatch_delay_s': 0.0,
                    'arrival_age_s': 0.0, 'applied': None})
                row['applied'] = _applied(None, row['clock']['host_now_ns'])
        episodes[0]['metrics'] = _record_metrics(manifest['latency_plan'],
                                                episodes[0], steps)

    _mutate_run(fixture['ttl_over'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'special_segments' in _failed_checks(result)
    details = ' '.join(failure['detail'] for failure in result['failures'])
    assert 'contiguous APPLIED/HOLDING' in details or \
        'ttl_over evidence incomplete' in details


def test_ttl_over_post_abort_residual_satisfies_evidence(tmp_path):
    """Lead-agreed alternative (a): residual may live in the POST_ABORT rows."""
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        post_index = None
        for index, row in enumerate(steps):
            transport = row.get('transport') or {}
            if transport.get('status') == 'REJECTED':
                transport['applied'] = None
                row['applied'] = {
                    'vx_forward_mps': 0.0, 'vy_left_mps': 0.0,
                    'vz_up_mps': 0.0, 'yaw_rate_ccw_world_radps': 0.0,
                    'action_id': '', 'issued_at_ns': 0,
                    'expires_at_ns': 0, 'age_s': 0.0, 'is_held': False}
        for index, row in enumerate(steps):
            if row.get('phase') == 'POST_ABORT':
                post_index = index
                break
        assert post_index is not None
        row = steps[post_index]
        host = row['clock']['host_now_ns']
        issued = host - 150_000_000
        ticket = {'id': 'post-abort-active', 'issued': issued,
                  'expires': issued + 150_000_000,
                  'scheduled': host - 50_000_000, 'arrival': host,
                  'command': 0.2}
        row['transport'] = {
            'status': 'APPLIED', 'action_id': ticket['id'],
            'executed_action_id': ticket['id'],
            'issued_at_ns': issued, 'expires_at_ns': ticket['expires'],
            'scheduled_arrival_ns': ticket['scheduled'],
            'arrival_ns': host, 'dispatch_delay_s': 0.1,
            'arrival_age_s': 0.15, 'reason': 'ACCEPT', 'executed': True,
            'rejections_this_step': []}
        row['applied'] = {
            'vx_forward_mps': 0.2, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
            'yaw_rate_ccw_world_radps': 0.0, 'action_id': ticket['id'],
            'issued_at_ns': issued, 'expires_at_ns': ticket['expires'],
            'age_s': 0.15, 'is_held': False}
        episodes[0]['metrics'] = _record_metrics(manifest['latency_plan'],
                                                episodes[0], steps)

    _mutate_run(fixture['ttl_over'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'PASS', (result['status'], result['failures'],
                                        result['missing_fields'])


def test_expected_outcome_alternatives_accepted(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        episodes[0]['outcome'] = 'TIMEOUT'
        episodes[0]['reason'] = 'WALL_TIMEOUT'
        for row in reversed(steps):
            if row.get('phase') == 'RUN':
                row['outcome'] = 'TIMEOUT'
                row['reason'] = 'WALL_TIMEOUT'
                break
        episodes[0]['metrics'] = _record_metrics(manifest['latency_plan'],
                                                episodes[0], steps)

    _mutate_run(fixture['ttl_over'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'PASS', (result['status'], result['failures'],
                                        result['missing_fields'])


def test_clock_sync_rejection_missing_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            transport = row.get('transport') or {}
            if transport.get('status') == 'REJECTED':
                transport['reason'] = 'REJECT_OWNER'
            for extra in transport.get('rejections_this_step') or []:
                extra['reason'] = 'REJECT_OWNER'
            if row.get('v2_admission') == 'REJECTED':
                row['v2_reject_reason'] = 'REJECT_OWNER'

    _mutate_run(fixture['clock_sync'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'special_segments' in _failed_checks(result)


def test_clock_mapping_unusable_missing_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        for row in steps:
            clock = row.get('clock') or {}
            if clock.get('mapping_usable') is False:
                clock.update({
                    'mapping_host_ns': clock.get('capture_host_ns'),
                    'mapping_error_ns': 0,
                    'mapping_usable': True, 'mapping_reason': 'ACCEPT',
                    'age_point_s': 0.2, 'age_bound_s': 0.2})
                row['observation_valid'] = True
                row['observation_reason'] = 'ACCEPT'
                row['observation_age_s'] = 0.2

    _mutate_run(fixture['clock_mapping'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'special_segments' in _failed_checks(result)


def test_post_abort_rows_missing_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps, episodes, manifest):
        kept = [row for row in steps if row.get('phase') != 'POST_ABORT']
        steps[:] = kept

    _mutate_run(fixture['ttl_over'], mutate)
    result = _verify(fixture)
    assert result['status'] == 'FAIL'
    assert 'post_abort_rows' in _failed_checks(result)


def test_exploration_style_v1_freeze_is_incomplete(tmp_path):
    """Old exploration runs lack the new schema: must be INCOMPLETE, not PASS."""
    fixture = build_fixture(tmp_path)
    # Drop the new raw-record blocks to emulate an old run and use a v1 freeze.
    for run in ('run_a', 'run_b'):
        def mutate(steps, episodes, manifest):
            for row in steps:
                for key in ('clock', 'transport', 'applied', 'phase'):
                    row.pop(key, None)
            for episode in episodes:
                episode.pop('metrics', None)
                episode.pop('phase_summary', None)
        _mutate_run(fixture[run], mutate)
    pair_freeze_path = Path(fixture['pair_freeze'])
    pair_freeze = json.loads(pair_freeze_path.read_text(encoding='utf-8'))
    pair_freeze['schema_version'] = 'boom_birds.latency_pair_freeze.v1'
    pair_freeze['status'] = 'FROZEN_AFTER_RUNS_RECORDED'
    pair_freeze.pop('frozen_at', None)
    pair_freeze.pop('worktree_state', None)
    pair_freeze_path.write_text(json.dumps(pair_freeze, indent=2) + '\n',
                                encoding='utf-8')
    # The manifests now point at a stale freeze digest; the verifier must report
    # that plus the missing raw fields, and never PASS.
    result = _verify(fixture, include_special=False)
    assert result['status'] == 'INCOMPLETE'
    missing = '\n'.join(result['missing_fields'])
    for expected in ('steps[].clock', 'steps[].transport', 'steps[].applied',
                     'steps[].phase', 'episodes[].metrics'):
        assert expected in missing, (expected, missing)
    assert result['checks']['schema_completeness']['passed'] is not True
