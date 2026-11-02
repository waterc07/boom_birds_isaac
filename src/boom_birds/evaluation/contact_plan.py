"""Contact-evidence / body-envelope verification pre-run freeze contract.

Implements the pre-run freeze for the ``codex/bb22-contact-envelope`` work
package (pure standard library, no simulator dependency).  The freeze is one
JSON file with six fixed segments:

===============================  =========  =====================  =========
segment_id                       role       mode                   episodes
===============================  =========  =====================  =========
``contact_A_wall``               wall       wall                   2
``contact_B_obstacle``           obstacle   obstacle               2
``contact_C_clearance``          clearance  clearance              2
``contact_D_geometry``           geometry   geometry               2
``replay_contact_inferred``      replay     replay                 2
``replay_no_contact``            replay     replay                 1
===============================  =========  =====================  =========

Total boundary evidence: **11 episodes** (4 segments x 2 + 2 + 1).

Contracts frozen here
---------------------
* ``boom_birds.contact_evidence.v2`` (``contact_contract.py``) -- the layered
  PhysX/geometry contact record; the freeze never re-implements its rules.
* ``boom_birds.body_envelope.v2`` (``sim/body_envelope.py``) -- the around-origin
  envelope; the freeze only records the contract version and the measured
  envelope source in ``support_scope``.

What the freeze records
-----------------------
* real UTC ``frozen_at`` (microseconds, timezone aware), actual
  ``git rev-parse HEAD`` and ``git status --porcelain -- src scripts tests
  configs`` digest (same normalization as the previous work packages);
* the RMUC2027 map identity (terrain/preview/map-config hashes) read from the
  map contract;
* the cases file hash and, per segment, the normalized run plan: role, mode,
  sorted unique ``case_ids``, contract versions, vehicle/map config hashes and
  ``run_params`` -- the JSON-comparable normalized copy of that segment's
  case parameters (robot/control/obstacle/map-wall targets) or, for replay
  segments, the frozen ``replay_params`` (identical to the previous
  ``boundary_default`` parameters) plus the referenced previous run evidence;
* the expected file hash and the embedded expected classification per case;
* the episode budget (11 episodes) and the support scope (simulation-only
  evidence; PhysX contact is not a real sensor; geometry inference is never a
  contact; envelope is not a mesh sweep).

Replay segments reference previous evidence by path string only
(``previous_run_dir`` / ``previous_episode_id``); the freeze checks that the
directory exists but never reads its contents.

``validate_run_plan`` compares the normalized JSON of the frozen run plan with
the runner's actual plan field by field (hashes included) and raises
``ContactPlanError(RuntimeError)`` on any difference.
``check_freeze_lineage`` rejects a freeze whose ``frozen_at`` is in the future,
whose ``code_commit`` differs from the current HEAD, or whose
``worktree_state`` digest differs from the current working tree.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

CONTACT_FREEZE_SCHEMA = 'boom_birds.contact_verification_freeze.v1'
CONTACT_CASES_SCHEMA = 'boom_birds.contact_verification_cases.v1'
CONTACT_EXPECTED_SCHEMA = 'boom_birds.contact_verification_expected.v1'
CONTACT_MANIFEST_SCHEMA = 'boom_birds.contact_verification_manifest.v1'
CONTACT_CONTRACT_VERSION = 'boom_birds.contact_evidence.v2'
ENVELOPE_CONTRACT_VERSION = 'boom_birds.body_envelope.v2'
FREEZE_STATUS = 'PRE_RUN_FROZEN'
EXPECTED_STATUS = 'EXPECTED_NOT_CONCLUSION'

ROLE_WALL = 'wall'
ROLE_OBSTACLE = 'obstacle'
ROLE_CLEARANCE = 'clearance'
ROLE_GEOMETRY = 'geometry'
ROLE_REPLAY = 'replay'
ROLES = (ROLE_WALL, ROLE_OBSTACLE, ROLE_CLEARANCE, ROLE_GEOMETRY, ROLE_REPLAY)
MODES = ROLES

# segment_id -> (role, mode, expected episodes); order is the freeze JSON order.
SEGMENT_TABLE = {
    'contact_A_wall': (ROLE_WALL, ROLE_WALL, 2),
    'contact_B_obstacle': (ROLE_OBSTACLE, ROLE_OBSTACLE, 2),
    'contact_C_clearance': (ROLE_CLEARANCE, ROLE_CLEARANCE, 2),
    'contact_D_geometry': (ROLE_GEOMETRY, ROLE_GEOMETRY, 2),
    'replay_contact_inferred': (ROLE_REPLAY, ROLE_REPLAY, 2),
    'replay_no_contact': (ROLE_REPLAY, ROLE_REPLAY, 1),
}
SEGMENT_IDS = tuple(SEGMENT_TABLE)
REPLAY_SEGMENT_IDS = tuple(
    segment_id for segment_id, (role, _mode, _count) in SEGMENT_TABLE.items()
    if role == ROLE_REPLAY)
MIN_EPISODES_REQUIRED = 11

DEFAULT_VEHICLE_CONFIG = 'configs/vehicles/sim_reference.yaml'
DEFAULT_MAP_CONFIG = 'configs/maps/rmuc2027.yaml'
DEFAULT_LOCAL_CONFIG = 'configs/maps/rmuc2027.local.yaml'
DEFAULT_OUTPUT = 'configs/scenarios/contact_verification_freeze_v1.json'

RUN_PLAN_FIELDS = (
    'segment_id',
    'role',
    'mode',
    'cases_file',
    'cases_sha256',
    'case_ids',
    'expected_file',
    'expected_sha256',
    'contact_contract_version',
    'envelope_contract_version',
    'vehicle_config',
    'vehicle_config_sha256',
    'map_config',
    'map_config_sha256',
    'run_params',
)

# Physical outcomes of the contact-evidence contract (contact_contract_divisions).
PHYSICAL_OUTCOMES = (
    'PHYSX_CONTACT_FORCE_MEASURED',
    'CONTACT_FORCE_MEASURED_UNATTRIBUTED',
    'PHYSX_CONTACT_EVENT_ONLY',
    'GEOMETRY_OVERLAP_ONLY',
    'NO_CONTACT',
    'UNKNOWN',
)
# Expected must_conditions kinds the independent verifier evaluates.
MUST_CONDITION_KINDS = (
    'force_measured',
    'event_or_force',
    'attribution_attributed',
    'attribution_within_inventory',
    'no_contact',
    'sensor_available',
    'event_false',
    'force_valid_zero',
    'overlap_gt_0.02',
    'not_geometry_only',
    'physical_outcome_in',
)
_NO_VALUE_CONDITION_KINDS = frozenset({
    'force_measured',
    'event_or_force',
    'attribution_attributed',
    'attribution_within_inventory',
    'no_contact',
    'sensor_available',
    'event_false',
    'force_valid_zero',
    'overlap_gt_0.02',
    'not_geometry_only',
})
_OUTCOME_LIST_CONDITION_KINDS = frozenset({'physical_outcome_in'})
REPLAY_VERDICTS = ('CONSISTENT', 'MISREPORT', 'MISS', 'UNDECIDABLE')
PREVIOUS_PHYSICAL_LABELS = ('CONTACT_INFERRED', 'NO_CONTACT')

# Replay segments must reuse the previous ``boundary_default`` runtime parameters
# (Lead 2026-11-02 contract).  Field names match the runner CLI; the last three
# are the runner-level configuration carried by the same ``replay_params`` block.
REPLAY_PARAM_FIELDS = (
    'vehicle_config',
    'methods',
    'execution_path',
    'obs_delay_s',
    'action_delay_s',
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'stop_distance_m',
    'post_abort_observe_s',
    'clock_offset_ms',
    'clock_drift_ppm',
    'clock_uncertainty_ms',
    'sync_fail_step',
    'obs_mapping_fail_step',
    'transport_stall_step',
    'transport_stall_delay_s',
    'obstacle_time_clamp',
)
REPLAY_PARAMS_BOUNDARY_DEFAULT = {
    'vehicle_config': DEFAULT_VEHICLE_CONFIG,
    'methods': ['supervisor'],
    'execution_path': 'v2',
    'obs_delay_s': 0.15,
    'action_delay_s': 0.10,
    'ttl_ms': 150,
    'max_age_ms': 150,
    'allowed_observation_age_ms': 300,
    'stop_distance_m': 1.1,
    'post_abort_observe_s': 3.0,
    'clock_offset_ms': 20.0,
    'clock_drift_ppm': 200.0,
    'clock_uncertainty_ms': 5.0,
    'sync_fail_step': -1,
    'obs_mapping_fail_step': -1,
    'transport_stall_step': -1,
    'transport_stall_delay_s': 0.15,
    'obstacle_time_clamp': True,
}
_METHODS = ('supervisor', 'follow_only')
_EXECUTION_PATHS = ('v1', 'v2')
REPLAY_PARAM_FLOAT_FIELDS = frozenset({
    'obs_delay_s',
    'action_delay_s',
    'stop_distance_m',
    'post_abort_observe_s',
    'clock_offset_ms',
    'clock_drift_ppm',
    'clock_uncertainty_ms',
    'transport_stall_delay_s',
})
REPLAY_PARAM_INT_FIELDS = frozenset({
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'sync_fail_step',
    'obs_mapping_fail_step',
    'transport_stall_step',
})
_NON_NEGATIVE_REPLAY_FIELDS = frozenset({
    'obs_delay_s',
    'action_delay_s',
    'post_abort_observe_s',
    'clock_uncertainty_ms',
    'transport_stall_delay_s',
})
_POSITIVE_REPLAY_FIELDS = frozenset({
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'stop_distance_m',
})
_STEP_REPLAY_FIELDS = frozenset({
    'sync_fail_step',
    'obs_mapping_fail_step',
    'transport_stall_step',
})

TRACKED_PATHS = ('src', 'scripts', 'tests', 'configs')
_SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_COMMIT_PATTERN = re.compile(r'^[0-9a-f]{7,64}$')

_SUPPORT_SCOPE_REQUIRED_KEYS = (
    'scope',
    'evidence_domain',
    'contact_contract_version',
    'envelope_contract_version',
    'contact_sensor_model',
    'simulation_models',
    'limitations',
)
EXPECTED_REQUIRED_KEYS = ('acceptable_physical_outcomes',)


class ContactPlanError(RuntimeError):
    """Freeze/plan/expected violates the contact-verification contract."""


# ---------------------------------------------------------------------------
# small typed normalizers
# ---------------------------------------------------------------------------

def _fail(code, message):
    raise ContactPlanError(code + ': ' + message)


def _as_float(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field.upper() + '_INVALID', '必须是数字，得到 ' + repr(value))
    number = float(value)
    if not math.isfinite(number):
        _fail(field.upper() + '_INVALID', '必须是有限数，得到 ' + repr(value))
    return round(number, 6)


def _as_int(value, field):
    if isinstance(value, bool):
        _fail(field.upper() + '_INVALID', '必须是整数，得到 ' + repr(value))
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    _fail(field.upper() + '_INVALID', '必须是整数，得到 ' + repr(value))


def _as_bool(value, field):
    if not isinstance(value, bool):
        _fail(field.upper() + '_INVALID', '必须是布尔，得到 ' + repr(value))
    return value


def _as_text(value, field):
    if not isinstance(value, str):
        _fail(field.upper() + '_INVALID', '必须是字符串，得到 ' + repr(value))
    return value


def _as_non_empty_text(value, field):
    text = _as_text(value, field).strip()
    if not text:
        _fail(field.upper() + '_INVALID', '不能为空')
    return text


def _as_sha256(value, field):
    text = _as_text(value, field).strip().lower()
    if not _SHA256_PATTERN.match(text):
        _fail('HASH_INVALID', field + ' 必须是 64 位小写十六进制')
    return text


def _as_path_text(value, field):
    text = _as_text(value, field).strip()
    if not text:
        _fail(field.upper() + '_INVALID', '不能为空')
    return Path(text).as_posix()


def _as_yaml_path(value, field):
    path = _as_path_text(value, field)
    if not path.lower().endswith(('.yaml', '.yml')):
        _fail(field.upper() + '_INVALID', '必须是 yaml 路径，得到 ' + repr(path))
    return path


def _as_vector3(value, field, *, positive=False):
    if isinstance(value, (str, bytes)):
        _fail(field.upper() + '_INVALID', '必须是三元向量')
    try:
        items = list(value)
    except TypeError:
        _fail(field.upper() + '_INVALID', '必须是三元向量')
    if len(items) != 3:
        _fail(field.upper() + '_INVALID', '必须恰好 3 个分量')
    numbers = [_as_float(item, field) for item in items]
    if positive and any(number <= 0.0 for number in numbers):
        _fail(field.upper() + '_INVALID', '分量必须为正')
    return numbers


def _as_text_list(value, field, *, allow_empty=False):
    if isinstance(value, (str, bytes)):
        _fail(field.upper() + '_INVALID', '必须是字符串列表')
    try:
        items = list(value)
    except TypeError:
        _fail(field.upper() + '_INVALID', '必须是字符串列表')
    if not items and not allow_empty:
        _fail(field.upper() + '_INVALID', '不能为空')
    result = []
    for item in items:
        result.append(_as_non_empty_text(item, field))
    return result


def _as_outcome_list(value, field, allowed=PHYSICAL_OUTCOMES):
    outcomes = _as_text_list(value, field)
    unknown = [item for item in outcomes if item not in allowed]
    if unknown:
        _fail(field.upper() + '_INVALID',
              '未知类别 ' + ', '.join(unknown) + '（只允许 ' + repr(allowed) + '）')
    if len(set(outcomes)) != len(outcomes):
        _fail(field.upper() + '_DUPLICATE', '类别不得重复')
    return outcomes


def _as_replay_verdict(value, field):
    verdict = _as_text(value, field)
    if verdict not in REPLAY_VERDICTS:
        _fail(field.upper() + '_INVALID',
              '只允许 ' + repr(REPLAY_VERDICTS) + '，得到 ' + repr(verdict))
    return verdict


def _as_previous_label(value, field):
    label = _as_text(value, field)
    if label not in PREVIOUS_PHYSICAL_LABELS:
        _fail(field.upper() + '_INVALID',
              '只允许 ' + repr(PREVIOUS_PHYSICAL_LABELS) + '，得到 ' + repr(label))
    return label


def _parse_aware_iso(value, field):
    text = _as_text(value, field).strip()
    if not text:
        _fail(field.upper() + '_INVALID', '不能为空')
    candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ContactPlanError(
            field.upper() + '_INVALID: 无法解析 ISO 时间 ' + repr(value)) from error
    if parsed.tzinfo is None:
        _fail(field.upper() + '_TIMEZONE_REQUIRED',
              '必须带时区（UTC），得到 ' + repr(value))
    return parsed


def _normalize_replay_params(raw):
    if not isinstance(raw, dict):
        _fail('REPLAY_PARAMS_INVALID', 'replay_params 必须是对象')
    missing = [field for field in REPLAY_PARAM_FIELDS if field not in raw]
    if missing:
        _fail('REPLAY_PARAMS_MISSING', ', '.join(missing))
    unknown = sorted(set(raw) - set(REPLAY_PARAM_FIELDS))
    if unknown:
        _fail('REPLAY_PARAMS_UNKNOWN', ', '.join(unknown))
    normalized = {}
    for field in REPLAY_PARAM_FIELDS:
        if field == 'obstacle_time_clamp':
            normalized[field] = _as_bool(raw[field], 'replay_params.' + field)
            if normalized[field] is not True:
                _fail('REPLAY_PARAMS_INVALID',
                      'obstacle_time_clamp 必须为 true（与上一轮 boundary_default 一致）')
        elif field == 'vehicle_config':
            normalized[field] = _as_yaml_path(raw[field],
                                             'replay_params.' + field)
        elif field == 'methods':
            methods = _as_text_list(raw[field], 'replay_params.' + field)
            unknown_methods = [item for item in methods
                               if item not in _METHODS]
            if unknown_methods:
                _fail('REPLAY_PARAMS_INVALID',
                      '未知 methods: ' + ', '.join(unknown_methods))
            normalized[field] = methods
        elif field == 'execution_path':
            path = _as_text(raw[field], 'replay_params.' + field)
            if path not in _EXECUTION_PATHS:
                _fail('REPLAY_PARAMS_INVALID',
                      'execution_path 只允许 ' + repr(_EXECUTION_PATHS))
            normalized[field] = path
        elif field in REPLAY_PARAM_FLOAT_FIELDS:
            normalized[field] = _as_float(raw[field], 'replay_params.' + field)
        else:
            normalized[field] = _as_int(raw[field], 'replay_params.' + field)
    for field in _NON_NEGATIVE_REPLAY_FIELDS:
        if normalized[field] < 0:
            _fail('REPLAY_PARAMS_NEGATIVE', field + ' 不得为负')
    for field in _POSITIVE_REPLAY_FIELDS:
        if normalized[field] <= 0:
            _fail('REPLAY_PARAMS_INVALID', field + ' 必须为正')
    for field in _STEP_REPLAY_FIELDS:
        if normalized[field] < -1:
            _fail('REPLAY_PARAMS_INVALID', field + ' 必须 >= -1')
    expected = _normalize_replay_params_reference()
    for field in REPLAY_PARAM_FIELDS:
        if normalized[field] != expected[field]:
            _fail('REPLAY_PARAMS_MISMATCH',
                  field + '=' + repr(normalized[field])
                  + ' 与上一轮 boundary_default 的 ' + repr(expected[field])
                  + ' 不一致')
    return normalized


def _normalize_replay_params_reference():
    reference = dict(REPLAY_PARAMS_BOUNDARY_DEFAULT)
    reference['methods'] = list(reference['methods'])
    for field in REPLAY_PARAM_FLOAT_FIELDS:
        reference[field] = round(float(reference[field]), 6)
    return reference


# ---------------------------------------------------------------------------
# cases file normalization
# ---------------------------------------------------------------------------

def _normalize_robot(raw, context):
    if not isinstance(raw, dict):
        _fail('CASE_ROBOT_INVALID', context + '.robot 必须是对象')
    for key in ('start_position_world_m', 'yaw_rad'):
        if key not in raw:
            _fail('CASE_ROBOT_MISSING', context + '.robot.' + key)
    return {
        'start_position_world_m': _as_vector3(
            raw['start_position_world_m'], context + '.robot.start_position_world_m'),
        'yaw_rad': _as_float(raw['yaw_rad'], context + '.robot.yaw_rad'),
    }


def _normalize_control(raw, context):
    if not isinstance(raw, dict):
        _fail('CASE_CONTROL_INVALID', context + '.control 必须是对象')
    for key in ('mode', 'forward_mps', 'max_steps'):
        if key not in raw:
            _fail('CASE_CONTROL_MISSING', context + '.control.' + key)
    mode = _as_text(raw['mode'], context + '.control.mode')
    if mode not in ('hover', 'forward_velocity'):
        _fail('CASE_CONTROL_MODE_INVALID',
              context + '.control.mode 只允许 hover/forward_velocity，得到 ' + repr(mode))
    forward = _as_float(raw['forward_mps'], context + '.control.forward_mps')
    if forward < 0:
        _fail('CASE_CONTROL_INVALID', context + '.control.forward_mps 不得为负')
    steps = _as_int(raw['max_steps'], context + '.control.max_steps')
    if steps < 1:
        _fail('CASE_CONTROL_INVALID', context + '.control.max_steps 必须 >= 1')
    return {'mode': mode, 'forward_mps': forward, 'max_steps': steps}


def _normalize_obstacle(raw, context):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail('CASE_OBSTACLE_INVALID', context + '.obstacle 必须是对象或 null')
    for key in ('size_m', 'start_position_world_m', 'velocity_world_mps'):
        if key not in raw:
            _fail('CASE_OBSTACLE_MISSING', context + '.obstacle.' + key)
    normalized = {
        'size_m': _as_vector3(raw['size_m'], context + '.obstacle.size_m',
                              positive=True),
        'start_position_world_m': _as_vector3(
            raw['start_position_world_m'],
            context + '.obstacle.start_position_world_m'),
        'velocity_world_mps': _as_vector3(
            raw['velocity_world_mps'],
            context + '.obstacle.velocity_world_mps'),
        'kinematic': _as_bool(raw.get('kinematic', True),
                              context + '.obstacle.kinematic'),
    }
    if normalized['kinematic'] is not True:
        _fail('CASE_OBSTACLE_INVALID',
              context + '.obstacle.kinematic 必须为 true（运动学障碍）')
    return normalized


def _normalize_target(raw, context):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail('CASE_TARGET_INVALID', context + '.target 必须是对象或 null')
    for key in ('kind', 'prim_path', 'map_config', 'local_config'):
        if key not in raw:
            _fail('CASE_TARGET_MISSING', context + '.target.' + key)
    kind = _as_text(raw['kind'], context + '.target.kind')
    if kind != 'map_wall':
        _fail('CASE_TARGET_INVALID',
              context + '.target.kind 必须是 map_wall，得到 ' + repr(kind))
    return {
        'kind': kind,
        'prim_path': _as_non_empty_text(
            raw['prim_path'], context + '.target.prim_path'),
        'map_config': _as_yaml_path(
            raw['map_config'], context + '.target.map_config'),
        'local_config': _as_yaml_path(
            raw['local_config'], context + '.target.local_config'),
    }


def _normalize_case(segment_id, role, raw, context):
    if not isinstance(raw, dict):
        _fail('CASE_INVALID', context + ' 必须是对象')
    if role == ROLE_REPLAY:
        return _normalize_replay_case(segment_id, raw, context)
    for key in ('case_id', 'robot', 'control'):
        if key not in raw:
            _fail('CASE_MISSING', context + '.' + key)
    spec = {
        'case_id': _as_non_empty_text(raw['case_id'], context + '.case_id'),
        'robot': _normalize_robot(raw['robot'], context),
        'control': _normalize_control(raw['control'], context),
        'obstacle': _normalize_obstacle(raw.get('obstacle'), context),
        'target': _normalize_target(raw.get('target'), context),
        'expected_physical': _as_outcome_list(
            raw.get('expected_physical', []), context + '.expected_physical')
        if raw.get('expected_physical')
        else [],
    }
    if role == ROLE_WALL:
        if spec['target'] is None:
            _fail('CASE_TARGET_MISSING',
                  context + '（wall 段必须给出 map_wall target）')
        if spec['obstacle'] is not None:
            _fail('CASE_OBSTACLE_UNEXPECTED',
                  context + '（wall 段不应带动态障碍）')
    elif role in (ROLE_OBSTACLE, ROLE_CLEARANCE, ROLE_GEOMETRY):
        if spec['obstacle'] is None and spec['target'] is None:
            _fail('CASE_TARGET_MISSING',
                  context + '（' + role + ' 段必须给出 obstacle 或 map_wall target）')
        if role in (ROLE_OBSTACLE, ROLE_GEOMETRY) and spec['obstacle'] is None:
            _fail('CASE_OBSTACLE_MISSING',
                  context + '（' + role + ' 段必须给出 obstacle）')
    return spec


def _normalize_replay_case(segment_id, raw, context):
    for key in ('case_id', 'source_cases_file', 'previous_run_dir',
                'previous_episode_id', 'previous_physical_label'):
        if key not in raw:
            _fail('REPLAY_CASE_MISSING', context + '.' + key)
    return {
        'case_id': _as_non_empty_text(raw['case_id'], context + '.case_id'),
        'source_cases_file': _as_path_text(
            raw['source_cases_file'], context + '.source_cases_file'),
        'previous_run_dir': _as_path_text(
            raw['previous_run_dir'], context + '.previous_run_dir'),
        'previous_episode_id': _as_non_empty_text(
            raw['previous_episode_id'], context + '.previous_episode_id'),
        'previous_physical_label': _as_previous_label(
            raw['previous_physical_label'],
            context + '.previous_physical_label'),
    }


def _group_case_entries(entries, segment_id, repeats):
    grouped = {}
    for entry, raw_repeat, context in entries:
        case_id = entry['case_id']
        grouped.setdefault(case_id, []).append((entry, raw_repeat, context))
    case_ids = sorted(grouped)
    repeat_indices = {}
    for case_id, items in grouped.items():
        indices = []
        for position, (_entry, raw_repeat, _context) in enumerate(items):
            if raw_repeat is None:
                indices.append(position)
            else:
                indices.append(_as_int(raw_repeat,
                                       segment_id + '.' + case_id + '.repeat'))
        if len(set(indices)) != len(indices):
            _fail('CASE_REPEAT_DUPLICATE',
                  segment_id + ' case_id=' + case_id + ' repeat 索引重复')
        if len(items) > 1:
            base = items[0][0]
            for other, _repeat, _context in items[1:]:
                if other != base:
                    _fail('CASE_REPEAT_SPEC_MISMATCH',
                          segment_id + ' case_id=' + case_id
                          + ' 的多次 repeat 参数必须相同（除 repeat 索引）')
        if len(items) not in (1, repeats):
            _fail('CASE_REPEAT_COUNT_INVALID',
                  segment_id + ' case_id=' + case_id + ' 有 ' + str(len(items))
                  + ' 条记录，segment repeats=' + str(repeats)
                  + '（每 case 必须 1 条模板或 repeats 条显式重复）')
        if len(items) == 1 and repeats > 1 and indices[0] != 0:
            _fail('CASE_REPEAT_COUNT_INVALID',
                  segment_id + ' case_id=' + case_id
                  + ' 单条模板的 repeat 必须为 0')
        repeat_indices[case_id] = sorted(indices)
    return case_ids, repeat_indices


def normalize_cases_payload(payload, *, repo_root=None):
    """Validate a ``boom_birds.contact_verification_cases.v1`` payload.

    Returns ``{'segments': {segment_id: {...}}, 'case_ids': {...}}`` where each
    segment holds the normalized case specs, the declared ``repeats`` and the
    episode count ``len(case_ids) * repeats``.  The fixed segment table (ids,
    roles, modes, episode counts) is enforced here.
    """
    if not isinstance(payload, dict):
        _fail('CASES_INVALID', 'cases 必须是 JSON 对象')
    if payload.get('schema_version') != CONTACT_CASES_SCHEMA:
        _fail('CASES_SCHEMA_MISMATCH',
              '期望 ' + CONTACT_CASES_SCHEMA + '，得到 '
              + repr(payload.get('schema_version')))
    if payload.get('contact_contract_version') != CONTACT_CONTRACT_VERSION:
        _fail('CONTACT_CONTRACT_VERSION_MISMATCH',
              'cases.contact_contract_version 必须是 ' + CONTACT_CONTRACT_VERSION)
    if payload.get('envelope_contract_version') != ENVELOPE_CONTRACT_VERSION:
        _fail('ENVELOPE_CONTRACT_VERSION_MISMATCH',
              'cases.envelope_contract_version 必须是 ' + ENVELOPE_CONTRACT_VERSION)
    raw_segments = payload.get('segments')
    if isinstance(raw_segments, dict):
        segment_nodes = [dict(node, segment_id=segment_id)
                         for segment_id, node in raw_segments.items()
                         if isinstance(node, dict)]
    elif isinstance(raw_segments, list):
        segment_nodes = list(raw_segments)
    else:
        _fail('CASES_SEGMENTS_INVALID', 'cases.segments 必须是列表或对象')
    if len(segment_nodes) != len(SEGMENT_IDS):
        _fail('CASES_SEGMENTS_MISMATCH',
              'cases.segments 必须恰好包含 ' + repr(SEGMENT_IDS)
              + '，得到 ' + repr([node.get('segment_id') for node in segment_nodes]))
    result = {'segments': {}, 'case_ids': {}, 'repeats': {}}
    top_replay_params = None
    if payload.get('replay_params') is not None:
        top_replay_params = _normalize_replay_params(payload['replay_params'])
    for node in segment_nodes:
        if not isinstance(node, dict):
            _fail('CASES_SEGMENTS_INVALID', 'segment 必须是对象')
        segment_id = node.get('segment_id')
        if segment_id not in SEGMENT_TABLE:
            _fail('CASES_SEGMENT_UNKNOWN', '未知 segment_id ' + repr(segment_id))
        role, mode, expected_episodes = SEGMENT_TABLE[segment_id]
        if segment_id in result['segments']:
            _fail('CASES_SEGMENT_DUPLICATE', '重复 segment_id ' + repr(segment_id))
        for key in ('role', 'mode', 'repeats', 'cases'):
            if key not in node:
                _fail('CASES_SEGMENT_MISSING', segment_id + '.' + key)
        node_role = _as_text(node['role'], segment_id + '.role')
        node_mode = _as_text(node['mode'], segment_id + '.mode')
        if node_role != role:
            _fail('CASES_SEGMENT_ROLE_MISMATCH',
                  segment_id + ' role 必须是 ' + repr(role) + '，得到 ' + repr(node_role))
        if node_mode != mode:
            _fail('CASES_SEGMENT_MODE_MISMATCH',
                  segment_id + ' mode 必须是 ' + repr(mode) + '，得到 ' + repr(node_mode))
        repeats = _as_int(node['repeats'], segment_id + '.repeats')
        if repeats < 1:
            _fail('CASES_SEGMENT_REPEATS_INVALID', segment_id + '.repeats 必须 >= 1')
        raw_cases = node['cases']
        if not isinstance(raw_cases, list) or not raw_cases:
            _fail('CASES_SEGMENT_CASES_INVALID',
                  segment_id + '.cases 必须是非空列表')
        entries = []
        replay_params = None
        if role == ROLE_REPLAY:
            raw_replay_params = node.get('replay_params')
            if raw_replay_params is None:
                if top_replay_params is None:
                    _fail('REPLAY_PARAMS_MISSING', segment_id + '.replay_params')
                replay_params = dict(top_replay_params)
            else:
                replay_params = _normalize_replay_params(raw_replay_params)
                if top_replay_params is not None \
                        and replay_params != top_replay_params:
                    _fail('REPLAY_PARAMS_MISMATCH',
                          segment_id + ' 的 replay_params 与顶层不一致')
        elif node.get('replay_params') is not None:
            _fail('REPLAY_PARAMS_UNEXPECTED',
                  segment_id + ' 不是 replay 段，不应带 replay_params')
        for index, raw_case in enumerate(raw_cases):
            context = segment_id + '.cases[' + str(index) + ']'
            normalized_case = _normalize_case(segment_id, role, raw_case,
                                              context)
            entries.append((normalized_case,
                            raw_case.get('repeat'), context))
        case_ids, repeat_indices = _group_case_entries(
            entries, segment_id, repeats)
        episodes = len(case_ids) * repeats
        if episodes != expected_episodes:
            _fail('CASES_EPISODES_MISMATCH',
                  segment_id + ' episodes = len(case_ids)×repeats = '
                  + str(len(case_ids)) + '×' + str(repeats) + ' = ' + str(episodes)
                  + '，固定段表要求 ' + str(expected_episodes)
                  + '（若每个 case 条目各对应 1 episode，请置 repeats=1）')
        cases_by_id = {}
        for entry, _repeat, _context in entries:
            case_id = entry['case_id']
            if case_id in cases_by_id:
                continue
            cases_by_id[case_id] = dict(entry)
        if role == ROLE_REPLAY and repo_root is not None:
            _check_replay_references(segment_id, cases_by_id, repo_root)
        result['segments'][segment_id] = {
            'segment_id': segment_id,
            'role': role,
            'mode': mode,
            'repeats': repeats,
            'case_ids': case_ids,
            'cases': cases_by_id,
            'repeat_indices': repeat_indices,
            'replay_params': replay_params,
            'episodes': episodes,
        }
        result['case_ids'][segment_id] = case_ids
        result['repeats'][segment_id] = repeats
    missing = sorted(set(SEGMENT_IDS) - set(result['segments']))
    if missing:
        _fail('CASES_SEGMENTS_MISSING', ', '.join(missing))
    total = sum(segment['episodes'] for segment in result['segments'].values())
    if total != MIN_EPISODES_REQUIRED:
        _fail('CASES_EPISODES_MISMATCH',
              '总 episode 数 ' + str(total) + ' != ' + str(MIN_EPISODES_REQUIRED))
    result['total_episodes'] = total
    result['schema_version'] = CONTACT_CASES_SCHEMA
    result['contact_contract_version'] = CONTACT_CONTRACT_VERSION
    result['envelope_contract_version'] = ENVELOPE_CONTRACT_VERSION
    return result


def _check_replay_references(segment_id, cases_by_id, repo_root):
    root = Path(repo_root)
    for case_id, spec in cases_by_id.items():
        previous = Path(str(spec['previous_run_dir']))
        resolved = previous if previous.is_absolute() else root / previous
        if not resolved.is_dir():
            _fail('REPLAY_PREVIOUS_RUN_MISSING',
                  segment_id + ' case_id=' + case_id + ' previous_run_dir 不存在: '
                  + str(resolved))
        source = Path(str(spec['source_cases_file']))
        resolved_source = source if source.is_absolute() else root / source
        if not resolved_source.is_file():
            _fail('REPLAY_SOURCE_CASES_MISSING',
                  segment_id + ' case_id=' + case_id + ' source_cases_file 不存在: '
                  + str(resolved_source))


def load_cases_file(path):
    """Read a cases JSON file and return ``(payload, sha256)``."""
    cases_path = Path(path)
    try:
        raw = cases_path.read_bytes()
    except OSError as error:
        raise ContactPlanError('CASES_READ_FAILED: ' + str(path) + ': '
                               + str(error)) from error
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContactPlanError('CASES_JSON_INVALID: ' + str(path) + ': '
                               + str(error)) from error
    return payload, hashlib.sha256(raw).hexdigest()


def load_expected_file(path):
    """Read the expected JSON file and return ``(payload, sha256)``."""
    expected_path = Path(path)
    try:
        raw = expected_path.read_bytes()
    except OSError as error:
        raise ContactPlanError('EXPECTED_READ_FAILED: ' + str(path) + ': '
                               + str(error)) from error
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContactPlanError('EXPECTED_JSON_INVALID: ' + str(path) + ': '
                               + str(error)) from error
    return payload, hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# run plan
# ---------------------------------------------------------------------------

def _normalize_run_params(segment_id, role, raw, case_ids):
    if not isinstance(raw, dict):
        _fail('RUN_PARAMS_INVALID', 'run_params 必须是对象')
    if role == ROLE_REPLAY:
        missing = [key for key in ('repeats', 'replay_params', 'cases')
                   if key not in raw]
        if missing:
            _fail('RUN_PARAMS_MISSING', segment_id + ': ' + ', '.join(missing))
        repeats = _as_int(raw['repeats'], 'run_params.repeats')
        replay_params = _normalize_replay_params(raw['replay_params'])
        raw_cases = raw['cases']
        if not isinstance(raw_cases, dict):
            _fail('RUN_PARAMS_INVALID', segment_id + '.run_params.cases 必须是对象')
        cases = {}
        for case_id in case_ids:
            if case_id not in raw_cases:
                _fail('RUN_PARAMS_CASES_MISMATCH',
                      segment_id + ' run_params.cases 缺少 ' + case_id)
            cases[case_id] = _normalize_replay_case(
                segment_id, dict(raw_cases[case_id], case_id=case_id),
                'run_params.cases.' + case_id)
        unknown = sorted(set(raw_cases) - set(case_ids))
        if unknown:
            _fail('RUN_PARAMS_CASES_MISMATCH',
                  segment_id + ' run_params.cases 多出 ' + ', '.join(unknown))
        normalized = {'repeats': repeats, 'replay_params': replay_params,
                      'cases': cases}
        if 'repeat_indices' in raw:
            normalized['repeat_indices'] = _normalize_repeat_indices(
                raw['repeat_indices'], case_ids, 'run_params.repeat_indices')
        return normalized
    missing = [key for key in ('repeats', 'cases') if key not in raw]
    if missing:
        _fail('RUN_PARAMS_MISSING', segment_id + ': ' + ', '.join(missing))
    repeats = _as_int(raw['repeats'], 'run_params.repeats')
    if repeats < 1:
        _fail('RUN_PARAMS_INVALID', 'run_params.repeats 必须 >= 1')
    raw_cases = raw['cases']
    if not isinstance(raw_cases, dict):
        _fail('RUN_PARAMS_INVALID', segment_id + '.run_params.cases 必须是对象')
    cases = {}
    for case_id in case_ids:
        if case_id not in raw_cases:
            _fail('RUN_PARAMS_CASES_MISMATCH',
                  segment_id + ' run_params.cases 缺少 ' + case_id)
        node = dict(raw_cases[case_id], case_id=case_id)
        cases[case_id] = _normalize_case(
            segment_id, role, node, 'run_params.cases.' + case_id)
    unknown = sorted(set(raw_cases) - set(case_ids))
    if unknown:
        _fail('RUN_PARAMS_CASES_MISMATCH',
              segment_id + ' run_params.cases 多出 ' + ', '.join(unknown))
    normalized = {'repeats': repeats, 'cases': cases}
    if 'repeat_indices' in raw:
        normalized['repeat_indices'] = _normalize_repeat_indices(
            raw['repeat_indices'], case_ids, 'run_params.repeat_indices')
    return normalized


def _normalize_repeat_indices(raw, case_ids, field):
    if not isinstance(raw, dict) or set(raw) != set(case_ids):
        _fail(field.upper() + '_INVALID', '必须恰好覆盖 case_ids')
    normalized = {}
    for case_id in case_ids:
        indices = raw[case_id]
        if not isinstance(indices, list) or not indices:
            _fail(field.upper() + '_INVALID', case_id + ' 必须是非空索引列表')
        converted = sorted(_as_int(value, field + '.' + case_id)
                           for value in indices)
        if len(set(converted)) != len(converted):
            _fail(field.upper() + '_DUPLICATE', case_id)
        normalized[case_id] = converted
    return normalized


def _as_case_ids(value):
    if isinstance(value, (str, bytes)):
        _fail('CASE_IDS_INVALID', '必须是 case_id 列表')
    try:
        items = list(value)
    except TypeError:
        _fail('CASE_IDS_INVALID', '必须是 case_id 列表')
    if not items:
        _fail('CASE_IDS_INVALID', '不能为空')
    case_ids = [_as_non_empty_text(item, 'case_ids') for item in items]
    if len(set(case_ids)) != len(case_ids):
        _fail('CASE_IDS_DUPLICATE', 'case_ids 不得重复')
    return sorted(case_ids)


def build_run_plan(**kwargs):
    """Build one normalized segment run plan (see ``RUN_PLAN_FIELDS``)."""
    unknown = sorted(set(kwargs) - set(RUN_PLAN_FIELDS))
    if unknown:
        _fail('UNKNOWN_RUN_PLAN_FIELD', ', '.join(unknown))
    missing = [field for field in RUN_PLAN_FIELDS if field not in kwargs]
    if missing:
        _fail('MISSING_RUN_PLAN_FIELD', ', '.join(missing))
    segment_id = _as_text(kwargs['segment_id'], 'segment_id').strip()
    if segment_id not in SEGMENT_TABLE:
        _fail('SEGMENT_ID_INVALID', repr(segment_id)
              + '（只允许 ' + repr(SEGMENT_IDS) + '）')
    role, mode, expected_episodes = SEGMENT_TABLE[segment_id]
    if _as_text(kwargs['role'], 'role') != role:
        _fail('SEGMENT_ROLE_MISMATCH',
              segment_id + ' 必须 role=' + repr(role))
    if _as_text(kwargs['mode'], 'mode') != mode:
        _fail('SEGMENT_MODE_MISMATCH',
              segment_id + ' 必须 mode=' + repr(mode))
    if _as_text(kwargs['contact_contract_version'],
                'contact_contract_version') != CONTACT_CONTRACT_VERSION:
        _fail('CONTACT_CONTRACT_VERSION_MISMATCH',
              '期望 ' + CONTACT_CONTRACT_VERSION)
    if _as_text(kwargs['envelope_contract_version'],
                'envelope_contract_version') != ENVELOPE_CONTRACT_VERSION:
        _fail('ENVELOPE_CONTRACT_VERSION_MISMATCH',
              '期望 ' + ENVELOPE_CONTRACT_VERSION)
    case_ids = _as_case_ids(kwargs['case_ids'])
    run_params = _normalize_run_params(
        segment_id, role, kwargs['run_params'], case_ids)
    episodes = len(case_ids) * run_params['repeats']
    if episodes != expected_episodes:
        _fail('RUN_PLAN_EPISODES_MISMATCH',
              segment_id + ' episodes=' + str(episodes)
              + ' != 固定段表 ' + str(expected_episodes))
    plan = {
        'segment_id': segment_id,
        'role': role,
        'mode': mode,
        'cases_file': _as_path_text(kwargs['cases_file'], 'cases_file'),
        'cases_sha256': _as_sha256(kwargs['cases_sha256'], 'cases_sha256'),
        'case_ids': case_ids,
        'expected_file': _as_path_text(kwargs['expected_file'], 'expected_file'),
        'expected_sha256': _as_sha256(
            kwargs['expected_sha256'], 'expected_sha256'),
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'vehicle_config': _as_yaml_path(kwargs['vehicle_config'],
                                        'vehicle_config'),
        'vehicle_config_sha256': _as_sha256(
            kwargs['vehicle_config_sha256'], 'vehicle_config_sha256'),
        'map_config': _as_yaml_path(kwargs['map_config'], 'map_config'),
        'map_config_sha256': _as_sha256(
            kwargs['map_config_sha256'], 'map_config_sha256'),
        'run_params': run_params,
    }
    return {field: plan[field] for field in RUN_PLAN_FIELDS}


def _normalize_run_plan(raw, context):
    if not isinstance(raw, dict):
        _fail('RUN_PLAN_INVALID', context + ' 必须是对象')
    missing = [field for field in RUN_PLAN_FIELDS if field not in raw]
    if missing:
        _fail('RUN_PLAN_FIELD_MISSING', context + ' 缺少 ' + ', '.join(missing))
    try:
        return build_run_plan(**{field: raw[field] for field in RUN_PLAN_FIELDS})
    except ContactPlanError as error:
        raise ContactPlanError(str(error) + '（' + context + '）') from error


# ---------------------------------------------------------------------------
# expected file normalization
# ---------------------------------------------------------------------------

_ACCEPTABLE_PHYSICAL_KEYS = (
    'acceptable_physical_outcomes',
    'acceptable_physical',
    'expected_physical_outcome',
    'physical_outcome',
)


def _normalize_expected_must_conditions(value, context):
    if value is None:
        return None
    if not isinstance(value, list):
        _fail('EXPECTED_CASE_INVALID', context + '.must_conditions 必须是列表')
    normalized = []
    for index, condition in enumerate(value):
        item_context = context + '.must_conditions[' + str(index) + ']'
        if isinstance(condition, str):
            text = condition.strip()
            if not text:
                _fail('EXPECTED_CONDITION_INVALID',
                      item_context + ' kind 不能为空')
            normalized.append(text)
        elif isinstance(condition, dict):
            kind = condition.get('kind') or condition.get('condition')
            if not isinstance(kind, str) or not kind.strip():
                _fail('EXPECTED_CONDITION_INVALID', item_context + '.kind')
            item = {'kind': kind.strip()}
            if 'value' in condition:
                item['value'] = condition['value']
            normalized.append(item)
        else:
            _fail('EXPECTED_CONDITION_INVALID',
                  item_context + ' 必须是字符串或 {kind,value}')
    return normalized


def _normalize_expected_outcomes(spec, context):
    for key in _ACCEPTABLE_PHYSICAL_KEYS:
        if key not in spec:
            continue
        value = spec[key]
        if isinstance(value, str):
            value = [value]
        return _as_outcome_list(value, context + '.' + key)
    _fail('EXPECTED_CASE_MISSING',
          context + ' 缺少 acceptable_physical_outcomes/acceptable_physical')


def _normalize_expected_attribution(spec, context):
    for key in ('attribution_prim_paths', 'wall_prim_paths',
                'required_attribution_prim_paths'):
        if key in spec:
            return _as_text_list(spec[key], context + '.' + key,
                                 allow_empty=True)
    values = []
    for condition in spec.get('must_conditions') or []:
        if not isinstance(condition, dict):
            continue
        kind = condition.get('kind') or condition.get('condition')
        if kind != 'attribution_prim_in':
            continue
        value = condition.get('value')
        if isinstance(value, list):
            values.extend(_as_text_list(
                value, context + '.attribution_prim_in'))
        else:
            values.append(_as_non_empty_text(
                value, context + '.attribution_prim_in'))
    return sorted(set(values)) if values else None


def _normalize_replay_verdict(value, context):
    if isinstance(value, str):
        verdict = _as_replay_verdict(value, context)
        return {'replay_verdict': verdict, 'replay_verdict_allowed': [verdict]}
    if not isinstance(value, dict):
        _fail('EXPECTED_REPLAY_VERDICT_INVALID',
              context + ' 必须是字符串或对象')
    single = value.get('replay_verdict') or value.get('expected_verdict') \
        or value.get('verdict')
    if single is not None:
        verdict = _as_replay_verdict(single, context)
        return {'replay_verdict': verdict, 'replay_verdict_allowed': [verdict]}
    allowed = value.get('allowed')
    if allowed is None:
        _fail('EXPECTED_REPLAY_VERDICT_MISSING', context + '.replay_verdict')
    allowed = _as_text_list(allowed, context + '.allowed')
    unknown = [item for item in allowed if item not in REPLAY_VERDICTS]
    if unknown:
        _fail('EXPECTED_REPLAY_VERDICT_INVALID',
              'allowed 列表含未知 verdict: ' + ', '.join(unknown))
    normalized = {'replay_verdict_allowed': allowed}
    if len(allowed) == 1:
        normalized['replay_verdict'] = allowed[0]
    if 'previous_physical_label' in value:
        normalized['previous_physical_label'] = _as_previous_label(
            value['previous_physical_label'],
            context + '.previous_physical_label')
    if 'rule' in value:
        normalized['replay_rule'] = _as_non_empty_text(
            value['rule'], context + '.rule')
    return normalized


def _normalize_expected_case(spec, context, *, segment_id, case_id, replay,
                             replay_verdicts, previous_label):
    if not isinstance(spec, dict):
        _fail('EXPECTED_CASE_INVALID', context + ' 必须是对象')
    normalized = {
        'case_id': case_id,
        'acceptable_physical_outcomes': _normalize_expected_outcomes(
            spec, context),
    }
    conditions = _normalize_expected_must_conditions(
        spec.get('must_conditions'), context)
    if conditions is not None:
        normalized['must_conditions'] = conditions
    if 'unsupported_allowed' in spec:
        value = spec['unsupported_allowed']
        if isinstance(value, list):
            normalized['unsupported_allowed'] = _as_text_list(
                value, context + '.unsupported_allowed', allow_empty=True)
        else:
            normalized['unsupported_allowed'] = _as_bool(
                value, context + '.unsupported_allowed')
    paths = _normalize_expected_attribution(spec, context)
    if paths is not None:
        normalized['attribution_prim_paths'] = paths
    if replay:
        verdict_source = spec.get('replay_verdict') \
            or spec.get('expected_verdict') or spec.get('verdict')
        if verdict_source is None:
            verdict_source = (replay_verdicts or {}).get(case_id)
        if verdict_source is None:
            verdict_source = (replay_verdicts or {}).get(segment_id)
        if verdict_source is None:
            _fail('EXPECTED_REPLAY_VERDICT_MISSING',
                  context + '.replay_verdict')
        resolved = _normalize_replay_verdict(
            verdict_source, context + '.replay_verdict')
        declared_label = resolved.pop('previous_physical_label', None)
        normalized.update(resolved)
        if declared_label is not None and previous_label is not None \
                and declared_label != previous_label:
            _fail('EXPECTED_REPLAY_LABEL_MISMATCH',
                  context + ' previous_physical_label='
                  + repr(declared_label) + ' 与 cases 文件 '
                  + repr(previous_label) + ' 不一致')
    return normalized


def _normalize_case_index(node, context):
    result = {}
    if node is None:
        return result
    if isinstance(node, dict):
        for case_id, spec in node.items():
            if not isinstance(spec, dict):
                _fail('EXPECTED_CASES_INVALID', context + '.' + str(case_id))
            item = dict(spec)
            item.setdefault('case_id', str(case_id))
            result[str(case_id)] = item
    elif isinstance(node, list):
        for index, spec in enumerate(node):
            if not isinstance(spec, dict):
                _fail('EXPECTED_CASES_INVALID',
                      context + '[' + str(index) + ']')
            case_id = spec.get('case_id') or spec.get('id')
            if not isinstance(case_id, str) or not case_id:
                _fail('EXPECTED_CASES_INVALID',
                      context + '[' + str(index) + '] 缺少 case_id')
            result[case_id] = dict(spec)
    else:
        _fail('EXPECTED_CASES_INVALID', context + ' 必须是对象或列表')
    return result


def normalize_expected_payload(payload, normalized_cases):
    """Validate the expected file and resolve one expectation per case.

    Accepts both the previous work package layout (top-level ``cases`` dict of
    ``acceptable_physical_outcomes`` plus per-case ``segments[*].cases``) and
    the Lead 2026-11-02 contact layout (top-level ``cases`` keyed by case id or
    segment id, ``segments[*].cases`` as a list of episode case ids and a
    ``replay_verdicts`` mapping case id -> allowed verdict rule).  Every episode
    case id of every fixed segment must be covered; replay cases must declare a
    single verdict or an allowed verdict set.
    """
    if not isinstance(payload, dict):
        _fail('EXPECTED_INVALID', 'expected 必须是 JSON 对象')
    if payload.get('schema_version') != CONTACT_EXPECTED_SCHEMA:
        _fail('EXPECTED_SCHEMA_MISMATCH',
              '期望 ' + CONTACT_EXPECTED_SCHEMA + '，得到 '
              + repr(payload.get('schema_version')))
    if payload.get('status') != EXPECTED_STATUS:
        _fail('EXPECTED_STATUS_INVALID', '必须是 ' + EXPECTED_STATUS)
    if 'contact_contract_version' in payload \
            and payload['contact_contract_version'] != CONTACT_CONTRACT_VERSION:
        _fail('CONTACT_CONTRACT_VERSION_MISMATCH',
              'expected.contact_contract_version 必须是 '
              + CONTACT_CONTRACT_VERSION)
    if 'envelope_contract_version' in payload \
            and payload['envelope_contract_version'] != ENVELOPE_CONTRACT_VERSION:
        _fail('ENVELOPE_CONTRACT_VERSION_MISMATCH',
              'expected.envelope_contract_version 必须是 '
              + ENVELOPE_CONTRACT_VERSION)
    top_cases = _normalize_case_index(payload.get('cases'), 'expected.cases')
    replay_verdicts = payload.get('replay_verdicts')
    if replay_verdicts is None:
        replay_verdicts = {}
    if not isinstance(replay_verdicts, dict):
        _fail('EXPECTED_REPLAY_VERDICTS_INVALID',
              'expected.replay_verdicts 必须是对象')
    raw_segments = payload.get('segments')
    if raw_segments is None:
        raw_segments = {}
    if isinstance(raw_segments, dict):
        segment_nodes = list(raw_segments.items())
    elif isinstance(raw_segments, list):
        segment_nodes = [(node.get('segment_id'), node)
                         for node in raw_segments if isinstance(node, dict)]
    else:
        _fail('EXPECTED_SEGMENTS_INVALID', 'expected.segments 必须是对象或列表')
    segment_case_specs = {}
    segment_episodes = {}
    for segment_id, node in segment_nodes:
        if segment_id not in SEGMENT_TABLE:
            _fail('EXPECTED_SEGMENT_UNKNOWN',
                  '未知 segment_id ' + repr(segment_id))
        if not isinstance(node, dict):
            _fail('EXPECTED_SEGMENTS_INVALID',
                  repr(segment_id) + ' 必须是对象')
        role = node.get('role')
        if role is not None and role != SEGMENT_TABLE[segment_id][0]:
            _fail('EXPECTED_SEGMENT_ROLE_MISMATCH',
                  repr(segment_id) + ' role=' + repr(role))
        episodes = node.get('expected_episodes')
        if episodes is not None:
            segment_episodes[segment_id] = _as_int(
                episodes, 'expected.segments.' + str(segment_id)
                + '.expected_episodes')
        cases_node = node.get('cases')
        ids = []
        specs = {}
        if isinstance(cases_node, dict):
            specs = _normalize_case_index(
                cases_node,
                'expected.segments.' + str(segment_id) + '.cases')
            ids = sorted(specs)
        elif isinstance(cases_node, list):
            for index, item in enumerate(cases_node):
                if isinstance(item, str):
                    ids.append(_as_non_empty_text(
                        item, 'expected.segments.' + str(segment_id)
                        + '.cases[' + str(index) + ']'))
                elif isinstance(item, dict):
                    case_id = item.get('case_id') or item.get('id')
                    if not isinstance(case_id, str) or not case_id:
                        _fail('EXPECTED_CASES_INVALID',
                              'expected.segments.' + str(segment_id)
                              + '.cases[' + str(index) + '] 缺少 case_id')
                    ids.append(case_id)
                    specs[case_id] = dict(item)
        elif cases_node is not None:
            _fail('EXPECTED_SEGMENTS_INVALID',
                  'expected.segments.' + str(segment_id)
                  + '.cases 必须是对象或列表')
        segment_case_specs[segment_id] = specs
        if ids:
            declared = set(ids)
            expected_ids = set(
                normalized_cases['segments'][segment_id]['case_ids'])
            if not declared <= expected_ids:
                _fail('EXPECTED_SEGMENT_CASES_MISMATCH',
                      repr(segment_id) + ' expected cases 含 cases 文件之外的 '
                      'id: ' + repr(sorted(declared - expected_ids)))
    per_segment = {}
    for segment_id in SEGMENT_IDS:
        segment = normalized_cases['segments'][segment_id]
        replay = segment['role'] == ROLE_REPLAY
        if segment_episodes.get(segment_id) is not None \
                and segment_episodes[segment_id] != segment['episodes']:
            _fail('EXPECTED_EPISODES_MISMATCH',
                  repr(segment_id) + ' expected_episodes='
                  + str(segment_episodes[segment_id]) + ' != cases 文件 '
                  + str(segment['episodes']))
        merged_cases = {}
        for case_id in segment['case_ids']:
            specific = segment_case_specs.get(segment_id, {}).get(case_id)
            spec = top_cases.get(case_id) or top_cases.get(segment_id) \
                or specific
            if spec is None:
                _fail('EXPECTED_CASE_MISSING',
                      'expected 未覆盖 ' + segment_id + ' case_id=' + case_id)
            merged_spec = dict(spec)
            if specific is not None:
                merged_spec.update(specific)
            merged_spec.setdefault('case_id', case_id)
            previous_label = None
            if replay:
                previous_label = segment['cases'][case_id][
                    'previous_physical_label']
            merged = _normalize_expected_case(
                merged_spec, 'expected.' + segment_id + '.' + case_id,
                segment_id=segment_id, case_id=case_id, replay=replay,
                replay_verdicts=replay_verdicts, previous_label=previous_label)
            merged_cases[case_id] = merged
        per_segment[segment_id] = merged_cases
    canonical_cases = {}
    for segment_id in SEGMENT_IDS:
        for case_id, spec in per_segment[segment_id].items():
            canonical_cases[case_id] = spec
    normalized_segments = {
        segment_id: {
            'role': normalized_cases['segments'][segment_id]['role'],
            'expected_episodes': normalized_cases['segments'][segment_id][
                'episodes'],
            'cases': per_segment[segment_id],
        }
        for segment_id in SEGMENT_IDS
    }
    normalized_payload = {
        'schema_version': CONTACT_EXPECTED_SCHEMA,
        'status': EXPECTED_STATUS,
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'cases': canonical_cases,
        'segments': normalized_segments,
    }
    for key in ('note', 'notes', 'freeze_rule', 'basis'):
        if key in payload:
            normalized_payload[key] = _as_non_empty_text(
                payload[key], 'expected.' + key)
    return normalized_payload, per_segment


# ---------------------------------------------------------------------------
# freeze assembly
# ---------------------------------------------------------------------------

def _normalize_cases_index(cases):
    if not isinstance(cases, (list, tuple)) or not cases:
        _fail('CASES_INVALID', 'cases 声明必须是非空列表')
    index = {}
    for entry in cases:
        if not isinstance(entry, dict):
            _fail('CASES_INVALID', 'cases[*] 必须是对象')
        cases_file = _as_path_text(entry.get('cases_file'), 'cases_file')
        sha = _as_sha256(entry.get('cases_sha256'), 'cases_sha256')
        if cases_file in index and index[cases_file] != sha:
            _fail('CASES_INVALID', '同一 cases_file 出现不同 sha256: ' + cases_file)
        index[cases_file] = sha
    return index


def _normalize_map_state(map_state):
    if not isinstance(map_state, dict):
        _fail('MAP_STATE_INVALID', 'map_state 必须是对象')
    normalized = {
        'map_asset_id': _as_non_empty_text(
            map_state.get('map_asset_id'), 'map_asset_id'),
        'terrain_sha256': _as_sha256(map_state.get('terrain_sha256'),
                                     'terrain_sha256'),
        'preview_sha256': _as_sha256(map_state.get('preview_sha256'),
                                     'preview_sha256'),
        'map_config_sha256': _as_sha256(map_state.get('map_config_sha256'),
                                        'map_config_sha256'),
    }
    if map_state.get('map_config_file') is not None:
        normalized['map_config_file'] = _as_path_text(
            map_state['map_config_file'], 'map_config_file')
    return normalized


def _normalize_worktree_state(worktree_state):
    if not isinstance(worktree_state, dict):
        _fail('WORKTREE_STATE_INVALID', 'worktree_state 必须是对象')
    if worktree_state.get('tracked_paths') != list(TRACKED_PATHS):
        _fail('WORKTREE_STATE_INVALID',
              'tracked_paths 必须是 ' + repr(list(TRACKED_PATHS)))
    return {
        'tracked_paths': list(TRACKED_PATHS),
        'status_text_sha256': _as_sha256(
            worktree_state.get('status_text_sha256'),
            'worktree_state.status_text_sha256'),
        'clean': bool(worktree_state.get('clean')),
    }


def _default_support_scope(segment_plans):
    replay_sources = set()
    for plan in segment_plans.values():
        if plan['role'] != ROLE_REPLAY:
            continue
        for spec in plan['run_params']['cases'].values():
            replay_sources.add(spec['previous_run_dir'])
    return {
        'scope': 'CURRENT_SIM_MODEL_ONLY',
        'evidence_domain': 'GUI Isaac Lab simulation (DirectX/D3D12); '
                           '非 SITL/HIL/实机',
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'contact_sensor_model': 'physx_contact_sensor '
                                '(filtered per-prim force / unfiltered net force); '
                                'unavailable channel => UNKNOWN',
        'simulation_models': [
            'rigid_body_physx_contact',
            'kinematic_obstacle',
            'sphere_overlap_geometry_inference',
            'reference_frame_aabb_envelope',
        ],
        'replay_sources': sorted(replay_sources),
        'limitations': [
            'PhysX contact evidence is simulation-channel evidence; it is not a '
            'real contact sensor and not hardware-in-the-loop evidence',
            'force/impulse magnitudes are policy-step window aggregates and are '
            'not event-resolved; impulse is never used as a force',
            'geometry overlap > 0.02 m is inference only and is never promoted '
            'to a PhysX contact event/force',
            'AABB/sphere envelope is a conservative bound at one measured joint '
            'state, not an all-attitude triangle-mesh sweep proof',
            'replay segments compare stored previous labels against re-simulated '
            'evidence; the referenced previous run directories are not re-read',
            'expected values are pre-run expectations, not conclusions; only '
            'independent verification promotes them',
            'this freeze covers the current simulation model only and does not '
            'raise any Gate',
        ],
    }


def _normalize_support_scope(support_scope, segment_plans):
    if support_scope is None:
        return _default_support_scope(segment_plans)
    if not isinstance(support_scope, dict):
        _fail('SUPPORT_SCOPE_INVALID', 'support_scope 必须是对象')
    missing = [key for key in _SUPPORT_SCOPE_REQUIRED_KEYS
               if key not in support_scope]
    if missing:
        _fail('SUPPORT_SCOPE_MISSING', ', '.join(missing))
    normalized = {
        'scope': _as_non_empty_text(support_scope['scope'], 'support_scope.scope'),
        'evidence_domain': _as_non_empty_text(
            support_scope['evidence_domain'], 'support_scope.evidence_domain'),
        'contact_contract_version': _as_non_empty_text(
            support_scope['contact_contract_version'],
            'support_scope.contact_contract_version'),
        'envelope_contract_version': _as_non_empty_text(
            support_scope['envelope_contract_version'],
            'support_scope.envelope_contract_version'),
        'contact_sensor_model': _as_non_empty_text(
            support_scope['contact_sensor_model'],
            'support_scope.contact_sensor_model'),
        'simulation_models': _as_text_list(
            support_scope['simulation_models'],
            'support_scope.simulation_models'),
        'limitations': _as_text_list(
            support_scope['limitations'], 'support_scope.limitations'),
    }
    if normalized['contact_contract_version'] != CONTACT_CONTRACT_VERSION:
        _fail('SUPPORT_SCOPE_MISMATCH',
              'support_scope.contact_contract_version 必须是 '
              + CONTACT_CONTRACT_VERSION)
    if normalized['envelope_contract_version'] != ENVELOPE_CONTRACT_VERSION:
        _fail('SUPPORT_SCOPE_MISMATCH',
              'support_scope.envelope_contract_version 必须是 '
              + ENVELOPE_CONTRACT_VERSION)
    if support_scope.get('replay_sources') is not None:
        normalized['replay_sources'] = _as_text_list(
            support_scope['replay_sources'], 'support_scope.replay_sources',
            allow_empty=True)
    return normalized


def _derive_budget(segment_plans):
    segment_episodes = {}
    by_role = {role: 0 for role in ROLES}
    for segment_id in SEGMENT_IDS:
        plan = segment_plans[segment_id]
        episodes = len(plan['case_ids']) * plan['run_params']['repeats']
        segment_episodes[segment_id] = episodes
        by_role[plan['role']] += episodes
    total = sum(segment_episodes.values())
    return {
        'total_episodes': total,
        'segment_episodes': segment_episodes,
        'by_role': by_role,
        'min_episodes_required': MIN_EPISODES_REQUIRED,
    }


def _check_budget(budget, derived):
    if budget is None:
        if derived['total_episodes'] < MIN_EPISODES_REQUIRED:
            _fail('EPISODES_INSUFFICIENT', '总 episode 数 '
                  + str(derived['total_episodes']) + ' < '
                  + str(MIN_EPISODES_REQUIRED))
        return derived
    if not isinstance(budget, dict):
        _fail('BUDGET_INVALID', 'budget 必须是对象')
    unknown = sorted(set(budget) - set(derived))
    if unknown:
        _fail('BUDGET_UNKNOWN_KEY', ', '.join(unknown))
    normalized = dict(derived)
    for key, value in derived.items():
        provided = budget.get(key, value)
        if key == 'segment_episodes':
            if not isinstance(provided, dict) or set(provided) != set(value):
                _fail('BUDGET_MISMATCH', 'segment_episodes 必须覆盖固定段表')
            normalized[key] = {}
            for segment_id in SEGMENT_IDS:
                normalized[key][segment_id] = _as_int(
                    provided[segment_id], 'budget.segment_episodes.' + segment_id)
                if normalized[key][segment_id] != value[segment_id]:
                    _fail('BUDGET_MISMATCH',
                          segment_id + ' episodes=' + str(
                              normalized[key][segment_id]) + ' != '
                          + str(value[segment_id]))
        elif key == 'by_role':
            if not isinstance(provided, dict):
                _fail('BUDGET_MISMATCH', 'by_role 必须是对象')
            normalized[key] = {}
            for role in ROLES:
                normalized[key][role] = _as_int(
                    provided.get(role, value[role]), 'budget.by_role.' + role)
                if normalized[key][role] != value[role]:
                    _fail('BUDGET_MISMATCH',
                          role + ' episodes 与派生值不一致')
        else:
            normalized[key] = _as_int(provided, 'budget.' + key)
            if normalized[key] != value:
                _fail('BUDGET_MISMATCH',
                      key + '=' + str(normalized[key]) + ' != ' + str(value))
    if normalized['total_episodes'] < MIN_EPISODES_REQUIRED:
        _fail('EPISODES_INSUFFICIENT', '总 episode 数 '
              + str(normalized['total_episodes']) + ' < '
              + str(MIN_EPISODES_REQUIRED))
    return normalized


def _looks_like_normalized_cases(payload):
    """True when ``payload`` is already a ``normalize_cases_payload`` result."""
    segments = payload.get('segments')
    if not isinstance(segments, dict) or 'total_episodes' not in payload:
        return False
    if set(segments) != set(SEGMENT_IDS):
        return False
    return all(
        isinstance(segments[segment_id], dict)
        and isinstance(segments[segment_id].get('cases'), dict)
        for segment_id in SEGMENT_IDS)


def build_freeze(*, frozen_at, code_commit, worktree_state, map_state, cases,
                 segment_run_plans, expected, expected_file, expected_sha256,
                 budget=None, support_scope=None, note='', repo_root=None):
    """Assemble the single-file contact-verification pre-run freeze.

    ``cases`` is the normalized cases payload (``normalize_cases_payload``) or
    the raw cases JSON payload; ``segment_run_plans`` maps every fixed segment
    id to its run plan; ``expected`` is the expected JSON payload.  When
    ``repo_root`` is given, replay ``previous_run_dir`` / ``source_cases_file``
    references are checked for existence (path strings only, contents never
    read).
    """
    if not isinstance(cases, dict):
        _fail('CASES_INVALID', 'cases 必须是对象')
    if _looks_like_normalized_cases(cases):
        normalized_cases = cases
    else:
        normalized_cases = normalize_cases_payload(cases, repo_root=repo_root)
    if repo_root is not None:
        for segment_id in REPLAY_SEGMENT_IDS:
            _check_replay_references(
                segment_id,
                normalized_cases['segments'][segment_id]['cases'],
                repo_root)
    if not isinstance(segment_run_plans, dict):
        _fail('SEGMENT_RUN_PLANS_INVALID', 'segment_run_plans 必须是对象')
    if set(segment_run_plans) != set(SEGMENT_IDS):
        _fail('SEGMENTS_MISMATCH',
              '冻结必须恰好包含 ' + repr(SEGMENT_IDS) + '，得到 '
              + repr(tuple(segment_run_plans)))
    plans = {}
    for segment_id in SEGMENT_IDS:
        plan = _normalize_run_plan(
            segment_run_plans[segment_id], 'run plan ' + segment_id)
        segment = normalized_cases['segments'][segment_id]
        if plan['case_ids'] != segment['case_ids']:
            _fail('RUN_PLAN_CASE_IDS_MISMATCH',
                  segment_id + ' run_plan.case_ids 与 cases 文件不一致')
        if plan['run_params']['repeats'] != segment['repeats']:
            _fail('RUN_PLAN_REPEATS_MISMATCH',
                  segment_id + ' run_plan.repeats 与 cases 文件不一致')
        if plan['run_params']['cases'] != segment['cases']:
            _fail('RUN_PLAN_CASES_MISMATCH',
                  segment_id + ' run_params.cases 与 cases 文件不一致')
        if plan['role'] != segment['role'] or plan['mode'] != segment['mode']:
            _fail('RUN_PLAN_ROLE_MISMATCH', segment_id)
        plans[segment_id] = plan
    cases_files = {plan['cases_file'] for plan in plans.values()}
    cases_shas = {plan['cases_sha256'] for plan in plans.values()}
    if len(cases_files) != 1:
        _fail('CASES_FILE_MISMATCH',
              '所有段必须使用同一 cases 文件，得到 ' + repr(sorted(cases_files)))
    if len(cases_shas) != 1:
        _fail('CASES_SHA256_MISMATCH',
              '所有段必须使用同一 cases_sha256，得到 ' + repr(sorted(cases_shas)))
    cases_index = _normalize_cases_index(cases_index_entries_from_plans(plans))
    expected_file = _as_path_text(expected_file, 'expected_file')
    expected_sha256 = _as_sha256(expected_sha256, 'expected_sha256')
    for segment_id, plan in plans.items():
        if plan['cases_file'] not in cases_index:
            _fail('CASE_FILE_NOT_DECLARED',
                  segment_id + ' 的 ' + plan['cases_file'] + ' 不在 cases 声明中')
        if cases_index[plan['cases_file']] != plan['cases_sha256']:
            _fail('CASE_SHA256_MISMATCH', segment_id)
        if plan['expected_file'] != expected_file:
            _fail('EXPECTED_FILE_MISMATCH',
                  segment_id + ' run_plan.expected_file='
                  + repr(plan['expected_file']) + ' != ' + repr(expected_file))
        if plan['expected_sha256'] != expected_sha256:
            _fail('EXPECTED_SHA256_MISMATCH',
                  segment_id + ' run_plan.expected_sha256 与 expected 文件 hash 不一致')
    normalized_expected, per_segment_expected = normalize_expected_payload(
        expected, normalized_cases)
    frozen_at_text = _as_text(frozen_at, 'frozen_at')
    _parse_aware_iso(frozen_at_text, 'frozen_at')
    commit = _as_text(code_commit, 'code_commit').strip().lower()
    if not _COMMIT_PATTERN.match(commit):
        _fail('CODE_COMMIT_INVALID', '必须是 git commit sha，得到 ' + repr(commit))
    worktree = _normalize_worktree_state(worktree_state)
    map_state_normalized = _normalize_map_state(map_state)
    derived_budget = _derive_budget(plans)
    normalized_budget = _check_budget(budget, derived_budget)
    normalized_support = _normalize_support_scope(support_scope, plans)
    note_text = _as_text(note, 'note').strip()
    if not note_text:
        _fail('NOTE_INVALID', 'note 不能为空（写明预期非结论与冻结范围）')
    vehicle_configs = {plan['vehicle_config'] for plan in plans.values()}
    map_configs = {plan['map_config'] for plan in plans.values()}
    if len(vehicle_configs) != 1 or len(map_configs) != 1:
        _fail('CONFIG_MISMATCH', '所有段必须使用同一 vehicle/map config')
    segments = {}
    for segment_id in SEGMENT_IDS:
        plan = plans[segment_id]
        segment = normalized_cases['segments'][segment_id]
        segments[segment_id] = {
            'segment_id': segment_id,
            'role': plan['role'],
            'mode': plan['mode'],
            'cases_file': plan['cases_file'],
            'cases_sha256': plan['cases_sha256'],
            'case_ids': list(plan['case_ids']),
            'repeats': segment['repeats'],
            'episodes': len(plan['case_ids']) * segment['repeats'],
            'run_plan': plan,
            'expected': {'cases': per_segment_expected[segment_id]},
            'expected_note': '预期非结论，实际以独立核验从原始记录重算为准',
        }
    freeze = {
        'schema_version': CONTACT_FREEZE_SCHEMA,
        'status': FREEZE_STATUS,
        'frozen_at': frozen_at_text,
        'code_commit': commit,
        'worktree_state': worktree,
        'map_state': map_state_normalized,
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'vehicle_config': next(iter(vehicle_configs)),
        'vehicle_config_sha256': plans[SEGMENT_IDS[0]]['vehicle_config_sha256'],
        'cases_file': next(iter(cases_index)),
        'cases_sha256': cases_index[next(iter(cases_index))],
        'expected_file': expected_file,
        'expected_sha256': expected_sha256,
        'segments': segments,
        'expected': normalized_expected,
        'budget': normalized_budget,
        'support_scope': normalized_support,
        'note': note_text,
    }
    return freeze


def cases_index_entries_from_plans(plans):
    """Declared cases-file index derived from the run plans (one cases file)."""
    index = {}
    for plan in plans.values():
        index[plan['cases_file']] = plan['cases_sha256']
    return [{'cases_file': path, 'cases_sha256': sha}
            for path, sha in sorted(index.items())]


# ---------------------------------------------------------------------------
# validation / lineage
# ---------------------------------------------------------------------------

def _check_freeze_schema(freeze):
    if not isinstance(freeze, dict):
        _fail('SCHEMA_VERSION_MISMATCH', 'freeze 必须是 JSON 对象')
    if freeze.get('schema_version') != CONTACT_FREEZE_SCHEMA:
        _fail('SCHEMA_VERSION_MISMATCH',
              '期望 ' + CONTACT_FREEZE_SCHEMA + '，得到 '
              + repr(freeze.get('schema_version')))


def validate_run_plan(freeze, segment_id, run_plan):
    """Compare the frozen and actual run plans field by field (JSON equality)."""
    _check_freeze_schema(freeze)
    if not isinstance(segment_id, str) or segment_id not in SEGMENT_TABLE:
        _fail('SEGMENT_ID_INVALID', repr(segment_id)
              + '（只允许 ' + repr(SEGMENT_IDS) + '）')
    segments = freeze.get('segments')
    if not isinstance(segments, dict):
        _fail('SEGMENTS_MISSING', 'freeze 中没有 segments')
    if segment_id not in segments:
        _fail('PLAN_NOT_FROZEN', 'segment_id=' + repr(segment_id) + ' 未冻结')
    entry = segments[segment_id]
    if not isinstance(entry, dict) or 'run_plan' not in entry:
        _fail('SEGMENT_RUN_PLAN_MISSING', 'segment_id=' + repr(segment_id))
    frozen_plan = _normalize_run_plan(entry['run_plan'],
                                      'frozen segment ' + segment_id)
    actual_plan = _normalize_run_plan(run_plan, 'actual segment ' + segment_id)
    for field in RUN_PLAN_FIELDS:
        if frozen_plan[field] != actual_plan[field]:
            _fail('RUN_PLAN_MISMATCH',
                  'field=' + field + ' expected=' + repr(frozen_plan[field])
                  + ' actual=' + repr(actual_plan[field]))
    return None


def _run_git(repo_root, args):
    try:
        completed = subprocess.run(
            ['git', *args], cwd=str(repo_root), capture_output=True,
            text=True, encoding='utf-8', errors='replace')
    except OSError as error:
        raise ContactPlanError('GIT_UNAVAILABLE: ' + str(error)) from error
    if completed.returncode != 0:
        raise ContactPlanError('GIT_FAILED: git ' + ' '.join(args) + ': '
                               + (completed.stderr or '').strip())
    return completed.stdout


def git_head(repo_root):
    """Current ``git rev-parse HEAD`` of ``repo_root``."""
    head = _run_git(repo_root, ['rev-parse', 'HEAD']).strip().lower()
    if not _COMMIT_PATTERN.match(head):
        _fail('CODE_COMMIT_INVALID', 'git HEAD=' + repr(head))
    return head


def _normalize_status_text(text):
    normalized = text.replace('\r\n', '\n')
    lines = [line.rstrip() for line in normalized.split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def _status_digest(text):
    return hashlib.sha256(_normalize_status_text(text).encode('utf-8')).hexdigest()


def worktree_state(repo_root, extra_untracked_paths=()):
    """``git status --porcelain -- src scripts tests configs`` digest."""
    root = Path(repo_root).resolve()
    raw = _run_git(root, ['status', '--porcelain', '--', *TRACKED_PATHS])
    lines = [line.rstrip() for line in raw.replace('\r\n', '\n').split('\n')
             if line.strip()]
    present = {line[3:] for line in lines if len(line) > 3}
    for raw_path in extra_untracked_paths:
        if raw_path is None:
            continue
        path = Path(str(raw_path))
        try:
            resolved = (path.resolve() if path.is_absolute()
                        else (root / path).resolve())
        except OSError:
            continue
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        posix = relative.as_posix()
        if posix in present or posix.split('/')[0] not in TRACKED_PATHS:
            continue
        lines.append('?? ' + posix)
        present.add(posix)
    text = '\n'.join(lines)
    return {
        'tracked_paths': list(TRACKED_PATHS),
        'status_text_sha256': _status_digest(text),
        'clean': not lines,
    }


def sha256_file(path):
    """sha256 of a file's raw bytes (freeze generator and tests)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_freeze_lineage(freeze, now_iso, repo_root):
    """Reject a future/backdated freeze, a stale HEAD or a dirty worktree."""
    _check_freeze_schema(freeze)
    if freeze.get('status') != FREEZE_STATUS:
        _fail('FREEZE_STATUS_INVALID',
              '必须是 ' + FREEZE_STATUS + '，得到 ' + repr(freeze.get('status')))
    frozen_at = _parse_aware_iso(freeze.get('frozen_at'), 'frozen_at')
    now = _parse_aware_iso(now_iso, 'now_iso')
    if frozen_at > now:
        _fail('FROZEN_AT_IN_FUTURE',
              'frozen_at 晚于当前时间（禁止未来时间/倒填）: '
              'frozen_at=' + repr(freeze.get('frozen_at')) + ' now='
              + repr(now_iso))
    recorded_commit = _as_text(freeze.get('code_commit'),
                               'code_commit').strip().lower()
    if not _COMMIT_PATTERN.match(recorded_commit):
        _fail('CODE_COMMIT_INVALID', repr(freeze.get('code_commit')))
    head = git_head(repo_root)
    if recorded_commit != head:
        _fail('CODE_COMMIT_MISMATCH',
              '冻结记录 ' + recorded_commit + '，当前 HEAD ' + head)
    state = freeze.get('worktree_state')
    if not isinstance(state, dict):
        _fail('WORKTREE_STATE_INVALID', '缺少 worktree_state')
    recorded = state.get('status_text_sha256') or state.get('digest')
    recorded = _as_sha256(recorded, 'worktree_state.status_text_sha256')
    current = worktree_state(repo_root)['status_text_sha256']
    if recorded != current:
        _fail('WORKTREE_STATE_MISMATCH',
              '冻结后 src/scripts/tests/configs 发生变化；必须新建冻结版本并重跑受影响段')
    return None
