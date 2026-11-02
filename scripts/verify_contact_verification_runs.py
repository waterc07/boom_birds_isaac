#!/usr/bin/env python3
"""Independent verification of contact-evidence / envelope evaluation runs.

Work package: ``codex/bb22-contact-envelope``.  The verifier is independent of
the runner: it reads only the raw run directory (``manifest.json``,
``episodes.jsonl``, ``steps.jsonl``), the pre-run freeze, the pre-frozen expected
configuration and the raw ``contact_record`` layers.  ``summary.json`` is never
read for conclusions.

The two contracts under verification are imported (pure standard-library modules,
no simulator dependency) so every production value is recomputed with the same
frozen rules while the recorded labels are treated as comparison targets:

* ``boom_birds.evaluation.contact_contract`` -- ``boom_birds.contact_evidence.v2``
  (four PhysX/geometry layers + attribution layer, strict ``> 0.02 N`` force
  threshold, sensor-invalid => UNKNOWN with ``magnitude_n=None``, valid zero =>
  NO_CONTACT with ``magnitude_n == 0.0``, impulse in ``N*s`` never used as force,
  geometry overlap never promoted to a PhysX contact, no fabricated prim paths).
* ``boom_birds.sim.body_envelope`` -- ``boom_birds.body_envelope.v2``
  (``sphere_about_origin.radius_m = || |center_offset_m| + half_extents_m ||_2``
  about the robot reference origin; ``sphere_about_aabb_center`` is comparison
  only; coverage source/limitations are part of the claim).

Run-directory contract assumed (the runner records these fields):

``manifest.json``
    schema_version='boom_birds.contact_verification_manifest.v1', code_commit,
    working_tree, gui_mode=true, renderer, freeze{path,sha256}, segment_id,
    role in {wall, obstacle, clearance, geometry, replay}, cases_file,
    cases_sha256, episode_ids (ordered, unique), run_plan, contact_sensor
    {available, mode, prim_paths, filter_prim_paths, update_order,
    physics{physics_dt_s, decimation, substeps_per_step}}, body_envelope (v2
    record), prim_inventory{robot:[{path,collision,rigid_body,contact_report}],
    obstacle:[...], map:[...]}, episode_boundary{started_from_reset,
    no_silent_reset}, contact_contract_version, envelope_contract_version.
``steps.jsonl`` (RUN rows)
    step, time_s, physics_step, position_world_m, velocity_world_mps,
    speed_mps, contact_record (v2 record), geometry_overlap_sphere_m,
    obstacle_position_world_m (optional), phase.
``episodes.jsonl``
    episode_id, case_id, mode, outcome, business_outcome, physical_outcome in
    {PHYSX_CONTACT_FORCE_MEASURED, CONTACT_FORCE_MEASURED_UNATTRIBUTED,
    PHYSX_CONTACT_EVENT_ONLY, GEOMETRY_OVERLAP_ONLY, NO_CONTACT, UNKNOWN},
    contact_summary, envelope_sphere_about_origin_m,
    replay{source_run, source_episode_id, previous_physical_label} (replay
    segments).

Freeze (``boom_birds.contact_verification_freeze.v1``) records schema_version,
status='PRE_RUN_FROZEN', frozen_at, code_commit, segments{segment_id:
{role, case_ids, repeats, run_plan, expected}}, and optionally the
cases/expected file hashes.  Expected (``boom_birds.contact_verification_expected.v1``)
records schema_version, status='EXPECTED_NOT_CONCLUSION' and per-case
``acceptable_physical_outcomes``/``must_conditions``/``attribution_prim_paths``
(and replay ``replay_verdict``).  Both files are written by the Lead; every
check reports missing fields as INCOMPLETE instead of guessing.

Usage:

    python scripts/verify_contact_verification_runs.py \
        --freeze configs/scenarios/contact_verification_freeze_v1.json \
        --run wall=outputs/map_eval/contact_wall \
        --expected configs/scenarios/contact_verification_expected_v1.json \
        --repo-root . \
        --output docs/reports/map_eval/contact_envelope/verify_contact_verification.json

Exit code: 0 = PASS, 1 = FAIL, 2 = INCOMPLETE.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from boom_birds.evaluation import contact_contract  # noqa: E402
from boom_birds.sim import body_envelope  # noqa: E402

CONTACT_MANIFEST_SCHEMA = 'boom_birds.contact_verification_manifest.v1'
CONTACT_FREEZE_SCHEMA = 'boom_birds.contact_verification_freeze.v1'
CONTACT_EXPECTED_SCHEMA = 'boom_birds.contact_verification_expected.v1'

# Canonical physical-outcome names are the contact_contract classification
# names.  The runner/expected files may use a ``PHYSX_`` prefix for the measured
# force / event-only names; both spellings are accepted and canonicalised for
# comparison (the recorded file itself is never rewritten).
CONTACT_FORCE_MEASURED = 'CONTACT_FORCE_MEASURED'
FORCE_MEASURED_UNATTRIBUTED = 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
EVENT_ONLY = 'CONTACT_EVENT_ONLY'
GEOMETRY_OVERLAP_ONLY = 'GEOMETRY_OVERLAP_ONLY'
NO_CONTACT = 'NO_CONTACT'
UNKNOWN = 'UNKNOWN'
PHYSICAL_OUTCOME_ALIASES = {
    'PHYSX_CONTACT_FORCE_MEASURED': CONTACT_FORCE_MEASURED,
    'CONTACT_FORCE_MEASURED': CONTACT_FORCE_MEASURED,
    'CONTACT_FORCE_MEASURED_UNATTRIBUTED': FORCE_MEASURED_UNATTRIBUTED,
    'PHYSX_CONTACT_EVENT_ONLY': EVENT_ONLY,
    'CONTACT_EVENT_ONLY': EVENT_ONLY,
    'GEOMETRY_OVERLAP_ONLY': GEOMETRY_OVERLAP_ONLY,
    'NO_CONTACT': NO_CONTACT,
    'UNKNOWN': UNKNOWN,
    # legacy clearance-package labels used as replay.previous_physical_label
    'CONTACT_INFERRED': CONTACT_FORCE_MEASURED,
    'CONTACT_MEASURED': CONTACT_FORCE_MEASURED,
}

PHYSICAL_OUTCOMES = (CONTACT_FORCE_MEASURED, FORCE_MEASURED_UNATTRIBUTED,
                     EVENT_ONLY, GEOMETRY_OVERLAP_ONLY, NO_CONTACT, UNKNOWN)
# Backwards-compatible spellings used by earlier fixtures/tools.
PHYSX_FORCE_MEASURED = CONTACT_FORCE_MEASURED
PHYSX_EVENT_ONLY = EVENT_ONLY
CONTACT_OUTCOMES = frozenset({CONTACT_FORCE_MEASURED,
                              FORCE_MEASURED_UNATTRIBUTED, EVENT_ONLY})
ROLES = ('wall', 'obstacle', 'clearance', 'geometry', 'replay')
REPLAY_VERDICTS = ('CONSISTENT', 'MISREPORT', 'MISS', 'UNDECIDABLE')

MUST_CONDITION_KINDS = frozenset({
    # Lead-aligned kinds used by the actual pre-frozen expected file
    'sensor_available_true', 'event_true', 'event_false',
    'force_measured_gt_0.02_n', 'force_available_with_valid_zero',
    'force_available', 'geometry_overlap_gt_0.02_m',
    'geometry_overlap_le_0.02_m', 'not_geometry_only', 'not_physx_force',
    'attribution_prim_in', 'event_true_or_force_available',
    'replay_verdict_recorded', 'replay_basis_from_raw_contact_record',
    # older spellings kept for compatibility with earlier frozen files
    'force_measured', 'event_or_force', 'attribution_attributed',
    'attribution_within_inventory', 'no_contact', 'sensor_available',
    'force_valid_zero', 'overlap_gt_0.02', 'physical_outcome_in',
})


def canonical_physical(value):
    """Canonical contact_contract physical-outcome name (alias tolerant)."""
    if value is None:
        return None
    return PHYSICAL_OUTCOME_ALIASES.get(str(value), str(value))

CONTACT_TOL = 1e-9
RADIUS_TOL = 1e-9
TIME_TOL_S = 1e-6
FORCE_TOL_N = 1e-9
IMPULSE_TOL_NS = 1e-9
PLAN_TOL = 1e-6

MAX_FAILURES = 800
MAX_CHECK_NOTES = 8
MAX_LIST_DETAIL = 40

CHECKS = (
    # data integrity
    ('schema_completeness', 'data_integrity'),
    ('freeze_lineage', 'data_integrity'),
    ('gui_evidence', 'data_integrity'),
    ('episode_identity_and_denominator', 'data_integrity'),
    ('step_physics_timing', 'data_integrity'),
    ('episode_boundary', 'data_integrity'),
    ('artifact_hashes', 'data_integrity'),
    # contact contract
    ('contact_record_schema', 'contact_contract'),
    ('contact_classification', 'contact_contract'),
    ('contact_units_and_threshold', 'contact_contract'),
    ('sensor_invalid_vs_valid_zero', 'contact_contract'),
    ('attribution_contract', 'contact_contract'),
    ('geometry_never_promoted', 'contact_contract'),
    ('impulse_never_force', 'contact_contract'),
    ('net_vs_per_prim', 'contact_contract'),
    ('contact_summary_recompute', 'contact_contract'),
    # envelope geometry
    ('envelope_radius_recompute', 'envelope_geometry'),
    ('envelope_coverage_inventory', 'envelope_geometry'),
    ('envelope_limitations', 'envelope_geometry'),
    ('envelope_legacy_delta', 'envelope_geometry'),
    # scenario expectation
    ('expected_config_coverage', 'scenario_expectation'),
    ('acceptable_physical_outcomes', 'scenario_expectation'),
    ('must_conditions', 'scenario_expectation'),
    ('segment_role_expectations', 'scenario_expectation'),
    ('replay_verdicts', 'scenario_expectation'),
    # performance / capability boundary
    ('contact_event_stats', 'performance_boundary'),
    ('force_impulse_extremes', 'performance_boundary'),
    ('attribution_coverage', 'performance_boundary'),
    ('geometry_only_and_unknown_stats', 'performance_boundary'),
)

CHECK_NAMES = tuple(name for name, _ in CHECKS)
CATEGORY_OF = {name: category for name, category in CHECKS}
CATEGORIES = ('data_integrity', 'contact_contract', 'envelope_geometry',
              'scenario_expectation', 'performance_boundary')


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def _num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _fnum(value):
    return float(value) if _num(value) else None


def _close(actual, expected, tol):
    return (_num(actual) and _num(expected)
            and abs(float(actual) - float(expected)) <= tol)


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
    return left is not None and right is not None \
        and all(abs(left[index] - right[index]) <= tol for index in range(length))


def _norm(vector):
    return math.sqrt(sum(value * value for value in vector))


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


def _sequence_equal(actual, expected):
    left = list(actual) if isinstance(actual, (list, tuple)) else None
    right = list(expected) if isinstance(expected, (list, tuple)) else None
    return left is not None and right is not None \
        and [str(item) for item in left] == [str(item) for item in right]


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

class MissingFields:
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
    def __init__(self):
        self.checks = {
            category: {name: {'passed': None, 'category': category,
                              'notes': [], 'failures': 0}
                       for name, check_category in CHECKS
                       if check_category == category}
            for category in CATEGORIES}
        self._category_of = CATEGORY_OF
        self.failures = []
        self.deviations = []
        self._deviation_index = {}
        self.missing = MissingFields()

    def _entry(self, name):
        return self.checks[self._category_of[name]][name]

    def ok(self, name, detail=''):
        entry = self._entry(name)
        if entry['passed'] is None:
            entry['passed'] = True
        if detail and len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append(str(detail))

    def note(self, name, detail):
        entry = self._entry(name)
        if len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append(str(detail))

    def fail(self, name, detail, *, run=None, episode_id=None, step=None,
             field=None, expected=None, actual=None):
        entry = self._entry(name)
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
        key = (str(check), str(kind), str(run), str(episode_id), str(case_id))
        existing = self._deviation_index.get(key)
        if existing is not None:
            existing['count'] += 1
            return
        deviation = {'kind': str(kind), 'check': check,
                     'category': self._category_of[check], 'detail': str(detail),
                     'count': 1}
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
        self._deviation_index[key] = deviation
        self.deviations.append(deviation)
        entry = self._entry(check)
        entry['passed'] = False
        entry['failures'] += 1
        if len(entry['notes']) < MAX_CHECK_NOTES:
            entry['notes'].append('deviation: ' + str(detail))

    def ok_if_clean(self, name, detail=''):
        if self._entry(name)['passed'] is None:
            self.ok(name, detail)

    def finalize(self):
        result = {}
        for category in CATEGORIES:
            result[category] = {}
            for name, entry in self.checks[category].items():
                if entry['passed'] is None:
                    self.missing.add('checks', name, 'check not evaluated')
                detail = '; '.join(entry['notes']) if entry['notes'] \
                    else 'not evaluated'
                if entry['failures'] > len(entry['notes']):
                    detail += ' (failures=%d)' % entry['failures']
                result[category][name] = {
                    'passed': entry['passed'], 'category': category,
                    'detail': detail}
        return result


# ---------------------------------------------------------------------------
# loaders
# ---------------------------------------------------------------------------

@dataclass
class RunEvidence:
    segment_id: str
    run_dir: Path
    manifest: dict = field(default_factory=dict)
    episodes: list = field(default_factory=list)
    steps_by_episode: dict = field(default_factory=dict)
    loaded: bool = False


def load_run(segment_id, run_dir, verifier):
    evidence = RunEvidence(segment_id=str(segment_id), run_dir=Path(run_dir))
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
    if not (evidence.run_dir / 'screenshots').is_dir():
        verifier.missing.add(segment_id, 'screenshots/', segment_id)
    try:
        if paths['manifest.json'].is_file():
            evidence.manifest = _load_json(paths['manifest.json'])
        if paths['episodes.jsonl'].is_file():
            evidence.episodes = _load_jsonl(paths['episodes.jsonl'])
        if paths['steps.jsonl'].is_file():
            rows = _load_jsonl(paths['steps.jsonl'])
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
    plan = entry.get('run_plan')
    if isinstance(plan, dict):
        return plan
    if any(key in entry for key in ('case_ids', 'role', 'repeats')):
        return entry
    return None


def _load_freeze(path, verifier):
    if path is None:
        verifier.missing.add('freeze', 'freeze file argument', 'cli')
        return None
    if not Path(path).is_file():
        verifier.missing.add('freeze', 'freeze file %s' % path, 'cli')
        return None
    try:
        return _load_json(path)
    except (OSError, ValueError) as error:
        verifier.fail('freeze_lineage', 'freeze parse failure: ' + repr(error),
                      run='freeze')
        return None


class ExpectedIndex:
    """Case/segment expectation lookup for the contact-verification expected file.

    Accepts the actual pre-frozen structure: top-level ``cases`` keyed by case
    id (fields ``acceptable_physical``/``acceptable_physical_outcomes``,
    ``must_conditions``, ``unsupported_allowed``), ``segments`` entries with a
    ``cases`` list of case ids, and top-level ``replay_verdicts``
    ``{case: {previous_physical_label, allowed, rule}}``.
    """

    def __init__(self):
        self.cases = {}
        self.segments = {}
        self.replay_verdicts = {}
        self.payload = None

    @staticmethod
    def _normalize_cases(node):
        result = {}
        if isinstance(node, list):
            for item in node:
                if isinstance(item, str):
                    result[str(item)] = {}
                elif isinstance(item, dict):
                    case_id = item.get('case_id') or item.get('id')
                    if case_id is not None:
                        result[str(case_id)] = dict(item)
        elif isinstance(node, dict):
            for case_id, item in node.items():
                if isinstance(item, dict):
                    merged = dict(item)
                    merged.setdefault('case_id', str(case_id))
                    result[str(case_id)] = merged
        return result

    def _segment_entry(self, node, segment_id):
        defaults = {}
        # A per-segment expectation may be stored as a top-level case whose id
        # equals the segment id (the actual expected file does this).
        base = self.cases.get(str(segment_id))
        if isinstance(base, dict):
            defaults.update(base)
        node_defaults = node.get('defaults')
        if isinstance(node_defaults, dict):
            defaults.update(node_defaults)
        for key, value in node.items():
            if key in ('cases', 'defaults', 'segment_id'):
                continue
            defaults.setdefault(key, value)
        cases = {}
        raw_cases = node.get('cases')
        for case_id, specific in self._normalize_cases(raw_cases).items():
            base_case = dict(self.cases.get(case_id) or {})
            base_case.update(specific)
            cases[case_id] = base_case
        return {'defaults': defaults, 'cases': cases}

    def add_payload(self, payload):
        if not isinstance(payload, dict):
            return
        self.payload = payload
        self.cases.update(self._normalize_cases(payload.get('cases')))
        verdicts = payload.get('replay_verdicts')
        if isinstance(verdicts, dict):
            for case_id, entry in verdicts.items():
                if isinstance(entry, dict):
                    self.replay_verdicts[str(case_id)] = dict(entry)
        segments = payload.get('segments')
        if isinstance(segments, dict):
            for segment_id, node in segments.items():
                if isinstance(node, dict):
                    self.segments[str(segment_id)] = self._segment_entry(
                        node, segment_id)
        elif isinstance(segments, list):
            for node in segments:
                if isinstance(node, dict) and node.get('segment_id') is not None:
                    segment_id = str(node['segment_id'])
                    self.segments[segment_id] = self._segment_entry(
                        node, segment_id)

    def add_freeze_segment_expected(self, segment_id, expected):
        if isinstance(expected, list):
            expected = {'cases': expected}
        if not isinstance(expected, dict):
            return
        merged = self.segments.setdefault(segment_id,
                                          {'defaults': {}, 'cases': {}})
        if isinstance(expected.get('defaults'), dict):
            merged['defaults'].update(expected['defaults'])
        merged['cases'].update(self._normalize_cases(expected.get('cases')))
        for key, value in expected.items():
            if key not in ('cases', 'defaults'):
                merged['defaults'].setdefault(key, value)

    def lookup(self, segment_id, case_id):
        spec = {}
        segment = self.segments.get(str(segment_id))
        if segment is not None:
            spec = dict(segment['defaults'])
            case_specific = self.cases.get(str(case_id))
            if isinstance(case_specific, dict):
                spec.update(case_specific)
            specific = segment['cases'].get(str(case_id))
            if isinstance(specific, dict):
                spec.update(specific)
        else:
            spec = dict(self.cases.get(str(case_id)) or {})
        verdict = self.replay_verdicts.get(str(case_id))
        if isinstance(verdict, dict):
            allowed = verdict.get('allowed')
            if isinstance(allowed, list):
                spec.setdefault('replay_allowed', [str(item)
                                                   for item in allowed])
            previous = verdict.get('previous_physical_label')
            if previous is not None:
                spec.setdefault('replay_previous_label', previous)
            rule = verdict.get('rule')
            if rule:
                spec.setdefault('replay_rule', rule)
        return spec or None

    def summary(self):
        return {'case_count': len(self.cases),
                'replay_verdict_count': len(self.replay_verdicts),
                'segments': {key: {'case_count': len(value['cases']),
                                   'default_keys': sorted(value['defaults'])}
                             for key, value in self.segments.items()}}


def _load_expected(path, verifier):
    if path is None:
        verifier.missing.add('expected', 'expected file argument', 'cli')
        return None
    if not Path(path).is_file():
        verifier.missing.add('expected', 'expected file %s' % path, 'cli')
        return None
    try:
        return _load_json(path)
    except (OSError, ValueError) as error:
        verifier.fail('expected_config_coverage',
                      'expected parse failure: ' + repr(error), run='expected')
        return None


# ---------------------------------------------------------------------------
# manifest / episode / step schema
# ---------------------------------------------------------------------------

def _require_keys(verifier, label, node, keys, prefix, example=None):
    if not isinstance(node, dict):
        verifier.missing.add(label, prefix, example)
        return
    for key in keys:
        if key not in node:
            verifier.missing.add(label, prefix + '.' + key, example)


def _require_values(verifier, label, node, keys, prefix, example=None):
    if not isinstance(node, dict):
        verifier.missing.add(label, prefix, example)
        return
    for key in keys:
        if node.get(key) is None:
            verifier.missing.add(label, prefix + '.' + key, example)


def verify_manifest_schema(evidence, verifier):
    label = evidence.segment_id
    manifest = evidence.manifest
    if not isinstance(manifest, dict):
        verifier.missing.add(label, 'manifest.json document', label)
        return
    required = ('schema_version', 'code_commit', 'working_tree', 'gui_mode',
                'renderer', 'freeze', 'segment_id', 'role', 'cases_file',
                'cases_sha256', 'episode_ids', 'run_plan',
                'contact_contract_version', 'envelope_contract_version',
                'contact_sensor', 'body_envelope', 'prim_inventory',
                'episode_boundary')
    _require_keys(verifier, label, manifest, required, 'manifest', label)
    if manifest.get('schema_version') not in (None, CONTACT_MANIFEST_SCHEMA):
        verifier.fail('schema_completeness',
                      'manifest.schema_version is not the contact-verification '
                      'manifest schema', run=label, field='schema_version',
                      expected=CONTACT_MANIFEST_SCHEMA,
                      actual=manifest.get('schema_version'))
    if manifest.get('segment_id') not in (None, evidence.segment_id):
        verifier.fail('schema_completeness',
                      'manifest.segment_id does not match the run segment',
                      run=label, field='segment_id',
                      expected=evidence.segment_id,
                      actual=manifest.get('segment_id'))
    role = manifest.get('role')
    if role is not None and role not in ROLES:
        verifier.fail('schema_completeness', 'manifest.role is not a known '
                      'contact-verification role', run=label, field='role',
                      expected=list(ROLES), actual=role)
    if manifest.get('contact_contract_version') is not None \
            and manifest['contact_contract_version'] \
            != contact_contract.CONTACT_EVIDENCE_SCHEMA_ID:
        verifier.fail('schema_completeness', 'manifest.contact_contract_version '
                      'mismatch', run=label, field='contact_contract_version',
                      expected=contact_contract.CONTACT_EVIDENCE_SCHEMA_ID,
                      actual=manifest['contact_contract_version'])
    if manifest.get('envelope_contract_version') is not None \
            and manifest['envelope_contract_version'] \
            != body_envelope.BODY_ENVELOPE_SCHEMA_VERSION:
        verifier.fail('schema_completeness', 'manifest.envelope_contract_version '
                      'mismatch', run=label, field='envelope_contract_version',
                      expected=body_envelope.BODY_ENVELOPE_SCHEMA_VERSION,
                      actual=manifest['envelope_contract_version'])
    run_plan = manifest.get('run_plan')
    if not isinstance(run_plan, dict):
        verifier.missing.add(label, 'manifest.run_plan', label)
    else:
        for key in ('role', 'case_ids'):
            if not run_plan.get(key):
                verifier.missing.add(label, 'manifest.run_plan.' + key, label)
    sensor = manifest.get('contact_sensor')
    if not isinstance(sensor, dict):
        verifier.missing.add(label, 'manifest.contact_sensor', label)
    else:
        for key in ('available', 'mode', 'prim_paths', 'filter_prim_paths',
                    'update_order', 'physics'):
            if key not in sensor:
                verifier.missing.add(label, 'manifest.contact_sensor.' + key,
                                     label)
        if not isinstance(sensor.get('available'), bool):
            verifier.missing.add(label, 'manifest.contact_sensor.available',
                                 label)
        physics = sensor.get('physics')
        if not isinstance(physics, dict):
            verifier.missing.add(label, 'manifest.contact_sensor.physics', label)
        else:
            for key in ('physics_dt_s', 'decimation', 'substeps_per_step'):
                if physics.get(key) is None:
                    verifier.missing.add(
                        label, 'manifest.contact_sensor.physics.' + key, label)
            if _num(physics.get('physics_dt_s')) \
                    and float(physics['physics_dt_s']) <= 0:
                verifier.fail('schema_completeness',
                              'contact_sensor.physics.physics_dt_s must be > 0',
                              run=label, field='contact_sensor.physics.'
                                               'physics_dt_s',
                              expected='> 0', actual=physics['physics_dt_s'])
    inventory = manifest.get('prim_inventory')
    if not isinstance(inventory, dict):
        verifier.missing.add(label, 'manifest.prim_inventory', label)
    else:
        for category in ('robot', 'obstacle', 'map'):
            entries = inventory.get(category)
            if not isinstance(entries, list):
                verifier.missing.add(label, 'manifest.prim_inventory.' + category,
                                     label)
                continue
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    verifier.missing.add(
                        label, 'manifest.prim_inventory.%s[%d]'
                               % (category, index), label)
                    continue
                for key in ('path', 'collision', 'rigid_body', 'contact_report'):
                    if key not in entry:
                        verifier.missing.add(
                            label, 'manifest.prim_inventory.%s[%d].%s'
                                   % (category, index, key), label)
                if not isinstance(entry.get('path'), str) or not entry['path']:
                    verifier.missing.add(
                        label, 'manifest.prim_inventory.%s[%d].path'
                               % (category, index), label)
                for key in ('collision', 'rigid_body', 'contact_report'):
                    if key in entry and not isinstance(entry[key], bool):
                        verifier.fail('schema_completeness',
                                      'prim_inventory flags must be booleans',
                                      run=label,
                                      field='prim_inventory.%s[%d].%s'
                                            % (category, index, key),
                                      expected='bool', actual=entry[key])
    boundary = manifest.get('episode_boundary')
    if not isinstance(boundary, dict):
        verifier.missing.add(label, 'manifest.episode_boundary', label)
    else:
        for key in ('started_from_reset', 'no_silent_reset'):
            if key not in boundary:
                verifier.missing.add(label, 'manifest.episode_boundary.' + key,
                                     label)
    _require_values(verifier, label, manifest.get('freeze'),
                    ('path', 'sha256'), 'manifest.freeze', label)
    if not manifest.get('episode_ids'):
        verifier.missing.add(label, 'manifest.episode_ids', label)
    verifier.ok_if_clean('schema_completeness',
                         'manifest schema checked for ' + label)


def verify_episode_schema(evidence, verifier):
    label = evidence.segment_id
    role = evidence.manifest.get('role') \
        if isinstance(evidence.manifest, dict) else None
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            verifier.fail('schema_completeness', 'episode row is not an object',
                          run=label)
            continue
        example = 'episode %s' % episode.get('episode_id')
        _require_keys(verifier, label, episode,
                      ('episode_id', 'case_id', 'mode', 'outcome',
                       'business_outcome', 'physical_outcome',
                       'contact_summary', 'envelope_sphere_about_origin_m'),
                      'episodes[]', example)
        physical = episode.get('physical_outcome')
        if physical is not None and canonical_physical(physical) \
                not in PHYSICAL_OUTCOMES:
            verifier.fail('schema_completeness',
                          'invalid episodes[].physical_outcome', run=label,
                          episode_id=episode.get('episode_id'),
                          field='physical_outcome',
                          expected=list(PHYSICAL_OUTCOMES), actual=physical)
        if physical is not None and canonical_physical(physical) \
                in PHYSICAL_OUTCOMES:
            verifier.ok_if_clean('schema_completeness',
                                 'episode physical_outcome enum checked for %s'
                                 % episode.get('episode_id'))
        if not isinstance(episode.get('contact_summary'), dict):
            verifier.missing.add(label, 'episodes[].contact_summary', example)
        _require_keys(verifier, label, episode.get('contact_summary'),
                      ('total_steps', 'classification_counts',
                       'max_force_n', 'unknown_steps', 'unknown_reasons',
                       'geometry_only_steps', 'attributed_steps',
                       'unattributed_steps'),
                      'episodes[].contact_summary', example)
        radius = episode.get('envelope_sphere_about_origin_m')
        if not _num(radius):
            verifier.missing.add(
                label, 'episodes[].envelope_sphere_about_origin_m', example)
        if role == 'replay':
            replay = episode.get('replay')
            if not isinstance(replay, dict):
                verifier.missing.add(label, 'episodes[].replay', example)
            else:
                for key in ('source_run', 'source_episode_id',
                            'previous_physical_label'):
                    if key not in replay:
                        verifier.missing.add(
                            label, 'episodes[].replay.' + key, example)
                previous = replay.get('previous_physical_label')
                if previous is not None \
                        and canonical_physical(previous) not in PHYSICAL_OUTCOMES:
                    verifier.missing.add(
                        label, 'episodes[].replay.previous_physical_label',
                        example)


def verify_step_schema(evidence, verifier):
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    role = manifest.get('role')
    for episode_id, rows in evidence.steps_by_episode.items():
        for row in rows:
            if not isinstance(row, dict):
                verifier.fail('schema_completeness', 'step row is not an object',
                              run=label)
                continue
            example = _example(row)
            _require_keys(verifier, label, row,
                          ('episode_id', 'step', 'time_s', 'physics_step',
                           'position_world_m', 'velocity_world_mps',
                           'speed_mps', 'contact_record', 'phase'),
                          'steps[]', example)
            if not isinstance(row.get('physics_step'), int) \
                    or isinstance(row.get('physics_step'), bool):
                verifier.missing.add(label, 'steps[].physics_step', example)
            # The wall mode does not compute a sphere overlap at all; the row
            # value is legitimately null/missing there.  Other roles must record
            # the geometry overlap number (possibly negative).
            if role != 'wall':
                if not _num(row.get('geometry_overlap_sphere_m')):
                    verifier.missing.add(
                        label, 'steps[].geometry_overlap_sphere_m', example)
            elif row.get('geometry_overlap_sphere_m') is not None \
                    and not _num(row.get('geometry_overlap_sphere_m')):
                verifier.missing.add(
                    label, 'steps[].geometry_overlap_sphere_m', example)
            if not isinstance(row.get('contact_record'), dict):
                verifier.missing.add(label, 'steps[].contact_record', example)
            phase = row.get('phase')
            if phase is not None and phase not in ('RUN', 'POST_ABORT'):
                verifier.fail('schema_completeness', 'invalid steps[].phase',
                              run=label, episode_id=episode_id,
                              step=row.get('step'), field='phase',
                              expected=['RUN', 'POST_ABORT'], actual=phase)


# ---------------------------------------------------------------------------
# data integrity checks
# ---------------------------------------------------------------------------

def check_freeze(evidence, freeze, freeze_path, expected_path, verifier,
                 repo_root=None):
    name = 'freeze_lineage'
    label = evidence.segment_id
    if not isinstance(freeze, dict):
        verifier.missing.add('freeze', 'freeze document', label)
        return
    schema = freeze.get('schema_version')
    if schema != CONTACT_FREEZE_SCHEMA:
        verifier.fail(name, 'freeze schema_version is not the contact '
                      'verification pre-run schema', run='freeze',
                      field='schema_version', expected=CONTACT_FREEZE_SCHEMA,
                      actual=schema)
    if freeze.get('status') != 'PRE_RUN_FROZEN':
        verifier.fail(name, 'freeze status is not PRE_RUN_FROZEN',
                      run='freeze', field='status',
                      expected='PRE_RUN_FROZEN', actual=freeze.get('status'))
    frozen_at = _parse_iso(freeze.get('frozen_at'))
    if frozen_at is None:
        verifier.missing.add('freeze', 'frozen_at', 'freeze')
    if not freeze.get('code_commit'):
        verifier.missing.add('freeze', 'code_commit', 'freeze')
    segments = _freeze_segments(freeze)
    if not segments:
        verifier.missing.add('freeze', 'segments', 'freeze')
    for segment_id, entry in segments.items():
        role = entry.get('role') or (_segment_run_plan(entry) or {}).get('role')
        if role not in ROLES:
            verifier.fail(name, 'freeze segment role is not a known role',
                          run='freeze', field='segments.%s.role' % segment_id,
                          expected=list(ROLES), actual=role)
        plan = _segment_run_plan(entry)
        if not (entry.get('case_ids') or (plan or {}).get('case_ids')):
            verifier.missing.add('freeze',
                                 'segments.%s.case_ids' % segment_id, 'freeze')
    if isinstance(freeze_path, Path) and freeze_path.is_file() \
            and freeze.get('artifact_sha256'):
        actual = _sha256_file(freeze_path)
        if freeze['artifact_sha256'] != actual:
            verifier.fail(name, 'freeze.artifact_sha256 does not match the freeze '
                          'file', run='freeze', field='artifact_sha256',
                          expected=actual, actual=freeze['artifact_sha256'])
    # Referenced input files/hashes.
    pairs = (('cases_file', 'cases_sha256'),
             ('expected_file', 'expected_sha256'))
    for file_key, sha_key in pairs:
        file_name = freeze.get(file_key)
        recorded = freeze.get(sha_key)
        if not file_name or not recorded:
            continue
        path = Path(str(file_name))
        if not path.is_absolute():
            path = Path('.') / path
        if not path.is_file():
            verifier.missing.add('freeze', '%s exists (%s)' % (file_key, path),
                                 'freeze')
            continue
        actual = _sha256_file(path)
        if str(recorded).lower() != actual:
            verifier.fail(name, 'freeze.%s does not match the file on disk'
                          % sha_key, run='freeze', field=sha_key,
                          expected=actual, actual=recorded)
    if expected_path is not None and Path(expected_path).is_file() \
            and freeze.get('expected_sha256'):
        actual = _sha256_file(expected_path)
        if str(freeze['expected_sha256']).lower() != actual:
            verifier.fail(name, 'provided expected file does not match the '
                          'freeze expected_sha256', run='freeze',
                          field='expected_sha256', expected=actual,
                          actual=freeze['expected_sha256'])
    # The actual freeze records the cases/expected hashes at the top level while
    # the case file path comes from the manifest/run plan.
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    cases_sha = freeze.get('cases_sha256')
    cases_file = freeze.get('cases_file') or manifest.get('cases_file')
    if cases_sha and cases_file:
        path = Path(str(cases_file))
        if not path.is_absolute():
            path = Path(repo_root or '.') / path
        if not path.is_file():
            verifier.missing.add('freeze', 'cases file exists (%s)' % path,
                                 'freeze')
        else:
            actual = _sha256_file(path)
            if str(cases_sha).lower() != actual:
                verifier.fail(name, 'freeze.cases_sha256 does not match the '
                              'cases file on disk', run='freeze',
                              field='cases_sha256', expected=actual,
                              actual=cases_sha)
    for version_key, expected_version in (
            ('contact_contract_version',
             contact_contract.CONTACT_EVIDENCE_SCHEMA_ID),
            ('envelope_contract_version',
             body_envelope.BODY_ENVELOPE_SCHEMA_VERSION)):
        recorded = freeze.get(version_key)
        if recorded is not None and recorded != expected_version:
            verifier.fail(name, 'freeze.%s mismatch' % version_key,
                          run='freeze', field=version_key,
                          expected=expected_version, actual=recorded)
    # Manifest freeze pointer.
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    pointer = manifest.get('freeze')
    if not isinstance(pointer, dict):
        verifier.missing.add(label, 'manifest.freeze', label)
        return
    if freeze_path is not None and Path(freeze_path).is_file():
        actual = _sha256_file(freeze_path)
        if str(pointer.get('sha256') or '').lower() != actual:
            verifier.fail(name, 'manifest.freeze.sha256 does not match the '
                          'freeze file', run=label, field='freeze.sha256',
                          expected=actual, actual=pointer.get('sha256'))
        else:
            verifier.ok(name, 'freeze file sha256 verified for ' + label)
    frozen = _parse_iso(pointer.get('frozen_at'))
    started = _parse_iso(manifest.get('started_at'))
    if pointer.get('frozen_at') is not None and frozen is None:
        verifier.missing.add(label, 'manifest.freeze.frozen_at', label)
    if pointer.get('frozen_at') is None and isinstance(freeze, dict):
        frozen = _parse_iso(freeze.get('frozen_at'))
    if manifest.get('started_at') is None:
        verifier.note(name, 'manifest.started_at is not recorded; freeze '
                      'precedence is enforced at the run entry point (INFO)')
    elif started is None:
        verifier.missing.add(label, 'manifest.started_at', label)
    if frozen is not None and started is not None:
        if frozen > started:
            verifier.fail(name, 'freeze.frozen_at is after manifest.started_at',
                          run=label, field='frozen_at',
                          expected='<= ' + str(started), actual=str(frozen))
    pointer_commit = str(pointer.get('code_commit') or '').lower()
    if not pointer_commit and isinstance(freeze, dict):
        pointer_commit = str(freeze.get('code_commit') or '').lower()
    manifest_commit = str(manifest.get('code_commit') or '').lower()
    if pointer_commit and manifest_commit and not (
            manifest_commit.startswith(pointer_commit)
            or pointer_commit.startswith(manifest_commit)):
        verifier.fail(name, 'manifest.code_commit does not match the freeze '
                      'code_commit', run=label, field='code_commit',
                      expected=pointer_commit, actual=manifest_commit)
    # Per-segment run_plan: frozen plan vs recorded plan.
    entry = segments.get(evidence.segment_id)
    if entry is None:
        verifier.fail(name, 'run segment is not declared in the freeze',
                      run=label, field='segment_id',
                      expected=sorted(segments), actual=evidence.segment_id)
        return
    frozen_plan = _segment_run_plan(entry) or {}
    recorded_plan = manifest.get('run_plan')
    if not isinstance(recorded_plan, dict):
        verifier.missing.add(label, 'manifest.run_plan', label)
        return
    for key, expected in frozen_plan.items():
        if key not in recorded_plan:
            verifier.missing.add(label, 'manifest.run_plan.' + key, label)
            continue
        actual = recorded_plan[key]
        if isinstance(expected, (list, tuple)):
            if not _sequence_equal(actual, expected):
                verifier.fail(name, 'frozen run_plan field disagrees with the '
                              'manifest', run=label,
                              field='run_plan.' + key, expected=expected,
                              actual=actual)
        elif _num(expected):
            if not _close(actual, expected, PLAN_TOL):
                verifier.fail(name, 'frozen run_plan field disagrees with the '
                              'manifest', run=label,
                              field='run_plan.' + key, expected=expected,
                              actual=actual)
        elif isinstance(expected, str):
            if str(actual or '') != expected:
                verifier.fail(name, 'frozen run_plan field disagrees with the '
                              'manifest', run=label,
                              field='run_plan.' + key, expected=expected,
                              actual=actual)
    frozen_cases = entry.get('case_ids') or frozen_plan.get('case_ids')
    manifest_cases = recorded_plan.get('case_ids')
    if frozen_cases is not None and manifest_cases is not None \
            and not _sequence_equal(manifest_cases, frozen_cases):
        verifier.fail(name, 'manifest.run_plan.case_ids do not match the frozen '
                      'case_ids', run=label, field='run_plan.case_ids',
                      expected=frozen_cases, actual=manifest_cases)
    frozen_role = entry.get('role') or frozen_plan.get('role')
    if frozen_role is not None and manifest.get('role') is not None \
            and frozen_role != manifest.get('role'):
        verifier.fail(name, 'manifest.role does not match the frozen role',
                      run=label, field='role', expected=frozen_role,
                      actual=manifest.get('role'))
    verifier.ok(name, 'freeze lineage checked for ' + label)


def check_gui(evidence, verifier):
    name = 'gui_evidence'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    if manifest.get('gui_mode') is not True:
        verifier.fail(name, 'manifest.gui_mode is not true', run=label,
                      field='gui_mode', expected=True,
                      actual=manifest.get('gui_mode'))
    renderer = str(manifest.get('renderer') or '').lower()
    if not any(token in renderer for token in ('directx', 'd3d12')):
        verifier.fail(name, 'manifest.renderer is not DirectX/D3D12', run=label,
                      field='renderer', expected='DirectX/D3D12',
                      actual=manifest.get('renderer'))
    command = str(manifest.get('command') or '')
    if 'headless' in command.lower():
        verifier.fail(name, 'run command contains headless', run=label,
                      field='command', expected='no headless', actual=command)
    if (evidence.run_dir / 'screenshots').is_dir():
        verifier.ok(name, 'GUI evidence present for ' + label)
    else:
        verifier.missing.add(label, 'screenshots/', label)


def check_episode_identity(evidence, freeze, verifier):
    name = 'episode_identity_and_denominator'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    declared = manifest.get('episode_ids')
    observed = [episode.get('episode_id') for episode in evidence.episodes
                if isinstance(episode, dict)]
    if not isinstance(declared, list):
        verifier.missing.add(label, 'manifest.episode_ids', label)
    else:
        if len(declared) != len(set(str(item) for item in declared)):
            verifier.fail(name, 'manifest.episode_ids contains duplicates',
                          run=label, field='episode_ids',
                          expected='unique', actual=declared)
        if [str(item) for item in declared] != [str(item) for item in observed]:
            verifier.fail(name, 'manifest.episode_ids do not match the episodes '
                          'on disk (order/identity)', run=label,
                          field='episode_ids', expected=declared,
                          actual=observed)
        if len(declared) != len(observed):
            verifier.fail(name, 'episode denominator mismatch', run=label,
                          field='episode_ids', expected=len(observed),
                          actual=len(declared))
    plan = manifest.get('run_plan') if isinstance(manifest.get('run_plan'),
                                                  dict) else {}
    case_ids = [str(item) for item in plan.get('case_ids') or [] if item]
    if not case_ids:
        verifier.missing.add(label, 'manifest.run_plan.case_ids', label)
        return
    observed_cases = Counter(str(episode.get('case_id'))
                             for episode in evidence.episodes
                             if isinstance(episode, dict))
    repeats = 1
    entry = None
    if isinstance(freeze, dict):
        entry = _freeze_segments(freeze).get(evidence.segment_id)
        if isinstance(entry, dict) and entry.get('repeats') is not None:
            repeats = int(entry['repeats'])
        elif isinstance(entry, dict):
            run_plan = _segment_run_plan(entry) or {}
            if run_plan.get('repeats') is not None:
                repeats = int(run_plan['repeats'])
    expected_episodes = None
    if isinstance(entry, dict):
        for key in ('episodes', 'expected_episodes'):
            value = entry.get(key)
            if isinstance(value, list):
                expected_episodes = len(value)
                break
            if isinstance(value, int) and not isinstance(value, bool):
                expected_episodes = int(value)
                break
            if isinstance(value, str) and value.strip().isdigit():
                expected_episodes = int(value)
                break
    if expected_episodes is None and plan.get('expected_episodes') is not None:
        expected_episodes = int(plan['expected_episodes'])
    base_counts = Counter(case_ids)
    if repeats > 1 and len(base_counts) == len(case_ids) \
            and (expected_episodes is None
                 or len(case_ids) * repeats == expected_episodes):
        expected_counts = Counter({case_id: repeats for case_id in case_ids})
    else:
        expected_counts = base_counts
    if observed_cases != expected_counts:
        verifier.fail(name, 'episode cases do not match run_plan.case_ids x '
                      'repeats', run=label, field='case_id',
                      expected=dict(expected_counts),
                      actual=dict(observed_cases))
    expected_total = expected_episodes if expected_episodes is not None \
        else sum(expected_counts.values())
    if len(evidence.episodes) != expected_total:
        verifier.fail(name, 'episode denominator does not match the frozen '
                      'expected episode count', run=label, field='episodes',
                      expected=expected_total, actual=len(evidence.episodes))
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        case_id = str(episode.get('case_id'))
        if case_id not in case_ids:
            verifier.fail(name, 'episode case is not declared in the run plan',
                          run=label, episode_id=episode.get('episode_id'),
                          field='case_id', expected=case_ids, actual=case_id)
    verifier.ok(name, 'episode identity/denominator checked for %s (%d '
                'episodes)' % (label, len(evidence.episodes)))


def check_step_timing(evidence, verifier):
    name = 'step_physics_timing'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    sensor = manifest.get('contact_sensor') if isinstance(
        manifest.get('contact_sensor'), dict) else {}
    physics = sensor.get('physics') if isinstance(sensor.get('physics'),
                                                  dict) else {}
    physics_dt = _fnum(physics.get('physics_dt_s'))
    decimation = physics.get('decimation')
    decimation = int(decimation) if isinstance(decimation, int) \
        and not isinstance(decimation, bool) else None
    if physics_dt is None or decimation is None:
        verifier.missing.add(label, 'contact_sensor.physics timing fields',
                             label)
        return
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        rows = sorted(evidence.steps_by_episode.get(
            episode.get('episode_id'), []), key=lambda row: (
                float(row.get('time_s')) if _num(row.get('time_s')) else -1.0,
                row.get('step') if _num(row.get('step')) else 0))
        if not rows:
            verifier.missing.add(label, 'steps for episode %s'
                                 % episode.get('episode_id'), label)
            continue
        first_physics = None
        first_time = None
        previous_step = None
        previous_physics = None
        previous_time = None
        for row in rows:
            step = row.get('step')
            time_s = _fnum(row.get('time_s'))
            physics_step = row.get('physics_step')
            if not _num(time_s) or not isinstance(physics_step, int):
                continue
            if previous_time is not None and time_s <= previous_time:
                verifier.fail(name, 'time_s is not strictly increasing',
                              run=label, episode_id=episode.get('episode_id'),
                              step=step, field='time_s',
                              expected='> %.6f' % previous_time, actual=time_s)
            if _num(step) and previous_step is not None \
                    and step != previous_step + 1:
                verifier.fail(name, 'step index is not contiguous', run=label,
                              episode_id=episode.get('episode_id'), step=step,
                              field='step', expected=previous_step + 1,
                              actual=step)
            if previous_physics is not None \
                    and physics_step != previous_physics + decimation:
                verifier.fail(name, 'physics_step does not advance by one '
                              'control step (decimation)', run=label,
                              episode_id=episode.get('episode_id'), step=step,
                              field='physics_step',
                              expected=previous_physics + decimation,
                              actual=physics_step)
            if first_physics is None:
                first_physics = physics_step
                first_time = time_s
            expected_time = first_time + (physics_step - first_physics) \
                * physics_dt
            if abs(time_s - expected_time) > TIME_TOL_S:
                verifier.fail(name, 'time_s does not match physics_step * '
                              'physics_dt_s', run=label,
                              episode_id=episode.get('episode_id'), step=step,
                              field='time_s', expected=expected_time,
                              actual=time_s)
            previous_step = step
            previous_physics = physics_step
            previous_time = time_s
    verifier.ok_if_clean(name, 'step/physics timing checked for ' + label)


def check_episode_boundary(evidence, verifier):
    name = 'episode_boundary'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    boundary = manifest.get('episode_boundary')
    if not isinstance(boundary, dict):
        verifier.missing.add(label, 'manifest.episode_boundary', label)
        return
    if boundary.get('started_from_reset') is not True:
        verifier.fail(name, 'episode_boundary.started_from_reset is not true',
                      run=label, field='episode_boundary.started_from_reset',
                      expected=True, actual=boundary.get('started_from_reset'))
    if boundary.get('no_silent_reset') is not True:
        verifier.fail(name, 'episode_boundary.no_silent_reset is not true',
                      run=label, field='episode_boundary.no_silent_reset',
                      expected=True, actual=boundary.get('no_silent_reset'))
    verifier.ok_if_clean(name, 'episode boundary checked for ' + label)


def check_artifacts(evidence, verifier):
    name = 'artifact_hashes'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    outputs = manifest.get('outputs_sha256') or manifest.get('artifact_hashes')
    verified = 0
    if isinstance(outputs, dict) and outputs:
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
    if (evidence.run_dir / 'summary.json').is_file():
        verifier.ok_if_clean(name, '%d artifact hashes verified for %s'
                             % (verified, label))
    else:
        verifier.missing.add(label, 'summary.json', label)


# ---------------------------------------------------------------------------
# contact contract checks
# ---------------------------------------------------------------------------

def _steps(evidence, episode):
    return sorted(evidence.steps_by_episode.get(episode.get('episode_id'), []),
                  key=lambda row: (float(row.get('time_s'))
                                   if _num(row.get('time_s')) else -1.0,
                                   row.get('step')
                                   if _num(row.get('step')) else 0))


def _inventory_paths(manifest):
    inventory = manifest.get('prim_inventory') \
        if isinstance(manifest.get('prim_inventory'), dict) else {}
    result = {'all': set(), 'collision': set(), 'by_category': {}}
    for category in ('robot', 'obstacle', 'map'):
        paths = set()
        for entry in inventory.get(category) or []:
            if not isinstance(entry, dict):
                continue
            path = entry.get('path')
            if not isinstance(path, str) or not path:
                continue
            paths.add(path)
            result['all'].add(path)
            if entry.get('collision') is True:
                result['collision'].add(path)
        result['by_category'][category] = paths
    return result


def check_contact_contract(evidence, episode, rows, verifier, analysis):
    label = evidence.segment_id
    episode_id = episode.get('episode_id')
    inventory = _inventory_paths(
        evidence.manifest if isinstance(evidence.manifest, dict) else {})
    records = []
    for row in rows:
        record = row.get('contact_record')
        step = row.get('step')
        if not isinstance(record, dict):
            verifier.missing.add(label, 'steps[].contact_record', _example(row))
            continue
        records.append(record)
        # schema / structural validation from the contract
        errors = contact_contract.validate_contact_record(record)
        if errors:
            verifier.fail('contact_record_schema', 'contact_record failed the '
                          'v2 validator: ' + '; '.join(errors), run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record', expected=[], actual=errors)
        if record.get('step') != step or not _close(record.get('time_s'),
                                                     row.get('time_s'),
                                                     TIME_TOL_S):
            verifier.fail('contact_record_schema', 'contact_record step/time do '
                          'not match the row', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.step/time', expected=(step,
                              row.get('time_s')),
                          actual=(record.get('step'), record.get('time_s')))
        try:
            recomputed = contact_contract.classify_contact(record)
        except (KeyError, TypeError, ValueError) as error:
            verifier.fail('contact_classification', 'independent classification '
                          'failed: ' + repr(error), run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.classification',
                          expected='classifiable', actual=repr(error))
            continue
        if record.get('classification') != recomputed:
            verifier.fail('contact_classification', 'stored classification is '
                          'not reproducible from the raw layers', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.classification',
                          expected=recomputed,
                          actual=record.get('classification'))
        layers = record.get('layers') if isinstance(record.get('layers'),
                                                    dict) else {}
        force = layers.get('force') if isinstance(layers.get('force'),
                                                  dict) else {}
        impulse = layers.get('impulse') if isinstance(layers.get('impulse'),
                                                      dict) else {}
        event = layers.get('event') if isinstance(layers.get('event'),
                                                  dict) else {}
        geometry = layers.get('geometry') if isinstance(layers.get('geometry'),
                                                        dict) else {}
        attribution = layers.get('attribution') \
            if isinstance(layers.get('attribution'), dict) else {}
        sensor = record.get('sensor') if isinstance(record.get('sensor'),
                                                    dict) else {}
        # units / threshold
        if force.get('unit') != contact_contract.FORCE_UNIT:
            verifier.fail('contact_units_and_threshold',
                          'force unit is not N', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.force.unit',
                          expected=contact_contract.FORCE_UNIT,
                          actual=force.get('unit'))
        if impulse.get('unit') != contact_contract.IMPULSE_UNIT:
            verifier.fail('contact_units_and_threshold',
                          'impulse unit is not N*s', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.impulse.unit',
                          expected=contact_contract.IMPULSE_UNIT,
                          actual=impulse.get('unit'))
        magnitude = force.get('magnitude_n')
        if not (_num(magnitude)
                and magnitude > contact_contract.CONTACT_FORCE_THRESHOLD_N) \
                and record.get('classification') in (
                    contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                    contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED):
            verifier.fail('contact_units_and_threshold',
                          'force-measured classification requires magnitude '
                          'strictly greater than the 0.02 N threshold', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.force.magnitude_n',
                          expected='> 0.02', actual=magnitude)
        if _num(magnitude) \
                and abs(magnitude - contact_contract.CONTACT_FORCE_THRESHOLD_N) \
                < 1e-12 and recomputed in (
                    contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                    contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED):
            verifier.fail('contact_units_and_threshold',
                          'magnitude exactly at the threshold must not be '
                          'classified as force measured', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.force.magnitude_n',
                          expected='strictly > 0.02', actual=magnitude)
        # sensor invalid vs valid zero
        sensor_available = sensor.get('available')
        if sensor_available is False:
            if recomputed != contact_contract.CLASS_UNKNOWN:
                verifier.fail('sensor_invalid_vs_valid_zero',
                              'sensor.unavailable must classify UNKNOWN',
                              run=label, episode_id=episode_id, step=step,
                              field='contact_record.sensor.available',
                              expected='UNKNOWN', actual=recomputed)
            if force.get('available') is True and force.get('magnitude_n') == 0.0:
                verifier.fail('sensor_invalid_vs_valid_zero',
                              'a zero force was recorded while the sensor was '
                              'unavailable (zero is not evidence of no contact)',
                              run=label, episode_id=episode_id, step=step,
                              field='contact_record.layers.force.magnitude_n',
                              expected=None, actual=force.get('magnitude_n'))
            if force.get('magnitude_n') is not None:
                verifier.fail('sensor_invalid_vs_valid_zero',
                              'sensor.unavailable must store force magnitude as '
                              'None, never a number', run=label,
                              episode_id=episode_id, step=step,
                              field='contact_record.layers.force.magnitude_n',
                              expected=None, actual=force.get('magnitude_n'))
        elif sensor_available is True \
                and recomputed == contact_contract.CLASS_NO_CONTACT:
            # A working channel may read a real sub-threshold force (< 0.02 N)
            # and still classify NO_CONTACT; a filtered or net-force zero is
            # both acceptable.  Only "unavailable"/null magnitudes are invalid.
            magnitude = force.get('magnitude_n')
            if force.get('available') is not True or not _num(magnitude) \
                    or magnitude < 0.0 \
                    or magnitude > contact_contract.CONTACT_FORCE_THRESHOLD_N \
                    + 1e-12:
                verifier.fail('sensor_invalid_vs_valid_zero',
                              'valid NO_CONTACT requires an available force '
                              'layer with a numeric sub-threshold magnitude',
                              run=label, episode_id=episode_id, step=step,
                              field='contact_record.layers.force',
                              expected='available=True, 0 <= magnitude_n <= '
                                       '0.02',
                              actual={'available': force.get('available'),
                                      'basis': force.get('basis'),
                                      'magnitude_n': magnitude})
        # attribution
        status = attribution.get('status')
        prim_paths = attribution.get('prim_paths')
        if status == contact_contract.ATTRIBUTION_ATTRIBUTED:
            # A filtered zero-force map is a valid ATTRIBUTED step with no
            # contacting prims; a force-measured or event step must name prims.
            requires_prims = (recomputed in (
                contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED)
                or event.get('event') is True)
            if requires_prims and not prim_paths:
                verifier.fail('attribution_contract', 'ATTRIBUTED contact step '
                              'requires non-empty prim_paths', run=label,
                              episode_id=episode_id, step=step,
                              field='contact_record.layers.attribution.'
                                    'prim_paths', expected='non-empty',
                              actual=prim_paths)
            for path in prim_paths or []:
                if path not in inventory['all']:
                    verifier.fail('attribution_contract',
                                  'attributed prim path is not in '
                                  'prim_inventory', run=label,
                                  episode_id=episode_id, step=step,
                                  field='contact_record.layers.attribution.'
                                        'prim_paths', expected='inventory path',
                                  actual=path)
                elif path not in inventory['collision']:
                    verifier.note('attribution_contract',
                                  'attributed prim %s is in the inventory but '
                                  'not flagged as collision geometry' % path)
            if force.get('basis') == contact_contract.FORCE_BASIS_NET:
                verifier.fail('attribution_contract', 'net-force basis cannot '
                              'be ATTRIBUTED', run=label,
                              episode_id=episode_id, step=step,
                              field='contact_record.layers.attribution.status',
                              expected='UNATTRIBUTED', actual=status)
        elif status in (contact_contract.ATTRIBUTION_UNATTRIBUTED,
                        contact_contract.ATTRIBUTION_UNKNOWN):
            if prim_paths:
                verifier.fail('attribution_contract',
                              'UNATTRIBUTED/UNKNOWN must not fabricate prim '
                              'paths', run=label, episode_id=episode_id,
                              step=step,
                              field='contact_record.layers.attribution.'
                                    'prim_paths', expected=[], actual=prim_paths)
        else:
            verifier.fail('attribution_contract', 'invalid attribution status',
                          run=label, episode_id=episode_id, step=step,
                          field='contact_record.layers.attribution.status',
                          expected=list(contact_contract.ATTRIBUTION_STATUSES),
                          actual=status)
        # geometry never promoted / impulse never a force
        if recomputed in CONTACT_OUTCOMES and not sensor_available:
            verifier.fail('geometry_never_promoted',
                          'a PhysX contact classification requires an available '
                          'sensor channel', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.sensor.available',
                          expected=True, actual=sensor_available)
        if recomputed == contact_contract.CLASS_GEOMETRY_OVERLAP_ONLY:
            if event.get('event') is True:
                verifier.fail('geometry_never_promoted',
                              'geometry-only classification must not carry an '
                              'event=True', run=label,
                              episode_id=episode_id, step=step,
                              field='contact_record.layers.event.event',
                              expected=False, actual=True)
        elif record.get('classification') \
                == contact_contract.CLASS_GEOMETRY_OVERLAP_ONLY \
                and event.get('event') is True:
            # A stored geometry-only label with a raw PhysX event is exactly the
            # promotion this contract forbids.
            verifier.fail('geometry_never_promoted',
                          'a stored GEOMETRY_OVERLAP_ONLY record carries '
                          'event=True (geometry promoted to a PhysX contact)',
                          run=label, episode_id=episode_id, step=step,
                          field='contact_record.classification',
                          expected=contact_contract.CLASS_CONTACT_EVENT_ONLY,
                          actual=record.get('classification'))
        if recomputed in (contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                          contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED):
            if force.get('available') is not True:
                verifier.fail('impulse_never_force',
                              'force-measured classification requires the force '
                              'layer to be available (impulse is not a force)',
                              run=label, episode_id=episode_id, step=step,
                              field='contact_record.layers.force.available',
                              expected=True, actual=force.get('available'))
        if force.get('basis') == contact_contract.FORCE_BASIS_NET \
                and force.get('per_prim_n') is not None:
            verifier.fail('net_vs_per_prim', 'net force must not be stored as a '
                          'per-prim force', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.force.per_prim_n',
                          expected=None, actual=force.get('per_prim_n'))
        if force.get('basis') == contact_contract.FORCE_BASIS_FILTERED \
                and not isinstance(force.get('per_prim_n'), dict):
            verifier.fail('net_vs_per_prim', 'filtered force basis requires a '
                          'per-prim force map', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.force.per_prim_n',
                          expected='mapping',
                          actual=force.get('per_prim_n'))
        # event source/basis enums
        if event.get('source') not in contact_contract.EVENT_SOURCES:
            verifier.fail('contact_units_and_threshold',
                          'invalid event.source enum', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.event.source',
                          expected=sorted(contact_contract.EVENT_SOURCES),
                          actual=event.get('source'))
        if event.get('force_basis') not in contact_contract.FORCE_BASES:
            verifier.fail('contact_units_and_threshold',
                          'invalid event.force_basis enum', run=label,
                          episode_id=episode_id, step=step,
                          field='contact_record.layers.event.force_basis',
                          expected=sorted(contact_contract.FORCE_BASES),
                          actual=event.get('force_basis'))
        # geometry overlap vs row value
        row_overlap = _fnum(row.get('geometry_overlap_sphere_m'))
        if geometry.get('available') is True:
            if row_overlap is None or not _close(
                    geometry.get('sphere_overlap_m'), row_overlap, 1e-9):
                verifier.fail('contact_record_schema',
                              'row.geometry_overlap_sphere_m does not match the '
                              'contact_record geometry layer', run=label,
                              episode_id=episode_id, step=step,
                              field='geometry_overlap_sphere_m',
                              expected=geometry.get('sphere_overlap_m'),
                              actual=row_overlap)
    analysis['records'] = records
    # contact summary vs independent aggregate of the same raw records
    summary = episode.get('contact_summary')
    if records and isinstance(summary, dict):
        try:
            recomputed_summary = contact_contract.summarize_contact_records(
                records)
        except ValueError as error:
            verifier.fail('contact_summary_recompute',
                          'independent contact summary failed: ' + repr(error),
                          run=label, episode_id=episode_id,
                          field='contact_summary', expected='valid records',
                          actual=repr(error))
            recomputed_summary = None
        if recomputed_summary is not None:
            for key in ('total_steps', 'classification_counts',
                        'max_force_n', 'unknown_steps', 'unknown_reasons',
                        'geometry_only_steps', 'attributed_steps',
                        'unattributed_steps'):
                expected_value = recomputed_summary.get(key)
                actual_value = summary.get(key)
                if key == 'max_force_n':
                    if not _equal_nullable(actual_value, expected_value,
                                           FORCE_TOL_N):
                        verifier.fail('contact_summary_recompute',
                                      'contact_summary.%s does not match the '
                                      'independent aggregate' % key,
                                      run=label, episode_id=episode_id,
                                      field='contact_summary.' + key,
                                      expected=expected_value,
                                      actual=actual_value)
                elif key == 'classification_counts' or key == 'unknown_reasons':
                    if _jsonable(actual_value) != _jsonable(expected_value):
                        verifier.fail('contact_summary_recompute',
                                      'contact_summary.%s does not match the '
                                      'independent aggregate' % key,
                                      run=label, episode_id=episode_id,
                                      field='contact_summary.' + key,
                                      expected=expected_value,
                                      actual=actual_value)
                elif actual_value != expected_value:
                    verifier.fail('contact_summary_recompute',
                                  'contact_summary.%s does not match the '
                                  'independent aggregate' % key, run=label,
                                  episode_id=episode_id,
                                  field='contact_summary.' + key,
                                  expected=expected_value,
                                  actual=actual_value)
    for name in ('contact_record_schema', 'contact_classification',
                 'contact_units_and_threshold',
                 'sensor_invalid_vs_valid_zero', 'attribution_contract',
                 'geometry_never_promoted', 'impulse_never_force',
                 'net_vs_per_prim', 'contact_summary_recompute'):
        verifier.ok_if_clean(name, 'checked for %s' % episode_id)
    analysis['inventory'] = inventory


def _equal_nullable(actual, expected, tolerance):
    if actual is None or expected is None:
        return actual is None and expected is None
    return _close(actual, expected, tolerance)


# ---------------------------------------------------------------------------
# envelope geometry checks
# ---------------------------------------------------------------------------

def check_envelope(evidence, verifier, repo_root=None):
    name = 'envelope_radius_recompute'
    label = evidence.segment_id
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    record = manifest.get('body_envelope')
    if not isinstance(record, dict):
        verifier.missing.add(label, 'manifest.body_envelope', label)
        return
    try:
        body_envelope.validate_body_envelope_record(record)
    except body_envelope.BodyEnvelopeValidationError as error:
        # Keep running the explicit geometry checks: the validator failure is
        # reported here and the per-field checks below identify the defect.
        verifier.fail(name, 'body_envelope.v2 validator rejected the record: '
                      + str(error), run=label, field='body_envelope',
                      expected='valid v2 record', actual=error.reason)
    aabb = record.get('aabb') if isinstance(record.get('aabb'), dict) else {}
    half = _vec(aabb.get('half_extents_m'))
    offset = _vec(aabb.get('center_offset_m'))
    sphere = record.get('sphere_about_origin') \
        if isinstance(record.get('sphere_about_origin'), dict) else {}
    center_sphere = record.get('sphere_about_aabb_center') \
        if isinstance(record.get('sphere_about_aabb_center'), dict) else {}
    production = record.get('production') \
        if isinstance(record.get('production'), dict) else {}
    if half is None or offset is None:
        verifier.missing.add(label, 'manifest.body_envelope.aabb vectors', label)
        return
    recomputed_radius = math.sqrt(sum((abs(offset[axis]) + half[axis]) ** 2
                                      for axis in range(3)))
    half_diagonal = math.sqrt(sum(value * value for value in half))
    if not _close(sphere.get('radius_m'), recomputed_radius, RADIUS_TOL):
        verifier.fail(name, 'sphere_about_origin.radius_m is not '
                      '|| |center_offset_m| + half_extents_m ||_2', run=label,
                      field='body_envelope.sphere_about_origin.radius_m',
                      expected=recomputed_radius,
                      actual=sphere.get('radius_m'))
    if not _close(production.get('radius_m'), recomputed_radius, RADIUS_TOL):
        verifier.fail(name, 'production.radius_m is not the around-origin '
                      'radius', run=label, field='body_envelope.production.'
                                                 'radius_m',
                      expected=recomputed_radius,
                      actual=production.get('radius_m'))
    if not _close(center_sphere.get('radius_m'), half_diagonal, RADIUS_TOL):
        verifier.fail(name, 'sphere_about_aabb_center.radius_m is not the half '
                      'diagonal ||half_extents_m||', run=label,
                      field='body_envelope.sphere_about_aabb_center.radius_m',
                      expected=half_diagonal,
                      actual=center_sphere.get('radius_m'))
    if production.get('envelope_field') \
            != body_envelope.PRODUCTION_ENVELOPE_FIELD:
        verifier.fail(name, 'production.envelope_field is not sphere_about_origin',
                      run=label, field='body_envelope.production.'
                                       'envelope_field',
                      expected=body_envelope.PRODUCTION_ENVELOPE_FIELD,
                      actual=production.get('envelope_field'))
    # episode-level recorded radius must equal the recomputed around-origin one
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        recorded = episode.get('envelope_sphere_about_origin_m')
        if recorded is None:
            verifier.missing.add(
                label, 'episodes[].envelope_sphere_about_origin_m',
                'episode %s' % episode.get('episode_id'))
        elif not _close(recorded, recomputed_radius, RADIUS_TOL):
            verifier.fail(name, 'episode envelope radius is not the around-origin '
                          'radius', run=label,
                          episode_id=episode.get('episode_id'),
                          field='envelope_sphere_about_origin_m',
                          expected=recomputed_radius, actual=recorded)
    verifier.ok_if_clean(name, 'envelope radius checked for ' + label)
    analysis = {'recomputed_radius_m': recomputed_radius,
                'half_diagonal_m': half_diagonal}
    # legacy clearance radius (must be explicit, delta is INFO not failure)
    legacy_seen = []
    for episode in evidence.episodes:
        if not isinstance(episode, dict):
            continue
        legacy_radius = None
        for key in ('legacy_clearance_radius_m',
                    'envelope_legacy_clearance_radius_m',
                    'clearance_legacy_radius_m'):
            if _num(episode.get(key)):
                legacy_radius = float(episode[key])
                break
        legacy_delta = None
        for key in ('legacy_clearance_delta_m', 'envelope_legacy_delta_m'):
            if _num(episode.get(key)):
                legacy_delta = float(episode[key])
                break
        if legacy_radius is None:
            continue
        expected_delta = recomputed_radius - legacy_radius
        if legacy_delta is None:
            verifier.missing.add(
                label, 'episodes[].envelope_legacy_delta_m (legacy clearance '
                       'radius is used)', 'episode %s'
                % episode.get('episode_id'))
        elif not _close(legacy_delta, expected_delta, RADIUS_TOL):
            verifier.fail('envelope_legacy_delta',
                          'recorded legacy clearance delta is not '
                          'r_origin - legacy_radius', run=label,
                          episode_id=episode.get('episode_id'),
                          field='legacy_clearance_delta_m',
                          expected=expected_delta, actual=legacy_delta)
        else:
            verifier.note('envelope_legacy_delta',
                          'legacy clearance radius used for %s: delta %.12f m '
                          '(INFO, not a failure)'
                          % (episode.get('episode_id'), expected_delta))
            legacy_seen.append({'episode_id': episode.get('episode_id'),
                                'legacy_radius_m': legacy_radius,
                                'delta_m': expected_delta})
    # The legacy clearance-radius correction is also recorded explicitly in the
    # analysis artifact; verify the recorded delta there and report it as INFO.
    legacy_artifact = None
    candidates = []
    if repo_root is not None:
        candidates.append(Path(repo_root) / 'docs' / 'reports' / 'map_eval'
                          / 'contact_envelope'
                          / 'analyze_envelope_correction.json')
    else:
        candidates.append(ROOT / 'docs' / 'reports' / 'map_eval'
                          / 'contact_envelope' / 'analyze_envelope_correction.json')
    for candidate in candidates:
        if candidate.is_file():
            try:
                legacy_artifact = _load_json(candidate)
            except (OSError, ValueError) as error:
                verifier.fail('envelope_legacy_delta',
                              'envelope correction artifact parse failure: '
                              + repr(error), run='envelope',
                              field='analyze_envelope_correction.json',
                              expected='valid json', actual=repr(error))
            break
    if isinstance(legacy_artifact, dict):
        recorded_origin = _fnum(legacy_artifact.get(
            'radius_sphere_about_origin_m'))
        recorded_center = _fnum(legacy_artifact.get(
            'radius_sphere_about_aabb_center_m'))
        recorded_delta = _fnum(legacy_artifact.get('legacy_underestimate_m'))
        expected_delta = recomputed_radius - half_diagonal
        if recorded_origin is not None \
                and not _close(recorded_origin, recomputed_radius, RADIUS_TOL):
            verifier.fail('envelope_legacy_delta',
                          'analysis artifact around-origin radius does not match '
                          'the manifest', run='envelope',
                          field='radius_sphere_about_origin_m',
                          expected=recomputed_radius, actual=recorded_origin)
        if recorded_center is not None \
                and not _close(recorded_center, half_diagonal, RADIUS_TOL):
            verifier.fail('envelope_legacy_delta',
                          'analysis artifact legacy radius is not the AABB half '
                          'diagonal', run='envelope',
                          field='radius_sphere_about_aabb_center_m',
                          expected=half_diagonal, actual=recorded_center)
        if recorded_delta is not None \
                and not _close(recorded_delta, expected_delta, RADIUS_TOL):
            verifier.fail('envelope_legacy_delta',
                          'analysis artifact legacy delta is not r_origin - '
                          'r_legacy', run='envelope',
                          field='legacy_underestimate_m',
                          expected=expected_delta, actual=recorded_delta)
        if recorded_delta is not None:
            verifier.note('envelope_legacy_delta',
                          'legacy clearance correction recorded explicitly: '
                          '%.9f -> %.9f m (delta %.12f m, INFO)'
                          % (half_diagonal, recomputed_radius, recorded_delta))
            legacy_seen.append({'source': str(candidate),
                                'legacy_radius_m': half_diagonal,
                                'delta_m': recorded_delta})
    verifier.ok_if_clean('envelope_legacy_delta',
                         'no legacy clearance radius recorded' if not legacy_seen
                         else '%d episodes record a legacy clearance delta '
                              '(INFO)' % len(legacy_seen))
    analysis['legacy'] = legacy_seen
    # coverage vs prim inventory
    inventory = _inventory_paths(manifest)
    coverage = record.get('coverage') if isinstance(record.get('coverage'),
                                                    dict) else {}
    collision_paths = coverage.get('collision_prim_paths') or []
    visual_paths = coverage.get('visual_prim_paths') or []
    prim_paths = coverage.get('prim_paths') or []
    robot_collision = sorted(inventory['by_category'].get('robot', set())
                             & inventory['collision'])
    global_collision = inventory['collision']
    for path in list(collision_paths) + list(visual_paths) + list(prim_paths):
        if path not in inventory['all']:
            verifier.fail('envelope_coverage_inventory',
                          'coverage prim path is not in prim_inventory',
                          run=label, field='body_envelope.coverage',
                          expected=sorted(inventory['all'])[:20], actual=path)
    source = coverage.get('source')
    if source == body_envelope.ENVELOPE_SOURCE_COLLISION_GEOMETRY:
        if sorted(collision_paths) != robot_collision:
            verifier.fail('envelope_coverage_inventory',
                          'coverage.collision_prim_paths does not equal the '
                          'prim_inventory robot CollisionAPI set', run=label,
                          field='body_envelope.coverage.collision_prim_paths',
                          expected=robot_collision,
                          actual=sorted(collision_paths))
        if set(robot_collision) - set(global_collision):
            verifier.fail('envelope_coverage_inventory',
                          'robot coverage paths are not flagged collision in '
                          'prim_inventory', run=label,
                          field='prim_inventory.robot', expected='collision',
                          actual=sorted(set(robot_collision) - global_collision))
    elif source == body_envelope.ENVELOPE_SOURCE_MIXED:
        if not collision_paths or not visual_paths:
            verifier.fail('envelope_coverage_inventory',
                          'mixed coverage requires collision and visual paths',
                          run=label, field='body_envelope.coverage',
                          expected='both non-empty', actual=source)
    if not (set(prim_paths) >= set(collision_paths) | set(visual_paths)):
        verifier.fail('envelope_coverage_inventory',
                      'coverage.prim_paths does not include every measured prim',
                      run=label, field='body_envelope.coverage.prim_paths',
                      expected='includes collision+visual paths',
                      actual=prim_paths)
    verifier.ok_if_clean('envelope_coverage_inventory',
                         'coverage compared with prim_inventory for ' + label)
    # limitations
    limitations = record.get('limitations') or []
    coverage_limitations = coverage.get('limitations') or []
    joined = ' '.join(str(item) for item in limitations).lower()
    if 'triangle-mesh sweep' not in joined or 'not' not in joined:
        verifier.fail('envelope_limitations',
                      'manifest limitations do not state the non-mesh-sweep '
                      'limitation', run=label,
                      field='body_envelope.limitations',
                      expected='AABB/sphere bound is not a triangle-mesh sweep',
                      actual=limitations)
    if not coverage_limitations:
        verifier.fail('envelope_limitations',
                      'coverage.limitations must not be empty (no unqualified '
                      'full-coverage claim)', run=label,
                      field='body_envelope.coverage.limitations',
                      expected='non-empty', actual=coverage_limitations)
    verifier.ok_if_clean('envelope_limitations',
                         'envelope limitations checked for ' + label)
    return analysis


# ---------------------------------------------------------------------------
# scenario expectations
# ---------------------------------------------------------------------------

def _parse_condition(condition):
    if isinstance(condition, str):
        return condition.strip(), None
    if isinstance(condition, dict):
        kind = condition.get('kind') or condition.get('condition')
        return (kind.strip() if isinstance(kind, str) else None,
                condition.get('value', condition.get('m')))
    return None, None


def _acceptable_outcomes(spec):
    value = spec.get('acceptable_physical_outcomes')
    if not (isinstance(value, list) and value):
        value = spec.get('acceptable_physical')
    if not (isinstance(value, list) and value):
        value = spec.get('expected_physical_outcome')
        if isinstance(value, str) and value:
            value = [value]
    if not (isinstance(value, list) and value):
        value = spec.get('physical_outcome')
        if isinstance(value, str) and value:
            value = [value]
    if not (isinstance(value, list) and value):
        return None
    return [canonical_physical(item) for item in value]


def _attribution_paths(spec):
    for key in ('attribution_prim_paths', 'wall_prim_paths',
                'required_attribution_prim_paths'):
        value = spec.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    # The actual expected file declares the wall prim inside a must_condition:
    # {"kind": "attribution_prim_in", "value": "<prim>"}.
    for condition in spec.get('must_conditions') or []:
        kind, value = _parse_condition(condition)
        if kind == 'attribution_prim_in' and isinstance(value, str) and value:
            return [value]
    return None


def _at_least_one(rows, predicate):
    return any(predicate(row) for row in rows)


def _contact_records(rows):
    return [row.get('contact_record') for row in rows
            if isinstance(row.get('contact_record'), dict)]


def _record_layers(record):
    layers = record.get('layers') if isinstance(record.get('layers'),
                                                dict) else {}
    return layers


def _record_force_magnitude(record):
    force = _record_layers(record).get('force')
    return _fnum(force.get('magnitude_n')) if isinstance(force, dict) else None


def _step_contact_view(rows):
    view = {'records': _contact_records(rows), 'event_steps': 0,
            'force_measured_steps': 0, 'attributed_steps': 0,
            'attribution_paths': set(), 'geometry_steps': 0,
            'sensor_available_all': True, 'event_true_steps': 0,
            'event_available_all': True,
            'force_available_steps': 0, 'valid_zero_steps': 0,
            'unknown_steps': 0, 'classifications': Counter(),
            'geometry_overlaps': [], 'max_geometry_overlap_m': 0.0,
            'min_geometry_overlap_m': 0.0,
            'row_force_measured_steps': 0, 'row_force_max_n': 0.0}
    for record in view['records']:
        sensor = record.get('sensor') if isinstance(record.get('sensor'),
                                                    dict) else {}
        layers = _record_layers(record)
        event = layers.get('event') if isinstance(layers.get('event'),
                                                  dict) else {}
        force = layers.get('force') if isinstance(layers.get('force'),
                                                  dict) else {}
        geometry = layers.get('geometry') if isinstance(layers.get('geometry'),
                                                        dict) else {}
        attribution = layers.get('attribution') \
            if isinstance(layers.get('attribution'), dict) else {}
        classification = record.get('classification')
        view['classifications'][str(classification)] += 1
        if sensor.get('available') is False:
            view['sensor_available_all'] = False
        if event.get('available') is False:
            view['event_available_all'] = False
        if event.get('event') is True:
            view['event_true_steps'] += 1
        if classification == contact_contract.CLASS_UNKNOWN:
            view['unknown_steps'] += 1
        if classification in (contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                              contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED):
            view['force_measured_steps'] += 1
        if classification in CONTACT_OUTCOMES:
            view['event_steps'] += 1
        if force.get('available') is True:
            view['force_available_steps'] += 1
            magnitude = force.get('magnitude_n')
            if _num(magnitude) and magnitude < 0.02 \
                    and event.get('event') is not True:
                view['valid_zero_steps'] += 1
        if geometry.get('available') is True:
            overlap = _fnum(geometry.get('sphere_overlap_m'))
            if overlap is not None:
                view['geometry_overlaps'].append(overlap)
                if overlap > 0.02:
                    view['geometry_steps'] += 1
        if attribution.get('status') == contact_contract.ATTRIBUTION_ATTRIBUTED:
            view['attributed_steps'] += 1
            for path in attribution.get('prim_paths') or []:
                view['attribution_paths'].add(path)
    # The runner also records the raw step-level contact force/prim (the filtered
    # wall contact path fills these even when the v2 force layer is unavailable).
    for row in rows:
        row_force = _fnum(row.get('contact_force_n'))
        if row_force is None:
            continue
        view['row_force_max_n'] = max(view['row_force_max_n'], row_force)
        if row_force > contact_contract.CONTACT_FORCE_THRESHOLD_N:
            view['row_force_measured_steps'] += 1
            prim = row.get('contact_prim')
            if isinstance(prim, str) and prim:
                view['attribution_paths'].add(prim)
    if view['geometry_overlaps']:
        view['max_geometry_overlap_m'] = max(view['geometry_overlaps'])
        view['min_geometry_overlap_m'] = min(view['geometry_overlaps'])
    return view


def _role_expectation(evidence, episode, spec, rows, verifier, analysis):
    role = evidence.manifest.get('role') \
        if isinstance(evidence.manifest, dict) else None
    label = evidence.segment_id
    episode_id = episode.get('episode_id')
    case_id = episode.get('case_id')
    physical = canonical_physical(episode.get('physical_outcome'))
    view = _step_contact_view(rows)
    analysis['view'] = view
    inventory = analysis.get('inventory') or _inventory_paths(evidence.manifest)
    declared_prims = _attribution_paths(spec) if isinstance(spec, dict) else None
    name = 'segment_role_expectations'
    if role == 'wall':
        if physical != CONTACT_FORCE_MEASURED:
            verifier.deviate(name, 'wall_force_measured_expected',
                             'wall segment expects CONTACT_FORCE_MEASURED',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=CONTACT_FORCE_MEASURED, actual=physical)
        measured_attributed = view['force_measured_steps'] > 0 \
            or (view['row_force_measured_steps'] > 0
                and bool(view['attribution_paths']))
        if not measured_attributed:
            verifier.deviate(name, 'wall_attributed_force_missing',
                             'wall segment requires at least one attributed '
                             'force-measured step', run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected='CONTACT_FORCE_MEASURED', actual=physical)
        robot_paths = inventory['by_category'].get('robot', set())
        wall_paths = set(declared_prims) if declared_prims else set()
        if wall_paths:
            # The expected file names the wall prim through an
            # attribution_prim_in must_condition; check it exists in inventory.
            outside = [path for path in wall_paths if path not in inventory['all']]
            if outside:
                verifier.fail('attribution_contract',
                              'declared wall attribution prim is not in '
                              'prim_inventory', run=label,
                              episode_id=episode_id,
                              field='expected.attribution_prim_in',
                              expected=sorted(inventory['all'])[:20],
                              actual=outside)
        if not wall_paths:
            non_robot = inventory['all'] - robot_paths
            wall_paths = {path for path in non_robot
                          if 'wall' in path.lower()}
            if not wall_paths:
                verifier.note(name, 'wall prim set not declared; falling back to '
                                   'prim_inventory non-robot paths')
                wall_paths = non_robot
        for path in view['attribution_paths']:
            if declared_prims and path not in declared_prims:
                verifier.deviate(name, 'wall_attribution_outside_wall_prims',
                                 'wall attribution prim is outside the declared '
                                 'wall prim set', run=label,
                                 episode_id=episode_id, case_id=case_id,
                                 expected=sorted(declared_prims), actual=path)
            elif not declared_prims and path not in wall_paths:
                verifier.deviate(name, 'wall_attribution_outside_wall_prims',
                                 'wall attribution prim is outside the inferred '
                                 'wall prim set', run=label,
                                 episode_id=episode_id, case_id=case_id,
                                 expected=sorted(wall_paths), actual=path)
    elif role == 'obstacle':
        if physical not in CONTACT_OUTCOMES:
            verifier.deviate(name, 'obstacle_physx_evidence_expected',
                             'obstacle segment requires measured force or a '
                             'PhysX event, not geometry-only/no-contact',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=list(CONTACT_OUTCOMES), actual=physical)
        has_physx = any(
            cls in (contact_contract.CLASS_CONTACT_FORCE_MEASURED,
                    contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED,
                    contact_contract.CLASS_CONTACT_EVENT_ONLY)
            for cls in view['classifications'])
        if not has_physx:
            verifier.deviate(name, 'obstacle_requires_physx_evidence',
                             'obstacle segment has no event/force evidence '
                             '(geometry overlap is not a PhysX contact)',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='event or force measured',
                             actual=dict(view['classifications']))
    elif role == 'clearance':
        if physical != NO_CONTACT:
            verifier.deviate(name, 'clearance_no_contact_expected',
                             'legal close approach must record NO_CONTACT',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=NO_CONTACT, actual=physical)
        if not view['sensor_available_all']:
            verifier.deviate(name, 'clearance_sensor_unavailable',
                             'NO_CONTACT requires an available sensor; a zero '
                             'reading with an unavailable sensor is UNKNOWN',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='sensor available', actual='unavailable')
        if view['event_true_steps']:
            verifier.deviate(name, 'clearance_unexpected_event',
                             'clearance segment recorded a PhysX contact event',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='no event', actual='event=True')
    elif role == 'geometry':
        if physical != GEOMETRY_OVERLAP_ONLY:
            verifier.deviate(name, 'geometry_overlap_only_expected',
                             'geometry segment expects GEOMETRY_OVERLAP_ONLY',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=GEOMETRY_OVERLAP_ONLY, actual=physical)
        if not view['geometry_steps']:
            verifier.deviate(name, 'geometry_overlap_missing',
                             'geometry segment has no sphere overlap > 0.02 m',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='overlap > 0.02', actual='none')
        if view['event_true_steps']:
            verifier.deviate(name, 'geometry_must_not_emit_event',
                             'geometry-only evidence must not carry event=True',
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected='event=False',
                             actual='event=True')
        for record in view['records']:
            force = _record_layers(record).get('force')
            event = _record_layers(record).get('event')
            geometry = _record_layers(record).get('geometry')
            if not isinstance(force, dict) or not isinstance(event, dict) \
                    or not isinstance(geometry, dict):
                continue
            if event.get('event') is True:
                continue
            overlap = _fnum(geometry.get('sphere_overlap_m'))
            if overlap is None or overlap <= 0.02:
                continue
            if force.get('available') is not True \
                    or not _close(force.get('magnitude_n'), 0.0, FORCE_TOL_N):
                verifier.deviate(name, 'geometry_requires_valid_zero_force',
                                 'geometry-only step requires a valid zero force '
                                 'reading', run=label,
                                 episode_id=episode_id, case_id=case_id,
                                 expected='force available magnitude 0.0',
                                 actual={'available': force.get('available'),
                                         'magnitude_n': force.get('magnitude_n')})
                break
    verifier.ok_if_clean(name, 'role expectations checked for %s (%s)'
                         % (episode_id, role))


def _must_condition_eval(kind, value, episode, rows, view, inventory):
    physical = canonical_physical(episode.get('physical_outcome'))
    if kind in ('force_measured', 'force_measured_gt_0.02_n'):
        return (view['force_measured_steps'] > 0
                or view['row_force_measured_steps'] > 0,
                'no force-measured (> 0.02 N) step')
    if kind in ('event_or_force', 'event_true_or_force_available'):
        return (view['event_true_steps'] > 0
                or view['force_measured_steps'] > 0
                or view['row_force_measured_steps'] > 0
                or view['force_available_steps'] > 0,
                'no event or force evidence')
    if kind == 'event_true':
        return (view['event_true_steps'] > 0, 'event=True was not recorded')
    if kind == 'event_false':
        return (view['event_true_steps'] == 0, 'event=True recorded')
    if kind == 'sensor_available_true' or kind == 'sensor_available':
        return (view['sensor_available_all']
                and view['event_available_all'],
                'sensor/event channel unavailable on some step')
    if kind == 'force_available':
        return (view['force_available_steps'] > 0,
                'force layer was never available')
    if kind in ('force_valid_zero', 'force_available_with_valid_zero'):
        return (view['force_available_steps'] > 0
                and view['valid_zero_steps'] == view['force_available_steps'],
                'force layer is not a valid explicit zero on every available '
                'step')
    if kind in ('overlap_gt_0.02', 'geometry_overlap_gt_0.02_m'):
        return (view['max_geometry_overlap_m'] > 0.02,
                'episode max sphere overlap %.6f is not > 0.02 m'
                % view['max_geometry_overlap_m'])
    if kind == 'geometry_overlap_le_0.02_m':
        return (view['min_geometry_overlap_m'] <= 0.02 + 1e-12,
                'episode min sphere overlap %.6f is not <= 0.02 m'
                % view['min_geometry_overlap_m'])
    if kind == 'not_geometry_only':
        return (physical != GEOMETRY_OVERLAP_ONLY,
                'physical outcome is geometry-only')
    if kind == 'not_physx_force':
        return (view['event_true_steps'] == 0
                and view['force_measured_steps'] == 0
                and view['row_force_measured_steps'] == 0,
                'PhysX event/force evidence is present')
    if kind == 'attribution_prim_in':
        expected = value if isinstance(value, str) else None
        if not expected:
            return (False, 'attribution_prim_in needs a string value')
        hit = any(path == expected or expected in path or path in expected
                  for path in view['attribution_paths'])
        return (hit, 'attribution prim %r not in attribution.prim_paths %s'
                % (expected, sorted(view['attribution_paths'])))
    if kind == 'attribution_attributed':
        return (view['attributed_steps'] > 0, 'no ATTRIBUTED step')
    if kind == 'attribution_within_inventory':
        outside = [path for path in view['attribution_paths']
                   if path not in inventory['all']]
        return (not outside and bool(view['attribution_paths']),
                'attribution prims outside inventory: %s' % outside
                if outside else 'no attributed prim paths')
    if kind == 'no_contact':
        return (physical == NO_CONTACT, 'physical outcome %s' % physical)
    if kind == 'physical_outcome_in':
        canonical = [canonical_physical(item) for item in value] \
            if isinstance(value, list) else [canonical_physical(value)]
        return (physical in canonical, 'physical outcome %s not in %s'
                % (physical, canonical))
    if kind in ('replay_verdict_recorded',
                'replay_basis_from_raw_contact_record'):
        replay = episode.get('replay') if isinstance(episode.get('replay'),
                                                     dict) else {}
        keys = ('verdict', 'replay_verdict', 'reviewed_verdict') \
            if kind == 'replay_verdict_recorded' \
            else ('basis', 'replay_basis', 'review_basis')
        for source in (replay, episode):
            for key in keys:
                text = source.get(key)
                if isinstance(text, str) and text.strip():
                    return (True, 'recorded %s' % key)
            verdict_keys = ('verdict', 'replay_verdict')
            for key in verdict_keys:
                text = source.get(key)
                if isinstance(text, str) and text.strip():
                    return (True, 'recorded %s' % key)
        return (False, 'no non-empty %s field recorded in the replay episode'
                % '/'.join(keys))
    return None


def check_scenario(evidence, episode, spec, rows, expected_index, verifier,
                   analysis):
    label = evidence.segment_id
    episode_id = episode.get('episode_id')
    case_id = episode.get('case_id')
    role = evidence.manifest.get('role') \
        if isinstance(evidence.manifest, dict) else None
    if spec is None:
        verifier.missing.add(label, 'expected classification for case %s'
                             % case_id, 'episode %s' % episode_id)
        verifier.ok_if_clean('expected_config_coverage',
                             'no expected entry for %s' % case_id)
        for name in ('acceptable_physical_outcomes', 'must_conditions',
                     'segment_role_expectations', 'replay_verdicts'):
            verifier.ok_if_clean(name, 'not applicable (missing expected)')
        return
    verifier.ok_if_clean('expected_config_coverage',
                         'expected classification present for %s' % case_id)
    acceptable = _acceptable_outcomes(spec)
    physical = canonical_physical(episode.get('physical_outcome'))
    if not acceptable:
        verifier.missing.add(label, 'expected.acceptable_physical for '
                             'case %s' % case_id, 'episode %s' % episode_id)
    else:
        if physical not in acceptable:
            verifier.deviate('acceptable_physical_outcomes',
                             'physical_outcome_not_acceptable',
                             'recorded physical outcome is not in the pre-frozen '
                             'acceptable set', run=label, episode_id=episode_id,
                             case_id=case_id, expected=acceptable,
                             actual=physical)
    unsupported_allowed = spec.get('unsupported_allowed')
    if unsupported_allowed is not True:
        if physical == UNKNOWN:
            verifier.deviate('acceptable_physical_outcomes',
                             'unknown_not_allowed',
                             'UNKNOWN physical outcome appeared where '
                             'unsupported_allowed is false', run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected='not UNKNOWN', actual=physical)
        elif analysis.get('view') and (analysis['view'].get('unknown_steps')
                                       or not analysis['view'].get(
                                           'sensor_available_all', True)):
            verifier.deviate('acceptable_physical_outcomes',
                             'unknown_step_not_allowed',
                             'UNKNOWN/sensor-unavailable steps appeared where '
                             'unsupported_allowed is false', run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected='sensor available on every step',
                             actual=sorted(analysis['view'].get(
                                 'classifications', {})))
    conditions = spec.get('must_conditions') or []
    if not isinstance(conditions, list):
        verifier.missing.add(label, 'expected.must_conditions for case %s'
                             % case_id, 'episode %s' % episode_id)
        conditions = []
    view = analysis.get('view') or _step_contact_view(rows)
    inventory = analysis.get('inventory') or _inventory_paths(evidence.manifest)
    for condition in conditions:
        kind, value = _parse_condition(condition)
        if kind is None or kind not in MUST_CONDITION_KINDS:
            verifier.missing.add(label, 'supported expected.must_conditions kind '
                                 'for case %s' % case_id,
                                 'episode %s (%r)' % (episode_id, kind))
            continue
        outcome = _must_condition_eval(kind, value, episode, rows, view,
                                       inventory)
        if outcome is None:
            verifier.missing.add(label, 'evaluable must_condition %s' % kind,
                                 episode_id)
            continue
        passed, detail = outcome
        if not passed:
            verifier.deviate('must_conditions', 'must_condition_failed',
                             'must condition %r failed: %s' % (kind, detail),
                             run=label, episode_id=episode_id, case_id=case_id,
                             expected=condition, actual=detail)
    # built-in role rules
    _role_expectation(evidence, episode, spec, rows, verifier, analysis)
    # replay verdicts
    if role == 'replay':
        verdict, verdict_detail = _derive_replay_verdict(episode, view)
        analysis['replay_verdict'] = verdict
        allowed = spec.get('replay_allowed')
        if not allowed:
            expected_verdict = spec.get('replay_verdict') \
                or spec.get('expected_verdict') or spec.get('verdict')
            allowed = [expected_verdict] if expected_verdict else None
        allowed = [str(item) for item in allowed] if isinstance(allowed, list) \
            else None
        rule = spec.get('replay_rule')
        replay = episode.get('replay') if isinstance(episode.get('replay'),
                                                     dict) else {}
        declared_previous = spec.get('replay_previous_label')
        recorded_previous = replay.get('previous_physical_label')
        if declared_previous is not None and recorded_previous is not None \
                and canonical_physical(declared_previous) \
                != canonical_physical(recorded_previous):
            verifier.deviate(
                'replay_verdicts', 'replay_previous_label_mismatch',
                'episode replay.previous_physical_label does not match the '
                'pre-frozen replay_verdicts declaration', run=label,
                episode_id=episode_id, case_id=case_id,
                expected=declared_previous, actual=recorded_previous)
        if rule:
            verifier.note('replay_verdicts',
                          'replay rule for %s (INFO): %s' % (case_id, rule))
        if not allowed:
            verifier.missing.add(label, 'expected.replay_verdicts for case %s'
                                 % case_id, 'episode %s' % episode_id)
        elif verdict not in allowed:
            verifier.deviate('replay_verdicts', 'replay_verdict_mismatch',
                             'derived replay verdict %s is not in the '
                             'pre-frozen allowed set %s'
                             % (verdict, allowed), run=label,
                             episode_id=episode_id, case_id=case_id,
                             expected=allowed, actual=verdict,
                             context={'basis': verdict_detail})
        else:
            verifier.ok_if_clean('replay_verdicts',
                                 'replay verdict %s ok for %s (%s)'
                                 % (verdict, episode_id, verdict_detail))
    else:
        verifier.ok_if_clean('replay_verdicts',
                             'not a replay episode (%s)' % episode_id)
    for name in ('acceptable_physical_outcomes', 'must_conditions'):
        verifier.ok_if_clean(name, 'checked for %s' % episode_id)


def _derive_replay_verdict(episode, view):
    replay = episode.get('replay') if isinstance(episode.get('replay'),
                                                 dict) else {}
    previous = canonical_physical(replay.get('previous_physical_label'))
    current = canonical_physical(episode.get('physical_outcome'))
    if not previous or previous == UNKNOWN or current == UNKNOWN \
            or not view.get('sensor_available_all', True):
        return 'UNDECIDABLE', ('unknown sensor/previous label; current=%s '
                               'previous=%s' % (current, previous))
    contact_prev = previous in CONTACT_OUTCOMES
    contact_cur = current in CONTACT_OUTCOMES
    if previous == current:
        return 'CONSISTENT', 'labels equal (%s)' % current
    if previous == NO_CONTACT and contact_cur:
        return 'MISREPORT', 'previous NO_CONTACT but current evidence is %s' \
            % current
    if contact_prev and current == NO_CONTACT:
        return 'MISS', 'previous %s but current evidence is valid NO_CONTACT' \
            % previous
    if contact_prev and current == GEOMETRY_OVERLAP_ONLY:
        return 'MISS', 'previous %s but current evidence is geometry-only' \
            % previous
    if previous == GEOMETRY_OVERLAP_ONLY and contact_cur:
        return 'MISREPORT', 'previous geometry-only but current evidence is %s' \
            % current
    if previous == GEOMETRY_OVERLAP_ONLY and current == NO_CONTACT:
        return 'CONSISTENT', 'both labels are non-contact (%s/%s)' \
            % (previous, current)
    return 'UNDECIDABLE', 'no deterministic comparison for %s/%s' \
        % (previous, current)


# ---------------------------------------------------------------------------
# performance aggregation
# ---------------------------------------------------------------------------

def _segment_performance(analyses):
    episodes = []
    classification_counts = Counter()
    physical_counts = Counter()
    total_event_steps = 0
    total_unknown_steps = 0
    total_geometry_steps = 0
    total_valid_zero_steps = 0
    total_force_steps = 0
    total_attributed = 0
    max_force = None
    max_impulse = None
    event_duration = 0
    for analysis in analyses:
        view = analysis.get('view') or {}
        rows = analysis.get('rows') or []
        physical = analysis.get('physical_outcome')
        physical_counts[str(physical)] += 1
        classification_counts.update(view.get('classifications') or {})
        total_event_steps += view['event_true_steps']
        total_unknown_steps += view['unknown_steps']
        total_geometry_steps += view['geometry_steps']
        total_valid_zero_steps += view['valid_zero_steps']
        total_force_steps += view['force_measured_steps']
        total_attributed += view['attributed_steps']
        max_force = _max_numeric(max_force, analysis.get('max_force_n'))
        max_impulse = _max_numeric(max_impulse, analysis.get('max_impulse_ns'))
        event_duration = max(event_duration,
                             _longest_event_run(analysis.get('records') or []))
        episodes.append({
            'episode_id': analysis.get('episode_id'),
            'case_id': analysis.get('case_id'),
            'role': analysis.get('role'),
            'physical_outcome': physical,
            'contact_steps': view['event_true_steps'],
            'force_measured_steps': view['force_measured_steps'],
            'unknown_steps': view['unknown_steps'],
            'geometry_only_steps': view['geometry_steps'],
            'valid_zero_steps': view['valid_zero_steps'],
            'attributed_steps': view['attributed_steps'],
            'max_force_n': analysis.get('max_force_n'),
            'max_impulse_ns': analysis.get('max_impulse_ns'),
            'event_duration_steps': _longest_event_run(
                analysis.get('records') or []),
            'replay_verdict': analysis.get('replay_verdict'),
        })
    total_steps = sum(len(analysis.get('records') or [])
                      for analysis in analyses)
    return {
        'episodes': episodes,
        'physical_outcome_counts': dict(physical_counts),
        'classification_counts': dict(classification_counts),
        'total_steps': total_steps,
        'contact_event_steps': total_event_steps,
        'unknown_steps': total_unknown_steps,
        'geometry_only_steps': total_geometry_steps,
        'valid_zero_steps': total_valid_zero_steps,
        'force_measured_steps': total_force_steps,
        'attributed_steps': total_attributed,
        'attribution_ratio': (total_attributed / total_steps)
        if total_steps else None,
        'max_force_n': max_force,
        'max_impulse_ns': max_impulse,
        'max_event_duration_steps': event_duration,
    }


def _max_numeric(current, value):
    if not _num(value):
        return current
    if current is None or value > current:
        return float(value)
    return current


def _longest_event_run(records):
    longest = 0
    current = 0
    for record in records:
        layers = _record_layers(record)
        event = layers.get('event') if isinstance(layers.get('event'),
                                                  dict) else {}
        if event.get('event') is True:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


# ---------------------------------------------------------------------------
# episode analysis
# ---------------------------------------------------------------------------

def analyze_episode(evidence, episode, expected_index, verifier):
    rows = _steps(evidence, episode)
    manifest = evidence.manifest if isinstance(evidence.manifest, dict) else {}
    analysis = {
        'episode_id': episode.get('episode_id'),
        'case_id': episode.get('case_id'),
        'role': manifest.get('role'),
        'rows': rows,
        'physical_outcome': canonical_physical(episode.get('physical_outcome')),
        'max_force_n': None,
        'max_impulse_ns': None,
    }
    check_contact_contract(evidence, episode, rows, verifier, analysis)
    view = analysis.get('view') or _step_contact_view(rows)
    analysis['view'] = view
    records = analysis.get('records') or []
    for record in records:
        layers = _record_layers(record)
        force = layers.get('force') if isinstance(layers.get('force'),
                                                  dict) else {}
        impulse = layers.get('impulse') if isinstance(layers.get('impulse'),
                                                      dict) else {}
        if force.get('available') is True:
            analysis['max_force_n'] = _max_numeric(analysis['max_force_n'],
                                                   force.get('magnitude_n'))
        if impulse.get('available') is True:
            analysis['max_impulse_ns'] = _max_numeric(
                analysis['max_impulse_ns'], impulse.get('magnitude_ns'))
    spec = expected_index.lookup(evidence.segment_id, episode.get('case_id'))
    check_scenario(evidence, episode, spec, rows, expected_index, verifier,
                   analysis)
    return analysis


# ---------------------------------------------------------------------------
# top-level orchestration
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description='Independent verification of contact-evidence / envelope '
                    'evaluation runs.')
    parser.add_argument('--freeze', type=Path, default=None,
                        help='pre-run contact verification freeze json')
    parser.add_argument('--run', action='append', default=[],
                        metavar='SEGMENT=DIR',
                        help='segment run directory (repeatable)')
    parser.add_argument('--expected', type=Path, default=None,
                        help='pre-frozen expected classification config')
    parser.add_argument('--repo-root', type=Path, default=Path('.'),
                        help='repository root for relative paths (default: .)')
    parser.add_argument('--output', type=Path, default=None,
                        help='write the verification JSON here')
    return parser


def _parse_run_spec(spec, parser):
    if '=' not in spec:
        parser.error('expected SEGMENT=DIR, got: ' + spec)
    segment_id, run_dir = spec.split('=', 1)
    if not segment_id.strip() or not run_dir.strip():
        parser.error('expected SEGMENT=DIR, got: ' + spec)
    return segment_id.strip(), run_dir.strip()


def run_verification(args, parser=None):
    verifier = Verifier()
    freeze_path = args.freeze
    freeze = _load_freeze(freeze_path, verifier)
    segments = _freeze_segments(freeze) if isinstance(freeze, dict) else {}
    expected_payload = _load_expected(args.expected, verifier)
    expected_index = ExpectedIndex()
    expected_index.add_payload(expected_payload)
    if isinstance(expected_payload, dict):
        schema = expected_payload.get('schema_version')
        if schema is not None and schema != CONTACT_EXPECTED_SCHEMA:
            verifier.fail('expected_config_coverage',
                          'expected config schema_version mismatch',
                          run='expected', field='schema_version',
                          expected=CONTACT_EXPECTED_SCHEMA, actual=schema)
        status = expected_payload.get('status')
        if status is not None and status != 'EXPECTED_NOT_CONCLUSION':
            verifier.fail('expected_config_coverage',
                          'expected config must be marked '
                          'EXPECTED_NOT_CONCLUSION', run='expected',
                          field='status', expected='EXPECTED_NOT_CONCLUSION',
                          actual=status)
        if not (expected_payload.get('cases')
                or expected_payload.get('segments')):
            verifier.missing.add('expected', 'cases/segments', 'expected config')
    if isinstance(freeze, dict):
        for segment_id, entry in segments.items():
            expected = entry.get('expected')
            if isinstance(expected, dict):
                expected_index.add_freeze_segment_expected(segment_id, expected)
        if not freeze.get('expected_file') and not freeze.get(
                'expected_sha256') and expected_payload is None:
            verifier.missing.add('freeze', 'expected_file/expected_sha256',
                                 'freeze')
    runs = {}
    for spec in args.run or []:
        segment_id, run_dir = _parse_run_spec(spec, parser)
        runs[segment_id] = load_run(segment_id, run_dir, verifier)
    if not runs:
        verifier.missing.add('verify', 'no run directories provided', 'cli')
    if isinstance(freeze, dict):
        for segment_id, entry in segments.items():
            if segment_id not in runs:
                verifier.missing.add('freeze', 'run directory for segment %s'
                                     % segment_id, segment_id)
    for segment_id, evidence in runs.items():
        if segment_id not in segments and isinstance(freeze, dict):
            verifier.fail('freeze_lineage', 'run segment is not declared in the '
                          'freeze', run=segment_id, field='segment_id',
                          expected=sorted(segments), actual=segment_id)
    # Schema completeness per run.
    for segment_id, evidence in runs.items():
        if not evidence.loaded:
            continue
        verify_manifest_schema(evidence, verifier)
        verify_episode_schema(evidence, verifier)
        verify_step_schema(evidence, verifier)
        check_freeze(evidence, freeze, Path(freeze_path)
                     if freeze_path else None,
                     Path(args.expected) if args.expected else None, verifier,
                     repo_root=args.repo_root)
        check_gui(evidence, verifier)
        check_episode_identity(evidence, freeze, verifier)
        check_step_timing(evidence, verifier)
        check_episode_boundary(evidence, verifier)
        check_artifacts(evidence, verifier)
        check_envelope(evidence, verifier, repo_root=args.repo_root)
        verifier.ok_if_clean('schema_completeness',
                             'raw schema complete for ' + segment_id)
    analyses = {}
    for segment_id, evidence in runs.items():
        if not evidence.loaded:
            continue
        segment_analyses = []
        for episode in evidence.episodes:
            if not isinstance(episode, dict):
                continue
            segment_analyses.append(analyze_episode(evidence, episode,
                                                    expected_index, verifier))
        analyses[segment_id] = segment_analyses
        role = evidence.manifest.get('role') if isinstance(
            evidence.manifest, dict) else None
        verifier.ok_if_clean('expected_config_coverage',
                             'expected coverage checked for %s' % segment_id)
        verifier.ok_if_clean('envelope_radius_recompute',
                             'envelope checked for ' + segment_id)
        verifier.ok_if_clean('envelope_coverage_inventory',
                             'coverage checked for ' + segment_id)
        verifier.ok_if_clean('envelope_limitations',
                             'limitations checked for ' + segment_id)
        verifier.ok_if_clean('replay_verdicts',
                             'replay verdicts checked for %s (role=%s)'
                             % (segment_id, role))
    # performance
    performance = {}
    for segment_id, segment_analyses in analyses.items():
        stats = _segment_performance(segment_analyses)
        performance[segment_id] = stats
        verifier.ok('contact_event_stats', '%s: %d event steps, %d physical '
                    'outcomes' % (segment_id, stats['contact_event_steps'],
                                  len(stats['episodes'])))
        verifier.ok('force_impulse_extremes', '%s: max force=%s N, max impulse=%s '
                    'N*s' % (segment_id, stats['max_force_n'],
                             stats['max_impulse_ns']))
        verifier.ok('attribution_coverage', '%s: %d/%d attributed steps'
                    % (segment_id, stats['attributed_steps'],
                       stats['total_steps']))
        verifier.ok('geometry_only_and_unknown_stats',
                    '%s: geometry-only=%d, unknown=%d, valid-zero=%d'
                    % (segment_id, stats['geometry_only_steps'],
                       stats['unknown_steps'], stats['valid_zero_steps']))
    for name in ('contact_event_stats', 'force_impulse_extremes',
                 'attribution_coverage', 'geometry_only_and_unknown_stats'):
        verifier.ok_if_clean(name, 'performance stats aggregated')
    # segments summary + lineage
    segment_summary = {}
    for segment_id, evidence in runs.items():
        segment_summary[segment_id] = {
            'role': evidence.manifest.get('role'),
            'episode_count': len(evidence.episodes),
            'case_ids': [str(episode.get('case_id'))
                         for episode in evidence.episodes
                         if isinstance(episode, dict)],
            'run_dir': str(evidence.run_dir),
            'performance': performance.get(segment_id),
        }
    freeze_info = {
        'path': str(freeze_path) if freeze_path else None,
        'sha256': _sha256_file(freeze_path)
        if freeze_path and Path(freeze_path).is_file() else None,
        'schema_version': freeze.get('schema_version')
        if isinstance(freeze, dict) else None,
        'status': freeze.get('status') if isinstance(freeze, dict) else None,
        'frozen_at': freeze.get('frozen_at') if isinstance(freeze, dict)
        else None,
        'code_commit': freeze.get('code_commit') if isinstance(freeze, dict)
        else None,
        'expected_file': freeze.get('expected_file')
        if isinstance(freeze, dict) else None,
        'expected_sha256': freeze.get('expected_sha256')
        if isinstance(freeze, dict) else None,
        'cases_file': freeze.get('cases_file') if isinstance(freeze, dict)
        else None,
        'cases_sha256': freeze.get('cases_sha256') if isinstance(freeze, dict)
        else None,
        'segments': {segment_id: {'role': entry.get('role'),
                                  'case_ids': entry.get('case_ids')
                                  or (_segment_run_plan(entry) or {}).get(
                                      'case_ids', [])}
                     for segment_id, entry in segments.items()},
        'expected_path': str(args.expected) if args.expected else None,
        'expected_file_sha256': _sha256_file(args.expected)
        if args.expected and Path(args.expected).is_file() else None,
    }
    checks = verifier.finalize()
    if verifier.missing:
        status = 'INCOMPLETE'
        checks['data_integrity']['schema_completeness']['passed'] = False
        checks['data_integrity']['schema_completeness']['detail'] = (
            'missing raw fields/incomplete data: %d entries; %s'
            % (verifier.missing.count(),
               checks['data_integrity']['schema_completeness']['detail']))
    elif verifier.failures or verifier.deviations:
        status = 'FAIL'
    else:
        status = 'PASS'
    result = {
        'status': status,
        'checks': checks,
        'checks_by_category': checks,
        'failures': _jsonable(verifier.failures),
        'deviations': _jsonable(verifier.deviations),
        'missing_fields': verifier.missing.as_list(),
        'recomputed': {
            'contracts': {
                'contact': contact_contract.CONTACT_EVIDENCE_SCHEMA_ID,
                'envelope': body_envelope.BODY_ENVELOPE_SCHEMA_VERSION,
                'force_threshold_n':
                    contact_contract.CONTACT_FORCE_THRESHOLD_N,
                'physical_outcomes': list(PHYSICAL_OUTCOMES),
            },
            'expected_index': expected_index.summary(),
            'performance': performance,
            'segments': {
                segment_id: {
                    'role': evidence.manifest.get('role'),
                    'episode_count': len(evidence.episodes),
                    'cases': [str(episode.get('case_id'))
                              for episode in evidence.episodes
                              if isinstance(episode, dict)],
                    'replay_verdicts': [
                        analysis.get('replay_verdict')
                        for analysis in analyses.get(segment_id, [])],
                }
                for segment_id, evidence in runs.items()},
        },
        'segments': segment_summary,
        'lineage': freeze_info,
        'run_dirs': {segment_id: str(evidence.run_dir)
                     for segment_id, evidence in runs.items()},
    }
    return result


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_verification(args, parser)
    text = json.dumps(_jsonable(result), indent=2, ensure_ascii=False)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    return {'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
