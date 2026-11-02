"""延迟包络正式评价的预运行冻结契约（纯标准库）。

对应计划 ``docs/superpowers/plans/2026-11-02-latency-envelope.md`` §3.3、§4.1–§4.3
与 Lead 2026-11-02 精确参数：

- ``build_run_plan``：把运行器 CLI 参数归一化为可逐字段比较的 ``latency_plan``
  （浮点 ``round(...,6)``、``cases_file`` 用 ``Path(...).as_posix()``、
  ``case_ids`` 排序、``methods`` 保持顺序）；
- ``build_freeze``：组装冻结文件（主 A/B 仅 ``stop_distance_m`` 与 ``config_id``
  可不同；专项段 run_plan 逐一记录）；
- ``validate_run_plan``：运行器启动前逐字段校验实际 run_plan；
- ``check_freeze_lineage``：校验 frozen_at 不早不晚、code_commit 与 git HEAD
  一致、工作树状态与冻结记录一致（冻结后改动 ``src/scripts/tests/configs``
  必须新建冻结版本并重跑受影响配对）；
- ``worktree_state``：``git status --porcelain -- src scripts tests configs``
  归一化文本的 sha256（与独立核验器共用同一归一化，见 ``_normalize_status_text``）。

本模块不得导入 Torch/Isaac/相机库；冻结文件只记录**预期**，不是结论。
"""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

LATENCY_FREEZE_SCHEMA = 'boom_birds.latency_freeze.v2'
LATENCY_EVAL_VERSION = 'boom_birds.latency_eval.v1'
FREEZE_STATUS = 'PRE_RUN_FROZEN'
FREEZE_SCOPE = 'CURRENT_SIM_MODEL_ONLY'
MAIN_ROLE = 'main'
SPECIAL_ROLE = 'special'
ROLES = (MAIN_ROLE, SPECIAL_ROLE)
ARTIFACT_MAIN_PAIR = 'main_pair'
ARTIFACT_SPECIAL = 'special'
ARTIFACTS = (ARTIFACT_MAIN_PAIR, ARTIFACT_SPECIAL)
TRACKED_PATHS = ('src', 'scripts', 'tests', 'configs')
EXECUTION_PATHS = ('v1', 'v2')

# 运行器（T4）按这些键调用 build_run_plan，字段名不得改名。
RUN_PLAN_FIELDS = (
    'role',
    'segment_id',
    'config_id',
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
)

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
_LATENCY_DEFAULT_FIELDS = (
    'obs_delay_s',
    'action_delay_s',
    'ttl_ms',
    'max_age_ms',
    'allowed_observation_age_ms',
    'post_abort_observe_s',
)
_SUPERVISOR_FIELDS = (
    'stop_distance_m',
    'release_distance_m',
    'prediction_horizon_s',
    'prediction_step_s',
    'observation_max_age_s',
    'max_stale_s',
    'max_wait_s',
    'min_hold_s',
    'release_hold_s',
    'resume_hold_s',
    'stop_speed_mps',
)

_SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_COMMIT_PATTERN = re.compile(r'^[0-9a-f]{7,64}$')
_EXPECTED_NOT_CONCLUSION = 'EXPECTED_NOT_CONCLUSION'
_BODY_ENVELOPE_SOURCE = 'measured_usd_aabb_at_runtime'


class LatencyFreezeError(ValueError):
    """冻结/计划违反延迟包络契约时抛出（错误码在异常消息前缀）。"""


# ---------------------------------------------------------------------------
# 基础归一化
# ---------------------------------------------------------------------------

