"""生成 clearance 几何/停止需求边界专项的预运行冻结（单文件多 segment）。

设计依据：``docs/superpowers/plans/2026-11-02-clearance-boundary.md`` §5、§7 与
任务 U2。

- 真实 UTC 时间 ``frozen_at``、实际 ``git rev-parse HEAD``、真实工作树状态、
  地图 4 个 hash、brake model hash、cases hash、expected hash 全部由本脚本
  自算，**不接受调用者传入**；
- 段运行参数（vehicle_config、obs/action delay、TTL、allowed obs age、
  stop_distance_m、post_abort_observe_s、clock offset/drift/uncertainty、
  故障注入 step、methods、execution_path）与 case ids：boundary/special 段
  **全部来自 expected 文件** ``segments[*].defaults.run_params`` / ``case_ids``；
  regression 段按 Lead 2026-11-02 裁决使用脚本内置默认参数表（expected 不写
  regression 预冻结预期，U3 用既有证据对照）。expected 文件 hash 进入冻结，
  运行后修改 expected（放宽集合/参数）必须重新冻结；
- 固定 9 个 segment：``boundary_default``（18 episode）、``boundary_delay_e1``
  （2）、``boundary_delay_e2``（2）、``boundary_fast``（2）、
  ``latency_clock_mapping_recheck``、``latency_ttl_over_recheck``、
  ``regression_dynamic``、``regression_no_obstacle``、``regression_fault``；
  边界 episode 合计 24；
- 输出已存在时**直接失败**（返回码 2），禁止覆盖或运行后倒填；
- ``--dry-run`` 只打印冻结 JSON，不写盘；
- 写出采用两遍：先写入占位工作树状态，再基于真实包含未跟踪冻结文件的工作树
  状态重写，使冻结记录与运行入口 ``check_freeze_lineage`` 校验一致；
- 正式生成必须在代码提交之后、正式运行之前执行（Lead 执行）。

自测（不写正式文件名）::

    E:\\isaac\\env_isaaclab\\Scripts\\python.exe scripts/make_boundary_freeze.py \
        --dry-run --output tmp/freeze_check/clearance_boundary_freeze_v1.json

正式生成::

    E:\\isaac\\env_isaaclab\\Scripts\\python.exe scripts/make_boundary_freeze.py
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from boom_birds.evaluation.boundary_plan import (  # noqa: E402
    BRAKE_MODEL_SPEED_SUPPORT_MPS,
    CLEARANCE_BOUNDARY_EXPECTED_SCHEMA,
    CLEARANCE_SCHEMA_VERSION,
    DEFAULT_BRAKE_MODEL_FILE,
    DEFAULT_BRAKE_MODEL_VERSION,
    DEFAULT_STOP_DISTANCE_M,
    DEFAULT_VEHICLE_CONFIG,
    EXPECTED_SEGMENT_IDS,
    FAST_VEHICLE_CONFIG,
    REGRESSION_SEGMENT_IDS,
    SEGMENT_IDS,
    SEGMENT_ROLES,
    STOP_REQUIREMENT_SCHEMA_VERSION,
    BoundaryFreezeError,
    build_freeze,
    build_run_plan,
    git_head,
    load_expected_file,
    sha256_file,
    worktree_state,
)
from boom_birds.sim.map_contract import load_map_contract  # noqa: E402

DEFAULT_MAP_CONFIG = 'configs/maps/rmuc2027.yaml'
DEFAULT_LOCAL_CONFIG = 'configs/maps/rmuc2027.local.yaml'
DEFAULT_EXPECTED = 'configs/scenarios/clearance_boundary_expected_v1.json'
DEFAULT_BRAKE_MODEL = DEFAULT_BRAKE_MODEL_FILE
DEFAULT_OUTPUT = 'configs/scenarios/clearance_boundary_freeze_v1.json'
DEFAULT_NOTE = (
    'clearance 边界专项预运行冻结（单文件 9 segment；boundary_default 18 + '
    'boundary_delay_e1 2 + boundary_delay_e2 2 + boundary_fast 2 = 24 边界 '
    'episode，另 2 个 recheck + 3 个回归）；冻结后修改 src/scripts/tests/configs '
    '必须新建版本并重跑受影响段；预期非结论，实际以独立核验从原始记录重算为准；'
    '本冻结只覆盖当前仿真模型，不提升任何 Gate。')

# regression 段按 Lead 2026-11-02 裁决不写 expected 预冻结预期（U3 对
# role=regression 无预期时显式放行，使用既有 v2 证据）；其默认参数在此固定，
# reset 由 git HEAD 锁定，并进入冻结 run_plan。
REGRESSION_SEGMENT_SPECS = {
    'regression_dynamic': {
        'cases_file': 'configs/scenarios/map_dynamic_cases_v1.json',
        'case_ids': ['dynamic_A_south_0'],
    },
    'regression_no_obstacle': {
        'cases_file': 'configs/scenarios/map_v2_regression_cases_v1.json',
        'case_ids': ['v2_reg_route_south_R1'],
    },
    'regression_fault': {
        'cases_file': 'configs/scenarios/map_v2_fault_cases_v1.json',
        'case_ids': ['fault_ttl_expiry_0'],
    },
}
REGRESSION_RUN_PARAMS = {
    'vehicle_config': DEFAULT_VEHICLE_CONFIG,
    'methods': ['supervisor'],
    'execution_path': 'v2',
    'obs_delay_s': 0.0,
    'action_delay_s': 0.0,
    'ttl_ms': 150,
    'max_age_ms': 150,
    'allowed_observation_age_ms': 250,
    'stop_distance_m': DEFAULT_STOP_DISTANCE_M,
    'post_abort_observe_s': 0.0,
    'clock_offset_ms': 0.0,
    'clock_drift_ppm': 0.0,
    'clock_uncertainty_ms': 0.0,
    'sync_fail_step': -1,
    'obs_mapping_fail_step': -1,
    'transport_stall_step': -1,
    'transport_stall_delay_s': 0.15,
}


class FreezeGenerationError(RuntimeError):
    """生成前置条件不满足（输入配置不一致等）。"""


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--expected', type=Path, default=Path(DEFAULT_EXPECTED),
                        help='场景预期与段运行参数（params case_ids 的权威来源）')
    parser.add_argument('--brake-model', type=Path,
                        default=Path(DEFAULT_BRAKE_MODEL),
                        help='制动模型文件（hash 进入冻结）')
    parser.add_argument('--map-config', type=Path,
                        default=Path(DEFAULT_MAP_CONFIG))
    parser.add_argument('--local-config', type=Path,
                        default=Path(DEFAULT_LOCAL_CONFIG))
    parser.add_argument('--output', type=Path, default=None,
                        help='冻结输出（默认 configs/scenarios/'
                             'clearance_boundary_freeze_v1.json）')
    parser.add_argument('--note', default=DEFAULT_NOTE,
                        help='冻结 note（必须写明预期非结论）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印冻结 JSON，不写盘')
    return parser


def _resolve_input(path):
    path = Path(path)
    return path if path.is_absolute() else (ROOT / path)


def _repo_relative(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _sha256_file(path):
    return sha256_file(path)


def _load_cases_file(path):
    """读取 map cases JSON（scripts/run_dynamic_eval.py 同格式）并返回 case_id 集合。"""
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise FreezeGenerationError('cases 文件不可读: %s: %s'
                                    % (path, error)) from error
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FreezeGenerationError('cases 文件不是合法 JSON: %s: %s'
                                    % (path, error)) from error
    if payload.get('schema_version') not in ('boom_birds.map_cases.v1',
                                             'boom_birds.map_cases.v2'):
        raise FreezeGenerationError(
            'cases 文件 schema 不受支持: %r' % payload.get('schema_version'))
    entries = payload.get('cases')
    if not isinstance(entries, list) or not entries:
        raise FreezeGenerationError('cases 文件缺少非空 cases 列表: %s' % path)
    case_ids = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('case_id'):
            raise FreezeGenerationError('cases 文件存在非法 case 条目: %s' % path)
        case_ids.append(str(entry['case_id']))
    if len(set(case_ids)) != len(case_ids):
        raise FreezeGenerationError('cases 文件 case_id 重复: %s' % path)
    return set(case_ids)


def _read_brake_model(path, expected_payload):
    """读取 brake model 文件：hash 由脚本自算；版本/支持区间与 expected 对齐。"""
    brake_path = _resolve_input(path)
    if not brake_path.is_file():
        raise FreezeGenerationError('brake model 文件不存在: %s' % brake_path)
    sha = _sha256_file(brake_path)
    version = None
    speed_support = None
    try:
        payload = json.loads(brake_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        for key in ('version', 'brake_model_version', 'model_version', 'id'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                version = value.strip()
                break
        for key in ('speed_support_mps', 'support_speed_mps',
                    'speed_range_mps', 'measured_speed_support_mps'):
            value = payload.get(key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                speed_support = [round(float(value[0]), 6),
                                round(float(value[1]), 6)]
                break
        interval = payload.get('support_interval_mps')
        if speed_support is None and isinstance(interval, dict) \
                and 'min' in interval and 'max' in interval:
            speed_support = [round(float(interval['min']), 6),
                            round(float(interval['max']), 6)]
    declared = expected_payload.get('brake_model') or {}
    expected_version = declared.get('version')
    if expected_version and version and expected_version != version:
        raise FreezeGenerationError(
            'brake model version 与 expected 声明不一致: 文件=%r expected=%r'
            % (version, expected_version))
    expected_support = declared.get('speed_support_mps')
    if expected_support:
        expected_support = [round(float(x), 6) for x in expected_support]
    if expected_support and speed_support and expected_support != speed_support:
        raise FreezeGenerationError(
            'brake model 支持区间与 expected 声明不一致: 文件=%r expected=%r'
            % (speed_support, expected_support))
    return {
        'path': _repo_relative(brake_path),
        'sha256': sha,
        'version': version or expected_version or DEFAULT_BRAKE_MODEL_VERSION,
        'speed_support_mps': speed_support or (
            list(expected_support) if expected_support else None),
    }


def _collect_segment_plans(expected_payload, expected_rel, expected_sha,
                           brake_sha, cases_cache):
    """构造固定 9 个 segment 的 run_plan。

    boundary/special 段来自 expected.segments[*].defaults（cases_file/case_ids/
    run_params 的权威来源）；regression 段按 Lead 裁决使用脚本内置默认参数表
    （expected 不列 regression 段）。全部 run_plan 进入冻结并逐字段锁定。
    """
    segments = expected_payload.get('segments')
    if not isinstance(segments, dict):
        raise FreezeGenerationError('expected.segments 必须是对象')
    plans = {}
    declared_cases = {}

    def _cached_cases(cases_file, segment_id):
        cases_path = _resolve_input(Path(cases_file))
        if cases_file not in cases_cache:
            if not cases_path.is_file():
                raise FreezeGenerationError(
                    'cases 文件不存在: %s（segment %s）'
                    % (cases_path, segment_id))
            cases_cache[cases_file] = {
                'sha256': _sha256_file(cases_path),
                'case_ids': _load_cases_file(cases_path),
            }
        cached = cases_cache[cases_file]
        declared_cases[cases_file] = cached['sha256']
        return cached

    def _build(segment_id, role, cases_file, case_ids, run_params):
        if not isinstance(run_params, dict):
            raise FreezeGenerationError(
                'segment %s 的 run_params 必须是对象' % segment_id)
        if not isinstance(case_ids, list) or not case_ids:
            raise FreezeGenerationError(
                'segment %s 的 case_ids 必须是非空列表' % segment_id)
        cached = _cached_cases(cases_file, segment_id)
        missing = sorted(set(case_ids) - cached['case_ids'])
        if missing:
            raise FreezeGenerationError(
                'segment %s 的 case 不在 %s 中: %s'
                % (segment_id, cases_file, ', '.join(missing)))
        vehicle_config = run_params.get('vehicle_config')
        if not isinstance(vehicle_config, str) or not vehicle_config.strip():
            raise FreezeGenerationError(
                'segment %s 的 run_params.vehicle_config 缺失' % segment_id)
        vehicle_path = _resolve_input(Path(vehicle_config))
        if not vehicle_path.is_file():
            raise FreezeGenerationError(
                'vehicle config 文件不存在: %s（segment %s）'
                % (vehicle_path, segment_id))
        plan_kwargs = dict(run_params)
        plan_kwargs.update(
            segment_id=segment_id,
            role=role,
            cases_file=cases_file,
            cases_sha256=cached['sha256'],
            case_ids=list(case_ids),
            vehicle_config=vehicle_config,
            vehicle_config_sha256=_sha256_file(vehicle_path),
            expected_file=expected_rel,
            expected_sha256=expected_sha,
            brake_model_sha256=brake_sha,
            clearance_schema_version=CLEARANCE_SCHEMA_VERSION,
            stop_requirement_schema_version=STOP_REQUIREMENT_SCHEMA_VERSION,
        )
        return build_run_plan(**plan_kwargs)

    for segment_id in EXPECTED_SEGMENT_IDS:
        entry = segments.get(segment_id)
        if not isinstance(entry, dict):
            raise FreezeGenerationError(
                'expected.segments 缺少 %r' % segment_id)
        defaults = entry.get('defaults')
        if not isinstance(defaults, dict):
            raise FreezeGenerationError(
                'expected.segments.%s.defaults 必须是对象' % segment_id)
        plans[segment_id] = _build(
            segment_id, SEGMENT_ROLES[segment_id], defaults.get('cases_file'),
            defaults.get('case_ids'), defaults.get('run_params'))
    for segment_id in REGRESSION_SEGMENT_IDS:
        spec = REGRESSION_SEGMENT_SPECS[segment_id]
        plans[segment_id] = _build(
            segment_id, SEGMENT_ROLES[segment_id], spec['cases_file'],
            list(spec['case_ids']), dict(REGRESSION_RUN_PARAMS))
    if set(plans) != set(SEGMENT_IDS):  # pragma: no cover - 防御
        raise FreezeGenerationError('内部错误: run_plan 未覆盖全部固定段')
    declared = [
        {'cases_file': cases_file, 'cases_sha256': declared_cases[cases_file]}
        for cases_file in sorted(declared_cases)
    ]
    return plans, declared


def _build_payload(args, worktree, frozen_at):
    expected_path = _resolve_input(args.expected)
    if not expected_path.is_file():
        raise FreezeGenerationError('expected 文件不存在: %s' % expected_path)
    expected_payload, expected_sha = load_expected_file(expected_path)
    if expected_payload.get('schema_version') != CLEARANCE_BOUNDARY_EXPECTED_SCHEMA:
        raise FreezeGenerationError(
            'expected schema_version 必须是 %s，得到 %r'
            % (CLEARANCE_BOUNDARY_EXPECTED_SCHEMA,
               expected_payload.get('schema_version')))
    expected_rel = _repo_relative(expected_path)
    brake = _read_brake_model(args.brake_model, expected_payload)

    map_config = _resolve_input(args.map_config)
    local_config = _resolve_input(args.local_config)
    contract = load_map_contract(map_config, local_config)
    map_state = {
        'map_asset_id': contract.asset_id,
        'terrain_sha256': contract.terrain_sha256,
        'preview_sha256': contract.preview_sha256,
        'map_config_sha256': _sha256_file(map_config),
        'map_config_file': _repo_relative(map_config),
    }

    cases_cache = {}
    plans, declared_cases = _collect_segment_plans(
        expected_payload, expected_rel, expected_sha, brake['sha256'],
        cases_cache)
    vehicle_configs = {}
    for plan in plans.values():
        path = plan['vehicle_config']
        vehicle_configs[path] = ('fast_vehicle_PRO_POSED'
                                 if path == FAST_VEHICLE_CONFIG
                                 else 'default_vehicle')
    support_scope = {
        'scope': 'CURRENT_SIM_MODEL_ONLY',
        'evidence_domain': 'GUI Isaac Lab simulation (DirectX/D3D12); '
                           '非 SITL/HIL/实机',
        'simulation_models': [
            'kinematic_obstacle',
            'velocity_chain',
            'simulated_camera_clock',
            'oracle_observation',
        ],
        'brake_model_version': brake['version'],
        'brake_model_speed_support_mps': (
            brake['speed_support_mps']
            if brake['speed_support_mps'] is not None
            else list(BRAKE_MODEL_SPEED_SUPPORT_MPS)),
        'vehicle_configs': vehicle_configs,
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
    freeze = build_freeze(
        frozen_at=frozen_at,
        code_commit=git_head(ROOT),
        worktree_state=worktree,
        map_state=map_state,
        cases=declared_cases,
        segment_run_plans=plans,
        expected=expected_payload,
        expected_file=expected_rel,
        expected_sha256=expected_sha,
        brake_model_file=brake['path'],
        brake_model_sha256=brake['sha256'],
        clearance_schema_version=CLEARANCE_SCHEMA_VERSION,
        stop_requirement_schema_version=STOP_REQUIREMENT_SCHEMA_VERSION,
        support_scope=support_scope,
        note=args.note,
    )
    return freeze


def _dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def _write_exclusive(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(_dump(payload))


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        output = None
        if args.output is not None:
            output = Path(args.output)
            if not output.is_absolute():
                output = ROOT / output
        if not args.dry_run:
            if output is None:
                output = ROOT / DEFAULT_OUTPUT
            if output.exists():
                print('ERROR: 冻结输出已存在（refusing to overwrite/backdate）: '
                      + str(output), file=sys.stderr)
                return 2
        else:
            output = output or (ROOT / DEFAULT_OUTPUT)
        frozen_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        if args.dry_run:
            freeze = _build_payload(args, worktree_state(ROOT), frozen_at)
            print(_dump(freeze))
            return 0
        placeholder_state = worktree_state(ROOT)
        freeze = _build_payload(args, placeholder_state, frozen_at)
        _write_exclusive(output, freeze)
        actual_state = worktree_state(ROOT)
        if actual_state['status_text_sha256'] != \
                placeholder_state['status_text_sha256']:
            freeze = _build_payload(args, actual_state, frozen_at)
            Path(output).write_text(_dump(freeze), encoding='utf-8')
        print('BOUNDARY_FREEZE_WRITTEN ' + str(output)
              + ' sha256=' + _sha256_file(output))
        print('CODE_COMMIT ' + freeze['code_commit'])
        print('FROZEN_AT ' + freeze['frozen_at'])
        print('EXPECTED_FILE ' + freeze['expected_file'])
        print('EXPECTED_SHA256 ' + freeze['expected_sha256'])
        print('BRAKE_MODEL_SHA256 ' + freeze['brake_model_sha256'])
        print('WORKTREE_STATUS_SHA256 '
              + freeze['worktree_state']['status_text_sha256'])
        budget = freeze['budget']
        print('BUDGET boundary_episodes=%d special_episodes=%d '
              'regression_episodes=%d total_episodes=%d'
              % (budget['boundary_episodes'], budget['special_episodes'],
                 budget['regression_episodes'], budget['total_episodes']))
        for segment_id in freeze['segments']:
            entry = freeze['segments'][segment_id]
            print('SEGMENT %s role=%s cases=%d'
                  % (segment_id, entry['role'], len(entry['case_ids'])))
        if freeze['worktree_state']['status_text_sha256'] != \
                worktree_state(ROOT)['status_text_sha256']:
            print('WARNING: 写出后工作树状态发生变化（并发修改?）；'
                  '运行前校验可能失败，请重新生成冻结。', file=sys.stderr)
        return 0
    except (BoundaryFreezeError, FreezeGenerationError, OSError,
            ValueError, TypeError, KeyError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
