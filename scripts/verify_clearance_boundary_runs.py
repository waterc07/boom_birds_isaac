#!/usr/bin/env python3
"""Independent verification of clearance-boundary evaluation runs.

Implements docs/superpowers/plans/2026-11-02-clearance-boundary.md sections 2, 3
and 6.

Design rules (same discipline as ``scripts/verify_latency_runs.py``):

* Pure standard library.  The verifier never imports the runner, the evaluation
  helpers or anything from ``src/`` -- every contract value is recomputed from
  the raw evidence recorded in ``steps.jsonl`` / ``episodes.jsonl`` /
  ``manifest.json`` plus the pre-run freeze, the expected classification file and
  the frozen brake model.
* ``summary.json`` is never read and recorded conclusions (metrics, expected
  verdicts) are never used as a verdict.  Recorded ``episodes[].metrics`` are
  comparison targets only: a disagreement with the independent recomputation is
  a failure.
* Every check carries a ``category`` in
  ``{data_integrity, contract_invariant, scenario_expectation,
  performance_boundary}``.
* Missing raw fields or incomplete data produce ``status = INCOMPLETE`` -- never
  ``PASS``.  Contradictions produce ``FAIL``.  A scenario expectation mismatch is
  recorded in ``deviations`` (never folded into PASS); any deviation also makes
  the overall status ``FAIL``.
* Boundary expectations are pre-run expectations, not conclusions: the expected
  file must be marked ``EXPECTED_NOT_CONCLUSION``.

Raw-record contract assumed (fixed by the plan and reported to the runner):

``steps.jsonl`` per row
    the retained ``run_dynamic_eval`` fields (episode_id, case_id, method,
    step, time_s, phase, position/velocity/speed, obstacle pose, clock,
    observation, transport/applied/v2 fields, supervisor fields, contact,
    outcome/reason) plus, for the supervisor path:
    ``clearance`` -- the plan section 2 record
        {schema_version, algorithm{id, version, units, frame, time_base,
         prediction_horizon_s, prediction_step_s},
         inputs{robot_center_world_m, robot_velocity_world_mps,
                target_waypoint_world_m, waypoint_index,
                obstacle_observed_center_world_m,
                obstacle_observed_velocity_world_mps,
                observation_age_point_s, observation_age_bound_s,
                observation_valid, observation_reason},
         prediction{obstacle_predicted_centers_world_m, point_distances_m,
                    min_index},
         metrics{center_distance_m, envelope_gap_sphere_m, path_clearance_m,
                 path_clearance_gap_sphere_m},
         envelopes{robot{kind, radius_m, aabb_half_extents_m, measured_prim,
                         source, attitude_scope, limitation},
                   obstacle{kind, radius_m, size_m, source}},
         validity{valid, reasons}, applicability{status, reasons, notes}}
    ``stop_requirement`` -- the plan section 3 record
        {schema_version, model_id, basis, inputs{robot_speed_mps,
         closing_speed_mps, observation_age_bound_s, action_delay_s,
         action_ttl_remaining_s, robot_radius_m, obstacle_radius_m,
         stop_threshold_m, proposed_margin_m},
         terms{brake_distance_m, transport_reaction_m,
               observation_age_motion_m, envelope_sum_m},
         required_clearance_m, margin_to_threshold_m,
         status, status_reasons}
``episodes.jsonl`` per row
    scenario_class, business_outcome, physical_outcome and ``metrics`` with the
    plan section 4 additions (min_path_clearance_m,
    min_path_clearance_gap_sphere_m, min_center_distance_m,
    min_envelope_gap_sphere_m, conservative_envelope, stop_requirement_extremes,
    post_abort) plus the retained brake metrics.
``manifest.json``
    boundary_plan/run_plan, clearance_schema_version,
    stop_requirement_schema_version, clearance_algorithm, brake_model_sha256,
    envelope_policy, body_envelope, freeze pointer, outputs_sha256,
    episode_ids, gui fields.  Boundary runs also carry ``contact_sensor`` with
    one of two honest evidence modes: ``sphere_overlap_inference`` (the
    environment force sensor does not report obstacle-robot force -- physical
    contact is inferred from conservative sphere overlap, with
    ``inference_rule.sphere_overlap_m_gt`` frozen at 0.02 m and
    ``force_sensor_available=false``) or ``force_sensor`` (a real sensor).
    A zero contact force is never read as ``NO_CONTACT`` by itself.

``contact_evidence`` per step (required when the manifest declares a mode):
    {sensor_force_n, force_sensor_available, center_distance_m, radii_sum_m,
     sphere_overlap_m, inferred_contact, inferred_contact_time_s,
     command_all_zero, robot_speed_mps}.  The verifier recomputes
    ``sphere_overlap_m = max(0, radii_sum - center_distance)``,
    ``inferred_contact = sphere_overlap_m > 0.02`` and the physical outcome:
    ``CONTACT_MEASURED`` (force > 0.02) > ``CONTACT_INFERRED`` (inferred
    overlap) > ``NO_CONTACT``.  ``episodes.metrics.contact_evidence_summary``
    records the aggregate.  POST_STOP_COLLISION contact ordering uses the
    inferred first-contact time (stop-complete / POST_ABORT phase / business
    stop + 0.5 s settle window); a contact scenario with neither measured force
    nor inferred contact is a scenario expectation FAIL, not INCOMPLETE.

Lead-aligned segment / expectation contract (2026-11-02):

* Boundary segments are ``boundary_default`` (18 episodes),
  ``boundary_delay_e1`` (2), ``boundary_delay_e2`` (2) and ``boundary_fast``
  (2) = 24 independent ``*_r0``/``*_r1`` cases with ``repeats=1``.  The
  denominator is the frozen ``run_plan.case_ids`` length, not an assumed repeat
  factor.
* ``role='boundary'`` segments validate the 8 boundary ``scenario_class``
  values through the expected file.  ``role='special'`` recheck segments use
  their declared ``acceptable_paths`` / ``criteria_id='(c)'`` checks, and
  ``role='regression'`` segments are compared with the existing v2 evidence
  (SUCCESS) instead of requiring an expected entry.

Usage:

    python scripts/verify_clearance_boundary_runs.py \
        --freeze configs/scenarios/clearance_boundary_freeze_v1.json \
        --run boundary_default=outputs/map_eval/clearance_boundary_default \
        --expected configs/scenarios/clearance_boundary_expected_v1.json \
        --brake-model configs/scenarios/brake_model_v1.json \
        --repo-root . \
        --output docs/reports/map_eval/clearance_boundary/verify_clearance_boundary.json

Exit code: 0 = PASS, 1 = FAIL, 2 = INCOMPLETE.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# contract constants
# ---------------------------------------------------------------------------

CLEARANCE_SCHEMA_VERSION = 'boom_birds.clearance.v1'
CLEARANCE_ALGORITHM_ID = 'supervisor_predicted_path_clearance'
CLEARANCE_ALGORITHM_VERSION = '1.0.0'
STOP_REQUIREMENT_SCHEMA_VERSION = 'boom_birds.stop_requirement.v1'
BOUNDARY_FREEZE_SCHEMA = 'boom_birds.clearance_boundary_freeze.v1'
BOUNDARY_EVAL_VERSION = 'boom_birds.clearance_boundary_eval.v1'
BRAKE_MODEL_SCHEMA = 'boom_birds.brake_model.v1'
BOUNDARY_EXPECTED_SCHEMA = 'boom_birds.clearance_boundary_expected.v1'

CATEGORIES = ('data_integrity', 'contract_invariant', 'scenario_expectation',
              'performance_boundary')

# (check name, category) -- the order is the report order and the test coverage
# order.  Every check is evaluated on every verification (or explicitly marked
# not applicable) so a missing branch shows up as INCOMPLETE, not PASS.
CHECKS = (
    # data integrity
    ('schema_completeness', 'data_integrity'),
    ('artifact_hashes', 'data_integrity'),
    ('episode_identity_and_denominator', 'data_integrity'),
    ('step_time_monotonicity', 'data_integrity'),
    ('gui_evidence', 'data_integrity'),
    ('freeze_lineage', 'data_integrity'),
    ('manifest_disk_consistency', 'data_integrity'),
    ('contact_sensor_evidence', 'data_integrity'),
    ('metrics_match_recorded', 'data_integrity'),
    ('business_physical_outcome', 'data_integrity'),
    # contract invariants
    ('clearance_recompute', 'contract_invariant'),
    ('clearance_prediction_structure', 'contract_invariant'),
    ('clearance_envelope_rules', 'contract_invariant'),
    ('clearance_metric_semantics', 'contract_invariant'),
    ('clearance_observation_age', 'contract_invariant'),
    ('clearance_decision_consistency', 'contract_invariant'),
    ('stop_requirement_recompute', 'contract_invariant'),
    ('stop_requirement_support_boundary', 'contract_invariant'),
    ('stop_requirement_basis', 'contract_invariant'),
    ('ttl_no_renewal', 'contract_invariant'),
    ('arrival_expiry_rejection', 'contract_invariant'),
    ('rejection_never_executed', 'contract_invariant'),
    ('hold_until_expiry_then_none', 'contract_invariant'),
    ('post_abort_old_setpoint', 'contract_invariant'),
    # scenario expectations
    ('expected_config_coverage', 'scenario_expectation'),
    ('scenario_class_match', 'scenario_expectation'),
    ('acceptable_outcomes', 'scenario_expectation'),
    ('must_conditions', 'scenario_expectation'),
    ('insufficient_margin_success_ban', 'scenario_expectation'),
    ('post_stop_collision_ordering', 'scenario_expectation'),
    ('unsupported_allowed_scope', 'scenario_expectation'),
    ('special_clock_mapping_paths', 'scenario_expectation'),
    ('special_ttl_over_criteria', 'scenario_expectation'),
    # performance / capability boundary
    ('brake_start_metrics', 'performance_boundary'),
    ('stop_distance_time', 'performance_boundary'),
    ('relative_closing_speed', 'performance_boundary'),
    ('contact_metrics', 'performance_boundary'),
    ('obstacle_approach_after_stop', 'performance_boundary'),
    ('post_abort_residual', 'performance_boundary'),
    ('unsupported_usage_stats', 'performance_boundary'),
    ('boundary_episode_coverage', 'performance_boundary'),
)

CHECK_NAMES = tuple(name for name, _ in CHECKS)
CATEGORY_OF = {name: category for name, category in CHECKS}

TRANSPORT_STATUSES = ('DIRECT', 'APPLIED', 'HOLDING', 'REJECTED', 'NONE')
PHASES = ('RUN', 'POST_ABORT')
SUPERVISOR_STATES = ('FOLLOW', 'BRAKE', 'HOLD', 'WAIT', 'RESUME',
                     'DEGRADED', 'ABORT', 'SUCCESS')
SUPERVISOR_ACTIONS = ('ROUTE', 'STOP', 'ABORT')
BUSINESS_OUTCOMES = ('SUCCESS', 'ABORT', 'TIMEOUT', 'INVALID')
PHYSICAL_OUTCOMES = ('NO_CONTACT', 'CONTACT_INFERRED', 'CONTACT_MEASURED',
                     'OUT_OF_BOUNDS')
CONTACT_EVIDENCE_MODES = ('sphere_overlap_inference', 'force_sensor')
CONTACT_EVIDENCE_KEYS = ('sensor_force_n', 'force_sensor_available',
                         'center_distance_m', 'radii_sum_m',
                         'sphere_overlap_m', 'inferred_contact',
                         'inferred_contact_time_s', 'command_all_zero',
                         'robot_speed_mps')
SCENARIO_CLASSES = ('BLOCKED_EXIT', 'BLOCKED_EXIT_TIGHT', 'NO_STOP_EXPECTED',
                    'STOP_WAIT_RESUME', 'INSUFFICIENT_MARGIN',
                    'STOP_OBSTACLE_HOLD', 'POST_STOP_COLLISION',
                    'HIGH_SPEED_STOP')
STOP_REQUIRED_CLASSES = frozenset({
    'BLOCKED_EXIT', 'BLOCKED_EXIT_TIGHT', 'STOP_WAIT_RESUME',
    'INSUFFICIENT_MARGIN', 'STOP_OBSTACLE_HOLD', 'POST_STOP_COLLISION',
    'HIGH_SPEED_STOP',
})
NO_STOP_CLASSES = frozenset({'NO_STOP_EXPECTED'})

STOP_SPEED_MPS = 0.08
STOP_HOLD_S = 0.5
CONTACT_FORCE_N = 0.02
# Kinematic contact inference (Lead-aligned 2026-11-02): the contact force sensor
# does not report obstacle-robot force in this environment, so physical contact
# is inferred from conservative sphere overlap.  The frozen rule is:
# inferred contact iff sphere_overlap_m > 0.02 m.  A sensor reading of 0 must
# never be read as "no contact".
CONTACT_OVERLAP_M = 0.02
DEFAULT_PROPOSED_MARGIN_M = 0.2
# Lead-aligned: the 24 boundary cases are independent case_ids (*_r0/*_r1, each
# one episode), so the default repeat count is 1 and the denominator comes from
# the freeze run_plan.case_ids (18 + 2 + 2 + 2 = 24).
DEFAULT_REPEATS = 1
# The Lead-aligned segment split: boundary_default (A/B/C 9 cases x2 = 18),
# boundary_delay_e1 (2), boundary_delay_e2 (2), boundary_fast (2) -> 24 episodes.
BOUNDARY_SEGMENTS = ('boundary_default', 'boundary_delay_e1',
                     'boundary_delay_e2', 'boundary_fast')

# block the stop-requirement status; marking reasons do not.
STOP_BLOCKING_REASONS = frozenset({
    'ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT',
    'ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT',
    'OBSERVATION_AGE_UNKNOWN',
    'ACTION_TTL_EXPIRED_BEFORE_ARRIVAL',
})
STOP_MARKER_REASONS = frozenset({
    'CLOSING_SPEED_NOT_MODELLED',
    'PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME',
})
STOP_ALLOWED_REASONS = STOP_BLOCKING_REASONS | STOP_MARKER_REASONS
STOP_BASES = ('actuation', 'trigger')

MUST_CONDITION_KINDS = frozenset({
    'no_contact', 'contact', 'contact_after_business_stop',
    'contact_after_business_outcome', 'stop_started', 'no_stop',
    'business_outcome_in', 'min_path_clearance_below_m',
    'min_path_clearance_at_least_m', 'min_margin_below_m',
    'min_margin_at_least_m', 'brake_speed_below_mps',
    'brake_speed_at_least_mps',
})

# numeric tolerances
GEOM_TOL = 1e-6          # production value vs independent geometry rebuild
AGE_TOL_S = 1e-6         # clock-derived ages
HOST_NS_TOL = 1_000_000  # host_now_ns vs time_s * 1e9
CLOCK_NS_TOL = 2         # integer ns rounding in the clock algebra
PLAN_TOL = 1e-6
METRIC_TOL_DIST_M = 5e-4
METRIC_TOL_TIME_S = 5e-4
METRIC_TOL_SPEED_MPS = 5e-4
METRIC_TOL_FORCE_N = 5e-4
METRIC_TOL_TTL_NS = 1

MAX_FAILURES = 800
MAX_CHECK_NOTES = 8
MAX_LIST_DETAIL = 40

CLEARANCE_TOP_KEYS = ('schema_version', 'algorithm', 'inputs', 'prediction',
                      'metrics', 'envelopes', 'validity', 'applicability')
CLEARANCE_ALGORITHM_KEYS = ('id', 'version', 'units', 'frame', 'time_base',
                            'prediction_horizon_s', 'prediction_step_s')
CLEARANCE_INPUT_KEYS = ('robot_center_world_m', 'robot_velocity_world_mps',
                        'target_waypoint_world_m', 'waypoint_index',
                        'obstacle_observed_center_world_m',
                        'obstacle_observed_velocity_world_mps',
                        'observation_age_point_s', 'observation_age_bound_s',
                        'observation_valid', 'observation_reason')
CLEARANCE_PREDICTION_KEYS = ('obstacle_predicted_centers_world_m',
                             'point_distances_m', 'min_index')
CLEARANCE_METRIC_KEYS = ('center_distance_m', 'envelope_gap_sphere_m',
                         'path_clearance_m', 'path_clearance_gap_sphere_m')
CLEARANCE_ROBOT_ENV_KEYS = ('kind', 'radius_m', 'aabb_half_extents_m',
                            'measured_prim', 'source', 'attitude_scope',
                            'limitation')
CLEARANCE_OBSTACLE_ENV_KEYS = ('kind', 'radius_m', 'size_m', 'source')
CLEARANCE_VALIDITY_KEYS = ('valid', 'reasons')
CLEARANCE_APPLICABILITY_KEYS = ('status', 'reasons', 'notes')

STOP_REQUIREMENT_TOP_KEYS = ('schema_version', 'model_id', 'basis', 'inputs',
                             'terms', 'required_clearance_m',
                             'margin_to_threshold_m', 'status',
                             'status_reasons')
STOP_REQUIREMENT_INPUT_KEYS = ('robot_speed_mps', 'closing_speed_mps',
                               'observation_age_bound_s', 'action_delay_s',
                               'action_ttl_remaining_s', 'robot_radius_m',
                               'obstacle_radius_m', 'stop_threshold_m',
                               'proposed_margin_m')
STOP_REQUIREMENT_TERM_KEYS = ('brake_distance_m', 'transport_reaction_m',
                              'observation_age_motion_m', 'envelope_sum_m')

STEP_TOP_KEYS = ('episode_id', 'case_id', 'method', 'scenario_class', 'step',
                 'time_s', 'phase', 'position_world_m', 'velocity_world_mps',
                 'speed_mps', 'obstacle_position_world_m',
                 'obstacle_velocity_world_mps', 'observation_valid',
                 'observation_reason', 'observation_age_s', 'supervisor_state',
                 'supervisor_action', 'contact_force_n', 'contact_prim',
                 'outcome', 'reason', 'execution_path')

CLOCK_KEYS = ('host_now_ns', 'capture_host_ns', 'capture_clock_ns',
              'camera_clock_id', 'mapping_host_ns', 'mapping_error_ns',
              'mapping_sync_generation', 'mapping_usable', 'mapping_reason',
              'age_point_s', 'age_bound_s')
TRANSPORT_KEYS = ('status', 'action_id', 'executed_action_id', 'issued_at_ns',
                  'expires_at_ns', 'scheduled_arrival_ns', 'arrival_ns',
                  'dispatch_delay_s', 'arrival_age_s', 'reason', 'executed')

EPISODE_KEYS = ('episode_id', 'case_id', 'segment_id', 'scenario_class',
                'business_outcome', 'physical_outcome', 'steps', 'duration_s',
                'metrics')
EPISODE_METRIC_KEYS = ('brake_start', 'initial_speed_mps', 'stop_distance_m',
                       'stop_time_s', 'stop_definition', 'min_path_clearance_m',
                       'min_path_clearance_gap_sphere_m', 'min_center_distance_m',
                       'min_envelope_gap_sphere_m', 'conservative_envelope',
                       'stop_requirement_extremes', 'max_closing_speed_mps',
                       'max_relative_speed_mps', 'contact_max_force_n',
                       'contact_prim', 'post_abort')

MANIFEST_REQUIRED_KEYS = ('schema_version', 'code_commit', 'gui_mode', 'renderer',
                          'command', 'started_at', 'outputs_sha256',
                          'episode_ids', 'gui_evidence', 'body_envelope',
                          'freeze', 'clearance_schema_version',
                          'stop_requirement_schema_version',
                          'clearance_algorithm', 'envelope_policy',
                          'cases_sha256', 'methods')

PLAN_COMPARE_KEYS = ('role', 'segment_id', 'config_id', 'case_ids', 'methods',
                     'execution_path', 'obs_delay_s', 'action_delay_s',
                     'ttl_ms', 'max_age_ms', 'allowed_observation_age_ms',
                     'stop_distance_m', 'post_abort_observe_s',
                     'clock_offset_ms', 'clock_drift_ppm',
                     'clock_uncertainty_ms', 'sync_fail_step',
                     'obs_mapping_fail_step', 'transport_stall_step',
                     'transport_stall_delay_s', 'cases_sha256',
                     'expected_sha256', 'brake_model_sha256',
                     'vehicle_config_file', 'vehicle_config_sha256')

DEVICE_GUI_RENDERERS = ('directx',)


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


def _vec(value, length=3):
    if not isinstance(value, (list, tuple)) or len(value) < length:
        return None
    try:
        return [float(value[index]) for index in range(length)]
    except (TypeError, ValueError):
        return None


def _vec_close(actual, expected, tol, length=3):
    left = _vec(actual, length)
    right = _vec(expected, length)
    if left is None or right is None:
        return False
    return all(abs(left[index] - right[index]) <= tol
               for index in range(length))


def _distance(left, right):
    return math.dist(left, right) if left is not None and right is not None \
        else None


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
        and sorted(str(item) for item in left) == sorted(str(item)
                                                         for item in right)


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


def _row_key(row):
    phase_rank = 0 if row.get('phase') != 'POST_ABORT' else 1
    step = row.get('step') if _num(row.get('step')) else 0
    time_s = float(row.get('time_s')) if _num(row.get('time_s')) else -1.0
    return (time_s, phase_rank, step)


def _sorted_rows(rows):
    return sorted(rows, key=_row_key)


def _point_in(value, choices):
    return isinstance(value, str) and value in choices


def _is_boundary_segment(segment_id):
    return isinstance(segment_id, str) and segment_id.startswith('boundary_')


def box_conservative_sphere_radius(half_extents_m):
    """Plan section 2: sqrt(sum(h_i^2)) -- half diagonal, not max half extent."""
    return math.sqrt(sum(float(value) ** 2 for value in half_extents_m))


def point_to_segment_distance(point, start, end):
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(value * value for value in segment)
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = sum((point[index] - start[index]) * segment[index]
            for index in range(3)) / length_sq
    t = min(1.0, max(0.0, t))
    projection = [start[index] + segment[index] * t for index in range(3)]
    return math.dist(point, projection)


def predict_obstacle_centers(center, velocity, horizon_s, step_s):
    """Plan section 2: predict 1.0 s at 0.1 s -> 11 points (k = 0..N)."""
    steps = max(1, int(math.ceil(float(horizon_s) / float(step_s))))
    return [[center[index] + velocity[index] * (k * step_s)
             for index in range(3)] for k in range(steps + 1)]


def _recompute_clearance(inputs, horizon_s, step_s):
    robot = _vec(inputs.get('robot_center_world_m'))
    target = _vec(inputs.get('target_waypoint_world_m'))
    center = _vec(inputs.get('obstacle_observed_center_world_m'))
    velocity = _vec(inputs.get('obstacle_observed_velocity_world_mps'))
    if robot is None or target is None or center is None or velocity is None:
        return None
    centers = predict_obstacle_centers(center, velocity, horizon_s, step_s)
    distances = [point_to_segment_distance(point, robot, target)
                 for point in centers]
    path_clearance = min(distances)
    return {
        'centers': centers,
        'distances': distances,
        'path_clearance_m': path_clearance,
        'min_index': distances.index(path_clearance),
        'center_distance_m': math.dist(robot, center),
    }


# ---------------------------------------------------------------------------
# reporting plumbing
# ---------------------------------------------------------------------------

class MissingFields:
    """Collects missing raw-record fields (never silently ignored)."""

    def __init__(self):
        self._items = {}

    def add(self, label, path, example=None):
        key = (str(label), str(path))
        item = self._items.get(key)
        if item is None:
            self._items[key] = {'label': str(label), 'path': str(path),
                                'count': 1, 'example': example}
        else:
            item['count'] += 1

    def count(self):
        return len(self._items)

    def __bool__(self):
        return bool(self._items)

    def as_list(self):
        result = []
        for item in sorted(self._items.values(),
                           key=lambda entry: (entry['label'], entry['path'])):
            text = 'missing raw field: %s: %s' % (item['label'], item['path'])
            if item['count'] > 1:
                text += ' (occurrences=%d)' % item['count']
            if item['example']:
                text += ' (e.g. %s)' % item['example']
            result.append(text)
        return result


class Verifier:
    """Accumulates per-check state, structured failures, deviations and gaps."""

    def __init__(self):
        self.checks = {
            name: {'category': CATEGORY_OF[name], 'passed': None,
                   'notes': [], 'failures': 0}
            for name in CHECK_NAMES}
        self.failures = []
        self.deviations = []
        self.missing = MissingFields()

    # -- state transitions --------------------------------------------------
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
            failure = {'check': name, 'category': entry['category'],
                       'detail': str(detail)}
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

    def deviate(self, check, kind, detail, *, run=None, episode_id=None,
                case_id=None, expected=None, actual=None, context=None):
        """Record a scenario expectation deviation (never a PASS)."""
        deviation = {'kind': str(kind), 'check': check,
                     'category': CATEGORY_OF[check], 'detail': str(detail)}
        if run is not None:
            deviation['run'] = str(run)
        if episode_id is not None:
            deviation['episode_id'] = str(episode_id)
        if case_id is not None:
            deviation['case_id'] = str(case_id)
        if expected is not None:
            deviation['expected'] = _jsonable(expected)
        if actual is not None:
            deviation['actual'] = _jsonable(actual)
        if isinstance(context, dict):
            deviation.update({str(key): _jsonable(value)
                              for key, value in context.items()})
        self.deviations.append(deviation)
        entry = self.checks[check]
        entry['passed'] = False
        entry['failures'] += 1
        if len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append('deviation: ' + str(detail))

    def skip(self, name, detail):
        entry = self.checks[name]
        if entry['passed'] is None and len(entry['notes']) < 3:
            entry['notes'].append('n/a: ' + str(detail))

    def ok_if_clean(self, name, detail):
        if self.checks[name]['passed'] is None:
            self.ok(name, detail)

    def finalize_checks(self):
        result = {}
        for name in CHECK_NAMES:
            entry = self.checks[name]
            if entry['passed'] is None:
                self.missing.add('checks', name, 'check not evaluated')
            detail = '; '.join(entry['notes']) if entry['notes'] \
                else 'not evaluated'
            if entry['failures'] > len(entry['notes']):
                detail += ' (failures=%d)' % entry['failures']
            result[name] = {'category': entry['category'],
                            'passed': entry['passed'], 'detail': detail}
        return result


# ---------------------------------------------------------------------------
# run / freeze / expected / brake-model loading
# ---------------------------------------------------------------------------

@dataclass
class RunEvidence:
    label: str
    segment_id: str
    run_dir: Path
    manifest: dict = field(default_factory=dict)
    episodes: list = field(default_factory=list)
    steps_by_episode: dict = field(default_factory=dict)
    row_count: int = 0
    loaded: bool = False


def load_run(segment_id, run_dir, verifier):
    evidence = RunEvidence(label=str(segment_id), segment_id=str(segment_id),
                           run_dir=Path(run_dir))
    if not evidence.run_dir.is_dir():
        verifier.missing.add(segment_id, 'run directory (%s)' % run_dir,
                             segment_id)
        return evidence
    paths = {
        'manifest.json': evidence.run_dir / 'manifest.json',
        'episodes.jsonl': evidence.run_dir / 'episodes.jsonl',
        'steps.jsonl': evidence.run_dir / 'steps.jsonl',
    }
    for name, path in paths.items():
        if not path.is_file():
            verifier.missing.add(segment_id, name, segment_id)
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
        verifier.fail('artifact_hashes', 'raw output parse failure: '
                      + repr(error), run=segment_id)
    evidence.loaded = all(path.is_file() for path in paths.values())
    return evidence


def _freeze_segments(freeze):
    segments = freeze.get('segments') if isinstance(freeze, dict) else None
    result = {}
    if isinstance(segments, dict):
        for segment_id, entry in segments.items():
            if isinstance(entry, dict):
                merged = dict(entry)
                merged.setdefault('segment_id', str(segment_id))
                result[str(segment_id)] = merged
    elif isinstance(segments, list):
        for entry in segments:
            if isinstance(entry, dict) and entry.get('segment_id') is not None:
                result[str(entry['segment_id'])] = dict(entry)
    return result


def _segment_run_plan(entry):
    if not isinstance(entry, dict):
        return None
    for key in ('run_plan', 'plan', 'run_plan_frozen'):
        plan = entry.get(key)
        if isinstance(plan, dict):
            return plan
    if any(key in entry for key in ('case_ids', 'stop_distance_m',
                                    'obs_delay_s')):
        return entry
    return None


def _load_freeze(path, verifier):
    if path is None:
        verifier.missing.add('freeze', 'freeze file argument', 'cli')
        return None
    path = Path(path)
    if not path.is_file():
        verifier.missing.add('freeze', 'freeze file %s' % path, 'cli')
        return None
    try:
        return _load_json(path)
    except (OSError, ValueError) as error:
        verifier.fail('freeze_lineage', 'freeze document parse failure: '
                      + repr(error), run='freeze')
        return None


class ExpectedIndex:
    """Case/segment expected classification lookup (pre-run expectations)."""

    def __init__(self):
        self.cases = {}
        self.segments = {}
        self.payload = None

    @staticmethod
    def _normalize_cases(node):
        result = {}
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    case_id = item.get('case_id') or item.get('id')
                    if case_id is not None:
                        result[str(case_id)] = dict(item)
        elif isinstance(node, dict):
            for case_id, item in node.items():
                if isinstance(item, dict):
                    merged = dict(item)
                    merged.setdefault('case_id', str(case_id))
                    result[str(case_id)] = merged
                elif isinstance(item, str):
                    result[str(case_id)] = {'scenario_class': item}
        return result

    def add_config(self, payload):
        if not isinstance(payload, dict):
            return
        self.payload = payload
        self.cases.update(self._normalize_cases(
            payload.get('cases') or payload.get('expected_cases')))
        segments = payload.get('segments')
        if segments is None:
            segments = payload.get('special_segments')
        if isinstance(segments, dict):
            for segment_id, node in segments.items():
                if not isinstance(node, dict):
                    continue
                cases = self._normalize_cases(node.get('cases'))
                defaults = node.get('defaults')
                defaults = dict(defaults) if isinstance(defaults, dict) else {}
                for key in node:
                    if key in ('cases', 'defaults', 'segment_id'):
                        continue
                    defaults.setdefault(key, node[key])
                self.segments[str(segment_id)] = {
                    'cases': cases, 'defaults': defaults}
        elif isinstance(segments, list):
            for node in segments:
                if not isinstance(node, dict) or node.get('segment_id') is None:
                    continue
                cases = self._normalize_cases(node.get('cases'))
                defaults = {key: value for key, value in node.items()
                            if key not in ('cases', 'segment_id')}
                self.segments[str(node['segment_id'])] = {
                    'cases': cases, 'defaults': defaults}

    def lookup(self, segment_id, case_id):
        spec = dict(self.cases.get(str(case_id)) or {})
        segment = self.segments.get(str(segment_id))
        if segment is not None:
            merged = dict(segment['defaults'])
            merged.update(spec)
            spec = merged
            specific = segment['cases'].get(str(case_id))
            if isinstance(specific, dict):
                spec.update(specific)
            if not spec and segment['cases']:
                spec = dict(segment['defaults'])
        return spec or None

    def segment_spec(self, segment_id):
        segment = self.segments.get(str(segment_id))
        if segment is None:
            return None
        return {'defaults': segment['defaults'],
                'cases': segment['cases']}

    def summary(self):
        return {'case_count': len(self.cases),
                'segments': {key: {'case_count': len(value['cases']),
                                   'defaults': sorted(value['defaults'])}
                             for key, value in self.segments.items()}}


class BrakeModel:
    """Frozen brake model (plan section 3): piecewise linear in speed only."""

    def __init__(self, payload, path):
        self.payload = payload if isinstance(payload, dict) else {}
        self.path = str(path) if path is not None else None
        self.points = []
        self.supported_min = None
        self.supported_max = None
        self.loaded = False
        self.valid = False

    def load(self, verifier):
        payload = self.payload
        label = 'brake_model'
        if not payload:
            verifier.missing.add(label, 'brake model document', self.path or '')
            return self
        schema = payload.get('schema_version')
        if schema != BRAKE_MODEL_SCHEMA:
            verifier.fail('freeze_lineage', 'brake model schema_version mismatch',
                          run=label, field='schema_version',
                          expected=BRAKE_MODEL_SCHEMA, actual=schema)
        self.model_id = payload.get('model_id')
        if not self.model_id:
            verifier.missing.add(label, 'model_id', 'brake model')
        points = payload.get('points')
        if not isinstance(points, list) or not points:
            verifier.missing.add(label, 'points', 'brake model')
        else:
            grouped = {}
            for item in points:
                if not isinstance(item, dict):
                    verifier.missing.add(label, 'points[]', 'brake model')
                    continue
                speed = _fnum(item.get('speed_mps'))
                distance = _fnum(item.get('brake_distance_m'))
                stop_time = _fnum(item.get('stop_time_s'))
                if speed is None or distance is None:
                    verifier.missing.add(
                        label, 'points[].speed_mps/brake_distance_m',
                        'brake model')
                    continue
                key = round(speed, 9)
                entry = grouped.setdefault(
                    key, {'speed_mps': speed, 'brake_distance_m': distance,
                          'stop_time_s': stop_time})
                # Duplicate speed levels are consolidated conservatively (max).
                if distance > entry['brake_distance_m']:
                    entry['brake_distance_m'] = distance
                if stop_time is not None and (entry['stop_time_s'] is None
                                              or stop_time > entry['stop_time_s']):
                    entry['stop_time_s'] = stop_time
            self.points = [grouped[key] for key in sorted(grouped)]
        support = payload.get('supported_speed_range_mps')
        if _vec(support, 2) is None:
            verifier.missing.add(label, 'supported_speed_range_mps',
                                 'brake model')
        else:
            self.supported_min, self.supported_max = _vec(support, 2)
        interpolation = payload.get('interpolation')
        if interpolation != 'piecewise_linear_in_speed':
            verifier.fail('freeze_lineage',
                          'brake model interpolation must be '
                          'piecewise_linear_in_speed (no other rule is '
                          'supported)', run=label, field='interpolation',
                          expected='piecewise_linear_in_speed',
                          actual=interpolation)
        extrapolation = payload.get('extrapolation')
        if extrapolation != 'forbidden':
            verifier.fail('freeze_lineage',
                          'brake model extrapolation must be forbidden', run=label,
                          field='extrapolation', expected='forbidden',
                          actual=extrapolation)
        source = payload.get('source')
        if not isinstance(source, dict):
            verifier.missing.add(label, 'source', 'brake model')
        else:
            for key in ('path', 'sha256'):
                if not source.get(key):
                    verifier.missing.add(label, 'source.' + key, 'brake model')
        self.loaded = True
        self.valid = bool(self.points) and self.supported_min is not None \
            and self.supported_max is not None
        if self.valid:
            verifier.ok('freeze_lineage', 'brake model loaded (%d points, '
                        'support %.6f..%.6f m/s)'
                        % (len(self.points), self.supported_min,
                           self.supported_max))
        return self

    def interpolate(self, speed):
        """Return (brake_distance_m, stop_time_s) or None when out of support."""
        if not self.valid or speed is None:
            return None
        if speed < self.supported_min - 1e-9 or speed > self.supported_max + 1e-9:
            return None
        if len(self.points) == 1:
            point = self.points[0]
            return point['brake_distance_m'], point['stop_time_s']
        for left, right in zip(self.points, self.points[1:]):
            if speed <= right['speed_mps'] + 1e-12:
                span = right['speed_mps'] - left['speed_mps']
                if span <= 1e-12:
                    return right['brake_distance_m'], right['stop_time_s']
                ratio = (speed - left['speed_mps']) / span
                distance = left['brake_distance_m'] + ratio * (
                    right['brake_distance_m'] - left['brake_distance_m'])
                left_time = left.get('stop_time_s')
                right_time = right.get('stop_time_s')
                stop_time = None
                if left_time is not None and right_time is not None:
                    stop_time = left_time + ratio * (right_time - left_time)
                return distance, stop_time
        last = self.points[-1]
        return last['brake_distance_m'], last.get('stop_time_s')


def _load_brake_model(path, verifier):
    model = BrakeModel({}, path)
    if path is None:
        verifier.missing.add('brake_model', 'brake model argument', 'cli')
        return model
    if not Path(path).is_file():
        verifier.missing.add('brake_model', 'brake model file %s' % path, 'cli')
        return model
    try:
        model.payload = _load_json(path)
    except (OSError, ValueError) as error:
        verifier.fail('freeze_lineage', 'brake model parse failure: '
                      + repr(error), run='brake_model')
        return model
    return model.load(verifier)


# ---------------------------------------------------------------------------
# schema completeness
# ---------------------------------------------------------------------------

def _require_keys(verifier, label, node, keys, prefix, example):
    if not isinstance(node, dict):
        verifier.missing.add(label, prefix, example)
        return
    for key in keys:
        if key not in node:
            verifier.missing.add(label, prefix + '.' + key, example)


def verify_manifest_schema(evidence, verifier):
    label = evidence.label
    manifest = evidence.manifest
    if not isinstance(manifest, dict):
        verifier.missing.add(label, 'manifest.json document', label)
        return
    _require_keys(verifier, label, manifest, MANIFEST_REQUIRED_KEYS,
                  'manifest', label)
    # The plan records a single pre-run plan per run under one of these names.
    plan = None
    for key in ('boundary_plan', 'run_plan', 'latency_plan'):
        if isinstance(manifest.get(key), dict):
            plan = manifest[key]
            break
    if plan is None:
        verifier.missing.add(label, 'manifest.boundary_plan', label)
    else:
        for key in ('role', 'segment_id', 'case_ids', 'methods',
                    'execution_path', 'obs_delay_s', 'action_delay_s',
                    'ttl_ms', 'stop_distance_m', 'post_abort_observe_s',
                    'cases_sha256'):
            if key not in plan:
                verifier.missing.add(label, 'manifest.boundary_plan.' + key,
                                     label)
    algorithm = manifest.get('clearance_algorithm')
    if not isinstance(algorithm, dict):
        verifier.missing.add(label, 'manifest.clearance_algorithm', label)
    else:
        for key in ('id', 'version'):
            if not algorithm.get(key):
                verifier.missing.add(
                    label, 'manifest.clearance_algorithm.' + key, label)
    envelope_policy = manifest.get('envelope_policy')
    if not isinstance(envelope_policy, dict):
        verifier.missing.add(label, 'manifest.envelope_policy', label)
    else:
        for key in ('robot_envelope', 'obstacle_envelope'):
            if key not in envelope_policy:
                verifier.missing.add(label, 'manifest.envelope_policy.' + key,
                                     label)
    body = manifest.get('body_envelope')
    if not isinstance(body, dict):
        verifier.missing.add(label, 'manifest.body_envelope', label)
    else:
        for key in ('half_extents_m', 'source', 'measured_prim'):
            if not body.get(key):
                verifier.missing.add(label, 'manifest.body_envelope.' + key,
                                     label)
    brake_pointer = manifest.get('brake_model')
    if isinstance(brake_pointer, dict):
        for key in ('model_id', 'sha256'):
            if not brake_pointer.get(key):
                verifier.missing.add(label, 'manifest.brake_model.' + key,
                                     label)
    elif not manifest.get('brake_model_sha256'):
        verifier.missing.add(label, 'manifest.brake_model_sha256', label)
    vehicle = manifest.get('vehicle_config')
    if isinstance(vehicle, dict):
        for key in ('path', 'sha256'):
            if not vehicle.get(key):
                verifier.missing.add(label, 'manifest.vehicle_config.' + key,
                                     label)
    elif not (manifest.get('vehicle_config_sha256')
              or (isinstance(plan, dict) and plan.get('vehicle_config_sha256'))):
        verifier.missing.add(label, 'manifest.vehicle_config_sha256', label)
    pointer = manifest.get('freeze')
    if not isinstance(pointer, dict):
        verifier.missing.add(label, 'manifest.freeze', label)
    else:
        for key in ('path', 'sha256', 'schema_version', 'frozen_at',
                    'code_commit'):
            if not pointer.get(key):
                verifier.missing.add(label, 'manifest.freeze.' + key, label)
    if not isinstance(manifest.get('outputs_sha256'), dict):
        verifier.missing.add(label, 'manifest.outputs_sha256', label)
    gui = manifest.get('gui_evidence')
    if not isinstance(gui, dict):
        verifier.missing.add(label, 'manifest.gui_evidence', label)
    if not manifest.get('episode_ids'):
        verifier.missing.add(label, 'manifest.episode_ids', label)
    # Contact evidence validity: a zero contact force must not by itself be read
    # as "no contact".  The run declares either a real force sensor or the
    # Lead-aligned kinematic sphere-overlap inference mode; the per-row
    # ``contact_evidence`` fields (checked separately) are the evidence.
    if _is_boundary_segment(evidence.segment_id):
        sensor = manifest.get('contact_sensor')
        if not isinstance(sensor, dict):
            verifier.missing.add(label, 'manifest.contact_sensor', label)
        else:
            mode = sensor.get('mode')
            if mode not in CONTACT_EVIDENCE_MODES:
                verifier.fail('contact_sensor_evidence',
                              'manifest.contact_sensor.mode is not a declared '
                              'contact-evidence mode', run=label,
                              field='contact_sensor.mode',
                              expected=list(CONTACT_EVIDENCE_MODES),
                              actual=mode)
            if not isinstance(sensor.get('valid'), bool):
                verifier.missing.add(label, 'manifest.contact_sensor.valid',
                                     label)
            elif sensor.get('valid') is not True:
                verifier.missing.add(
                    label, 'manifest.contact_sensor.valid=true (contact evidence '
                           'is not valid: a zero force cannot be concluded as '
                           'NO_CONTACT)', label)
            if mode == 'sphere_overlap_inference':
                if sensor.get('force_sensor_available') is not False:
                    verifier.fail('contact_sensor_evidence',
                                  'sphere_overlap_inference requires '
                                  'force_sensor_available=false', run=label,
                                  field='contact_sensor.force_sensor_available',
                                  expected=False,
                                  actual=sensor.get('force_sensor_available'))
                if not sensor.get('reason'):
                    verifier.missing.add(
                        label, 'manifest.contact_sensor.reason', label)
                rule = sensor.get('inference_rule')
                if not isinstance(rule, dict):
                    verifier.missing.add(
                        label, 'manifest.contact_sensor.inference_rule', label)
                else:
                    overlap = _fnum(rule.get('sphere_overlap_m_gt'))
                    if not _close(overlap, CONTACT_OVERLAP_M, GEOM_TOL):
                        verifier.fail(
                            'contact_sensor_evidence',
                            'inference rule threshold is not the frozen '
                            'sphere_overlap_m_gt=0.02', run=label,
                            field='contact_sensor.inference_rule.'
                                  'sphere_overlap_m_gt',
                            expected=CONTACT_OVERLAP_M, actual=overlap)
                    if not rule.get('conservative_radii'):
                        verifier.missing.add(
                            label, 'manifest.contact_sensor.inference_rule.'
                                   'conservative_radii', label)
            else:
                for key in ('prim_path', 'source'):
                    if not sensor.get(key):
                        verifier.missing.add(
                            label, 'manifest.contact_sensor.' + key, label)
    if manifest.get('clearance_schema_version') != CLEARANCE_SCHEMA_VERSION:
        verifier.fail('schema_completeness',
                      'manifest.clearance_schema_version mismatch', run=label,
                      field='clearance_schema_version',
                      expected=CLEARANCE_SCHEMA_VERSION,
                      actual=manifest.get('clearance_schema_version'))
    if manifest.get('stop_requirement_schema_version') \
            != STOP_REQUIREMENT_SCHEMA_VERSION:
        verifier.fail('schema_completeness',
                      'manifest.stop_requirement_schema_version mismatch',
                      run=label, field='stop_requirement_schema_version',
                      expected=STOP_REQUIREMENT_SCHEMA_VERSION,
                      actual=manifest.get('stop_requirement_schema_version'))
    algorithm = algorithm if isinstance(algorithm, dict) else {}
    if algorithm.get('id') and algorithm.get('id') != CLEARANCE_ALGORITHM_ID:
        verifier.fail('schema_completeness',
                      'manifest.clearance_algorithm.id mismatch', run=label,
                      field='clearance_algorithm.id',
                      expected=CLEARANCE_ALGORITHM_ID,
                      actual=algorithm.get('id'))
    if algorithm.get('version') \
            and algorithm.get('version') != CLEARANCE_ALGORITHM_VERSION:
        verifier.fail('schema_completeness',
                      'manifest.clearance_algorithm.version mismatch', run=label,
                      field='clearance_algorithm.version',
                      expected=CLEARANCE_ALGORITHM_VERSION,
                      actual=algorithm.get('version'))


def _require_numeric_or_allowed(verifier, label, node, key, prefix, example,
                                allow_none, reason=None):
    value = node.get(key) if isinstance(node, dict) else None
    if value is None:
        if allow_none:
            return
        verifier.missing.add(label, prefix + '.' + key, example)
        return
    if not _num(value):
        verifier.missing.add(label, prefix + '.' + key, example)


def _manifest_plan(evidence):
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    for key in ('boundary_plan', 'run_plan', 'latency_plan'):
        if isinstance(manifest.get(key), dict):
            return manifest[key]
    return {}


def verify_episode_schema(evidence, verifier):
    label = evidence.label
    role = _manifest_plan(evidence).get('role')
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            verifier.fail('schema_completeness', 'episode row is not an object',
                          run=label)
            continue
        example = 'episode %s' % episode.get('episode_id')
        _require_keys(verifier, label, episode, EPISODE_KEYS, 'episodes[]',
                      example)
        business = episode.get('business_outcome')
        if business is not None and business not in BUSINESS_OUTCOMES:
            verifier.fail('schema_completeness',
                          'invalid episodes[].business_outcome', run=label,
                          episode_id=episode.get('episode_id'),
                          field='business_outcome',
                          expected=list(BUSINESS_OUTCOMES), actual=business)
        physical = episode.get('physical_outcome')
        if physical is not None and physical not in PHYSICAL_OUTCOMES:
            verifier.fail('schema_completeness',
                          'invalid episodes[].physical_outcome', run=label,
                          episode_id=episode.get('episode_id'),
                          field='physical_outcome',
                          expected=list(PHYSICAL_OUTCOMES), actual=physical)
        scenario_class = episode.get('scenario_class')
        if scenario_class is not None and scenario_class not in SCENARIO_CLASSES \
                and role in ('boundary', 'main', None):
            # Only boundary runs use the 8-class boundary vocabulary; special
            # and regression runs keep their original map/fault case classes.
            verifier.fail('schema_completeness',
                          'invalid episodes[].scenario_class', run=label,
                          episode_id=episode.get('episode_id'),
                          field='scenario_class',
                          expected=list(SCENARIO_CLASSES),
                          actual=scenario_class)
        metrics = episode.get('metrics')
        if not isinstance(metrics, dict):
            verifier.missing.add(label, 'episodes[].metrics', example)
            continue
        for key in EPISODE_METRIC_KEYS:
            if key not in metrics:
                verifier.missing.add(label, 'episodes[].metrics.' + key,
                                     example)
        contact_mode = _contact_mode(evidence)
        if contact_mode in CONTACT_EVIDENCE_MODES:
            summary = metrics.get('contact_evidence_summary')
            if not isinstance(summary, dict):
                verifier.missing.add(
                    label, 'episodes[].metrics.contact_evidence_summary',
                    example)
            else:
                for key in ('max_sensor_force_n', 'max_sphere_overlap_m',
                            'inferred_contact',
                            'first_inferred_contact_time_s', 'radii_sum_m'):
                    if key not in summary:
                        verifier.missing.add(
                            label, 'episodes[].metrics.contact_evidence_summary.'
                                   + key, example)
        envelope = metrics.get('conservative_envelope')
        if isinstance(envelope, dict):
            robot_keys = ('robot_radius_m', 'radius_m')
            if not any(envelope.get(key) is not None for key in robot_keys):
                verifier.missing.add(
                    label, 'episodes[].metrics.conservative_envelope.'
                    'robot_radius_m', example)
            if not (envelope.get('robot_source') or envelope.get('source')):
                verifier.missing.add(
                    label, 'episodes[].metrics.conservative_envelope.'
                    'robot_source', example)
            for key in ('attitude_scope', 'obstacle_radius_m',
                        'obstacle_source'):
                if key not in envelope:
                    verifier.missing.add(
                        label, 'episodes[].metrics.conservative_envelope.'
                        + key, example)
        extremes = metrics.get('stop_requirement_extremes')
        if isinstance(extremes, dict):
            for key in ('min_margin_m', 'unsupported_steps',
                        'unsupported_reasons', 'max_robot_speed_mps'):
                if key not in extremes:
                    verifier.missing.add(
                        label, 'episodes[].metrics.stop_requirement_extremes.'
                        + key, example)
        post = metrics.get('post_abort')
        phase_summary = episode.get('phase_summary')
        post_rows = (int(phase_summary.get('POST_ABORT') or 0)
                     if isinstance(phase_summary, dict) else 0)
        if post_rows > 0 and not isinstance(post, dict):
            verifier.missing.add(label, 'episodes[].metrics.post_abort', example)
        if isinstance(post, dict):
            for key in ('steps', 'residual_distance_m', 'time_to_stop_s',
                        'contact'):
                if key not in post:
                    verifier.missing.add(
                        label, 'episodes[].metrics.post_abort.' + key, example)


def _contact_mode(evidence):
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    sensor = manifest.get('contact_sensor')
    if isinstance(sensor, dict):
        return sensor.get('mode')
    return None


def verify_step_schema(evidence, verifier):
    label = evidence.label
    contact_mode = _contact_mode(evidence)
    for episode_id, rows in evidence.steps_by_episode.items():
        for row in rows:
            example = _example(row)
            _require_keys(verifier, label, row, STEP_TOP_KEYS, 'steps[]',
                          example)
            if row.get('phase') is not None \
                    and row.get('phase') not in PHASES:
                verifier.fail('schema_completeness',
                              'invalid steps[].phase', run=label,
                              episode_id=episode_id, step=row.get('step'),
                              field='phase', expected=list(PHASES),
                              actual=row.get('phase'))
            state = row.get('supervisor_state')
            if state is not None and state not in SUPERVISOR_STATES:
                verifier.fail('schema_completeness',
                              'invalid steps[].supervisor_state', run=label,
                              episode_id=episode_id, step=row.get('step'),
                              field='supervisor_state',
                              expected=list(SUPERVISOR_STATES), actual=state)
            action = row.get('supervisor_action')
            if action is not None and action not in SUPERVISOR_ACTIONS:
                verifier.fail('schema_completeness',
                              'invalid steps[].supervisor_action', run=label,
                              episode_id=episode_id, step=row.get('step'),
                              field='supervisor_action',
                              expected=list(SUPERVISOR_ACTIONS), actual=action)
            for key in ('clock', 'transport', 'applied'):
                if not isinstance(row.get(key), dict):
                    verifier.missing.add(label, 'steps[].' + key, example)
            clock = row.get('clock')
            if isinstance(clock, dict):
                for key in CLOCK_KEYS:
                    if key not in clock:
                        verifier.missing.add(label, 'steps[].clock.' + key,
                                             example)
            transport = row.get('transport')
            if isinstance(transport, dict):
                for key in TRANSPORT_KEYS:
                    if key not in transport:
                        verifier.missing.add(label,
                                             'steps[].transport.' + key, example)
            if contact_mode in CONTACT_EVIDENCE_MODES:
                evidence_row = row.get('contact_evidence')
                if not isinstance(evidence_row, dict):
                    verifier.missing.add(label, 'steps[].contact_evidence',
                                         example)
                else:
                    for key in CONTACT_EVIDENCE_KEYS:
                        if key not in evidence_row:
                            verifier.missing.add(
                                label, 'steps[].contact_evidence.' + key,
                                example)
            if row.get('phase') == 'POST_ABORT':
                continue
            if row.get('observation_valid') is True \
                    and not isinstance(row.get('clearance'), dict):
                verifier.missing.add(
                    label, 'steps[].clearance on an observation-valid RUN row',
                    example)
            if isinstance(row.get('clearance'), dict):
                _verify_clearance_presence(verifier, label, row, example)
            if not isinstance(row.get('stop_requirement'), dict):
                verifier.missing.add(
                    label, 'steps[].stop_requirement on a RUN row', example)
            elif isinstance(row.get('stop_requirement'), dict):
                _verify_stop_requirement_presence(verifier, label, row, example)


def _verify_clearance_presence(verifier, label, row, example):
    record = row.get('clearance')
    _require_keys(verifier, label, record, CLEARANCE_TOP_KEYS, 'steps[].clearance',
                  example)
    valid = (record.get('validity') or {}).get('valid') \
        if isinstance(record.get('validity'), dict) else None
    _require_keys(verifier, label, record.get('algorithm'),
                  CLEARANCE_ALGORITHM_KEYS, 'steps[].clearance.algorithm',
                  example)
    for key in CLEARANCE_INPUT_KEYS:
        if not isinstance(record.get('inputs'), dict) \
                or key not in record['inputs']:
            verifier.missing.add(label, 'steps[].clearance.inputs.' + key,
                                 example)
    if valid is not False:
        _require_keys(verifier, label, record.get('prediction'),
                      CLEARANCE_PREDICTION_KEYS,
                      'steps[].clearance.prediction', example)
        _require_keys(verifier, label, record.get('metrics'),
                      CLEARANCE_METRIC_KEYS, 'steps[].clearance.metrics',
                      example)
    envelopes = record.get('envelopes')
    if not isinstance(envelopes, dict):
        verifier.missing.add(label, 'steps[].clearance.envelopes', example)
    else:
        _require_keys(verifier, label, envelopes.get('robot'),
                      CLEARANCE_ROBOT_ENV_KEYS,
                      'steps[].clearance.envelopes.robot', example)
        _require_keys(verifier, label, envelopes.get('obstacle'),
                      CLEARANCE_OBSTACLE_ENV_KEYS,
                      'steps[].clearance.envelopes.obstacle', example)
    _require_keys(verifier, label, record.get('validity'),
                  CLEARANCE_VALIDITY_KEYS, 'steps[].clearance.validity',
                  example)
    _require_keys(verifier, label, record.get('applicability'),
                  CLEARANCE_APPLICABILITY_KEYS,
                  'steps[].clearance.applicability', example)


def _verify_stop_requirement_presence(verifier, label, row, example):
    record = row.get('stop_requirement')
    _require_keys(verifier, label, record, STOP_REQUIREMENT_TOP_KEYS,
                  'steps[].stop_requirement', example)
    reasons = record.get('status_reasons')
    if not isinstance(reasons, list):
        verifier.missing.add(label,
                             'steps[].stop_requirement.status_reasons', example)
    _require_keys(verifier, label, record.get('inputs'),
                  STOP_REQUIREMENT_INPUT_KEYS, 'steps[].stop_requirement.inputs',
                  example)
    _require_keys(verifier, label, record.get('terms'),
                  STOP_REQUIREMENT_TERM_KEYS, 'steps[].stop_requirement.terms',
                  example)
    status = record.get('status')
    if status is not None and status not in ('SUPPORTED', 'UNSUPPORTED'):
        verifier.fail('schema_completeness',
                      'invalid stop_requirement.status', run=label,
                      episode_id=row.get('episode_id'), step=row.get('step'),
                      field='stop_requirement.status',
                      expected=['SUPPORTED', 'UNSUPPORTED'], actual=status)
    basis = record.get('basis')
    if basis is not None and basis not in STOP_BASES:
        verifier.fail('schema_completeness',
                      'invalid stop_requirement.basis', run=label,
                      episode_id=row.get('episode_id'), step=row.get('step'),
                      field='stop_requirement.basis', expected=list(STOP_BASES),
                      actual=basis)


# ---------------------------------------------------------------------------
# freeze / artifacts / GUI lineage
# ---------------------------------------------------------------------------

def _worktree_digest_candidates(repo_root):
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


def check_freeze_document(freeze, freeze_path, verifier, repo_root):
    name = 'freeze_lineage'
    if not isinstance(freeze, dict):
        return
    schema = freeze.get('schema_version')
    if schema != BOUNDARY_FREEZE_SCHEMA:
        verifier.fail(name, 'freeze schema_version is not the boundary pre-run '
                      'schema', run='freeze', field='schema_version',
                      expected=BOUNDARY_FREEZE_SCHEMA, actual=schema)
    status = freeze.get('status')
    if status != 'PRE_RUN_FROZEN':
        verifier.fail(name, 'freeze status is not PRE_RUN_FROZEN (recorded '
                      'evidence cannot be upgraded)', run='freeze',
                      field='status', expected='PRE_RUN_FROZEN', actual=status)
    frozen_at = _parse_iso(freeze.get('frozen_at'))
    if frozen_at is None:
        verifier.missing.add('freeze', 'frozen_at', 'freeze')
    if not freeze.get('code_commit'):
        verifier.missing.add('freeze', 'code_commit', 'freeze')
    worktree = freeze.get('worktree_state')
    if not isinstance(worktree, dict):
        verifier.missing.add('freeze', 'worktree_state', 'freeze')
    else:
        for key in ('tracked_paths', 'status_text_sha256', 'clean'):
            if worktree.get(key) is None:
                verifier.missing.add('freeze', 'worktree_state.' + key,
                                     'freeze')
    if not isinstance(freeze.get('body_envelope'), dict):
        verifier.missing.add('freeze', 'body_envelope', 'freeze')
    segments = _freeze_segments(freeze)
    if not segments:
        verifier.missing.add('freeze', 'segments', 'freeze')
    for segment_id, entry in segments.items():
        plan = _segment_run_plan(entry)
        if plan is None:
            verifier.missing.add('freeze',
                                 'segments[%s].run_plan' % segment_id, 'freeze')
            continue
        for key in ('role', 'segment_id', 'case_ids', 'methods',
                    'execution_path', 'obs_delay_s', 'action_delay_s',
                    'ttl_ms', 'stop_distance_m', 'post_abort_observe_s'):
            if key not in plan:
                verifier.missing.add(
                    'freeze', 'segments[%s].run_plan.%s' % (segment_id, key),
                    'freeze')
        if plan.get('role') is not None \
                and plan.get('role') not in ('boundary', 'special',
                                             'regression', 'main'):
            verifier.fail('freeze_lineage', 'unknown run_plan.role (expected '
                          'boundary/special/regression)', run='freeze',
                          field='segments[%s].run_plan.role' % segment_id,
                          expected=['boundary', 'special', 'regression'],
                          actual=plan.get('role'))
        for key in ('cases_sha256', 'expected_sha256', 'brake_model_sha256',
                    'vehicle_config_sha256'):
            if not plan.get(key) and not entry.get(key) and not freeze.get(key):
                verifier.missing.add(
                    'freeze', 'segments[%s].run_plan.%s' % (segment_id, key),
                    'freeze')
    # The freeze may carry the shared input file references either globally or
    # per segment; a reference must exist somewhere and be hashed.
    run_plans = [_segment_run_plan(entry) or {} for entry in segments.values()]

    def _freeze_value(key):
        value = freeze.get(key)
        if value:
            return value
        for plan in run_plans:
            if plan.get(key):
                return plan[key]
        return None

    for key, file_key in (('cases', 'cases_file'), ('expected', 'expected_file'),
                          ('brake_model', 'brake_model_file')):
        if not _freeze_value(file_key):
            verifier.missing.add('freeze', file_key, 'freeze')
        elif not _freeze_value(key + '_sha256'):
            verifier.missing.add('freeze', key + '_sha256', 'freeze')
    if not freeze.get('frozen_at'):
        verifier.missing.add('freeze', 'frozen_at', 'freeze')
    if isinstance(freeze_path, Path) and freeze_path.is_file() \
            and freeze.get('artifact_sha256') \
            and freeze['artifact_sha256'] != _sha256_file(freeze_path):
        verifier.fail(name, 'freeze.artifact_sha256 does not match the freeze '
                      'file', run='freeze', field='artifact_sha256',
                      expected=_sha256_file(freeze_path),
                      actual=freeze.get('artifact_sha256'))
    if repo_root is not None and (Path(repo_root) / '.git').exists() \
            and isinstance(worktree, dict) and worktree.get('status_text_sha256'):
        candidates = _worktree_digest_candidates(repo_root)
        if candidates is None:
            verifier.note(name, 'INFO: git status unavailable; worktree digest '
                          'not recomputed')
        elif worktree['status_text_sha256'] not in candidates:
            verifier.note(name, 'INFO: current worktree digest differs from the '
                          'recorded freeze digest (expected after the post-run '
                          'commit; not a PASS criterion)')
    verifier.ok(name, 'freeze document parsed')


def check_freeze_files(freeze, expected_path, brake_model_path, verifier,
                       repo_root):
    """Hash the freeze-referenced cases/expected/brake-model files on disk."""
    name = 'artifact_hashes'
    if not isinstance(freeze, dict):
        return
    pairs = []
    for file_key, sha_key in (('cases_file', 'cases_sha256'),
                              ('expected_file', 'expected_sha256'),
                              ('brake_model_file', 'brake_model_sha256')):
        if freeze.get(file_key) and freeze.get(sha_key):
            pairs.append((freeze.get(file_key), freeze.get(sha_key)))
        for entry in _freeze_segments(freeze).values():
            plan = _segment_run_plan(entry) or {}
            file_name = plan.get(file_key) or entry.get(file_key)
            digest = plan.get(sha_key) or entry.get(sha_key)
            if file_name and digest:
                pairs.append((file_name, digest))
    seen = set()
    for file_name, recorded in pairs:
        key = (str(file_name), str(recorded))
        if key in seen:
            continue
        seen.add(key)
        path = Path(str(file_name))
        if not path.is_absolute():
            path = Path(repo_root) / path
        if not path.is_file():
            verifier.missing.add('freeze', 'file exists (%s)' % path, 'freeze')
            continue
        actual = _sha256_file(path)
        if str(recorded).lower() != actual:
            verifier.fail(name, 'freeze file hash does not match the file on '
                          'disk', run='freeze', field=str(file_name),
                          expected=actual, actual=recorded)
        else:
            verifier.ok(name, 'freeze file hash verified (%s)' % path.name)
    if freeze.get('expected_file') and expected_path is not None:
        expected_name = Path(str(freeze['expected_file']))
        provided = Path(expected_path)
        if expected_name.name != provided.name:
            verifier.note(name, 'expected file argument %s differs from the '
                          'freeze %s' % (provided.name, expected_name.name))


def check_run_lineage(evidence, freeze, entry, freeze_path, verifier,
                      expected_path, brake_model_path, repo_root=None):
    name = 'freeze_lineage'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    if freeze is None or entry is None:
        return
    pointer = manifest.get('freeze')
    if not isinstance(pointer, dict):
        verifier.missing.add(label, 'manifest.freeze', label)
    else:
        if freeze_path is not None and Path(freeze_path).is_file():
            actual = _sha256_file(freeze_path)
            if str(pointer.get('sha256') or '').lower() != actual:
                verifier.fail(name, 'manifest.freeze.sha256 does not match the '
                              'freeze file', run=label,
                              field='freeze.sha256', expected=actual,
                              actual=pointer.get('sha256'))
            else:
                verifier.ok(name, 'freeze file sha256 verified for ' + label)
        if pointer.get('schema_version') \
                and pointer.get('schema_version') != BOUNDARY_FREEZE_SCHEMA:
            verifier.fail(name, 'manifest.freeze.schema_version mismatch',
                          run=label, field='freeze.schema_version',
                          expected=BOUNDARY_FREEZE_SCHEMA,
                          actual=pointer.get('schema_version'))
        frozen = _parse_iso(pointer.get('frozen_at'))
        started = _parse_iso(manifest.get('started_at'))
        if frozen is None:
            verifier.missing.add(label, 'manifest.freeze.frozen_at', label)
        if started is None:
            verifier.missing.add(label, 'manifest.started_at', label)
        if frozen is not None and started is not None:
            if frozen > started:
                verifier.fail(name, 'freeze.frozen_at is after manifest.'
                              'started_at (freeze must precede the run)',
                              run=label, field='frozen_at',
                              expected='<= ' + str(started), actual=str(frozen))
            else:
                verifier.ok(name, 'frozen_at <= started_at')
        pointer_commit = str(pointer.get('code_commit') or '').lower()
        manifest_commit = str(manifest.get('code_commit') or '').lower()
        if pointer_commit and manifest_commit and not (
                manifest_commit.startswith(pointer_commit)
                or pointer_commit.startswith(manifest_commit)):
            verifier.fail(name, 'manifest.code_commit does not match '
                          'freeze.code_commit', run=label,
                          field='code_commit', expected=pointer_commit,
                          actual=manifest_commit)
    # Per-segment run plan: frozen plan vs recorded manifest plan.
    plan = None
    for key in ('boundary_plan', 'run_plan', 'latency_plan'):
        if isinstance(manifest.get(key), dict):
            plan = manifest[key]
            break
    frozen_plan = _segment_run_plan(entry)
    if frozen_plan is not None:
        if plan is None:
            verifier.missing.add(label, 'manifest.boundary_plan', label)
        else:
            for key in PLAN_COMPARE_KEYS:
                if key not in frozen_plan:
                    continue
                expected = frozen_plan[key]
                actual = plan.get(key)
                if key in ('case_ids', 'methods'):
                    if not _same_sequence(actual, expected):
                        verifier.fail(name, 'frozen run plan field disagrees '
                                      'with the manifest', run=label,
                                      field='boundary_plan.' + key,
                                      expected=expected, actual=actual)
                elif _num(expected):
                    if not _close(actual, expected, PLAN_TOL):
                        verifier.fail(name, 'frozen run plan field disagrees '
                                      'with the manifest', run=label,
                                      field='boundary_plan.' + key,
                                      expected=expected, actual=actual)
                elif isinstance(expected, str):
                    if str(actual or '') != expected:
                        verifier.fail(name, 'frozen run plan field disagrees '
                                      'with the manifest', run=label,
                                      field='boundary_plan.' + key,
                                      expected=expected, actual=actual)
            if plan.get('case_ids') is not None:
                case_ids = [str(item) for item in plan.get('case_ids') or []
                            if item]
                if not case_ids:
                    verifier.missing.add(
                        label, 'manifest.boundary_plan.case_ids', label)
    # Hash/plan case identifiers.
    frozen_cases = frozen_plan.get('case_ids') if isinstance(frozen_plan, dict) \
        else None
    manifest_cases = plan.get('case_ids') if isinstance(plan, dict) else None
    if frozen_cases is not None and manifest_cases is not None \
            and not _same_sequence(manifest_cases, frozen_cases):
        verifier.fail(name, 'manifest case_ids do not match the frozen plan',
                      run=label, field='case_ids', expected=frozen_cases,
                      actual=manifest_cases)
    # Manifest / freeze / disk hash agreement for this run's inputs.
    if isinstance(plan, dict):
        cases_file = plan.get('cases_file')
        if cases_file:
            path = Path(str(cases_file))
            if not path.is_absolute():
                path = Path(repo_root or '.') / path
            recorded = plan.get('cases_sha256')
            if path.is_file() and recorded:
                actual = _sha256_file(path)
                if str(recorded).lower() != actual:
                    verifier.fail(name, 'manifest.boundary_plan.cases_sha256 '
                                  'does not match the cases file', run=label,
                                  field='boundary_plan.cases_sha256',
                                  expected=actual, actual=recorded)
    if expected_path is not None:
        recorded = manifest.get('expected_sha256') \
            or (plan.get('expected_sha256') if isinstance(plan, dict) else None)
        if recorded and Path(expected_path).is_file():
            actual = _sha256_file(expected_path)
            if str(recorded).lower() != actual:
                verifier.fail(name, 'manifest expected_sha256 does not match the '
                              'expected file', run=label,
                              field='expected_sha256', expected=actual,
                              actual=recorded)
    if brake_model_path is not None:
        recorded = manifest.get('brake_model_sha256')
        if not recorded and isinstance(manifest.get('brake_model'), dict):
            recorded = manifest['brake_model'].get('sha256')
        if recorded and Path(brake_model_path).is_file():
            actual = _sha256_file(brake_model_path)
            if str(recorded).lower() != actual:
                verifier.fail(name, 'manifest.brake_model_sha256 does not match '
                              'the brake model file', run=label,
                              field='brake_model_sha256', expected=actual,
                              actual=recorded)


def _position_push_anomalies(evidence):
    """Detect robot displacement that cannot be explained by commanded motion.

    A kinematic obstacle can push the robot even when the contact sensor records
    zero force; such rows must not be read as NO_CONTACT.
    """
    anomalies = []
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        rows = _sorted_rows(evidence.steps_by_episode.get(
            episode.get('episode_id'), []))
        previous = None
        for row in rows:
            position = _vec(row.get('position_world_m'))
            time_s = _fnum(row.get('time_s'))
            speed = _fnum(row.get('speed_mps'))
            if position is None or time_s is None:
                continue
            if previous is not None:
                previous_position, previous_time, previous_speed = previous
                delta_t = time_s - previous_time
                if delta_t <= 0:
                    continue
                displacement = math.dist(previous_position, position)
                explained = max(previous_speed or 0.0, speed or 0.0) * delta_t
                if displacement > explained + max(0.01, 0.1 * explained) \
                        and (speed is None or speed <= STOP_SPEED_MPS + 0.02):
                    anomalies.append({
                        'episode_id': episode.get('episode_id'),
                        'step': row.get('step'),
                        'displacement_m': displacement,
                        'explained_m': explained})
            previous = (position, time_s, speed)
    return anomalies


def check_contact_sensor(evidence, verifier):
    """Validate the contact-evidence mode declared by the run.

    Two honest modes are accepted:
    * ``sphere_overlap_inference`` -- the environment has no usable force sensor;
      contact is inferred from conservative sphere overlap (> 0.02 m) and the
      per-row ``contact_evidence`` is checked separately.
    * ``force_sensor`` -- a real contact force sensor is declared.
    """
    name = 'contact_sensor_evidence'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    if not _is_boundary_segment(evidence.segment_id):
        verifier.ok(name, 'not a boundary segment: contact-evidence mode is '
                    'checked on boundary runs only')
        return
    sensor = manifest.get('contact_sensor')
    if not isinstance(sensor, dict):
        verifier.missing.add(label, 'manifest.contact_sensor', label)
        return
    valid = sensor.get('valid')
    mode = sensor.get('mode')
    if valid is not True:
        anomalies = _position_push_anomalies(evidence)
        if anomalies:
            verifier.missing.add(
                label, 'contact evidence is invalid and %d row(s) show robot '
                       'displacement not explained by commanded speed (e.g. %s): '
                       'a zero force cannot be concluded as NO_CONTACT'
                % (len(anomalies), anomalies[0]))
        verifier.note(name, 'contact evidence is not declared valid: no '
                      'NO_CONTACT conclusion is drawn from a zero force '
                      '(contact-dependent scenarios are INCOMPLETE)')
        return
    if mode == 'sphere_overlap_inference':
        if sensor.get('force_sensor_available') is not False:
            verifier.fail(name, 'sphere_overlap_inference requires '
                          'force_sensor_available=false', run=label,
                          field='contact_sensor.force_sensor_available',
                          expected=False,
                          actual=sensor.get('force_sensor_available'))
        rule = sensor.get('inference_rule')
        rule = rule if isinstance(rule, dict) else {}
        verifier.ok(name, 'kinematic contact inference mode declared '
                    '(sphere_overlap_m > %.3f, force sensor unavailable: %s)'
                    % (CONTACT_OVERLAP_M, sensor.get('reason')))
        if not rule.get('conservative_radii'):
            verifier.missing.add(
                label, 'manifest.contact_sensor.inference_rule.'
                       'conservative_radii', label)
        return
    if mode not in CONTACT_EVIDENCE_MODES:
        verifier.missing.add(label, 'manifest.contact_sensor.mode', label)
        return
    prim = sensor.get('prim_path')
    source = sensor.get('source')
    if not prim:
        verifier.missing.add(label, 'manifest.contact_sensor.prim_path', label)
    if not source:
        verifier.missing.add(label, 'manifest.contact_sensor.source', label)
    if prim and source:
        verifier.ok(name, 'contact force sensor declared (%s via %s)'
                    % (prim, source))


def check_artifacts(evidence, verifier):
    name = 'artifact_hashes'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    outputs = manifest.get('outputs_sha256')
    if not isinstance(outputs, dict) or not outputs:
        verifier.missing.add(label, 'manifest.outputs_sha256', label)
        return
    verified = 0
    for file_name, digest in outputs.items():
        path = evidence.run_dir / str(file_name)
        if not path.is_file():
            verifier.missing.add(label, 'artifact %s' % file_name, label)
            continue
        actual = _sha256_file(path)
        if not isinstance(digest, str) or actual != digest.lower():
            verifier.fail(name, 'artifact hash mismatch', run=label,
                          field=str(file_name), expected=actual,
                          actual=digest)
        else:
            verified += 1
    if verified:
        verifier.ok(name, '%d artifact hashes verified for %s'
                    % (verified, label))


def _check_contact_evidence_row(evidence, episode, row, ctx, verifier, stats):
    """Validate the per-row contact evidence and aggregate the episode stats.

    The frozen inference rule is ``sphere_overlap_m > 0.02`` where
    ``sphere_overlap_m = max(0, radii_sum_m - center_distance_m)`` and
    ``radii_sum_m`` is the conservative sphere sum (robot AABB half diagonal +
    obstacle max(size)/2).  A measured sensor force, when available, is
    validated against the row's contact force; a zero force is never treated as
    NO_CONTACT by itself.
    """
    name = 'contact_sensor_evidence'
    mode = ctx.get('contact_mode')
    if mode not in CONTACT_EVIDENCE_MODES:
        return
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('contact_evidence')
    if not isinstance(record, dict):
        return
    robot_position = _vec(row.get('position_world_m'))
    obstacle_position = _vec(row.get('obstacle_position_world_m'))
    radii_sum = ctx.get('radii_sum_m')
    if robot_position is not None and obstacle_position is not None:
        center = math.dist(robot_position, obstacle_position)
        if not _close(record.get('center_distance_m'), center, GEOM_TOL):
            verifier.fail(name, 'contact_evidence.center_distance_m is not the '
                          'robot/obstacle center distance', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_evidence.center_distance_m',
                          expected=center,
                          actual=record.get('center_distance_m'))
    if radii_sum is not None:
        if not _close(record.get('radii_sum_m'), radii_sum, GEOM_TOL):
            verifier.fail(name, 'contact_evidence.radii_sum_m is not the '
                          'conservative sphere radius sum', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_evidence.radii_sum_m',
                          expected=radii_sum, actual=record.get('radii_sum_m'))
        center = _fnum(record.get('center_distance_m'))
        if center is not None:
            overlap = max(0.0, radii_sum - center)
            if not _close(record.get('sphere_overlap_m'), overlap, GEOM_TOL):
                verifier.fail(name, 'contact_evidence.sphere_overlap_m is not '
                              'max(0, radii_sum - center_distance)', run=label,
                              episode_id=episode_id, step=step,
                              field='contact_evidence.sphere_overlap_m',
                              expected=overlap,
                              actual=record.get('sphere_overlap_m'))
            inferred = record.get('inferred_contact')
            expected_inferred = overlap > CONTACT_OVERLAP_M
            if inferred is not expected_inferred:
                verifier.fail(name, 'contact_evidence.inferred_contact does not '
                              'follow the frozen sphere_overlap_m > %.3f rule'
                              % CONTACT_OVERLAP_M, run=label,
                              episode_id=episode_id, step=step,
                              field='contact_evidence.inferred_contact',
                              expected=expected_inferred, actual=inferred)
            stats['max_sphere_overlap_m'] = max(
                stats['max_sphere_overlap_m'], overlap)
            if expected_inferred:
                stats['inferred_contact'] = True
                inferred_time = _fnum(row.get('time_s'))
                if stats['first_inferred_contact_time_s'] is None \
                        or inferred_time is not None \
                        and inferred_time < stats['first_inferred_contact_time_s']:
                    stats['first_inferred_contact_time_s'] = inferred_time
                    stats['first_inferred_contact_phase'] = row.get('phase')
    time_s = _fnum(row.get('time_s'))
    if _num(record.get('inferred_contact_time_s')) and time_s is not None:
        if abs(float(record['inferred_contact_time_s']) - time_s) > 1e-9:
            verifier.fail(name, 'contact_evidence.inferred_contact_time_s is '
                          'not the row time', run=label, episode_id=episode_id,
                          step=step,
                          field='contact_evidence.inferred_contact_time_s',
                          expected=time_s,
                          actual=record.get('inferred_contact_time_s'))
    sensor_force = _fnum(record.get('sensor_force_n'))
    row_force = _fnum(row.get('contact_force_n'))
    if sensor_force is not None and row_force is not None \
            and not _close(sensor_force, row_force, 1e-6):
        verifier.fail(name, 'contact_evidence.sensor_force_n does not match '
                      'the row contact_force_n', run=label,
                      episode_id=episode_id, step=step,
                      field='contact_evidence.sensor_force_n',
                      expected=row_force, actual=sensor_force)
    force_value = sensor_force if sensor_force is not None else (row_force or 0)
    stats['max_sensor_force_n'] = max(stats['max_sensor_force_n'],
                                      float(force_value or 0.0))
    if force_value is not None and force_value > CONTACT_FORCE_N:
        stats['measured_contact'] = True
    available = ctx.get('force_sensor_available')
    if isinstance(available, bool):
        recorded_available = record.get('force_sensor_available')
        if recorded_available is not available:
            verifier.fail(name, 'contact_evidence.force_sensor_available does '
                          'not match the manifest mode', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_evidence.force_sensor_available',
                          expected=available, actual=recorded_available)
    applied = row.get('applied') if isinstance(row.get('applied'), dict) else {}
    values = [_fnum(applied.get(field)) for field in
              ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
               'yaw_rate_ccw_world_radps')]
    all_zero = all(value is not None and abs(value) <= 1e-9
                   for value in values)
    if record.get('command_all_zero') is not all_zero:
        verifier.fail(name, 'contact_evidence.command_all_zero does not match '
                      'the applied setpoint', run=label, episode_id=episode_id,
                      step=step, field='contact_evidence.command_all_zero',
                      expected=all_zero, actual=record.get('command_all_zero'))
    speed = _fnum(row.get('speed_mps'))
    if speed is not None and not _close(record.get('robot_speed_mps'), speed,
                                        GEOM_TOL):
        verifier.fail(name, 'contact_evidence.robot_speed_mps does not match '
                      'the row speed', run=label, episode_id=episode_id,
                      step=step, field='contact_evidence.robot_speed_mps',
                      expected=speed, actual=record.get('robot_speed_mps'))


def check_manifest_disk(evidence, repo_root, verifier):
    """Manifest-declared case identity/hash must match the disk evidence."""
    name = 'manifest_disk_consistency'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    plan = _manifest_plan(evidence)
    cases_file = plan.get('cases_file')
    recorded = manifest.get('cases_sha256') or plan.get('cases_sha256')
    if not cases_file:
        verifier.missing.add(label, 'manifest.boundary_plan.cases_file', label)
    elif not recorded:
        verifier.missing.add(label, 'manifest.cases_sha256', label)
    else:
        path = Path(str(cases_file))
        if not path.is_absolute():
            path = Path(repo_root or '.') / path
        if not path.is_file():
            verifier.missing.add(label, 'cases file exists (%s)' % path, label)
        else:
            actual = _sha256_file(path)
            if str(recorded).lower() != actual:
                verifier.fail(name, 'manifest.cases_sha256 does not match the '
                              'cases file on disk', run=label,
                              field='cases_sha256', expected=actual,
                              actual=recorded)
    outputs = manifest.get('outputs_sha256')
    if not isinstance(outputs, dict) or not outputs:
        verifier.missing.add(label, 'manifest.outputs_sha256', label)
    verifier.ok_if_clean(name, 'manifest/disk identity checked for %s' % label)


def check_gui(evidence, verifier):
    name = 'gui_evidence'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    if manifest.get('gui_mode') is not True:
        verifier.fail(name, 'manifest.gui_mode is not true (GUI/DirectX '
                      'evidence required)', run=label, field='gui_mode',
                      expected=True, actual=manifest.get('gui_mode'))
    renderer = str(manifest.get('renderer') or '').lower()
    if not any(token in renderer for token in DEVICE_GUI_RENDERERS):
        verifier.fail(name, 'renderer is not DirectX', run=label,
                      field='renderer', expected='DirectX', actual=renderer)
    command = str(manifest.get('command') or '')
    if '--headless' in command or 'headless=true' in command:
        verifier.fail(name, 'run command contains --headless', run=label,
                      field='command', expected='no --headless',
                      actual=command)
    if isinstance(manifest.get('gui_evidence'), dict):
        verifier.ok(name, 'gui_evidence present for %s' % label)
    else:
        verifier.missing.add(label, 'manifest.gui_evidence', label)


# ---------------------------------------------------------------------------
# structural checks
# ---------------------------------------------------------------------------

def check_episode_identity(evidence, verifier):
    name = 'episode_identity_and_denominator'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    seen = set()
    for episode in evidence.episodes:
        episode_id = episode.get('episode_id') if isinstance(episode, dict) \
            else None
        if not episode_id:
            verifier.missing.add(label, 'episodes[].episode_id', label)
            continue
        if episode_id in seen:
            verifier.fail(name, 'duplicate episode_id in episodes.jsonl',
                          run=label, episode_id=episode_id,
                          field='episode_id', expected='unique',
                          actual='duplicate')
        seen.add(episode_id)
    declared = manifest.get('episode_ids')
    if isinstance(declared, list):
        declared_set = {str(item) for item in declared}
        if declared_set != seen:
            verifier.fail(name, 'manifest.episode_ids do not match the episodes '
                          'on disk', run=label, field='episode_ids',
                          expected=sorted(seen), actual=sorted(declared_set))
        if len(declared) != len(seen):
            verifier.fail(name, 'episode denominator (manifest count) does not '
                          'match episodes on disk', run=label,
                          field='episode_ids', expected=len(seen),
                          actual=len(declared))
    else:
        verifier.missing.add(label, 'manifest.episode_ids', label)
    plan = None
    for key in ('boundary_plan', 'run_plan', 'latency_plan'):
        if isinstance(manifest.get(key), dict):
            plan = manifest[key]
            break
    plan = plan or {}
    case_ids = [str(item) for item in plan.get('case_ids') or [] if item]
    episode_cases = [episode.get('case_id')
                     for episode in evidence.episodes
                     if isinstance(episode, dict)]
    if case_ids:
        if sorted(str(item) for item in episode_cases if item) \
                != sorted(case_ids):
            verifier.fail(name, 'episode cases do not match the run plan case '
                          'ids', run=label, field='case_ids',
                          expected=sorted(case_ids),
                          actual=sorted(str(item) for item in episode_cases
                                        if item))
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        segment = episode.get('segment_id')
        if plan.get('segment_id') and segment is not None \
                and str(segment) != str(plan.get('segment_id')):
            verifier.fail(name, 'episode.segment_id does not match the run plan',
                          run=label, episode_id=episode.get('episode_id'),
                          field='segment_id', expected=plan.get('segment_id'),
                          actual=segment)
    verifier.ok_if_clean(name, 'episode identity/denominator checked for %s'
                         % label)


def check_step_time(evidence, verifier):
    name = 'step_time_monotonicity'
    label = evidence.label
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    plan = None
    for key in ('boundary_plan', 'run_plan', 'latency_plan'):
        if isinstance(manifest.get(key), dict):
            plan = manifest[key]
            break
    plan = plan or {}
    dt = _fnum(plan.get('control_step_s'))
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        rows = _sorted_rows(evidence.steps_by_episode.get(
            episode.get('episode_id'), []))
        if not rows:
            continue
        previous_time = None
        previous_step = None
        previous_phase = None
        run_count = 0
        for row in rows:
            step = row.get('step')
            time_s = row.get('time_s')
            phase = row.get('phase')
            if _num(time_s):
                if previous_time is not None and time_s <= previous_time:
                    verifier.fail(name, 'time_s is not strictly increasing',
                                  run=label,
                                  episode_id=episode.get('episode_id'),
                                  step=step, field='time_s',
                                  expected='> %.6f' % previous_time,
                                  actual=time_s)
                previous_time = time_s
            if _num(step) and previous_step is not None:
                allowed = step == previous_step + 1
                if phase == 'POST_ABORT' and previous_phase != 'POST_ABORT':
                    allowed = step in (previous_step, previous_step + 1)
                if step == previous_step and phase == 'POST_ABORT':
                    allowed = True
                if not allowed:
                    verifier.fail(name, 'step index is not contiguous', run=label,
                                  episode_id=episode.get('episode_id'),
                                  step=step, field='step',
                                  expected=previous_step + 1, actual=step)
            previous_step = step
            previous_phase = phase
            if phase != 'POST_ABORT':
                run_count += 1
                if row.get('env_terminated'):
                    verifier.fail(name, 'env terminated inside a RUN episode',
                                  run=label,
                                  episode_id=episode.get('episode_id'),
                                  step=step, field='env_terminated',
                                  expected=False,
                                  actual=row.get('env_terminated'))
                if row.get('env_truncated'):
                    verifier.fail(name, 'env truncated inside a RUN episode',
                                  run=label,
                                  episode_id=episode.get('episode_id'),
                                  step=step, field='env_truncated',
                                  expected=False,
                                  actual=row.get('env_truncated'))
                if row.get('boundary_count_ok') is False:
                    verifier.fail(name, 'undeclared episode boundary', run=label,
                                  episode_id=episode.get('episode_id'),
                                  step=step, field='boundary_count_ok',
                                  expected=True,
                                  actual=False)
        recorded_steps = episode.get('steps')
        if _num(recorded_steps) and run_count not in (recorded_steps,
                                                      recorded_steps + 1):
            verifier.fail(name, 'episode.steps does not match RUN step rows',
                          run=label, episode_id=episode.get('episode_id'),
                          field='steps', expected=run_count,
                          actual=recorded_steps)
        if dt is not None and _num(recorded_steps) \
                and _num(episode.get('duration_s')):
            expected_duration = recorded_steps * dt
            if abs(float(episode.get('duration_s')) - expected_duration) > 1e-3:
                verifier.fail(name, 'episode.duration_s does not match '
                              'steps*control_step_s', run=label,
                              episode_id=episode.get('episode_id'),
                              field='duration_s', expected=expected_duration,
                              actual=episode.get('duration_s'))
    verifier.ok_if_clean(name, 'step timing checked')


# ---------------------------------------------------------------------------
# contract invariants: clearance
# ---------------------------------------------------------------------------

def _check_clearance_row(evidence, episode, row, ctx, verifier, stats):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('clearance')
    obs_valid = row.get('observation_valid')
    if not isinstance(record, dict):
        if obs_valid is True:
            verifier.missing.add(
                label, 'steps[].clearance on an observation-valid step',
                _example(row))
        else:
            stats['no_record_invalid_steps'] += 1
        return None
    stats['records'] += 1
    valid = None
    validity = record.get('validity')
    if isinstance(validity, dict):
        valid = validity.get('valid')
    if not isinstance(valid, bool):
        verifier.fail('clearance_recompute', 'clearance.validity.valid is not a '
                      'boolean', run=label, episode_id=episode_id, step=step,
                      field='clearance.validity.valid', expected='bool',
                      actual=valid)
        return None
    # observation validity is a contract: valid <=> mapping usable AND raw valid
    clock = row.get('clock') if isinstance(row.get('clock'), dict) else {}
    usable = clock.get('mapping_usable')
    raw_dropout = 'DROPOUT' in str(row.get('observation_reason') or '').upper()
    if isinstance(usable, bool):
        expected_obs_valid = usable and not raw_dropout
        if obs_valid is not expected_obs_valid:
            verifier.fail('clearance_observation_age', 'observation_valid is not '
                          'mapping_usable AND raw_valid', run=label,
                          episode_id=episode_id, step=step,
                          field='observation_valid',
                          expected=expected_obs_valid, actual=obs_valid)
    if valid != obs_valid:
        verifier.fail('clearance_recompute', 'clearance.validity.valid does not '
                      'track observation_valid', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.validity.valid', expected=obs_valid,
                      actual=valid)
    applicability = record.get('applicability') \
        if isinstance(record.get('applicability'), dict) else {}
    status = applicability.get('status')
    if status not in ('SUPPORTED', 'UNSUPPORTED'):
        verifier.fail('clearance_recompute', 'clearance.applicability.status is '
                      'not SUPPORTED/UNSUPPORTED', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.applicability.status',
                      expected=['SUPPORTED', 'UNSUPPORTED'], actual=status)
    elif valid is False and status != 'UNSUPPORTED':
        verifier.fail('clearance_recompute', 'invalid clearance observation must '
                      'be declared UNSUPPORTED', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.applicability.status',
                      expected='UNSUPPORTED', actual=status)
    stats['applicability'][str(status)] += 1
    if not isinstance(applicability.get('reasons'), list):
        verifier.missing.add(label, 'steps[].clearance.applicability.reasons',
                             _example(row))
    validity_reasons = validity.get('reasons') \
        if isinstance(validity, dict) else None
    if not isinstance(validity_reasons, list):
        verifier.missing.add(label, 'steps[].clearance.validity.reasons',
                             _example(row))
    if valid is False:
        return None
    return _check_clearance_valid_row(evidence, episode, row, ctx, verifier,
                                      stats, record)


def _check_clearance_valid_row(evidence, episode, row, ctx, verifier, stats,
                               record):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    algorithm = record.get('algorithm') \
        if isinstance(record.get('algorithm'), dict) else {}
    name = 'clearance_prediction_structure'
    for key, expected in (('id', CLEARANCE_ALGORITHM_ID),
                          ('version', CLEARANCE_ALGORITHM_VERSION),
                          ('units', 'm'), ('frame', 'world_ENU_Z_up'),
                          ('time_base', 'simulation_time_s')):
        if algorithm.get(key) != expected:
            verifier.fail(name, 'clearance.algorithm.%s mismatch' % key,
                          run=label, episode_id=episode_id, step=step,
                          field='clearance.algorithm.' + key,
                          expected=expected, actual=algorithm.get(key))
    horizon = _fnum(algorithm.get('prediction_horizon_s'))
    step_s = _fnum(algorithm.get('prediction_step_s'))
    if horizon is None or step_s is None or horizon <= 0 or step_s <= 0:
        verifier.missing.add(label, 'clearance.algorithm prediction horizon/step',
                             _example(row))
        return None
    supervisor = ctx.get('supervisor') or {}
    expected_horizon = _fnum(supervisor.get('prediction_horizon_s'))
    expected_step = _fnum(supervisor.get('prediction_step_s'))
    if expected_horizon is not None and not _close(horizon, expected_horizon,
                                                   GEOM_TOL):
        verifier.fail(name, 'clearance prediction horizon differs from the '
                      'frozen supervisor config', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.algorithm.prediction_horizon_s',
                      expected=expected_horizon, actual=horizon)
    if expected_step is not None and not _close(step_s, expected_step, GEOM_TOL):
        verifier.fail(name, 'clearance prediction step differs from the frozen '
                      'supervisor config', run=label, episode_id=episode_id,
                      step=step,
                      field='clearance.algorithm.prediction_step_s',
                      expected=expected_step, actual=step_s)
    inputs = record.get('inputs') \
        if isinstance(record.get('inputs'), dict) else {}
    # inputs mirror the raw state (production record vs raw evidence)
    for field, raw_key, tolerance in (
            ('robot_center_world_m', 'position_world_m', GEOM_TOL),
            ('robot_velocity_world_mps', 'velocity_world_mps', GEOM_TOL),
            ('obstacle_observed_center_world_m', 'obstacle_position_world_m',
             GEOM_TOL),
            ('obstacle_observed_velocity_world_mps',
             'obstacle_velocity_world_mps', GEOM_TOL)):
        if not _vec_close(inputs.get(field), row.get(raw_key), tolerance):
            verifier.fail('clearance_recompute',
                          'clearance input does not mirror the raw step state',
                          run=label, episode_id=episode_id, step=step,
                          field='clearance.inputs.' + field,
                          expected=row.get(raw_key), actual=inputs.get(field))
    waypoint_index = inputs.get('waypoint_index')
    waypoints = episode.get('waypoints') or []
    if _num(waypoint_index) and isinstance(waypoints, list):
        index = int(waypoint_index)
        if 0 <= index < len(waypoints):
            if not _vec_close(inputs.get('target_waypoint_world_m'),
                              waypoints[index], GEOM_TOL):
                verifier.fail('clearance_recompute',
                              'clearance target waypoint is not the recorded '
                              'waypoint at waypoint_index', run=label,
                              episode_id=episode_id, step=step,
                              field='clearance.inputs.target_waypoint_world_m',
                              expected=waypoints[index],
                              actual=inputs.get('target_waypoint_world_m'))
        else:
            verifier.fail('clearance_recompute',
                          'clearance waypoint_index out of range', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.inputs.waypoint_index',
                          expected='0..%d' % (len(waypoints) - 1),
                          actual=waypoint_index)
    recomputed = _recompute_clearance(inputs, horizon, step_s)
    if recomputed is None:
        verifier.missing.add(label, 'clearance.inputs geometry vectors',
                             _example(row))
        return None
    prediction = record.get('prediction') \
        if isinstance(record.get('prediction'), dict) else {}
    centers = prediction.get('obstacle_predicted_centers_world_m')
    distances = prediction.get('point_distances_m')
    min_index = prediction.get('min_index')
    expected_count = len(recomputed['centers'])
    if not isinstance(centers, list) or len(centers) != expected_count:
        verifier.fail(name, 'prediction point count is not horizon/step + 1',
                      run=label, episode_id=episode_id, step=step,
                      field='clearance.prediction.obstacle_predicted_centers_world_m',
                      expected=expected_count,
                      actual=len(centers) if isinstance(centers, list)
                      else None)
    else:
        for index, (actual, expected) in enumerate(zip(centers,
                                                       recomputed['centers'])):
            if not _vec_close(actual, expected, GEOM_TOL):
                verifier.fail('clearance_prediction_structure',
                              'predicted obstacle center mismatch', run=label,
                              episode_id=episode_id, step=step,
                              field='clearance.prediction.'
                                    'obstacle_predicted_centers_world_m[%d]'
                                    % index, expected=expected, actual=actual)
    if not isinstance(distances, list) or len(distances) != expected_count:
        verifier.fail(name, 'point_distances_m length is not the prediction '
                      'point count', run=label, episode_id=episode_id,
                      step=step,
                      field='clearance.prediction.point_distances_m',
                      expected=expected_count,
                      actual=len(distances) if isinstance(distances, list)
                      else None)
        return recomputed
    for index, (actual, expected) in enumerate(zip(distances,
                                                   recomputed['distances'])):
        if not _close(actual, expected, GEOM_TOL):
            verifier.fail('clearance_prediction_structure',
                          'point-to-segment distance mismatch', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.prediction.point_distances_m[%d]'
                                % index, expected=expected, actual=actual)
    if min_index != recomputed['min_index']:
        verifier.fail('clearance_prediction_structure', 'min_index is not the '
                      'argmin of point_distances_m', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.prediction.min_index',
                      expected=recomputed['min_index'], actual=min_index)
    # production path clearance vs independent rebuild (1e-6)
    metrics = record.get('metrics') if isinstance(record.get('metrics'),
                                                  dict) else {}
    if not _close(metrics.get('path_clearance_m'),
                  recomputed['path_clearance_m'], GEOM_TOL):
        verifier.fail('clearance_recompute', 'production path_clearance_m does '
                      'not match the independent reconstruction', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.metrics.path_clearance_m',
                      expected=recomputed['path_clearance_m'],
                      actual=metrics.get('path_clearance_m'))
    stats['max_abs_error_m'] = max(stats['max_abs_error_m'],
                                   abs(_fnum(metrics.get('path_clearance_m'))
                                       - recomputed['path_clearance_m'])
                                   if _num(metrics.get('path_clearance_m'))
                                   else 0.0)
    if _fnum(metrics.get('path_clearance_m')) is not None:
        stats['min_path_clearance_m'] = min(
            stats['min_path_clearance_m'],
            float(metrics['path_clearance_m']))
    return recomputed


def _check_clearance_envelopes(evidence, episode, row, ctx, verifier, stats):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('clearance')
    if not isinstance(record, dict):
        return
    envelopes = record.get('envelopes')
    if not isinstance(envelopes, dict):
        return
    robot = envelopes.get('robot') if isinstance(envelopes.get('robot'),
                                                 dict) else {}
    obstacle = envelopes.get('obstacle') if isinstance(envelopes.get('obstacle'),
                                                       dict) else {}
    half = _vec(robot.get('aabb_half_extents_m'))
    radius = _fnum(robot.get('radius_m'))
    manifest_body = ctx.get('body_envelope') or {}
    validity = record.get('validity') if isinstance(record.get('validity'),
                                                    dict) else {}
    if half is None:
        if validity.get('valid') is not False:
            verifier.missing.add(label, 'clearance.envelopes.robot.'
                                 'aabb_half_extents_m', _example(row))
        return
    expected_radius = box_conservative_sphere_radius(half)
    if robot.get('kind') != 'sphere_over_spawn_aabb_half_diagonal':
        verifier.fail('clearance_envelope_rules', 'robot envelope kind is not '
                      'the half-diagonal sphere rule', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.robot.kind',
                      expected='sphere_over_spawn_aabb_half_diagonal',
                      actual=robot.get('kind'))
    if not _close(radius, expected_radius, GEOM_TOL):
        verifier.fail('clearance_envelope_rules', 'robot radius is not '
                      'sqrt(sum(aabb_half_extents^2)) (half diagonal rule; '
                      'max-half-extent is not conservative)', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.robot.radius_m',
                      expected=expected_radius, actual=radius)
    body_half = _vec(manifest_body.get('half_extents_m'))
    if body_half is not None and not _vec_close(half, body_half, GEOM_TOL):
        verifier.fail('clearance_envelope_rules', 'robot AABB half extents do '
                      'not match manifest.body_envelope', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.robot.aabb_half_extents_m',
                      expected=body_half, actual=half)
    if manifest_body.get('measured_prim') \
            and robot.get('measured_prim') != manifest_body.get('measured_prim'):
        verifier.fail('clearance_envelope_rules', 'robot envelope measured_prim '
                      'does not match the manifest', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.robot.measured_prim',
                      expected=manifest_body.get('measured_prim'),
                      actual=robot.get('measured_prim'))
    source = robot.get('source')
    if not source:
        verifier.missing.add(label, 'clearance.envelopes.robot.source',
                             _example(row))
    if not robot.get('attitude_scope'):
        verifier.missing.add(label, 'clearance.envelopes.robot.attitude_scope',
                             _example(row))
    if not robot.get('limitation'):
        verifier.missing.add(label, 'clearance.envelopes.robot.limitation',
                             _example(row))
    obstacle_size = _vec(obstacle.get('size_m'))
    obstacle_radius = _fnum(obstacle.get('radius_m'))
    if obstacle.get('kind') != 'sphere_over_case_cuboid':
        verifier.fail('clearance_envelope_rules', 'obstacle envelope kind is not '
                      'sphere_over_case_cuboid', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.obstacle.kind',
                      expected='sphere_over_case_cuboid',
                      actual=obstacle.get('kind'))
    if obstacle_size is None:
        if validity.get('valid') is not False:
            verifier.missing.add(label, 'clearance.envelopes.obstacle.size_m',
                                 _example(row))
        return
    expected_obstacle_radius = max(obstacle_size) / 2.0
    if not _close(obstacle_radius, expected_obstacle_radius, GEOM_TOL):
        verifier.fail('clearance_envelope_rules', 'obstacle radius is not '
                      'max(size_m)/2', run=label, episode_id=episode_id,
                      step=step,
                      field='clearance.envelopes.obstacle.radius_m',
                      expected=expected_obstacle_radius,
                      actual=obstacle_radius)
    episode_obstacle = episode.get('obstacle') \
        if isinstance(episode.get('obstacle'), dict) else {}
    case_size = _vec(episode_obstacle.get('size_m'))
    if case_size is not None and not _vec_close(obstacle_size, case_size,
                                                GEOM_TOL):
        verifier.fail('clearance_envelope_rules', 'obstacle size does not match '
                      'the recorded episode obstacle', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.envelopes.obstacle.size_m',
                      expected=case_size, actual=obstacle_size)
    stats['robot_radius_m'] = radius
    stats['obstacle_radius_m'] = obstacle_radius
    stats['aabb_half_extents_m'] = half


def _check_clearance_metrics(evidence, episode, row, ctx, verifier, stats,
                             recomputed):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('clearance')
    metrics = record.get('metrics') if isinstance(record, dict) \
        and isinstance(record.get('metrics'), dict) else {}
    envelopes = record.get('envelopes') if isinstance(record, dict) \
        and isinstance(record.get('envelopes'), dict) else {}
    robot = envelopes.get('robot') if isinstance(envelopes.get('robot'),
                                                 dict) else {}
    obstacle = envelopes.get('obstacle') if isinstance(envelopes.get('obstacle'),
                                                       dict) else {}
    robot_radius = _fnum(robot.get('radius_m'))
    obstacle_radius = _fnum(obstacle.get('radius_m'))
    center_distance = _fnum(metrics.get('center_distance_m'))
    envelope_gap = _fnum(metrics.get('envelope_gap_sphere_m'))
    path_clearance = _fnum(metrics.get('path_clearance_m'))
    path_gap = _fnum(metrics.get('path_clearance_gap_sphere_m'))
    name = 'clearance_metric_semantics'
    expected_center = recomputed['center_distance_m']
    if not _close(center_distance, expected_center, GEOM_TOL):
        verifier.fail(name, 'center_distance_m is not the robot/obstacle center '
                      'distance', run=label, episode_id=episode_id, step=step,
                      field='clearance.metrics.center_distance_m',
                      expected=expected_center, actual=center_distance)
    if not _close(path_clearance, recomputed['path_clearance_m'], GEOM_TOL):
        verifier.fail(name, 'path_clearance_m is not the predicted path '
                      'clearance', run=label, episode_id=episode_id, step=step,
                      field='clearance.metrics.path_clearance_m',
                      expected=recomputed['path_clearance_m'],
                      actual=path_clearance)
    sum_radii = None
    if robot_radius is not None and obstacle_radius is not None:
        sum_radii = robot_radius + obstacle_radius
    if sum_radii is not None and expected_center is not None:
        expected_gap = expected_center - sum_radii
        if not _close(envelope_gap, expected_gap, GEOM_TOL):
            verifier.fail(name, 'envelope_gap_sphere_m is not center_distance - '
                          '(robot_radius + obstacle_radius)', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.metrics.envelope_gap_sphere_m',
                          expected=expected_gap, actual=envelope_gap)
    if sum_radii is not None:
        expected_path_gap = recomputed['path_clearance_m'] - sum_radii
        if not _close(path_gap, expected_path_gap, GEOM_TOL):
            verifier.fail(name, 'path_clearance_gap_sphere_m is not '
                          'path_clearance - (robot_radius + obstacle_radius)',
                          run=label, episode_id=episode_id, step=step,
                          field='clearance.metrics.path_clearance_gap_sphere_m',
                          expected=expected_path_gap, actual=path_gap)
    # The four quantities are distinct definitions; a sphere gap cannot equal
    # the center distance when the envelope has positive radius.
    if sum_radii is not None and sum_radii > 0:
        if center_distance is not None and envelope_gap is not None \
                and not (envelope_gap < center_distance - 1e-12):
            verifier.fail(name, 'envelope_gap_sphere_m is not distinct from '
                          'center_distance_m (metric aliasing)', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.metrics.envelope_gap_sphere_m',
                          expected='< center_distance_m',
                          actual=envelope_gap)
        if path_clearance is not None and path_gap is not None \
                and not (path_gap < path_clearance - 1e-12):
            verifier.fail(name, 'path_clearance_gap_sphere_m is not distinct '
                          'from path_clearance_m (metric aliasing)', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.metrics.path_clearance_gap_sphere_m',
                          expected='< path_clearance_m', actual=path_gap)
    stats['min_center_distance_m'] = min(
        stats['min_center_distance_m'],
        center_distance if center_distance is not None else float('inf'))
    if envelope_gap is not None:
        stats['min_envelope_gap_sphere_m'] = min(
            stats['min_envelope_gap_sphere_m'], envelope_gap)
    if path_gap is not None:
        stats['min_path_clearance_gap_sphere_m'] = min(
            stats['min_path_clearance_gap_sphere_m'], path_gap)


def _check_clearance_observation(evidence, episode, row, ctx, verifier):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('clearance')
    if not isinstance(record, dict):
        return
    inputs = record.get('inputs') if isinstance(record.get('inputs'),
                                                dict) else {}
    clock = row.get('clock') if isinstance(row.get('clock'), dict) else {}
    if inputs.get('observation_valid') != row.get('observation_valid'):
        verifier.fail('clearance_observation_age', 'clearance input '
                      'observation_valid does not match the step observation',
                      run=label, episode_id=episode_id, step=step,
                      field='clearance.inputs.observation_valid',
                      expected=row.get('observation_valid'),
                      actual=inputs.get('observation_valid'))
    if str(inputs.get('observation_reason') or '') \
            != str(row.get('observation_reason') or ''):
        verifier.fail('clearance_observation_age', 'clearance input '
                      'observation_reason does not match the step observation',
                      run=label, episode_id=episode_id, step=step,
                      field='clearance.inputs.observation_reason',
                      expected=row.get('observation_reason'),
                      actual=inputs.get('observation_reason'))
    usable = clock.get('mapping_usable')
    if usable is False:
        return
    validity = record.get('validity') if isinstance(record.get('validity'),
                                                    dict) else {}
    if validity.get('valid') is not True:
        # An invalid observation has no meaningful age/geometry contract here;
        # the validity/observation-consistency checks above are the evidence.
        return
    point = _fnum(inputs.get('observation_age_point_s'))
    bound = _fnum(inputs.get('observation_age_bound_s'))
    clock_point = _fnum(clock.get('age_point_s'))
    clock_bound = _fnum(clock.get('age_bound_s'))
    if point is None or bound is None:
        verifier.missing.add(label, 'clearance.inputs observation ages',
                             _example(row))
        return
    if not _close(point, clock_point, AGE_TOL_S):
        verifier.fail('clearance_observation_age', 'observation_age_point_s '
                      'does not match clock.age_point_s', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.inputs.observation_age_point_s',
                      expected=clock_point, actual=point)
    if not _close(bound, clock_bound, AGE_TOL_S):
        verifier.fail('clearance_observation_age', 'observation_age_bound_s '
                      'does not match clock.age_bound_s', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.inputs.observation_age_bound_s',
                      expected=clock_bound, actual=bound)
    if bound + 1e-9 < point:
        verifier.fail('clearance_observation_age', 'observation_age_bound_s is '
                      'below observation_age_point_s', run=label,
                      episode_id=episode_id, step=step,
                      field='clearance.inputs.observation_age_bound_s',
                      expected='>= age_point_s', actual=bound)
    recorded_age = _fnum(row.get('observation_age_s'))
    if recorded_age is not None and not _close(recorded_age, bound, 1e-9):
        verifier.fail('clearance_observation_age', 'observation_age_s must equal '
                      'the conservative age bound', run=label,
                      episode_id=episode_id, step=step,
                      field='observation_age_s', expected=bound,
                      actual=recorded_age)
    # clock algebra: age_bound = age_point + mapping_error/1e9
    error_ns = _fnum(clock.get('mapping_error_ns'))
    if error_ns is not None:
        expected_bound = clock_point + error_ns / 1e9
        if not _close(bound, expected_bound, AGE_TOL_S):
            verifier.fail('clearance_observation_age', 'observation_age_bound_s '
                          'is not age_point_s + mapping_error_ns/1e9', run=label,
                          episode_id=episode_id, step=step,
                          field='clearance.inputs.observation_age_bound_s',
                          expected=expected_bound, actual=bound)


def _check_clearance_decision(evidence, episode, row, ctx, verifier):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    state = row.get('supervisor_state')
    action = row.get('supervisor_action')
    if state == 'ABORT' and action not in (None, 'ABORT'):
        verifier.fail('clearance_decision_consistency', 'ABORT state must '
                      'record the ABORT action', run=label,
                      episode_id=episode_id, step=step,
                      field='supervisor_action', expected='ABORT',
                      actual=action)
    if state in ('BRAKE', 'HOLD', 'WAIT') and action not in (None, 'STOP'):
        verifier.fail('clearance_decision_consistency', 'stopping state must '
                      'record the STOP action', run=label,
                      episode_id=episode_id, step=step,
                      field='supervisor_action', expected='STOP',
                      actual=action)
    record = row.get('clearance')
    if not isinstance(record, dict) or row.get('observation_valid') is not True:
        return
    metrics = record.get('metrics') if isinstance(record.get('metrics'),
                                                  dict) else {}
    path_clearance = _fnum(metrics.get('path_clearance_m'))
    threshold = ctx.get('stop_threshold_m')
    if path_clearance is None or threshold is None:
        return
    if state in ('FOLLOW', 'RESUME') and path_clearance < threshold - 1e-9:
        verifier.fail('clearance_decision_consistency', 'supervisor stays in a '
                      'non-stopping state while path clearance is below the '
                      'stop threshold', run=label, episode_id=episode_id,
                      step=step, field='supervisor_state',
                      expected='BRAKE/HOLD/WAIT (clearance < %.6f)' % threshold,
                      actual='%s (clearance=%.6f)' % (state, path_clearance))
    production = row.get('clearance_m')
    if production is not None and not _close(production, path_clearance,
                                             GEOM_TOL):
        verifier.fail('clearance_decision_consistency',
                      'recorded production clearance_m differs from the '
                      'clearance record path_clearance_m', run=label,
                      episode_id=episode_id, step=step, field='clearance_m',
                      expected=path_clearance, actual=production)


def check_clearance_episode(evidence, episode, rows, ctx, verifier, analysis):
    stats = analysis['clearance']
    for row in rows:
        _check_clearance_row(evidence, episode, row, ctx, verifier, stats)
        _check_clearance_envelopes(evidence, episode, row, ctx, verifier, stats)
        record = row.get('clearance')
        if isinstance(record, dict) and isinstance(record.get('validity'),
                                                   dict) \
                and record['validity'].get('valid') is True:
            inputs = record.get('inputs') if isinstance(record.get('inputs'),
                                                        dict) else {}
            algorithm = record.get('algorithm') \
                if isinstance(record.get('algorithm'), dict) else {}
            horizon = _fnum(algorithm.get('prediction_horizon_s'))
            step_s = _fnum(algorithm.get('prediction_step_s'))
            if horizon is not None and step_s is not None and horizon > 0 \
                    and step_s > 0:
                recomputed = _recompute_clearance(inputs, horizon, step_s)
                if recomputed is not None:
                    _check_clearance_metrics(evidence, episode, row, ctx,
                                             verifier, stats, recomputed)
        _check_clearance_observation(evidence, episode, row, ctx, verifier)
        _check_clearance_decision(evidence, episode, row, ctx, verifier)
    if stats['records'] == 0:
        for name in ('clearance_recompute', 'clearance_prediction_structure',
                     'clearance_envelope_rules', 'clearance_metric_semantics',
                     'clearance_observation_age',
                     'clearance_decision_consistency'):
            verifier.ok_if_clean(name, 'no clearance records to check for %s'
                                 % episode.get('episode_id'))
    else:
        for name in ('clearance_recompute', 'clearance_prediction_structure',
                     'clearance_envelope_rules', 'clearance_metric_semantics',
                     'clearance_observation_age',
                     'clearance_decision_consistency'):
            verifier.ok_if_clean(name, 'clearance contract checked for %s'
                                 % episode.get('episode_id'))


# ---------------------------------------------------------------------------
# contract invariants: stop requirement
# ---------------------------------------------------------------------------

def _expected_stop_requirement(inputs, basis, threshold, proposed_margin,
                               brake_model, horizons):
    """Recompute the stop requirement from the recorded inputs (plan s3)."""
    speed = _fnum(inputs.get('robot_speed_mps'))
    closing = _fnum(inputs.get('closing_speed_mps'))
    age = _fnum(inputs.get('observation_age_bound_s'))
    delay = _fnum(inputs.get('action_delay_s'))
    ttl = _fnum(inputs.get('action_ttl_remaining_s'))
    robot_radius = _fnum(inputs.get('robot_radius_m'))
    obstacle_radius = _fnum(inputs.get('obstacle_radius_m'))
    reasons = []
    if speed is None:
        return None
    if brake_model is None or not brake_model.valid:
        # A missing/incomplete brake model is already an INCOMPLETE condition;
        # do not pretend to recompute the stop requirement without it.
        return None
    interpolated = brake_model.interpolate(speed)
    brake_distance = None
    brake_time = None
    if interpolated is None:
        if speed > brake_model.supported_max + 1e-9:
            reasons.append('ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT')
        else:
            reasons.append('ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT')
    else:
        brake_distance, brake_time = interpolated
    if age is None:
        reasons.append('OBSERVATION_AGE_UNKNOWN')
    if ttl is not None and delay is not None and ttl + 1e-12 < delay:
        reasons.append('ACTION_TTL_EXPIRED_BEFORE_ARRIVAL')
    transport_reaction = None
    if speed is not None and delay is not None:
        transport_reaction = speed * delay if basis == 'actuation' else 0.0
    observation_motion = None
    if closing is not None and age is not None:
        observation_motion = closing * age
    envelope_sum = None
    if robot_radius is not None and obstacle_radius is not None:
        envelope_sum = robot_radius + obstacle_radius
    blocking = [reason for reason in reasons
                if reason in STOP_BLOCKING_REASONS]
    markers = []
    if closing is None:
        markers.append('CLOSING_SPEED_NOT_MODELLED')
    horizon = _fnum(horizons.get('prediction_horizon_s'))
    if brake_time is not None and horizon is not None and brake_time > horizon:
        markers.append('PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME')
    required = None
    margin = None
    if not blocking and brake_distance is not None \
            and transport_reaction is not None and envelope_sum is not None \
            and (observation_motion is not None or age == 0):
        required = brake_distance + transport_reaction \
            + (observation_motion or 0.0) + envelope_sum
        if threshold is not None:
            margin = threshold - required - proposed_margin
    status = 'UNSUPPORTED' if blocking else 'SUPPORTED'
    return {
        'brake_distance_m': brake_distance,
        'transport_reaction_m': transport_reaction,
        'observation_age_motion_m': observation_motion,
        'envelope_sum_m': envelope_sum,
        'required_clearance_m': required,
        'margin_to_threshold_m': margin,
        'status': status,
        'blocking_reasons': blocking,
        'marker_reasons': markers,
        'brake_time_s': brake_time,
    }


def _check_stop_requirement_row(evidence, episode, row, ctx, verifier, stats):
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    record = row.get('stop_requirement')
    if not isinstance(record, dict):
        return
    stats['records'] += 1
    inputs = record.get('inputs') if isinstance(record.get('inputs'),
                                                dict) else {}
    terms = record.get('terms') if isinstance(record.get('terms'), dict) else {}
    status = record.get('status')
    basis = record.get('basis')
    reasons = record.get('status_reasons')
    reasons = [str(item) for item in reasons] if isinstance(reasons, list) else []
    model = ctx.get('brake_model')
    model_id = record.get('model_id')
    expected_model_id = model.model_id if model is not None and model.loaded \
        else None
    if expected_model_id and model_id != expected_model_id:
        verifier.fail('stop_requirement_recompute', 'stop_requirement.model_id '
                      'does not match the frozen brake model', run=label,
                      episode_id=episode_id, step=step,
                      field='stop_requirement.model_id',
                      expected=expected_model_id, actual=model_id)
    if basis not in STOP_BASES:
        verifier.fail('stop_requirement_basis', 'stop_requirement.basis is not '
                      'actuation/trigger', run=label, episode_id=episode_id,
                      step=step, field='stop_requirement.basis',
                      expected=list(STOP_BASES), actual=basis)
        return
    for reason in reasons:
        if reason not in STOP_ALLOWED_REASONS:
            verifier.fail('stop_requirement_recompute', 'unknown '
                          'stop_requirement.status_reason', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.status_reasons',
                          expected=sorted(STOP_ALLOWED_REASONS), actual=reason)
    # raw-vs-recorded input cross-checks
    speed = _fnum(inputs.get('robot_speed_mps'))
    row_speed = _fnum(row.get('speed_mps'))
    if row_speed is not None and not _close(speed, row_speed, GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'stop_requirement input '
                      'robot_speed_mps does not match the measured step speed',
                      run=label, episode_id=episode_id, step=step,
                      field='stop_requirement.inputs.robot_speed_mps',
                      expected=row_speed, actual=speed)
    age = _fnum(inputs.get('observation_age_bound_s'))
    row_age = _fnum(row.get('observation_age_s'))
    if age is not None and row_age is not None \
            and not _close(age, row_age, AGE_TOL_S):
        verifier.fail('stop_requirement_recompute', 'stop_requirement input '
                      'observation_age_bound_s does not match the step age',
                      run=label, episode_id=episode_id, step=step,
                      field='stop_requirement.inputs.observation_age_bound_s',
                      expected=row_age, actual=age)
    plan = ctx.get('plan') or {}
    delay = _fnum(inputs.get('action_delay_s'))
    plan_delay = _fnum(plan.get('action_delay_s'))
    if plan_delay is not None and not _close(delay, plan_delay, GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'stop_requirement input '
                      'action_delay_s does not match the frozen run plan',
                      run=label, episode_id=episode_id, step=step,
                      field='stop_requirement.inputs.action_delay_s',
                      expected=plan_delay, actual=delay)
    robot_radius = _fnum(inputs.get('robot_radius_m'))
    obstacle_radius = _fnum(inputs.get('obstacle_radius_m'))
    envelope = ctx.get('envelope')
    if envelope is not None:
        if envelope.get('robot_radius_m') is not None \
                and not _close(robot_radius, envelope['robot_radius_m'],
                               GEOM_TOL):
            verifier.fail('stop_requirement_recompute',
                          'stop_requirement robot_radius_m does not match the '
                          'clearance envelope', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.inputs.robot_radius_m',
                          expected=envelope['robot_radius_m'],
                          actual=robot_radius)
        if envelope.get('obstacle_radius_m') is not None \
                and not _close(obstacle_radius, envelope['obstacle_radius_m'],
                               GEOM_TOL):
            verifier.fail('stop_requirement_recompute',
                          'stop_requirement obstacle_radius_m does not match '
                          'the clearance envelope', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.inputs.obstacle_radius_m',
                          expected=envelope['obstacle_radius_m'],
                          actual=obstacle_radius)
    threshold = _fnum(inputs.get('stop_threshold_m'))
    stop_threshold = ctx.get('stop_threshold_m')
    if stop_threshold is not None and not _close(threshold, stop_threshold,
                                                 GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'stop_requirement input '
                      'stop_threshold_m does not match the frozen run plan',
                      run=label, episode_id=episode_id, step=step,
                      field='stop_requirement.inputs.stop_threshold_m',
                      expected=stop_threshold, actual=threshold)
    proposed = _fnum(inputs.get('proposed_margin_m'))
    expected_proposed = ctx.get('proposed_margin_m', DEFAULT_PROPOSED_MARGIN_M)
    if proposed is None:
        verifier.missing.add(label, 'stop_requirement.inputs.'
                             'proposed_margin_m', _example(row))
    elif expected_proposed is not None and not _close(proposed,
                                                      expected_proposed,
                                                      GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'proposed_margin_m is not '
                      'the frozen PROPOSED planning margin', run=label,
                      episode_id=episode_id, step=step,
                      field='stop_requirement.inputs.proposed_margin_m',
                      expected=expected_proposed, actual=proposed)
    ttl_remaining = _fnum(inputs.get('action_ttl_remaining_s'))
    ttl_s = ctx.get('ttl_s')
    if ttl_remaining is not None and ttl_s is not None:
        if ttl_remaining < -1e-9 or ttl_remaining > ttl_s + 1e-9:
            verifier.fail('stop_requirement_recompute', 'action_ttl_remaining_s '
                          'is outside [0, ttl]', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.inputs.action_ttl_remaining_s',
                          expected='0..%s' % ttl_s, actual=ttl_remaining)
    # recompute the whole model
    expected = _expected_stop_requirement(
        inputs, basis, threshold if threshold is not None else stop_threshold,
        proposed if proposed is not None else expected_proposed, model,
        ctx.get('supervisor') or {})
    if expected is None:
        return
    for reason in expected['blocking_reasons']:
        if reason not in reasons:
            verifier.fail('stop_requirement_recompute', 'required UNSUPPORTED '
                          'reason is missing', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.status_reasons',
                          expected=reason, actual=reasons)
    for reason in reasons:
        if reason in STOP_BLOCKING_REASONS \
                and reason not in expected['blocking_reasons']:
            verifier.fail('stop_requirement_recompute', 'recorded UNSUPPORTED '
                          'reason is not reproducible from the inputs',
                          run=label, episode_id=episode_id, step=step,
                          field='stop_requirement.status_reasons',
                          expected=expected['blocking_reasons'], actual=reason)
    expected_status = expected['status']
    if status != expected_status:
        verifier.fail('stop_requirement_recompute', 'stop_requirement.status is '
                      'not reproducible from the inputs and the brake model',
                      run=label, episode_id=episode_id, step=step,
                      field='stop_requirement.status',
                      expected=expected_status, actual=status)
    # term-level recomputation
    for field in STOP_REQUIREMENT_TERM_KEYS:
        expected_value = expected.get(field)
        actual_value = _fnum(terms.get(field))
        if expected_value is None and actual_value is None:
            continue
        if not _close(actual_value, expected_value, GEOM_TOL):
            verifier.fail('stop_requirement_recompute', 'stop_requirement term '
                          'is not reproducible', run=label,
                          episode_id=episode_id, step=step,
                          field='stop_requirement.terms.' + field,
                          expected=expected_value, actual=actual_value)
    if not _equal_nullable(_fnum(record.get('required_clearance_m')),
                           expected['required_clearance_m'], GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'required_clearance_m is not '
                      'the sum of the recomputed terms', run=label,
                      episode_id=episode_id, step=step,
                      field='stop_requirement.required_clearance_m',
                      expected=expected['required_clearance_m'],
                      actual=record.get('required_clearance_m'))
    if not _equal_nullable(_fnum(record.get('margin_to_threshold_m')),
                           expected['margin_to_threshold_m'], GEOM_TOL):
        verifier.fail('stop_requirement_recompute', 'margin_to_threshold_m is '
                      'not threshold - required - proposed_margin', run=label,
                      episode_id=episode_id, step=step,
                      field='stop_requirement.margin_to_threshold_m',
                      expected=expected['margin_to_threshold_m'],
                      actual=record.get('margin_to_threshold_m'))
    if basis == 'trigger' and _fnum(terms.get('transport_reaction_m')) not in (
            None, 0.0):
        verifier.fail('stop_requirement_basis', 'trigger-basis stop requirement '
                      'must not add the actuation reaction distance', run=label,
                      episode_id=episode_id, step=step,
                      field='stop_requirement.terms.transport_reaction_m',
                      expected=0.0,
                      actual=terms.get('transport_reaction_m'))
    # support boundary / no extrapolation
    support_name = 'stop_requirement_support_boundary'
    if model is not None and model.valid and speed is not None:
        outside = (speed > model.supported_max + 1e-9
                   or speed < model.supported_min - 1e-9)
        if outside:
            if status != 'UNSUPPORTED':
                verifier.fail(support_name, 'robot speed outside the brake model '
                              'support must be UNSUPPORTED (no extrapolation)',
                              run=label, episode_id=episode_id, step=step,
                              field='stop_requirement.status',
                              expected='UNSUPPORTED', actual=status)
            for field in ('brake_distance_m', 'required_clearance_m',
                          'margin_to_threshold_m'):
                value = terms.get(field) if field in terms else record.get(field)
                if value is not None:
                    verifier.fail(support_name, 'no extrapolation outside the '
                                  'brake model support: %s must be null' % field,
                                  run=label, episode_id=episode_id, step=step,
                                  field='stop_requirement.' + field,
                                  expected=None, actual=value)
            stats['outside_support_steps'] += 1
        else:
            stats['interpolated_steps'] += 1
    if status == 'UNSUPPORTED':
        stats['unsupported_steps'] += 1
        for reason in reasons:
            stats['unsupported_reasons'][reason] += 1
    if speed is not None:
        stats['max_robot_speed_mps'] = max(stats['max_robot_speed_mps'], speed)
    margin = _fnum(record.get('margin_to_threshold_m'))
    if margin is not None:
        stats['min_margin_m'] = min(stats['min_margin_m'], margin)
    if _num(record.get('required_clearance_m')):
        stats['max_required_clearance_m'] = max(
            stats['max_required_clearance_m'],
            float(record['required_clearance_m']))


def check_stop_requirement_episode(evidence, episode, rows, ctx, verifier,
                                   analysis):
    stats = analysis['stop_requirement']
    for row in rows:
        _check_stop_requirement_row(evidence, episode, row, ctx, verifier, stats)
    if stats['records'] == 0:
        for name in ('stop_requirement_recompute',
                     'stop_requirement_support_boundary',
                     'stop_requirement_basis'):
            verifier.ok_if_clean(name, 'no stop_requirement records for %s'
                                 % episode.get('episode_id'))
    else:
        for name in ('stop_requirement_recompute',
                     'stop_requirement_support_boundary',
                     'stop_requirement_basis'):
            verifier.ok_if_clean(name, 'stop requirement contract checked for %s'
                                 % episode.get('episode_id'))


# ---------------------------------------------------------------------------
# contract invariants: TTL / arrival gate / old setpoint
# ---------------------------------------------------------------------------

def _check_applied_record(evidence, episode, row, active, ttl_s, host,
                          verifier):
    name = 'hold_until_expiry_then_none'
    label = evidence.label
    episode_id = episode.get('episode_id')
    step = row.get('step')
    transport = row.get('transport') if isinstance(row.get('transport'),
                                                    dict) else {}
    status = transport.get('status')
    applied = row.get('applied')
    if not isinstance(applied, dict):
        return
    fields = ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
              'yaw_rate_ccw_world_radps')
    if status == 'NONE' or active is None:
        for field in fields:
            value = _fnum(applied.get(field))
            if value is not None and abs(value) > 1e-12:
                verifier.fail(name, 'no active setpoint but the applied command '
                              'is non-zero', run=label, episode_id=episode_id,
                              step=step, field='applied.' + field,
                              expected=0.0, actual=value)
        if applied.get('action_id') not in ('', None) and status == 'NONE':
            verifier.fail(name, 'no active setpoint but applied.action_id is set',
                          run=label, episode_id=episode_id, step=step,
                          field='applied.action_id', expected='',
                          actual=applied.get('action_id'))
        return
    if applied.get('action_id') != active.get('id'):
        verifier.fail(name, 'applied.action_id is not the active action',
                      run=label, episode_id=episode_id, step=step,
                      field='applied.action_id', expected=active.get('id'),
                      actual=applied.get('action_id'))
    if status == 'HOLDING' and applied.get('is_held') is not True:
        verifier.fail(name, 'HOLDING must record applied.is_held=true', run=label,
                      episode_id=episode_id, step=step,
                      field='applied.is_held', expected=True,
                      actual=applied.get('is_held'))
    age = _fnum(applied.get('age_s'))
    if age is not None and ttl_s is not None and age > ttl_s + 1e-9:
        verifier.fail(name, 'applied active setpoint outlives its TTL', run=label,
                      episode_id=episode_id, step=step, field='applied.age_s',
                      expected='<= %.9f' % ttl_s, actual=age)


def check_transport_episode(evidence, episode, rows, ctx, verifier, analysis):
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
    executed_ids = []
    status_counts = Counter()
    reject_reasons = Counter()
    for row in rows:
        transport = row.get('transport')
        if not isinstance(transport, dict):
            continue
        step = row.get('step')
        status = transport.get('status')
        status_counts[status] += 1
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
        if status is not None and status not in TRANSPORT_STATUSES:
            verifier.fail('schema_completeness', 'invalid transport.status',
                          run=label, episode_id=episode_id, step=step,
                          field='transport.status',
                          expected=list(TRANSPORT_STATUSES), actual=status)
        if _num(issued) and _num(expires) and not (issued == 0 and expires == 0):
            delta = expires - issued
            if ttl_ns is not None and delta != ttl_ns:
                verifier.fail('ttl_no_renewal', 'expires_at_ns - issued_at_ns is '
                              'not the frozen TTL (re-send must not extend it)',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.expires_at_ns',
                              expected=ttl_ns, actual=delta)
        if status in ('APPLIED', 'HOLDING', 'REJECTED'):
            if _num(arrival) and _num(scheduled) and arrival < scheduled - 1:
                verifier.fail('arrival_expiry_rejection', 'action arrives before '
                              'its scheduled dispatch time', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.arrival_ns',
                              expected='>= %s' % scheduled, actual=arrival)
            if _num(arrival) and _num(issued) and arrival_age is not None:
                expected_age = (arrival - issued) / 1e9
                if abs(arrival_age - expected_age) > 1e-9:
                    verifier.fail('arrival_expiry_rejection', 'arrival_age_s is '
                                  'not (arrival_ns - issued_at_ns)/1e9',
                                  run=label, episode_id=episode_id, step=step,
                                  field='transport.arrival_age_s',
                                  expected=expected_age, actual=arrival_age)
            if _num(dispatch) and _num(scheduled) and _num(issued):
                expected_dispatch = (scheduled - issued) / 1e9
                if abs(dispatch - expected_dispatch) > 1e-9:
                    verifier.fail('arrival_expiry_rejection',
                                  'dispatch_delay_s is not (scheduled - issued)'
                                  '/1e9', run=label, episode_id=episode_id,
                                  step=step,
                                  field='transport.dispatch_delay_s',
                                  expected=expected_dispatch, actual=dispatch)
            if action_delay_ns is not None and status != 'DIRECT':
                on_stall = stall_active and _num(step) and step >= stall_step
                if not on_stall and _num(dispatch):
                    expected_delay = action_delay_ns / 1e9
                    if abs(dispatch - expected_delay) > 1e-6:
                        verifier.fail('arrival_expiry_rejection',
                                      'dispatch delay does not match the frozen '
                                      'action delay', run=label,
                                      episode_id=episode_id, step=step,
                                      field='transport.dispatch_delay_s',
                                      expected=expected_delay, actual=dispatch)
        if status == 'DIRECT':
            if executed is not True or action_id != executed_id:
                verifier.fail('arrival_expiry_rejection', 'DIRECT transport '
                              'must execute action_id', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.status', expected='executed',
                              actual=status)
            if _num(issued) and _num(expires):
                active = {'id': action_id, 'issued': issued,
                          'expires': expires}
                executed_ids.append(executed_id)
        elif status == 'APPLIED':
            if executed is not True:
                verifier.fail('arrival_expiry_rejection', 'APPLIED transport '
                              'must execute the setpoint', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed', expected=True,
                              actual=executed)
            if arrival_age is not None and ttl_s is not None \
                    and arrival_age > ttl_s + 1e-9:
                verifier.fail('arrival_expiry_rejection', 'arrival was accepted '
                              'although its age is at/after the TTL', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.arrival_age_s',
                              expected='< %.9f' % ttl_s, actual=arrival_age)
            if _num(issued) and _num(expires):
                active = {'id': action_id, 'issued': issued,
                          'expires': expires}
            executed_ids.append(executed_id)
            if executed_id in rejected_ids:
                verifier.fail('rejection_never_executed', 'a previously rejected '
                              'action id was executed', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed_action_id',
                              expected='not a rejected action id',
                              actual=executed_id)
        elif status == 'HOLDING':
            if executed is not True:
                verifier.fail('hold_until_expiry_then_none', 'HOLDING transport '
                              'must execute the active setpoint', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed', expected=True,
                              actual=executed)
            if active is None:
                verifier.fail('hold_until_expiry_then_none', 'HOLDING recorded '
                              'without an active setpoint', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.status', expected='ACTIVE',
                              actual=status)
            else:
                if _num(host) and _num(active.get('expires')) \
                        and host >= active['expires']:
                    verifier.fail('hold_until_expiry_then_none', 'HOLDING '
                                  'setpoint is at/after its TTL expiry',
                                  run=label, episode_id=episode_id, step=step,
                                  field='clock.host_now_ns',
                                  expected='< %s' % active['expires'],
                                  actual=host)
                if executed_id != active.get('id'):
                    verifier.fail('hold_until_expiry_then_none', 'HOLDING '
                                  'executed_action_id is not the active action',
                                  run=label, episode_id=episode_id, step=step,
                                  field='transport.executed_action_id',
                                  expected=active.get('id'),
                                  actual=executed_id)
                if _num(issued) and _num(active.get('issued')) \
                        and issued != active['issued']:
                    verifier.fail('ttl_no_renewal', 'HOLDING re-issued the active '
                                  'action (TTL renewal)', run=label,
                                  episode_id=episode_id, step=step,
                                  field='transport.issued_at_ns',
                                  expected=active['issued'], actual=issued)
                if _num(expires) and _num(active.get('expires')) \
                        and expires != active['expires']:
                    verifier.fail('ttl_no_renewal', 'HOLDING extended the active '
                                  'expiry', run=label, episode_id=episode_id,
                                  step=step, field='transport.expires_at_ns',
                                  expected=active['expires'], actual=expires)
            executed_ids.append(executed_id)
            if executed_id in rejected_ids:
                verifier.fail('rejection_never_executed', 'a previously rejected '
                              'action id was executed', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed_action_id',
                              expected='not a rejected action id',
                              actual=executed_id)
        elif status == 'REJECTED':
            if executed is not False:
                verifier.fail('arrival_expiry_rejection', 'REJECTED transport '
                              'must not execute the action', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed', expected=False,
                              actual=executed)
            if not reason:
                verifier.fail('arrival_expiry_rejection', 'REJECTED transport '
                              'must record a reason', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.reason', expected='reason',
                              actual=reason)
            if action_id and action_id == executed_id:
                verifier.fail('rejection_never_executed', 'rejected action id '
                              'recorded as executed', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed_action_id',
                              expected='!= %s' % action_id, actual=executed_id)
            if action_id:
                rejected_ids.add(action_id)
            reject_reasons[str(reason)] += 1
            if reason == 'ACTION_EXPIRED' and arrival_age is not None \
                    and ttl_s is not None and arrival_age + 1e-9 < ttl_s:
                verifier.fail('arrival_expiry_rejection', 'ACTION_EXPIRED '
                              'rejection but the arrival age is below the TTL',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.arrival_age_s',
                              expected='>= %.9f' % ttl_s, actual=arrival_age)
        elif status == 'NONE':
            if executed is not False:
                verifier.fail('hold_until_expiry_then_none', 'NONE transport '
                              'must not execute a setpoint', run=label,
                              episode_id=episode_id, step=step,
                              field='transport.executed', expected=False,
                              actual=executed)
            no_new_action = row.get('v2_admission') in (None, '',
                                                        'NO_NEW_ACTION')
            if active is not None:
                expired = (_num(host) and _num(active.get('expires'))
                           and host >= active['expires'] - 1e-9)
                if expired:
                    active = None
                elif not no_new_action:
                    verifier.fail('hold_until_expiry_then_none', 'active '
                                  'setpoint dropped before its TTL expiry',
                                  run=label, episode_id=episode_id, step=step,
                                  field='transport.status', expected='HOLDING',
                                  actual='NONE')
        for extra in transport.get('rejections_this_step') or []:
            if not isinstance(extra, dict):
                continue
            extra_id = extra.get('action_id')
            extra_reason = extra.get('reason')
            extra_age = _fnum(extra.get('arrival_age_s'))
            reject_reasons[str(extra_reason)] += 1
            if extra_id:
                rejected_ids.add(extra_id)
            if extra_reason == 'ACTION_EXPIRED' and extra_age is not None \
                    and ttl_s is not None and extra_age + 1e-9 < ttl_s:
                verifier.fail('arrival_expiry_rejection', 'ACTION_EXPIRED '
                              'rejection but the arrival age is below the TTL',
                              run=label, episode_id=episode_id, step=step,
                              field='transport.rejections_this_step',
                              expected='>= %.9f' % ttl_s, actual=extra_age)
        if executed_id and executed_id in rejected_ids:
            verifier.fail('rejection_never_executed', 'a previously rejected '
                          'action id was executed', run=label,
                          episode_id=episode_id, step=step,
                          field='transport.executed_action_id',
                          expected='not a rejected action id', actual=executed_id)
        _check_applied_record(evidence, episode, row, active, ttl_s, host,
                              verifier)
    analysis['transport'] = {
        'status_counts': dict(status_counts),
        'rejection_reasons': dict(reject_reasons),
        'rejected_ids': sorted(rejected_ids),
        'executed_ids': sorted({str(item) for item in executed_ids
                                if item not in (None, '')}),
    }
    if status_counts:
        verifier.ok_if_clean('ttl_no_renewal', 'transport TTL checked for %s'
                             % episode_id)
        verifier.ok_if_clean('arrival_expiry_rejection', 'arrival gate checked '
                             'for %s' % episode_id)
        verifier.ok_if_clean('rejection_never_executed', 'rejection/execution '
                             'disjointness checked for %s' % episode_id)
        verifier.ok_if_clean('hold_until_expiry_then_none', 'holding/expiry '
                             'checked for %s' % episode_id)


def check_post_abort_episode(evidence, episode, rows, ctx, verifier, analysis):
    name = 'post_abort_old_setpoint'
    label = evidence.label
    episode_id = episode.get('episode_id')
    plan = ctx.get('plan') or {}
    observe_s = _fnum(plan.get('post_abort_observe_s'))
    post_rows = [row for row in rows if row.get('phase') == 'POST_ABORT']
    if observe_s is not None and observe_s > 0:
        if not post_rows:
            verifier.fail(name, 'post-abort observation window configured but no '
                          'POST_ABORT rows exist', run=label,
                          episode_id=episode_id, field='phase',
                          expected='POST_ABORT', actual='absent')
            return
        verifier.ok(name, '%d POST_ABORT rows recorded for %s'
                    % (len(post_rows), episode_id))
    elif post_rows:
        verifier.ok(name, 'POST_ABORT rows present without a configured window '
                    '(informational)')
        return
    else:
        verifier.ok(name, 'no post-abort observation window requested')
        return
    # The business stop time: first terminal business row in the RUN phase.
    business_stop_ns = None
    for row in rows:
        if row.get('phase') == 'POST_ABORT':
            continue
        if row.get('outcome') in BUSINESS_OUTCOMES and _num(row.get('time_s')):
            business_stop_ns = round(float(row['time_s']) * 1e9)
    residual = False
    fallback = False
    previous_active = None
    for row in post_rows:
        transport = row.get('transport') if isinstance(row.get('transport'),
                                                        dict) else {}
        applied = row.get('applied') if isinstance(row.get('applied'),
                                                    dict) else {}
        status = transport.get('status')
        if applied.get('action_id') or status == 'HOLDING':
            residual = True
        if status == 'NONE' and applied.get('action_id') in ('', None):
            values = [_fnum(applied.get(field)) for field in
                      ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
                       'yaw_rate_ccw_world_radps')]
            if all(value is not None and abs(value) <= 1e-12
                   for value in values):
                fallback = True
        # A post-abort row may keep executing the pre-abort setpoint until its
        # TTL expires, but never a newly issued setpoint.
        issued = transport.get('issued_at_ns')
        if business_stop_ns is not None and _num(issued) \
                and issued > business_stop_ns + 1_000_000:
            verifier.fail(name, 'a setpoint issued after the business stop was '
                          'executed during the post-abort window', run=label,
                          episode_id=episode_id, step=row.get('step'),
                          field='transport.issued_at_ns',
                          expected='<= %s' % business_stop_ns, actual=issued)
        state = row.get('supervisor_state')
        if state in ('FOLLOW', 'RESUME', 'SUCCESS'):
            verifier.fail(name, 'post-abort observation resumed the mission '
                          '(supervisor state %s)' % state, run=label,
                          episode_id=episode_id, step=row.get('step'),
                          field='supervisor_state', expected='ABORT/DEGRADED',
                          actual=state)
        # Old setpoint must not outlive its TTL while being held.
        clock = row.get('clock') if isinstance(row.get('clock'), dict) else {}
        host = clock.get('host_now_ns')
        active = None
        if status in ('APPLIED', 'DIRECT'):
            ttl = transport.get('expires_at_ns')
            issued = transport.get('issued_at_ns')
            if _num(issued) and _num(ttl):
                active = {'issued': issued, 'expires': ttl}
        elif status == 'HOLDING':
            ttl = transport.get('expires_at_ns')
            if _num(transport.get('issued_at_ns')) and _num(ttl):
                active = {'issued': transport['issued_at_ns'], 'expires': ttl}
        elif status == 'NONE' and previous_active is not None:
            if _num(host) and _num(previous_active.get('expires')) \
                    and host < previous_active['expires'] - 1e-9 \
                    and row.get('v2_admission') not in (None, '',
                                                        'NO_NEW_ACTION'):
                verifier.fail(name, 'old setpoint dropped before its TTL expiry '
                              'during post-abort', run=label,
                              episode_id=episode_id, step=row.get('step'),
                              field='transport.status', expected='HOLDING',
                              actual='NONE')
        if active is not None:
            if _num(host) and _num(active.get('expires')) \
                    and host >= active['expires']:
                verifier.fail(name, 'old setpoint remains active at/after its TTL '
                              'expiry during post-abort', run=label,
                              episode_id=episode_id, step=row.get('step'),
                              field='clock.host_now_ns',
                              expected='< %s' % active['expires'], actual=host)
            previous_active = active
    if not (residual or fallback):
        verifier.fail(name, 'POST_ABORT rows show neither a residual old setpoint '
                      'nor the zero-target fallback', run=label,
                      episode_id=episode_id, field='applied.action_id',
                      expected='old setpoint or zero target', actual='absent')
    analysis['post_abort'] = {'rows': len(post_rows), 'residual': residual,
                              'fallback': fallback}


# ---------------------------------------------------------------------------
# performance recomputation
# ---------------------------------------------------------------------------

def _rebuild_metrics(rows, episode, ctx):
    metric_rows = _sorted_rows([row for row in rows if _num(row.get('time_s'))])
    run_rows = [row for row in metric_rows if row.get('phase') != 'POST_ABORT']
    post_rows = [row for row in metric_rows if row.get('phase') == 'POST_ABORT']
    dt = ctx.get('dt')
    if dt is None:
        diffs = []
        times = [float(row['time_s']) for row in metric_rows]
        for left, right in zip(times, times[1:]):
            if right > left:
                diffs.append(right - left)
        if diffs:
            diffs.sort()
            dt = diffs[len(diffs) // 2]
    times = [float(row['time_s']) if _num(row.get('time_s')) else None
             for row in metric_rows]
    speeds = []
    positions = []
    velocities = []
    obstacle_velocities = []
    obstacle_positions = []
    for row in metric_rows:
        speed = _fnum(row.get('speed_mps'))
        if speed is None:
            velocity = _vec(row.get('velocity_world_mps'))
            speed = math.sqrt(sum(value * value for value in velocity)) \
                if velocity is not None else None
        speeds.append(speed)
        positions.append(_vec(row.get('position_world_m')))
        velocities.append(_vec(row.get('velocity_world_mps')))
        obstacle_velocities.append(_vec(row.get('obstacle_velocity_world_mps')))
        obstacle_positions.append(_vec(row.get('obstacle_position_world_m')))
    distances = [_distance(positions[index], obstacle_positions[index])
                 for index in range(len(metric_rows))]
    brake_index = None
    for index, row in enumerate(metric_rows):
        if row.get('phase') == 'POST_ABORT':
            continue
        if row.get('supervisor_action') == 'STOP':
            brake_index = index
            break
    brake = None
    if brake_index is not None:
        row = metric_rows[brake_index]
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
    stop_complete_time = None
    if brake_index is not None and dt and dt > 0:
        window = max(1, int(round(STOP_HOLD_S / dt)))
        for index in range(brake_index, len(metric_rows) - window + 1):
            window_speeds = speeds[index:index + window]
            if all(speed is not None and speed <= STOP_SPEED_MPS
                   for speed in window_speeds):
                stop_complete_time = times[index + window - 1]
                start_position = positions[brake_index]
                stop_position = positions[index + window - 1]
                direction = velocities[brake_index]
                if start_position is not None and stop_position is not None:
                    norm = math.sqrt(sum(value * value for value in direction)) \
                        if direction is not None else 0.0
                    if norm > 1e-9:
                        delta = [stop_position[axis] - start_position[axis]
                                 for axis in range(3)]
                        unit = [direction[axis] / norm for axis in range(3)]
                        stop_distance = sum(delta[axis] * unit[axis]
                                            for axis in range(3))
                    else:
                        stop_distance = math.dist(start_position, stop_position)
                    stop_time = times[index + window - 1] - times[brake_index]
                break
    # Geometry from the independently reconstructed clearance inputs on valid
    # rows (production clearance metrics are comparison targets only).
    min_path_clearance = None
    min_path_clearance_gap = None
    min_center_distance = None
    min_envelope_gap = None
    robot_radius = None
    obstacle_radius = None
    for row in run_rows:
        record = row.get('clearance')
        if not isinstance(record, dict) or not isinstance(
                record.get('validity'), dict) \
                or record['validity'].get('valid') is not True:
            continue
        inputs = record.get('inputs') if isinstance(record.get('inputs'),
                                                    dict) else {}
        algorithm = record.get('algorithm') \
            if isinstance(record.get('algorithm'), dict) else {}
        horizon = _fnum(algorithm.get('prediction_horizon_s'))
        step_s = _fnum(algorithm.get('prediction_step_s'))
        if horizon is None or step_s is None:
            continue
        recomputed = _recompute_clearance(inputs, horizon, step_s)
        if recomputed is None:
            continue
        envelopes = record.get('envelopes') \
            if isinstance(record.get('envelopes'), dict) else {}
        robot_env = envelopes.get('robot') \
            if isinstance(envelopes.get('robot'), dict) else {}
        obstacle_env = envelopes.get('obstacle') \
            if isinstance(envelopes.get('obstacle'), dict) else {}
        if _num(robot_env.get('radius_m')):
            robot_radius = float(robot_env['radius_m'])
        if _num(obstacle_env.get('radius_m')):
            obstacle_radius = float(obstacle_env['radius_m'])
        path = recomputed['path_clearance_m']
        center = recomputed['center_distance_m']
        if min_path_clearance is None or path < min_path_clearance:
            min_path_clearance = path
        if min_center_distance is None or center < min_center_distance:
            min_center_distance = center
        if _num(robot_env.get('radius_m')) \
                and _num(obstacle_env.get('radius_m')):
            gap = path - (robot_env['radius_m'] + obstacle_env['radius_m'])
            if min_path_clearance_gap is None or gap < min_path_clearance_gap:
                min_path_clearance_gap = gap
            envelope_gap = center - (robot_env['radius_m']
                                     + obstacle_env['radius_m'])
            if min_envelope_gap is None or envelope_gap < min_envelope_gap:
                min_envelope_gap = envelope_gap
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
    for velocity, obstacle_velocity in zip(velocities, obstacle_velocities):
        if velocity is None or obstacle_velocity is None:
            continue
        relative = math.sqrt(sum((velocity[axis] - obstacle_velocity[axis]) ** 2
                                 for axis in range(3)))
        if max_relative is None or relative > max_relative:
            max_relative = relative
    contact_max = 0.0
    contact_prim = ''
    first_contact_time = None
    first_contact_phase = None
    first_inferred_time = None
    inferred_any = False
    measured_any = False
    max_overlap = 0.0
    for index, row in enumerate(metric_rows):
        row_evidence = row.get('contact_evidence')
        row_evidence = row_evidence if isinstance(row_evidence, dict) else {}
        force = _fnum(row.get('contact_force_n'))
        if force is None:
            force = _fnum(row_evidence.get('sensor_force_n'))
        row_measured = force is not None and force > CONTACT_FORCE_N
        if row_measured:
            measured_any = True
            if force > contact_max:
                contact_max = force
        overlap = _fnum(row_evidence.get('sphere_overlap_m'))
        if overlap is not None:
            max_overlap = max(max_overlap, overlap)
        row_inferred = row_evidence.get('inferred_contact') is True \
            or (overlap is not None and overlap > CONTACT_OVERLAP_M)
        row_time = times[index]
        row_phase = row.get('phase')
        if row_inferred:
            inferred_any = True
            if first_inferred_time is None:
                first_inferred_time = row_time
                first_contact_phase = row_phase
        if (row_measured or row_inferred) and (first_contact_time is None
                                               or (row_time is not None
                                                   and first_contact_time
                                                   is not None
                                                   and row_time
                                                   < first_contact_time)):
            first_contact_time = row_time
            first_contact_phase = row_phase
        prim = row.get('contact_prim')
        if prim and not contact_prim:
            contact_prim = str(prim)
    if measured_any:
        physical_outcome = 'CONTACT_MEASURED'
    elif inferred_any:
        physical_outcome = 'CONTACT_INFERRED'
    else:
        physical_outcome = 'NO_CONTACT'
    if not contact_prim and inferred_any:
        contact_prim = 'INFERRED_OBSTACLE_OVERLAP'
    obstacle_approach_after_stop = None
    if stop_complete_time is not None:
        at_stop = None
        after_min = None
        for index, time_s in enumerate(times):
            if time_s is None or distances[index] is None:
                continue
            if abs(time_s - stop_complete_time) <= 1e-9:
                at_stop = distances[index]
            if time_s >= stop_complete_time - 1e-9:
                if after_min is None or distances[index] < after_min:
                    after_min = distances[index]
        if at_stop is not None and after_min is not None:
            obstacle_approach_after_stop = at_stop - after_min
    post_steps = len(post_rows)
    residual = 0.0
    time_to_stop = 0.0
    post_contact = False
    if post_rows:
        first = post_rows[0]
        last = post_rows[-1]
        first_position = _vec(first.get('position_world_m'))
        last_position = _vec(last.get('position_world_m'))
        if first_position is not None and last_position is not None:
            residual = math.dist(first_position, last_position)
        post_speeds = [_fnum(row.get('speed_mps')) for row in post_rows]
        first_time = _fnum(first.get('time_s'))
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
            (_num(row.get('contact_force_n'))
             and _fnum(row.get('contact_force_n')) > CONTACT_FORCE_N)
            or (isinstance(row.get('contact_evidence'), dict)
                and (row['contact_evidence'].get('inferred_contact') is True
                     or (_fnum(row['contact_evidence'].get(
                         'sphere_overlap_m')) or 0.0) > CONTACT_OVERLAP_M))
            for row in post_rows)
    business_outcome_time = None
    business_outcome = episode.get('business_outcome')
    for row in run_rows:
        if row.get('outcome') == business_outcome \
                and _num(row.get('time_s')):
            business_outcome_time = float(row['time_s'])
    extreme = ctx.get('analysis_ref') or {}
    stop_stats = extreme.get('stop_requirement') or {}
    return {
        'brake_start': brake,
        'initial_speed_mps': (brake or {}).get('speed_mps'),
        'stop_distance_m': stop_distance,
        'stop_time_s': stop_time,
        'stop_complete_time_s': stop_complete_time,
        'stop_definition': ('speed<=0.08_mps_sustained_0.5s_'
                            'along_initial_speed_direction'),
        'min_path_clearance_m': min_path_clearance,
        'min_path_clearance_gap_sphere_m': min_path_clearance_gap,
        'min_center_distance_m': min_center_distance,
        'min_envelope_gap_sphere_m': min_envelope_gap,
        'max_closing_speed_mps': max_closing,
        'max_relative_speed_mps': max_relative,
        'contact_max_force_n': contact_max,
        'contact_prim': contact_prim,
        'first_contact_time_s': first_contact_time,
        'first_contact_phase': first_contact_phase,
        'first_inferred_contact_time_s': first_inferred_time,
        'inferred_contact': inferred_any,
        'measured_contact': measured_any,
        'max_sphere_overlap_m': max_overlap,
        'obstacle_approach_after_stop_m': obstacle_approach_after_stop,
        'post_abort': {'steps': post_steps,
                       'residual_distance_m': residual,
                       'time_to_stop_s': time_to_stop,
                       'contact': post_contact},
        'robot_radius_m': robot_radius,
        'obstacle_radius_m': obstacle_radius,
        'physical_outcome': physical_outcome,
        'business_outcome_time_s': business_outcome_time,
        'stop_requirement_stats': {
            'unsupported_steps': stop_stats.get('unsupported_steps', 0),
            'unsupported_reasons': {
                key: value for key, value in
                (stop_stats.get('unsupported_reasons') or {}).items()},
            'min_margin_m': stop_stats.get('min_margin_m'),
            'max_robot_speed_mps': stop_stats.get('max_robot_speed_mps'),
        },
    }


def _metric_mismatch(verifier, label, episode_id, field, expected, actual):
    verifier.fail('metrics_match_recorded', 'recorded metric disagrees with '
                  'the independent recomputation', run=label,
                  episode_id=episode_id, field='metrics.' + field,
                  expected=expected, actual=actual)


def check_metrics_match(evidence, episode, ctx, verifier, analysis):
    label = evidence.label
    episode_id = episode.get('episode_id')
    recorded = episode.get('metrics') if isinstance(episode.get('metrics'),
                                                    dict) else {}
    recomputed = analysis['metrics']
    recorded_brake = recorded.get('brake_start')
    expected_brake = recomputed.get('brake_start')
    if recorded_brake is None and expected_brake is None:
        pass
    elif not isinstance(recorded_brake, dict) \
            or not isinstance(expected_brake, dict):
        _metric_mismatch(verifier, label, episode_id, 'brake_start',
                         expected_brake, recorded_brake)
    else:
        for field, tolerance in (('time_s', METRIC_TOL_TIME_S),
                                 ('speed_mps', METRIC_TOL_SPEED_MPS),
                                 ('observation_age_s', AGE_TOL_S)):
            if not _close(recorded_brake.get(field),
                          expected_brake.get(field), tolerance):
                _metric_mismatch(verifier, label, episode_id,
                                 'brake_start.' + field,
                                 expected_brake.get(field),
                                 recorded_brake.get(field))
        for field in ('position_world_m', 'velocity_world_mps'):
            if not _vec_close(recorded_brake.get(field),
                              expected_brake.get(field),
                              METRIC_TOL_DIST_M):
                _metric_mismatch(verifier, label, episode_id,
                                 'brake_start.' + field,
                                 expected_brake.get(field),
                                 recorded_brake.get(field))
        if recorded_brake.get('step') != expected_brake.get('step'):
            _metric_mismatch(verifier, label, episode_id, 'brake_start.step',
                             expected_brake.get('step'),
                             recorded_brake.get('step'))
        if recorded_brake.get('supervisor_state') \
                != expected_brake.get('supervisor_state'):
            _metric_mismatch(verifier, label, episode_id,
                             'brake_start.supervisor_state',
                             expected_brake.get('supervisor_state'),
                             recorded_brake.get('supervisor_state'))
    numeric = (
        ('initial_speed_mps', METRIC_TOL_SPEED_MPS),
        ('stop_distance_m', METRIC_TOL_DIST_M),
        ('stop_time_s', METRIC_TOL_TIME_S),
        ('min_path_clearance_m', METRIC_TOL_DIST_M),
        ('min_path_clearance_gap_sphere_m', METRIC_TOL_DIST_M),
        ('min_center_distance_m', METRIC_TOL_DIST_M),
        ('min_envelope_gap_sphere_m', METRIC_TOL_DIST_M),
        ('max_closing_speed_mps', METRIC_TOL_SPEED_MPS),
        ('max_relative_speed_mps', METRIC_TOL_SPEED_MPS),
        ('contact_max_force_n', METRIC_TOL_FORCE_N),
    )
    for field, tolerance in numeric:
        expected = recomputed.get(field)
        actual = recorded.get(field)
        if expected is None and actual is None:
            continue
        if not _close(actual, expected, tolerance):
            _metric_mismatch(verifier, label, episode_id, field, expected,
                             actual)
    if str(recorded.get('contact_prim') or '') \
            != str(recomputed.get('contact_prim') or ''):
        _metric_mismatch(verifier, label, episode_id, 'contact_prim',
                         recomputed.get('contact_prim'),
                         recorded.get('contact_prim'))
    if recomputed.get('brake_start') is not None:
        if not recorded.get('stop_definition'):
            _metric_mismatch(verifier, label, episode_id, 'stop_definition',
                             recomputed['stop_definition'],
                             recorded.get('stop_definition'))
    envelope = recorded.get('conservative_envelope')
    if isinstance(envelope, dict):
        robot_radius = envelope.get('robot_radius_m',
                                    envelope.get('radius_m'))
        if recomputed.get('robot_radius_m') is not None \
                and not _close(robot_radius, recomputed['robot_radius_m'],
                               GEOM_TOL):
            _metric_mismatch(verifier, label, episode_id,
                             'conservative_envelope.robot_radius_m',
                             recomputed['robot_radius_m'], robot_radius)
        if recomputed.get('obstacle_radius_m') is not None \
                and not _close(envelope.get('obstacle_radius_m'),
                               recomputed['obstacle_radius_m'], GEOM_TOL):
            _metric_mismatch(verifier, label, episode_id,
                             'conservative_envelope.obstacle_radius_m',
                             recomputed['obstacle_radius_m'],
                             envelope.get('obstacle_radius_m'))
        body = ctx.get('body_envelope') or {}
        body_half = _vec(body.get('half_extents_m'))
        if body_half is not None:
            expected_radius = box_conservative_sphere_radius(body_half)
            if not _close(robot_radius, expected_radius, GEOM_TOL):
                _metric_mismatch(
                    verifier, label, episode_id,
                    'conservative_envelope.robot_radius_m', expected_radius,
                    robot_radius)
    recorded_post = recorded.get('post_abort')
    expected_post = recomputed['post_abort']
    if isinstance(recorded_post, dict):
        if expected_post['steps'] > 0:
            if recorded_post.get('steps') != expected_post['steps']:
                _metric_mismatch(verifier, label, episode_id,
                                 'post_abort.steps', expected_post['steps'],
                                 recorded_post.get('steps'))
            if not _equal_nullable(recorded_post.get('residual_distance_m'),
                                   expected_post['residual_distance_m'],
                                   METRIC_TOL_DIST_M):
                _metric_mismatch(verifier, label, episode_id,
                                 'post_abort.residual_distance_m',
                                 expected_post['residual_distance_m'],
                                 recorded_post.get('residual_distance_m'))
            if not _equal_nullable(recorded_post.get('time_to_stop_s'),
                                   expected_post['time_to_stop_s'],
                                   METRIC_TOL_TIME_S):
                _metric_mismatch(verifier, label, episode_id,
                                 'post_abort.time_to_stop_s',
                                 expected_post['time_to_stop_s'],
                                 recorded_post.get('time_to_stop_s'))
            recorded_contact = recorded_post.get('contact')
            if recorded_contact is None \
                    and _num(recorded_post.get('contact_max_force_n')):
                recorded_contact = (recorded_post['contact_max_force_n']
                                    > CONTACT_FORCE_N)
            if recorded_contact is not None \
                    and bool(recorded_contact) != expected_post['contact']:
                _metric_mismatch(verifier, label, episode_id,
                                 'post_abort.contact',
                                 expected_post['contact'], recorded_contact)
    extremes = recorded.get('stop_requirement_extremes')
    stats = recomputed['stop_requirement_stats']
    if isinstance(extremes, dict):
        if extremes.get('unsupported_steps') != stats['unsupported_steps']:
            _metric_mismatch(verifier, label, episode_id,
                             'stop_requirement_extremes.unsupported_steps',
                             stats['unsupported_steps'],
                             extremes.get('unsupported_steps'))
        recorded_reasons = extremes.get('unsupported_reasons')
        if isinstance(recorded_reasons, dict):
            if {str(key): int(value)
                    for key, value in recorded_reasons.items()} \
                    != {str(key): int(value)
                        for key, value in stats['unsupported_reasons'].items()}:
                _metric_mismatch(
                    verifier, label, episode_id,
                    'stop_requirement_extremes.unsupported_reasons',
                    stats['unsupported_reasons'], recorded_reasons)
        if not _equal_nullable(extremes.get('min_margin_m'),
                               stats['min_margin_m'], METRIC_TOL_DIST_M):
            _metric_mismatch(verifier, label, episode_id,
                             'stop_requirement_extremes.min_margin_m',
                             stats['min_margin_m'],
                             extremes.get('min_margin_m'))
        if not _equal_nullable(extremes.get('max_robot_speed_mps'),
                               stats['max_robot_speed_mps'],
                               METRIC_TOL_SPEED_MPS):
            _metric_mismatch(
                verifier, label, episode_id,
                'stop_requirement_extremes.max_robot_speed_mps',
                stats['max_robot_speed_mps'],
                extremes.get('max_robot_speed_mps'))
    if ctx.get('contact_mode') in CONTACT_EVIDENCE_MODES:
        summary = recorded.get('contact_evidence_summary')
        evidence_stats = analysis.get('contact_evidence') or {}
        if isinstance(summary, dict):
            radii_sum = ctx.get('radii_sum_m')
            pairs = (
                ('max_sensor_force_n',
                 evidence_stats.get('max_sensor_force_n'),
                 METRIC_TOL_FORCE_N),
                ('max_sphere_overlap_m',
                 evidence_stats.get('max_sphere_overlap_m'),
                 METRIC_TOL_DIST_M),
                ('first_inferred_contact_time_s',
                 evidence_stats.get('first_inferred_contact_time_s'),
                 METRIC_TOL_TIME_S),
                ('radii_sum_m', radii_sum, GEOM_TOL),
            )
            for field, expected, tolerance in pairs:
                if not _equal_nullable(summary.get(field), expected,
                                       tolerance):
                    _metric_mismatch(verifier, label, episode_id,
                                     'contact_evidence_summary.' + field,
                                     expected, summary.get(field))
            recorded_inferred = summary.get('inferred_contact')
            if recorded_inferred is not None \
                    and bool(recorded_inferred) \
                    != bool(evidence_stats.get('inferred_contact')):
                _metric_mismatch(verifier, label, episode_id,
                                 'contact_evidence_summary.inferred_contact',
                                 evidence_stats.get('inferred_contact'),
                                 recorded_inferred)
    verifier.ok_if_clean('metrics_match_recorded',
                         'recorded metrics recomputed for %s' % episode_id)


def check_business_physical(evidence, episode, ctx, verifier, analysis):
    name = 'business_physical_outcome'
    label = evidence.label
    episode_id = episode.get('episode_id')
    recomputed = analysis['metrics']
    business = episode.get('business_outcome')
    physical = episode.get('physical_outcome')
    if business is None:
        verifier.missing.add(label, 'episodes[].business_outcome',
                             'episode %s' % episode_id)
    if physical is None:
        verifier.missing.add(label, 'episodes[].physical_outcome',
                             'episode %s' % episode_id)
    if physical is not None and recomputed.get('physical_outcome'):
        if physical == 'OUT_OF_BOUNDS':
            verifier.note(name, 'recorded physical_outcome=OUT_OF_BOUNDS: the '
                          'contact-only recomputation does not classify '
                          'out-of-bounds geometry')
        elif physical != recomputed['physical_outcome']:
            verifier.fail(name, 'recorded physical_outcome does not match the '
                          'contact evidence recomputed from the raw rows',
                          run=label, episode_id=episode_id,
                          field='physical_outcome',
                          expected=recomputed['physical_outcome'],
                          actual=physical)
    # The final RUN row must carry the business outcome (no physical-only
    # outcome substituting for the business verdict).
    run_rows = [row for row in analysis['rows']
                if row.get('phase') != 'POST_ABORT']
    if run_rows and business is not None:
        terminal = run_rows[-1]
        if terminal.get('outcome') not in (None, 'RUNNING') \
                and terminal.get('outcome') != business:
            verifier.fail(name, 'final RUN step outcome differs from the '
                          'business_outcome', run=label,
                          episode_id=episode_id,
                          step=terminal.get('step'), field='outcome',
                          expected=business, actual=terminal.get('outcome'))
    verifier.ok_if_clean(name, 'business/physical outcome separation checked '
                         'for %s' % episode_id)


# ---------------------------------------------------------------------------
# scenario expectations
# ---------------------------------------------------------------------------

def _contact_time(analysis):
    recomputed = analysis['metrics']
    return recomputed.get('first_contact_time_s')


def _contact_after_business_stop(analysis):
    """Lead-aligned POST_STOP_COLLISION ordering.

    The first inferred/measured contact must happen after the robot has stopped
    (speed <= 0.08 m/s sustained 0.5 s, i.e. the stop-complete time), or in the
    POST_ABORT phase, or later than the business stop/ABORT time + 0.5 s settle
    window.  A contact while the robot is still moving is a deviation.
    """
    recomputed = analysis['metrics']
    contact = _contact_time(analysis)
    if contact is None:
        return False, 'no inferred/measured contact observed'
    phase = recomputed.get('first_contact_phase')
    if phase == 'POST_ABORT':
        return True, 'first contact %.6f s is in the POST_ABORT phase' % contact
    stop_complete = recomputed.get('stop_complete_time_s')
    business_time = recomputed.get('business_outcome_time_s')
    reasons = []
    if stop_complete is not None:
        if contact > stop_complete + 1e-9:
            return True, ('first contact %.6f s after stop complete %.6f s'
                          % (contact, stop_complete))
        reasons.append('first contact %.6f s <= stop complete %.6f s'
                       % (contact, stop_complete))
    else:
        reasons.append('no stop-complete time recomputed')
    if business_time is not None and contact > business_time + STOP_HOLD_S:
        return True, ('first contact %.6f s later than business stop %.6f s '
                      '+ %.1f s settle window'
                      % (contact, business_time, STOP_HOLD_S))
    reasons.append('first contact %.6f s vs business outcome %.6f s (+%.1f s)'
                   % (contact, business_time if business_time is not None
                      else float('nan'), STOP_HOLD_S))
    return False, '; '.join(reasons)


def _must_condition_eval(kind, value, analysis, episode):
    recomputed = analysis['metrics']
    business = episode.get('business_outcome')
    first_contact = recomputed.get('first_contact_time_s')
    business_time = recomputed.get('business_outcome_time_s')
    brake_speed = recomputed.get('initial_speed_mps')
    if kind == 'no_contact':
        return first_contact is None, \
            'inferred/measured contact observed at %.6f s' % first_contact \
            if first_contact is not None else 'no inferred/measured contact'
    if kind == 'contact':
        return first_contact is not None, 'no inferred/measured contact observed'
    if kind == 'contact_after_business_stop':
        return _contact_after_business_stop(analysis)
    if kind == 'contact_after_business_outcome':
        if first_contact is None:
            return False, 'no inferred/measured contact observed'
        if business_time is None:
            return False, 'no terminal business row time'
        return (first_contact > business_time + 1e-9,
                'first contact %.6f s vs business outcome %.6f s'
                % (first_contact, business_time))
    if kind == 'stop_started':
        return recomputed.get('brake_start') is not None, 'no STOP action'
    if kind == 'no_stop':
        run_rows = [row for row in analysis['rows']
                    if row.get('phase') != 'POST_ABORT']
        stopped = any(row.get('supervisor_action') == 'STOP'
                      or row.get('supervisor_state') in ('BRAKE', 'HOLD', 'WAIT')
                      for row in run_rows)
        return not stopped, 'a STOP/BRAKE/HOLD/WAIT event was recorded'
    if kind == 'business_outcome_in':
        values = value if isinstance(value, list) else [value]
        return business in values, 'business_outcome %s not in %s' % (
            business, values)
    clearance = recomputed.get('min_path_clearance_m')
    if kind == 'min_path_clearance_below_m':
        limit = _fnum(value)
        if clearance is None or limit is None:
            return False, 'min path clearance not recomputed'
        return clearance < limit, 'min path clearance %.6f not < %.6f' % (
            clearance, limit)
    if kind == 'min_path_clearance_at_least_m':
        limit = _fnum(value)
        if clearance is None or limit is None:
            return False, 'min path clearance not recomputed'
        return clearance >= limit, 'min path clearance %.6f not >= %.6f' % (
            clearance, limit)
    margin = (recomputed.get('stop_requirement_stats') or {}).get('min_margin_m')
    if kind == 'min_margin_below_m':
        limit = _fnum(value)
        if margin is None or limit is None:
            return False, 'min margin not recomputed'
        return margin < limit, 'min margin %.6f not < %.6f' % (margin, limit)
    if kind == 'min_margin_at_least_m':
        limit = _fnum(value)
        if margin is None or limit is None:
            return False, 'min margin not recomputed'
        return margin >= limit, 'min margin %.6f not >= %.6f' % (margin, limit)
    if kind == 'brake_speed_below_mps':
        limit = _fnum(value)
        if brake_speed is None or limit is None:
            return False, 'brake start speed not recomputed'
        return brake_speed < limit, 'brake speed %.6f not < %.6f' % (
            brake_speed, limit)
    if kind == 'brake_speed_at_least_mps':
        limit = _fnum(value)
        if brake_speed is None or limit is None:
            return False, 'brake start speed not recomputed'
        return brake_speed >= limit, 'brake speed %.6f not >= %.6f' % (
            brake_speed, limit)
    return None


def _parse_condition(condition):
    if isinstance(condition, str):
        return condition.strip(), None
    if isinstance(condition, dict):
        kind = condition.get('kind') or condition.get('condition')
        return (kind.strip() if isinstance(kind, str) else None,
                condition.get('value', condition.get('m')))
    return None, None


EXPECTATION_CHECK_NAMES = ('scenario_class_match', 'acceptable_outcomes',
                           'must_conditions', 'insufficient_margin_success_ban',
                           'post_stop_collision_ordering',
                           'unsupported_allowed_scope')


def _mark_expectation_checked(verifier, case_id):
    for name in EXPECTATION_CHECK_NAMES:
        verifier.ok_if_clean(name, 'expectation checked for %s' % case_id)


def check_expected_episode(evidence, episode, ctx, verifier, analysis):
    label = evidence.label
    episode_id = episode.get('episode_id')
    case_id = episode.get('case_id')
    segment_id = evidence.segment_id
    expected_index = ctx.get('expected_index')
    plan = ctx.get('plan') or {}
    role = plan.get('role')
    if expected_index is None:
        verifier.missing.add(label, 'expected config', 'cli')
        return
    # Role dispatch (Lead-aligned): boundary/main segments use the pre-frozen
    # 8-class expectation; special segments use their declared path/criteria
    # checks; regression segments are compared with the existing v2 evidence.
    if role == 'regression':
        business = episode.get('business_outcome')
        if business != 'SUCCESS':
            verifier.fail('expected_config_coverage', 'regression run outcome is '
                          'not SUCCESS (existing v2 regression evidence expects '
                          'SUCCESS)', run=label, episode_id=episode_id,
                          field='business_outcome', expected='SUCCESS',
                          actual=business)
        else:
            verifier.ok_if_clean('expected_config_coverage',
                                 'regression %s business SUCCESS matches the '
                                 'existing v2 regression evidence' % episode_id)
        _mark_expectation_checked(verifier, case_id)
        return
    if role == 'special':
        verifier.ok_if_clean('expected_config_coverage',
                             'special segment %s uses the declared defaults and '
                             'the dedicated special checks' % segment_id)
        _mark_expectation_checked(verifier, case_id)
        return
    spec = expected_index.lookup(segment_id, case_id)
    if spec is None:
        verifier.missing.add(label, 'expected classification for case %s'
                             % case_id, 'episode %s' % episode_id)
        _mark_expectation_checked(verifier, case_id)
        return
    verifier.ok_if_clean('expected_config_coverage',
                         'expected classification present for %s' % case_id)
    evaluated = set()
    test_class = spec.get('scenario_class')
    if test_class is None:
        verifier.missing.add(label, 'expected.scenario_class for case %s'
                             % case_id, 'episode %s' % episode_id)
    elif test_class not in SCENARIO_CLASSES:
        verifier.fail('scenario_class_match', 'expected scenario_class is not a '
                      'known boundary class', run=label,
                      episode_id=episode_id, field='scenario_class',
                      expected=list(SCENARIO_CLASSES), actual=test_class)
        evaluated.add('scenario_class_match')
    else:
        evaluated.add('scenario_class_match')
        actual_class = episode.get('scenario_class')
        if actual_class != test_class:
            verifier.deviate('scenario_class_match', 'scenario_class_mismatch',
                             'recorded scenario_class does not match the '
                             'pre-frozen expected class', run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected=test_class, actual=actual_class)
    acceptable = spec.get('acceptable_outcomes')
    if not isinstance(acceptable, list) or not acceptable:
        verifier.missing.add(label, 'expected.acceptable_outcomes for case %s'
                             % case_id, 'episode %s' % episode_id)
    else:
        evaluated.add('acceptable_outcomes')
        business = episode.get('business_outcome')
        if business not in acceptable:
            verifier.deviate(
                'acceptable_outcomes', 'business_outcome_not_acceptable',
                'business outcome %s is not in the pre-frozen acceptable set %s'
                % (business, acceptable), run=label, episode_id=episode_id,
                case_id=case_id, expected=acceptable, actual=business)
    # must_conditions
    conditions = spec.get('must_conditions')
    if conditions is None:
        conditions = []
    if not isinstance(conditions, list):
        verifier.missing.add(label, 'expected.must_conditions for case %s'
                             % case_id, 'episode %s' % episode_id)
        conditions = []
    for condition in conditions:
        kind, value = _parse_condition(condition)
        if kind is None or kind not in MUST_CONDITION_KINDS:
            verifier.missing.add(label, 'supported expected.must_conditions kind '
                                 'for case %s' % case_id,
                                 'episode %s (%r)' % (episode_id, kind))
            continue
        outcome = _must_condition_eval(kind, value, analysis, episode)
        passed, detail = outcome if outcome is not None else (False, 'not '
                                                              'evaluated')
        if not passed:
            verifier.deviate('must_conditions', 'must_condition_failed',
                             'must condition %r failed: %s' % (kind, detail),
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=condition, actual=detail,
                             context={'condition_kind': kind})
    # built-in class semantics
    test_class_name = test_class if isinstance(test_class, str) else ''
    business = episode.get('business_outcome')
    recomputed = analysis['metrics']
    if test_class_name == 'INSUFFICIENT_MARGIN':
        if business == 'SUCCESS':
            verifier.deviate(
                'insufficient_margin_success_ban',
                'insufficient_margin_success',
                'INSUFFICIENT_MARGIN case completed as business SUCCESS',
                run=label, episode_id=episode_id, case_id=case_id,
                expected='not SUCCESS', actual=business)
    if test_class_name == 'POST_STOP_COLLISION':
        first_contact = recomputed.get('first_contact_time_s')
        first_inferred = recomputed.get('first_inferred_contact_time_s')
        business_time = recomputed.get('business_outcome_time_s')
        if first_contact is None:
            verifier.deviate('post_stop_collision_ordering',
                             'post_stop_collision_missing_contact',
                             'POST_STOP_COLLISION case recorded neither a '
                             'measured force nor an inferred sphere overlap',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='contact after the business stop',
                             actual='no inferred/measured contact')
        else:
            contact_ok, contact_detail = _contact_after_business_stop(analysis)
            if not contact_ok:
                verifier.deviate(
                    'post_stop_collision_ordering',
                    'post_stop_collision_contact_before_stop',
                    'contact ordering does not satisfy POST_STOP_COLLISION',
                    run=label, episode_id=episode_id, case_id=case_id,
                    expected='first contact after stop-complete / POST_ABORT / '
                             'business stop + 0.5 s',
                    actual=contact_detail,
                    context={'first_contact_time_s': first_contact,
                             'first_inferred_contact_time_s': first_inferred,
                             'stop_complete_time_s': recomputed.get(
                                 'stop_complete_time_s'),
                             'business_outcome_time_s': business_time,
                             'contact_evidence_mode': ctx.get('contact_mode')})
    if test_class_name == 'NO_STOP_EXPECTED':
        run_rows = [row for row in analysis['rows']
                    if row.get('phase') != 'POST_ABORT']
        stopped = any(row.get('supervisor_action') == 'STOP'
                      or row.get('supervisor_state') in ('BRAKE', 'HOLD', 'WAIT')
                      for row in run_rows)
        if stopped:
            verifier.deviate('must_conditions', 'unexpected_stop',
                             'NO_STOP_EXPECTED case triggered a STOP/WAIT state',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='no stop', actual='stop recorded')
    if test_class_name in STOP_REQUIRED_CLASSES:
        if recomputed.get('brake_start') is None:
            verifier.deviate('must_conditions', 'expected_stop_missing',
                             'scenario class requires a STOP but no brake start '
                             'was recorded', run=label, episode_id=episode_id,
                             case_id=case_id, expected='STOP', actual='none')
    # unsupported_allowed scope
    evaluated.add('unsupported_allowed_scope')
    allowed = spec.get('unsupported_allowed', False)
    stop_stats = analysis['stop_requirement']
    unsupported_steps = stop_stats.get('unsupported_steps', 0)
    reasons = {str(key) for key, value in
               (stop_stats.get('unsupported_reasons') or {}).items()
               if value}
    scope_name = 'unsupported_allowed_scope'
    if unsupported_steps:
        if allowed is True:
            verifier.ok_if_clean(scope_name, 'UNSUPPORTED steps are declared '
                                 'allowed for %s' % case_id)
        elif isinstance(allowed, list):
            not_allowed = sorted(reasons - {str(item) for item in allowed})
            if not_allowed:
                verifier.deviate(scope_name, 'unsupported_reason_not_allowed',
                                 'UNSUPPORTED reasons outside the declared '
                                 'allowed set: %s' % not_allowed, run=label,
                                 episode_id=episode_id, case_id=case_id,
                                 expected=allowed, actual=sorted(reasons))
            else:
                verifier.ok_if_clean(scope_name, 'UNSUPPORTED reasons within '
                                     'the declared allowed set for %s' % case_id)
        else:
            verifier.deviate(scope_name, 'unsupported_not_allowed',
                             'UNSUPPORTED stop requirement appeared where the '
                             'pre-frozen expectation does not allow it: %s'
                             % sorted(reasons), run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected=False, actual=sorted(reasons))
    else:
        verifier.ok_if_clean(scope_name, 'no UNSUPPORTED stop requirement for %s'
                             % case_id)
    if isinstance(conditions, list):
        evaluated.add('must_conditions')
    if test_class_name:
        evaluated.add('insufficient_margin_success_ban')
        evaluated.add('post_stop_collision_ordering')
    for name in EXPECTATION_CHECK_NAMES:
        if name in evaluated:
            verifier.ok_if_clean(name, 'expectation checked for %s' % case_id)


def check_expected_coverage(evidence, ctx, verifier):
    name = 'expected_config_coverage'
    label = evidence.label
    expected_index = ctx.get('expected_index')
    plan = ctx.get('plan') or {}
    if expected_index is None:
        return
    observed = Counter(str(episode.get('case_id'))
                       for episode in evidence.episodes
                       if isinstance(episode, dict))
    role = plan.get('role')
    checked = 0
    for case_id, count in observed.items():
        spec = expected_index.lookup(evidence.segment_id, case_id)
        if spec is None:
            if role == 'regression':
                verifier.ok_if_clean(name, 'regression case %s has no pre-run '
                                     'expectation (existing evidence)'
                                     % case_id)
            else:
                verifier.missing.add(
                    label, 'expected classification for case %s' % case_id,
                    evidence.segment_id)
            continue
        checked += 1
        repeats = spec.get('repeats')
        if not _num(repeats):
            repeats = DEFAULT_REPEATS if _is_boundary_segment(
                evidence.segment_id) else 1
        repeats = int(repeats)
        if count < repeats:
            verifier.missing.add(
                label, 'expected case %s episodes (expected %d, observed %d)'
                % (case_id, repeats, count), evidence.segment_id)
        elif count > repeats:
            verifier.fail(name, 'more episodes recorded for case %s than the '
                          'pre-frozen repeat count', run=label, field='case_id',
                          expected=repeats, actual=count)
    verifier.ok_if_clean(name, 'expected coverage checked for %s '
                         '(%d cases, %d episodes)'
                         % (evidence.segment_id, checked, sum(observed.values())))


# ---------------------------------------------------------------------------
# special (recheck) segments with pre-declared acceptable paths / criteria
# ---------------------------------------------------------------------------

_SPECIAL_PATH_FIELDS = ('admission_reject_reason', 'arrival_reject_reason',
                        'observation_reason', 'supervisor_reason',
                        'episode_reason', 'reason')


def _expected_segment_defaults(ctx, segment_id):
    expected_index = ctx.get('expected_index')
    if expected_index is None:
        return {}
    segment = expected_index.segment_spec(segment_id)
    if segment is None:
        return {}
    return segment.get('defaults') or {}


def _actual_mapping_paths(evidence):
    actual = {field: set() for field in _SPECIAL_PATH_FIELDS}
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        reason = episode.get('reason')
        if reason:
            actual['supervisor_reason'].add(str(reason))
            actual['episode_reason'].add(str(reason))
        rows = _sorted_rows(evidence.steps_by_episode.get(
            episode.get('episode_id'), []))
        for row in rows:
            admission = row.get('v2_reject_reason')
            if admission:
                actual['admission_reject_reason'].add(str(admission))
            observation = row.get('observation_reason')
            if observation:
                actual['observation_reason'].add(str(observation))
            transport = row.get('transport')
            if isinstance(transport, dict) and transport.get('reason'):
                actual['arrival_reject_reason'].add(
                    str(transport['reason']))
                if row.get('phase') != 'POST_ABORT':
                    actual['reason'].add(str(transport['reason']))
    return actual


def check_special_clock_mapping(evidence, ctx, verifier):
    name = 'special_clock_mapping_paths'
    label = evidence.label
    defaults = _expected_segment_defaults(ctx, evidence.segment_id)
    paths = defaults.get('acceptable_paths')
    if not isinstance(paths, list) or not paths:
        verifier.missing.add(label, 'expected segment %s defaults.'
                             'acceptable_paths' % evidence.segment_id, label)
        return
    must_hit = defaults.get('must_hit_declared_path', True)
    actual = _actual_mapping_paths(evidence)
    hits = []
    for index, path in enumerate(paths):
        if not isinstance(path, dict):
            verifier.missing.add(label, 'acceptable_paths[] entry', label)
            continue
        specified = {key: value for key, value in path.items()
                     if key in _SPECIAL_PATH_FIELDS and value}
        if not specified:
            verifier.missing.add(label, 'acceptable_paths[] declared field',
                                 label)
            continue
        matched_fields = {}
        hit = True
        for key, value in specified.items():
            values = actual.get(key) or set()
            text = str(value)
            match = text in values
            if not match:
                hit = False
                break
            matched_fields[key] = text
        if hit:
            hits.append({'priority': index + 1, 'path': specified,
                         'matched': matched_fields})
    if not hits:
        if must_hit is False:
            verifier.ok(name, 'no declared clock-mapping path hit, but '
                        'must_hit_declared_path=false (allowed)')
            return
        verifier.fail(name, 'the run did not hit any pre-declared acceptable '
                      'clock-mapping path (the set is frozen before the run and '
                      'must not be extended afterwards)', run=label,
                      field='acceptable_paths', expected=paths,
                      actual={key: sorted(values) for key, values in
                              actual.items() if values})
        return
    first = min(hits, key=lambda entry: entry['priority'])
    verifier.ok(name, 'hit pre-declared clock-mapping path #%d %s '
                '(must_hit_declared_path=%s)'
                % (first['priority'], first['matched'], must_hit))


def check_special_ttl_over(evidence, ctx, verifier):
    name = 'special_ttl_over_criteria'
    label = evidence.label
    defaults = _expected_segment_defaults(ctx, evidence.segment_id)
    plan = ctx.get('plan') or {}
    ttl_ns = ctx.get('ttl_ns')
    ttl_s = (ttl_ns / 1e9) if ttl_ns is not None else None
    criteria_id = defaults.get('criteria_id')
    if criteria_id is not None and str(criteria_id) != '(c)':
        verifier.fail(name, 'the declared ttl_over criteria is not (c)', run=label,
                      field='criteria_id', expected='(c)', actual=criteria_id)
    declared_outcomes = None
    for key in ('acceptable_outcomes', 'business_outcomes',
                'expected_outcomes'):
        value = defaults.get(key)
        if isinstance(value, list) and value:
            declared_outcomes = [str(item) for item in value]
            break
    if declared_outcomes is None:
        value = defaults.get('expected_outcome')
        if value:
            declared_outcomes = [str(value)]
            if isinstance(defaults.get('expected_outcome_alternatives'), list):
                declared_outcomes += [str(item) for item in
                                      defaults['expected_outcome_alternatives']]
    if declared_outcomes is None:
        verifier.missing.add(label, 'expected segment %s defaults business '
                             'outcome set' % evidence.segment_id, label)
    finished = {}

    def mark(key, ok, detail):
        finished[key] = {'passed': bool(ok), 'detail': detail}
        if not ok:
            verifier.fail(name, 'ttl_over criterion %s failed: %s'
                          % (key, detail), run=label, field=key)

    # Collect the transport sequence.
    rows = []
    for episode in evidence.episodes:
        if isinstance(episode, dict):
            rows.extend(_sorted_rows(evidence.steps_by_episode.get(
                episode.get('episode_id'), [])))
    rows.sort(key=_row_key)
    first_rejection_index = None
    rejected_ids = set()
    executed_ids = set()
    rejection_ok = False
    expiry_none_ok = False
    for index, row in enumerate(rows):
        transport = row.get('transport')
        if not isinstance(transport, dict):
            continue
        status = transport.get('status')
        action_id = transport.get('action_id')
        executed_id = transport.get('executed_action_id')
        arrival_age = _fnum(transport.get('arrival_age_s'))
        reason = transport.get('reason')
        if status == 'REJECTED':
            if action_id:
                rejected_ids.add(str(action_id))
            if reason == 'ACTION_EXPIRED' and arrival_age is not None \
                    and ttl_s is not None and arrival_age + 1e-9 >= ttl_s \
                    and not transport.get('executed'):
                rejection_ok = True
            if first_rejection_index is None:
                first_rejection_index = index
        if status in ('APPLIED', 'DIRECT', 'HOLDING') and executed_id:
            executed_ids.add(str(executed_id))
        for extra in transport.get('rejections_this_step') or []:
            if isinstance(extra, dict) and extra.get('action_id'):
                rejected_ids.add(str(extra['action_id']))
                extra_age = _fnum(extra.get('arrival_age_s'))
                if extra.get('reason') == 'ACTION_EXPIRED' \
                        and extra_age is not None and ttl_s is not None \
                        and extra_age + 1e-9 >= ttl_s:
                    rejection_ok = True
        if status == 'NONE' and reason == 'ACTION_EXPIRED':
            expiry_none_ok = True
    mark('1_action_expired_rejection',
         rejection_ok and first_rejection_index is not None,
         'ACTION_EXPIRED arrival rejection with age >= TTL and executed=False')
    mark('2_rejected_never_executed',
         rejection_ok and not (rejected_ids & executed_ids),
         'rejected ids=%d executed ids=%d intersection=%s'
         % (len(rejected_ids), len(executed_ids),
            sorted(rejected_ids & executed_ids)))
    # 3: contiguous APPLIED/HOLDING before the first rejection with a strictly
    # later expiry than the last executing row host time.
    prefix = rows[:first_rejection_index] if first_rejection_index is not None \
        else []
    contiguous = 0
    last_active = None
    for row in reversed(prefix):
        transport = row.get('transport') if isinstance(row.get('transport'),
                                                        dict) else {}
        if transport.get('status') in ('APPLIED', 'HOLDING'):
            contiguous += 1
            last_active = (row, transport)
        else:
            break
    active_expiry_ok = False
    if last_active is not None:
        row, transport = last_active
        clock = row.get('clock') if isinstance(row.get('clock'), dict) else {}
        host = clock.get('host_now_ns')
        expires = transport.get('expires_at_ns')
        active_expiry_ok = (_num(host) and _num(expires) and expires > host)
    mark('3_old_active_before_rejection',
         contiguous > 0 and active_expiry_ok,
         'contiguous APPLIED/HOLDING rows before first rejection=%d, active '
         'expiry strictly after host=%s' % (contiguous, active_expiry_ok))
    mark('4_active_expiry_to_none', expiry_none_ok,
         'recorded NONE row with reason ACTION_EXPIRED')
    # 5: after the first rejection a zero-target fallback appears; record the
    # residual distance/time of the post-rejection (coasting) window.
    fallback = False
    residual = None
    residual_time = None
    if first_rejection_index is not None:
        tail = rows[first_rejection_index:]
        for row in tail:
            applied = row.get('applied') if isinstance(row.get('applied'),
                                                       dict) else {}
            speed = _fnum(row.get('speed_mps'))
            transport = row.get('transport') \
                if isinstance(row.get('transport'), dict) else {}
            zero = all((_fnum(applied.get(field)) or 0.0) == 0.0
                       for field in ('vx_forward_mps', 'vy_left_mps',
                                     'vz_up_mps',
                                     'yaw_rate_ccw_world_radps'))
            if (speed is not None and speed <= STOP_SPEED_MPS) \
                    or (transport.get('status') == 'NONE' and zero):
                fallback = True
                break
        positions = []
        times = []
        for row in tail:
            position = _vec(row.get('position_world_m'))
            time_s = _fnum(row.get('time_s'))
            if position is not None and time_s is not None:
                positions.append(position)
                times.append(time_s)
        if positions:
            residual = math.dist(positions[0], positions[-1])
            residual_time = times[-1] - times[0]
    mark('5_zero_target_fallback_after_rejection',
         fallback,
         'zero-target fallback present=%s residual_distance_m=%s '
         'residual_time_s=%s' % (fallback, residual, residual_time))
    # 6: business result in the declared set.
    outcomes = {str(episode.get('business_outcome'))
                for episode in evidence.episodes if isinstance(episode, dict)}
    if declared_outcomes is not None:
        outcome_ok = bool(outcomes) and outcomes.issubset(set(declared_outcomes))
        mark('6_business_outcome_declared',
             outcome_ok,
             'business outcomes=%s declared=%s'
             % (sorted(outcomes), declared_outcomes))
    detail = '; '.join('%s=%s' % (key, finished[key]['passed'])
                       for key in sorted(finished))
    verifier.note(name, 'criteria_id=%s %s' % (criteria_id, detail))
    if finished and all(entry['passed'] for entry in finished.values()):
        verifier.ok(name, 'ttl_over criteria (c) satisfied: ' + detail)


def _check_special_segment(evidence, ctx, verifier):
    if evidence.segment_id == 'latency_clock_mapping_recheck':
        check_special_clock_mapping(evidence, ctx, verifier)
        verifier.ok('special_ttl_over_criteria',
                    'n/a: %s is not a ttl-over recheck segment'
                    % evidence.segment_id)
    elif evidence.segment_id == 'latency_ttl_over_recheck':
        check_special_ttl_over(evidence, ctx, verifier)
        verifier.ok('special_clock_mapping_paths',
                    'n/a: %s is not a clock-mapping recheck segment'
                    % evidence.segment_id)
    else:
        verifier.ok('special_clock_mapping_paths',
                    'n/a: %s is not a clock-mapping recheck segment'
                    % evidence.segment_id)
        verifier.ok('special_ttl_over_criteria',
                    'n/a: %s is not a ttl-over recheck segment'
                    % evidence.segment_id)


def _mark_special_not_applicable(verifier, segment_id):
    verifier.ok('special_clock_mapping_paths',
                'n/a: %s is not a clock-mapping recheck segment' % segment_id)
    verifier.ok('special_ttl_over_criteria',
                'n/a: %s is not a ttl-over recheck segment' % segment_id)


# ---------------------------------------------------------------------------
# top-level orchestration
# ---------------------------------------------------------------------------

def _check_episode_structure(evidence, episode, ctx, verifier):
    rows = _sorted_rows(evidence.steps_by_episode.get(
        episode.get('episode_id'), []))
    run_rows = [row for row in rows if row.get('phase') != 'POST_ABORT']
    post_rows = [row for row in rows if row.get('phase') == 'POST_ABORT']
    analysis = {
        'episode_id': episode.get('episode_id'),
        'case_id': episode.get('case_id'),
        'segment_id': evidence.segment_id,
        'scenario_class': episode.get('scenario_class'),
        'business_outcome': episode.get('business_outcome'),
        'physical_outcome': episode.get('physical_outcome'),
        'rows': rows,
        'run_rows': run_rows,
        'post_rows': post_rows,
        'clearance': {
            'records': 0,
            'no_record_invalid_steps': 0,
            'max_abs_error_m': 0.0,
            'min_path_clearance_m': float('inf'),
            'min_path_clearance_gap_sphere_m': float('inf'),
            'min_center_distance_m': float('inf'),
            'min_envelope_gap_sphere_m': float('inf'),
            'robot_radius_m': None,
            'obstacle_radius_m': None,
            'aabb_half_extents_m': None,
            'applicability': Counter(),
        },
        'stop_requirement': {
            'records': 0,
            'unsupported_steps': 0,
            'unsupported_reasons': Counter(),
            'outside_support_steps': 0,
            'interpolated_steps': 0,
            'max_robot_speed_mps': 0.0,
            'min_margin_m': float('inf'),
            'max_required_clearance_m': float('-inf'),
        },
        'transport': {},
        'post_abort': {},
        'contact_evidence': {
            'max_sensor_force_n': 0.0,
            'max_sphere_overlap_m': 0.0,
            'inferred_contact': False,
            'measured_contact': False,
            'first_inferred_contact_time_s': None,
            'first_inferred_contact_phase': None,
        },
    }
    # Conservative sphere radii for the contact inference rule.
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    body = manifest.get('body_envelope') if isinstance(
        manifest.get('body_envelope'), dict) else {}
    body_half = _vec(body.get('half_extents_m'))
    episode_obstacle = episode.get('obstacle') \
        if isinstance(episode.get('obstacle'), dict) else {}
    obstacle_size = _vec(episode_obstacle.get('size_m'))
    radii_sum = None
    if body_half is not None:
        robot_radius = box_conservative_sphere_radius(body_half)
        if obstacle_size is not None:
            radii_sum = robot_radius + max(obstacle_size) / 2.0
        else:
            radii_sum = robot_radius
    sensor = manifest.get('contact_sensor')
    sensor = sensor if isinstance(sensor, dict) else {}
    ctx['contact_mode'] = sensor.get('mode')
    ctx['force_sensor_available'] = sensor.get('force_sensor_available')
    ctx['radii_sum_m'] = radii_sum
    for row in rows:
        _check_contact_evidence_row(evidence, episode, row, ctx, verifier,
                                    analysis['contact_evidence'])
    check_clearance_episode(evidence, episode, rows, ctx, verifier, analysis)
    envelope = {
        'robot_radius_m': analysis['clearance'].get('robot_radius_m'),
        'obstacle_radius_m': analysis['clearance'].get('obstacle_radius_m'),
    }
    ctx['envelope'] = envelope
    check_stop_requirement_episode(evidence, episode, rows, ctx, verifier,
                                   analysis)
    check_transport_episode(evidence, episode, rows, ctx, verifier, analysis)
    check_post_abort_episode(evidence, episode, rows, ctx, verifier, analysis)
    ctx['analysis_ref'] = analysis
    analysis['metrics'] = _rebuild_metrics(rows, episode, ctx)
    check_metrics_match(evidence, episode, ctx, verifier, analysis)
    check_business_physical(evidence, episode, ctx, verifier, analysis)
    check_expected_episode(evidence, episode, ctx, verifier, analysis)
    # performance bookkeeping: recorded-vs-recomputed stop-required presence.
    cls = str(episode.get('scenario_class') or '')
    if cls in STOP_REQUIRED_CLASSES \
            and analysis['metrics'].get('brake_start') is None:
        verifier.fail('brake_start_metrics', 'a STOP-required scenario class has '
                      'no recorded STOP/brake start', run=evidence.label,
                      episode_id=episode.get('episode_id'),
                      field='metrics.brake_start', expected='STOP',
                      actual='none')
    else:
        verifier.ok_if_clean('brake_start_metrics',
                             'brake start checked for %s'
                             % episode.get('episode_id'))
    verifier.ok_if_clean('stop_distance_time', 'stop distance/time checked for %s'
                         % episode.get('episode_id'))
    verifier.ok_if_clean('relative_closing_speed', 'closing/relative speed '
                         'checked for %s' % episode.get('episode_id'))
    verifier.ok_if_clean('contact_metrics', 'contact metrics checked for %s'
                         % episode.get('episode_id'))
    verifier.ok_if_clean('obstacle_approach_after_stop',
                         'post-stop obstacle approach checked for %s'
                         % episode.get('episode_id'))
    verifier.ok_if_clean('post_abort_residual', 'post-abort residual checked for '
                         '%s' % episode.get('episode_id'))
    return analysis


def _clear_internal(value, defaults=(float('inf'), float('-inf'))):
    if _num(value):
        number = float(value)
        if number == defaults[0] or number == defaults[1]:
            return None
        return number
    return None


def _segment_performance(analyses):
    episodes = []
    accepted = Counter()
    physical = Counter()
    for analysis in analyses:
        metrics = analysis['metrics']
        episode = {
            'episode_id': analysis['episode_id'],
            'case_id': analysis['case_id'],
            'scenario_class': analysis['scenario_class'],
            'business_outcome': analysis['business_outcome'],
            'physical_outcome': analysis['physical_outcome'],
            'recomputed_physical_outcome': metrics.get('physical_outcome'),
            'brake_start_time_s': (metrics.get('brake_start') or {}).get(
                'time_s'),
            'brake_start_step': (metrics.get('brake_start') or {}).get('step'),
            'initial_speed_mps': _clear_internal(
                metrics.get('initial_speed_mps')),
            'stop_distance_m': _clear_internal(metrics.get('stop_distance_m')),
            'stop_time_s': _clear_internal(metrics.get('stop_time_s')),
            'stop_complete_time_s': _clear_internal(
                metrics.get('stop_complete_time_s')),
            'max_closing_speed_mps': _clear_internal(
                metrics.get('max_closing_speed_mps')),
            'max_relative_speed_mps': _clear_internal(
                metrics.get('max_relative_speed_mps')),
            'min_path_clearance_m': _clear_internal(
                metrics.get('min_path_clearance_m')),
            'min_center_distance_m': _clear_internal(
                metrics.get('min_center_distance_m')),
            'first_contact_time_s': metrics.get('first_contact_time_s'),
            'first_contact_phase': metrics.get('first_contact_phase'),
            'first_inferred_contact_time_s': metrics.get(
                'first_inferred_contact_time_s'),
            'inferred_contact': metrics.get('inferred_contact'),
            'measured_contact': metrics.get('measured_contact'),
            'max_sphere_overlap_m': metrics.get('max_sphere_overlap_m'),
            'contact_max_force_n': metrics.get('contact_max_force_n'),
            'obstacle_approach_after_stop_m': _clear_internal(
                metrics.get('obstacle_approach_after_stop_m')),
            'post_abort': {
                'steps': metrics['post_abort']['steps'],
                'residual_distance_m': _clear_internal(
                    metrics['post_abort']['residual_distance_m']),
                'time_to_stop_s': _clear_internal(
                    metrics['post_abort']['time_to_stop_s']),
                'contact': metrics['post_abort']['contact'],
            },
            'stop_requirement': {
                'unsupported_steps': metrics['stop_requirement_stats'][
                    'unsupported_steps'],
                'unsupported_reasons': metrics['stop_requirement_stats'][
                    'unsupported_reasons'],
                'min_margin_m': _clear_internal(
                    metrics['stop_requirement_stats']['min_margin_m']),
                'max_robot_speed_mps': _clear_internal(
                    metrics['stop_requirement_stats']['max_robot_speed_mps']),
            },
        }
        episodes.append(episode)
        accepted[str(analysis['business_outcome'])] += 1
        physical[str(analysis['physical_outcome'])] += 1
    return {'episodes': episodes,
            'business_outcomes': dict(accepted),
            'physical_outcomes': dict(physical)}


def _segment_episode_metrics(evidence):
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    return manifest.get('boundary_plan') or manifest.get('run_plan') \
        or manifest.get('latency_plan') or {}


def run_verification(args, parser=None):
    verifier = Verifier()
    repo_root = Path(args.repo_root) if args.repo_root is not None else Path('.')
    freeze_path = args.freeze
    freeze = _load_freeze(freeze_path, verifier)
    if isinstance(freeze, dict):
        segments = _freeze_segments(freeze)
        check_freeze_document(freeze, Path(freeze_path), verifier, repo_root)
    else:
        segments = {}
    expected_path = args.expected
    expected_payload = None
    if expected_path is not None:
        if not Path(expected_path).is_file():
            verifier.missing.add('expected', 'expected config file %s'
                                 % expected_path, 'cli')
        else:
            try:
                expected_payload = _load_json(expected_path)
            except (OSError, ValueError) as error:
                verifier.fail('scenario_class_match',
                              'expected config parse failure: ' + repr(error),
                              run='expected')
    else:
        verifier.missing.add('expected', 'expected config argument', 'cli')
    expected_index = ExpectedIndex()
    expected_index.add_config(expected_payload)
    if isinstance(expected_payload, dict):
        schema = expected_payload.get('schema_version')
        if schema is not None and schema != BOUNDARY_EXPECTED_SCHEMA:
            verifier.fail('expected_config_coverage',
                          'expected config schema_version mismatch',
                          run='expected', field='schema_version',
                          expected=BOUNDARY_EXPECTED_SCHEMA, actual=schema)
        status = expected_payload.get('status')
        if status is not None and status != 'EXPECTED_NOT_CONCLUSION':
            verifier.fail('expected_config_coverage',
                          'expected config must be marked '
                          'EXPECTED_NOT_CONCLUSION (pre-run expectations are not '
                          'conclusions)', run='expected', field='status',
                          expected='EXPECTED_NOT_CONCLUSION', actual=status)
        if not expected_payload.get('cases'):
            verifier.missing.add('expected', 'cases', 'expected config')
    brake_model = _load_brake_model(args.brake_model, verifier)
    # Load provided runs.
    runs = {}
    provided = {}
    for spec in args.run or []:
        if '=' not in spec:
            if parser is not None:
                parser.error('expected SEGMENT_ID=DIR, got: ' + spec)
            raise SystemExit(2)
        segment_id, run_dir = spec.split('=', 1)
        segment_id = segment_id.strip()
        run_dir = run_dir.strip()
        if not segment_id or not run_dir:
            if parser is not None:
                parser.error('expected SEGMENT_ID=DIR, got: ' + spec)
            raise SystemExit(2)
        evidence = load_run(segment_id, run_dir, verifier)
        runs[segment_id] = evidence
        provided[segment_id] = run_dir
    if not runs:
        verifier.missing.add('verify', 'no run directories provided', 'cli')
    # Freeze file hash references.
    check_freeze_files(freeze, expected_path, args.brake_model, verifier,
                       repo_root)
    # Per-run document checks.
    analyses = {}
    for segment_id, evidence in runs.items():
        if not evidence.loaded:
            continue
        before = verifier.missing.count()
        verify_manifest_schema(evidence, verifier)
        verify_episode_schema(evidence, verifier)
        verify_step_schema(evidence, verifier)
        if verifier.missing.count() == before:
            verifier.ok('schema_completeness', 'raw schema complete for %s'
                        % segment_id)
        plan = _segment_episode_metrics(evidence)
        ctx = {
            'plan': plan,
            'ttl_ns': _ns_from_ms(plan.get('ttl_ms')) if plan else None,
            'action_delay_ns': _ns_from_ms(plan.get('action_delay_s'))
            if plan else None,
            'dt': None,
            'stop_threshold_m': _fnum(plan.get('stop_distance_m')) if plan
            else None,
            'body_envelope': evidence.manifest.get('body_envelope', {}),
            'supervisor': (expected_payload or {}).get('supervisor') or {},
            'proposed_margin_m': _fnum((expected_payload or {}).get(
                'proposed_margin_m')) or DEFAULT_PROPOSED_MARGIN_M,
            'brake_model': brake_model,
            'expected_index': expected_index,
            'envelope': None,
            'analysis_ref': None,
        }
        # dt is not recorded in the plan; infer from step spacing later.
        entry = segments.get(segment_id)
        if freeze is not None and isinstance(freeze, dict):
            if entry is None:
                verifier.fail('freeze_lineage', 'run segment is not declared in '
                              'the freeze document', run=segment_id,
                              field='segment_id',
                              expected=sorted(segments), actual=segment_id)
            else:
                check_run_lineage(evidence, freeze, entry, Path(freeze_path),
                                  verifier, expected_path, args.brake_model,
                                  repo_root)
        else:
            verifier.missing.add(segment_id, 'freeze document', segment_id)
        check_artifacts(evidence, verifier)
        check_gui(evidence, verifier)
        check_contact_sensor(evidence, verifier)
        check_episode_identity(evidence, verifier)
        check_manifest_disk(evidence, repo_root, verifier)
        check_step_time(evidence, verifier)
        check_expected_coverage(evidence, ctx, verifier)
        segment_analyses = []
        for episode in evidence.episodes:
            if not isinstance(episode, dict):
                continue
            analysis = _check_episode_structure(evidence, episode, ctx,
                                                verifier)
            segment_analyses.append(analysis)
        analyses[segment_id] = {
            'evidence': evidence,
            'segment_performance': _segment_performance(segment_analyses),
            'episodes': segment_analyses,
            'plan': plan,
        }
        if not segment_analyses:
            verifier.missing.add(segment_id, 'episode rows', segment_id)
        if plan.get('role') == 'special':
            _check_special_segment(evidence, ctx, verifier)
        else:
            _mark_special_not_applicable(verifier, segment_id)
    # Declared-but-not-provided segments.
    for segment_id in segments:
        if segment_id not in runs:
            verifier.missing.add('freeze', 'run directory for segment %s'
                                 % segment_id, segment_id)
    # Cross-run denominator based on the expected boundary cases.
    _check_boundary_denominator(analyses, expected_index, verifier)
    if not verifier.missing:
        verifier.ok_if_clean('unsupported_usage_stats',
                             'unsupported usage aggregated across runs')
        verifier.ok_if_clean('boundary_episode_coverage',
                             'boundary episode coverage checked')
    if not verifier.missing:
        verifier.ok_if_clean('manifest_disk_consistency',
                             'manifest / disk identity checked')
    # Compose result.
    computed_checks = verifier.finalize_checks()
    if verifier.missing:
        status = 'INCOMPLETE'
        computed_checks['schema_completeness']['passed'] = False
        computed_checks['schema_completeness']['detail'] = (
            'missing raw fields/incomplete data: %d entries; %s'
            % (verifier.missing.count(),
               computed_checks['schema_completeness']['detail']))
    elif verifier.failures or verifier.deviations:
        status = 'FAIL'
    else:
        status = 'PASS'
    recomputed, performance, unsupported = _compose_reports(
        analyses, expected_index, brake_model, expected_payload)
    freeze_info = _freeze_report(freeze_path, freeze, segments, expected_path,
                                 args.brake_model)
    contact_evidence = recomputed.get('contact_evidence') or {}
    result = {
        'status': status,
        'checks': computed_checks,
        'checks_by_category': {
            category: {name: entry for name, entry in computed_checks.items()
                       if entry['category'] == category}
            for category in CATEGORIES},
        'failures': _jsonable(verifier.failures),
        'deviations': _jsonable(verifier.deviations),
        'missing_fields': verifier.missing.as_list(),
        'contact_evidence_mode': contact_evidence.get('evidence_domain'),
        'contact_evidence_limitation': contact_evidence.get('limitation'),
        'recomputed': recomputed,
        'performance': performance,
        'unsupported': unsupported,
        'freeze': freeze_info,
        'run_dirs': {key: str(value) for key, value in provided.items()},
    }
    return result


def _check_boundary_denominator(analyses, expected_index, verifier):
    name = 'boundary_episode_coverage'
    observed = Counter()
    for entry in analyses.values():
        for episode in entry['evidence'].episodes:
            if isinstance(episode, dict) and episode.get('case_id'):
                observed[str(episode['case_id'])] += 1
    # Lead-aligned denominator: the frozen run_plan.case_ids define the expected
    # episode count (24 = 18 + 2 + 2 + 2), not an assumed repeat factor.
    by_segment_expected = {}
    by_segment_observed = {}
    freeze_case_ids = {}
    for segment_id, entry in analyses.items():
        if not _is_boundary_segment(segment_id):
            continue
        plan = entry['plan'] or {}
        case_ids = [str(item) for item in plan.get('case_ids') or [] if item]
        freeze_case_ids[segment_id] = case_ids
        by_segment_expected[segment_id] = len(case_ids)
        by_segment_observed[segment_id] = len(entry['evidence'].episodes)
    if not by_segment_expected:
        verifier.ok(name, 'no boundary segment supplied: denominator not '
                    'applicable (recheck/regression only)')
        return
    total_expected = sum(by_segment_expected.values())
    total_observed = sum(by_segment_observed.values())
    for segment_id, expected in by_segment_expected.items():
        observed_count = by_segment_observed.get(segment_id, 0)
        if observed_count < expected:
            verifier.missing.add(
                'coverage', '%s episodes (%d/%d)'
                % (segment_id, observed_count, expected), segment_id)
    # Every frozen boundary case must carry a pre-frozen expectation and be
    # observed the declared number of times (repeats=1 for independent cases).
    expected_boundary_ids = set()
    for case_id, spec in expected_index.cases.items():
        if str(case_id).startswith('boundary_'):
            expected_boundary_ids.add(str(case_id))
            repeats = spec.get('repeats')
            repeats = int(repeats) if _num(repeats) else DEFAULT_REPEATS
            if observed.get(str(case_id), 0) < repeats:
                verifier.missing.add(
                    'coverage', 'expected case %s episodes (%d/%d)'
                    % (case_id, observed.get(str(case_id), 0), repeats),
                    'expected config')
    for segment in expected_index.segments.values():
        for case_id, spec in segment['cases'].items():
            if str(case_id).startswith('boundary_'):
                expected_boundary_ids.add(str(case_id))
                merged = dict(segment['defaults'])
                merged.update(spec)
                repeats = merged.get('repeats')
                repeats = int(repeats) if _num(repeats) else DEFAULT_REPEATS
                if observed.get(str(case_id), 0) < repeats:
                    verifier.missing.add(
                        'coverage', 'expected case %s episodes (%d/%d)'
                        % (case_id, observed.get(str(case_id), 0), repeats),
                        'expected config')
    frozen_ids = set().union(*freeze_case_ids.values()) if freeze_case_ids \
        else set()
    for case_id in sorted(frozen_ids - expected_boundary_ids):
        verifier.missing.add('coverage', 'expected classification for frozen '
                             'boundary case %s' % case_id, 'expected config')
    for case_id in sorted(expected_boundary_ids - frozen_ids):
        verifier.fail(name, 'pre-frozen expected boundary case is not present in '
                      'any frozen run_plan.case_ids', run='coverage',
                      field='case_ids', expected=sorted(frozen_ids),
                      actual=case_id)
    verifier.ok(name, 'boundary denominator %d/%d episodes %s'
                % (total_observed, total_expected,
                   {segment_id: '%d/%d' % (by_segment_observed.get(segment_id, 0),
                                           expected)
                    for segment_id, expected in by_segment_expected.items()}))


def _compose_reports(analyses, expected_index, brake_model, expected_payload):
    recomputed_segments = {}
    performance_segments = {}
    unsupported_stop = Counter()
    unsupported_steps = 0
    unsupported_segments = defaultdict(int)
    clearance_max_error = 0.0
    clearance_records = 0
    clearance_min_path = None
    stop_records = 0
    outside_support = 0
    min_margin = None
    max_speed = None
    for segment_id, entry in analyses.items():
        evidence = entry['evidence']
        segment_perf = entry['segment_performance']
        performance_segments[segment_id] = segment_perf
        clear_stats = {
            'records': 0, 'valid_records': 0, 'max_abs_error_m': 0.0,
            'min_path_clearance_m': None, 'applicability': Counter(),
        }
        stop_stats = {
            'records': 0, 'unsupported_steps': 0,
            'unsupported_reasons': Counter(), 'outside_support_steps': 0,
            'max_robot_speed_mps': None, 'min_margin_m': None,
        }
        for analysis in entry['episodes']:
            analysis_clear = analysis['clearance']
            clear_stats['max_abs_error_m'] = max(
                clear_stats['max_abs_error_m'],
                analysis_clear.get('max_abs_error_m') or 0.0)
            for key, value in (analysis_clear.get('applicability')
                               or {}).items():
                clear_stats['applicability'][str(key)] += int(value)
            if analysis_clear.get('max_abs_error_m') is not None:
                clearance_max_error = max(
                    clearance_max_error,
                    analysis_clear['max_abs_error_m'])
            for row in analysis['rows']:
                record = row.get('clearance')
                if isinstance(record, dict):
                    clear_stats['records'] += 1
                    clearance_records += 1
                    if isinstance(record.get('validity'), dict) \
                            and record['validity'].get('valid') is True:
                        clear_stats['valid_records'] += 1
                stop = row.get('stop_requirement')
                if isinstance(stop, dict):
                    stop_stats['records'] += 1
                    stop_records += 1
                    if stop.get('status') == 'UNSUPPORTED':
                        stop_stats['unsupported_steps'] += 1
                        unsupported_steps += 1
                        unsupported_segments[segment_id] += 1
                        for reason in stop.get('status_reasons') or []:
                            stop_stats['unsupported_reasons'][str(reason)] += 1
                            unsupported_stop[str(reason)] += 1
                    inputs = stop.get('inputs') \
                        if isinstance(stop.get('inputs'), dict) else {}
                    speed = _fnum(inputs.get('robot_speed_mps'))
                    if speed is not None:
                        if stop_stats['max_robot_speed_mps'] is None \
                                or speed > stop_stats['max_robot_speed_mps']:
                            stop_stats['max_robot_speed_mps'] = speed
                        if max_speed is None or speed > max_speed:
                            max_speed = speed
                    margin = _fnum(stop.get('margin_to_threshold_m'))
                    if margin is not None:
                        if stop_stats['min_margin_m'] is None \
                                or margin < stop_stats['min_margin_m']:
                            stop_stats['min_margin_m'] = margin
                        if min_margin is None or margin < min_margin:
                            min_margin = margin
            # Independent performance values (recomputed, not production).
            for episode in segment_perf.get('episodes') or []:
                if episode.get('episode_id') == analysis.get('episode_id'):
                    value = _clear_internal(
                        episode.get('min_path_clearance_m'))
                    if value is not None and (
                            clear_stats['min_path_clearance_m'] is None
                            or value < clear_stats['min_path_clearance_m']):
                        clear_stats['min_path_clearance_m'] = value
                        if clearance_min_path is None \
                                or value < clearance_min_path:
                            clearance_min_path = value
                    break
        recomputed_segments[segment_id] = {
            'episode_count': len(entry['episodes']),
            'role': entry['plan'].get('role'),
            'case_ids': [str(item) for item in
                         (entry['plan'].get('case_ids') or []) if item],
            'contact_sensor': evidence.manifest.get('contact_sensor'),
            'clearance': {
                'records': clear_stats['records'],
                'valid_records': clear_stats['valid_records'],
                'min_path_clearance_m': clear_stats['min_path_clearance_m'],
                'applicability': dict(clear_stats['applicability']),
            },
            'stop_requirement': {
                'records': stop_stats['records'],
                'unsupported_steps': stop_stats['unsupported_steps'],
                'unsupported_reasons': dict(stop_stats['unsupported_reasons']),
                'max_robot_speed_mps': stop_stats['max_robot_speed_mps'],
                'min_margin_m': stop_stats['min_margin_m'],
            },
        }
    if brake_model is not None and brake_model.loaded:
        brake_info = {
            'model_id': brake_model.model_id,
            'supported_speed_range_mps': [brake_model.supported_min,
                                          brake_model.supported_max],
            'points': brake_model.points,
            'extrapolation': 'forbidden',
        }
    else:
        brake_info = {'loaded': False}
    recomputed = {
        'segments': recomputed_segments,
        'expected_index': expected_index.summary(),
        'brake_model': brake_info,
        'clearance': {
            'records': clearance_records,
            'max_abs_error_m': None if not clearance_records
            else clearance_max_error,
            'min_path_clearance_m': clearance_min_path,
        },
        'stop_requirement': {
            'records': stop_records,
            'unsupported_steps': unsupported_steps,
            'by_reason': dict(unsupported_stop),
            'max_robot_speed_mps': max_speed,
            'min_margin_m': min_margin,
        },
        'metric_definitions': {
            'path_clearance_m': 'min point-to-segment distance from predicted '
                                'obstacle centers to [robot_center_now -> '
                                'current waypoint center] (11 points, 1.0 s / '
                                '0.1 s)',
            'center_distance_m': 'robot center to observed obstacle center',
            'envelope_gap_sphere_m': 'center_distance - (robot_radius + '
                                     'obstacle_radius)',
            'path_clearance_gap_sphere_m': 'path_clearance - (robot_radius + '
                                           'obstacle_radius)',
            'robot_radius_m': 'sqrt(sum(aabb_half_extents_m^2)); half diagonal, '
                              'not max half extent',
            'obstacle_radius_m': 'max(size_m) / 2',
            'stop_distance_m': 'along the initial brake velocity direction to '
                               'speed <= 0.08 m/s sustained 0.5 s',
        },
    }
    boundary_observed = {
        segment_id: len(entry['segment_performance'].get('episodes') or [])
        for segment_id, entry in analyses.items()
        if _is_boundary_segment(segment_id)}
    boundary_expected = {
        segment_id: len([str(item) for item in
                         ((entry['plan'] or {}).get('case_ids') or []) if item])
        for segment_id, entry in analyses.items()
        if _is_boundary_segment(segment_id)}
    boundary_expected_total = sum(boundary_expected.values())
    performance = {
        'segments': performance_segments,
        'boundary_episode_total': sum(boundary_observed.values()),
        'boundary_episode_expected': boundary_expected_total or None,
        'boundary_episodes_by_segment': {
            segment_id: {'expected': boundary_expected.get(segment_id, 0),
                         'observed': count}
            for segment_id, count in boundary_observed.items()},
        'special_segments': {
            segment_id: entry['segment_performance']
            for segment_id, entry in analyses.items()
            if not _is_boundary_segment(segment_id)},
        'recheck_and_regression_note': 'recheck/regression segments are '
                                       'reported separately and are not part of '
                                       'the 24-episode boundary denominator',
    }
    recomputed['boundary_denominator'] = {
        'expected_total': boundary_expected_total or None,
        'observed_total': sum(boundary_observed.values()),
        'by_segment': {
            segment_id: {'expected': boundary_expected.get(segment_id, 0),
                         'observed': boundary_observed.get(segment_id, 0)}
            for segment_id in sorted(set(boundary_observed)
                                     | set(boundary_expected))},
        'note': 'Lead-aligned split 24 = boundary_default 18 + '
                'boundary_delay_e1 2 + boundary_delay_e2 2 + '
                'boundary_fast 2; the expected count is the frozen '
                'run_plan.case_ids length.',
    }
    contact_mode = None
    contact_rule = None
    force_available = None
    inferred_episodes = 0
    measured_episodes = 0
    max_overlap_global = 0.0
    first_inferred_global = None
    for segment_id, entry in analyses.items():
        sensor = entry['evidence'].manifest.get('contact_sensor') \
            if isinstance(entry['evidence'].manifest, dict) else None
        sensor = sensor if isinstance(sensor, dict) else {}
        mode = sensor.get('mode')
        if contact_mode is None and mode:
            contact_mode = mode
            contact_rule = sensor.get('inference_rule')
            force_available = sensor.get('force_sensor_available')
        segment_inferred = 0
        segment_measured = 0
        segment_overlap = 0.0
        segment_first = None
        for analysis in entry['episodes']:
            evidence_stats = analysis.get('contact_evidence') or {}
            if evidence_stats.get('inferred_contact'):
                segment_inferred += 1
            if evidence_stats.get('measured_contact'):
                segment_measured += 1
            segment_overlap = max(segment_overlap,
                                 evidence_stats.get('max_sphere_overlap_m')
                                 or 0.0)
            first = evidence_stats.get('first_inferred_contact_time_s')
            if first is not None and (segment_first is None
                                     or first < segment_first):
                segment_first = first
        inferred_episodes += segment_inferred
        measured_episodes += segment_measured
        max_overlap_global = max(max_overlap_global, segment_overlap)
        if segment_first is not None and (first_inferred_global is None
                                          or segment_first
                                          < first_inferred_global):
            first_inferred_global = segment_first
        if segment_id in recomputed_segments:
            recomputed_segments[segment_id]['contact_evidence'] = {
                'mode': mode,
                'inferred_episodes': segment_inferred,
                'measured_episodes': segment_measured,
                'max_sphere_overlap_m': segment_overlap,
                'first_inferred_contact_time_s': segment_first,
            }
    recomputed['contact_evidence'] = {
        'mode': contact_mode,
        'evidence_domain': 'kinematic_inference'
        if contact_mode == 'sphere_overlap_inference' else contact_mode,
        'force_sensor_available': force_available,
        'inference_rule': contact_rule,
        'limitation': ('The environment contact force sensor does not report '
                       'obstacle-robot force; physical contact is inferred from '
                       'conservative sphere overlap (> %.3f m) and a zero force '
                       'is never read as NO_CONTACT. This is a kinematic '
                       'geometry inference, not a measured contact force.'
                       % CONTACT_OVERLAP_M),
        'inferred_episodes': inferred_episodes,
        'measured_episodes': measured_episodes,
        'max_sphere_overlap_m': max_overlap_global,
        'first_inferred_contact_time_s': first_inferred_global,
    }
    unsupported = {
        'stop_requirement': {
            'step_count': unsupported_steps,
            'by_reason': dict(unsupported_stop),
            'by_segment': dict(unsupported_segments),
            'max_robot_speed_mps': max_speed,
            'min_margin_m': min_margin,
        },
        'clearance_applicability': {
            'by_segment': {
                segment_id: entry['clearance']['applicability']
                for segment_id, entry in recomputed_segments.items()},
        },
    }
    return _jsonable(recomputed), _jsonable(performance), _jsonable(unsupported)


def _freeze_report(freeze_path, freeze, segments, expected_path,
                   brake_model_path):
    info = {
        'path': str(freeze_path) if freeze_path is not None else None,
        'sha256': None,
        'schema_version': None,
        'status': None,
        'frozen_at': None,
        'code_commit': None,
    }
    if freeze_path is not None and Path(freeze_path).is_file():
        info['sha256'] = _sha256_file(freeze_path)
    if isinstance(freeze, dict):
        for key in ('schema_version', 'status', 'frozen_at', 'code_commit'):
            info[key] = freeze.get(key)
        info['expected_file'] = freeze.get('expected_file')
        info['expected_sha256'] = freeze.get('expected_sha256')
        info['brake_model_file'] = freeze.get('brake_model_file')
        info['brake_model_sha256'] = freeze.get('brake_model_sha256')
        info['cases_file'] = freeze.get('cases_file')
        info['cases_sha256'] = freeze.get('cases_sha256')
        info['segments'] = {
            segment_id: {
                'case_ids': [str(item) for item in
                             ((_segment_run_plan(entry) or {}).get('case_ids')
                              or []) if item],
                'role': (_segment_run_plan(entry) or {}).get('role'),
            }
            for segment_id, entry in segments.items()
        }
    if expected_path is not None and Path(expected_path).is_file():
        info['expected_path'] = str(expected_path)
        info['expected_file_sha256'] = _sha256_file(expected_path)
    if brake_model_path is not None and Path(brake_model_path).is_file():
        info['brake_model_path'] = str(brake_model_path)
        info['brake_model_file_sha256'] = _sha256_file(brake_model_path)
    return info


def build_parser():
    parser = argparse.ArgumentParser(
        description='Independent verification of clearance-boundary evaluation '
                    'runs (plan section 6).')
    parser.add_argument('--freeze', type=Path, default=None,
                        help='pre-run boundary freeze json')
    parser.add_argument('--run', action='append', default=[],
                        metavar='SEGMENT_ID=DIR',
                        help='segment run directory (repeatable)')
    parser.add_argument('--expected', type=Path, default=None,
                        help='pre-frozen expected classification config')
    parser.add_argument('--brake-model', type=Path, default=None,
                        help='frozen brake model json')
    parser.add_argument('--repo-root', type=Path, default=Path('.'),
                        help='repository root for relative paths (default: .)')
    parser.add_argument('--output', type=Path, default=None,
                        help='write the verification JSON here')
    return parser


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
