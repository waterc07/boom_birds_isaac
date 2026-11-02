#!/usr/bin/env python3
"""Independent verification of latency-envelope evaluation runs.

Implements docs/superpowers/plans/2026-11-02-latency-envelope.md section 6.

Design rules:

* Pure standard library.  The verifier never imports the runner, the evaluation
  helpers or anything from ``src/`` -- it recomputes from the raw evidence only.
* ``summary.json`` is never read and recorded ``metrics`` are never used as a
  conclusion.  Steps are re-derived from ``steps.jsonl``; ``episodes.jsonl``
  metrics are compared against the independent recomputation and any mismatch
  is reported as a failure.
* Missing raw fields or incomplete data produce ``status = INCOMPLETE`` -- never
  ``PASS``.  Unknown enum values / contradictions produce ``FAIL``.

Expected raw-record contract (plan section 3, fixed names):

``steps.jsonl`` per row
    phase, clock{host_now_ns, capture_host_ns, capture_clock_ns,
    camera_clock_id, mapping_host_ns, mapping_error_ns,
    mapping_sync_generation, mapping_usable, mapping_reason, age_point_s,
    age_bound_s}, observation_age_s, observation_valid, observation_reason,
    transport{status, action_id, executed_action_id, issued_at_ns,
    expires_at_ns, scheduled_arrival_ns, arrival_ns, dispatch_delay_s,
    arrival_age_s, reason, executed}, applied{vx_forward_mps, vy_left_mps,
    vz_up_mps, yaw_rate_ccw_world_radps, action_id, issued_at_ns,
    expires_at_ns, age_s, is_held}, plus the retained ``v2_*`` fields and the
    physical state fields (position/velocity/speed/obstacle/supervisor/contact).
``episodes.jsonl`` per row
    config_id, segment_id, pair_key, phase_summary and ``metrics`` (plan 3.2).
``manifest.json``
    latency_plan, clock_plan, freeze, body_envelope, evaluation_version,
    episode_ids, gui_evidence plus the existing manifest fields.

Clock algebra assumed (plan 2.1/2.4):

    capture_host_ns = max(0, host_now_ns - obs_delay_ns - case_obs_delay_ns)
    capture_clock_ns = round(capture_host_ns + offset_ns
                             + capture_host_ns * drift_ppm / 1e6)
    mapping_host_ns = round((capture_clock_ns - offset_ns)
                            / (1 + drift_ppm / 1e6))
    mapping_error_ns = abs(offset_ns) + uncertainty_ns
                       + ceil(abs(drift_ppm) * 1e-6 * abs(host_now_ns))
    age_point_s = max(0, (host_now_ns - mapping_host_ns) / 1e9)
    age_bound_s = age_point_s + mapping_error_ns / 1e9
    observation_age_s == age_bound_s
    mapping_usable == observation_valid; unusable => reason
    'CLOCK_MAPPING_UNUSABLE'.

Transport semantics assumed (plan 2.2/3.1):

    expires_at_ns - issued_at_ns == ttl_ns for every accepted action (re-sends
    never extend the TTL); ``status='DIRECT'`` when action delay is zero and
    ``executed_action_id == action_id``; ``APPLIED`` = a newly arrived action
    was accepted this step; ``HOLDING`` = no new arrival but the previous active
    setpoint is still inside its TTL and keeps executing; ``REJECTED`` = an
    arrival was refused (``executed=False``, its ``action_id`` must never show
    up as an ``executed_action_id``); ``NONE`` = no active setpoint (applied
    record is all-zero).  ``arrival_age_s = (arrival_ns - issued_at_ns) / 1e9``
    and ``dispatch_delay_s = (scheduled_arrival_ns - issued_at_ns) / 1e9``.

Usage:

    python scripts/verify_latency_runs.py \
        --pair-freeze configs/scenarios/latency_pair_freeze_v2.json \
        --run-a outputs/map_eval/latency_formal2_A \
        --run-b outputs/map_eval/latency_formal2_B \
        --special-freeze configs/scenarios/latency_special_freeze_v2.json \
        --special-run ttl_near=outputs/map_eval/latency_ttl_near \
        --special-run ttl_over=outputs/map_eval/latency_ttl_over \
        --special-run clock_sync=outputs/map_eval/latency_clock_sync \
        --special-run clock_mapping=outputs/map_eval/latency_clock_mapping \
        --regression-run regression_no_obstacle=outputs/map_eval/latency_reg_no_obstacle \
        --regression-run regression_dynamic=outputs/map_eval/latency_reg_dynamic \
        --expected-config configs/scenarios/latency_expected_v1.json \
        --output docs/reports/map_eval/latency/verify_latency_runs.json

Exit code: 0 = PASS, 1 = FAIL, 2 = INCOMPLETE.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LATENCY_EVAL_VERSION = 'boom_birds.latency_eval.v1'
LATENCY_FREEZE_SCHEMA = 'boom_birds.latency_freeze.v2'

TRANSPORT_STATUSES = ('DIRECT', 'APPLIED', 'HOLDING', 'REJECTED', 'NONE')
PHASES = ('RUN', 'POST_ABORT')
OUTCOMES = ('SUCCESS', 'COLLISION', 'TIMEOUT', 'OUT_OF_BOUNDS', 'ABORT', 'INVALID')

STOP_SPEED_MPS = 0.08
STOP_HOLD_S = 0.5
CONTACT_FORCE_N = 0.02

# Numeric tolerances.  Raw times/positions are recorded by a simulation that
# rounds to a few decimals, so the recompute-vs-recorded comparison must allow
# a little rounding while staying far below one 50 ms control tick.
HOST_NS_TOL = 1_000_000            # 1 ms between host_now_ns and time_s * 1e9
CLOCK_NS_TOL = 2                   # integer ns rounding in clock algebra
AGE_TOL_S = 1e-6                   # clock ages are derived from integer ns
METRIC_TOL_TIME_S = 5e-4
METRIC_TOL_DIST_M = 5e-4
METRIC_TOL_SPEED_MPS = 5e-4
METRIC_TOL_FORCE_N = 5e-4
PLAN_TOL = 1e-6

CHECK_NAMES = (
    'schema_completeness',
    'clock_domain_and_mapping',
    'observation_age_and_queueing',
    'ttl_no_renewal',
    'arrival_expiry_rejection',
    'rejection_never_executed',
    'hold_until_expiry_then_none',
    'applied_record_consistency',
    'brake_start_and_stop_metrics',
    'geometry_contact_metrics',
    'metrics_match_recorded',
    'episode_continuity',
    'pair_consistency',
    'denominator_and_episode_ids',
    'expected_classification',
    'artifact_hashes',
    'freeze_lineage',
    'gui_evidence',
    'special_segments',
    'post_abort_rows',
)

STEP_TOP_KEYS = (
    'episode_id', 'case_id', 'method', 'step', 'time_s', 'phase',
    'position_world_m', 'velocity_world_mps', 'speed_mps', 'command',
    'supervisor_state', 'supervisor_action', 'observation_valid',
    'observation_reason', 'contact_force_n',
    'contact_prim', 'outcome', 'reason', 'env_terminated', 'env_truncated',
    'episode_length_buf', 'boundary_count_ok', 'execution_path',
)

V2_STEP_KEYS = ('v2_admission', 'v2_action_id', 'v2_reject_reason',
                'v2_executed', 'v2_issued_at_ns', 'v2_expires_at_ns',
                'v2_context', 'v2_context_owner', 'v2_fault_type')

CLOCK_KEYS = (
    'host_now_ns', 'capture_host_ns', 'capture_clock_ns', 'camera_clock_id',
    'mapping_host_ns', 'mapping_error_ns', 'mapping_sync_generation',
    'mapping_usable', 'mapping_reason', 'age_point_s', 'age_bound_s',
)

TRANSPORT_KEYS = (
    'status', 'action_id', 'executed_action_id', 'issued_at_ns',
    'expires_at_ns', 'scheduled_arrival_ns', 'arrival_ns',
    'dispatch_delay_s', 'arrival_age_s', 'reason', 'executed',
)

APPLIED_KEYS = (
    'vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
    'yaw_rate_ccw_world_radps', 'action_id', 'issued_at_ns',
    'expires_at_ns', 'age_s', 'is_held',
)

V2_CONTEXT_KEYS = (
    'system_boot_id', 'mission_epoch', 'localization_epoch', 'control_epoch',
    'clock_id', 'px4_boot_id', 'sync_generation',
)

LATENCY_PLAN_KEYS = (
    'role', 'segment_id', 'config_id', 'obs_delay_s', 'action_delay_s',
    'ttl_ms', 'max_age_ms', 'allowed_observation_age_ms', 'stop_distance_m',
    'post_abort_observe_s', 'sync_fail_step', 'obs_mapping_fail_step',
    'transport_stall_step', 'transport_stall_delay_s', 'execution_path',
    'methods', 'case_ids',
)

CLOCK_PLAN_KEYS = ('camera_clock_id', 'offset_ms', 'drift_ppm', 'uncertainty_ms')

MANIFEST_POINTER_KEYS = ('path', 'sha256', 'schema_version', 'frozen_at',
                         'code_commit')

METRICS_KEYS = (
    'brake_start', 'initial_speed_mps', 'stop_distance_m', 'stop_time_s',
    'stop_definition', 'final_speed_mps', 'min_center_distance_m',
    'min_center_distance_time_s', 'min_envelope_gap_m', 'envelope',
    'max_closing_speed_mps', 'max_relative_speed_mps', 'contact_max_force_n',
    'contact_prim', 'executed_action_count', 'arrival_rejection_count',
    'arrival_reject_reasons', 'post_abort',
)

EPISODE_KEYS = ('episode_id', 'case_id', 'method', 'outcome', 'reason', 'steps',
                'duration_s', 'config_id', 'segment_id', 'pair_key',
                'phase_summary', 'metrics')

MANIFEST_KEYS = (
    'schema_version', 'code_commit', 'gui_mode', 'renderer', 'command',
    'started_at', 'methods', 'cases_sha256', 'map_asset_id',
    'terrain_sha256', 'preview_sha256', 'map_config_sha256',
    'outputs_sha256', 'latency_plan', 'clock_plan', 'freeze',
    'body_envelope', 'evaluation_version', 'episode_ids', 'gui_evidence',
)

ENVELOPE_KEYS = ('body_half_extents_m', 'obstacle_half_extents_m',
                 'body_radius_m', 'obstacle_radius_m')

POST_ABORT_KEYS = ('steps', 'residual_distance_m', 'time_to_stop_s', 'contact')

EXPECTED_SPEC_KEYS = frozenset({
    'outcome', 'expected_outcome', 'classification', 'reason',
    'expected_reason', 'expected_reason_contains', 'behavior',
    'expected_behavior', 'note',
})

PAIR_EQUALITY_KEYS = (
    'obs_delay_s', 'action_delay_s', 'ttl_ms', 'max_age_ms',
    'allowed_observation_age_ms', 'post_abort_observe_s', 'sync_fail_step',
    'obs_mapping_fail_step', 'transport_stall_step', 'transport_stall_delay_s',
    'execution_path', 'methods', 'case_ids',
)

PAIR_NON_STOP_KEYS = frozenset({'role', 'config_id', 'segment_id',
                                'stop_distance_m'})

MAX_FAILURES = 800
MAX_CHECK_NOTES = 6
MAX_LIST_DETAIL = 40


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fnum(value):
    return float(value) if _num(value) else None


def _close(actual, expected, tol):
    return (_num(actual) and _num(expected)
            and abs(float(actual) - float(expected)) <= tol)


def _equal_nullable(actual, expected, tol):
    if actual is None or expected is None:
        return actual is None and expected is None
    return _close(actual, expected, tol)


def _vec_close(actual, expected, tol, length=3):
    if not isinstance(actual, (list, tuple)) or len(actual) < length:
        return False
    if not isinstance(expected, (list, tuple)) or len(expected) < length:
        return False
    return all(_close(actual[i], expected[i], tol) for i in range(length))


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else None


def _same_sequence(actual, expected):
    left = _as_list(actual)
    right = _as_list(expected)
    return left is not None and right is not None \
        and [str(item) for item in left] == [str(item) for item in right]


def _same_list_unordered(actual, expected):
    left = _as_list(actual)
    right = _as_list(expected)
    return left is not None and right is not None \
        and sorted(str(item) for item in left) == sorted(str(item) for item in right)


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _load_jsonl(path):
    rows = []
    with Path(path).open('r', encoding='utf-8') as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_iso(text):
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError:
        return None


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _short(value, limit=MAX_LIST_DETAIL):
    if isinstance(value, (list, tuple)):
        if len(value) > limit:
            return [str(item) for item in value[:limit]] + ['...']
        return [_jsonable(item) for item in value]
    return value


def _example(row, prefix='episode'):
    return '%s %s step %s' % (prefix, row.get('episode_id'), row.get('step'))


def _ns_from_ms(value):
    return int(round(float(value) * 1e6)) if _num(value) else None


def _ns_from_s(value):
    return int(round(float(value) * 1e9)) if _num(value) else None


def _s_to_dt(rows):
    times = [float(row['time_s']) for row in rows
             if _num(row.get('time_s'))]
    if len(times) < 2:
        return None
    diffs = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not diffs:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]


# ---------------------------------------------------------------------------
# reporting plumbing
# ---------------------------------------------------------------------------

class MissingFields:
    """Collects missing raw-record fields (never silently ignored)."""

    def __init__(self):
        self._items = {}

    def add(self, label, path, example=None):
        key = (label, path)
        item = self._items.get(key)
        if item is None:
            self._items[key] = {'label': label, 'path': path, 'count': 1,
                                'example': example}
        else:
            item['count'] += 1

    def extend(self, label, paths, example=None):
        for path in paths:
            self.add(label, path, example)

    def __bool__(self):
        return bool(self._items)

    def count(self):
        return len(self._items)

    def as_list(self):
        result = []
        for item in sorted(self._items.values(),
                           key=lambda entry: (entry['label'], entry['path'])):
            text = '%s: %s' % (item['label'], item['path'])
            if item['count'] > 1:
                text += ' (occurrences=%d)' % item['count']
            if item['example']:
                text += ' (e.g. %s)' % item['example']
            result.append(text)
        return result


class Verifier:
    """Accumulates per-check pass/fail state, structured failures and gaps."""

    def __init__(self):
        self.checks = {name: {'passed': None, 'notes': [], 'failures': 0}
                       for name in CHECK_NAMES}
        self.failures = []
        self.missing = MissingFields()

    def ok(self, name, detail=''):
        entry = self.checks[name]
        if entry['passed'] is None:
            entry['passed'] = True
        if detail and len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append(str(detail))

    def note(self, name, detail):
        entry = self.checks[name]
        if len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append(str(detail))

    def fail(self, name, detail, *, run=None, episode_id=None, step=None,
             field=None, expected=None, actual=None):
        entry = self.checks[name]
        entry['passed'] = False
        entry['failures'] += 1
        if len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append('x ' + str(detail))
        if len(self.failures) < MAX_FAILURES:
            failure = {'check': name, 'detail': str(detail)}
            if run is not None:
                failure['run'] = str(run)
            if episode_id is not None:
                failure['episode_id'] = str(episode_id)
            if step is not None:
                failure['step'] = step
            if field is not None:
                failure['field'] = str(field)
            if expected is not None:
                failure['expected'] = _jsonable(expected)
            if actual is not None:
                failure['actual'] = _jsonable(actual)
            self.failures.append(failure)

    def skip(self, name, detail):
        entry = self.checks[name]
        if entry['passed'] is None and len(entry['notes']) < 3:
            entry['notes'].append('skip: ' + str(detail))

    def ok_if_clean(self, name, detail):
        if self.checks[name]['passed'] is None:
            self.ok(name, detail)

    def finalize_checks(self):
        result = {}
        for name, entry in self.checks.items():
            detail = '; '.join(entry['notes']) if entry['notes'] \
                else 'not evaluated'
            if entry['failures'] > len(entry['notes']):
                detail += ' (failures=%d)' % entry['failures']
            result[name] = {'passed': entry['passed'], 'detail': detail}
        return result


# ---------------------------------------------------------------------------
# run loading / schema completeness
# ---------------------------------------------------------------------------

@dataclass
class RunEvidence:
    label: str
    role: str
    run_dir: Path
    manifest: dict = field(default_factory=dict)
    episodes: list = field(default_factory=list)
    steps_by_episode: dict = field(default_factory=dict)
    row_count: int = 0
    loaded: bool = False


def load_run(label, role, run_dir, verifier):
    evidence = RunEvidence(label=label, role=role, run_dir=Path(run_dir))
    if not evidence.run_dir.is_dir():
        verifier.missing.add(label, 'run_dir')
        return evidence
    paths = {
        'manifest.json': evidence.run_dir / 'manifest.json',
        'episodes.jsonl': evidence.run_dir / 'episodes.jsonl',
        'steps.jsonl': evidence.run_dir / 'steps.jsonl',
    }
    for name, path in paths.items():
        if not path.is_file():
            verifier.missing.add(label, name)
    try:
        if paths['manifest.json'].is_file():
            evidence.manifest = _load_json(paths['manifest.json'])
        if paths['episodes.jsonl'].is_file():
            evidence.episodes = _load_jsonl(paths['episodes.jsonl'])
        if paths['steps.jsonl'].is_file():
            rows = _load_jsonl(paths['steps.jsonl'])
            evidence.row_count = len(rows)
            for row in rows:
                evidence.steps_by_episode.setdefault(
                    row.get('episode_id'), []).append(row)
    except (OSError, ValueError) as error:
        verifier.fail('artifact_hashes', 'raw output parse failure: ' + repr(error),
                      run=label)
    evidence.loaded = all(path.is_file() for path in paths.values())
    return evidence


def _require_keys(verifier, label, node, keys, prefix, example):
    if not isinstance(node, dict):
        verifier.missing.add(label, prefix, example)
        return
    for key in keys:
        if node.get(key) is None:
            verifier.missing.add(label, prefix + '.' + key, example)


def verify_step_schema(evidence, verifier):
    label = evidence.label
    for rows in evidence.steps_by_episode.values():
        for row in rows:
            example = _example(row)
            _require_keys(verifier, label, row, STEP_TOP_KEYS, 'steps[]', example)
            clock = row.get('clock')
            if not isinstance(clock, dict):
                verifier.missing.add(label, 'steps[].clock', example)
            else:
                unusable = clock.get('mapping_usable') is False
                optional_none = {'mapping_host_ns', 'mapping_error_ns',
                                 'age_point_s', 'age_bound_s'}
                for key in CLOCK_KEYS:
                    if key not in clock:
                        verifier.missing.add(
                            label, 'steps[].clock.' + key, example)
                    elif clock.get(key) is None \
                            and not (unusable and key in optional_none):
                        verifier.missing.add(
                            label, 'steps[].clock.' + key, example)
                if unusable and row.get('observation_age_s') is None:
                    pass  # age is undefined while the camera mapping is unusable
                elif row.get('observation_age_s') is None:
                    verifier.missing.add(
                        label, 'steps[].observation_age_s', example)
            transport = row.get('transport')
            if not isinstance(transport, dict):
                verifier.missing.add(label, 'steps[].transport', example)
            else:
                for key in TRANSPORT_KEYS:
                    if key not in transport:
                        verifier.missing.add(
                            label, 'steps[].transport.' + key, example)
                for key in ('status', 'executed'):
                    if transport.get(key) is None:
                        verifier.missing.add(
                            label, 'steps[].transport.' + key, example)
            _require_keys(verifier, label, row.get('applied'), APPLIED_KEYS,
                          'steps[].applied', example)
            for key in ('v2_admission', 'v2_action_id', 'v2_reject_reason',
                        'v2_executed', 'v2_fault_type'):
                if key not in row:
                    verifier.missing.add(label, 'steps[].' + key, example)
            for key in ('v2_admission', 'v2_action_id', 'v2_reject_reason',
                        'v2_executed'):
                if row.get(key) is None:
                    verifier.missing.add(label, 'steps[].' + key, example)
            if row.get('v2_action_id'):
                for key in ('v2_issued_at_ns', 'v2_expires_at_ns',
                            'v2_context', 'v2_context_owner'):
                    if row.get(key) is None:
                        verifier.missing.add(label, 'steps[].' + key, example)
                _require_keys(verifier, label, row.get('v2_context'),
                              V2_CONTEXT_KEYS, 'steps[].v2_context', example)
            phase = row.get('phase')
            if phase is not None and phase not in PHASES:
                verifier.fail('schema_completeness',
                              'invalid step.phase value', run=label,
                              episode_id=row.get('episode_id'),
                              step=row.get('step'), field='phase',
                              expected=list(PHASES), actual=phase)
            status = (row.get('transport') or {}).get('status') \
                if isinstance(row.get('transport'), dict) else None
            if status is not None and status not in TRANSPORT_STATUSES:
                verifier.fail('schema_completeness',
                              'invalid transport.status value', run=label,
                              episode_id=row.get('episode_id'),
                              step=row.get('step'), field='transport.status',
                              expected=list(TRANSPORT_STATUSES), actual=status)
            if not row.get('episode_id'):
                verifier.missing.add(label, 'steps[].episode_id', example)


def verify_episode_schema(evidence, verifier):
    label = evidence.label
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            verifier.fail('schema_completeness', 'episode row is not an object',
                          run=label)
            continue
        example = 'episode %s' % episode.get('episode_id')
        _require_keys(verifier, label, episode, EPISODE_KEYS, 'episodes[]',
                      example)
        metrics = episode.get('metrics')
        if not isinstance(metrics, dict):
            verifier.missing.add(label, 'episodes[].metrics', example)
        else:
            for key in METRICS_KEYS:
                if key not in metrics:
                    verifier.missing.add(
                        label, 'episodes[].metrics.' + key, example)
            envelope = metrics.get('envelope')
            if isinstance(envelope, dict):
                _require_keys(verifier, label, envelope, ENVELOPE_KEYS,
                              'episodes[].metrics.envelope', example)
            elif 'envelope' not in metrics:
                verifier.missing.add(label, 'episodes[].metrics.envelope',
                                     example)
            post_abort = metrics.get('post_abort')
            if isinstance(post_abort, dict):
                for key in ('steps', 'residual_distance_m',
                            'time_to_stop_s'):
                    if key not in post_abort:
                        verifier.missing.add(
                            label, 'episodes[].metrics.post_abort.' + key,
                            example)
                if post_abort.get('contact') is None \
                        and post_abort.get('contact_max_force_n') is None:
                    verifier.missing.add(
                        label, 'episodes[].metrics.post_abort.contact', example)
            else:
                verifier.missing.add(label,
                                     'episodes[].metrics.post_abort', example)


def verify_manifest_schema(evidence, verifier):
    label = evidence.label
    manifest = evidence.manifest
    _require_keys(verifier, label, manifest, MANIFEST_KEYS, 'manifest', label)
    _require_keys(verifier, label, manifest.get('latency_plan'),
                  LATENCY_PLAN_KEYS, 'manifest.latency_plan', label)
    _require_keys(verifier, label, manifest.get('clock_plan'), CLOCK_PLAN_KEYS,
                  'manifest.clock_plan', label)
    pointer = manifest.get('freeze')
    if not isinstance(pointer, dict):
        verifier.missing.add(label, 'manifest.freeze', label)
    elif pointer:
        _require_keys(verifier, label, pointer, MANIFEST_POINTER_KEYS,
                      'manifest.freeze', label)
    elif evidence.role != 'regression':
        # Regression (isolation) runs may legitimately have no freeze pointer;
        # every formal main/special run must record one.
        verifier.missing.add(label, 'manifest.freeze', label)
    _require_keys(verifier, label, manifest.get('body_envelope'),
                  ('half_extents_m', 'source', 'measured_prim'),
                  'manifest.body_envelope', label)
    gui_evidence = manifest.get('gui_evidence')
    if not gui_evidence:
        verifier.missing.add(label, 'manifest.gui_evidence', label)


# ---------------------------------------------------------------------------
# freeze / artifact / GUI checks
# ---------------------------------------------------------------------------

def _worktree_digest_candidates(repo_root):
    """Return candidate worktree-status digests for known normalisations."""
    try:
        completed = subprocess.run(
            ['git', 'status', '--porcelain', '--', 'src', 'scripts', 'tests',
             'configs'],
            cwd=str(repo_root), capture_output=True, text=True, timeout=60,
            check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    raw = completed.stdout
    lines = [line.rstrip() for line in raw.replace('\r\n', '\n').split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    joined = '\n'.join(lines)
    candidates = {hashlib.sha256(joined.encode('utf-8')).hexdigest()}
    candidates.add(hashlib.sha256((joined + '\n').encode('utf-8')).hexdigest())
    return candidates


def verify_freeze(freeze, freeze_path, role, verifier, label):
    """Validate a freeze document itself (not the runs)."""
    name = 'freeze_lineage'
    if not isinstance(freeze, dict):
        verifier.missing.add(label, 'freeze document')
        return
    schema = freeze.get('schema_version')
    if schema != LATENCY_FREEZE_SCHEMA:
        verifier.fail(name, 'freeze schema_version is not the v2 pre-run schema',
                      run=label, field='schema_version',
                      expected=LATENCY_FREEZE_SCHEMA, actual=schema)
    status = freeze.get('status')
    if status != 'PRE_RUN_FROZEN':
        verifier.fail(name, 'freeze status is not PRE_RUN_FROZEN (recorded '
                      'evidence cannot be upgraded)', run=label,
                      field='status', expected='PRE_RUN_FROZEN', actual=status)
    frozen_at = freeze.get('frozen_at')
    if not _parse_iso(frozen_at):
        verifier.missing.add(label, 'freeze.frozen_at', label)
    if not freeze.get('code_commit'):
        verifier.missing.add(label, 'freeze.code_commit', label)
    worktree = freeze.get('worktree_state')
    if not isinstance(worktree, dict):
        verifier.missing.add(label, 'freeze.worktree_state', label)
    else:
        for key in ('tracked_paths', 'status_text_sha256', 'clean'):
            if worktree.get(key) is None:
                verifier.missing.add(label, 'freeze.worktree_state.' + key, label)
    if freeze.get('evaluation_version') != LATENCY_EVAL_VERSION:
        verifier.fail(name, 'freeze.evaluation_version mismatch', run=label,
                      field='evaluation_version',
                      expected=LATENCY_EVAL_VERSION,
                      actual=freeze.get('evaluation_version'))
    case_ids = freeze.get('case_ids')
    main_plans = freeze.get('main_run_plans')
    derived_case_ids = []
    if isinstance(main_plans, dict):
        for run_plan in main_plans.values():
            if isinstance(run_plan, dict) \
                    and isinstance(run_plan.get('case_ids'), list) \
                    and run_plan['case_ids']:
                derived_case_ids = list(run_plan['case_ids'])
                break
    if (not isinstance(case_ids, list) or not case_ids) and not derived_case_ids:
        verifier.missing.add(label, 'freeze.case_ids', label)
    cases_file = freeze.get('cases_file')
    cases_sha = freeze.get('cases_sha256')
    if not cases_file:
        verifier.missing.add(label, 'freeze.cases_file', label)
    elif not cases_sha:
        verifier.missing.add(label, 'freeze.cases_sha256', label)
    for key in ('map_asset_id', 'terrain_sha256', 'preview_sha256',
                'map_config_sha256'):
        if freeze.get(key) is None:
            verifier.missing.add(label, 'freeze.' + key, label)
    if not isinstance(freeze.get('clock_plan'), dict):
        verifier.missing.add(label, 'freeze.clock_plan', label)
    if not isinstance(freeze.get('latency_plan'), dict) \
            and not isinstance(freeze.get('latency_plan_defaults'), dict):
        verifier.missing.add(label, 'freeze.latency_plan_defaults', label)
    if not isinstance(freeze.get('evaluation'), dict):
        verifier.missing.add(label, 'freeze.evaluation', label)
    if not isinstance(freeze.get('body_envelope'), dict):
        verifier.missing.add(label, 'freeze.body_envelope', label)
    if role == 'pair':
        plans = freeze.get('main_run_plans')
        if not isinstance(plans, dict) or not plans:
            verifier.missing.add(label, 'freeze.main_run_plans', label)
    if role == 'special':
        segments = freeze.get('special_segments')
        if not isinstance(segments, (list, dict)) or not segments:
            verifier.missing.add(label, 'freeze.special_segments', label)
    verifier.ok(name, 'freeze document parsed (%s)' % label)


def verify_freeze_file_digest_cases(freeze, freeze_path, verifier, label,
                                    repo_root):
    if not isinstance(freeze, dict):
        return
    cases_file = freeze.get('cases_file')
    cases_sha = freeze.get('cases_sha256')
    if not cases_file or not cases_sha:
        return
    path = Path(str(cases_file))
    if not path.is_absolute():
        path = Path(repo_root) / path
    if not path.is_file():
        verifier.missing.add(label, 'freeze.cases_file exists (%s)' % path, label)
        return
    actual = _sha256_file(path)
    if actual != str(cases_sha).lower():
        verifier.fail('freeze_lineage', 'freeze.cases_sha256 does not match the '
                      'cases file on disk', run=label, field='cases_sha256',
                      expected=actual, actual=cases_sha)


def verify_worktree_digest(freeze, freeze_path, verifier, label, repo_root):
    if not isinstance(freeze, dict):
        return
    worktree = freeze.get('worktree_state')
    if not isinstance(worktree, dict):
        return
    recorded = worktree.get('status_text_sha256')
    root = Path(repo_root)
    if not (root / '.git').exists():
        verifier.skip('freeze_lineage', 'repo root has no .git; worktree digest '
                      'not recomputed')
        return
    candidates = _worktree_digest_candidates(root)
    if candidates is None:
        verifier.skip('freeze_lineage', 'git status unavailable; worktree digest '
                      'not recomputed')
        return
    if recorded not in candidates:
        # Post-run commits legitimately change HEAD/worktree; the recorded
        # digest is only informative during final verification (Lead lineage
        # contract).  Real-time lineage enforcement belongs to the run entry
        # point (check_freeze_lineage), not to the independent verifier.
        verifier.note('freeze_lineage', 'INFO: current worktree digest differs '
                      'from the recorded freeze digest (expected after the '
                      'post-run commit; not a PASS criterion)')
    else:
        verifier.ok('freeze_lineage', 'freeze worktree digest matches current '
                    'worktree (informational)')


def verify_artifacts(evidence, freeze_path, verifier):
    name = 'artifact_hashes'
    label = evidence.label
    manifest = evidence.manifest
    pointer = manifest.get('freeze')
    records_freeze = (isinstance(pointer, dict)
                      and any(pointer.get(key) for key in
                              ('path', 'sha256', 'frozen_at', 'code_commit')))
    outputs = manifest.get('outputs_sha256')
    verified_outputs = 0
    if not isinstance(outputs, dict) or not outputs:
        verifier.missing.add(label, 'manifest.outputs_sha256', label)
    else:
        for file_name, digest in outputs.items():
            path = evidence.run_dir / str(file_name)
            if not path.is_file():
                verifier.missing.add(label,
                                     'artifact %s' % file_name, label)
                continue
            actual = _sha256_file(path)
            if not isinstance(digest, str) or actual != digest.lower():
                verifier.fail(name, 'artifact hash mismatch', run=label,
                              field=str(file_name), expected=actual,
                              actual=digest)
            else:
                verified_outputs += 1
    if verified_outputs:
        verifier.ok(name, '%d artifact hashes verified for %s'
                    % (verified_outputs, label))
    if not records_freeze:
        # Regression/isolation runs may record an empty freeze pointer.
        return
    target = (Path(freeze_path)
              if freeze_path and Path(freeze_path).is_file() else None)
    recorded_path = pointer.get('path')
    points_to_target = False
    if target is not None and recorded_path:
        given = Path(str(recorded_path))
        points_to_target = (given.resolve() == target.resolve()
                            if given.is_absolute()
                            else given.name == target.name)
    if points_to_target:
        actual_freeze_sha = _sha256_file(target)
        recorded = pointer.get('sha256')
        if recorded:
            if str(recorded).lower() != actual_freeze_sha:
                verifier.fail(name, 'manifest.freeze.sha256 does not match the '
                              'freeze file', run=label, field='freeze.sha256',
                              expected=actual_freeze_sha, actual=recorded)
            else:
                verifier.ok(name, 'freeze file sha256 verified for ' + label)
        else:
            verifier.missing.add(label, 'manifest.freeze.sha256', label)
        pointer_schema = pointer.get('schema_version')
        if pointer_schema and pointer_schema != LATENCY_FREEZE_SCHEMA:
            verifier.fail('freeze_lineage', 'manifest.freeze.schema_version is not '
                          'the v2 freeze schema', run=label,
                          field='freeze.schema_version',
                          expected=LATENCY_FREEZE_SCHEMA, actual=pointer_schema)
        elif not pointer_schema:
            verifier.missing.add(label, 'manifest.freeze.schema_version', label)
    elif target is not None and recorded_path:
        # Special/regression runs may reference their own frozen scenario file;
        # it is not supplied here, so only the self-consistency is checked.
        verifier.note('freeze_lineage', '%s freeze pointer references %s (not the '
                      'provided freeze)' % (label, recorded_path))
    frozen = _parse_iso(pointer.get('frozen_at'))
    started = _parse_iso(manifest.get('started_at'))
    if frozen is None:
        verifier.missing.add(label, 'manifest.freeze.frozen_at', label)
    if started is None:
        verifier.missing.add(label, 'manifest.started_at', label)
    if frozen is not None and started is not None:
        if frozen > started:
            verifier.fail('freeze_lineage', 'freeze.frozen_at is after '
                          'manifest.started_at (freeze must precede the run)',
                          run=label, field='frozen_at',
                          expected='<= ' + str(started), actual=str(frozen))
        else:
            verifier.ok('freeze_lineage', 'frozen_at <= started_at')
    pointer_commit = pointer.get('code_commit')
    manifest_commit = manifest.get('code_commit')
    if pointer_commit and manifest_commit:
        left = str(manifest_commit).lower()
        right = str(pointer_commit).lower()
        if not (left.startswith(right) or right.startswith(left)):
            verifier.fail('freeze_lineage', 'manifest.code_commit does not match '
                          'freeze.code_commit', run=label, field='code_commit',
                          expected=right, actual=left)
        else:
            verifier.ok('freeze_lineage', 'code_commit matches freeze')


def verify_gui(evidence, verifier):
    name = 'gui_evidence'
    label = evidence.label
    manifest = evidence.manifest
    if manifest.get('gui_mode') is not True:
        verifier.fail(name, 'manufactured/gui evidence: manifest.gui_mode is not '
                      'true', run=label, field='gui_mode', expected=True,
                      actual=manifest.get('gui_mode'))
    renderer = str(manifest.get('renderer') or '').lower()
    if 'directx' not in renderer:
        verifier.fail(name, 'renderer is not DirectX', run=label,
                      field='renderer', expected='DirectX', actual=renderer)
    command = str(manifest.get('command') or '')
    if '--headless' in command or 'headless=true' in command:
        verifier.fail(name, 'run command contains --headless', run=label,
                      field='command', expected='no --headless',
                      actual=command)
    evidence_payload = manifest.get('gui_evidence')
    if evidence_payload:
        verifier.ok(name, 'gui_evidence present for %s' % label)
    else:
        verifier.skip(name, 'gui_evidence missing')


# ---------------------------------------------------------------------------
# per-episode structural checks
# ---------------------------------------------------------------------------

def _check_episode_structure(evidence, episode, rows, ctx, verifier):
    name = 'episode_continuity'
    label = evidence.label
    episode_id = episode.get('episode_id')
    if not rows:
        return
    run_rows = [row for row in rows if row.get('phase') != 'POST_ABORT']
    last_run_index = max((index for index, row in enumerate(rows)
                          if row.get('phase') != 'POST_ABORT'), default=None)
    recorded_steps = episode.get('steps')
    decision_only = (
        isinstance(recorded_steps, int) and not isinstance(recorded_steps, bool)
        and run_rows and len(run_rows) == recorded_steps + 1
        and run_rows[-1].get('outcome') in OUTCOMES
        and (len(run_rows) == 1
             or run_rows[-2].get('outcome') in (None, 'RUNNING')))
    dt = ctx.get('dt')
    previous_time = None
    previous_step = None
    run_index = 0
    terminal_rows = 0
    previous_buffer = None
    states = set()
    for index, row in enumerate(rows):
        step = row.get('step')
        time_s = row.get('time_s')
        phase = row.get('phase')
        is_run = phase != 'POST_ABORT'
        if _num(time_s):
            if previous_time is not None:
                if time_s <= previous_time:
                    verifier.fail(name, 'time_s is not strictly increasing',
                                  run=label, episode_id=episode_id, step=step,
                                  field='time_s', expected='> %.6f'
                                  % previous_time, actual=time_s)
                elif dt is not None and abs((time_s - previous_time) - dt) > 1e-6:
                    verifier.fail(name, 'step time delta is not constant', run=label,
                                  episode_id=episode_id, step=step,
                                  field='time_s',
                                  expected='%.6f' % dt,
                                  actual=time_s - previous_time)
            previous_time = time_s
        if _num(step) and previous_step is not None and step != previous_step + 1:
            same_step_allowed = (
                step == previous_step
                and ((is_run and decision_only and index == last_run_index)
                     or (not is_run and index > 0
                         and rows[index - 1].get('phase') != 'POST_ABORT')))
            if not same_step_allowed:
                verifier.fail(name, 'step index is not contiguous', run=label,
                              episode_id=episode_id, step=step, field='step',
                              expected=previous_step + 1, actual=step)
        previous_step = step
        outcome = row.get('outcome')
        if is_run:
            if row.get('env_terminated'):
                verifier.fail(name, 'env terminated inside a RUN episode', run=label,
                              episode_id=episode_id, step=step,
                              field='env_terminated', expected=False,
                              actual=row.get('env_terminated'))
            if row.get('env_truncated'):
                verifier.fail(name, 'env truncated inside a RUN episode', run=label,
                              episode_id=episode_id, step=step,
                              field='env_truncated', expected=False,
                              actual=row.get('env_truncated'))
            if row.get('boundary_count_ok') is False:
                verifier.fail(name, 'undeclared episode boundary (boundary_count_ok'
                              ' false)', run=label, episode_id=episode_id,
                              step=step, field='boundary_count_ok',
                              expected=True, actual=False)
            buffer = row.get('episode_length_buf')
            if _num(buffer):
                decision_row = decision_only and index == last_run_index
                if buffer != run_index + 1 and not decision_row:
                    verifier.fail(name, 'episode_length_buf is not a clean per-'
                                  'episode count', run=label,
                                  episode_id=episode_id, step=step,
                                  field='episode_length_buf',
                                  expected=run_index + 1, actual=buffer)
                previous_buffer = buffer
            if outcome in OUTCOMES:
                terminal_rows += 1
                if index != last_run_index:
                    verifier.fail(name, 'terminal outcome appears before the last '
                                  'RUN row', run=label, episode_id=episode_id,
                                  step=step, field='outcome',
                                  expected='RUNNING', actual=outcome)
            elif outcome is not None and outcome != 'RUNNING':
                verifier.fail(name, 'unknown step outcome value', run=label,
                              episode_id=episode_id, step=step,
                              field='outcome', expected='RUNNING', actual=outcome)
            run_index += 1
            state = row.get('supervisor_state')
            if state:
                states.add(str(state))
        else:
            if outcome not in (None, 'RUNNING') and outcome != episode.get('outcome') \
                    and outcome not in OUTCOMES:
                verifier.fail(name, 'unknown POST_ABORT outcome value', run=label,
                              episode_id=episode_id, step=step,
                              field='outcome', expected='RUNNING',
                              actual=outcome)
            buffer = row.get('episode_length_buf')
            if _num(buffer) and _num(previous_buffer) and buffer < previous_buffer:
                verifier.fail(name, 'episode_length_buf decreased', run=label,
                              episode_id=episode_id, step=step,
                              field='episode_length_buf',
                              expected='>= %s' % previous_buffer, actual=buffer)
            if _num(buffer):
                previous_buffer = buffer
    episode_outcome = episode.get('outcome')
    if _num(recorded_steps) and len(run_rows) not in (
            recorded_steps, recorded_steps + 1):
        verifier.fail(name, 'episode.steps does not match RUN step rows', run=label,
                      episode_id=episode_id, field='steps',
                      expected=len(run_rows), actual=recorded_steps)
    elif decision_only:
        verifier.ok(name, 'decision-only terminal row tolerated for %s'
                    % episode_id)
    if dt is not None and _num(episode.get('duration_s')) \
            and _num(episode.get('steps')):
        expected_duration = episode.get('steps') * dt
        if abs(episode.get('duration_s') - expected_duration) > 1e-3:
            verifier.fail(name, 'episode.duration_s does not match steps*dt',
                          run=label, episode_id=episode_id, field='duration_s',
                          expected=expected_duration,
                          actual=episode.get('duration_s'))
    if run_rows:
        last = run_rows[-1]
        if episode_outcome in OUTCOMES:
            if terminal_rows != 1:
                verifier.fail(name, 'episode must have exactly one terminal step '
                              'classification', run=label,
                              episode_id=episode_id, field='outcome',
                              expected=1, actual=terminal_rows)
            if last.get('outcome') != episode_outcome:
                verifier.fail(name, 'final RUN step outcome does not match the '
                              'episode outcome', run=label,
                              episode_id=episode_id, step=last.get('step'),
                              field='outcome', expected=episode_outcome,
                              actual=last.get('outcome'))
            if last.get('reason') != episode.get('reason'):
                verifier.fail(name, 'final RUN step reason does not match the '
                              'episode reason', run=label,
                              episode_id=episode_id, step=last.get('step'),
                              field='reason', expected=episode.get('reason'),
                              actual=last.get('reason'))
    recorded_phases = episode.get('phase_summary')
    phases = Counter(row.get('phase') for row in rows)
    if isinstance(recorded_phases, dict):
        if {str(key): int(value) for key, value in recorded_phases.items()} \
                != {str(key): int(value) for key, value in phases.items()}:
            verifier.fail(name, 'episode.phase_summary does not match raw rows',
                          run=label, episode_id=episode_id,
                          field='phase_summary',
                          expected=dict(phases), actual=recorded_phases)
    return {'states': states, 'phase_counts': phases, 'run_rows': run_rows}


# ---------------------------------------------------------------------------
# per-episode clock checks
# ---------------------------------------------------------------------------

def _check_episode_clock(evidence, episode, rows, ctx, verifier, analysis):
    name = 'clock_domain_and_mapping'
    age_name = 'observation_age_and_queueing'
    label = evidence.label
    episode_id = episode.get('episode_id')
    clock_plan = ctx.get('clock_plan') or {}
    offset_ns = _ns_from_ms(clock_plan.get('offset_ms'))
    uncertainty_ns = _ns_from_ms(clock_plan.get('uncertainty_ms'))
    drift_ppm = _fnum(clock_plan.get('drift_ppm'))
    camera_id = clock_plan.get('camera_clock_id')
    obs_delay_ns = ctx.get('obs_delay_ns')
    case_obs_ns = ctx.get('case_obs_delay_ns') or 0
    previous_host = None
    for row in rows:
        clock = row.get('clock')
        if not isinstance(clock, dict):
            continue
        phase = row.get('phase')
        host = clock.get('host_now_ns')
        step = row.get('step')
        if _num(host):
            if previous_host is not None and host < previous_host:
                verifier.fail(name, 'host_now_ns is not monotonic', run=label,
                              episode_id=episode_id, step=step,
                              field='clock.host_now_ns',
                              expected='>= %s' % previous_host, actual=host)
            previous_host = host
            time_s = row.get('time_s')
            if _num(time_s):
                expected_host = round(float(time_s) * 1e9)
                if abs(host - expected_host) > HOST_NS_TOL:
                    verifier.fail(name, 'host_now_ns and time_s disagree',
                                  run=label, episode_id=episode_id, step=step,
                                  field='clock.host_now_ns',
                                  expected=expected_host, actual=host)
        if phase == 'POST_ABORT':
            # No new observation is produced after the business ABORT; only the
            # host clock/phase continuity is meaningful there.
            continue
        if camera_id and clock.get('camera_clock_id') not in (None, camera_id):
            verifier.fail(name, 'camera_clock_id does not match clock_plan',
                          run=label, episode_id=episode_id, step=step,
                          field='clock.camera_clock_id', expected=camera_id,
                          actual=clock.get('camera_clock_id'))
        usable = clock.get('mapping_usable')
        observation_valid = row.get('observation_valid')
        if isinstance(usable, bool):
            if observation_valid is not usable:
                verifier.fail(age_name, 'observation_valid must equal '
                              'mapping_usable', run=label,
                              episode_id=episode_id, step=step,
                              field='observation_valid', expected=usable,
                              actual=observation_valid)
            mapping_reason = clock.get('mapping_reason')
            if usable:
                if mapping_reason is not None and not str(mapping_reason) \
                        .startswith('ACCEPT'):
                    verifier.fail(name, 'usable mapping must record an ACCEPT '
                                  'reason', run=label, episode_id=episode_id,
                                  step=step, field='clock.mapping_reason',
                                  expected='ACCEPT', actual=mapping_reason)
            else:
                if mapping_reason != 'CLOCK_MAPPING_UNUSABLE':
                    verifier.fail(name, 'unusable mapping reason must be '
                                  'CLOCK_MAPPING_UNUSABLE', run=label,
                                  episode_id=episode_id, step=step,
                                  field='clock.mapping_reason',
                                  expected='CLOCK_MAPPING_UNUSABLE',
                                  actual=mapping_reason)
                if row.get('observation_reason') != 'CLOCK_MAPPING_UNUSABLE':
                    verifier.fail(name, 'unusable mapping must set observation_'
                                  'reason=CLOCK_MAPPING_UNUSABLE', run=label,
                                  episode_id=episode_id, step=step,
                                  field='observation_reason',
                                  expected='CLOCK_MAPPING_UNUSABLE',
                                  actual=row.get('observation_reason'))
                analysis['mapping_unusable'].append({
                    'episode_id': episode_id, 'step': step,
                    'mapping_reason': mapping_reason,
                    'observation_reason': row.get('observation_reason')})
        if usable is False:
            # While the camera mapping is unusable there is no meaningful
            # capture/age relation to recompute; the unusable-mapping evidence
            # itself is validated above.
            continue
        if offset_ns is None or uncertainty_ns is None or drift_ppm is None:
            continue
        capture_host = clock.get('capture_host_ns')
        capture_clock = clock.get('capture_clock_ns')
        if _num(host) and _num(capture_host) and obs_delay_ns is not None:
            expected_capture = max(0, host - obs_delay_ns - case_obs_ns)
            if abs(capture_host - expected_capture) > HOST_NS_TOL:
                verifier.fail(age_name, 'capture_host_ns does not reflect the '
                              'observation delay', run=label,
                              episode_id=episode_id, step=step,
                              field='clock.capture_host_ns',
                              expected=expected_capture, actual=capture_host)
        if not (_num(capture_host) and _num(capture_clock)):
            continue
        expected_clock = round(capture_host + offset_ns
                               + capture_host * drift_ppm / 1e6)
        if abs(capture_clock - expected_clock) > CLOCK_NS_TOL:
            verifier.fail(name, 'capture_clock_ns does not match the simulated '
                          'camera clock', run=label, episode_id=episode_id,
                          step=step, field='clock.capture_clock_ns',
                          expected=expected_clock, actual=capture_clock)
        mapped = clock.get('mapping_host_ns')
        if _num(mapped):
            expected_mapped = round((capture_clock - offset_ns)
                                    / (1.0 + drift_ppm / 1e6))
            if abs(mapped - expected_mapped) > CLOCK_NS_TOL:
                verifier.fail(name, 'mapping_host_ns is not the inverse mapping',
                              run=label, episode_id=episode_id, step=step,
                              field='clock.mapping_host_ns',
                              expected=expected_mapped, actual=mapped)
            if usable is False or not _num(host):
                continue
            recorded_error = clock.get('mapping_error_ns')
            expected_error = (abs(offset_ns) + uncertainty_ns
                              + math.ceil(abs(drift_ppm) * 1e-6 * abs(host)))
            if _num(recorded_error) and recorded_error != expected_error:
                verifier.fail(name, 'mapping_error_ns does not equal the '
                              'conservative mapping uncertainty', run=label,
                              episode_id=episode_id, step=step,
                              field='clock.mapping_error_ns',
                              expected=expected_error, actual=recorded_error)
            error_ns = expected_error if not _num(recorded_error) \
                else recorded_error
            raw_point = (host - mapped) / 1e9
            expected_point = max(0.0, raw_point)
            point = clock.get('age_point_s')
            bound = clock.get('age_bound_s')
            if _num(point) and abs(point - expected_point) > AGE_TOL_S:
                verifier.fail(age_name, 'age_point_s mismatch', run=label,
                              episode_id=episode_id, step=step,
                              field='clock.age_point_s',
                              expected=expected_point, actual=point)
            if _num(point) and _num(bound):
                if bound + 1e-9 < point:
                    verifier.fail(age_name, 'age_bound_s < age_point_s', run=label,
                                  episode_id=episode_id, step=step,
                                  field='clock.age_bound_s',
                                  expected='>= %.9f' % point, actual=bound)
                expected_bound = expected_point + error_ns / 1e9
                if abs(bound - expected_bound) > AGE_TOL_S:
                    verifier.fail(age_name, 'age_bound_s is not the conservative '
                                  'bound', run=label, episode_id=episode_id,
                                  step=step, field='clock.age_bound_s',
                                  expected=expected_bound, actual=bound)
                recorded_age = row.get('observation_age_s')
                if _num(recorded_age) and abs(recorded_age - bound) > 1e-9:
                    verifier.fail(age_name, 'observation_age_s must equal the '
                                  'conservative age_bound_s', run=label,
                                  episode_id=episode_id, step=step,
                                  field='observation_age_s',
                                  expected=bound, actual=recorded_age)
                if usable:
                    analysis['observation_bounds'].append(bound)
            elif usable:
                verifier.skip(age_name, 'age_point/age_bound not recorded')


# ---------------------------------------------------------------------------
# per-episode transport checks
# ---------------------------------------------------------------------------

def _check_applied(evidence, episode, row, active, ttl_s, host, verifier):
    name = 'applied_record_consistency'
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    transport = row.get('transport') or {}
    status = transport.get('status')
    applied = row.get('applied')
    if not isinstance(applied, dict):
        return
    if active is None and status != 'NONE':
        # No holder is active (it may have expired during this step); the applied
        # record must then be the documented zero fallback.
        for field in ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
                      'yaw_rate_ccw_world_radps'):
            if _num(applied.get(field)) and abs(applied.get(field)) > 1e-12:
                verifier.fail(name, 'no active setpoint but applied command is '
                              'non-zero', run=label, episode_id=episode_id,
                              step=step, field='applied.' + field,
                              expected=0.0, actual=applied.get(field))
        if applied.get('action_id') not in ('', None):
            verifier.fail(name, 'no active setpoint but applied.action_id is set',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.action_id', expected='',
                          actual=applied.get('action_id'))
        return
    is_held = applied.get('is_held')
    if status == 'NONE':
        for field in ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
                      'yaw_rate_ccw_world_radps'):
            if _num(applied.get(field)) and abs(applied.get(field)) > 1e-12:
                verifier.fail(name, 'no active setpoint but applied command is '
                              'non-zero', run=label, episode_id=episode_id,
                              step=step, field='applied.' + field,
                              expected=0.0, actual=applied.get(field))
        if applied.get('action_id') not in ('', None):
            verifier.fail(name, 'no active setpoint but applied.action_id is set',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.action_id', expected='',
                          actual=applied.get('action_id'))
        if is_held is not False:
            verifier.fail(name, 'no active setpoint but applied.is_held is not '
                          'false', run=label, episode_id=episode_id, step=step,
                          field='applied.is_held', expected=False,
                          actual=is_held)
        return
    if active is None:
        return
    if applied.get('action_id') != active.get('id'):
        verifier.fail(name, 'applied.action_id is not the active action', run=label,
                      episode_id=episode_id, step=step,
                      field='applied.action_id', expected=active.get('id'),
                      actual=applied.get('action_id'))
    if _num(applied.get('issued_at_ns')) and _num(active.get('issued')) \
            and applied.get('issued_at_ns') != active.get('issued'):
        verifier.fail(name, 'applied.issued_at_ns is not the active issue time',
                      run=label, episode_id=episode_id, step=step,
                      field='applied.issued_at_ns',
                      expected=active.get('issued'),
                      actual=applied.get('issued_at_ns'))
    if _num(applied.get('expires_at_ns')) and _num(active.get('expires')) \
            and applied.get('expires_at_ns') != active.get('expires'):
        verifier.fail(name, 'applied.expires_at_ns is not the active expiry',
                      run=label, episode_id=episode_id, step=step,
                      field='applied.expires_at_ns',
                      expected=active.get('expires'),
                      actual=applied.get('expires_at_ns'))
    if status == 'HOLDING':
        if is_held is not True:
            verifier.fail(name, 'HOLDING must record applied.is_held=true',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.is_held', expected=True,
                          actual=is_held)
    elif status in ('APPLIED', 'DIRECT'):
        if is_held is not False:
            verifier.fail(name, 'freshly applied setpoint must record '
                          'applied.is_held=false', run=label,
                          episode_id=episode_id, step=step,
                          field='applied.is_held', expected=False,
                          actual=is_held)
    age = _fnum(applied.get('age_s'))
    if age is not None and _num(host) and _num(active.get('issued')):
        expected_age = (host - active.get('issued')) / 1e9
        if abs(age - expected_age) > AGE_TOL_S:
            verifier.fail(name, 'applied.age_s is not the active setpoint age',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.age_s', expected=expected_age,
                          actual=age)
        if ttl_s is not None and age > ttl_s + 1e-9:
            verifier.fail(name, 'applied active setpoint outlives its TTL',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.age_s', expected='<= %.9f' % ttl_s,
                          actual=age)


def _check_episode_transport(evidence, episode, rows, ctx, verifier, analysis):
    name_ttl = 'ttl_no_renewal'
    name_arr = 'arrival_expiry_rejection'
    name_rej = 'rejection_never_executed'
    name_hold = 'hold_until_expiry_then_none'
    name_queue = 'observation_age_and_queueing'
    label = evidence.label
    episode_id = episode.get('episode_id')
    plan = ctx.get('plan') or {}
    ttl_ns = ctx.get('ttl_ns')
    ttl_s = (ttl_ns / 1e9) if ttl_ns is not None else None
    action_delay_ns = ctx.get('action_delay_ns')
    stall_step = plan.get('transport_stall_step')
    stall_active = isinstance(stall_step, int) and stall_step >= 0
    active = None
    rejected_ids = set()
    rejected_row_index = {}
    executed_ids = []
    executed_rows = []
    rejected_reasons = Counter()
    for row_index, row in enumerate(rows):
        transport = row.get('transport')
        if not isinstance(transport, dict):
            continue
        step = row.get('step')
        status = transport.get('status')
        executed = transport.get('executed')
        action_id = transport.get('action_id')
        executed_id = transport.get('executed_action_id')
        issued = transport.get('issued_at_ns')
        expires = transport.get('expires_at_ns')
        scheduled = transport.get('scheduled_arrival_ns')
        arrival = transport.get('arrival_ns')
        arrival_age = _fnum(transport.get('arrival_age_s'))
        dispatch = _fnum(transport.get('dispatch_delay_s'))
        reason = transport.get('reason')
        clock = row.get('clock') if isinstance(row.get('clock'), dict) else {}
        host = clock.get('host_now_ns')
        analysis['status_counts'][status] += 1
        if _num(issued) and _num(expires) and not (issued == 0 and expires == 0):
            delta = expires - issued
            analysis['ttl_deltas'].append(delta)
            if ttl_ns is not None and delta != ttl_ns:
                verifier.fail(name_ttl, 'expires_at_ns - issued_at_ns is not the '
                              'frozen TTL', run=label, episode_id=episode_id,
                              step=step, field='transport.expires_at_ns',
                              expected=ttl_ns, actual=delta)
        if status in ('APPLIED', 'HOLDING', 'REJECTED'):
            if _num(arrival) and _num(scheduled) and arrival < scheduled - 1:
                verifier.fail(name_arr, 'action arrives before its scheduled '
                              'dispatch time', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.arrival_ns', expected='>= %s'
                              % scheduled, actual=arrival)
            if _num(arrival) and _num(issued) and arrival_age is not None:
                expected_age = (arrival - issued) / 1e9
                if abs(arrival_age - expected_age) > 1e-9:
                    verifier.fail(name_arr, 'arrival_age_s is not '
                                  '(arrival_ns - issued_at_ns)/1e9', run=label,
                                  episode_id=episode_id, step=step,
                                  field='transport.arrival_age_s',
                                  expected=expected_age, actual=arrival_age)
            if _num(dispatch) and _num(scheduled) and _num(issued):
                if abs(dispatch - (scheduled - issued) / 1e9) > 1e-9:
                    verifier.fail(name_queue, 'dispatch_delay_s is not '
                                  '(scheduled_arrival_ns - issued_at_ns)/1e9',
                                  run=label, episode_id=episode_id, step=step,
                                  field='transport.dispatch_delay_s',
                                  expected=(scheduled - issued) / 1e9,
                                  actual=dispatch)
            if action_delay_ns is not None and status != 'DIRECT':
                on_stall = stall_active and _num(step) and step >= stall_step
                if not on_stall and _num(dispatch):
                    expected_delay = action_delay_ns / 1e9
                    if abs(dispatch - expected_delay) > 1e-6:
                        verifier.fail(name_queue, 'dispatch delay does not match '
                                      'the frozen action delay', run=label,
                                      episode_id=episode_id, step=step,
                                      field='transport.dispatch_delay_s',
                                      expected=expected_delay, actual=dispatch)
        if status == 'DIRECT':
            if executed is not True:
                verifier.fail(name_arr, 'DIRECT transport must execute the '
                              'setpoint', run=label, episode_id=episode_id,
                              step=step, field='transport.executed',
                              expected=True, actual=executed)
            if action_id != executed_id:
                verifier.fail(name_arr, 'DIRECT executed_action_id must equal '
                              'action_id', run=label, episode_id=episode_id,
                              step=step, field='transport.executed_action_id',
                              expected=action_id, actual=executed_id)
            if _num(arrival) and _num(issued) and arrival != issued:
                verifier.fail(name_arr, 'DIRECT arrival_ns must equal issued_at_ns',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.arrival_ns', expected=issued,
                              actual=arrival)
            if arrival_age is not None and abs(arrival_age) > 1e-9:
                verifier.fail(name_arr, 'DIRECT arrival age must be zero', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.arrival_age_s', expected=0.0,
                              actual=arrival_age)
            if _num(issued) and _num(expires):
                active = {'id': action_id, 'issued': issued,
                          'expires': expires}
                executed_ids.append(executed_id)
                executed_rows.append({'id': executed_id,
                                      'row_index': row_index})
        elif status == 'APPLIED':
            if executed is not True:
                verifier.fail(name_arr, 'APPLIED transport must execute the '
                              'setpoint', run=label, episode_id=episode_id,
                              step=step, field='transport.executed',
                              expected=True, actual=executed)
            accepted = {
                'episode_id': episode_id, 'step': step, 'status': status,
                'action_id': action_id, 'executed_action_id': executed_id,
                'arrival_age_s': arrival_age, 'ttl_s': ttl_s,
                'arrival_ns': arrival, 'scheduled_arrival_ns': scheduled,
                'issued_at_ns': issued, 'expires_at_ns': expires,
                'host_now_ns': host, 'phase': row.get('phase')}
            analysis['accepted'].append(accepted)
            if arrival_age is not None:
                analysis['arrival_ages'].append(arrival_age)
                if ttl_s is not None and arrival_age > ttl_s + 1e-9:
                    verifier.fail(name_arr, 'arrival was accepted although age >= '
                                  'TTL', run=label, episode_id=episode_id,
                                  step=step, field='transport.arrival_age_s',
                                  expected='< %.9f' % ttl_s, actual=arrival_age)
            if _num(issued) and _num(expires):
                active = {'id': action_id, 'issued': issued,
                          'expires': expires}
            executed_ids.append(executed_id)
            executed_rows.append({'id': executed_id, 'row_index': row_index})
            if executed_id in rejected_ids:
                verifier.fail(name_rej, 'a previously rejected action id was '
                              'executed', run=label, episode_id=episode_id,
                              step=step, field='transport.executed_action_id',
                              expected='not a rejected action id',
                              actual=executed_id)
        elif status == 'HOLDING':
            if executed is not True:
                verifier.fail(name_hold, 'HOLDING transport must execute the '
                              'active setpoint', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed', expected=True,
                              actual=executed)
            if active is None:
                verifier.fail(name_hold, 'HOLDING recorded without an active '
                              'setpoint', run=label, episode_id=episode_id,
                              step=step, field='transport.status',
                              expected='APPLIED/NONE', actual=status)
            else:
                if _num(host) and _num(active.get('expires')) \
                        and host >= active.get('expires'):
                    verifier.fail(name_hold, 'HOLDING setpoint is at/after its '
                                  'TTL expiry', run=label,
                                  episode_id=episode_id, step=step,
                                  field='clock.host_now_ns',
                                  expected='< %s' % active.get('expires'),
                                  actual=host)
                if executed_id != active.get('id'):
                    verifier.fail(name_hold, 'HOLDING executed_action_id is not '
                                  'the active action', run=label,
                                  episode_id=episode_id, step=step,
                                  field='transport.executed_action_id',
                                  expected=active.get('id'),
                                  actual=executed_id)
                if _num(issued) and _num(active.get('issued')) \
                        and issued != active.get('issued'):
                    verifier.fail(name_hold, 'HOLDING re-issued the active action '
                                  '(TTL renewal)', run=label,
                                  episode_id=episode_id, step=step,
                                  field='transport.issued_at_ns',
                                  expected=active.get('issued'), actual=issued)
                if _num(expires) and _num(active.get('expires')) \
                        and expires != active.get('expires'):
                    verifier.fail(name_hold, 'HOLDING extended the active expiry',
                                  run=label, episode_id=episode_id, step=step,
                                  field='transport.expires_at_ns',
                                  expected=active.get('expires'), actual=expires)
            executed_ids.append(executed_id)
            executed_rows.append({'id': executed_id, 'row_index': row_index})
            if executed_id in rejected_ids:
                verifier.fail(name_rej, 'a previously rejected action id was '
                              'executed', run=label, episode_id=episode_id,
                              step=step, field='transport.executed_action_id',
                              expected='not a rejected action id',
                              actual=executed_id)
        elif status == 'REJECTED':
            if executed is not False:
                verifier.fail(name_arr, 'REJECTED transport must not execute the '
                              'action', run=label, episode_id=episode_id,
                              step=step, field='transport.executed',
                              expected=False, actual=executed)
            if not reason:
                verifier.fail(name_arr, 'REJECTED transport must record a reason',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.reason', expected='reject reason',
                              actual=reason)
            if action_id and action_id == executed_id:
                verifier.fail(name_rej, 'rejected action id recorded as executed',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.executed_action_id',
                              expected='!= %s' % action_id, actual=executed_id)
            if action_id:
                rejected_ids.add(action_id)
                rejected_row_index.setdefault(action_id, row_index)
            rejected_reasons[str(reason)] += 1
            analysis['rejection_reasons'][str(reason)] += 1
            analysis['rejected'].append({
                'episode_id': episode_id, 'step': step, 'action_id': action_id,
                'reason': reason, 'arrival_age_s': arrival_age,
                'arrival_ns': arrival, 'scheduled_arrival_ns': scheduled,
                'issued_at_ns': issued, 'expires_at_ns': expires,
                'executed': executed, 'executed_action_id': executed_id,
                'host_now_ns': host, 'ttl_s': ttl_s,
                'row_index': row_index, 'origin': 'arrival',
                'phase': row.get('phase')})
            if reason == 'ACTION_EXPIRED' and arrival_age is not None \
                    and ttl_s is not None and arrival_age + 1e-9 < ttl_s:
                verifier.fail(name_arr, 'ACTION_EXPIRED rejection but arrival age '
                              'is below the TTL', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.arrival_age_s',
                              expected='>= %.9f' % ttl_s, actual=arrival_age)
        elif status == 'NONE':
            if executed is not False:
                verifier.fail(name_hold, 'NONE transport must not execute a '
                              'setpoint', run=label, episode_id=episode_id,
                              step=step, field='transport.executed',
                              expected=False, actual=executed)
            no_new_action = row.get('v2_admission') in (None, '', 'NO_NEW_ACTION')
            if active is not None:
                expired = (_num(host) and _num(active.get('expires'))
                           and host >= active.get('expires') - 1e-9)
                if expired:
                    active = None
                elif not no_new_action:
                    verifier.fail(name_hold, 'active setpoint dropped before its '
                                  'TTL expiry', run=label,
                                  episode_id=episode_id, step=step,
                                  field='transport.status', expected='HOLDING',
                                  actual='NONE')
        # Extra rejected arrivals recorded in the transport record for the same
        # step (several tickets can arrive/reject in one control tick).
        for extra in transport.get('rejections_this_step') or []:
            if not isinstance(extra, dict):
                continue
            extra_id = extra.get('action_id')
            extra_reason = extra.get('reason')
            extra_age = _fnum(extra.get('arrival_age_s'))
            analysis['rejection_reasons'][str(extra_reason)] += 1
            if extra_id:
                rejected_ids.add(extra_id)
                rejected_row_index.setdefault(extra_id, row_index)
            analysis['rejected'].append({
                'episode_id': episode_id, 'step': step, 'action_id': extra_id,
                'reason': extra_reason, 'arrival_age_s': extra_age,
                'arrival_ns': extra.get('arrival_ns'),
                'scheduled_arrival_ns': extra.get('scheduled_arrival_ns'),
                'executed': False, 'executed_action_id': executed_id,
                'host_now_ns': host, 'ttl_s': ttl_s,
                'row_index': row_index, 'origin': 'same_step',
                'phase': row.get('phase')})
            if extra_reason == 'ACTION_EXPIRED' and extra_age is not None \
                    and ttl_s is not None and extra_age + 1e-9 < ttl_s:
                verifier.fail(name_arr, 'ACTION_EXPIRED rejection but arrival age '
                              'is below the TTL', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.rejections_this_step',
                              expected='>= %.9f' % ttl_s, actual=extra_age)
        if executed_id and executed_id in rejected_ids:
            verifier.fail(name_rej, 'a previously rejected action id was executed',
                          run=label, episode_id=episode_id, step=step,
                          field='transport.executed_action_id',
                          expected='not a rejected action id', actual=executed_id)
        if active is not None and status == 'REJECTED' and _num(host) \
                and _num(active.get('expires')) \
                and host >= active['expires'] - 1e-9:
            # A rejected arrival does not keep an expired holder alive.
            active = None
        _check_applied(evidence, episode, row, active, ttl_s, host, verifier)
    distinct_executed = sorted({str(item) for item in executed_ids
                                if item not in (None, '')})
    rejected_rows = sum(1 for row in rows
                        if isinstance(row.get('transport'), dict)
                        and row['transport'].get('status') == 'REJECTED')
    return {
        'executed_action_count': len(distinct_executed),
        'arrival_rejection_count': rejected_rows,
        'arrival_reject_reasons': dict(rejected_reasons),
    }


# ---------------------------------------------------------------------------
# independent metric recomputation
# ---------------------------------------------------------------------------

def _row_geometry(row):
    position = row.get('position_world_m')
    obstacle = row.get('obstacle_position_world_m')
    if not (isinstance(position, (list, tuple)) and len(position) >= 3
            and isinstance(obstacle, (list, tuple)) and len(obstacle) >= 3):
        return None
    try:
        return math.dist([float(position[i]) for i in range(3)],
                         [float(obstacle[i]) for i in range(3)])
    except (TypeError, ValueError):
        return None


def _recompute_episode_metrics(evidence, episode, rows, ctx, verifier, analysis,
                               structure):
    label = evidence.label
    episode_id = episode.get('episode_id')
    dt = ctx.get('dt')
    plan = ctx.get('plan') or {}
    method = episode.get('method')
    run_rows = structure['run_rows']
    post_rows = [row for row in rows if row.get('phase') == 'POST_ABORT']
    times = []
    speeds = []
    positions = []
    velocities = []
    obstacle_velocities = []
    distances = []
    brake_index = None
    contact_max = 0.0
    contact_prim = ''
    for index, row in enumerate(run_rows):
        time_s = _fnum(row.get('time_s'))
        position = row.get('position_world_m')
        velocity = row.get('velocity_world_mps')
        speed = _fnum(row.get('speed_mps'))
        if speed is None and isinstance(velocity, (list, tuple)) \
                and len(velocity) >= 3:
            try:
                speed = math.sqrt(sum(float(velocity[i]) ** 2 for i in range(3)))
            except (TypeError, ValueError):
                speed = None
        if _num(time_s):
            times.append(time_s)
        else:
            times.append(None)
        speeds.append(speed)
        positions.append(list(position) if isinstance(position, (list, tuple))
                         else None)
        velocities.append(list(velocity) if isinstance(velocity, (list, tuple))
                          else None)
        obstacle_velocity = row.get('obstacle_velocity_world_mps')
        obstacle_velocities.append(
            list(obstacle_velocity)
            if isinstance(obstacle_velocity, (list, tuple)) else None)
        distance = _row_geometry(row)
        distances.append(distance)
        if brake_index is None and method == 'supervisor' \
                and row.get('supervisor_action') == 'STOP':
            brake_index = index
        force = _fnum(row.get('contact_force_n'))
        if force is not None and force > contact_max:
            contact_max = force
        prim = row.get('contact_prim')
        if prim and not contact_prim:
            contact_prim = str(prim)
    brake = None
    if brake_index is not None:
        row = run_rows[brake_index]
        brake = {
            'step': row.get('step'),
            'time_s': _fnum(row.get('time_s')),
            'position_world_m': positions[brake_index],
            'velocity_world_mps': velocities[brake_index],
            'speed_mps': speeds[brake_index],
            'supervisor_state': row.get('supervisor_state'),
            'observation_age_s': _fnum(row.get('observation_age_s')),
        }
    stop_distance = None
    stop_time = None
    if brake_index is not None and dt and dt > 0:
        window = max(1, int(round(STOP_HOLD_S / dt)))
        stop_index = None
        for index in range(brake_index, len(run_rows) - window + 1):
            window_speeds = speeds[index:index + window]
            if all(speed is not None and speed <= STOP_SPEED_MPS
                   for speed in window_speeds):
                stop_index = index + window - 1
                break
        if stop_index is not None:
            start_position = positions[brake_index]
            stop_position = positions[stop_index]
            if start_position is not None and stop_position is not None:
                direction = velocities[brake_index]
                if direction is not None and len(direction) >= 3:
                    norm = math.sqrt(sum(float(direction[i]) ** 2
                                         for i in range(3)))
                else:
                    norm = 0.0
                if norm > 1e-9:
                    delta = [float(stop_position[i]) - float(start_position[i])
                             for i in range(3)]
                    unit = [float(direction[i]) / norm for i in range(3)]
                    stop_distance = sum(delta[i] * unit[i] for i in range(3))
                elif len(start_position) >= 3:
                    stop_distance = math.dist(
                        [float(start_position[i]) for i in range(3)],
                        [float(stop_position[i]) for i in range(3)])
                if times[brake_index] is not None \
                        and times[stop_index] is not None:
                    stop_time = times[stop_index] - times[brake_index]
    min_distance = None
    min_distance_time = None
    for index, distance in enumerate(distances):
        if distance is None:
            continue
        if min_distance is None or distance < min_distance:
            min_distance = distance
            min_distance_time = times[index]
    max_closing = None
    for index in range(1, len(distances)):
        previous = distances[index - 1]
        current = distances[index]
        if previous is None or current is None:
            continue
        if times[index] is None or times[index - 1] is None:
            continue
        delta_t = times[index] - times[index - 1]
        if delta_t <= 0:
            continue
        closing = (previous - current) / delta_t
        if max_closing is None or closing > max_closing:
            max_closing = closing
    max_relative = None
    for index, velocity in enumerate(velocities):
        obstacle_velocity = obstacle_velocities[index]
        if velocity is None or obstacle_velocity is None:
            continue
        if len(velocity) < 3 or len(obstacle_velocity) < 3:
            continue
        relative = math.sqrt(sum((float(velocity[i])
                                  - float(obstacle_velocity[i])) ** 2
                                 for i in range(3)))
        if max_relative is None or relative > max_relative:
            max_relative = relative
    body_half = ctx.get('body_half_extents')
    obstacle = episode.get('obstacle') if isinstance(episode.get('obstacle'),
                                                     dict) else {}
    obstacle_size = obstacle.get('size_m')
    body_radius = None
    obstacle_radius = None
    envelope = None
    if isinstance(body_half, (list, tuple)) and len(body_half) >= 3 \
            and isinstance(obstacle_size, (list, tuple)) \
            and len(obstacle_size) >= 3:
        try:
            body_half_values = [float(body_half[i]) for i in range(3)]
            obstacle_half_values = [float(obstacle_size[i]) / 2.0
                                    for i in range(3)]
            body_radius = max(body_half_values)
            obstacle_radius = max(obstacle_half_values)
            envelope = {
                'body_half_extents_m': body_half_values,
                'obstacle_half_extents_m': obstacle_half_values,
                'body_radius_m': body_radius,
                'obstacle_radius_m': obstacle_radius,
            }
        except (TypeError, ValueError):
            envelope = None
    min_gap = None
    if min_distance is not None and body_radius is not None \
            and obstacle_radius is not None:
        min_gap = min_distance - (body_radius + obstacle_radius)
    final_speed = None
    if rows:
        final_speed = _fnum(rows[-1].get('speed_mps'))
    if final_speed is None and speeds:
        final_speed = speeds[-1]
    # POST_ABORT residual evidence.
    post_steps = len(post_rows)
    residual = 0.0
    time_to_stop = 0.0
    post_contact = False
    if post_rows:
        first = post_rows[0]
        last = post_rows[-1]
        first_position = first.get('position_world_m')
        last_position = last.get('position_world_m')
        if isinstance(first_position, (list, tuple)) \
                and isinstance(last_position, (list, tuple)) \
                and len(first_position) >= 3 and len(last_position) >= 3:
            try:
                residual = math.dist(
                    [float(first_position[i]) for i in range(3)],
                    [float(last_position[i]) for i in range(3)])
            except (TypeError, ValueError):
                residual = None
        post_speeds = [_fnum(row.get('speed_mps')) for row in post_rows]
        first_time = _fnum(first.get('time_s'))
        time_to_stop = None
        window = max(1, int(round(STOP_HOLD_S / dt))) if dt and dt > 0 else 1
        for index in range(0, len(post_rows) - window + 1):
            window_speeds = post_speeds[index:index + window]
            if all(speed is not None and speed <= STOP_SPEED_MPS
                   for speed in window_speeds):
                end_time = _fnum(post_rows[index + window - 1].get('time_s'))
                if first_time is not None and end_time is not None:
                    time_to_stop = end_time - first_time
                break
        post_contact = any(
            _fnum(row.get('contact_force_n')) is not None
            and _fnum(row.get('contact_force_n')) > CONTACT_FORCE_N
            for row in post_rows)
    return {
        'brake_start': brake,
        'initial_speed_mps': (brake or {}).get('speed_mps'),
        'stop_distance_m': stop_distance,
        'stop_time_s': stop_time,
        'stop_definition': ('speed<=0.08_mps_sustained_0.5s_'
                            'along_initial_speed_direction'),
        'final_speed_mps': final_speed,
        'min_center_distance_m': min_distance,
        'min_center_distance_time_s': min_distance_time,
        'min_envelope_gap_m': min_gap,
        'envelope': envelope,
        'max_closing_speed_mps': max_closing,
        'max_relative_speed_mps': max_relative,
        'contact_max_force_n': contact_max,
        'contact_prim': contact_prim,
        'executed_action_count': None,
        'arrival_rejection_count': None,
        'arrival_reject_reasons': None,
        'post_abort': {
            'steps': post_steps,
            'residual_distance_m': residual,
            'time_to_stop_s': time_to_stop,
            'contact': post_contact,
        },
        'phase_summary': {str(key): int(value)
                          for key, value in structure['phase_counts'].items()},
        'states': sorted(structure['states']),
        'outcome': episode.get('outcome'),
        'reason': episode.get('reason'),
    }


def _compare_episode_metrics(evidence, episode, recomputed, verifier):
    name = 'metrics_match_recorded'
    label = evidence.label
    episode_id = episode.get('episode_id')
    recorded = episode.get('metrics')
    if not isinstance(recorded, dict):
        return

    def mismatch(field, expected, actual, tolerance=None):
        verifier.fail(name, 'recorded metrics disagree with the independent '
                      'recompute', run=label, episode_id=episode_id,
                      field='metrics.' + field, expected=expected,
                      actual=actual)

    recorded_brake = recorded.get('brake_start')
    expected_brake = recomputed.get('brake_start')
    if recorded_brake is None and expected_brake is None:
        pass
    elif not isinstance(recorded_brake, dict) \
            or not isinstance(expected_brake, dict):
        mismatch('brake_start', expected_brake, recorded_brake)
    else:
        for field, tolerance in (('time_s', METRIC_TOL_TIME_S),
                                 ('speed_mps', METRIC_TOL_SPEED_MPS),
                                 ('observation_age_s', AGE_TOL_S)):
            if not _close(recorded_brake.get(field),
                          expected_brake.get(field), tolerance):
                mismatch('brake_start.' + field, expected_brake.get(field),
                         recorded_brake.get(field))
        for field in ('position_world_m', 'velocity_world_mps'):
            if not _vec_close(recorded_brake.get(field),
                              expected_brake.get(field),
                              METRIC_TOL_DIST_M,
                              len(expected_brake.get(field) or []) or 3):
                mismatch('brake_start.' + field, expected_brake.get(field),
                         recorded_brake.get(field))
        if recorded_brake.get('step') != expected_brake.get('step'):
            mismatch('brake_start.step', expected_brake.get('step'),
                     recorded_brake.get('step'))
        if recorded_brake.get('supervisor_state') \
                != expected_brake.get('supervisor_state'):
            mismatch('brake_start.supervisor_state',
                     expected_brake.get('supervisor_state'),
                     recorded_brake.get('supervisor_state'))
    numeric_fields = (
        ('initial_speed_mps', METRIC_TOL_SPEED_MPS),
        ('stop_distance_m', METRIC_TOL_DIST_M),
        ('stop_time_s', METRIC_TOL_TIME_S),
        ('final_speed_mps', METRIC_TOL_SPEED_MPS),
        ('min_center_distance_m', METRIC_TOL_DIST_M),
        ('min_center_distance_time_s', METRIC_TOL_TIME_S),
        ('min_envelope_gap_m', METRIC_TOL_DIST_M),
        ('max_closing_speed_mps', METRIC_TOL_SPEED_MPS),
        ('max_relative_speed_mps', METRIC_TOL_SPEED_MPS),
        ('contact_max_force_n', METRIC_TOL_FORCE_N),
    )
    for field, tolerance in numeric_fields:
        expected = recomputed.get(field)
        actual = recorded.get(field)
        if expected is None and actual is None:
            continue
        if not _close(actual, expected, tolerance):
            mismatch(field, expected, actual)
    if str(recorded.get('contact_prim') or '') \
            != str(recomputed.get('contact_prim') or ''):
        mismatch('contact_prim', recomputed.get('contact_prim'),
                 recorded.get('contact_prim'))
    for field in ('executed_action_count', 'arrival_rejection_count'):
        if recorded.get(field) != recomputed.get(field):
            mismatch(field, recomputed.get(field), recorded.get(field))
    recorded_reasons = recorded.get('arrival_reject_reasons')
    if isinstance(recorded_reasons, dict) or isinstance(
            recomputed.get('arrival_reject_reasons'), dict):
        left = {str(key): int(value) for key, value in
                (recorded_reasons or {}).items()} \
            if isinstance(recorded_reasons, dict) else recorded_reasons
        right = {str(key): int(value) for key, value in
                 (recomputed.get('arrival_reject_reasons') or {}).items()} \
            if isinstance(recomputed.get('arrival_reject_reasons'), dict) else None
        if left != right:
            mismatch('arrival_reject_reasons', right, left)
    recorded_envelope = recorded.get('envelope')
    expected_envelope = recomputed.get('envelope')
    if isinstance(recorded_envelope, dict) or isinstance(expected_envelope, dict):
        if not isinstance(recorded_envelope, dict) \
                or not isinstance(expected_envelope, dict):
            mismatch('envelope', expected_envelope, recorded_envelope)
        else:
            for field in ('body_half_extents_m', 'obstacle_half_extents_m'):
                if not _vec_close(recorded_envelope.get(field),
                                  expected_envelope.get(field), 1e-6):
                    mismatch('envelope.' + field, expected_envelope.get(field),
                             recorded_envelope.get(field))
            for field in ('body_radius_m', 'obstacle_radius_m'):
                if not _close(recorded_envelope.get(field),
                              expected_envelope.get(field), 1e-6):
                    mismatch('envelope.' + field, expected_envelope.get(field),
                             recorded_envelope.get(field))
    recorded_post = recorded.get('post_abort')
    expected_post = recomputed.get('post_abort')
    if isinstance(recorded_post, dict):
        if expected_post['steps'] == 0:
            pass
        else:
            if recorded_post.get('steps') != expected_post['steps']:
                mismatch('post_abort.steps', expected_post['steps'],
                         recorded_post.get('steps'))
            if not _equal_nullable(recorded_post.get('residual_distance_m'),
                                   expected_post['residual_distance_m'],
                                   METRIC_TOL_DIST_M):
                mismatch('post_abort.residual_distance_m',
                         expected_post['residual_distance_m'],
                         recorded_post.get('residual_distance_m'))
            if not _equal_nullable(recorded_post.get('time_to_stop_s'),
                                   expected_post['time_to_stop_s'],
                                   METRIC_TOL_TIME_S):
                mismatch('post_abort.time_to_stop_s',
                         expected_post['time_to_stop_s'],
                         recorded_post.get('time_to_stop_s'))
            if recorded_post.get('contact') is None \
                    and _num(recorded_post.get('contact_max_force_n')):
                recorded_contact = (recorded_post['contact_max_force_n']
                                    > CONTACT_FORCE_N)
            else:
                recorded_contact = recorded_post.get('contact')
            if recorded_contact is not None \
                    and bool(recorded_contact) != expected_post['contact']:
                mismatch('post_abort.contact', expected_post['contact'],
                         recorded_contact)
    recorded_phases = episode.get('phase_summary')
    if isinstance(recorded_phases, dict):
        left = {str(key): int(value) for key, value in recorded_phases.items()}
        if left != recomputed['phase_summary']:
            mismatch('phase_summary', recomputed['phase_summary'], left)
    if episode.get('method') == 'supervisor':
        recorded_definition = recorded.get('stop_definition')
        if recorded_definition in (None, ''):
            mismatch('stop_definition', recomputed['stop_definition'], None)


# ---------------------------------------------------------------------------
# run inspection
# ---------------------------------------------------------------------------

def _freeze_run_plan(freeze, config_id):
    if not isinstance(freeze, dict):
        return None
    for key in ('main_run_plans', 'run_plans'):
        node = freeze.get(key)
        if isinstance(node, dict):
            if isinstance(node.get(config_id), dict):
                return node[config_id]
            for value in node.values():
                if isinstance(value, dict) and value.get('config_id') == config_id:
                    return value
    configs = freeze.get('configs')
    if isinstance(configs, dict) and isinstance(configs.get(config_id), dict):
        value = configs[config_id]
        if isinstance(value.get('run_plan'), dict):
            return value['run_plan']
        if value.get('case_ids') is not None:
            return value
    return None


def _freeze_special_segment(freeze, segment_id):
    if not isinstance(freeze, dict):
        return None
    segments = freeze.get('special_segments')
    if isinstance(segments, list):
        for entry in segments:
            if isinstance(entry, dict) and entry.get('segment_id') == segment_id:
                return entry
    if isinstance(segments, dict) \
            and isinstance(segments.get(segment_id), dict):
        return segments[segment_id]
    return None


def _same_value(actual, expected):
    if _num(actual) and _num(expected):
        return abs(float(actual) - float(expected)) <= PLAN_TOL
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return _same_list_unordered(actual, expected)
    return actual == expected


def _compare_run_plan(evidence, freeze_plan, check_name, verifier, field_prefix):
    plan = evidence.manifest.get('latency_plan')
    if not isinstance(freeze_plan, dict) or not isinstance(plan, dict):
        return
    label = evidence.label
    for key in LATENCY_PLAN_KEYS:
        if key not in freeze_plan:
            continue
        expected = freeze_plan[key]
        actual = plan.get(key)
        if actual is None and expected is not None:
            verifier.missing.add(label, field_prefix + key, label)
            continue
        if not _same_value(actual, expected):
            verifier.fail(check_name, '%s does not match the frozen run plan'
                          % (field_prefix + key), run=label, field=field_prefix + key,
                          expected=expected, actual=actual)


def _compare_clock_plan(evidence, expected, check_name, verifier):
    actual = evidence.manifest.get('clock_plan')
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return
    label = evidence.label
    for key in CLOCK_PLAN_KEYS:
        if key not in expected:
            continue
        if not _same_value(actual.get(key), expected[key]):
            verifier.fail(check_name, 'clock_plan.%s does not match the freeze'
                          % key, run=label, field='clock_plan.' + key,
                          expected=expected[key], actual=actual.get(key))


def inspect_run(evidence, ctx, verifier):
    analysis = {
        'label': evidence.label, 'role': evidence.role,
        'run_dir': str(evidence.run_dir), 'loaded': evidence.loaded,
        'episode_count': len(evidence.episodes), 'episodes': {},
        'outcomes': Counter(), 'status_counts': Counter(),
        'rejection_reasons': Counter(), 'accepted': [], 'rejected': [],
        'mapping_unusable': [], 'ttl_deltas': [], 'arrival_ages': [],
        'observation_bounds': [], 'phase_counts': Counter(),
        'episode_ids': [], 'states': set(),
    }
    if not evidence.loaded:
        return analysis
    plan = evidence.manifest.get('latency_plan')
    clock_plan = evidence.manifest.get('clock_plan')
    plan = plan if isinstance(plan, dict) else {}
    clock_plan = clock_plan if isinstance(clock_plan, dict) else {}
    body = evidence.manifest.get('body_envelope')
    body = body if isinstance(body, dict) else {}
    run_ctx = {
        'plan': plan,
        'clock_plan': clock_plan,
        'ttl_ns': _ns_from_ms(plan.get('ttl_ms')),
        'action_delay_ns': _ns_from_s(plan.get('action_delay_s')),
        'obs_delay_ns': _ns_from_s(plan.get('obs_delay_s')),
        'body_half_extents': body.get('half_extents_m'),
    }
    seen = set()
    metrics_compared = 0
    episodes_with_brake = 0
    episodes_with_geometry = 0
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        episode_id = episode.get('episode_id')
        if episode_id in seen:
            verifier.fail('denominator_and_episode_ids', 'duplicate episode_id',
                          run=evidence.label, episode_id=episode_id,
                          field='episode_id', expected='unique', actual='duplicate')
        seen.add(episode_id)
        analysis['episode_ids'].append(episode_id)
        rows = evidence.steps_by_episode.get(episode_id, [])
        if not rows:
            verifier.missing.add(evidence.label,
                                 'steps[] for episode %s' % episode_id,
                                 'episode %s' % episode_id)
        obstacle = episode.get('obstacle')
        case_obs_delay = 0.0
        if isinstance(obstacle, dict) and _num(obstacle.get('observation_delay_s')):
            case_obs_delay = float(obstacle['observation_delay_s'])
        episode_ctx = dict(run_ctx)
        episode_ctx['case_obs_delay_ns'] = _ns_from_s(case_obs_delay)
        dt = _s_to_dt(rows)
        episode_ctx['dt'] = dt
        structure = _check_episode_structure(evidence, episode, rows, episode_ctx,
                                             verifier)
        _check_episode_clock(evidence, episode, rows, episode_ctx, verifier,
                             analysis)
        transport = _check_episode_transport(evidence, episode, rows,
                                             episode_ctx, verifier, analysis)
        recomputed = _recompute_episode_metrics(evidence, episode, rows,
                                                episode_ctx, verifier, analysis,
                                                structure or {
                                                    'run_rows': rows,
                                                    'states': set(),
                                                    'phase_counts': Counter()})
        recomputed['executed_action_count'] = transport['executed_action_count']
        recomputed['arrival_rejection_count'] = \
            transport['arrival_rejection_count']
        recomputed['arrival_reject_reasons'] = \
            transport['arrival_reject_reasons']
        analysis['episodes'][episode_id] = recomputed
        analysis['outcomes'][episode.get('outcome')] += 1
        analysis['phase_counts'].update(recomputed['phase_summary'])
        analysis['states'].update(recomputed['states'])
        _compare_episode_metrics(evidence, episode, recomputed, verifier)
        if isinstance(episode.get('metrics'), dict):
            metrics_compared += 1
        if recomputed.get('brake_start') is not None:
            episodes_with_brake += 1
        if recomputed.get('min_center_distance_m') is not None:
            episodes_with_geometry += 1
    if episodes_with_brake:
        verifier.ok('brake_start_and_stop_metrics',
                    '%d/%d episodes have a recomputed brake start'
                    % (episodes_with_brake, len(evidence.episodes)))
    if episodes_with_geometry:
        verifier.ok('geometry_contact_metrics',
                    '%d/%d episodes have recomputed geometry'
                    % (episodes_with_geometry, len(evidence.episodes)))
    if metrics_compared:
        verifier.ok('metrics_match_recorded',
                    '%d recorded metric blocks compared against the independent '
                    'recompute' % metrics_compared)
    if analysis['observation_bounds']:
        verifier.ok('clock_domain_and_mapping',
                    '%d clock rows recomputed' % len(analysis['observation_bounds']))
        verifier.ok('observation_age_and_queueing',
                    '%d observation ages recomputed'
                    % len(analysis['observation_bounds']))
    if analysis['ttl_deltas']:
        verifier.ok('ttl_no_renewal', '%d accepted-action TTL deltas checked'
                    % len(analysis['ttl_deltas']))
    if analysis['status_counts']:
        verifier.ok('arrival_expiry_rejection',
                    'transport statuses validated: %s'
                    % dict(analysis['status_counts']))
        verifier.ok('applied_record_consistency',
                    '%d applied records checked'
                    % sum(analysis['status_counts'].values()))
        verifier.ok_if_clean('hold_until_expiry_then_none',
                             'HOLDING/NONE invariants checked')
        verifier.ok_if_clean('rejection_never_executed',
                             'no rejected action id was executed')
    if analysis['episodes']:
        verifier.ok_if_clean('episode_continuity',
                             '%d episodes are step/time contiguous'
                             % len(analysis['episodes']))
    if evidence.manifest.get('gui_evidence'):
        verifier.ok('gui_evidence', 'gui_evidence present for ' + evidence.label)
    manifest_ids = evidence.manifest.get('episode_ids')
    if isinstance(manifest_ids, list):
        if len(set(map(str, manifest_ids))) != len(manifest_ids):
            verifier.fail('denominator_and_episode_ids',
                          'manifest.episode_ids contains duplicates',
                          run=evidence.label, field='episode_ids',
                          expected='unique', actual='duplicate')
        if sorted(map(str, manifest_ids)) != sorted(
                str(item) for item in seen if item is not None):
            verifier.fail('denominator_and_episode_ids',
                          'manifest.episode_ids does not match raw episodes',
                          run=evidence.label, field='episode_ids',
                          expected=sorted(map(str, manifest_ids)),
                          actual=sorted(str(item) for item in seen))
    verify_artifacts(evidence, ctx.get('freeze_path'), verifier)
    verify_gui(evidence, verifier)
    return analysis


# ---------------------------------------------------------------------------
# pair / special / expected checks
# ---------------------------------------------------------------------------

def _parse_expected_spec(value):
    if isinstance(value, str):
        label = value.strip()
        if label.upper() in OUTCOMES:
            return {'outcome': label.upper(), 'alternatives': [],
                    'reason_contains': None, 'classification': None,
                    'details': {}}
        return {'outcome': None, 'alternatives': [],
                'reason_contains': None, 'classification': label,
                'details': {}}
    if isinstance(value, dict):
        outcome = value.get('expected_outcome')
        if outcome is None:
            outcome = value.get('outcome')
        if isinstance(outcome, str) and outcome.strip().upper() in OUTCOMES:
            outcome = outcome.strip().upper()
        else:
            outcome = None
        alternatives = []
        for key in ('expected_outcome_alternatives', 'outcome_alternatives'):
            raw = value.get(key)
            if isinstance(raw, list):
                alternatives.extend(
                    item.strip().upper() for item in raw
                    if isinstance(item, str) and item.strip().upper() in OUTCOMES)
        reason = value.get('expected_reason_contains')
        if reason is None:
            reason = value.get('expected_reason')
        if reason is None:
            reason = value.get('reason')
        classification = value.get('classification')
        if classification is None:
            classification = value.get('expected_behavior')
        if classification is None:
            classification = value.get('behavior')
        if outcome is None and reason is None and classification is None:
            return None
        return {
            'outcome': outcome,
            'alternatives': alternatives,
            'reason_contains': reason if isinstance(reason, str) else None,
            'classification': classification
            if isinstance(classification, str) else None,
            'details': value,
        }
    return None


def _normalize_expected(node):
    """Return case_id -> expected spec (''*'' is a segment default)."""
    result = {}
    if node is None:
        return result
    if isinstance(node, str):
        spec = _parse_expected_spec(node)
        if spec:
            result['*'] = spec
        return result
    if isinstance(node, list):
        for item in node:
            if not isinstance(item, dict):
                continue
            case_id = item.get('case_id') or item.get('id')
            spec = _parse_expected_spec(item)
            if case_id and spec:
                result[str(case_id)] = spec
        return result
    if isinstance(node, dict):
        if any(key in node for key in EXPECTED_SPEC_KEYS):
            spec = _parse_expected_spec(node)
            nested = node.get('cases')
            if isinstance(nested, (dict, list)):
                result.update(_normalize_expected(nested))
            if spec:
                result.setdefault('*', spec)
            return result
        if isinstance(node.get('cases'), (dict, list)):
            return _normalize_expected(node.get('cases'))
        for key, value in node.items():
            if key in ('schema_version', 'evaluation_version', 'note', 'status',
                       'expected'):
                continue
            spec = _parse_expected_spec(value)
            if spec:
                result[str(key)] = spec
        return result
    return result


class ExpectedIndex:
    def __init__(self):
        self.cases = {}
        self.segments = {}

    def add_freeze(self, freeze):
        if not isinstance(freeze, dict):
            return
        evaluation = freeze.get('evaluation')
        if isinstance(evaluation, dict):
            expected = evaluation.get('expected')
            if isinstance(expected, dict) and isinstance(expected.get('main'),
                                                         dict):
                for config_cases in expected['main'].values():
                    self.cases.update(_normalize_expected(config_cases))
                special = expected.get('special')
                if isinstance(special, dict):
                    for segment_id, node in special.items():
                        self.segments.setdefault(str(segment_id), {}) \
                            .update(_normalize_expected(node))
            else:
                self.cases.update(_normalize_expected(expected))
        segments = freeze.get('special_segments')
        if isinstance(segments, list):
            for entry in segments:
                if isinstance(entry, dict) and entry.get('segment_id'):
                    self.segments.setdefault(str(entry['segment_id']), {}) \
                        .update(_normalize_expected(entry.get('expected')))
        elif isinstance(segments, dict):
            for segment_id, entry in segments.items():
                if isinstance(entry, dict):
                    self.segments.setdefault(str(segment_id), {}) \
                        .update(_normalize_expected(entry.get('expected')))

    def add_config(self, payload):
        if not isinstance(payload, dict):
            return
        self.cases.update(_normalize_expected(
            payload.get('cases') or payload.get('expected_cases')))
        segments = payload.get('segments')
        if segments is None:
            segments = payload.get('special_segments')
        if isinstance(segments, dict):
            for segment_id, entry in segments.items():
                self.segments.setdefault(str(segment_id), {}) \
                    .update(_normalize_expected(entry))
        elif isinstance(segments, list):
            for entry in segments:
                if isinstance(entry, dict) and entry.get('segment_id'):
                    self.segments.setdefault(str(entry['segment_id']), {}) \
                        .update(_normalize_expected(entry.get('expected')
                                                    or entry))

    def lookup(self, segment_id, case_id):
        def _merge(specs, key):
            if not isinstance(specs, dict):
                return None
            base = specs.get('*')
            specific = specs.get(str(key)) if key is not None else None
            if specific is None:
                return base
            if isinstance(base, dict) and isinstance(specific, dict):
                merged = dict(base)
                merged.update(specific)
                if not merged.get('alternatives') and base.get('alternatives'):
                    merged['alternatives'] = list(base['alternatives'])
                return merged
            return specific

        if segment_id and segment_id in self.segments:
            found = _merge(self.segments[segment_id], case_id)
            if found is not None:
                return found
        return _merge(self.cases, case_id)

    def summary(self):
        return {'cases': len(self.cases),
                'segments': {key: len(value)
                             for key, value in self.segments.items()}}


def verify_expected_run(evidence, analysis, expected_index, verifier):
    name = 'expected_classification'
    plan = evidence.manifest.get('latency_plan')
    segment_id = plan.get('segment_id') if isinstance(plan, dict) else ''
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        case_id = episode.get('case_id')
        episode_id = episode.get('episode_id')
        spec = expected_index.lookup(segment_id, case_id)
        if spec is None:
            verifier.missing.add(evidence.label,
                                 'expected classification for case %s'
                                 % case_id, 'episode %s' % episode_id)
            continue
        outcome = episode.get('outcome')
        allowed = set(spec.get('alternatives') or [])
        if spec.get('outcome') and outcome != spec['outcome'] \
                and outcome not in allowed:
            verifier.fail(name, 'case outcome does not match the pre-frozen '
                          'expected classification', run=evidence.label,
                          episode_id=episode_id, field='outcome',
                          expected=[spec['outcome']] + sorted(allowed),
                          actual=outcome)
        else:
            verifier.ok(name, 'expected classification matched for %s'
                        % episode_id)
        reason = str(episode.get('reason') or '')
        if spec.get('reason_contains') \
                and spec['reason_contains'] not in reason:
            verifier.fail(name, 'case reason does not contain the pre-frozen '
                          'expected reason', run=evidence.label,
                          episode_id=episode_id, field='reason',
                          expected=spec['reason_contains'], actual=reason)


def verify_pair(evidence_a, evidence_b, analysis_a, analysis_b, freeze,
                verifier):
    name = 'pair_consistency'
    denom = 'denominator_and_episode_ids'
    if evidence_a is None or evidence_b is None:
        if evidence_a is None:
            verifier.missing.add('pair', 'run_a directory', 'main_A')
        if evidence_b is None:
            verifier.missing.add('pair', 'run_b directory', 'main_B')
        return
    label = evidence_a.label + '/' + evidence_b.label
    plan_a = evidence_a.manifest.get('latency_plan')
    plan_b = evidence_b.manifest.get('latency_plan')
    plan_a = plan_a if isinstance(plan_a, dict) else {}
    plan_b = plan_b if isinstance(plan_b, dict) else {}
    config_a = plan_a.get('config_id')
    config_b = plan_b.get('config_id')
    # Frozen run plans must match the recorded plans.
    freeze_plan_a = _freeze_run_plan(freeze, config_a) if freeze else None
    freeze_plan_b = _freeze_run_plan(freeze, config_b) if freeze else None
    if freeze is not None:
        if freeze_plan_a is None:
            verifier.missing.add('pair', 'freeze.main_run_plans[%s]' % config_a,
                                 evidence_a.label)
        else:
            _compare_run_plan(evidence_a, freeze_plan_a, name, verifier,
                              'latency_plan.')
        if freeze_plan_b is None:
            verifier.missing.add('pair', 'freeze.main_run_plans[%s]' % config_b,
                                 evidence_b.label)
        else:
            _compare_run_plan(evidence_b, freeze_plan_b, name, verifier,
                              'latency_plan.')
        _compare_clock_plan(evidence_a, freeze.get('clock_plan'), name, verifier)
        _compare_clock_plan(evidence_b, freeze.get('clock_plan'), name, verifier)
        for key in ('map_asset_id', 'terrain_sha256', 'preview_sha256',
                    'map_config_sha256', 'cases_sha256'):
            if freeze.get(key) is None:
                verifier.missing.add('freeze', key, 'pair freeze')
                continue
            for evidence in (evidence_a, evidence_b):
                if evidence.manifest.get(key) != freeze.get(key):
                    verifier.fail(name, 'run %s does not match the freeze'
                                  % key, run=evidence.label, field=key,
                                  expected=freeze.get(key),
                                  actual=evidence.manifest.get(key))
    # A/B must differ only by the stop distance.
    keys = (set(plan_a) | set(plan_b)) - PAIR_NON_STOP_KEYS
    for key in sorted(keys):
        value_a = plan_a.get(key)
        value_b = plan_b.get(key)
        if value_a is None and value_b is None:
            continue
        if not _same_value(value_a, value_b):
            verifier.fail(name, 'A/B latency plans differ on a field that must be '
                          'identical', run=label, field=key, expected=value_b,
                          actual=value_a)
    clock_a = evidence_a.manifest.get('clock_plan')
    clock_b = evidence_b.manifest.get('clock_plan')
    if isinstance(clock_a, dict) and isinstance(clock_b, dict):
        for key in CLOCK_PLAN_KEYS:
            if not _same_value(clock_a.get(key), clock_b.get(key)):
                verifier.fail(name, 'A/B clock plans differ', run=label,
                              field='clock_plan.' + key,
                              expected=clock_b.get(key), actual=clock_a.get(key))
    # Case sets and denominators.
    def case_ids(evidence):
        return [episode.get('case_id') for episode in evidence.episodes
                if isinstance(episode, dict)]
    cases_a = case_ids(evidence_a)
    cases_b = case_ids(evidence_b)
    if sorted(cases_a) != sorted(cases_b):
        verifier.fail(name, 'A/B case sets differ', run=label, field='case_ids',
                      expected=sorted(cases_b), actual=sorted(cases_a))
    for evidence, cases in ((evidence_a, cases_a), (evidence_b, cases_b)):
        if len(set(cases)) != len(cases):
            verifier.fail(denom, 'run must contain each case exactly once',
                          run=evidence.label, field='case_ids',
                          expected='unique', actual=cases)
    expected_count = None
    if isinstance(freeze, dict):
        case_ids_freeze = freeze.get('case_ids')
        if not (isinstance(case_ids_freeze, list) and case_ids_freeze):
            for run_plan in (freeze_plan_a, freeze_plan_b):
                if isinstance(run_plan, dict) \
                        and isinstance(run_plan.get('case_ids'), list) \
                        and run_plan['case_ids']:
                    case_ids_freeze = run_plan['case_ids']
                    break
        if isinstance(case_ids_freeze, list) and case_ids_freeze:
            expected_count = len(case_ids_freeze)
            for evidence, cases in ((evidence_a, cases_a),
                                    (evidence_b, cases_b)):
                if sorted(str(item) for item in cases) \
                        != sorted(str(item) for item in case_ids_freeze):
                    verifier.fail(name, 'run cases do not match the frozen case '
                                  'list', run=evidence.label, field='case_ids',
                                  expected=sorted(case_ids_freeze),
                                  actual=sorted(map(str, cases)))
            if _num(freeze.get('episodes_per_config')):
                expected_count = int(freeze['episodes_per_config'])
        if _num(freeze.get('total_episodes')):
            total = freeze['total_episodes']
            actual_total = len(cases_a) + len(cases_b)
            if actual_total != int(total):
                verifier.missing.add('pair', 'denominator %d/%d episodes'
                                     % (actual_total, int(total)), 'pair')
    for evidence, cases in ((evidence_a, cases_a), (evidence_b, cases_b)):
        if expected_count is not None and len(cases) != expected_count:
            verifier.missing.add(evidence.label,
                                 'denominator %d/%d episodes'
                                 % (len(cases), expected_count),
                                 evidence.label)
        verifier.ok(denom, '%s %d/%s episodes' % (
            evidence.label, len(cases), expected_count if expected_count
            else '?'))
    # Frozen stop distances.
    if isinstance(freeze, dict) and isinstance(freeze.get('configs'), dict):
        for config_id, evidence, plan in ((config_a, evidence_a, plan_a),
                                          (config_b, evidence_b, plan_b)):
            config = freeze['configs'].get(config_id)
            if not isinstance(config, dict):
                verifier.missing.add('pair', 'freeze.configs[%s]' % config_id,
                                     evidence.label)
                continue
            expected_stop = config.get('stop_distance_m')
            if not _num(expected_stop):
                verifier.missing.add('pair',
                                     'freeze.configs[%s].stop_distance_m'
                                     % config_id, evidence.label)
            elif not _close(plan.get('stop_distance_m'), expected_stop,
                            PLAN_TOL):
                verifier.fail(name, 'recorded stop distance does not match the '
                              'frozen config', run=evidence.label,
                              field='stop_distance_m', expected=expected_stop,
                              actual=plan.get('stop_distance_m'))
    stop_a = plan_a.get('stop_distance_m')
    stop_b = plan_b.get('stop_distance_m')
    if _num(stop_a) and _num(stop_b) and abs(stop_a - stop_b) <= 1e-9:
        verifier.fail(name, 'A/B stop distances are identical', run=label,
                      field='stop_distance_m', expected='different',
                      actual=stop_a)
    # Episode ids must be unique across the pair when config ids differ.
    ids_a = set(map(str, analysis_a.get('episode_ids') or []))
    ids_b = set(map(str, analysis_b.get('episode_ids') or []))
    if config_a != config_b and ids_a & ids_b:
        verifier.fail(denom, 'episode_id collision across configs', run=label,
                      field='episode_id', expected='unique',
                      actual=sorted(ids_a & ids_b))
    verifier.ok_if_clean(name, 'A/B plans, clock plans, case sets and frozen stop '
                         'distances are consistent (only stop differs)')
    verifier.ok_if_clean(denom, 'episode ids unique across the pair')


def _segment_kind(segment_id, plan):
    text = str(segment_id or '').lower()
    if 'ttl_near' in text:
        return 'ttl_near'
    if 'ttl_over' in text:
        return 'ttl_over'
    if 'clock_sync' in text:
        return 'clock_sync'
    if 'clock_mapping' in text:
        return 'clock_mapping'
    if 'regression' in text:
        return 'regression'
    return 'generic'


def _rows_after(rows, step):
    for index, row in enumerate(rows):
        if row.get('step') == step:
            return rows[index + 1:]
    return []


def _evidence_after(rows, step, status, require_zero=False):
    found = []
    for row in _rows_after(rows, step):
        transport = row.get('transport')
        if not isinstance(transport, dict) or transport.get('status') != status:
            continue
        applied = row.get('applied') if isinstance(row.get('applied'), dict) else {}
        if require_zero:
            values = [applied.get('vx_forward_mps'),
                      applied.get('vy_left_mps'),
                      applied.get('vz_up_mps'),
                      applied.get('yaw_rate_ccw_world_radps')]
            if not all(_num(value) and abs(value) <= 1e-12 for value in values):
                continue
            if applied.get('action_id') not in ('', None):
                continue
            if applied.get('is_held') is not False:
                continue
        found.append(row)
    return found


def _row_applied_info(row):
    """Return the executed-setpoint record of a step row.

    The runner records the applied setpoint both at the top level (``applied``)
    and nested inside the transport record (``transport.applied``); a rejected
    arrival keeps the old setpoint in the nested copy.  Prefer the top-level
    record but fall back to the transport copy.
    """
    applied = row.get('applied')
    transport = row.get('transport')
    nested = transport.get('applied') if isinstance(transport, dict) else None
    if isinstance(applied, dict) and applied.get('action_id'):
        return applied
    if isinstance(nested, dict) and nested.get('action_id'):
        return nested
    if isinstance(applied, dict):
        return applied
    if isinstance(nested, dict):
        return nested
    return {}


def _applied_is_zero(applied):
    if not isinstance(applied, dict):
        return True
    values = [applied.get('vx_forward_mps'), applied.get('vy_left_mps'),
              applied.get('vz_up_mps'),
              applied.get('yaw_rate_ccw_world_radps')]
    if not all(_num(value) and abs(value) <= 1e-12 for value in values):
        return False
    if applied.get('action_id') not in ('', None):
        return False
    if applied.get('is_held') not in (None, False):
        return False
    return True


def _expected_details(freeze_entry, expected_index, segment_id):
    details = {}
    if isinstance(freeze_entry, dict) \
            and isinstance(freeze_entry.get('expected'), dict):
        details.update(freeze_entry['expected'])
    if expected_index is not None:
        specs = expected_index.segments.get(str(segment_id))
        if isinstance(specs, dict):
            spec = specs.get('*')
            if isinstance(spec, dict) and isinstance(spec.get('details'), dict):
                for key, value in spec['details'].items():
                    details.setdefault(key, value)
    return details


def _rejection_evidence(evidence, analysis, reasons):
    wanted = {str(item) for item in reasons if item}
    found = []
    for item in analysis.get('rejected') or []:
        if str(item.get('reason')) in wanted:
            found.append(dict(item))
    for episode_id, rows in evidence.steps_by_episode.items():
        for row in rows:
            reason = str(row.get('v2_reject_reason') or '')
            if row.get('v2_admission') == 'REJECTED' and reason in wanted:
                found.append({
                    'episode_id': episode_id, 'step': row.get('step'),
                    'action_id': row.get('v2_action_id'), 'reason': reason,
                    'origin': 'admission', 'executed': False,
                    'arrival_age_s': None, 'row': row})
    return found


def _check_segment(segment_id, evidence, analysis, freeze_entry, expected_index,
                   verifier):
    label = evidence.label
    plan = evidence.manifest.get('latency_plan')
    plan = plan if isinstance(plan, dict) else {}
    kind = _segment_kind(segment_id, plan)
    ttl_ns = _ns_from_ms(plan.get('ttl_ms'))
    ttl_s = ttl_ns / 1e9 if ttl_ns else None
    accepted = analysis.get('accepted') or []
    rejected = analysis.get('rejected') or []
    detail = '%s kind=%s' % (segment_id, kind)
    details = _expected_details(freeze_entry, expected_index, segment_id)
    if kind == 'ttl_near':
        expected_age = _fnum(details.get('arrival_accept_age_s'))
        expected_margin = _fnum(details.get('ttl_margin_s'))
        matches = [item for item in accepted
                   if item.get('arrival_age_s') is not None
                   and abs(item['arrival_age_s'] - (expected_age or 0.1)) <= 0.005]
        if ttl_s is None:
            verifier.missing.add(label, 'latency_plan.ttl_ms', label)
        elif not matches:
            verifier.fail('special_segments', 'ttl_near: no accepted arrival close '
                          'to the frozen near-TTL age', run=label,
                          field='transport.arrival_age_s',
                          expected='%.4f +- 0.005' % (expected_age or 0.1),
                          actual=[item.get('arrival_age_s')
                                  for item in accepted[:10]])
        else:
            ages = [item['arrival_age_s'] for item in matches]
            best = min(ages, key=lambda age: abs(age - (expected_age or 0.1)))
            margin = ttl_s - best
            verifier.ok('special_segments',
                        'ttl_near: accepted age=%.4fs ttl=%.3fs margin=%.4fs'
                        % (best, ttl_s, margin))
            if margin < -1e-9:
                verifier.fail('special_segments', 'ttl_near: accepted arrival age '
                              'exceeds the TTL', run=label,
                              field='transport.arrival_age_s',
                              expected='< %.3f' % ttl_s, actual=best)
            if expected_margin is not None \
                    and abs(margin - expected_margin) > 1e-3:
                verifier.fail('special_segments', 'ttl_near: TTL margin does not '
                              'match the frozen expectation', run=label,
                              field='ttl_margin_s', expected=expected_margin,
                              actual=margin)
    elif kind == 'ttl_over':
        expected_reason = str(details.get('arrival_reject_reason')
                              or 'ACTION_EXPIRED')
        expired = [item for item in rejected
                   if str(item.get('reason')) in {expected_reason,
                                                  'ACTION_EXPIRED'}]
        if not expired:
            verifier.fail('special_segments', 'ttl_over: no expired-arrival '
                          'rejection recorded', run=label,
                          field='transport.reason', expected=expected_reason,
                          actual=sorted({str(item.get('reason'))
                                         for item in rejected}))
        else:
            item = expired[0]
            age = item.get('arrival_age_s')
            if ttl_s is not None and (age is None or age + 1e-9 < ttl_s):
                verifier.fail('special_segments', 'ttl_over: expired rejection '
                              'arrival age is below the TTL', run=label,
                              episode_id=item.get('episode_id'),
                              step=item.get('step'),
                              field='transport.arrival_age_s',
                              expected='>= %.3f' % ttl_s, actual=age)
            if item.get('executed') is not False:
                verifier.fail('special_segments', 'ttl_over: expired arrival was '
                              'executed', run=label,
                              episode_id=item.get('episode_id'),
                              step=item.get('step'), field='transport.executed',
                              expected=False, actual=item.get('executed'))
            rows = evidence.steps_by_episode.get(item.get('episode_id'), [])
            start = item.get('row_index')
            if not isinstance(start, int):
                start = next((index for index, row in enumerate(rows)
                              if row.get('step') == item.get('step')), 0)
            run_residual = False
            run_applied = {}
            post_residual = False
            fallback = False
            executed_after = False
            for row in rows[max(0, start):]:
                transport = row.get('transport')
                transport = transport if isinstance(transport, dict) else {}
                applied = _row_applied_info(row)
                phase = row.get('phase')
                if transport.get('status') == 'HOLDING':
                    if phase == 'POST_ABORT':
                        post_residual = True
                    else:
                        run_residual = True
                if applied.get('action_id'):
                    if phase == 'POST_ABORT':
                        post_residual = True
                    else:
                        run_residual = True
                        if not run_applied:
                            run_applied = applied
                if transport.get('status') == 'NONE' \
                        and _applied_is_zero(applied):
                    fallback = True
                if transport.get('executed') and item.get('action_id') \
                        and transport.get('executed_action_id') \
                        == item.get('action_id'):
                    executed_after = True
            residual = run_residual or post_residual
            if not residual:
                verifier.fail('special_segments', 'ttl_over: no residual old '
                              'setpoint record at the rejection row or in the '
                              'POST_ABORT window', run=label,
                              episode_id=item.get('episode_id'),
                              field='applied.action_id',
                              expected='old active setpoint record',
                              actual='absent')
            if not fallback:
                verifier.fail('special_segments', 'ttl_over: no zero-target '
                              'fallback after the expired setpoint', run=label,
                              episode_id=item.get('episode_id'),
                              field='transport.status', expected='NONE + zero '
                              'applied', actual='absent')
            if executed_after:
                verifier.fail('special_segments', 'ttl_over: the expired brake '
                              'command was executed after its rejection',
                              run=label, episode_id=item.get('episode_id'),
                              field='transport.executed_action_id',
                              expected='rejected action never executed',
                              actual=item.get('action_id'))
            if residual and fallback and not executed_after:
                where = 'POST_ABORT' if post_residual else 'RUN_REJECTION'
                age_s = run_applied.get('age_s')
                held = run_applied.get('is_held')
                verifier.ok('special_segments', 'ttl_over: expired brake command '
                            'rejected (age=%s); residual old setpoint in %s'
                            ' (applied.action_id=%s age_s=%s is_held=%s); '
                            'zero-target fallback present'
                            % (round(age, 4) if age is not None else age, where,
                               run_applied.get('action_id'), age_s, held))
    elif kind == 'clock_sync':
        reasons = {details.get('inflight_arrival_reject_reason'),
                   details.get('admission_reject_reason'),
                   'REJECT_SYNC_OR_PX4_BOOT'}
        items = _rejection_evidence(evidence, analysis, reasons)
        arrival_items = [item for item in items
                         if item.get('origin') in ('arrival', 'same_step')]
        admission_items = [item for item in items
                           if item.get('origin') == 'admission']
        if not items:
            verifier.fail('special_segments', 'clock_sync: no sync-generation '
                          'rejection recorded', run=label,
                          field='transport.reason',
                          expected='REJECT_SYNC_OR_PX4_BOOT',
                          actual=sorted({str(item.get('reason'))
                                         for item in rejected}))
        else:
            item = (arrival_items or admission_items)[0]
            age = item.get('arrival_age_s')
            if arrival_items:
                if ttl_s is not None and age is not None and age > ttl_s + 1e-9:
                    verifier.fail('special_segments', 'clock_sync: rejection '
                                  'looks like a TTL expiry, not an in-flight '
                                  'sync failure', run=label,
                                  episode_id=item.get('episode_id'),
                                  field='transport.arrival_age_s',
                                  expected='<= %.3f' % ttl_s, actual=age)
            elif not admission_items:
                verifier.fail('special_segments', 'clock_sync: no in-flight '
                              'arrival rejection recorded', run=label,
                              field='transport.status', expected='arrival '
                              'rejection', actual='absent')
            verifier.ok('special_segments', 'clock_sync: sync rejection '
                        'recorded (origin=%s age=%s)'
                        % (item.get('origin'),
                           round(age, 4) if age is not None else age))
    elif kind == 'clock_mapping':
        expected_reason = str(details.get('observation_reason')
                              or 'CLOCK_MAPPING_UNUSABLE')
        unusable = [item for item in (analysis.get('mapping_unusable') or [])
                    if str(item.get('mapping_reason')) == expected_reason]
        if not unusable:
            verifier.fail('special_segments', 'clock_mapping: no observation with '
                          '%s recorded' % expected_reason, run=label,
                          field='clock.mapping_reason',
                          expected=expected_reason, actual='absent')
        else:
            verifier.ok('special_segments', 'clock_mapping: %d unusable-mapping '
                        'observation steps' % len(unusable))
        states = set(analysis.get('states') or [])
        if 'DEGRADED' not in states:
            verifier.fail('special_segments', 'clock_mapping: supervisor never '
                          'entered DEGRADED', run=label,
                          field='supervisor_state', expected='DEGRADED',
                          actual=sorted(states))
        if 'ABORT' not in set(analysis.get('outcomes') or {}) \
                and 'ABORT' not in states:
            verifier.fail('special_segments', 'clock_mapping: episode never '
                          'ABORTed', run=label, field='outcome',
                          expected='ABORT', actual=sorted(
                              set(analysis.get('outcomes') or {})))
        stale_reasons = {details.get('admission_reject_reason'),
                         details.get('arrival_reject_reason'),
                         'ACTION_EXPIRED', 'REJECT_OBSERVATION_STALE',
                         'REJECT_STALE_OBSERVATION', 'OBSERVATION_STALE'}
        stale = _rejection_evidence(evidence, analysis, stale_reasons)
        if not stale:
            verifier.fail('special_segments', 'clock_mapping: no action rejected '
                          'because its observation was stale/unusable', run=label,
                          field='transport.reason', expected='stale-observation '
                          'rejection', actual=sorted({str(item.get('reason'))
                                                      for item in rejected}))
        else:
            verifier.ok('special_segments', 'clock_mapping: stale-observation '
                        'action rejection recorded (%s)'
                        % stale[0].get('reason'))
    elif kind == 'regression':
        expected_delays = {'obs_delay_s': plan.get('obs_delay_s'),
                           'action_delay_s': plan.get('action_delay_s')}
        for key, value in expected_delays.items():
            if not (_num(value) and abs(value) <= 1e-12):
                verifier.fail('special_segments', 'regression run must use zero '
                              'latency (%s)' % key, run=label, field=key,
                              expected=0.0, actual=value)
        clock_plan = evidence.manifest.get('clock_plan')
        if isinstance(clock_plan, dict):
            for key in ('offset_ms', 'drift_ppm', 'uncertainty_ms'):
                value = clock_plan.get(key)
                if _num(value) and abs(value) > 1e-12:
                    verifier.fail('special_segments', 'regression run must use a '
                                  'zero clock plan (%s)' % key, run=label,
                                  field='clock_plan.' + key, expected=0.0,
                                  actual=value)
        direct = analysis.get('status_counts', {}).get('DIRECT', 0)
        if direct <= 0:
            verifier.fail('special_segments', 'regression run has no DIRECT '
                          'transport steps', run=label, field='transport.status',
                          expected='DIRECT', actual=direct)
        else:
            verifier.ok('special_segments', 'regression: %d DIRECT transport '
                        'steps' % direct)
        for episode_id in evidence.steps_by_episode:
            for row in evidence.steps_by_episode[episode_id]:
                transport = row.get('transport')
                if not isinstance(transport, dict):
                    continue
                if transport.get('status') == 'DIRECT' \
                        and transport.get('action_id') \
                        != transport.get('executed_action_id'):
                    verifier.fail('special_segments', 'regression DIRECT step '
                                  'executed_action_id != action_id', run=label,
                                  episode_id=episode_id,
                                  step=row.get('step'),
                                  field='transport.executed_action_id',
                                  expected=transport.get('action_id'),
                                  actual=transport.get('executed_action_id'))
    else:
        verifier.ok('special_segments', detail + ' (no segment-specific check)')
    # POST_ABORT raw rows must exist when the frozen plan requests a window and
    # must show either residual old-setpoint execution or the zero-target
    # fallback after the rejection.
    observe_s = plan.get('post_abort_observe_s')
    if _num(observe_s) and observe_s > 0:
        post_rows = []
        for rows in evidence.steps_by_episode.values():
            post_rows.extend(row for row in rows
                             if row.get('phase') == 'POST_ABORT')
        if not post_rows:
            verifier.fail('post_abort_rows', 'post-abort observation window is '
                          'configured but no POST_ABORT raw rows exist',
                          run=label, field='phase', expected='POST_ABORT',
                          actual='absent')
        else:
            residual = False
            fallback = False
            for row in post_rows:
                transport = row.get('transport')
                transport = transport if isinstance(transport, dict) else {}
                applied = row.get('applied')
                applied = applied if isinstance(applied, dict) else {}
                if applied.get('action_id') or transport.get('status') == 'HOLDING':
                    residual = True
                if transport.get('status') == 'NONE' \
                        and applied.get('action_id') in ('', None):
                    values = [applied.get('vx_forward_mps'),
                              applied.get('vy_left_mps'),
                              applied.get('vz_up_mps'),
                              applied.get('yaw_rate_ccw_world_radps')]
                    if all(_num(value) and abs(value) <= 1e-12
                           for value in values):
                        fallback = True
            if not (residual or fallback):
                verifier.fail('post_abort_rows', 'POST_ABORT rows show neither a '
                              'residual old setpoint nor the zero-target fallback',
                              run=label, field='applied.action_id',
                              expected='old setpoint or zero target',
                              actual='absent')
            else:
                verifier.ok('post_abort_rows', 'post_abort_rows: %d POST_ABORT '
                            'rows (residual=%s fallback=%s)'
                            % (len(post_rows), residual, fallback))
    elif isinstance(plan.get('post_abort_observe_s'), (int, float)):
        verifier.note('post_abort_rows', 'post_abort_rows: no observation window '
                      'configured for %s' % segment_id)


def verify_special(special_freeze, special_runs, regression_runs,
                   expected_index, verifier):
    name = 'special_segments'
    analyses = {}
    provided = {}
    provided.update(special_runs)
    provided.update(regression_runs)
    declared = {}
    if isinstance(special_freeze, dict):
        segments = special_freeze.get('special_segments')
        if isinstance(segments, list):
            for entry in segments:
                if isinstance(entry, dict) and entry.get('segment_id'):
                    declared[str(entry['segment_id'])] = entry
        elif isinstance(segments, dict):
            for segment_id, entry in segments.items():
                if isinstance(entry, dict):
                    declared[str(segment_id)] = entry
    for segment_id, evidence in provided.items():
        analysis = evidence.get('analysis') if isinstance(evidence, dict) else None
        if analysis is None:
            continue
        analyses[segment_id] = analysis
        entry = declared.get(segment_id)
        if special_freeze is not None and not entry:
            kind = _segment_kind(segment_id, {})
            if kind == 'regression':
                # Isolation regression runs are governed by the existing v2
                # regression freeze; absence here is not a contradiction.
                verifier.ok(name, 'regression run %s checked without a special '
                            'freeze entry' % segment_id)
            else:
                verifier.fail(name, 'special run is not declared in the special '
                              'freeze', run=segment_id, field='segment_id',
                              expected=sorted(declared), actual=segment_id)
        plan = evidence['evidence'].manifest.get('latency_plan')
        plan = plan if isinstance(plan, dict) else {}
        segment_plan = evidence['evidence'].manifest.get('latency_plan')
        if isinstance(segment_plan, dict) and isinstance(entry, dict) \
                and isinstance(entry.get('run_plan'), dict):
            _compare_run_plan(evidence['evidence'], entry['run_plan'], name,
                              verifier, 'latency_plan.')
        elif isinstance(entry, dict) and entry.get('run_plan') is None:
            verifier.missing.add(segment_id,
                                 'freeze.special_segments[%s].run_plan'
                                 % segment_id, segment_id)
        _check_segment(segment_id, evidence['evidence'], analysis, entry,
                       expected_index, verifier)
        verify_expected_run(evidence['evidence'], analysis, expected_index,
                            verifier)
    if special_freeze is not None:
        for segment_id in declared:
            if segment_id not in provided:
                verifier.missing.add(segment_id,
                                     'special run directory', segment_id)
        if not provided and declared:
            verifier.skip(name, 'no special run directories provided')
    verifier.ok_if_clean(name, '%d special/regression segments checked'
                         % len(provided))
    return analyses


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

def _run_summary(analysis):
    arrival_ages = [value for value in analysis.get('arrival_ages') or []
                    if _num(value)]
    bounds = [value for value in analysis.get('observation_bounds') or []
              if _num(value)]
    return {
        'role': analysis.get('role'),
        'run_dir': analysis.get('run_dir'),
        'episode_count': analysis.get('episode_count'),
        'loaded': analysis.get('loaded'),
        'outcomes': dict(analysis.get('outcomes') or {}),
        'status_counts': dict(analysis.get('status_counts') or {}),
        'phase_counts': dict(analysis.get('phase_counts') or {}),
        'rejection_reasons': dict(analysis.get('rejection_reasons') or {}),
        'ttl_ns_observed': sorted({int(value) for value in
                                   analysis.get('ttl_deltas') or []}),
        'arrival_age_s': {
            'count': len(arrival_ages),
            'min': min(arrival_ages) if arrival_ages else None,
            'max': max(arrival_ages) if arrival_ages else None,
        },
        'observation_age_bound_s': {
            'count': len(bounds),
            'min': min(bounds) if bounds else None,
            'max': max(bounds) if bounds else None,
        },
        'rejected_arrivals': _short(analysis.get('rejected') or []),
        'mapping_unusable_steps': len(analysis.get('mapping_unusable') or []),
        'episodes': analysis.get('episodes') or {},
    }


def _load_freeze(path, label, verifier):
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        verifier.missing.add(label, 'freeze file %s' % path, label)
        return None
    try:
        return _load_json(path)
    except (OSError, ValueError) as error:
        verifier.fail('freeze_lineage', 'freeze document parse failure: '
                      + repr(error), run=label)
        return None


def _parse_run_spec(spec, parser):
    if '=' not in spec:
        parser.error('expected SEGMENT_ID=DIR, got: ' + spec)
    key, value = spec.split('=', 1)
    if not key.strip() or not value.strip():
        parser.error('expected SEGMENT_ID=DIR, got: ' + spec)
    return key.strip(), value.strip()


def build_parser():
    parser = argparse.ArgumentParser(
        description='Independent verification of latency-envelope evaluation '
                    'runs (plan section 6).')
    parser.add_argument('--pair-freeze', type=Path, default=None,
                        help='pre-run pair freeze json (v2)')
    parser.add_argument('--run-a', type=Path, default=None,
                        help='main config A run directory')
    parser.add_argument('--run-b', type=Path, default=None,
                        help='main config B run directory')
    parser.add_argument('--special-freeze', type=Path, default=None,
                        help='pre-run special-segment freeze json (v2)')
    parser.add_argument('--special-run', action='append', default=[],
                        metavar='SEGMENT_ID=DIR',
                        help='special segment run directory (repeatable)')
    parser.add_argument('--regression-run', action='append', default=[],
                        metavar='ID=DIR',
                        help='isolation regression run directory (repeatable)')
    parser.add_argument('--freeze-v1', type=Path, default=None,
                        help='optional exploration (v1) freeze; used as fallback '
                             'pair freeze when --pair-freeze is absent')
    parser.add_argument('--expected-config', type=Path, default=None,
                        help='expected classification config '
                             '(default: configs/scenarios/latency_expected_v1.json '
                             'when it exists)')
    parser.add_argument('--output', type=Path, default=None,
                        help='write the verification JSON here')
    parser.add_argument('--repo-root', type=Path, default=Path('.'),
                        help='repository root for relative freeze paths and the '
                             'worktree digest (default: .)')
    return parser


def run_verification(args, parser=None):
    parser = parser or build_parser()
    verifier = Verifier()
    verifier.note('schema_completeness', 'raw-only recompute: summary.json is '
                 'not read and recorded metrics are comparison targets only')
    run_dirs = {}
    pair_freeze_path = args.pair_freeze
    if pair_freeze_path is None and args.freeze_v1 is not None:
        pair_freeze_path = args.freeze_v1
    special_freeze_path = args.special_freeze
    pair_freeze = _load_freeze(pair_freeze_path, 'pair_freeze', verifier)
    special_freeze = _load_freeze(special_freeze_path, 'special_freeze',
                                  verifier)
    exploration_freeze = None
    if args.freeze_v1 is not None and pair_freeze_path != args.freeze_v1:
        exploration_freeze = _load_freeze(args.freeze_v1, 'exploration_freeze',
                                          verifier)
    expected_index = ExpectedIndex()
    expected_index.add_freeze(pair_freeze)
    expected_index.add_freeze(special_freeze)
    expected_path = args.expected_config
    if expected_path is None:
        default_expected = Path('configs/scenarios/latency_expected_v1.json')
        if default_expected.is_file():
            expected_path = default_expected
    if expected_path is not None:
        expected_payload = _load_freeze(expected_path, 'expected_config',
                                        verifier)
        expected_index.add_config(expected_payload)
    # Load runs.
    evidence_a = load_run('main_A', 'main', args.run_a, verifier) \
        if args.run_a is not None else None
    evidence_b = load_run('main_B', 'main', args.run_b, verifier) \
        if args.run_b is not None else None
    special_entries = {}
    for spec in args.special_run:
        segment_id, run_dir = _parse_run_spec(spec, parser)
        label = segment_id
        evidence = load_run(label, 'special', Path(run_dir), verifier)
        special_entries[segment_id] = {'evidence': evidence, 'run_dir': run_dir}
        run_dirs[label] = run_dir
    for spec in args.regression_run:
        segment_id, run_dir = _parse_run_spec(spec, parser)
        label = segment_id
        evidence = load_run(label, 'regression', Path(run_dir), verifier)
        special_entries[segment_id] = {'evidence': evidence, 'run_dir': run_dir}
        run_dirs[label] = run_dir
    if evidence_a is not None:
        run_dirs['main_A'] = str(args.run_a)
    if evidence_b is not None:
        run_dirs['main_B'] = str(args.run_b)
    if not run_dirs:
        verifier.missing.add('verify', 'no run directories provided', 'cli')
    # Schema completeness.
    for evidence in [item for item in (evidence_a, evidence_b) if item] \
            + [entry['evidence'] for entry in special_entries.values()]:
        if evidence is None or not evidence.loaded:
            continue
        before = verifier.missing.count()
        verify_manifest_schema(evidence, verifier)
        verify_episode_schema(evidence, verifier)
        verify_step_schema(evidence, verifier)
        if verifier.missing.count() == before:
            verifier.ok('schema_completeness',
                        'raw schema complete for %s' % evidence.label)
    # Freeze document checks.
    if pair_freeze_path is not None:
        if pair_freeze is None:
            pass
        else:
            verify_freeze(pair_freeze, pair_freeze_path, 'pair', verifier,
                          'pair_freeze')
            verify_freeze_file_digest_cases(pair_freeze, pair_freeze_path,
                                            verifier, 'pair_freeze',
                                            args.repo_root)
            verify_worktree_digest(pair_freeze, pair_freeze_path, verifier,
                                   'pair_freeze', args.repo_root)
    if special_freeze_path is not None and special_freeze is not None:
        verify_freeze(special_freeze, special_freeze_path, 'special', verifier,
                      'special_freeze')
        verify_freeze_file_digest_cases(special_freeze, special_freeze_path,
                                        verifier, 'special_freeze',
                                        args.repo_root)
    # Inspect runs.
    analyses = {}
    pair_ctx = {'freeze_path': pair_freeze_path}
    if evidence_a is not None:
        analyses['main_A'] = inspect_run(evidence_a, pair_ctx, verifier)
    if evidence_b is not None:
        analyses['main_B'] = inspect_run(evidence_b, pair_ctx, verifier)
    for segment_id, entry in special_entries.items():
        regression = entry['evidence'].role == 'regression'
        freeze_path = None if regression else special_freeze_path
        analysis = inspect_run(entry['evidence'],
                               {'freeze_path': freeze_path}, verifier)
        entry['analysis'] = analysis
        analyses[segment_id] = analysis
    # Pair + denominator checks.
    if evidence_a is not None or evidence_b is not None:
        if pair_freeze is None:
            verifier.missing.add('pair', 'pair freeze document', 'pair')
        verify_pair(evidence_a, evidence_b,
                    analyses.get('main_A') or {},
                    analyses.get('main_B') or {}, pair_freeze, verifier)
        for evidence, analysis in ((evidence_a, analyses.get('main_A')),
                                   (evidence_b, analyses.get('main_B'))):
            if evidence is not None and analysis is not None:
                verify_expected_run(evidence, analysis, expected_index, verifier)
    # Special checks.
    if special_entries or special_freeze is not None:
        verify_special(special_freeze, special_entries, {}, expected_index,
                       verifier)
    # Exploration freeze is context only; never upgrades evidence.
    if exploration_freeze is not None:
        verifier.ok('freeze_lineage', 'exploration freeze recorded as context '
                    '(not used to upgrade evidence)')
    # Compose result.
    status = 'PASS'
    if verifier.missing:
        status = 'INCOMPLETE'
        schema = verifier.checks['schema_completeness']
        schema['passed'] = False
        schema['notes'].append('missing raw fields/incomplete data: %d entries'
                               % verifier.missing.count())
    elif verifier.failures:
        status = 'FAIL'
    recomputed = {
        'runs': {label: _run_summary(analysis)
                 for label, analysis in analyses.items()},
        'expected_index': expected_index.summary(),
        'metric_definitions': {
            'stop': 'speed<=0.08_mps for 0.5 s; distance projected on the '
                    'initial brake velocity direction',
            'executed_action_count': 'distinct executed_action_id values',
            'arrival_rejection_count': 'rows with transport.status=REJECTED',
        },
    }
    pair_recomputed = {}
    if evidence_a is not None and evidence_b is not None:
        plan_a = evidence_a.manifest.get('latency_plan') or {}
        plan_b = evidence_b.manifest.get('latency_plan') or {}
        pair_recomputed = {
            'config_a': plan_a.get('config_id'),
            'config_b': plan_b.get('config_id'),
            'stop_a': plan_a.get('stop_distance_m'),
            'stop_b': plan_b.get('stop_distance_m'),
            'ttl_a_ms': plan_a.get('ttl_ms'),
            'ttl_b_ms': plan_b.get('ttl_ms'),
            'obs_delay_a_s': plan_a.get('obs_delay_s'),
            'obs_delay_b_s': plan_b.get('obs_delay_s'),
            'action_delay_a_s': plan_a.get('action_delay_s'),
            'action_delay_b_s': plan_b.get('action_delay_s'),
            'case_count_a': len(evidence_a.episodes),
            'case_count_b': len(evidence_b.episodes),
        }
    recomputed['pair'] = pair_recomputed
    freeze_info = {'path': str(pair_freeze_path) if pair_freeze_path else None,
                   'sha256': _sha256_file(pair_freeze_path)
                   if pair_freeze_path and Path(pair_freeze_path).is_file()
                   else None,
                   'frozen_at': pair_freeze.get('frozen_at')
                   if isinstance(pair_freeze, dict) else None,
                   'code_commit': pair_freeze.get('code_commit')
                   if isinstance(pair_freeze, dict) else None,
                   'schema_version': pair_freeze.get('schema_version')
                   if isinstance(pair_freeze, dict) else None}
    if special_freeze_path is not None:
        freeze_info['special'] = {
            'path': str(special_freeze_path),
            'sha256': _sha256_file(special_freeze_path)
            if Path(special_freeze_path).is_file() else None,
            'frozen_at': special_freeze.get('frozen_at')
            if isinstance(special_freeze, dict) else None,
            'code_commit': special_freeze.get('code_commit')
            if isinstance(special_freeze, dict) else None,
            'schema_version': special_freeze.get('schema_version')
            if isinstance(special_freeze, dict) else None,
        }
    if exploration_freeze is not None:
        freeze_info['exploration_v1'] = {
            'path': str(args.freeze_v1),
            'sha256': _sha256_file(args.freeze_v1),
            'frozen_at': exploration_freeze.get('frozen_at'),
            'code_commit': exploration_freeze.get('code_commit'),
            'schema_version': exploration_freeze.get('schema_version'),
            'status': exploration_freeze.get('status'),
        }
    result = {
        'status': status,
        'checks': verifier.finalize_checks(),
        'recomputed': _jsonable(recomputed),
        'failures': _jsonable(verifier.failures),
        'missing_fields': verifier.missing.as_list(),
        'run_dirs': run_dirs,
        'freeze': _jsonable(freeze_info),
    }
    return result


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_verification(args, parser)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    return {'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
