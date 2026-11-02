"""生成延迟包络正式评价的预运行冻结 v2（主配对 + 专项）。

设计依据：``docs/superpowers/plans/2026-11-02-latency-envelope.md`` §4–§5 与
Lead 2026-11-02 精确参数。

- 真实 UTC 时间 ``frozen_at``、实际 ``git rev-parse HEAD``、真实工作树状态、
  cases/map hash 全部由本脚本自算，**不接受调用者传入**；
- 输出已存在时直接失败（返回码 2），禁止覆盖或运行后倒填；
- ``--dry-run`` 只打印 ``{"pair": ..., "special": ...}`` JSON，不写盘；
- 写出采用两遍：先写入占位工作树状态，再基于真实包含两个未跟踪冻结文件的
  工作树状态重写，使冻结记录与运行入口校验完全一致；
- 正式生成必须在代码提交之后、正式运行之前执行。

示例（自测，不写正式文件名）::

    $bbPython scripts/make_latency_freeze.py --dry-run --output-root tmp/freeze_check
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from boom_birds.evaluation.latency_plan import (  # noqa: E402
    LATENCY_EVAL_VERSION,
    LatencyFreezeError,
    build_freeze,
    build_run_plan,
    git_head,
    worktree_state,
)
from boom_birds.evaluation.supervisor import SupervisorConfig  # noqa: E402
from boom_birds.sim.map_contract import (  # noqa: E402
    load_map_cases,
    load_map_contract,
)

EXPECTED_SCHEMA = 'boom_birds.latency_expected.v1'
EXPECTED_STATUS = 'EXPECTED_NOT_CONCLUSION'
EXPECTED_OUTCOMES = ('SUCCESS', 'ABORT', 'TIMEOUT', 'COLLISION',
                     'OUT_OF_BOUNDS', 'INVALID')
SPECIAL_SEGMENT_IDS = ('ttl_near', 'ttl_over', 'clock_sync', 'clock_mapping')
MAIN_CASE_IDS = (
    'dynamic_A_north_0',
    'dynamic_A_south_0',
    'dynamic_A_south_1',
    'dynamic_B_north_0',
    'dynamic_B_south_0',
    'dynamic_B_south_1',
    'dynamic_C_north_0',
    'dynamic_C_south_0',
    'dynamic_D_north_0',
    'dynamic_D_south_0',
    'dynamic_E_north_0',
    'dynamic_E_south_0',
)
SPECIAL_STOP_CASE = 'special_stop_north'

DEFAULT_MAP_CONFIG = 'configs/maps/rmuc2027.yaml'
DEFAULT_LOCAL_CONFIG = 'configs/maps/rmuc2027.local.yaml'
DEFAULT_CASES = 'configs/scenarios/map_dynamic_cases_v1.json'
DEFAULT_SPECIAL_CASES = 'configs/scenarios/latency_special_cases_v1.json'
DEFAULT_EXPECTED = 'configs/scenarios/latency_expected_v1.json'
DEFAULT_PAIR_FILENAME = 'latency_pair_freeze_v2.json'
DEFAULT_SPECIAL_FILENAME = 'latency_special_freeze_v2.json'
DEFAULT_PAIR_OUTPUT = 'configs/scenarios/' + DEFAULT_PAIR_FILENAME
DEFAULT_SPECIAL_OUTPUT = 'configs/scenarios/' + DEFAULT_SPECIAL_FILENAME

SUPERVISOR_FIELDS = (
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


class FreezeGenerationError(RuntimeError):
    """生成前置条件不满足（输入配置不一致等）。"""


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map-config', type=Path, default=Path(DEFAULT_MAP_CONFIG))
    parser.add_argument('--local-config', type=Path,
                        default=Path(DEFAULT_LOCAL_CONFIG))
    parser.add_argument('--cases', type=Path, default=Path(DEFAULT_CASES))
    parser.add_argument('--special-cases', type=Path,
                        default=Path(DEFAULT_SPECIAL_CASES))
    parser.add_argument('--expected', type=Path, default=Path(DEFAULT_EXPECTED))
    parser.add_argument('--pair-output', type=Path, default=None,
                        help='主配对冻结输出路径（默认 configs/scenarios/%s）'
                             % DEFAULT_PAIR_FILENAME)
    parser.add_argument('--special-output', type=Path, default=None,
                        help='专项冻结输出路径（默认 configs/scenarios/%s）'
                             % DEFAULT_SPECIAL_FILENAME)
    parser.add_argument('--output-root', type=Path, default=None,
                        help='同时覆盖两个输出到该目录（自测用，避免正式文件名）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印 JSON，不写盘')
    parser.add_argument('--case-ids', default=','.join(MAIN_CASE_IDS),
                        help='主配对 12 个 case_id（逗号分隔）')
    parser.add_argument('--methods', default='supervisor')
    parser.add_argument('--execution-path', default='v2', choices=('v1', 'v2'))
    parser.add_argument('--stop-a', type=float, default=1.1)
    parser.add_argument('--stop-b', type=float, default=1.38)
    parser.add_argument('--obs-delay-s', type=float, default=0.15)
    parser.add_argument('--action-delay-s', type=float, default=0.10)
    parser.add_argument('--ttl-ms', type=int, default=150)
    parser.add_argument('--max-age-ms', type=int, default=150)
    parser.add_argument('--allowed-observation-age-ms', type=int, default=300)
    parser.add_argument('--post-abort-observe-s', type=float, default=0.0)
    parser.add_argument('--clock-offset-ms', type=float, default=20.0)
    parser.add_argument('--clock-drift-ppm', type=float, default=200.0)
    parser.add_argument('--clock-uncertainty-ms', type=float, default=5.0)
    parser.add_argument('--sync-fail-step', type=int, default=-1)
    parser.add_argument('--obs-mapping-fail-step', type=int, default=-1)
    parser.add_argument('--transport-stall-step', type=int, default=-1)
    parser.add_argument('--transport-stall-delay-s', type=float, default=0.15)
    parser.add_argument('--special-case-id', default=SPECIAL_STOP_CASE,
                        help='专项段使用的 case_id（来自 latency_special_cases_v1.json）')
    parser.add_argument('--special-post-abort-observe-s', type=float, default=3.0,
                        help='ttl_over/clock_sync/clock_mapping 的 ABORT 后物理观测窗口')
    parser.add_argument('--ttl-near-ttl-ms', type=int, default=120)
    parser.add_argument('--ttl-near-action-delay-s', type=float, default=0.10)
    parser.add_argument('--ttl-near-stop-distance-m', type=float, default=1.1)
    parser.add_argument('--ttl-over-ttl-ms', type=int, default=150)
    parser.add_argument('--ttl-over-action-delay-s', type=float, default=0.10)
    parser.add_argument('--ttl-over-stop-distance-m', type=float, default=1.1)
    parser.add_argument('--ttl-over-stall-step', type=int, default=300)
    parser.add_argument('--ttl-over-stall-delay-s', type=float, default=0.15)
    parser.add_argument('--clock-sync-sync-fail-step', type=int, default=300)
    parser.add_argument('--clock-sync-stop-distance-m', type=float, default=1.1)
    parser.add_argument('--clock-mapping-fail-step', type=int, default=280)
    parser.add_argument('--clock-mapping-stop-distance-m', type=float, default=1.1)
    parser.add_argument('--body-envelope-tolerance-m', type=float, default=0.01)
    return parser


def _resolve_input(path):
    path = Path(path)
    return path if path.is_absolute() else (ROOT / path)


def _repo_relative(path):
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _resolve_outputs(args):
    if args.output_root is not None:
        root = Path(args.output_root)
        pair = args.pair_output or (root / DEFAULT_PAIR_FILENAME)
        special = args.special_output or (root / DEFAULT_SPECIAL_FILENAME)
    else:
        pair = args.pair_output or (ROOT / DEFAULT_PAIR_OUTPUT)
        special = args.special_output or (ROOT / DEFAULT_SPECIAL_OUTPUT)
    pair, special = Path(pair), Path(special)
    if pair.resolve() == special.resolve():
        raise FreezeGenerationError('主配对与专项冻结输出路径不能相同')
    return pair, special


def _supervisor_dict():
    config = SupervisorConfig()
    return {field: round(float(getattr(config, field)), 6)
            for field in SUPERVISOR_FIELDS}


def _load_expected(path):
    raw = Path(path).read_text(encoding='utf-8')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FreezeGenerationError('expected 文件不是合法 JSON: %s' % error) from error
    if payload.get('schema_version') != EXPECTED_SCHEMA:
        raise FreezeGenerationError(
            'expected schema_version 必须是 %s，得到 %r'
            % (EXPECTED_SCHEMA, payload.get('schema_version')))
    if payload.get('evaluation_version') != LATENCY_EVAL_VERSION:
        raise FreezeGenerationError(
            'expected evaluation_version 必须是 %s' % LATENCY_EVAL_VERSION)
    if payload.get('status') != EXPECTED_STATUS:
        raise FreezeGenerationError(
            'expected status 必须是 %s（预期非结论）' % EXPECTED_STATUS)
    cases = payload.get('cases')
    if not isinstance(cases, dict) or not cases:
        raise FreezeGenerationError('expected.cases 必须是非空对象')
    for case_id, entry in cases.items():
        if not isinstance(entry, dict):
            raise FreezeGenerationError('expected.cases.%s 必须是对象' % case_id)
        if entry.get('expected_outcome') not in EXPECTED_OUTCOMES:
            raise FreezeGenerationError(
                'expected.cases.%s.expected_outcome 非法: %r'
                % (case_id, entry.get('expected_outcome')))
    segments = payload.get('segments')
    if not isinstance(segments, dict) or not segments:
        raise FreezeGenerationError('expected.segments 必须是非空对象')
    if set(segments) != set(SPECIAL_SEGMENT_IDS):
        raise FreezeGenerationError(
            'expected.segments 必须恰好包含 %r，得到 %r'
            % (SPECIAL_SEGMENT_IDS, tuple(sorted(segments))))
    for segment_id, entry in segments.items():
        if not isinstance(entry, dict):
            raise FreezeGenerationError('expected.segments.%s 必须是对象' % segment_id)
        if entry.get('expected_outcome') not in EXPECTED_OUTCOMES:
            raise FreezeGenerationError(
                'expected.segments.%s.expected_outcome 非法: %r'
                % (segment_id, entry.get('expected_outcome')))
        if not isinstance(entry.get('cases'), dict) or not entry['cases']:
            raise FreezeGenerationError(
                'expected.segments.%s.cases 必须是非空对象' % segment_id)
    supervisor = payload.get('supervisor')
    if not isinstance(supervisor, dict):
        raise FreezeGenerationError('expected.supervisor 必须是对象')
    current = _supervisor_dict()
    for field in SUPERVISOR_FIELDS:
        if field not in supervisor:
            raise FreezeGenerationError(
                'expected.supervisor 缺少 %s' % field)
        try:
            value = round(float(supervisor[field]), 6)
        except (TypeError, ValueError) as error:
            raise FreezeGenerationError(
                'expected.supervisor.%s 不是数字: %r'
                % (field, supervisor[field])) from error
        if value != current[field]:
            raise FreezeGenerationError(
                'expected.supervisor.%s=%r 与 SupervisorConfig=%r 不一致，'
                '不允许冻结与实现脱节的阈值'
                % (field, supervisor[field], current[field]))
    if not isinstance(payload.get('thresholds'), dict):
        raise FreezeGenerationError('expected.thresholds 必须是对象')
    if not isinstance(payload.get('note'), str) or not payload['note'].strip():
        raise FreezeGenerationError('expected.note 必须写明"预期非结论"')
    return payload


def _collect_inputs(args):
    map_config = _resolve_input(args.map_config)
    local_config = _resolve_input(args.local_config)
    cases_path = _resolve_input(args.cases)
    special_path = _resolve_input(args.special_cases)
    expected_path = _resolve_input(args.expected)

    contract = load_map_contract(map_config, local_config)
    dynamic_cases = load_map_cases(cases_path, contract)
    special_cases = load_map_cases(special_path, contract)

    case_ids = [item.strip() for item in args.case_ids.split(',') if item.strip()]
    if not case_ids:
        raise FreezeGenerationError('--case-ids 不能为空')
    if len(set(case_ids)) != len(case_ids):
        raise FreezeGenerationError('--case-ids 含重复项')
    available = {case.case_id for case in dynamic_cases}
    unknown = sorted(set(case_ids) - available)
    if unknown:
        raise FreezeGenerationError(
            '--case-ids 中有主 cases 文件不存在的 case: ' + ', '.join(unknown))
    if args.special_case_id not in {case.case_id for case in special_cases}:
        raise FreezeGenerationError(
            '--special-case-id=%r 不在专项 cases 文件中'
            % args.special_case_id)

    expected = _load_expected(expected_path)
    if set(expected['cases']) != set(case_ids):
        raise FreezeGenerationError(
            'expected.cases 与 --case-ids 不一致（预期非结论必须逐 case 对齐）')
    for segment_id in SPECIAL_SEGMENT_IDS:
        segment = expected['segments'][segment_id]
        if segment.get('case_ids') != [args.special_case_id]:
            raise FreezeGenerationError(
                'expected.segments.%s.case_ids 必须是 [%r]'
                % (segment_id, args.special_case_id))
        if set(segment['cases']) != {args.special_case_id}:
            raise FreezeGenerationError(
                'expected.segments.%s.cases 必须恰好包含 %r'
                % (segment_id, args.special_case_id))

    methods = [item.strip() for item in args.methods.split(',') if item.strip()]
    if not methods:
        raise FreezeGenerationError('--methods 不能为空')
    return {
        'map_asset_id': contract.asset_id,
        'terrain_sha256': contract.terrain_sha256,
        'preview_sha256': contract.preview_sha256,
        'map_config_sha256': _sha256_file(map_config),
        'map_config_file': _repo_relative(map_config),
        'cases_file': _repo_relative(cases_path),
        'cases_sha256': _sha256_file(cases_path),
        'special_cases_file': _repo_relative(special_path),
        'special_cases_sha256': _sha256_file(special_path),
        'case_ids': case_ids,
        'special_case_id': args.special_case_id,
        'methods': methods,
        'expected': expected,
    }


def _main_run_plan(inputs, args, config_id, stop_distance_m):
    return build_run_plan(
        role='main',
        segment_id='',
        config_id=config_id,
        cases_file=inputs['cases_file'],
        cases_sha256=inputs['cases_sha256'],
        case_ids=inputs['case_ids'],
        methods=inputs['methods'],
        execution_path=args.execution_path,
        obs_delay_s=args.obs_delay_s,
        action_delay_s=args.action_delay_s,
        ttl_ms=args.ttl_ms,
        max_age_ms=args.max_age_ms,
        allowed_observation_age_ms=args.allowed_observation_age_ms,
        stop_distance_m=stop_distance_m,
        post_abort_observe_s=args.post_abort_observe_s,
        clock_offset_ms=args.clock_offset_ms,
        clock_drift_ppm=args.clock_drift_ppm,
        clock_uncertainty_ms=args.clock_uncertainty_ms,
        sync_fail_step=args.sync_fail_step,
        obs_mapping_fail_step=args.obs_mapping_fail_step,
        transport_stall_step=args.transport_stall_step,
        transport_stall_delay_s=args.transport_stall_delay_s,
    )


def _special_run_plan(inputs, args, segment_id, *, action_delay_s, ttl_ms,
                      stop_distance_m, post_abort_observe_s,
                      sync_fail_step=-1, obs_mapping_fail_step=-1,
                      transport_stall_step=-1, transport_stall_delay_s=0.15):
    return build_run_plan(
        role='special',
        segment_id=segment_id,
        config_id='',
        cases_file=inputs['special_cases_file'],
        cases_sha256=inputs['special_cases_sha256'],
        case_ids=[inputs['special_case_id']],
        methods=inputs['methods'],
        execution_path=args.execution_path,
        obs_delay_s=args.obs_delay_s,
        action_delay_s=action_delay_s,
        ttl_ms=ttl_ms,
        max_age_ms=args.max_age_ms,
        allowed_observation_age_ms=args.allowed_observation_age_ms,
        stop_distance_m=stop_distance_m,
        post_abort_observe_s=post_abort_observe_s,
        clock_offset_ms=args.clock_offset_ms,
        clock_drift_ppm=args.clock_drift_ppm,
        clock_uncertainty_ms=args.clock_uncertainty_ms,
        sync_fail_step=sync_fail_step,
        obs_mapping_fail_step=obs_mapping_fail_step,
        transport_stall_step=transport_stall_step,
        transport_stall_delay_s=transport_stall_delay_s,
    )


_SEGMENT_PURPOSE = {
    'ttl_near': '近 TTL 接纳：到达年龄 100 ms < TTL 120 ms，验证接纳与 20 ms 余量',
    'ttl_over': '超 TTL 到达拒绝：stall 后制动命令到达年龄 150 ms >= TTL 150 ms，'
                '验证拒绝、旧 setpoint 残余与零目标回退',
    'clock_sync': 'sync 代次传输中失效：接纳与在途到达均拒绝，post-abort 观测旧 setpoint 到期',
    'clock_mapping': '相机时钟映射失效：观测 CLOCK_MAPPING_UNUSABLE，监督器 DEGRADED→ABORT',
}


def _build_special_segments(inputs, args):
    expected = inputs['expected']['segments']
    segments = {}

    def add(segment_id, plan):
        segments[segment_id] = {
            'segment_id': segment_id,
            'purpose': _SEGMENT_PURPOSE[segment_id],
            'case_ids': list(plan['case_ids']),
            'cases_file': plan['cases_file'],
            'cases_sha256': plan['cases_sha256'],
            'run_plan': plan,
            'expected': expected[segment_id],
            'expected_note': '预期非结论，实际以独立核验为准',
        }

    add('ttl_near', _special_run_plan(
        inputs, args, 'ttl_near',
        action_delay_s=args.ttl_near_action_delay_s,
        ttl_ms=args.ttl_near_ttl_ms,
        stop_distance_m=args.ttl_near_stop_distance_m,
        post_abort_observe_s=0.0))
    add('ttl_over', _special_run_plan(
        inputs, args, 'ttl_over',
        action_delay_s=args.ttl_over_action_delay_s,
        ttl_ms=args.ttl_over_ttl_ms,
        stop_distance_m=args.ttl_over_stop_distance_m,
        post_abort_observe_s=args.special_post_abort_observe_s,
        transport_stall_step=args.ttl_over_stall_step,
        transport_stall_delay_s=args.ttl_over_stall_delay_s))
    add('clock_sync', _special_run_plan(
        inputs, args, 'clock_sync',
        action_delay_s=args.action_delay_s,
        ttl_ms=args.ttl_ms,
        stop_distance_m=args.clock_sync_stop_distance_m,
        post_abort_observe_s=args.special_post_abort_observe_s,
        sync_fail_step=args.clock_sync_sync_fail_step))
    add('clock_mapping', _special_run_plan(
        inputs, args, 'clock_mapping',
        action_delay_s=args.action_delay_s,
        ttl_ms=args.ttl_ms,
        stop_distance_m=args.clock_mapping_stop_distance_m,
        post_abort_observe_s=args.special_post_abort_observe_s,
        obs_mapping_fail_step=args.clock_mapping_fail_step))
    return segments


def _build_payloads(inputs, args, worktree, frozen_at):
    main_run_plans = {
        'A': _main_run_plan(inputs, args, 'A', args.stop_a),
        'B': _main_run_plan(inputs, args, 'B', args.stop_b),
    }
    special_segments = _build_special_segments(inputs, args)
    expected = inputs['expected']

    evaluation = {
        'version': LATENCY_EVAL_VERSION,
        'status': EXPECTED_STATUS,
        'note': expected['note'],
        'supervisor': _supervisor_dict(),
        'supervisor_overrides': {
            'A': {'stop_distance_m': round(float(args.stop_a), 6)},
            'B': {'stop_distance_m': round(float(args.stop_b), 6)},
        },
        'thresholds': expected['thresholds'],
        'expected': {
            'main': {'A': expected['cases'], 'B': expected['cases']},
            'special': {segment_id: special_segments[segment_id]['expected']
                        for segment_id in special_segments},
        },
    }
    latency_plan_defaults = {
        'obs_delay_s': args.obs_delay_s,
        'action_delay_s': args.action_delay_s,
        'ttl_ms': args.ttl_ms,
        'max_age_ms': args.max_age_ms,
        'allowed_observation_age_ms': args.allowed_observation_age_ms,
        'post_abort_observe_s': args.post_abort_observe_s,
    }
    clock_plan = {
        'camera_clock_id': 'camera_sim',
        'offset_ms': args.clock_offset_ms,
        'drift_ppm': args.clock_drift_ppm,
        'uncertainty_ms': args.clock_uncertainty_ms,
        'sync_generation_plan': {
            'initial': 0,
            'clock_sync_fail_step': args.clock_sync_sync_fail_step,
            'note': '主配对与专项开段 sync_generation=0；clock_sync 段按 '
                    '--sync-fail-step 在接纳前推进代次（发端拒绝）。',
        },
    }
    body_envelope = {
        'source': 'measured_usd_aabb_at_runtime',
        'half_extents_m': None,
        'measured_prim': None,
        'tolerance_m': args.body_envelope_tolerance_m,
        'status': 'PROPOSED',
        'note': '运行时从 USD AABB 实测并写入 manifest；冻结只记录计划来源与容差，'
                '不含实测值；核验时用 manifest 实测 AABB 与 steps 重算比对。',
    }
    cases = [
        {'cases_file': inputs['cases_file'],
         'cases_sha256': inputs['cases_sha256']},
        {'cases_file': inputs['special_cases_file'],
         'cases_sha256': inputs['special_cases_sha256']},
    ]
    map_state = {
        'map_asset_id': inputs['map_asset_id'],
        'terrain_sha256': inputs['terrain_sha256'],
        'preview_sha256': inputs['preview_sha256'],
        'map_config_sha256': inputs['map_config_sha256'],
        'map_config_file': inputs['map_config_file'],
    }
    pair = build_freeze(
        frozen_at=frozen_at,
        code_commit=git_head(ROOT),
        worktree_state=worktree,
        map_state=map_state,
        cases=cases,
        primary_cases_file=inputs['cases_file'],
        artifact='main_pair',
        main_run_plans=main_run_plans,
        special_segments=special_segments,
        evaluation=evaluation,
        clock_plan=clock_plan,
        latency_plan_defaults=latency_plan_defaults,
        body_envelope=body_envelope,
        note='主配对预运行冻结（12 case × A/B，仅 stop_distance_m 与 config_id 不同）；'
             '冻结后修改 src/scripts/tests/configs 必须新建版本并重跑受影响配对；'
             '预期非结论，实际以独立核验为准。',
    )
    special = build_freeze(
        frozen_at=frozen_at,
        code_commit=git_head(ROOT),
        worktree_state=worktree,
        map_state=map_state,
        cases=cases,
        primary_cases_file=inputs['special_cases_file'],
        artifact='special',
        main_run_plans=main_run_plans,
        special_segments=special_segments,
        evaluation=evaluation,
        clock_plan=clock_plan,
        latency_plan_defaults=latency_plan_defaults,
        body_envelope=body_envelope,
        note='专项段预运行冻结（ttl_near/ttl_over/clock_sync/clock_mapping，'
             'case 全部为 special_stop_north）；运行器 CLI 必须与 run_plan 逐字段一致；'
             '预期非结论，实际以独立核验为准。',
    )
    return {'pair': pair, 'special': special}


def _dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def _write_exclusive(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(_dump(payload))


def _rewrite_within_run(path, payload):
    Path(path).write_text(_dump(payload), encoding='utf-8')


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        pair_path, special_path = _resolve_outputs(args)
    except FreezeGenerationError as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1
    if not args.dry_run:
        existing = [str(path) for path in (pair_path, special_path)
                    if path.exists()]
        if existing:
            print('ERROR: 冻结输出已存在（refusing to overwrite/backdate）: '
                  + ', '.join(existing), file=sys.stderr)
            return 2
    try:
        inputs = _collect_inputs(args)
        frozen_at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        if args.dry_run:
            payloads = _build_payloads(inputs, args, worktree_state(ROOT),
                                       frozen_at)
            print(json.dumps({'pair': payloads['pair'],
                              'special': payloads['special']},
                             ensure_ascii=False, indent=2))
            return 0
        placeholder_state = worktree_state(ROOT)
        payloads = _build_payloads(inputs, args, placeholder_state, frozen_at)
        _write_exclusive(pair_path, payloads['pair'])
        _write_exclusive(special_path, payloads['special'])
        actual_state = worktree_state(ROOT)
        if actual_state['status_text_sha256'] != \
                placeholder_state['status_text_sha256']:
            payloads = _build_payloads(inputs, args, actual_state, frozen_at)
            _rewrite_within_run(pair_path, payloads['pair'])
            _rewrite_within_run(special_path, payloads['special'])
        pair = payloads['pair']
        for path, payload in ((pair_path, payloads['pair']),
                              (special_path, payloads['special'])):
            print('LATENCY_FREEZE_WRITTEN ' + str(path)
                  + ' sha256=' + _sha256_file(path)
                  + ' artifact=' + payload['artifact'])
        print('CODE_COMMIT ' + pair['code_commit'])
        print('FROZEN_AT ' + pair['frozen_at'])
        print('WORKTREE_STATUS_SHA256 '
              + pair['worktree_state']['status_text_sha256'])
        if pair['worktree_state']['status_text_sha256'] != \
                worktree_state(ROOT)['status_text_sha256']:
            print('WARNING: 写出后工作树状态发生变化（并发修改?）；'
                  '运行前校验可能失败，请重新生成冻结。', file=sys.stderr)
        return 0
    except (LatencyFreezeError, FreezeGenerationError, OSError,
            ValueError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
