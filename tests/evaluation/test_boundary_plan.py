"""回归测试：clearance 边界专项预运行冻结契约（boundary_plan / make_boundary_freeze）。

覆盖计划 §5（场景与冻结）、Lead 2026-11-02 的 9 段修正与任务 U2：
- ``build_run_plan`` 归一化（浮点 round(...,6)、路径 posix、case_ids 排序、
  methods 顺序保持、9 段名/role 固定映射）与非法输入拒绝；
- expected 文件：24 个 boundary case（8 类、repeats=1、U3 kind 集合）、6 个
  expected 段（4 boundary + 2 special）、special 段 acceptable_paths/(c) 判据、
  regression 段不写预期、与 U3 ``ExpectedIndex`` 契约逐项可消费；
- ``build_freeze``：单文件 9 段冻结、budget 24/2/3/29、support_scope、
  regression expected=null、不得缺段/错配；
- ``validate_run_plan`` 逐字段比对（含 1e-6 归一化噪声容忍）；
- ``check_freeze_lineage``：frozen_at 未来/倒填、HEAD、worktree digest；
- ``worktree_state`` 与 ``latency_plan`` 归一化规则逐字节一致；
- ``make_boundary_freeze`` 脚本：--dry-run 不落盘、已存在拒绝覆盖、expected
  case 缺失拒绝、regression 段默认参数正确。
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from boom_birds.evaluation.boundary_plan import (  # noqa: E402
    BOUNDARY_SEGMENT_IDS,
    BRAKE_MODEL_SPEED_SUPPORT_MPS,
    BUSINESS_OUTCOMES,
    CLEARANCE_BOUNDARY_FREEZE_SCHEMA,
    CLEARANCE_SCHEMA_VERSION,
    EXPECTED_FREEZE_RULE,
    EXPECTED_SEGMENT_IDS,
    FREEZE_SCOPE,
    FREEZE_STATUS,
    MIN_BOUNDARY_EPISODES,
    MUST_CONDITION_KINDS,
    REGRESSION_SEGMENT_IDS,
    RUN_PLAN_FIELDS,
    SCENARIO_CLASSES,
    SEGMENT_IDS,
    SEGMENT_ROLES,
    SPECIAL_SEGMENT_IDS,
    STOP_REQUIREMENT_SCHEMA_VERSION,
    TRACKED_PATHS,
    BoundaryFreezeError,
    build_freeze,
    build_run_plan,
    check_freeze_lineage,
    expected_case,
    git_head,
    load_expected_file,
    validate_run_plan,
    worktree_state,
)

EXPECTED_FILE = 'configs/scenarios/clearance_boundary_expected_v1.json'
BOUNDARY_CASES_FILE = 'configs/scenarios/clearance_boundary_cases_v1.json'
SPECIAL_CASES_FILE = 'configs/scenarios/latency_special_cases_v1.json'
DYNAMIC_CASES_FILE = 'configs/scenarios/map_dynamic_cases_v1.json'
REGRESSION_CASES_FILE = 'configs/scenarios/map_v2_regression_cases_v1.json'
FAULT_CASES_FILE = 'configs/scenarios/map_v2_fault_cases_v1.json'
FAST_VEHICLE = 'configs/vehicles/sim_reference_boundary_fast.yaml'
DEFAULT_VEHICLE = 'configs/vehicles/sim_reference.yaml'
BRAKE_FILE = 'configs/scenarios/brake_model_v1.json'
TERRAIN_SHA = '1' * 64
PREVIEW_SHA = '2' * 64
MAP_CONFIG_SHA = '3' * 64
WORKTREE_SHA = 'c' * 64
VEHICLE_SHA = 'd' * 64
BRAKE_SHA = 'e' * 64

REGRESSION_SPECS = {
    'regression_dynamic': (DYNAMIC_CASES_FILE, ['dynamic_A_south_0']),
    'regression_no_obstacle': (REGRESSION_CASES_FILE,
                               ['v2_reg_route_south_R1']),
    'regression_fault': (FAULT_CASES_FILE, ['fault_ttl_expiry_0']),
}
REGRESSION_RUN_PARAMS = {
    'vehicle_config': DEFAULT_VEHICLE,
    'methods': ['supervisor'],
    'execution_path': 'v2',
    'obs_delay_s': 0.0,
    'action_delay_s': 0.0,
    'ttl_ms': 150,
    'max_age_ms': 150,
    'allowed_observation_age_ms': 250,
    'stop_distance_m': 1.1,
    'post_abort_observe_s': 0.0,
    'clock_offset_ms': 0.0,
    'clock_drift_ppm': 0.0,
    'clock_uncertainty_ms': 0.0,
    'sync_fail_step': -1,
    'obs_mapping_fail_step': -1,
    'transport_stall_step': -1,
    'transport_stall_delay_s': 0.15,
}


def _now_iso(offset_s=0.0):
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_s)).isoformat(timespec='microseconds')


def _cases_sha(cases_file):
    return hashlib.sha256(cases_file.encode('utf-8')).hexdigest()


def _real_expected():
    payload, sha = load_expected_file(ROOT / EXPECTED_FILE)
    return payload, sha


def _segment_plans(expected, expected_sha, overrides=None):
    plans = {}
    for segment_id in SEGMENT_IDS:
        if segment_id in REGRESSION_SEGMENT_IDS:
            cases_file, case_ids = REGRESSION_SPECS[segment_id]
            run_params = dict(REGRESSION_RUN_PARAMS)
        else:
            defaults = expected['segments'][segment_id]['defaults']
            cases_file = defaults['cases_file']
            case_ids = list(defaults['case_ids'])
            run_params = dict(defaults['run_params'])
        kwargs = dict(run_params)
        kwargs.update(
            segment_id=segment_id,
            role=SEGMENT_ROLES[segment_id],
            cases_file=cases_file,
            cases_sha256=_cases_sha(cases_file),
            case_ids=case_ids,
            vehicle_config_sha256=VEHICLE_SHA,
            expected_file=EXPECTED_FILE,
            expected_sha256=expected_sha,
            brake_model_sha256=BRAKE_SHA,
            clearance_schema_version=CLEARANCE_SCHEMA_VERSION,
            stop_requirement_schema_version=STOP_REQUIREMENT_SCHEMA_VERSION,
        )
        if overrides and segment_id in overrides:
            kwargs.update(overrides[segment_id])
        plans[segment_id] = build_run_plan(**kwargs)
    return plans


def _declared_cases(plans):
    index = {}
    for plan in plans.values():
        index[plan['cases_file']] = plan['cases_sha256']
    return [{'cases_file': path, 'cases_sha256': sha}
            for path, sha in sorted(index.items())]


def _freeze_kwargs(**overrides):
    expected, expected_sha = _real_expected()
    plans = _segment_plans(expected, expected_sha)
    kwargs = dict(
        frozen_at=_now_iso(),
        code_commit='f' * 40,
        worktree_state={'tracked_paths': list(TRACKED_PATHS),
                        'status_text_sha256': WORKTREE_SHA, 'clean': False},
        map_state={'map_asset_id': 'rmuc2027-isaacsim-20261028',
                   'terrain_sha256': TERRAIN_SHA,
                   'preview_sha256': PREVIEW_SHA,
                   'map_config_sha256': MAP_CONFIG_SHA,
                   'map_config_file': 'configs/maps/rmuc2027.yaml'},
        cases=_declared_cases(plans),
        segment_run_plans=plans,
        expected=expected,
        expected_file=EXPECTED_FILE,
        expected_sha256=expected_sha,
        brake_model_file=BRAKE_FILE,
        brake_model_sha256=BRAKE_SHA,
        note='测试冻结：预期非结论，实际以独立核验为准。',
    )
    kwargs.update(overrides)
    return kwargs


def _freeze(**overrides):
    return build_freeze(**_freeze_kwargs(**overrides))


def _plan(segment_id='boundary_default', **overrides):
    expected, expected_sha = _real_expected()
    if segment_id not in SEGMENT_IDS:
        defaults = expected['segments']['boundary_default']['defaults']
        kwargs = dict(defaults['run_params'])
        kwargs.update(
            segment_id=segment_id,
            role='boundary',
            cases_file=defaults['cases_file'],
            cases_sha256=_cases_sha(defaults['cases_file']),
            case_ids=list(defaults['case_ids']),
            vehicle_config_sha256=VEHICLE_SHA,
            expected_file=EXPECTED_FILE,
            expected_sha256=expected_sha,
            brake_model_sha256=BRAKE_SHA,
            clearance_schema_version=CLEARANCE_SCHEMA_VERSION,
            stop_requirement_schema_version=STOP_REQUIREMENT_SCHEMA_VERSION,
        )
        kwargs.update(overrides)
        return build_run_plan(**kwargs)
    return _segment_plans(expected, expected_sha,
                          {segment_id: overrides})[segment_id]


# ---------------------------------------------------------------------------
# build_run_plan：归一化与非法输入
# ---------------------------------------------------------------------------

def test_build_run_plan_normalizes_float_path_and_case_order():
    plan = _plan('boundary_default', obs_delay_s=0.123456789,
                 action_delay_s=0.1000004,
                 cases_file='configs\\scenarios\\clearance_boundary_cases_v1.json',
                 case_ids=['boundary_B_cross_late_r1',
                           'boundary_A_static_far_r0'])
    assert plan['obs_delay_s'] == 0.123457
    assert plan['action_delay_s'] == 0.1
    assert plan['cases_file'] == BOUNDARY_CASES_FILE
    assert plan['case_ids'] == ['boundary_A_static_far_r0',
                                'boundary_B_cross_late_r1']
    assert tuple(plan) == RUN_PLAN_FIELDS


def test_build_run_plan_keeps_methods_order():
    plan = _plan(methods=['follow_only', 'supervisor'])
    assert plan['methods'] == ['follow_only', 'supervisor']


def test_build_run_plan_contains_documented_fields():
    plan = _plan('boundary_fast')
    assert plan['segment_id'] == 'boundary_fast'
    assert plan['role'] == 'boundary'
    assert plan['vehicle_config'] == FAST_VEHICLE
    assert plan['vehicle_config_sha256'] == VEHICLE_SHA
    assert plan['ttl_ms'] == 150
    assert plan['max_age_ms'] == 150
    assert plan['allowed_observation_age_ms'] == 300
    assert plan['stop_distance_m'] == 1.1
    assert plan['post_abort_observe_s'] == 3.0
    assert plan['clock_offset_ms'] == 20.0
    assert plan['clock_drift_ppm'] == 200.0
    assert plan['clock_uncertainty_ms'] == 5.0
    assert plan['expected_file'] == EXPECTED_FILE
    assert plan['brake_model_sha256'] == BRAKE_SHA
    assert plan['clearance_schema_version'] == CLEARANCE_SCHEMA_VERSION
    assert plan['stop_requirement_schema_version'] == STOP_REQUIREMENT_SCHEMA_VERSION
    json.dumps(plan)


def test_e_delay_segments_have_segment_level_delays():
    e1 = _plan('boundary_delay_e1')
    e2 = _plan('boundary_delay_e2')
    assert (e1['obs_delay_s'], e1['action_delay_s']) == (0.2, 0.1)
    assert (e2['obs_delay_s'], e2['action_delay_s']) == (0.18, 0.12)
    assert e1['case_ids'] == [
        'boundary_E_delay_insufficient_r0', 'boundary_E_delay_insufficient_r1']
    assert e2['case_ids'] == [
        'boundary_E_action_late_r0', 'boundary_E_action_late_r1']
    assert e1['role'] == e2['role'] == 'boundary'


def test_recheck_and_regression_segment_parameters():
    clock = _plan('latency_clock_mapping_recheck')
    assert clock['role'] == 'special'
    assert clock['obs_mapping_fail_step'] == 280
    ttl = _plan('latency_ttl_over_recheck')
    assert ttl['role'] == 'special'
    assert ttl['transport_stall_step'] == 300
    assert ttl['transport_stall_delay_s'] == 0.15
    for segment_id in REGRESSION_SEGMENT_IDS:
        plan = _plan(segment_id)
        assert plan['role'] == 'regression'
        assert plan['obs_delay_s'] == 0.0
        assert plan['action_delay_s'] == 0.0
        assert plan['allowed_observation_age_ms'] == 250
        assert plan['post_abort_observe_s'] == 0.0
        assert plan['clock_offset_ms'] == 0.0


def test_build_run_plan_rejects_unknown_and_missing_fields():
    with pytest.raises(BoundaryFreezeError, match='UNKNOWN'):
        _plan(surprise=1)
    with pytest.raises(BoundaryFreezeError, match='MISSING'):
        build_run_plan(segment_id='boundary_default', role='boundary')


def test_build_run_plan_rejects_unknown_segment_and_role_mismatch():
    with pytest.raises(BoundaryFreezeError, match='SEGMENT_ID'):
        _plan('boundary_unknown')
    with pytest.raises(BoundaryFreezeError, match='SEGMENT_ROLE_MISMATCH'):
        _plan('latency_clock_mapping_recheck', role='boundary')
    with pytest.raises(BoundaryFreezeError, match='SEGMENT_ROLE_MISMATCH'):
        _plan('boundary_fast', role='special')


def test_build_run_plan_rejects_bad_scalars():
    with pytest.raises(BoundaryFreezeError, match='EXECUTION_PATH'):
        _plan(execution_path='v3')
    with pytest.raises(BoundaryFreezeError, match='NEGATIVE'):
        _plan(obs_delay_s=-0.1)
    with pytest.raises(BoundaryFreezeError, match='HASH'):
        _plan(vehicle_config_sha256='not-a-hash')
    with pytest.raises(BoundaryFreezeError, match='STEP'):
        _plan(sync_fail_step=-2)
    with pytest.raises(BoundaryFreezeError, match='VEHICLE_CONFIG'):
        _plan(vehicle_config='configs/vehicles/sim_reference.json')
    with pytest.raises(BoundaryFreezeError, match='SCHEMA_VERSION'):
        _plan(clearance_schema_version='boom_birds.clearance.v2')
    with pytest.raises(BoundaryFreezeError, match='SCHEMA_VERSION'):
        _plan(stop_requirement_schema_version='boom_birds.stop_requirement.v2')
    with pytest.raises(BoundaryFreezeError, match='CASE_IDS'):
        _plan(case_ids=['boundary_A_static_far_r0',
                        'boundary_A_static_far_r0'])
    with pytest.raises(BoundaryFreezeError, match='METHODS'):
        _plan(methods=['follow_only', 'follow_only'])


# ---------------------------------------------------------------------------
# expected 文件结构（U3 契约、24 case、8 类、repeats=1、6 段、专项预声明）
# ---------------------------------------------------------------------------

def test_expected_file_covers_24_boundary_cases():
    expected, _ = _real_expected()
    assert expected['status'] == 'EXPECTED_NOT_CONCLUSION'
    assert '预期非结论' in expected['note']
    assert EXPECTED_FREEZE_RULE in expected['freeze_rule']
    cases = expected['cases']
    assert len(cases) == 24
    boundary_ids = set()
    for segment_id in BOUNDARY_SEGMENT_IDS:
        boundary_ids.update(
            expected['segments'][segment_id]['defaults']['case_ids'])
    assert set(cases) == boundary_ids
    for case_id, entry in cases.items():
        assert entry['scenario_class'] in SCENARIO_CLASSES
        assert entry['acceptable_outcomes']
        assert set(entry['acceptable_outcomes']) <= set(BUSINESS_OUTCOMES)
        assert entry['repeats'] == 1
        assert case_id.endswith(('_r0', '_r1'))
        assert isinstance(entry['unsupported_allowed'], (bool, list))
        kinds = [item if isinstance(item, str) else item['kind']
                 for item in entry['must_conditions']]
        assert kinds
        assert set(kinds) <= set(MUST_CONDITION_KINDS)
        assert entry['design'] and entry['performance_note']
    bases = {case_id.rsplit('_r', 1)[0] for case_id in cases}
    assert len(bases) == 12


def test_expected_boundary_segments_split_18_2_2_2():
    expected, _ = _real_expected()
    segments = expected['segments']
    assert set(segments) == set(EXPECTED_SEGMENT_IDS)
    assert set(segments) & set(REGRESSION_SEGMENT_IDS) == set()
    counts = {segment_id: len(segments[segment_id]['defaults']['case_ids'])
              for segment_id in BOUNDARY_SEGMENT_IDS}
    assert counts == {'boundary_default': 18, 'boundary_delay_e1': 2,
                      'boundary_delay_e2': 2, 'boundary_fast': 2}
    assert sum(counts.values()) == MIN_BOUNDARY_EPISODES
    assert segments['boundary_delay_e1']['defaults']['run_params'][
        'obs_delay_s'] == 0.2
    assert segments['boundary_delay_e2']['defaults']['run_params'][
        'action_delay_s'] == 0.12
    assert segments['boundary_fast']['defaults']['run_params'][
        'vehicle_config'] == FAST_VEHICLE
    for segment_id in BOUNDARY_SEGMENT_IDS:
        defaults = segments[segment_id]['defaults']
        assert segments[segment_id]['cases'] == {}
        for field in ('vehicle_config', 'methods', 'execution_path',
                      'obs_delay_s', 'action_delay_s', 'ttl_ms', 'max_age_ms',
                      'allowed_observation_age_ms', 'stop_distance_m',
                      'post_abort_observe_s', 'clock_offset_ms',
                      'clock_drift_ppm', 'clock_uncertainty_ms',
                      'sync_fail_step', 'obs_mapping_fail_step',
                      'transport_stall_step', 'transport_stall_delay_s'):
            assert field in defaults['run_params']


def test_expected_special_segments_declare_pre_run_criteria():
    expected, _ = _real_expected()
    clock = expected['segments']['latency_clock_mapping_recheck']
    assert clock['defaults']['cases_file'] == SPECIAL_CASES_FILE
    assert clock['defaults']['case_ids'] == ['special_stop_north']
    paths = clock['defaults']['acceptable_paths']
    assert [item['priority'] for item in paths] == [1, 2]
    assert paths[0]['admission_reject_reason'] == 'REJECT_STALE_OBSERVATION'
    assert paths[0]['observation_reason'] == 'CLOCK_MAPPING_UNUSABLE'
    assert paths[0]['supervisor_state'] == 'DEGRADED_ABORT'
    assert paths[1]['supervisor_reason'] == 'OBSERVATION_STALE'
    assert paths[1]['episode_reason'] == 'OBSERVATION_STALE'
    assert clock['defaults']['must_hit_declared_path'] is True
    assert EXPECTED_FREEZE_RULE in clock['defaults']['freeze_rule']
    # special case 不冒充 8 类（Lead 裁决）
    clock_case = clock['cases']['special_stop_north']
    assert 'scenario_class' not in clock_case
    assert clock_case['repeats'] == 1
    ttl = expected['segments']['latency_ttl_over_recheck']
    criteria = ttl['defaults']['criteria']
    assert ttl['defaults']['criteria_id'] == '(c)'
    assert ttl['defaults']['acceptable_outcomes'] == ['ABORT', 'TIMEOUT']
    for key in ('rejected_before_executed', 'rejected_action_not_executed',
                'old_valid_setpoint_before_first_reject', 'expiry_to_none',
                'zero_target_fallback'):
        assert criteria[key] is True
    assert criteria['business_outcomes'] == ['ABORT', 'TIMEOUT']
    assert EXPECTED_FREEZE_RULE in ttl['defaults']['freeze_rule']
    assert ttl['defaults']['run_params']['transport_stall_step'] == 300


def test_expected_brake_model_declaration_matches_frozen_model():
    expected, _ = _real_expected()
    brake = expected['brake_model']
    assert brake['file'] == BRAKE_FILE
    assert brake['version'] == 'brake_final4.v1'
    assert [round(float(x), 6) for x in brake['speed_support_mps']] == \
        list(BRAKE_MODEL_SPEED_SUPPORT_MPS)


def test_expected_config_is_consumable_by_u3_expected_index():
    verifier_path = ROOT / 'scripts' / 'verify_clearance_boundary_runs.py'
    if not verifier_path.is_file():
        pytest.skip('U3 verifier 尚未落盘')
    spec = importlib.util.spec_from_file_location(
        'verify_clearance_boundary_runs_contract_check', verifier_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # pragma: no cover - import-time failure
        pytest.skip('U3 verifier 暂时无法导入: %r' % (error,))
    payload, _ = _real_expected()
    index = module.ExpectedIndex()
    index.add_config(payload)
    assert len(index.cases) == 24
    for case_id, entry in payload['cases'].items():
        assert entry['scenario_class'] in module.SCENARIO_CLASSES
        for condition in entry['must_conditions']:
            kind = condition if isinstance(condition, str) else condition['kind']
            assert kind in module.MUST_CONDITION_KINDS
        assert entry['repeats'] == 1
    spec_boundary = index.lookup('boundary_default',
                                 'boundary_A_static_far_r0')
    assert spec_boundary['scenario_class'] == 'BLOCKED_EXIT'
    assert spec_boundary['acceptable_outcomes'] == ['ABORT', 'TIMEOUT']
    clock = index.lookup('latency_clock_mapping_recheck',
                         'special_stop_north')
    assert len(clock['acceptable_paths']) == 2
    assert clock['must_hit_declared_path'] is True
    if hasattr(module, '_SPECIAL_PATH_FIELDS'):
        for path in clock['acceptable_paths']:
            declared = [key for key in path
                        if key in module._SPECIAL_PATH_FIELDS and path[key]]
            assert declared, 'clock 路径必须声明 U3 识别的 reason 字段'
    ttl_defaults = index.segment_spec('latency_ttl_over_recheck')['defaults']
    assert any(isinstance(ttl_defaults.get(key), list) and ttl_defaults[key]
               for key in ('acceptable_outcomes', 'business_outcomes',
                           'expected_outcomes'))
    ttl = index.lookup('latency_ttl_over_recheck', 'special_stop_north')
    assert ttl['criteria_id'] == '(c)'
    # U3 对 role=regression 且无预期显式放行
    assert index.lookup('regression_dynamic', 'dynamic_A_south_0') is None


# ---------------------------------------------------------------------------
# build_freeze：单文件 9 段、budget、regression expected=null、support_scope
# ---------------------------------------------------------------------------

def test_build_freeze_contains_single_file_segments_contract():
    freeze = _freeze()
    expected, expected_sha = _real_expected()
    assert freeze['schema_version'] == CLEARANCE_BOUNDARY_FREEZE_SCHEMA
    assert freeze['status'] == FREEZE_STATUS
    assert freeze['scope'] == FREEZE_SCOPE
    assert freeze['expected_file'] == EXPECTED_FILE
    assert freeze['expected_sha256'] == expected_sha
    assert freeze['brake_model_file'] == BRAKE_FILE
    assert freeze['brake_model_sha256'] == BRAKE_SHA
    assert freeze['clearance_schema_version'] == CLEARANCE_SCHEMA_VERSION
    assert freeze['stop_requirement_schema_version'] == \
        STOP_REQUIREMENT_SCHEMA_VERSION
    assert freeze['map_asset_id'] == 'rmuc2027-isaacsim-20261028'
    assert list(freeze['segments']) == list(SEGMENT_IDS)
    assert 'main_run_plans' not in freeze
    for segment_id, segment in freeze['segments'].items():
        assert segment['segment_id'] == segment_id
        assert segment['role'] == SEGMENT_ROLES[segment_id]
        assert segment['case_ids'] == segment['run_plan']['case_ids']
        assert segment['cases_file'] == segment['run_plan']['cases_file']
        assert segment['run_plan']['role'] == segment['role']
        assert 'expected_note' in segment
        if segment_id in REGRESSION_SEGMENT_IDS:
            assert segment['expected'] is None
        else:
            assert segment['expected'] is not None
    boundary_ids = set()
    for segment_id in BOUNDARY_SEGMENT_IDS:
        boundary_ids.update(freeze['segments'][segment_id]['case_ids'])
    assert set(freeze['expected']['cases']) == boundary_ids
    assert set(freeze['expected']['segments']) == set(EXPECTED_SEGMENT_IDS)
    assert freeze['budget'] == {
        'boundary_episodes': 24,
        'special_episodes': 2,
        'regression_episodes': 3,
        'total_episodes': 29,
        'min_boundary_episodes_required': 24,
    }
    assert freeze['budget']['boundary_episodes'] >= MIN_BOUNDARY_EPISODES
    assert freeze['support_scope']['scope'] == FREEZE_SCOPE
    assert freeze['support_scope']['brake_model_version'] == 'brake_final4.v1'
    assert freeze['support_scope']['brake_model_speed_support_mps'] == \
        list(BRAKE_MODEL_SPEED_SUPPORT_MPS)
    assert set(freeze['support_scope']['vehicle_configs']) == {
        DEFAULT_VEHICLE, FAST_VEHICLE}
    assert freeze['support_scope']['limitations']
    assert '预期非结论' in freeze['note']
    json.dumps(freeze)


def test_freeze_embeds_expected_and_helper_lookup():
    freeze = _freeze()
    entry = expected_case(freeze, 'boundary_D_fast_cross_r1')
    assert entry['scenario_class'] == 'HIGH_SPEED_STOP'
    assert entry['unsupported_allowed'] == [
        'ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT']
    special = expected_case(freeze, 'special_stop_north')
    assert 'scenario_class' not in special
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_CASE_MISSING'):
        expected_case(freeze, 'not_a_case')


def test_build_freeze_rejects_missing_or_extra_segment():
    kwargs = _freeze_kwargs()
    plans = dict(kwargs['segment_run_plans'])
    plans.pop('regression_fault')
    with pytest.raises(BoundaryFreezeError, match='SEGMENTS_MISMATCH'):
        _freeze(segment_run_plans=plans)
    plans = dict(kwargs['segment_run_plans'])
    plans['boundary_unknown'] = plans['boundary_default']
    with pytest.raises(BoundaryFreezeError, match='SEGMENTS_MISMATCH'):
        _freeze(segment_run_plans=plans)


def test_build_freeze_rejects_missing_or_extra_expected_segment():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    del expected['segments']['boundary_delay_e1']
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_SEGMENTS_MISMATCH'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    expected['segments']['boundary_unknown'] = copy.deepcopy(
        expected['segments']['boundary_default'])
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_SEGMENTS_MISMATCH'):
        _freeze(expected=expected)


def test_build_freeze_rejects_expected_case_ids_mismatch():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    defaults = expected['segments']['boundary_delay_e1']['defaults']
    defaults['case_ids'] = defaults['case_ids'][:-1]
    with pytest.raises(BoundaryFreezeError, match='CASE_IDS_MISMATCH'):
        _freeze(expected=expected)


def test_build_freeze_rejects_expected_run_param_mismatch():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    expected['segments']['boundary_default']['defaults']['run_params'][
        'obs_delay_s'] = 0.2
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_RUN_PARAM_MISMATCH'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    expected['segments']['boundary_fast']['defaults']['run_params'][
        'vehicle_config'] = DEFAULT_VEHICLE
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_RUN_PARAM_MISMATCH'):
        _freeze(expected=expected)


def test_build_freeze_rejects_missing_case_expected():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    del expected['cases']['boundary_A_static_far_r0']
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_CASE'):
        _freeze(expected=expected)


def test_build_freeze_rejects_insufficient_boundary_episodes():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    defaults = expected['segments']['boundary_delay_e1']['defaults']
    for case_id in ('boundary_A_static_far_r0', 'boundary_A_static_far_r1',
                    'boundary_E_delay_insufficient_r0'):
        del expected['cases'][case_id]
        if case_id in defaults['case_ids']:
            defaults['case_ids'].remove(case_id)
        else:
            expected['segments']['boundary_default']['defaults'][
                'case_ids'].remove(case_id)
    plans = _segment_plans(expected, _freeze_kwargs()['expected_sha256'])
    with pytest.raises(BoundaryFreezeError, match='BOUNDARY_EPISODES'):
        _freeze(expected=expected, segment_run_plans=plans,
                cases=_declared_cases(plans))


def test_build_freeze_rejects_special_class_and_empty_boundary_conditions():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    clock = expected['segments']['latency_clock_mapping_recheck']
    clock['cases']['special_stop_north']['scenario_class'] = 'BLOCKED_EXIT'
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_CASE_CLASS_NOT_ALLOWED'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    expected['cases']['boundary_A_static_far_r0']['must_conditions'] = []
    with pytest.raises(BoundaryFreezeError, match='must_conditions'):
        _freeze(expected=expected)


def test_build_freeze_rejects_clock_paths_without_freeze_rule():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    clock = expected['segments']['latency_clock_mapping_recheck']['defaults']
    clock['freeze_rule'] = '运行前冻结'
    with pytest.raises(BoundaryFreezeError, match='FREEZE_RULE'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    clock = expected['segments']['latency_clock_mapping_recheck']['defaults']
    clock['acceptable_paths'] = []
    with pytest.raises(BoundaryFreezeError, match='ACCEPTABLE_PATHS'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    clock = expected['segments']['latency_clock_mapping_recheck']['defaults']
    clock['acceptable_paths'][1]['priority'] = 1
    with pytest.raises(BoundaryFreezeError, match='PRIORITY'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    clock = expected['segments']['latency_clock_mapping_recheck']['defaults']
    clock['acceptable_paths'][0] = {'priority': 1, 'path_id': 'x'}
    with pytest.raises(BoundaryFreezeError, match='REASON'):
        _freeze(expected=expected)


def test_build_freeze_rejects_ttl_criteria_relaxation():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    ttl = expected['segments']['latency_ttl_over_recheck']['defaults']
    ttl['criteria']['rejected_action_not_executed'] = False
    with pytest.raises(BoundaryFreezeError, match='TTL_CRITERIA'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    ttl = expected['segments']['latency_ttl_over_recheck']['defaults']
    ttl['criteria_id'] = '(a)'
    with pytest.raises(BoundaryFreezeError, match='criteria_id'):
        _freeze(expected=expected)
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    del expected['segments']['latency_ttl_over_recheck']['defaults'][
        'criteria']['expiry_to_none']
    with pytest.raises(BoundaryFreezeError, match='TTL_CRITERIA_MISSING'):
        _freeze(expected=expected)


def test_build_freeze_rejects_unknown_condition_kind():
    expected = copy.deepcopy(_freeze_kwargs()['expected'])
    expected['cases']['boundary_A_static_far_r0']['must_conditions'] = [
        'definitely_not_a_kind']
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_CONDITION_UNKNOWN'):
        _freeze(expected=expected)


def test_build_freeze_rejects_expected_file_and_hash_mismatch():
    kwargs = _freeze_kwargs()
    plans = dict(kwargs['segment_run_plans'])
    plans['boundary_default'] = dict(plans['boundary_default'],
                                     expected_sha256='b' * 64)
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_SHA256'):
        _freeze(segment_run_plans=plans)
    plans = dict(kwargs['segment_run_plans'])
    plans['boundary_default'] = dict(
        plans['boundary_default'],
        expected_file='configs/scenarios/other.json')
    with pytest.raises(BoundaryFreezeError, match='EXPECTED_FILE'):
        _freeze(segment_run_plans=plans)


def test_build_freeze_rejects_undeclared_case_file():
    kwargs = _freeze_kwargs()
    cases = [entry for entry in kwargs['cases']
             if entry['cases_file'] != BOUNDARY_CASES_FILE]
    with pytest.raises(BoundaryFreezeError, match='CASE_FILE_NOT_DECLARED'):
        _freeze(cases=cases)


def test_build_freeze_rejects_budget_mismatch_and_bad_shape():
    with pytest.raises(BoundaryFreezeError, match='BUDGET_MISMATCH'):
        _freeze(budget={'boundary_episodes': 18})
    with pytest.raises(BoundaryFreezeError, match='BUDGET'):
        _freeze(budget='lots')
    with pytest.raises(BoundaryFreezeError, match='NOTE'):
        _freeze(note='冻结说明')


def test_build_freeze_rejects_bad_support_scope():
    with pytest.raises(BoundaryFreezeError, match='SUPPORT_SCOPE'):
        _freeze(support_scope={'scope': FREEZE_SCOPE})
    scope = {
        'scope': FREEZE_SCOPE,
        'evidence_domain': 'GUI',
        'simulation_models': ['kinematic_obstacle'],
        'brake_model_version': 'other_model.v1',
        'brake_model_speed_support_mps': [0.1, 0.5],
        'vehicle_configs': {DEFAULT_VEHICLE: 'default'},
        'limitations': ['x'],
    }
    with pytest.raises(BoundaryFreezeError, match='SUPPORT_SCOPE'):
        _freeze(support_scope=scope)


def test_build_freeze_rejects_naive_frozen_at_or_bad_hash_shape():
    with pytest.raises(BoundaryFreezeError, match='TIMEZONE'):
        _freeze(frozen_at='2026-11-02T12:00:00')
    map_state = dict(_freeze_kwargs()['map_state'])
    map_state['terrain_sha256'] = 'xyz'
    with pytest.raises(BoundaryFreezeError, match='HASH'):
        _freeze(map_state=map_state)
    with pytest.raises(BoundaryFreezeError, match='WORKTREE_STATE'):
        _freeze(worktree_state={'tracked_paths': ['src'],
                                'status_text_sha256': WORKTREE_SHA})


# ---------------------------------------------------------------------------
# validate_run_plan
# ---------------------------------------------------------------------------

def test_validate_run_plan_accepts_frozen_plans():
    freeze = _freeze()
    for segment_id in SEGMENT_IDS:
        plan = dict(freeze['segments'][segment_id]['run_plan'])
        assert validate_run_plan(freeze, segment_id, plan) is None


def test_validate_run_plan_accepts_rounding_noise_and_case_reorder():
    freeze = _freeze()
    plan = dict(freeze['segments']['boundary_default']['run_plan'])
    plan['obs_delay_s'] = 0.1500004
    plan['case_ids'] = list(reversed(plan['case_ids']))
    assert validate_run_plan(freeze, 'boundary_default', plan) is None


def test_validate_run_plan_rejects_field_mismatch():
    freeze = _freeze()
    plan = dict(freeze['segments']['boundary_delay_e1']['run_plan'])
    plan['obs_delay_s'] = 0.15
    with pytest.raises(BoundaryFreezeError, match='RUN_PLAN_MISMATCH'):
        try:
            validate_run_plan(freeze, 'boundary_delay_e1', plan)
        except BoundaryFreezeError as error:
            assert 'obs_delay_s' in str(error)
            raise


def test_validate_run_plan_rejects_unknown_segment_and_bad_schema():
    freeze = _freeze()
    plan = dict(freeze['segments']['boundary_default']['run_plan'])
    with pytest.raises(BoundaryFreezeError, match='SEGMENT_ID'):
        validate_run_plan(freeze, 'boundary_unknown', plan)
    broken = dict(freeze)
    broken['schema_version'] = 'boom_birds.latency_freeze.v2'
    with pytest.raises(BoundaryFreezeError, match='SCHEMA'):
        validate_run_plan(broken, 'boundary_default', plan)
    incomplete = dict(plan)
    incomplete.pop('ttl_ms')
    with pytest.raises(BoundaryFreezeError, match='MISSING'):
        validate_run_plan(freeze, 'boundary_default', incomplete)
    no_plan = copy.deepcopy(freeze)
    del no_plan['segments']['boundary_default']['run_plan']
    with pytest.raises(BoundaryFreezeError, match='RUN_PLAN_MISSING'):
        validate_run_plan(no_plan, 'boundary_default', plan)


# ---------------------------------------------------------------------------
# worktree_state / check_freeze_lineage（独立临时 git 仓库）
# ---------------------------------------------------------------------------

def _git(cwd, *args):
    completed = subprocess.run(['git', *args], cwd=str(cwd),
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path):
    root = tmp_path / 'repo'
    for sub in TRACKED_PATHS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / 'src' / 'mod.py').write_text('VALUE = 1\n', encoding='utf-8')
    (root / 'configs' / 'freeze.json').write_text('{}\n', encoding='utf-8')
    _git(root, 'init', '-q')
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.email=test@example.com',
         '-c', 'user.name=Test', 'commit', '-q', '-m', 'init')
    return root


def _lineage_freeze(root, **overrides):
    freeze = {
        'schema_version': CLEARANCE_BOUNDARY_FREEZE_SCHEMA,
        'status': FREEZE_STATUS,
        'frozen_at': _now_iso(),
        'code_commit': git_head(root),
        'worktree_state': worktree_state(root),
    }
    freeze.update(overrides)
    return freeze


def test_worktree_state_reports_clean_repo(git_repo):
    state = worktree_state(git_repo)
    assert state['clean'] is True
    assert state['tracked_paths'] == list(TRACKED_PATHS)
    assert len(state['status_text_sha256']) == 64


def test_worktree_state_changes_with_tracked_modification(git_repo):
    clean = worktree_state(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    dirty = worktree_state(git_repo)
    assert dirty['clean'] is False
    assert dirty['status_text_sha256'] != clean['status_text_sha256']


def test_worktree_state_extra_untracked_paths_is_deterministic(git_repo):
    base = worktree_state(git_repo)
    extra = worktree_state(git_repo, extra_untracked_paths=[
        'configs/clearance_boundary_freeze_v1.json'])
    assert extra['status_text_sha256'] != base['status_text_sha256']
    again = worktree_state(git_repo, extra_untracked_paths=[
        'configs/clearance_boundary_freeze_v1.json'])
    assert again['status_text_sha256'] == extra['status_text_sha256']


def test_worktree_state_ignores_paths_outside_tracked_roots(git_repo):
    base = worktree_state(git_repo)
    ignored = worktree_state(git_repo,
                             extra_untracked_paths=['outputs/freeze.json',
                                                    'tmp/freeze.json'])
    assert ignored['status_text_sha256'] == base['status_text_sha256']


def test_worktree_state_matches_latency_plan_normalization(git_repo):
    from boom_birds.evaluation.latency_plan import (
        worktree_state as latency_worktree_state)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\r\n', encoding='utf-8')
    (git_repo / 'configs' / 'other.json').write_text('{}\n', encoding='utf-8')
    ours = worktree_state(git_repo)
    reference = latency_worktree_state(git_repo)
    assert ours['status_text_sha256'] == reference['status_text_sha256']
    assert ours['clean'] == reference['clean']


def test_check_freeze_lineage_accepts_current_state(git_repo):
    assert check_freeze_lineage(_lineage_freeze(git_repo), _now_iso(),
                                git_repo) is None


def test_check_freeze_lineage_rejects_future_and_backdated(git_repo):
    freeze = _lineage_freeze(git_repo, frozen_at=_now_iso(300))
    with pytest.raises(BoundaryFreezeError, match='FUTURE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)
    with pytest.raises(BoundaryFreezeError, match='FUTURE'):
        check_freeze_lineage(_lineage_freeze(git_repo), _now_iso(-3600), git_repo)


def test_check_freeze_lineage_rejects_commit_mismatch(git_repo):
    freeze = _lineage_freeze(git_repo, code_commit='0' * 40)
    with pytest.raises(BoundaryFreezeError, match='COMMIT'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_worktree_change(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    with pytest.raises(BoundaryFreezeError, match='WORKTREE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_new_untracked_file(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'configs' / 'new.json').write_text('{}\n', encoding='utf-8')
    with pytest.raises(BoundaryFreezeError, match='WORKTREE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_new_commit(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    _git(git_repo, 'add', '-A')
    _git(git_repo, '-c', 'user.email=test@example.com',
         '-c', 'user.name=Test', 'commit', '-q', '-m', 'second')
    with pytest.raises(BoundaryFreezeError, match='COMMIT'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_bad_status_schema_and_naive_now(git_repo):
    with pytest.raises(BoundaryFreezeError, match='STATUS'):
        check_freeze_lineage(
            _lineage_freeze(git_repo, status='FROZEN_AFTER_RUNS'),
            _now_iso(), git_repo)
    broken = _lineage_freeze(git_repo)
    broken['schema_version'] = 'boom_birds.latency_freeze.v2'
    with pytest.raises(BoundaryFreezeError, match='SCHEMA'):
        check_freeze_lineage(broken, _now_iso(), git_repo)
    with pytest.raises(BoundaryFreezeError, match='TIMEZONE'):
        check_freeze_lineage(_lineage_freeze(git_repo),
                             '2026-11-02T12:00:00', git_repo)


# ---------------------------------------------------------------------------
# make_boundary_freeze 脚本：--dry-run、不覆盖、expected case 缺失拒绝
# ---------------------------------------------------------------------------

SCRIPT = ROOT / 'scripts' / 'make_boundary_freeze.py'


@pytest.fixture()
def freeze_script(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'make_boundary_freeze_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_contract = SimpleNamespace(
        asset_id='rmuc2027-isaacsim-20261028',
        terrain_sha256=TERRAIN_SHA,
        preview_sha256=PREVIEW_SHA,
        bounds_min_m=(-14.0, -8.0, -0.3),
        bounds_max_m=(14.0, 8.0, 3.5),
    )
    # 避免在单元测试里哈希 90 MB 地形；cases/map config/brake model 用真实文件。
    monkeypatch.setattr(module, 'load_map_contract',
                        lambda *args, **kwargs: fake_contract)
    return module


@pytest.fixture()
def script_inputs(tmp_path):
    """tmp expected：boundary cases 指向 tmp 夹具（brake model 用真实文件）。"""
    expected = json.loads((ROOT / EXPECTED_FILE).read_text(encoding='utf-8'))
    cases = tmp_path / 'clearance_boundary_cases_v1.json'
    cases.write_text(json.dumps({
        'schema_version': 'boom_birds.map_cases.v2',
        'asset_id': 'rmuc2027-isaacsim-20261028',
        'cases': [{'case_id': case_id}
                  for case_id in sorted(expected['cases'])],
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    for segment_id in BOUNDARY_SEGMENT_IDS:
        expected['segments'][segment_id]['defaults']['cases_file'] = \
            cases.as_posix()
    expected_path = tmp_path / 'clearance_boundary_expected_v1.json'
    expected_path.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    return {
        'expected': expected_path,
        'cases': cases,
        'output': tmp_path / 'clearance_boundary_freeze_v1.json',
    }


def _script_args(inputs):
    return ['--expected', str(inputs['expected']),
            '--brake-model', str(ROOT / BRAKE_FILE),
            '--output', str(inputs['output'])]


def test_script_dry_run_prints_json_and_writes_nothing(freeze_script,
                                                       script_inputs, capsys):
    args = ['--dry-run'] + _script_args(script_inputs)
    assert freeze_script.main(args) == 0
    assert not script_inputs['output'].exists()
    freeze = json.loads(capsys.readouterr().out)
    assert freeze['schema_version'] == CLEARANCE_BOUNDARY_FREEZE_SCHEMA
    assert freeze['status'] == FREEZE_STATUS
    assert list(freeze['segments']) == list(SEGMENT_IDS)
    assert freeze['budget'] == {
        'boundary_episodes': 24,
        'special_episodes': 2,
        'regression_episodes': 3,
        'total_episodes': 29,
        'min_boundary_episodes_required': 24,
    }
    e1 = freeze['segments']['boundary_delay_e1']['run_plan']
    e2 = freeze['segments']['boundary_delay_e2']['run_plan']
    assert (e1['obs_delay_s'], e1['action_delay_s']) == (0.2, 0.1)
    assert (e2['obs_delay_s'], e2['action_delay_s']) == (0.18, 0.12)
    assert freeze['segments']['boundary_fast']['run_plan']['vehicle_config'] == \
        FAST_VEHICLE
    clock = freeze['segments']['latency_clock_mapping_recheck']['run_plan']
    assert clock['obs_mapping_fail_step'] == 280
    ttl = freeze['segments']['latency_ttl_over_recheck']['run_plan']
    assert ttl['transport_stall_step'] == 300
    assert ttl['transport_stall_delay_s'] == 0.15
    for segment_id in REGRESSION_SEGMENT_IDS:
        segment = freeze['segments'][segment_id]
        assert segment['expected'] is None
        assert segment['run_plan']['obs_delay_s'] == 0.0
    assert freeze['code_commit'] == git_head(ROOT)
    frozen_at = datetime.fromisoformat(freeze['frozen_at'])
    assert frozen_at.tzinfo is not None
    assert frozen_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_script_refuses_to_overwrite_existing_output(freeze_script,
                                                     script_inputs, capsys):
    script_inputs['output'].write_text('{"marker": "keep"}\n', encoding='utf-8')
    assert freeze_script.main(_script_args(script_inputs)) == 2
    assert script_inputs['output'].read_text(encoding='utf-8') == \
        '{"marker": "keep"}\n'
    assert 'refusing' in capsys.readouterr().err


def test_script_writes_freeze_then_refuses_second_run(freeze_script,
                                                      script_inputs, capsys):
    assert freeze_script.main(_script_args(script_inputs)) == 0
    out = script_inputs['output']
    assert out.is_file()
    first_bytes = out.read_bytes()
    freeze = json.loads(out.read_text(encoding='utf-8'))
    assert freeze['worktree_state']['tracked_paths'] == list(TRACKED_PATHS)
    assert len(freeze['worktree_state']['status_text_sha256']) == 64
    assert '预期非结论' in freeze['note']
    assert freeze['expected_file'].endswith('clearance_boundary_expected_v1.json')
    assert freeze_script.main(_script_args(script_inputs)) == 2
    assert out.read_bytes() == first_bytes


def test_script_rejects_expected_case_missing_from_cases_file(freeze_script,
                                                              script_inputs,
                                                              capsys):
    payload = json.loads(script_inputs['cases'].read_text(encoding='utf-8'))
    payload['cases'] = [entry for entry in payload['cases']
                        if entry['case_id'] != 'boundary_A_static_far_r0']
    script_inputs['cases'].write_text(
        json.dumps(payload, ensure_ascii=False) + '\n', encoding='utf-8')
    assert freeze_script.main(_script_args(script_inputs)) == 1
    assert '不在' in capsys.readouterr().err
    assert not script_inputs['output'].exists()


def test_script_rejects_missing_brake_model(freeze_script, script_inputs,
                                            capsys):
    args = _script_args(script_inputs)
    args[args.index('--brake-model') + 1] = str(
        script_inputs['output'].parent / 'missing_brake_model.json')
    assert freeze_script.main(args) == 1
    assert 'brake model' in capsys.readouterr().err