def _as_float(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须是数字，得到 {value!r}')
    number = float(value)
    if not math.isfinite(number):
        raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须是有限数，得到 {value!r}')
    return round(number, 6)


def _as_int(value, field):
    if isinstance(value, bool):
        raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须是整数，得到 {value!r}')
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须是整数，得到 {value!r}')


def _as_text(value, field):
    if not isinstance(value, str):
        raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须是字符串，得到 {value!r}')
    return value


def _as_sha256(value, field):
    text = _as_text(value, field).strip().lower()
    if not _SHA256_PATTERN.match(text):
        raise LatencyFreezeError(f'HASH_INVALID: {field} 必须是 64 位小写十六进制')
    return text


def _as_commit(value):
    text = _as_text(value, 'code_commit').strip().lower()
    if not _COMMIT_PATTERN.match(text):
        raise LatencyFreezeError(
            f'CODE_COMMIT_INVALID: 必须是 git commit sha，得到 {value!r}')
    return text


def _as_cases_file(value):
    text = _as_text(value, 'cases_file').strip()
    if not text:
        raise LatencyFreezeError('CASES_FILE_INVALID: 不能为空')
    return Path(text).as_posix()


def _as_case_ids(value):
    if isinstance(value, (str, bytes)):
        raise LatencyFreezeError('CASE_IDS_INVALID: 必须是 case_id 列表')
    try:
        items = list(value)
    except TypeError as error:
        raise LatencyFreezeError('CASE_IDS_INVALID: 必须是 case_id 列表') from error
    if not items:
        raise LatencyFreezeError('CASE_IDS_INVALID: 不能为空')
    case_ids = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise LatencyFreezeError(f'CASE_IDS_INVALID: 非法 case_id {item!r}')
        case_ids.append(item.strip())
    if len(set(case_ids)) != len(case_ids):
        raise LatencyFreezeError('CASE_IDS_DUPLICATE: case_ids 不得重复')
    return sorted(case_ids)


def _as_methods(value):
    if isinstance(value, (str, bytes)):
        raise LatencyFreezeError('METHODS_INVALID: 必须是方法列表')
    try:
        items = list(value)
    except TypeError as error:
        raise LatencyFreezeError('METHODS_INVALID: 必须是方法列表') from error
    methods = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise LatencyFreezeError(f'METHODS_INVALID: 非法方法 {item!r}')
        methods.append(item.strip())
    if not methods:
        raise LatencyFreezeError('METHODS_INVALID: 不能为空')
    if len(set(methods)) != len(methods):
        raise LatencyFreezeError('METHODS_DUPLICATE: methods 不得重复')
    return methods


def _parse_aware_iso(value, field):
    text = _as_text(value, field).strip()
    if not text:
        raise LatencyFreezeError(f'{field.upper()}_INVALID: 不能为空')
    candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise LatencyFreezeError(
            f'{field.upper()}_INVALID: 无法解析 ISO 时间 {value!r}') from error
    if parsed.tzinfo is None:
        raise LatencyFreezeError(
            f'{field.upper()}_TIMEZONE_REQUIRED: 必须带时区（UTC），得到 {value!r}')
    return parsed


# ---------------------------------------------------------------------------
# run_plan
# ---------------------------------------------------------------------------

def build_run_plan(**kwargs):
    """按固定字段与归一化规则构造一次运行的冻结计划（见模块说明）。"""
    unknown = sorted(set(kwargs) - set(RUN_PLAN_FIELDS))
    if unknown:
        raise LatencyFreezeError('UNKNOWN_RUN_PLAN_FIELD: ' + ', '.join(unknown))
    missing = [field for field in RUN_PLAN_FIELDS if field not in kwargs]
    if missing:
        raise LatencyFreezeError('MISSING_RUN_PLAN_FIELD: ' + ', '.join(missing))

    role = _as_text(kwargs['role'], 'role')
    if role not in ROLES:
        raise LatencyFreezeError(f'ROLE_INVALID: {role!r}（只允许 {ROLES}）')
    segment_id = '' if kwargs['segment_id'] is None else _as_text(
        kwargs['segment_id'], 'segment_id').strip()
    config_id = '' if kwargs['config_id'] is None else _as_text(
        kwargs['config_id'], 'config_id').strip()
    if role == MAIN_ROLE:
        if segment_id:
            raise LatencyFreezeError(
                'SEGMENT_ID_NOT_ALLOWED_FOR_MAIN_ROLE: 主配对段 segment_id 必须为空')
        if not config_id:
            raise LatencyFreezeError(
                'CONFIG_ID_REQUIRED_FOR_MAIN_ROLE: 主配对段必须给出 config_id')
    else:
        if not segment_id:
            raise LatencyFreezeError(
                'SEGMENT_ID_REQUIRED_FOR_SPECIAL_ROLE: 专项段必须给出 segment_id')

    execution_path = _as_text(kwargs['execution_path'], 'execution_path')
    if execution_path not in EXECUTION_PATHS:
        raise LatencyFreezeError(
            f'EXECUTION_PATH_INVALID: {execution_path!r}（只允许 {EXECUTION_PATHS}）')

    plan = {
        'role': role,
        'segment_id': segment_id,
        'config_id': config_id,
        'cases_file': _as_cases_file(kwargs['cases_file']),
        'cases_sha256': _as_sha256(kwargs['cases_sha256'], 'cases_sha256'),
        'case_ids': _as_case_ids(kwargs['case_ids']),
        'methods': _as_methods(kwargs['methods']),
        'execution_path': execution_path,
    }
    for field in _FLOAT_FIELDS:
        plan[field] = _as_float(kwargs[field], field)
    for field in _INT_FIELDS:
        plan[field] = _as_int(kwargs[field], field)
    for field in _NON_NEGATIVE_FIELDS:
        if plan[field] < 0:
            raise LatencyFreezeError(f'{field.upper()}_NEGATIVE: 不得为负')
    for field in _POSITIVE_FIELDS:
        if plan[field] <= 0:
            raise LatencyFreezeError(f'{field.upper()}_INVALID: 必须为正')
    for field in _STEP_FIELDS:
        if plan[field] < -1:
            raise LatencyFreezeError(
                f'{field.upper()}_INVALID: 步索引必须 >= -1（-1 表示不启用）')
    return {field: plan[field] for field in RUN_PLAN_FIELDS}


def _normalize_existing_run_plan(run_plan, context):
    if not isinstance(run_plan, dict):
        raise LatencyFreezeError(f'RUN_PLAN_INVALID: {context} 必须是对象')
    missing = [field for field in RUN_PLAN_FIELDS if field not in run_plan]
    if missing:
        raise LatencyFreezeError(
            f'RUN_PLAN_FIELD_MISSING: {context} 缺少 ' + ', '.join(missing))
    try:
        return build_run_plan(**{field: run_plan[field]
                                 for field in RUN_PLAN_FIELDS})
    except LatencyFreezeError as error:
        raise LatencyFreezeError(f'{error}（{context}）') from error


def _select_frozen_run_plan(freeze, role, segment_id, config_id):
    if not isinstance(freeze, dict):
        raise LatencyFreezeError('SCHEMA_VERSION_MISMATCH: freeze 必须是 JSON 对象')
    if freeze.get('schema_version') != LATENCY_FREEZE_SCHEMA:
        raise LatencyFreezeError(
            'SCHEMA_VERSION_MISMATCH: 期望 '
            f'{LATENCY_FREEZE_SCHEMA}，得到 {freeze.get("schema_version")!r}')
    if role not in ROLES:
        raise LatencyFreezeError(f'ROLE_INVALID: {role!r}（只允许 {ROLES}）')
    if role == MAIN_ROLE:
        plans = freeze.get('main_run_plans')
        if not isinstance(plans, dict):
            raise LatencyFreezeError('MAIN_RUN_PLANS_MISSING: 冻结中没有 main_run_plans')
        if config_id not in plans:
            raise LatencyFreezeError(f'PLAN_NOT_FROZEN: 主配对 config_id={config_id!r} 未冻结')
        return plans[config_id], f'main config {config_id}'
    segments = freeze.get('special_segments')
    if not isinstance(segments, dict):
        raise LatencyFreezeError('SPECIAL_SEGMENTS_MISSING: 冻结中没有 special_segments')
    if segment_id not in segments:
        raise LatencyFreezeError(
            f'PLAN_NOT_FROZEN: 专项段 segment_id={segment_id!r} 未冻结')
    entry = segments[segment_id]
    if not isinstance(entry, dict) or 'run_plan' not in entry:
        raise LatencyFreezeError(
            f'SPECIAL_SEGMENT_RUN_PLAN_MISSING: segment_id={segment_id!r}')
    return entry['run_plan'], f'special segment {segment_id}'


def validate_run_plan(freeze, role, segment_id, config_id, run_plan):
    """逐字段比对运行器实际 run_plan 与冻结计划；首个不一致抛错。"""
    frozen_plan, context = _select_frozen_run_plan(freeze, role, segment_id,
                                                   config_id or '')
    expected = _normalize_existing_run_plan(frozen_plan, 'frozen ' + context)
    actual = _normalize_existing_run_plan(run_plan, 'actual ' + context)
    for field in RUN_PLAN_FIELDS:
        if expected[field] != actual[field]:
            raise LatencyFreezeError(
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
        raise LatencyFreezeError(f'GIT_UNAVAILABLE: {error}') from error
    if completed.returncode != 0:
        raise LatencyFreezeError(
            'GIT_FAILED: git ' + ' '.join(args) + ': '
            + (completed.stderr or '').strip())
    return completed.stdout


def git_head(repo_root):
    """返回仓库当前 HEAD 的完整 commit sha（冻结生成与世系校验共用）。"""
    head = _run_git(repo_root, ['rev-parse', 'HEAD']).strip().lower()
    if not _COMMIT_PATTERN.match(head):
        raise LatencyFreezeError(f'CODE_COMMIT_INVALID: git HEAD={head!r}')
    return head


def _normalize_status_text(text):
    """把 git status --porcelain 输出归一化为行级文本（与核验器共用）。

    规则（Lead 2026-11-02 对齐）：``\\r\\n`` → ``\\n``、逐行 rstrip、丢弃行为空
    的行、``\\n``.join，**不带末尾换行**；随后对 UTF-8 字节做 sha256。
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
            resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
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
    """校验冻结的生成时刻/代码提交/工作树状态；不得倒填或先运行后冻结。"""
    if not isinstance(freeze, dict):
        raise LatencyFreezeError('SCHEMA_VERSION_MISMATCH: freeze 必须是 JSON 对象')
    if freeze.get('schema_version') != LATENCY_FREEZE_SCHEMA:
        raise LatencyFreezeError(
            'SCHEMA_VERSION_MISMATCH: 期望 '
            f'{LATENCY_FREEZE_SCHEMA}，得到 {freeze.get("schema_version")!r}')
    if freeze.get('status') != FREEZE_STATUS:
        raise LatencyFreezeError(
            f'FREEZE_STATUS_INVALID: 必须是 {FREEZE_STATUS}，'
            f'得到 {freeze.get("status")!r}')
    frozen_at = _parse_aware_iso(freeze.get('frozen_at'), 'frozen_at')
    now = _parse_aware_iso(now_iso, 'now_iso')
    if frozen_at > now:
        raise LatencyFreezeError(
            'FROZEN_AT_IN_FUTURE: frozen_at 晚于当前时间（禁止未来时间/倒填）: '
            f'frozen_at={freeze.get("frozen_at")!r} now={now_iso!r}')
    recorded_commit = _as_commit(freeze.get('code_commit'))
    head = git_head(repo_root)
    if recorded_commit != head:
        raise LatencyFreezeError(
            f'CODE_COMMIT_MISMATCH: 冻结记录 {recorded_commit}，当前 HEAD {head}')
    state = freeze.get('worktree_state')
    if not isinstance(state, dict):
        raise LatencyFreezeError('WORKTREE_STATE_INVALID: 缺少 worktree_state')
    recorded = state.get('status_text_sha256') or state.get('digest')
    recorded = _as_sha256(recorded, 'worktree_state.status_text_sha256')
    current = worktree_state(repo_root)['status_text_sha256']
    if recorded != current:
        raise LatencyFreezeError(
            'WORKTREE_STATE_MISMATCH: 冻结后 src/scripts/tests/configs 发生变化；'
            '必须新建冻结版本并重跑受影响配对')
    return None


# ---------------------------------------------------------------------------
# 冻结组装
# ---------------------------------------------------------------------------

def _normalize_cases_index(cases):
    if not isinstance(cases, (list, tuple)) or not cases:
        raise LatencyFreezeError('CASES_INVALID: cases 必须是非空列表')
    index = {}
    for entry in cases:
        if not isinstance(entry, dict):
            raise LatencyFreezeError('CASES_INVALID: cases[*] 必须是对象')
        cases_file = _as_cases_file(entry.get('cases_file'))
        sha = _as_sha256(entry.get('cases_sha256'), 'cases_sha256')
        if cases_file in index and index[cases_file] != sha:
            raise LatencyFreezeError(
                f'CASES_INVALID: 同一 cases_file 出现不同 sha256: {cases_file}')
        index[cases_file] = sha
    return index


def _check_declared_case_file(plan, index):
    cases_file = plan['cases_file']
    if cases_file not in index:
        raise LatencyFreezeError(
            f'CASE_FILE_NOT_DECLARED: {cases_file} 不在冻结 cases 声明中')
    if index[cases_file] != plan['cases_sha256']:
        raise LatencyFreezeError(
            f'CASE_SHA256_MISMATCH: {cases_file} 声明 sha256 与 cases 列表不一致')


def _normalize_main_run_plans(main_run_plans, index):
    if main_run_plans is None:
        return {}
    if not isinstance(main_run_plans, dict):
        raise LatencyFreezeError('MAIN_RUN_PLANS_INVALID: 必须是对象')
    normalized = {}
    for config_id in sorted(main_run_plans):
        plan = _normalize_existing_run_plan(
            main_run_plans[config_id], f'main run plan {config_id}')
        if plan['role'] != MAIN_ROLE:
            raise LatencyFreezeError(
                f'MAIN_RUN_PLAN_ROLE_INVALID: config_id={config_id} 必须是 main')
        if plan['segment_id']:
            raise LatencyFreezeError(
                f'MAIN_RUN_PLAN_SEGMENT_INVALID: config_id={config_id} 的 segment_id 必须为空')
        if plan['config_id'] != config_id:
            raise LatencyFreezeError(
                'MAIN_RUN_PLAN_CONFIG_ID_MISMATCH: 键与 run_plan.config_id 不一致: '
                f'{config_id!r} != {plan["config_id"]!r}')
        _check_declared_case_file(plan, index)
        normalized[config_id] = plan
    if normalized and set(normalized) != {'A', 'B'}:
        raise LatencyFreezeError(
            'MAIN_RUN_PLANS_MISMATCH: 主配对必须恰好包含 A/B，得到 '
            + ', '.join(sorted(normalized)))
    if len(normalized) == 2:
        first, second = normalized['A'], normalized['B']
        for field in RUN_PLAN_FIELDS:
            if field in ('config_id', 'stop_distance_m'):
                continue
            if first[field] != second[field]:
                raise LatencyFreezeError(
                    'MAIN_PAIR_MISMATCH field=' + field
                    + ': 主 A/B 只允许 stop_distance_m 与 config_id 不同')
    return normalized


def _normalize_special_segments(special_segments, index):
    if special_segments is None:
        return {}
    if not isinstance(special_segments, dict):
        raise LatencyFreezeError(
            'SPECIAL_SEGMENTS_INVALID: special_segments 必须是对象字典')
    normalized = {}
    for segment_id in sorted(special_segments):
        entry = special_segments[segment_id]
        if not isinstance(entry, dict):
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_INVALID: {segment_id} 必须是对象')
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise LatencyFreezeError('SPECIAL_SEGMENT_ID_INVALID: 段名不能为空')
        if 'run_plan' not in entry:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_RUN_PLAN_MISSING: {segment_id}')
        plan = _normalize_existing_run_plan(
            entry['run_plan'], f'special run plan {segment_id}')
        if plan['role'] != SPECIAL_ROLE:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_RUN_PLAN_ROLE_INVALID: {segment_id} 必须是 special')
        if plan['segment_id'] != segment_id:
            raise LatencyFreezeError(
                'SPECIAL_SEGMENT_ID_MISMATCH: '
                f'键 {segment_id!r} != run_plan.segment_id {plan["segment_id"]!r}')
        _check_declared_case_file(plan, index)
        case_ids = entry.get('case_ids')
        if list(case_ids) != plan['case_ids']:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_CASE_IDS_MISMATCH: {segment_id}')
        cases_file = _as_cases_file(entry.get('cases_file'))
        if cases_file != plan['cases_file']:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_CASE_FILE_MISMATCH: {segment_id}')
        sha = _as_sha256(entry.get('cases_sha256'), 'cases_sha256')
        if sha != plan['cases_sha256']:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_CASE_SHA_MISMATCH: {segment_id}')
        expected = entry.get('expected')
        if not isinstance(expected, dict) or not expected:
            raise LatencyFreezeError(
                f'SPECIAL_SEGMENT_EXPECTED_MISSING: {segment_id} 缺少预期分类')
        normalized[segment_id] = {
            'segment_id': segment_id,
            'purpose': str(entry.get('purpose', '') or ''),
            'case_ids': list(plan['case_ids']),
            'cases_file': cases_file,
            'cases_sha256': sha,
            'run_plan': plan,
            'expected': expected,
            'expected_note': str(entry.get('expected_note', '预期非结论')),
        }
    return normalized


def _validate_evaluation(evaluation, main_run_plans, special_segments):
    if not isinstance(evaluation, dict):
        raise LatencyFreezeError('EVALUATION_INVALID: evaluation 必须是对象')
    for key in ('version', 'status', 'supervisor', 'thresholds', 'expected'):
        if key not in evaluation:
            raise LatencyFreezeError(f'EVALUATION_MISSING: evaluation.{key}')
    if evaluation['version'] != LATENCY_EVAL_VERSION:
        raise LatencyFreezeError(
            'EVALUATION_VERSION_MISMATCH: 期望 '
            f'{LATENCY_EVAL_VERSION}，得到 {evaluation["version"]!r}')
    supervisor = evaluation['supervisor']
    if not isinstance(supervisor, dict):
        raise LatencyFreezeError('EVALUATION_INVALID: evaluation.supervisor 必须是对象')
    for field in _SUPERVISOR_FIELDS:
        if field not in supervisor:
            raise LatencyFreezeError(
                f'EVALUATION_MISSING: evaluation.supervisor.{field}')
        _as_float(supervisor[field], 'supervisor.' + field)
    if not isinstance(evaluation['thresholds'], dict):
        raise LatencyFreezeError('EVALUATION_INVALID: evaluation.thresholds 必须是对象')
    expected = evaluation['expected']
    if not isinstance(expected, dict):
        raise LatencyFreezeError('EVALUATION_INVALID: evaluation.expected 必须是对象')
    expected_main = expected.get('main') or {}
    expected_special = expected.get('special') or {}
    if not isinstance(expected_main, dict) or not isinstance(expected_special, dict):
        raise LatencyFreezeError(
            'EVALUATION_INVALID: evaluation.expected.main/special 必须是对象')
    for config_id, plan in main_run_plans.items():
        config_expected = expected_main.get(config_id)
        if not isinstance(config_expected, dict):
            raise LatencyFreezeError(
                f'EXPECTED_MISSING: evaluation.expected.main.{config_id}')
        frozen_cases = set(plan['case_ids'])
        labeled = set(config_expected)
        missing = sorted(frozen_cases - labeled)
        if missing:
            raise LatencyFreezeError(
                f'EXPECTED_MISSING: evaluation.expected.main.{config_id} 缺少 '
                + ', '.join(missing))
        unexpected = sorted(labeled - frozen_cases)
        if unexpected:
            raise LatencyFreezeError(
                f'EXPECTED_UNEXPECTED: evaluation.expected.main.{config_id} 多出 '
                + ', '.join(unexpected))
    for segment_id in special_segments:
        if not isinstance(expected_special.get(segment_id), dict):
            raise LatencyFreezeError(
                f'EXPECTED_MISSING: evaluation.expected.special.{segment_id}')
    return evaluation


def _validate_latency_defaults(latency_plan_defaults, main_run_plans):
    if not isinstance(latency_plan_defaults, dict):
        raise LatencyFreezeError(
            'LATENCY_PLAN_DEFAULTS_INVALID: 必须是对象')
    values = {}
    for field in _LATENCY_DEFAULT_FIELDS:
        if field not in latency_plan_defaults:
            raise LatencyFreezeError(
                f'LATENCY_PLAN_DEFAULTS_MISSING: {field}')
        if field in _FLOAT_FIELDS:
            values[field] = _as_float(latency_plan_defaults[field],
                                      'latency_plan_defaults.' + field)
        else:
            values[field] = _as_int(latency_plan_defaults[field],
                                    'latency_plan_defaults.' + field)
    if 'A' in main_run_plans:
        reference = main_run_plans['A']
        for field in _LATENCY_DEFAULT_FIELDS:
            if values[field] != reference[field]:
                raise LatencyFreezeError(
                    'LATENCY_PLAN_DEFAULTS_MISMATCH field=' + field
                    + ' defaults=' + repr(values[field])
                    + ' main A=' + repr(reference[field]))
    return values


def _validate_clock_plan(clock_plan, main_run_plans):
    if not isinstance(clock_plan, dict):
        raise LatencyFreezeError('CLOCK_PLAN_INVALID: 必须是对象')
    for key in ('camera_clock_id', 'offset_ms', 'drift_ppm', 'uncertainty_ms',
                'sync_generation_plan'):
        if key not in clock_plan:
            raise LatencyFreezeError(f'CLOCK_PLAN_MISSING: {key}')
    _as_text(clock_plan['camera_clock_id'], 'clock_plan.camera_clock_id')
    if not isinstance(clock_plan['sync_generation_plan'], dict):
        raise LatencyFreezeError(
            'CLOCK_PLAN_INVALID: clock_plan.sync_generation_plan 必须是对象')
    pairs = (('offset_ms', 'clock_offset_ms'),
             ('drift_ppm', 'clock_drift_ppm'),
             ('uncertainty_ms', 'clock_uncertainty_ms'))
    values = {key: _as_float(clock_plan[key], 'clock_plan.' + key)
              for key, _ in pairs}
    if 'A' in main_run_plans:
        reference = main_run_plans['A']
        for key, plan_field in pairs:
            if values[key] != reference[plan_field]:
                raise LatencyFreezeError(
                    'CLOCK_PLAN_MISMATCH field=' + key
                    + ' clock_plan=' + repr(values[key])
                    + ' main A=' + repr(reference[plan_field]))
    return dict(clock_plan)


def _validate_body_envelope(body_envelope):
    if not isinstance(body_envelope, dict):
        raise LatencyFreezeError('BODY_ENVELOPE_INVALID: 必须是对象')
    if body_envelope.get('source') != _BODY_ENVELOPE_SOURCE:
        raise LatencyFreezeError(
            'BODY_ENVELOPE_INVALID: source 必须是 ' + _BODY_ENVELOPE_SOURCE)
    tolerance = body_envelope.get('tolerance_m')
    if tolerance is not None:
        _as_float(tolerance, 'body_envelope.tolerance_m')
    half_extents = body_envelope.get('half_extents_m')
    if half_extents is not None and not isinstance(half_extents, (list, tuple, dict)):
        raise LatencyFreezeError(
            'BODY_ENVELOPE_INVALID: half_extents_m 必须是列表/对象或 null')
    return body_envelope


def build_freeze(*, frozen_at, code_commit, worktree_state, map_state, cases,
                 primary_cases_file, artifact,
                 main_run_plans=None, special_segments=None, evaluation=None,
                 clock_plan=None, latency_plan_defaults=None,
                 body_envelope=None, note=''):
    """组装一个 v2 冻结对象（主配对或专项；两者共享源码/工作树世系）。"""
    if artifact not in ARTIFACTS:
        raise LatencyFreezeError(
            f'ARTIFACT_INVALID: {artifact!r}（只允许 {ARTIFACTS}）')
    if artifact == ARTIFACT_MAIN_PAIR and not main_run_plans:
        raise LatencyFreezeError(
            'MAIN_RUN_PLANS_REQUIRED_FOR_MAIN_PAIR: 主配对冻结必须包含 A/B run plan')
    if artifact == ARTIFACT_SPECIAL and not special_segments:
        raise LatencyFreezeError(
            'SPECIAL_SEGMENTS_REQUIRED_FOR_SPECIAL_ARTIFACT: 专项冻结必须包含 special_segments')

    frozen_at_text = _as_text(frozen_at, 'frozen_at')
    _parse_aware_iso(frozen_at_text, 'frozen_at')
    commit = _as_commit(code_commit)

    if not isinstance(worktree_state, dict):
        raise LatencyFreezeError('WORKTREE_STATE_INVALID: 必须是对象')
    tracked_paths = worktree_state.get('tracked_paths')
    if tracked_paths != list(TRACKED_PATHS):
        raise LatencyFreezeError(
            'WORKTREE_STATE_INVALID: tracked_paths 必须是 ' + repr(list(TRACKED_PATHS)))
    state = {
        'tracked_paths': list(TRACKED_PATHS),
        'status_text_sha256': _as_sha256(
            worktree_state.get('status_text_sha256'),
            'worktree_state.status_text_sha256'),
        'clean': bool(worktree_state.get('clean')),
    }

    if not isinstance(map_state, dict):
        raise LatencyFreezeError('MAP_STATE_INVALID: 必须是对象')
    asset_id = _as_text(map_state.get('map_asset_id'), 'map_asset_id').strip()
    if not asset_id:
        raise LatencyFreezeError('MAP_STATE_INVALID: map_asset_id 不能为空')
    map_hashes = {
        'terrain_sha256': _as_sha256(map_state.get('terrain_sha256'),
                                     'terrain_sha256'),
        'preview_sha256': _as_sha256(map_state.get('preview_sha256'),
                                     'preview_sha256'),
        'map_config_sha256': _as_sha256(map_state.get('map_config_sha256'),
                                        'map_config_sha256'),
    }
    map_config_file = map_state.get('map_config_file')
    if map_config_file is not None:
        map_config_file = Path(_as_text(map_config_file, 'map_config_file')).as_posix()

    case_index = _normalize_cases_index(cases)
    primary_file = _as_cases_file(primary_cases_file)
    if primary_file not in case_index:
        raise LatencyFreezeError(
            f'CASE_FILE_NOT_DECLARED: primary_cases_file {primary_file} 不在 cases 声明中')

    normalized_main = _normalize_main_run_plans(main_run_plans, case_index)
    normalized_special = _normalize_special_segments(special_segments, case_index)
    if artifact == ARTIFACT_MAIN_PAIR and not normalized_main:
        raise LatencyFreezeError(
            'MAIN_RUN_PLANS_REQUIRED_FOR_MAIN_PAIR: 主配对冻结必须包含 A/B run plan')
    if artifact == ARTIFACT_SPECIAL and not normalized_special:
        raise LatencyFreezeError(
            'SPECIAL_SEGMENTS_REQUIRED_FOR_SPECIAL_ARTIFACT: 专项冻结必须包含 special_segments')

    validated_evaluation = _validate_evaluation(evaluation, normalized_main,
                                                normalized_special)
    validated_defaults = _validate_latency_defaults(latency_plan_defaults,
                                                     normalized_main)
    validated_clock = _validate_clock_plan(clock_plan, normalized_main)
    validated_body = _validate_body_envelope(body_envelope)

    freeze = {
        'schema_version': LATENCY_FREEZE_SCHEMA,
        'artifact': artifact,
        'status': FREEZE_STATUS,
        'scope': FREEZE_SCOPE,
        'frozen_at': frozen_at_text,
        'code_commit': commit,
        'worktree_state': state,
        'evaluation_version': LATENCY_EVAL_VERSION,
        'map_asset_id': asset_id,
        'terrain_sha256': map_hashes['terrain_sha256'],
        'preview_sha256': map_hashes['preview_sha256'],
        'map_config_sha256': map_hashes['map_config_sha256'],
    }
    if map_config_file is not None:
        freeze['map_config_file'] = map_config_file
    freeze['cases_file'] = primary_file
    freeze['cases_sha256'] = case_index[primary_file]
    freeze['latency_plan_defaults'] = validated_defaults
    freeze['clock_plan'] = validated_clock
    freeze['main_run_plans'] = normalized_main
    freeze['special_segments'] = normalized_special
    freeze['evaluation'] = validated_evaluation
    freeze['body_envelope'] = validated_body
    freeze['note'] = str(note)
    return freeze
