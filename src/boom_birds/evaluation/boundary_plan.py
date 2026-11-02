"""Clearance 几何/停止需求边界专项的预运行冻结契约（纯标准库）。

对应计划 ``docs/superpowers/plans/2026-11-02-clearance-boundary.md`` §5（场景与冻结）、
§4（运行器集成）与任务 U2，并与 2026-11-02 Lead 修正（9 段）及 U3 核验器
``scripts/verify_clearance_boundary_runs.py`` 的 expected 契约对齐：

- ``build_run_plan``：把一次段运行的参数归一化为可逐字段比较的 ``run_plan``
  （浮点 ``round(...,6)``、路径 ``Path(...).as_posix()``、``case_ids`` 排序、
  ``methods`` 保持顺序、``role`` 必须与固定段表一致）；
- ``build_freeze``：组装**单文件多 segment** 冻结（真实 UTC ``frozen_at``、
  ``code_commit``、``worktree_state`` digest、地图 4 个 hash、brake model hash、
  expected 文件 hash 与内嵌 expected、固定 9 段 run_plan、episode ``budget``、
  ``support_scope`` 支持范围说明）；
- ``validate_run_plan``：运行器启动前逐字段校验实际 run_plan；
- ``check_freeze_lineage``：校验 ``frozen_at`` 不晚于当前时间、``code_commit``
  与实际 git HEAD 一致、工作树状态与冻结记录一致；
- ``worktree_state``：``git status --porcelain -- src scripts tests configs``
  归一化文本的 sha256（**与 latency_plan._normalize_status_text 同一规则**，
  回归测试逐字节对齐）。

固定 9 段（2026-11-02 Lead 修正；E 段按延迟拆成两段，取消 case 级覆盖）：

============================  ============  ==================================
segment_id                    role          说明
============================  ============  ==================================
boundary_default              boundary      A/B/C 9 场景 ×2 = 18 episode
boundary_delay_e1             boundary      E obs200/action100，2 episode
boundary_delay_e2             boundary      E obs180/action120，2 episode
boundary_fast                 boundary      D 快速车 max 0.9，2 episode
latency_clock_mapping_recheck special       时钟映射失效重跑，1 episode
latency_ttl_over_recheck      special       超 TTL 重跑（stall 0.15），1 episode
regression_dynamic            regression    默认参数回归，1 episode
regression_no_obstacle        regression    默认参数回归，1 episode
regression_fault              regression    默认参数回归，1 episode
============================  ============  ==================================

边界 GUI episode 合计 18+2+2+2 = **24**；另 2 个 recheck + 3 个回归单列。

expected 文件契约（U3 ``ExpectedIndex`` 消费）：

- 顶层 ``{schema_version, status='EXPECTED_NOT_CONCLUSION', note, freeze_rule,
  cases, segments[, basis, brake_model]}``；
- ``cases``：24 个 ``boundary_*_r0/_r1`` 条目，每个
  ``{scenario_class, acceptable_outcomes, must_conditions, unsupported_allowed,
  repeats, design, performance_note}``；``must_conditions`` 是**字符串 kind 或
  ``{kind, value}`` 的列表**，kind 严格使用 U3 的
  ``MUST_CONDITION_KINDS``，未识别 kind 在核验器中记 INCOMPLETE；
- ``segments``：**只列 6 段**（4 个 boundary + 2 个 special），每段
  ``{cases: {...}, defaults: {...}}``；``defaults`` 存放 ``cases_file``、
  ``case_ids``、``run_params``（17 项）以及段级预声明（clock 的
  ``acceptable_paths``/``must_hit_declared_path``、ttl 的 ``criteria_id='(c)'``
  +``criteria``、``freeze_rule``）；regression 段**不列**（U3 对
  ``role='regression'`` 且无预期显式放行，使用既有证据），其 run_plan 由
  ``scripts/make_boundary_freeze.py`` 的默认参数表生成并同样进入冻结。

冻结文件只记录**预期**，不是结论；实际以独立核验从原始记录重算为准。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

CLEARANCE_BOUNDARY_FREEZE_SCHEMA = 'boom_birds.clearance_boundary_freeze.v1'
CLEARANCE_BOUNDARY_EXPECTED_SCHEMA = 'boom_birds.clearance_boundary_expected.v1'
CLEARANCE_SCHEMA_VERSION = 'boom_birds.clearance.v1'
STOP_REQUIREMENT_SCHEMA_VERSION = 'boom_birds.stop_requirement.v1'
FREEZE_STATUS = 'PRE_RUN_FROZEN'
FREEZE_SCOPE = 'CURRENT_SIM_MODEL_ONLY'
EXPECTED_STATUS = 'EXPECTED_NOT_CONCLUSION'
EXPECTED_FREEZE_RULE = '运行前冻结、不得事后扩展'

ROLE_BOUNDARY = 'boundary'
ROLE_SPECIAL = 'special'
ROLE_REGRESSION = 'regression'
ROLES = (ROLE_BOUNDARY, ROLE_SPECIAL, ROLE_REGRESSION)

# 与 2026-11-02 Lead 修正的 9 段表一致；顺序即冻结 JSON 的书写顺序。
SEGMENT_ROLES = {
    'boundary_default': ROLE_BOUNDARY,
    'boundary_delay_e1': ROLE_BOUNDARY,
    'boundary_delay_e2': ROLE_BOUNDARY,
    'boundary_fast': ROLE_BOUNDARY,
    'latency_clock_mapping_recheck': ROLE_SPECIAL,
    'latency_ttl_over_recheck': ROLE_SPECIAL,
    'regression_dynamic': ROLE_REGRESSION,
    'regression_no_obstacle': ROLE_REGRESSION,
    'regression_fault': ROLE_REGRESSION,
}
SEGMENT_IDS = tuple(SEGMENT_ROLES)
BOUNDARY_SEGMENT_IDS = tuple(
    segment_id for segment_id in SEGMENT_IDS
    if SEGMENT_ROLES[segment_id] == ROLE_BOUNDARY)
SPECIAL_SEGMENT_IDS = tuple(
    segment_id for segment_id in SEGMENT_IDS
    if SEGMENT_ROLES[segment_id] == ROLE_SPECIAL)
REGRESSION_SEGMENT_IDS = tuple(
    segment_id for segment_id in SEGMENT_IDS
    if SEGMENT_ROLES[segment_id] == ROLE_REGRESSION)
EXPECTED_SEGMENT_IDS = BOUNDARY_SEGMENT_IDS + SPECIAL_SEGMENT_IDS

DEFAULT_VEHICLE_CONFIG = 'configs/vehicles/sim_reference.yaml'
FAST_VEHICLE_CONFIG = 'configs/vehicles/sim_reference_boundary_fast.yaml'
DEFAULT_BRAKE_MODEL_FILE = 'configs/scenarios/brake_model_v1.json'
DEFAULT_BRAKE_MODEL_VERSION = 'brake_final4.v1'
# brake_model_v1.json support_interval_mps 端点（下界向上、上界向下取整到 1e-6，
# 保守）：support_interval_mps = 0.2480405096–0.8514284649。
BRAKE_MODEL_SPEED_SUPPORT_MPS = (0.248041, 0.851428)
DEFAULT_STOP_DISTANCE_M = 1.1
DEFAULT_POST_ABORT_OBSERVE_S = 3.0
MIN_BOUNDARY_EPISODES = 24

TRACKED_PATHS = ('src', 'scripts', 'tests', 'configs')
EXECUTION_PATHS = ('v1', 'v2')
METHODS = ('supervisor', 'follow_only')

# 预期类别：与 U3 核验器 SCENARIO_CLASSES 完全一致（超出即核验 FAIL）。
SCENARIO_CLASSES = (
    'BLOCKED_EXIT',
    'BLOCKED_EXIT_TIGHT',
    'NO_STOP_EXPECTED',
    'STOP_WAIT_RESUME',
    'INSUFFICIENT_MARGIN',
    'STOP_OBSTACLE_HOLD',
    'POST_STOP_COLLISION',
    'HIGH_SPEED_STOP',
)
BUSINESS_OUTCOMES = ('SUCCESS', 'ABORT', 'TIMEOUT')

# must_conditions kind 词表：与 U3 核验器 MUST_CONDITION_KINDS 完全一致。
_NO_VALUE_CONDITION_KINDS = frozenset({
    'no_contact',
    'contact',
    'contact_after_business_stop',
    'contact_after_business_outcome',
    'stop_started',
    'no_stop',
})
_OUTCOME_LIST_CONDITION_KINDS = frozenset({'business_outcome_in'})
_NUMERIC_CONDITION_KINDS = frozenset({
    'min_path_clearance_below_m',
    'min_path_clearance_at_least_m',
    'min_margin_below_m',
    'min_margin_at_least_m',
    'brake_speed_below_mps',
    'brake_speed_at_least_mps',
})
MUST_CONDITION_KINDS = (
    'no_contact', 'contact', 'contact_after_business_stop',
    'contact_after_business_outcome', 'stop_started', 'no_stop',
    'business_outcome_in', 'min_path_clearance_below_m',
    'min_path_clearance_at_least_m', 'min_margin_below_m',
    'min_margin_at_least_m', 'brake_speed_below_mps',
    'brake_speed_at_least_mps',
)

# 运行器（Lead）按这些键调用 build_run_plan；字段名不得改名。
RUN_PLAN_FIELDS = (
    'segment_id',
    'role',
    'vehicle_config',
    'vehicle_config_sha256',
    'cases_file',
    'cases_sha256',
    'case_ids',
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
    'expected_file',
    'expected_sha256',
    'brake_model_sha256',
    'clearance_schema_version',
    'stop_requirement_schema_version',
)

_STRUCTURAL_FIELDS = frozenset({
    'segment_id',
    'role',
    'vehicle_config',
    'vehicle_config_sha256',
    'cases_file',
    'cases_sha256',
    'case_ids',
    'methods',
    'execution_path',
    'expected_file',
    'expected_sha256',
    'brake_model_sha256',
    'clearance_schema_version',
    'stop_requirement_schema_version',
})
# expected.segments[*].defaults.run_params 必须显式声明这些字段（无隐式默认）。
PARAM_FIELDS = tuple(
    field for field in RUN_PLAN_FIELDS if field not in _STRUCTURAL_FIELDS)
_EXPECTED_STRUCTURAL_PARAMS = ('vehicle_config', 'methods', 'execution_path')
EXPECTED_RUN_PARAM_FIELDS = _EXPECTED_STRUCTURAL_PARAMS + PARAM_FIELDS

_FLOAT_FIELDS = frozenset({
    'obs_delay_s',
    'action_delay_s',
    'stop_distance_m',
    'post_abort_observe_s',
    'clock_offset_ms',
    'clock_drift_ppm',
    'clock_uncertainty_ms',
    'transport_stall_delay_s',
})
_INT_FIELDS = frozenset({
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'sync_fail_step',
    'obs_mapping_fail_step',
    'transport_stall_step',
})
_NON_NEGATIVE_FIELDS = frozenset({
    'obs_delay_s',
    'action_delay_s',
    'post_abort_observe_s',
    'transport_stall_delay_s',
    'clock_uncertainty_ms',
})
_POSITIVE_FIELDS = frozenset({
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'stop_distance_m',
})
_STEP_FIELDS = frozenset({
    'sync_fail_step',
    'obs_mapping_fail_step',
    'transport_stall_step',
})

_REQUIRED_CASE_KEYS = (
    'scenario_class',
    'acceptable_outcomes',
    'must_conditions',
    'unsupported_allowed',
    'repeats',
)
_SEGMENT_KEYS = ('cases', 'defaults')
_DEFAULTS_REQUIRED_KEYS = ('cases_file', 'case_ids', 'run_params')
_TTL_CRITERIA_TRUE_KEYS = (
    'rejected_before_executed',
    'rejected_action_not_executed',
    'old_valid_setpoint_before_first_reject',
    'expiry_to_none',
    'zero_target_fallback',
)

_SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_COMMIT_PATTERN = re.compile(r'^[0-9a-f]{7,64}$')
_SUPPORT_SCOPE_KEYS = (
    'scope',
    'evidence_domain',
    'simulation_models',
    'brake_model_version',
    'brake_model_speed_support_mps',
    'vehicle_configs',
    'limitations',
)


class BoundaryFreezeError(ValueError):
    """冻结/计划/预期违反 clearance 边界契约时抛出（错误码在异常消息前缀）。"""


# ---------------------------------------------------------------------------
# 基础归一化
# ---------------------------------------------------------------------------

def _as_float(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 必须是数字，得到 {value!r}')
    number = float(value)
    if not math.isfinite(number):
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 必须是有限数，得到 {value!r}')
    return round(number, 6)


def _as_int(value, field):
    if isinstance(value, bool):
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 必须是整数，得到 {value!r}')
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise BoundaryFreezeError(
        f'{field.upper()}_INVALID: 必须是整数，得到 {value!r}')


def _as_text(value, field):
    if not isinstance(value, str):
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 必须是字符串，得到 {value!r}')
    return value


def _as_non_empty_text(value, field):
    text = _as_text(value, field).strip()
    if not text:
        raise BoundaryFreezeError(f'{field.upper()}_INVALID: 不能为空')
    return text


def _as_sha256(value, field):
    text = _as_text(value, field).strip().lower()
    if not _SHA256_PATTERN.match(text):
        raise BoundaryFreezeError(f'HASH_INVALID: {field} 必须是 64 位小写十六进制')
    return text


def _as_commit(value):
    text = _as_text(value, 'code_commit').strip().lower()
    if not _COMMIT_PATTERN.match(text):
        raise BoundaryFreezeError(
            f'CODE_COMMIT_INVALID: 必须是 git commit sha，得到 {value!r}')
    return text


def _as_path_text(value, field):
    text = _as_text(value, field).strip()
    if not text:
        raise BoundaryFreezeError(f'{field.upper()}_INVALID: 不能为空')
    return Path(text).as_posix()


def _as_vehicle_config(value):
    path = _as_path_text(value, 'vehicle_config')
    if not path.lower().endswith(('.yaml', '.yml')):
        raise BoundaryFreezeError(
            f'VEHICLE_CONFIG_INVALID: 必须是 yaml 路径，得到 {path!r}')
    return path


def _as_string_list(value, field, *, allow_empty=False):
    if isinstance(value, (str, bytes)):
        raise BoundaryFreezeError(f'{field.upper()}_INVALID: 必须是字符串列表')
    try:
        items = list(value)
    except TypeError as error:
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 必须是字符串列表') from error
    if not items and not allow_empty:
        raise BoundaryFreezeError(f'{field.upper()}_INVALID: 不能为空')
    result = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise BoundaryFreezeError(
                f'{field.upper()}_INVALID: 非法字符串项 {item!r}')
        result.append(item.strip())
    return result


def _as_case_ids(value):
    case_ids = _as_string_list(value, 'case_ids')
    if len(set(case_ids)) != len(case_ids):
        raise BoundaryFreezeError('CASE_IDS_DUPLICATE: case_ids 不得重复')
    return sorted(case_ids)


def _as_methods(value):
    methods = _as_string_list(value, 'methods')
    unknown = [method for method in methods if method not in METHODS]
    if unknown:
        raise BoundaryFreezeError(
            'METHODS_INVALID: 未知方法 ' + ', '.join(unknown)
            + f'（只允许 {METHODS}）')
    if len(set(methods)) != len(methods):
        raise BoundaryFreezeError('METHODS_DUPLICATE: methods 不得重复')
    return methods


def _as_outcome_list(value, field):
    outcomes = _as_string_list(value, field)
    unknown = [outcome for outcome in outcomes if outcome not in BUSINESS_OUTCOMES]
    if unknown:
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 未知业务结果 ' + ', '.join(unknown)
            + f'（只允许 {BUSINESS_OUTCOMES}）')
    if len(set(outcomes)) != len(outcomes):
        raise BoundaryFreezeError(f'{field.upper()}_DUPLICATE: 结果类别不得重复')
    return list(outcomes)


def _parse_aware_iso(value, field):
    text = _as_text(value, field).strip()
    if not text:
        raise BoundaryFreezeError(f'{field.upper()}_INVALID: 不能为空')
    candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise BoundaryFreezeError(
            f'{field.upper()}_INVALID: 无法解析 ISO 时间 {value!r}') from error
    if parsed.tzinfo is None:
        raise BoundaryFreezeError(
            f'{field.upper()}_TIMEZONE_REQUIRED: 必须带时区（UTC），得到 {value!r}')
    return parsed


# ---------------------------------------------------------------------------
# run_plan
# ---------------------------------------------------------------------------

def build_run_plan(**kwargs):
    """按固定字段与归一化规则构造一次段运行的冻结计划（见模块说明）。"""
    unknown = sorted(set(kwargs) - set(RUN_PLAN_FIELDS))
    if unknown:
        raise BoundaryFreezeError('UNKNOWN_RUN_PLAN_FIELD: ' + ', '.join(unknown))
    missing = [field for field in RUN_PLAN_FIELDS if field not in kwargs]
    if missing:
        raise BoundaryFreezeError('MISSING_RUN_PLAN_FIELD: ' + ', '.join(missing))

    segment_id = _as_text(kwargs['segment_id'], 'segment_id').strip()
    if segment_id not in SEGMENT_ROLES:
        raise BoundaryFreezeError(
            f'SEGMENT_ID_INVALID: {segment_id!r}（只允许 {SEGMENT_IDS}）')
    role = _as_text(kwargs['role'], 'role')
    expected_role = SEGMENT_ROLES[segment_id]
    if role != expected_role:
        raise BoundaryFreezeError(
            'SEGMENT_ROLE_MISMATCH: segment_id=' + segment_id
            + f' 必须使用 role={expected_role!r}，得到 {role!r}')

    methods = _as_methods(kwargs['methods'])
    execution_path = _as_text(kwargs['execution_path'], 'execution_path')
    if execution_path not in EXECUTION_PATHS:
        raise BoundaryFreezeError(
            f'EXECUTION_PATH_INVALID: {execution_path!r}（只允许 {EXECUTION_PATHS}）')
    if _as_text(kwargs['clearance_schema_version'],
                'clearance_schema_version') != CLEARANCE_SCHEMA_VERSION:
        raise BoundaryFreezeError(
            'CLEARANCE_SCHEMA_VERSION_MISMATCH: 期望 '
            + CLEARANCE_SCHEMA_VERSION)
    if _as_text(kwargs['stop_requirement_schema_version'],
                'stop_requirement_schema_version') != STOP_REQUIREMENT_SCHEMA_VERSION:
        raise BoundaryFreezeError(
            'STOP_REQUIREMENT_SCHEMA_VERSION_MISMATCH: 期望 '
            + STOP_REQUIREMENT_SCHEMA_VERSION)

    plan = {
        'segment_id': segment_id,
        'role': role,
        'vehicle_config': _as_vehicle_config(kwargs['vehicle_config']),
        'vehicle_config_sha256': _as_sha256(
            kwargs['vehicle_config_sha256'], 'vehicle_config_sha256'),
        'cases_file': _as_path_text(kwargs['cases_file'], 'cases_file'),
        'cases_sha256': _as_sha256(kwargs['cases_sha256'], 'cases_sha256'),
        'case_ids': _as_case_ids(kwargs['case_ids']),
        'methods': methods,
        'execution_path': execution_path,
        'expected_file': _as_path_text(kwargs['expected_file'], 'expected_file'),
        'expected_sha256': _as_sha256(
            kwargs['expected_sha256'], 'expected_sha256'),
        'brake_model_sha256': _as_sha256(
            kwargs['brake_model_sha256'], 'brake_model_sha256'),
        'clearance_schema_version': CLEARANCE_SCHEMA_VERSION,
        'stop_requirement_schema_version': STOP_REQUIREMENT_SCHEMA_VERSION,
    }
    for field in _FLOAT_FIELDS:
        plan[field] = _as_float(kwargs[field], field)
    for field in _INT_FIELDS:
        plan[field] = _as_int(kwargs[field], field)
    for field in _NON_NEGATIVE_FIELDS:
        if plan[field] < 0:
            raise BoundaryFreezeError(f'{field.upper()}_NEGATIVE: 不得为负')
    for field in _POSITIVE_FIELDS:
        if plan[field] <= 0:
            raise BoundaryFreezeError(f'{field.upper()}_INVALID: 必须为正')
    for field in _STEP_FIELDS:
        if plan[field] < -1:
            raise BoundaryFreezeError(
                f'{field.upper()}_INVALID: 步索引必须 >= -1（-1 表示不启用）')
    return {field: plan[field] for field in RUN_PLAN_FIELDS}


def _normalize_run_plan(run_plan, context):
    if not isinstance(run_plan, dict):
        raise BoundaryFreezeError(f'RUN_PLAN_INVALID: {context} 必须是对象')
    missing = [field for field in RUN_PLAN_FIELDS if field not in run_plan]
    if missing:
        raise BoundaryFreezeError(
            f'RUN_PLAN_FIELD_MISSING: {context} 缺少 ' + ', '.join(missing))
    try:
        return build_run_plan(
            **{field: run_plan[field] for field in RUN_PLAN_FIELDS})
    except BoundaryFreezeError as error:
        raise BoundaryFreezeError(f'{error}（{context}）') from error


def _check_freeze_schema(freeze):
    if not isinstance(freeze, dict):
        raise BoundaryFreezeError('SCHEMA_VERSION_MISMATCH: freeze 必须是 JSON 对象')
    if freeze.get('schema_version') != CLEARANCE_BOUNDARY_FREEZE_SCHEMA:
        raise BoundaryFreezeError(
            'SCHEMA_VERSION_MISMATCH: 期望 '
            f'{CLEARANCE_BOUNDARY_FREEZE_SCHEMA}，'
            f'得到 {freeze.get("schema_version")!r}')


def validate_run_plan(freeze, segment_id, run_plan):
    """逐字段比对运行器实际 run_plan 与冻结计划；首个不一致抛错。

    签名固定为 ``validate_run_plan(freeze, segment_id, run_plan)``：冻结按
    segment 唯一确定 role/cases/参数，运行器只需给出段名。
    """
    _check_freeze_schema(freeze)
    if not isinstance(segment_id, str) or segment_id not in SEGMENT_ROLES:
        raise BoundaryFreezeError(
            f'SEGMENT_ID_INVALID: {segment_id!r}（只允许 {SEGMENT_IDS}）')
    segments = freeze.get('segments')
    if not isinstance(segments, dict):
        raise BoundaryFreezeError('SEGMENTS_MISSING: 冻结中没有 segments')
    if segment_id not in segments:
        raise BoundaryFreezeError(
            f'PLAN_NOT_FROZEN: segment_id={segment_id!r} 未冻结')
    entry = segments[segment_id]
    if not isinstance(entry, dict) or 'run_plan' not in entry:
        raise BoundaryFreezeError(
            f'SEGMENT_RUN_PLAN_MISSING: segment_id={segment_id!r}')
    expected = _normalize_run_plan(
        entry['run_plan'], f'frozen segment {segment_id}')
    actual = _normalize_run_plan(run_plan, f'actual segment {segment_id}')
    for field in RUN_PLAN_FIELDS:
        if expected[field] != actual[field]:
            raise BoundaryFreezeError(
                'RUN_PLAN_MISMATCH field=' + field
                + ' expected=' + repr(expected[field])
                + ' actual=' + repr(actual[field]))
    return None


# ---------------------------------------------------------------------------
# git / 工作树状态
# ---------------------------------------------------------------------------

def _run_git(repo_root, args):
    try:
        completed = subprocess.run(
            ['git', *args], cwd=str(repo_root), capture_output=True,
            text=True, encoding='utf-8', errors='replace')
    except OSError as error:
        raise BoundaryFreezeError(f'GIT_UNAVAILABLE: {error}') from error
    if completed.returncode != 0:
        raise BoundaryFreezeError(
            'GIT_FAILED: git ' + ' '.join(args) + ': '
            + (completed.stderr or '').strip())
    return completed.stdout


def git_head(repo_root):
    """返回仓库当前 HEAD 的完整 commit sha（冻结生成与世系校验共用）。"""
    head = _run_git(repo_root, ['rev-parse', 'HEAD']).strip().lower()
    if not _COMMIT_PATTERN.match(head):
        raise BoundaryFreezeError(f'CODE_COMMIT_INVALID: git HEAD={head!r}')
    return head


def _normalize_status_text(text):
    """与 ``latency_plan._normalize_status_text`` **完全相同**的归一化规则。

    ``\\r\\n`` → ``\\n``、逐行 rstrip、丢弃行尾空行、``\\n``.join，
    **不带末尾换行**；随后对 UTF-8 字节做 sha256。
    """
    normalized = text.replace('\r\n', '\n')
    lines = [line.rstrip() for line in normalized.split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def _status_digest(text):
    return hashlib.sha256(_normalize_status_text(text).encode('utf-8')).hexdigest()


def worktree_state(repo_root, extra_untracked_paths=()):
    """``git status --porcelain -- src scripts tests configs`` 的状态摘要。

    ``extra_untracked_paths`` 仅用于生成预演（模拟将要写出、当前尚不存在的
    冻结文件）；实际生成脚本用两遍写出 + 真实重算，不依赖该模拟。
    """
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


def check_freeze_lineage(freeze, now_iso, repo_root):
    """校验冻结生成时刻/代码提交/工作树状态；不得未来时间或运行后倒填。"""
    _check_freeze_schema(freeze)
    if freeze.get('status') != FREEZE_STATUS:
        raise BoundaryFreezeError(
            f'FREEZE_STATUS_INVALID: 必须是 {FREEZE_STATUS}，'
            f'得到 {freeze.get("status")!r}')
    frozen_at = _parse_aware_iso(freeze.get('frozen_at'), 'frozen_at')
    now = _parse_aware_iso(now_iso, 'now_iso')
    if frozen_at > now:
        raise BoundaryFreezeError(
            'FROZEN_AT_IN_FUTURE: frozen_at 晚于当前时间（禁止未来时间/倒填）: '
            f'frozen_at={freeze.get("frozen_at")!r} now={now_iso!r}')
    recorded_commit = _as_commit(freeze.get('code_commit'))
    head = git_head(repo_root)
    if recorded_commit != head:
        raise BoundaryFreezeError(
            f'CODE_COMMIT_MISMATCH: 冻结记录 {recorded_commit}，当前 HEAD {head}')
    state = freeze.get('worktree_state')
    if not isinstance(state, dict):
        raise BoundaryFreezeError('WORKTREE_STATE_INVALID: 缺少 worktree_state')
    recorded = state.get('status_text_sha256') or state.get('digest')
    recorded = _as_sha256(recorded, 'worktree_state.status_text_sha256')
    current = worktree_state(repo_root)['status_text_sha256']
    if recorded != current:
        raise BoundaryFreezeError(
            'WORKTREE_STATE_MISMATCH: 冻结后 src/scripts/tests/configs 发生变化；'
            '必须新建冻结版本并重跑受影响段')
    return None


# ---------------------------------------------------------------------------
# expected 校验
# ---------------------------------------------------------------------------

def _validate_case_condition(condition, context):
    if isinstance(condition, str):
        kind = condition.strip()
        if not kind:
            raise BoundaryFreezeError(
                f'EXPECTED_CONDITION_INVALID: {context} kind 不能为空')
        if kind not in MUST_CONDITION_KINDS:
            raise BoundaryFreezeError(
                f'EXPECTED_CONDITION_UNKNOWN: {context} 未知 kind {kind!r}'
                f'（只允许 {MUST_CONDITION_KINDS}）')
        if kind not in _NO_VALUE_CONDITION_KINDS:
            raise BoundaryFreezeError(
                f'EXPECTED_CONDITION_VALUE_REQUIRED: {context} kind={kind!r} '
                '必须写成 {kind, value}')
        return kind
    if not isinstance(condition, dict):
        raise BoundaryFreezeError(
            f'EXPECTED_CONDITION_INVALID: {context} 必须是字符串或对象')
    kind = condition.get('kind')
    if not isinstance(kind, str) or kind.strip() not in MUST_CONDITION_KINDS:
        raise BoundaryFreezeError(
            f'EXPECTED_CONDITION_UNKNOWN: {context}.kind={kind!r}'
            f'（只允许 {MUST_CONDITION_KINDS}）')
    kind = kind.strip()
    if kind in _NO_VALUE_CONDITION_KINDS:
        value = condition.get('value')
        if value is not None:
            raise BoundaryFreezeError(
                f'EXPECTED_CONDITION_VALUE_UNEXPECTED: {context} kind={kind!r} '
                '不接受 value')
        return {'kind': kind}
    value = condition.get('value')
    if value is None:
        raise BoundaryFreezeError(
            f'EXPECTED_CONDITION_VALUE_REQUIRED: {context} kind={kind!r} '
            '缺少 value')
    if kind in _OUTCOME_LIST_CONDITION_KINDS:
        return {'kind': kind,
                'value': _as_outcome_list(value, context + '.' + kind)}
    number = _as_float(value, context + '.' + kind)
    if number < 0:
        raise BoundaryFreezeError(
            f'EXPECTED_CONDITION_NEGATIVE: {context}.{kind} 不得为负')
    return {'kind': kind, 'value': number}


def _validate_expected_case(entry, context, *, require_scenario_class=True,
                            allow_empty_conditions=False):
    if not isinstance(entry, dict):
        raise BoundaryFreezeError(f'EXPECTED_CASE_INVALID: {context} 必须是对象')
    missing = [key for key in _REQUIRED_CASE_KEYS if key not in entry
               and not (key == 'scenario_class'
                        and not require_scenario_class)]
    if missing:
        raise BoundaryFreezeError(
            f'EXPECTED_CASE_MISSING: {context} 缺少 ' + ', '.join(missing))
    normalized = {}
    if require_scenario_class:
        scenario_class = _as_text(
            entry['scenario_class'], context + '.scenario_class')
        if scenario_class not in SCENARIO_CLASSES:
            raise BoundaryFreezeError(
                f'EXPECTED_CASE_CLASS_INVALID: {context}.scenario_class='
                f'{scenario_class!r}（只允许 {SCENARIO_CLASSES}）')
        normalized['scenario_class'] = scenario_class
    else:
        # special/regression 段按 Lead 2026-11-02 裁决不使用 8 类判定，
        # scenario_class 留空/省略（不得用边界类冒充）。
        scenario_class = entry.get('scenario_class')
        if scenario_class not in (None, ''):
            raise BoundaryFreezeError(
                f'EXPECTED_CASE_CLASS_NOT_ALLOWED: {context} 的非 boundary 段'
                '预期不得声明 scenario_class（按 Lead 裁决留空/省略）')
    acceptable = _as_outcome_list(
        entry['acceptable_outcomes'], context + '.acceptable_outcomes')
    conditions = entry['must_conditions']
    if not isinstance(conditions, list):
        raise BoundaryFreezeError(
            f'EXPECTED_CASE_INVALID: {context}.must_conditions 必须是列表')
    if not conditions and not allow_empty_conditions:
        raise BoundaryFreezeError(
            f'EXPECTED_CASE_INVALID: {context}.must_conditions 必须是非空列表')
    normalized_conditions = [
        _validate_case_condition(item, context + '.must_conditions[%d]' % index)
        for index, item in enumerate(conditions)]
    unsupported = entry['unsupported_allowed']
    if isinstance(unsupported, list):
        unsupported = _as_string_list(
            unsupported, context + '.unsupported_allowed')
    elif not isinstance(unsupported, bool):
        raise BoundaryFreezeError(
            f'EXPECTED_CASE_INVALID: {context}.unsupported_allowed 必须是布尔'
            '或 reason 列表')
    repeats = _as_int(entry['repeats'], context + '.repeats')
    if repeats < 1:
        raise BoundaryFreezeError(
            f'EXPECTED_CASE_INVALID: {context}.repeats 必须 >= 1'
            '（逐 _r0/_r1 的独立 case_id 为 1）')
    normalized.update({
        'acceptable_outcomes': acceptable,
        'must_conditions': normalized_conditions,
        'unsupported_allowed': unsupported,
        'repeats': repeats,
    })
    for key in ('design', 'performance_note', 'note'):
        if key in entry:
            normalized[key] = _as_non_empty_text(entry[key], context + '.' + key)
    return normalized


def _validate_clock_paths(value, context):
    if not isinstance(value, list) or not value:
        raise BoundaryFreezeError(
            f'ACCEPTABLE_PATHS_INVALID: {context} 必须是非空列表')
    normalized = []
    priorities = []
    for index, item in enumerate(value):
        item_context = f'{context}[{index}]'
        if not isinstance(item, dict):
            raise BoundaryFreezeError(
                f'ACCEPTABLE_PATHS_INVALID: {item_context} 必须是对象')
        priority = _as_int(item.get('priority'), item_context + '.priority')
        if priority < 1 or priority in priorities:
            raise BoundaryFreezeError(
                f'ACCEPTABLE_PATHS_PRIORITY_INVALID: {item_context}.priority '
                '必须唯一且 >= 1')
        priorities.append(priority)
        path_id = _as_non_empty_text(item.get('path_id'), item_context + '.path_id')
        reason_keys = [key for key in (
            'admission_reject_reason',
            'arrival_reject_reason',
            'observation_reason',
            'supervisor_reason',
            'episode_reason',
            'reason',
        ) if key in item]
        if not reason_keys:
            raise BoundaryFreezeError(
                f'ACCEPTABLE_PATHS_REASON_MISSING: {item_context} 至少声明一个 '
                'admission_reject_reason/arrival_reject_reason/'
                'observation_reason/supervisor_reason/episode_reason/reason')
        entry = {'priority': priority, 'path_id': path_id}
        for key in reason_keys:
            entry[key] = _as_non_empty_text(item[key], item_context + '.' + key)
        for key in ('supervisor_state', 'note'):
            if key in item:
                entry[key] = _as_non_empty_text(item[key], item_context + '.' + key)
        normalized.append(entry)
    normalized.sort(key=lambda item: item['priority'])
    return normalized


def _validate_ttl_criteria(value, context):
    if not isinstance(value, dict) or not value:
        raise BoundaryFreezeError(f'TTL_CRITERIA_INVALID: {context} 必须是非空对象')
    normalized = {}
    for key in _TTL_CRITERIA_TRUE_KEYS:
        if key not in value:
            raise BoundaryFreezeError(f'TTL_CRITERIA_MISSING: {context}.{key}')
        if value[key] is not True:
            raise BoundaryFreezeError(
                f'TTL_CRITERIA_INVALID: {context}.{key} 必须为 true（(c) 判据）')
        normalized[key] = True
    business = _as_outcome_list(
        value.get('business_outcomes'), context + '.business_outcomes')
    if not set(business) <= {'ABORT', 'TIMEOUT'}:
        raise BoundaryFreezeError(
            f'TTL_CRITERIA_INVALID: {context}.business_outcomes 只允许 '
            'ABORT/TIMEOUT（业务结果之一）')
    normalized['business_outcomes'] = business
    return normalized


def _validate_freeze_rule(value, context):
    rule = _as_non_empty_text(value, context)
    if EXPECTED_FREEZE_RULE not in rule:
        raise BoundaryFreezeError(
            f'FREEZE_RULE_INVALID: {context} 必须包含 {EXPECTED_FREEZE_RULE!r}'
            '（禁止事后扩展可接受集合）')
    return rule


def _validate_run_params(value, plan, context):
    if not isinstance(value, dict):
        raise BoundaryFreezeError(
            f'RUN_PARAMS_INVALID: {context} 必须是对象')
    missing = [field for field in EXPECTED_RUN_PARAM_FIELDS if field not in value]
    if missing:
        raise BoundaryFreezeError(
            f'RUN_PARAMS_MISSING: {context} 缺少 ' + ', '.join(missing))
    unknown = sorted(set(value) - set(EXPECTED_RUN_PARAM_FIELDS))
    if unknown:
        raise BoundaryFreezeError(
            f'RUN_PARAMS_UNKNOWN_KEY: {context} 含未知键 ' + ', '.join(unknown))
    normalized = {}
    for field in EXPECTED_RUN_PARAM_FIELDS:
        if field == 'vehicle_config':
            normalized[field] = _as_vehicle_config(value[field])
        elif field == 'methods':
            normalized[field] = _as_methods(value[field])
        elif field == 'execution_path':
            path = _as_text(value[field], 'execution_path')
            if path not in EXECUTION_PATHS:
                raise BoundaryFreezeError(
                    f'EXECUTION_PATH_INVALID: {path!r}（只允许 {EXECUTION_PATHS}）')
            normalized[field] = path
        else:
            normalized[field] = _normalize_param(field, value[field])
        if normalized[field] != plan[field]:
            raise BoundaryFreezeError(
                'EXPECTED_RUN_PARAM_MISMATCH field=' + field
                + ' expected=' + repr(normalized[field])
                + ' run_plan=' + repr(plan[field]))
    return normalized


def _normalize_param(field, value):
    """把 expected/run_params 的单个字段按 run_plan 规则归一化（供核对）。"""
    if field in _FLOAT_FIELDS:
        return _as_float(value, field)
    if field in _INT_FIELDS:
        return _as_int(value, field)
    raise BoundaryFreezeError(f'RUN_PARAMS_FIELD_INVALID: {field!r} 不是参数字段')


def _validate_special_defaults(segment_id, defaults, context):
    normalized = {}
    if segment_id == 'latency_clock_mapping_recheck':
        normalized['acceptable_paths'] = _validate_clock_paths(
            defaults.get('acceptable_paths'), context + '.acceptable_paths')
        if defaults.get('must_hit_declared_path') is not True:
            raise BoundaryFreezeError(
                f'EXPECTED_SEGMENT_INVALID: {context}.must_hit_declared_path '
                '必须为 true')
        normalized['must_hit_declared_path'] = True
    elif segment_id == 'latency_ttl_over_recheck':
        criteria_id = _as_text(
            defaults.get('criteria_id'), context + '.criteria_id')
        if criteria_id != '(c)':
            raise BoundaryFreezeError(
                f'EXPECTED_SEGMENT_INVALID: {context}.criteria_id 必须是 (c)')
        normalized['criteria_id'] = criteria_id
        normalized['criteria'] = _validate_ttl_criteria(
            defaults.get('criteria'), context + '.criteria')
        if 'acceptable_outcomes' in defaults:
            normalized['acceptable_outcomes'] = _as_outcome_list(
                defaults['acceptable_outcomes'],
                context + '.acceptable_outcomes')
    normalized['freeze_rule'] = _validate_freeze_rule(
        defaults.get('freeze_rule'), context + '.freeze_rule')
    return normalized


def _validate_expected_segment(segment_id, entry, plan, expected_payload):
    context = 'expected.segments.' + segment_id
    if not isinstance(entry, dict):
        raise BoundaryFreezeError(
            f'EXPECTED_SEGMENT_INVALID: {context} 必须是对象')
    unknown = sorted(set(entry) - set(_SEGMENT_KEYS))
    if unknown:
        raise BoundaryFreezeError(
            f'EXPECTED_SEGMENT_UNKNOWN_KEY: {context} 含未知键 '
            + ', '.join(unknown) + '（只允许 cases/defaults）')
    defaults = entry.get('defaults')
    if not isinstance(defaults, dict):
        raise BoundaryFreezeError(
            f'EXPECTED_SEGMENT_INVALID: {context}.defaults 必须是对象')
    missing = [key for key in _DEFAULTS_REQUIRED_KEYS if key not in defaults]
    if missing:
        raise BoundaryFreezeError(
            f'EXPECTED_SEGMENT_DEFAULTS_MISSING: {context}.defaults 缺少 '
            + ', '.join(missing))
    cases_file = _as_path_text(
        defaults['cases_file'], context + '.defaults.cases_file')
    if cases_file != plan['cases_file']:
        raise BoundaryFreezeError(
            'EXPECTED_SEGMENT_CASES_FILE_MISMATCH: ' + context
            + f' cases_file={cases_file!r} != run_plan {plan["cases_file"]!r}')
    case_ids = _as_case_ids(defaults['case_ids'])
    if case_ids != plan['case_ids']:
        raise BoundaryFreezeError(
            'EXPECTED_SEGMENT_CASE_IDS_MISMATCH: ' + context
            + ' case_ids 与 run_plan 不一致')
    run_params = _validate_run_params(
        defaults['run_params'], plan, context + '.defaults.run_params')
    normalized = {
        'cases_file': cases_file,
        'case_ids': case_ids,
        'run_params': run_params,
    }
    for key in ('purpose', 'note'):
        if key in defaults:
            normalized[key] = _as_non_empty_text(
                defaults[key], context + '.defaults.' + key)
    segment_cases = entry.get('cases')
    if not isinstance(segment_cases, dict):
        raise BoundaryFreezeError(
            f'EXPECTED_SEGMENT_INVALID: {context}.cases 必须是对象')
    if plan['role'] == ROLE_BOUNDARY:
        normalized['cases'] = {}
        for case_id, case_entry in segment_cases.items():
            if case_id not in expected_payload['cases']:
                raise BoundaryFreezeError(
                    f'EXPECTED_CASE_MISSING: {context} 引用的 {case_id!r} '
                    '不在 expected.cases 中')
            if case_entry != expected_payload['cases'][case_id]:
                raise BoundaryFreezeError(
                    'EXPECTED_CASE_DUPLICATE_MISMATCH: ' + context
                    + f' cases.{case_id} 与顶层 cases 条目不一致')
        if set(segment_cases) == set(case_ids):
            normalized['cases'] = dict(segment_cases)
        else:
            for case_id in case_ids:
                if case_id not in expected_payload['cases']:
                    raise BoundaryFreezeError(
                        f'EXPECTED_CASE_MISSING: {context} 的 {case_id!r} '
                        '不在 expected.cases 中')
    else:
        if set(segment_cases) != set(case_ids):
            raise BoundaryFreezeError(
                f'EXPECTED_SEGMENT_CASES_MISSING: {context}.cases 必须恰好覆盖 '
                'case_ids')
        normalized['cases'] = {
            case_id: _validate_expected_case(
                segment_cases[case_id], f'{context}.cases.{case_id}',
                require_scenario_class=False, allow_empty_conditions=True)
            for case_id in case_ids
        }
        normalized.update(_validate_special_defaults(
            segment_id, defaults, context + '.defaults'))
    return normalized


def _validate_expected_payload(expected, expected_file, expected_sha256,
                               segment_run_plans):
    if not isinstance(expected, dict):
        raise BoundaryFreezeError('EXPECTED_INVALID: expected 必须是对象')
    if expected.get('schema_version') != CLEARANCE_BOUNDARY_EXPECTED_SCHEMA:
        raise BoundaryFreezeError(
            'EXPECTED_SCHEMA_MISMATCH: 期望 '
            f'{CLEARANCE_BOUNDARY_EXPECTED_SCHEMA}，'
            f'得到 {expected.get("schema_version")!r}')
    if expected.get('status') != EXPECTED_STATUS:
        raise BoundaryFreezeError(
            f'EXPECTED_STATUS_INVALID: 必须是 {EXPECTED_STATUS}'
            '（预期非结论）')
    note = _as_non_empty_text(expected.get('note'), 'expected.note')
    if '预期非结论' not in note:
        raise BoundaryFreezeError(
            'EXPECTED_NOTE_INVALID: expected.note 必须写明"预期非结论"')
    freeze_rule = _validate_freeze_rule(
        expected.get('freeze_rule'), 'expected.freeze_rule')
    cases = expected.get('cases')
    if not isinstance(cases, dict) or not cases:
        raise BoundaryFreezeError(
            'EXPECTED_CASES_INVALID: expected.cases 必须是非空对象')
    normalized_cases = {
        case_id: _validate_expected_case(
            cases[case_id], 'expected.cases.' + case_id)
        for case_id in cases
    }
    segments = expected.get('segments')
    if not isinstance(segments, dict):
        raise BoundaryFreezeError(
            'EXPECTED_SEGMENTS_INVALID: expected.segments 必须是对象')
    if set(segments) != set(EXPECTED_SEGMENT_IDS):
        raise BoundaryFreezeError(
            'EXPECTED_SEGMENTS_MISMATCH: expected.segments 必须恰好包含 '
            + repr(EXPECTED_SEGMENT_IDS) + '，得到 ' + repr(tuple(segments))
            + '（regression 段按 U3 契约不写预冻结预期，使用既有证据）')
    if set(segment_run_plans) != set(SEGMENT_IDS):
        raise BoundaryFreezeError(
            'SEGMENTS_MISMATCH: 冻结必须恰好包含 ' + repr(SEGMENT_IDS)
            + '，得到 ' + repr(tuple(segment_run_plans)))
    normalized_segments = {}
    boundary_case_ids = set()
    for segment_id in SEGMENT_IDS:
        plan = _normalize_run_plan(
            segment_run_plans[segment_id], f'run plan {segment_id}')
        if plan['segment_id'] != segment_id:
            raise BoundaryFreezeError(
                'SEGMENT_ID_MISMATCH: 键 ' + segment_id
                + f' != run_plan.segment_id {plan["segment_id"]!r}')
        if plan['role'] != SEGMENT_ROLES[segment_id]:
            raise BoundaryFreezeError('SEGMENT_ROLE_MISMATCH: ' + segment_id)
        if plan['expected_file'] != expected_file:
            raise BoundaryFreezeError(
                'EXPECTED_FILE_MISMATCH: ' + segment_id
                + f' run_plan.expected_file={plan["expected_file"]!r}'
                f' != {expected_file!r}')
        if plan['expected_sha256'] != expected_sha256:
            raise BoundaryFreezeError(
                'EXPECTED_SHA256_MISMATCH: ' + segment_id
                + ' run_plan.expected_sha256 与 expected 文件 sha256 不一致')
        if segment_id in EXPECTED_SEGMENT_IDS:
            normalized_segments[segment_id] = _validate_expected_segment(
                segment_id, segments[segment_id], plan,
                {'cases': normalized_cases})
            if plan['role'] == ROLE_BOUNDARY:
                boundary_case_ids.update(normalized_segments[segment_id]
                                         ['case_ids'])
        else:
            normalized_segments[segment_id] = None
    expected_case_ids = set(normalized_cases)
    if expected_case_ids != boundary_case_ids:
        raise BoundaryFreezeError(
            'EXPECTED_CASES_MISMATCH: expected.cases 与 boundary 段 case_ids 不一致：'
            ' missing=' + repr(sorted(boundary_case_ids - expected_case_ids))
            + ' unexpected=' + repr(sorted(expected_case_ids - boundary_case_ids)))
    normalized_payload = {
        'schema_version': CLEARANCE_BOUNDARY_EXPECTED_SCHEMA,
        'status': EXPECTED_STATUS,
        'note': note,
        'freeze_rule': freeze_rule,
        'cases': normalized_cases,
        'segments': {
            segment_id: normalized_segments[segment_id]
            for segment_id in EXPECTED_SEGMENT_IDS
        },
    }
    if 'basis' in expected:
        normalized_payload['basis'] = _as_non_empty_text(
            expected['basis'], 'expected.basis')
    if 'brake_model' in expected:
        brake = expected['brake_model']
        if not isinstance(brake, dict):
            raise BoundaryFreezeError(
                'EXPECTED_BRAKE_MODEL_INVALID: expected.brake_model 必须是对象')
        normalized_brake = {}
        if 'file' in brake:
            normalized_brake['file'] = _as_path_text(
                brake['file'], 'expected.brake_model.file')
        if 'version' in brake:
            normalized_brake['version'] = _as_non_empty_text(
                brake['version'], 'expected.brake_model.version')
        support = brake.get('speed_support_mps')
        if support is not None:
            low, high = _validate_speed_support(
                support, 'expected.brake_model')
            normalized_brake['speed_support_mps'] = [low, high]
        normalized_payload['brake_model'] = normalized_brake
    return normalized_payload, normalized_segments


def _validate_speed_support(value, context):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise BoundaryFreezeError(
            f'{context.upper()}_SPEED_SUPPORT_INVALID: 必须是 [low, high]')
    low = _as_float(value[0], context + '.speed_support_mps[0]')
    high = _as_float(value[1], context + '.speed_support_mps[1]')
    if low < 0 or not low < high:
        raise BoundaryFreezeError(
            f'{context.upper()}_SPEED_SUPPORT_INVALID: 必须 0 <= low < high')
    return low, high


# ---------------------------------------------------------------------------
# 冻结组装
# ---------------------------------------------------------------------------

def _normalize_cases_index(cases):
    if not isinstance(cases, (list, tuple)) or not cases:
        raise BoundaryFreezeError('CASES_INVALID: cases 必须是非空列表')
    index = {}
    for entry in cases:
        if not isinstance(entry, dict):
            raise BoundaryFreezeError('CASES_INVALID: cases[*] 必须是对象')
        cases_file = _as_path_text(entry.get('cases_file'), 'cases_file')
        sha = _as_sha256(entry.get('cases_sha256'), 'cases_sha256')
        if cases_file in index and index[cases_file] != sha:
            raise BoundaryFreezeError(
                f'CASES_INVALID: 同一 cases_file 出现不同 sha256: {cases_file}')
        index[cases_file] = sha
    return index


def _normalize_map_state(map_state):
    if not isinstance(map_state, dict):
        raise BoundaryFreezeError('MAP_STATE_INVALID: 必须是对象')
    asset_id = _as_non_empty_text(map_state.get('map_asset_id'), 'map_asset_id')
    normalized = {
        'map_asset_id': asset_id,
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
        raise BoundaryFreezeError('WORKTREE_STATE_INVALID: 必须是对象')
    tracked_paths = worktree_state.get('tracked_paths')
    if tracked_paths != list(TRACKED_PATHS):
        raise BoundaryFreezeError(
            'WORKTREE_STATE_INVALID: tracked_paths 必须是 '
            + repr(list(TRACKED_PATHS)))
    return {
        'tracked_paths': list(TRACKED_PATHS),
        'status_text_sha256': _as_sha256(
            worktree_state.get('status_text_sha256'),
            'worktree_state.status_text_sha256'),
        'clean': bool(worktree_state.get('clean')),
    }


def _default_support_scope(vehicle_configs, brake_version, speed_support):
    return {
        'scope': FREEZE_SCOPE,
        'evidence_domain': 'GUI Isaac Lab simulation (DirectX/D3D12); '
                           '非 SITL/HIL/实机',
        'simulation_models': [
            'kinematic_obstacle',
            'velocity_chain',
            'simulated_camera_clock',
            'oracle_observation',
        ],
        'brake_model_version': brake_version,
        'brake_model_speed_support_mps': list(speed_support),
        'vehicle_configs': dict(vehicle_configs),
        'limitations': [
            '制动模型只允许在实测支持区间内分段线性插值，区间外不外推',
            '支持区间外速度必须标 UNSUPPORTED，不得当作已验证安全余量',
            'AABB/球包络是保守近似，不是网格扫掠或实机安全证明',
            '快速车 max_horizontal_mps=0.9 是 PROPOSED，不是实测飞机限制',
            '相机时钟域是模拟第二时钟，不存在真实多设备时钟/串口延迟',
            '预期非结论；实际以独立核验从原始 steps/episodes/manifest 重算为准',
            '本冻结只覆盖当前仿真模型，不提升任何 Gate',
        ],
    }


def _normalize_support_scope(support_scope, vehicle_configs, brake_version,
                             speed_support):
    if support_scope is None:
        support_scope = _default_support_scope(
            vehicle_configs, brake_version, speed_support)
    if not isinstance(support_scope, dict):
        raise BoundaryFreezeError('SUPPORT_SCOPE_INVALID: 必须是对象')
    missing = [key for key in _SUPPORT_SCOPE_KEYS if key not in support_scope]
    if missing:
        raise BoundaryFreezeError(
            'SUPPORT_SCOPE_MISSING: ' + ', '.join(missing))
    normalized = {
        'scope': _as_text(support_scope['scope'], 'support_scope.scope'),
        'evidence_domain': _as_non_empty_text(
            support_scope['evidence_domain'], 'support_scope.evidence_domain'),
        'simulation_models': _as_string_list(
            support_scope['simulation_models'],
            'support_scope.simulation_models'),
        'brake_model_version': _as_non_empty_text(
            support_scope['brake_model_version'],
            'support_scope.brake_model_version'),
        'brake_model_speed_support_mps': list(_validate_speed_support(
            support_scope['brake_model_speed_support_mps'], 'support_scope')),
        'vehicle_configs': {},
        'limitations': _as_string_list(
            support_scope['limitations'], 'support_scope.limitations'),
    }
    vehicle_scope = support_scope['vehicle_configs']
    if not isinstance(vehicle_scope, dict) or not vehicle_scope:
        raise BoundaryFreezeError(
            'SUPPORT_SCOPE_INVALID: support_scope.vehicle_configs 必须是非空对象')
    for path, label in vehicle_scope.items():
        normalized_path = _as_path_text(path, 'support_scope.vehicle_configs')
        normalized['vehicle_configs'][normalized_path] = _as_non_empty_text(
            label, 'support_scope.vehicle_configs.' + normalized_path)
    declared = set(normalized['vehicle_configs'])
    if set(vehicle_configs) - declared:
        raise BoundaryFreezeError(
            'SUPPORT_SCOPE_MISSING: support_scope.vehicle_configs 未覆盖 '
            + ', '.join(sorted(set(vehicle_configs) - declared)))
    if normalized['brake_model_version'] != brake_version:
        raise BoundaryFreezeError(
            'SUPPORT_SCOPE_MISMATCH: support_scope.brake_model_version='
            + repr(normalized['brake_model_version'])
            + ' 与 expected.brake_model.version=' + repr(brake_version) + ' 不一致')
    if list(normalized['brake_model_speed_support_mps']) != list(speed_support):
        raise BoundaryFreezeError(
            'SUPPORT_SCOPE_MISMATCH: support_scope.brake_model_speed_support_mps '
            '与 expected.brake_model.speed_support_mps 不一致')
    return normalized


def build_freeze(*, frozen_at, code_commit, worktree_state, map_state, cases,
                 segment_run_plans, expected, expected_file, expected_sha256,
                 brake_model_file, brake_model_sha256,
                 clearance_schema_version=CLEARANCE_SCHEMA_VERSION,
                 stop_requirement_schema_version=STOP_REQUIREMENT_SCHEMA_VERSION,
                 budget=None, support_scope=None, note=''):
    """组装 clearance 边界专项的**单文件多 segment** 预运行冻结。

    参数：
    - ``frozen_at``：真实 UTC 时间（带时区 ISO 8601，脚本自算，不接受倒填）；
    - ``code_commit``：真实 ``git rev-parse HEAD``；
    - ``worktree_state``：``worktree_state(repo_root)`` 的返回值；
    - ``map_state``：``{map_asset_id, terrain_sha256, preview_sha256,
      map_config_sha256[, map_config_file]}``；
    - ``cases``：``[{cases_file, cases_sha256}, ...]`` 声明本冻结用到的全部
      cases 文件；
    - ``segment_run_plans``：``{segment_id: run_plan}``，必须恰好覆盖
      ``SEGMENT_IDS``（9 段）；
    - ``expected`` / ``expected_file`` / ``expected_sha256``：expected JSON
      内容、仓库相对 posix 路径、文件 sha256；
    - ``brake_model_file`` / ``brake_model_sha256``：制动模型文件与 hash；
    - ``budget``：可省略（按 segment case 数派生）；给出时必须与派生值一致；
    - ``support_scope``：支持范围说明；省略时用保守默认（GUI 仿真域、
      brake_final4.v1、0.248041–0.851428 m/s 支持区间、不外推）；
    - ``note``：自由说明（必须写明预期非结论）。
    """
    frozen_at_text = _as_text(frozen_at, 'frozen_at')
    _parse_aware_iso(frozen_at_text, 'frozen_at')
    commit = _as_commit(code_commit)
    if clearance_schema_version != CLEARANCE_SCHEMA_VERSION:
        raise BoundaryFreezeError(
            'CLEARANCE_SCHEMA_VERSION_MISMATCH: 期望 '
            + CLEARANCE_SCHEMA_VERSION)
    if stop_requirement_schema_version != STOP_REQUIREMENT_SCHEMA_VERSION:
        raise BoundaryFreezeError(
            'STOP_REQUIREMENT_SCHEMA_VERSION_MISMATCH: 期望 '
            + STOP_REQUIREMENT_SCHEMA_VERSION)
    state = _normalize_worktree_state(worktree_state)
    map_state_normalized = _normalize_map_state(map_state)
    cases_index = _normalize_cases_index(cases)
    expected_file = _as_path_text(expected_file, 'expected_file')
    expected_sha256 = _as_sha256(expected_sha256, 'expected_sha256')
    brake_model_file = _as_path_text(brake_model_file, 'brake_model_file')
    brake_model_sha256 = _as_sha256(
        brake_model_sha256, 'brake_model_sha256')
    if not isinstance(segment_run_plans, dict):
        raise BoundaryFreezeError(
            'SEGMENT_RUN_PLANS_INVALID: segment_run_plans 必须是对象')

    normalized_expected, normalized_segments = _validate_expected_payload(
        expected, expected_file, expected_sha256, segment_run_plans)
    expected_brake = normalized_expected.get('brake_model') or {}
    if expected_brake.get('file') and expected_brake['file'] != brake_model_file:
        raise BoundaryFreezeError(
            'BRAKE_MODEL_FILE_MISMATCH: expected.brake_model.file='
            + repr(expected_brake['file']) + ' != ' + repr(brake_model_file))
    brake_version = (expected_brake.get('version')
                     or DEFAULT_BRAKE_MODEL_VERSION)
    speed_support = (expected_brake.get('speed_support_mps')
                     or list(BRAKE_MODEL_SPEED_SUPPORT_MPS))

    plans = {}
    for segment_id in SEGMENT_IDS:
        plan = _normalize_run_plan(
            segment_run_plans[segment_id], f'run plan {segment_id}')
        plans[segment_id] = plan
        if plan['cases_file'] not in cases_index:
            raise BoundaryFreezeError(
                f'CASE_FILE_NOT_DECLARED: {segment_id} 的 {plan["cases_file"]} '
                '不在 cases 声明中')
        if cases_index[plan['cases_file']] != plan['cases_sha256']:
            raise BoundaryFreezeError(
                f'CASE_SHA256_MISMATCH: {segment_id} 的 cases_sha256 与 '
                'cases 声明不一致')
        if plan['brake_model_sha256'] != brake_model_sha256:
            raise BoundaryFreezeError(
                f'BRAKE_MODEL_SHA256_MISMATCH: {segment_id} 的 '
                'run_plan.brake_model_sha256 与冻结 brake_model_sha256 不一致')

    segments = {}
    for segment_id in SEGMENT_IDS:
        plan = plans[segment_id]
        expected_entry = normalized_segments[segment_id]
        segments[segment_id] = {
            'segment_id': segment_id,
            'role': plan['role'],
            'purpose': ((expected_entry or {}).get('purpose')
                        or _segment_purpose(segment_id)),
            'cases_file': plan['cases_file'],
            'cases_sha256': plan['cases_sha256'],
            'case_ids': list(plan['case_ids']),
            'methods': list(plan['methods']),
            'run_plan': plan,
            'expected': expected_entry,
            'expected_note': (
                '预期非结论，实际以独立核验为准' if expected_entry is not None
                else 'regression 段按 U3 契约不写预冻结分类预期，对照既有证据'),
        }

    vehicle_configs = {}
    for segment_id, entry in segments.items():
        path = entry['run_plan']['vehicle_config']
        vehicle_configs[path] = ('fast_vehicle_PRO_POSED'
                                 if path == FAST_VEHICLE_CONFIG
                                 else 'default_vehicle')
    normalized_support = _normalize_support_scope(
        support_scope, vehicle_configs, brake_version, speed_support)

    derived_budget = {
        'boundary_episodes': sum(len(plans[segment]['case_ids'])
                                 for segment in BOUNDARY_SEGMENT_IDS),
        'special_episodes': sum(len(plans[segment]['case_ids'])
                                for segment in SPECIAL_SEGMENT_IDS),
        'regression_episodes': sum(len(plans[segment]['case_ids'])
                                   for segment in REGRESSION_SEGMENT_IDS),
    }
    derived_budget['total_episodes'] = (
        derived_budget['boundary_episodes']
        + derived_budget['special_episodes']
        + derived_budget['regression_episodes'])
    derived_budget['min_boundary_episodes_required'] = MIN_BOUNDARY_EPISODES
    if derived_budget['boundary_episodes'] < MIN_BOUNDARY_EPISODES:
        raise BoundaryFreezeError(
            'BOUNDARY_EPISODES_INSUFFICIENT: 边界段 episode 数 '
            f'{derived_budget["boundary_episodes"]} < {MIN_BOUNDARY_EPISODES}')
    if budget is None:
        normalized_budget = derived_budget
    else:
        if not isinstance(budget, dict):
            raise BoundaryFreezeError('BUDGET_INVALID: budget 必须是对象')
        unknown = sorted(set(budget) - set(derived_budget))
        if unknown:
            raise BoundaryFreezeError(
                'BUDGET_UNKNOWN_KEY: ' + ', '.join(unknown))
        normalized_budget = {}
        for key, value in derived_budget.items():
            normalized_budget[key] = _as_int(budget.get(key, value), 'budget.' + key)
            if normalized_budget[key] != value:
                raise BoundaryFreezeError(
                    'BUDGET_MISMATCH field=' + key
                    + ' declared=' + repr(normalized_budget[key])
                    + ' derived=' + repr(value))

    note_text = str(note)
    if '预期非结论' not in note_text:
        raise BoundaryFreezeError(
            'NOTE_INVALID: note 必须写明"预期非结论"')

    freeze = {
        'schema_version': CLEARANCE_BOUNDARY_FREEZE_SCHEMA,
        'status': FREEZE_STATUS,
        'scope': FREEZE_SCOPE,
        'frozen_at': frozen_at_text,
        'code_commit': commit,
        'worktree_state': state,
        'map_asset_id': map_state_normalized['map_asset_id'],
        'terrain_sha256': map_state_normalized['terrain_sha256'],
        'preview_sha256': map_state_normalized['preview_sha256'],
        'map_config_sha256': map_state_normalized['map_config_sha256'],
        'clearance_schema_version': CLEARANCE_SCHEMA_VERSION,
        'stop_requirement_schema_version': STOP_REQUIREMENT_SCHEMA_VERSION,
        'brake_model_file': brake_model_file,
        'brake_model_sha256': brake_model_sha256,
        'expected_file': expected_file,
        'expected_sha256': expected_sha256,
        'cases': [
            {'cases_file': path, 'cases_sha256': sha}
            for path, sha in sorted(cases_index.items())
        ],
        'segments': segments,
        'expected': normalized_expected,
        'budget': normalized_budget,
        'support_scope': normalized_support,
        'note': note_text,
    }
    if 'map_config_file' in map_state_normalized:
        freeze['map_config_file'] = map_state_normalized['map_config_file']
    return freeze


# ---------------------------------------------------------------------------
# 运行器/核验器辅助
# ---------------------------------------------------------------------------

_SEGMENT_PURPOSES = {
    'boundary_default': 'A/B/C 边界场景 9 场景 × r0/r1 = 18 episode（默认延迟）',
    'boundary_delay_e1': 'E 延迟边界·间隙不足：obs 200 ms/action 100 ms，2 episode',
    'boundary_delay_e2': 'E 延迟边界·动作迟到：obs 180 ms/action 120 ms，2 episode',
    'boundary_fast': 'D 近最高实测速度：快速车 max 0.9（PROPOSED），2 episode',
    'latency_clock_mapping_recheck': '时钟映射失效重跑，预声明可接受路径集合与优先级',
    'latency_ttl_over_recheck': '超 TTL 重跑（stall 0.15 s），预声明 (c) 判据',
    'regression_dynamic': '动态 A 类路线默认参数回归',
    'regression_no_obstacle': '无障碍路线默认参数回归',
    'regression_fault': 'fault_ttl_expiry_0 默认参数回归',
}


def _segment_purpose(segment_id):
    return _SEGMENT_PURPOSES.get(segment_id, segment_id)


def expected_case(freeze, case_id):
    """从冻结内嵌 expected 取逐 case 预期（boundary case 或段内 case）。"""
    _check_freeze_schema(freeze)
    expected = freeze.get('expected')
    if not isinstance(expected, dict):
        raise BoundaryFreezeError('EXPECTED_MISSING: 冻结中没有内嵌 expected')
    cases = expected.get('cases')
    if isinstance(cases, dict) and case_id in cases:
        return cases[case_id]
    segments = expected.get('segments')
    if isinstance(segments, dict):
        for segment in segments.values():
            segment_cases = (segment or {}).get('cases')
            if isinstance(segment_cases, dict) and case_id in segment_cases:
                return segment_cases[case_id]
    raise BoundaryFreezeError(f'EXPECTED_CASE_MISSING: {case_id!r}')


def sha256_file(path):
    """仓库内文件 sha256（冻结生成脚本与测试共用）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_expected_file(path):
    """读取 expected JSON 并返回 ``(payload, sha256)``（sha 基于原始字节）。

    非法 JSON 抛 ``BoundaryFreezeError``；schema 的语义校验在 ``build_freeze``
    内完成。
    """
    expected_path = Path(path)
    try:
        raw = expected_path.read_bytes()
    except OSError as error:
        raise BoundaryFreezeError(
            f'EXPECTED_READ_FAILED: {path}: {error}') from error
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BoundaryFreezeError(
            f'EXPECTED_JSON_INVALID: {path}: {error}') from error
    return payload, hashlib.sha256(raw).hexdigest()
