"""回归测试：延迟包络预运行冻结契约（latency_plan / make_latency_freeze）。

覆盖计划 §4.1–§4.3 与 Lead 2026-11-02 精确参数：
- build_run_plan 归一化（浮点 round(...,6)、cases_file posix、case_ids 排序、methods 顺序保持）；
- 字段不一致拒绝、主 A/B 仅 stop 不同的配对校验；
- frozen_at 未来/倒填、code_commit、worktree 变动拒绝；
- 冻结生成脚本不覆盖已存在文件（--dry-run 不落盘）。
"""
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

from boom_birds.evaluation.latency_plan import (  # noqa: E402
    FREEZE_SCOPE,
    FREEZE_STATUS,
    LATENCY_EVAL_VERSION,
    LATENCY_FREEZE_SCHEMA,
    MAIN_ROLE,
    RUN_PLAN_FIELDS,
    SPECIAL_ROLE,
    TRACKED_PATHS,
    LatencyFreezeError,
    build_freeze,
    build_run_plan,
    check_freeze_lineage,
    git_head,
    validate_run_plan,
    worktree_state,
)

MAIN_CASES_FILE = 'configs/scenarios/map_dynamic_cases_v1.json'
SPECIAL_CASES_FILE = 'configs/scenarios/latency_special_cases_v1.json'
MAIN_CASES_SHA = 'a' * 64
SPECIAL_CASES_SHA = 'b' * 64
TERRAIN_SHA = '1' * 64
PREVIEW_SHA = '2' * 64
MAP_CONFIG_SHA = '3' * 64
WORKTREE_SHA = 'c' * 64
MAIN_PLAN_CASE_IDS = ('dynamic_A_south_0', 'dynamic_B_north_0')
FULL_MAIN_CASE_IDS = (
    'dynamic_A_north_0', 'dynamic_A_south_0', 'dynamic_A_south_1',
    'dynamic_B_north_0', 'dynamic_B_south_0', 'dynamic_B_south_1',
    'dynamic_C_north_0', 'dynamic_C_south_0',
    'dynamic_D_north_0', 'dynamic_D_south_0',
    'dynamic_E_north_0', 'dynamic_E_south_0',
)


def _now_iso(offset_s=0.0):
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_s)).isoformat(timespec='microseconds')


def _run_plan(**overrides):
    kwargs = dict(
        role=MAIN_ROLE,
        segment_id='',
        config_id='A',
        cases_file=MAIN_CASES_FILE,
        cases_sha256=MAIN_CASES_SHA,
        case_ids=['dynamic_B_north_0', 'dynamic_A_south_0'],
        methods=['supervisor'],
        execution_path='v2',
        obs_delay_s=0.15,
        action_delay_s=0.10,
        ttl_ms=150,
        max_age_ms=150,
        allowed_observation_age_ms=300,
        stop_distance_m=1.1,
        post_abort_observe_s=0.0,
        clock_offset_ms=20.0,
        clock_drift_ppm=200.0,
        clock_uncertainty_ms=5.0,
        sync_fail_step=-1,
        obs_mapping_fail_step=-1,
        transport_stall_step=-1,
        transport_stall_delay_s=0.15,
    )
    kwargs.update(overrides)
    return build_run_plan(**kwargs)


def _special_run_plan(segment_id='ttl_near', **overrides):
    kwargs = dict(
        role=SPECIAL_ROLE,
        segment_id=segment_id,
        config_id='',
        cases_file=SPECIAL_CASES_FILE,
        cases_sha256=SPECIAL_CASES_SHA,
        case_ids=['special_stop_north'],
        methods=['supervisor'],
        execution_path='v2',
        obs_delay_s=0.15,
        action_delay_s=0.10,
        ttl_ms=120,
        max_age_ms=150,
        allowed_observation_age_ms=300,
        stop_distance_m=1.1,
        post_abort_observe_s=0.0,
        clock_offset_ms=20.0,
        clock_drift_ppm=200.0,
        clock_uncertainty_ms=5.0,
        sync_fail_step=-1,
        obs_mapping_fail_step=-1,
        transport_stall_step=-1,
        transport_stall_delay_s=0.15,
    )
    kwargs.update(overrides)
    return build_run_plan(**kwargs)


def _segment(segment_id='ttl_near', **plan_overrides):
    plan = _special_run_plan(segment_id, **plan_overrides)
    return {
        'segment_id': segment_id,
        'purpose': 'test segment',
        'case_ids': list(plan['case_ids']),
        'cases_file': plan['cases_file'],
        'cases_sha256': plan['cases_sha256'],
        'run_plan': plan,
        'expected': {'outcome': 'SUCCESS'},
        'expected_note': '预期非结论',
    }


def _supervisor():
    return {
        'stop_distance_m': 1.1,
        'release_distance_m': 1.6,
        'prediction_horizon_s': 1.0,
        'prediction_step_s': 0.1,
        'observation_max_age_s': 0.3,
        'max_stale_s': 2.0,
        'max_wait_s': 8.0,
        'min_hold_s': 0.5,
        'release_hold_s': 0.5,
        'resume_hold_s': 0.3,
        'stop_speed_mps': 0.12,
    }


def _evaluation(case_ids=MAIN_PLAN_CASE_IDS, segments=('ttl_near',)):
    return {
        'version': LATENCY_EVAL_VERSION,
        'status': 'EXPECTED_NOT_CONCLUSION',
        'note': '预期非结论，实际以独立核验为准',
        'supervisor': _supervisor(),
        'supervisor_overrides': {'A': {'stop_distance_m': 1.1},
                                 'B': {'stop_distance_m': 1.38}},
        'thresholds': {'success_distance_m': 0.2, 'stop_speed_max_mps': 0.08,
                       'contact_force_threshold_n': 0.02},
        'expected': {
            'main': {config: {case_id: {'expected_outcome': 'SUCCESS'}
                              for case_id in case_ids}
                     for config in ('A', 'B')},
            'special': {segment: {'outcome': 'SUCCESS'} for segment in segments},
        },
    }


def _freeze_kwargs(**overrides):
    kwargs = dict(
        frozen_at=_now_iso(),
        code_commit='f' * 40,
        worktree_state={'tracked_paths': list(TRACKED_PATHS),
                        'status_text_sha256': WORKTREE_SHA, 'clean': True},
        map_state={'map_asset_id': 'rmuc2027-isaacsim-20261028',
                   'terrain_sha256': TERRAIN_SHA,
                   'preview_sha256': PREVIEW_SHA,
                   'map_config_sha256': MAP_CONFIG_SHA,
                   'map_config_file': 'configs/maps/rmuc2027.yaml'},
        cases=[{'cases_file': MAIN_CASES_FILE, 'cases_sha256': MAIN_CASES_SHA},
               {'cases_file': SPECIAL_CASES_FILE,
                'cases_sha256': SPECIAL_CASES_SHA}],
        primary_cases_file=MAIN_CASES_FILE,
        artifact='main_pair',
        main_run_plans={'A': _run_plan(config_id='A', stop_distance_m=1.1),
                        'B': _run_plan(config_id='B', stop_distance_m=1.38)},
        special_segments={'ttl_near': _segment('ttl_near')},
        evaluation=_evaluation(),
        clock_plan={'camera_clock_id': 'camera_sim', 'offset_ms': 20.0,
                    'drift_ppm': 200.0, 'uncertainty_ms': 5.0,
                    'sync_generation_plan': {'initial': 0}},
        latency_plan_defaults={'obs_delay_s': 0.15, 'action_delay_s': 0.10,
                               'ttl_ms': 150, 'max_age_ms': 150,
                               'allowed_observation_age_ms': 300,
                               'post_abort_observe_s': 0.0},
        body_envelope={'source': 'measured_usd_aabb_at_runtime',
                       'half_extents_m': None, 'measured_prim': None,
                       'tolerance_m': 0.01},
        note='test freeze',
    )
    kwargs.update(overrides)
    return kwargs


def _freeze(**overrides):
    return build_freeze(**_freeze_kwargs(**overrides))


# ---------------------------------------------------------------------------
# build_run_plan：归一化
# ---------------------------------------------------------------------------

def test_build_run_plan_normalizes_float_path_and_case_order():
    plan = _run_plan(obs_delay_s=0.123456789, action_delay_s=0.1000004,
                     cases_file='configs\\scenarios\\map_dynamic_cases_v1.json',
                     case_ids=['dynamic_B_north_0', 'dynamic_A_south_0'])
    assert plan['obs_delay_s'] == 0.123457
    assert plan['action_delay_s'] == 0.1
    assert plan['cases_file'] == MAIN_CASES_FILE
    assert plan['case_ids'] == ['dynamic_A_south_0', 'dynamic_B_north_0']
    assert tuple(plan) == RUN_PLAN_FIELDS


def test_build_run_plan_keeps_methods_order():
    plan = _run_plan(methods=['supervisor', 'follow_only'])
    assert plan['methods'] == ['supervisor', 'follow_only']


def test_build_run_plan_rejects_unknown_keyword():
    with pytest.raises(LatencyFreezeError, match='UNKNOWN'):
        _run_plan(surprise=1)


def test_build_run_plan_rejects_missing_field():
    kwargs = dict(role=MAIN_ROLE, segment_id='', config_id='A')
    with pytest.raises(LatencyFreezeError, match='MISSING'):
        build_run_plan(**kwargs)


def test_build_run_plan_rejects_invalid_role():
    with pytest.raises(LatencyFreezeError, match='ROLE'):
        _run_plan(role='pair')


def test_build_run_plan_rejects_main_with_segment_id():
    with pytest.raises(LatencyFreezeError, match='SEGMENT'):
        _run_plan(segment_id='ttl_near')


def test_build_run_plan_rejects_special_without_segment_id():
    with pytest.raises(LatencyFreezeError, match='SEGMENT'):
        _special_run_plan(segment_id='')


def test_build_run_plan_rejects_duplicate_case_ids():
    with pytest.raises(LatencyFreezeError, match='CASE_IDS'):
        _run_plan(case_ids=['dynamic_A_south_0', 'dynamic_A_south_0'])


def test_build_run_plan_rejects_bad_execution_path():
    with pytest.raises(LatencyFreezeError, match='EXECUTION_PATH'):
        _run_plan(execution_path='v3')


def test_build_run_plan_rejects_negative_delay():
    with pytest.raises(LatencyFreezeError, match='NEGATIVE'):
        _run_plan(obs_delay_s=-0.1)


def test_build_run_plan_rejects_bad_case_sha():
    with pytest.raises(LatencyFreezeError, match='HASH'):
        _run_plan(cases_sha256='not-a-hash')


def test_build_run_plan_rejects_bad_step_index():
    with pytest.raises(LatencyFreezeError, match='STEP'):
        _run_plan(sync_fail_step=-2)


# ---------------------------------------------------------------------------
# build_freeze：结构与配对校验
# ---------------------------------------------------------------------------

def test_build_freeze_contains_contract_fields():
    freeze = _freeze()
    assert freeze['schema_version'] == LATENCY_FREEZE_SCHEMA
    assert freeze['status'] == FREEZE_STATUS
    assert freeze['scope'] == FREEZE_SCOPE
    assert freeze['artifact'] == 'main_pair'
    assert freeze['evaluation_version'] == LATENCY_EVAL_VERSION
    assert freeze['cases_file'] == MAIN_CASES_FILE
    assert freeze['cases_sha256'] == MAIN_CASES_SHA
    assert freeze['map_asset_id'] == 'rmuc2027-isaacsim-20261028'
    assert freeze['terrain_sha256'] == TERRAIN_SHA
    assert freeze['preview_sha256'] == PREVIEW_SHA
    assert freeze['map_config_sha256'] == MAP_CONFIG_SHA
    assert freeze['evaluation']['status'] == 'EXPECTED_NOT_CONCLUSION'
    assert 'expected' in freeze['evaluation']
    assert freeze['latency_plan_defaults']['ttl_ms'] == 150
    assert freeze['clock_plan']['drift_ppm'] == 200.0
    assert freeze['body_envelope']['source'] == 'measured_usd_aabb_at_runtime'
    assert freeze['note'] == 'test freeze'
    # 必须可 JSON 序列化（Path/tuple 等不得残留）
    json.dumps(freeze, ensure_ascii=False)
    assert isinstance(freeze['frozen_at'], str)
    assert datetime.fromisoformat(freeze['frozen_at']).tzinfo is not None


def test_build_freeze_special_artifact_requires_segments():
    with pytest.raises(LatencyFreezeError, match='SPECIAL_SEGMENTS'):
        _freeze(artifact='special', special_segments=None)


def test_build_freeze_evaluation_expected_per_case_and_segment():
    freeze = _freeze()
    evaluation = freeze['evaluation']
    assert evaluation['version'] == LATENCY_EVAL_VERSION
    assert isinstance(evaluation['thresholds'], dict) and evaluation['thresholds']
    assert set(evaluation['expected']['main']) == {'A', 'B'}
    assert set(evaluation['expected']['main']['A']) == set(MAIN_PLAN_CASE_IDS)
    assert set(evaluation['expected']['main']['B']) == set(MAIN_PLAN_CASE_IDS)
    assert set(evaluation['expected']['special']) == {'ttl_near'}
    assert isinstance(freeze['main_run_plans'], dict)
    assert isinstance(freeze['special_segments'], dict)


def test_expected_config_has_cases_and_segments_structures():
    payload = json.loads(
        (ROOT / 'configs/scenarios/latency_expected_v1.json')
        .read_text(encoding='utf-8'))
    assert payload['evaluation_version'] == LATENCY_EVAL_VERSION
    assert payload['status'] == 'EXPECTED_NOT_CONCLUSION'
    assert '预期非结论' in payload['note']
    assert set(payload['cases']) == set(FULL_MAIN_CASE_IDS)
    outcomes = {'SUCCESS', 'ABORT', 'TIMEOUT', 'COLLISION', 'OUT_OF_BOUNDS',
                'INVALID'}
    for entry in payload['cases'].values():
        assert entry['expected_outcome'] in outcomes
    assert set(payload['segments']) == {'ttl_near', 'ttl_over', 'clock_sync',
                                        'clock_mapping'}
    for segment in payload['segments'].values():
        assert segment['expected_outcome'] in outcomes
        assert isinstance(segment['cases'], dict) and segment['cases']


def test_build_freeze_rejects_unknown_artifact():
    with pytest.raises(LatencyFreezeError, match='ARTIFACT'):
        _freeze(artifact='pair')


def test_build_freeze_main_pair_may_differ_only_by_stop_and_config():
    freeze = _freeze()
    assert freeze['main_run_plans']['A']['stop_distance_m'] == 1.1
    assert freeze['main_run_plans']['B']['stop_distance_m'] == 1.38
    assert (freeze['main_run_plans']['A']['config_id'], 
            freeze['main_run_plans']['B']['config_id']) == ('A', 'B')


def test_build_freeze_rejects_main_pair_field_difference():
    b_plan = _run_plan(config_id='B', stop_distance_m=1.38, obs_delay_s=0.2)
    with pytest.raises(LatencyFreezeError, match='MAIN_PAIR_MISMATCH'):
        _freeze(main_run_plans={'A': _run_plan(config_id='A'),
                                'B': b_plan})


def test_build_freeze_rejects_main_pair_case_set_difference():
    b_plan = _run_plan(config_id='B', stop_distance_m=1.38,
                       case_ids=['dynamic_A_south_0'])
    with pytest.raises(LatencyFreezeError, match='MAIN_PAIR_MISMATCH'):
        _freeze(main_run_plans={'A': _run_plan(config_id='A'), 'B': b_plan})


def test_build_freeze_rejects_missing_main_config():
    with pytest.raises(LatencyFreezeError, match='MAIN_RUN_PLANS'):
        _freeze(main_run_plans={'A': _run_plan(config_id='A')})


def test_build_freeze_rejects_missing_expected_main_case():
    evaluation = _evaluation()
    del evaluation['expected']['main']['B']['dynamic_A_south_0']
    with pytest.raises(LatencyFreezeError, match='EXPECTED_MISSING'):
        _freeze(evaluation=evaluation)


def test_build_freeze_rejects_missing_expected_segment():
    evaluation = _evaluation()
    evaluation['expected']['special'].clear()
    with pytest.raises(LatencyFreezeError, match='EXPECTED_MISSING'):
        _freeze(evaluation=evaluation)


def test_build_freeze_rejects_naive_frozen_at():
    with pytest.raises(LatencyFreezeError, match='TIMEZONE'):
        _freeze(frozen_at='2026-11-02T12:00:00')


def test_build_freeze_rejects_bad_hash_shape():
    map_state = dict(_freeze_kwargs()['map_state'])
    map_state['terrain_sha256'] = 'xyz'
    with pytest.raises(LatencyFreezeError, match='HASH'):
        _freeze(map_state=map_state)


def test_build_freeze_rejects_undeclared_case_file():
    plan = _run_plan(cases_file='configs/scenarios/other.json')
    with pytest.raises(LatencyFreezeError, match='CASE_FILE'):
        _freeze(main_run_plans={'A': plan,
                                'B': _run_plan(config_id='B',
                                               stop_distance_m=1.38,
                                               cases_file='configs/scenarios/other.json')})
    with pytest.raises(LatencyFreezeError, match='CASE_FILE'):
        _freeze(primary_cases_file='configs/scenarios/other.json')


def test_build_freeze_rejects_special_plan_role_mismatch():
    segment = _segment('ttl_near')
    segment['run_plan'] = _run_plan()  # role=main
    with pytest.raises(LatencyFreezeError, match='SPECIAL'):
        _freeze(special_segments={'ttl_near': segment})


def test_build_freeze_rejects_special_segment_id_mismatch():
    segment = _segment('ttl_near')
    with pytest.raises(LatencyFreezeError, match='SEGMENT'):
        _freeze(special_segments={'ttl_over': segment})


def test_build_freeze_rejects_latency_defaults_mismatch():
    defaults = dict(_freeze_kwargs()['latency_plan_defaults'])
    defaults['obs_delay_s'] = 0.2
    with pytest.raises(LatencyFreezeError, match='LATENCY_PLAN'):
        _freeze(latency_plan_defaults=defaults)


def test_build_freeze_rejects_clock_plan_mismatch():
    clock_plan = dict(_freeze_kwargs()['clock_plan'])
    clock_plan['drift_ppm'] = 100.0
    with pytest.raises(LatencyFreezeError, match='CLOCK_PLAN'):
        _freeze(clock_plan=clock_plan)


# ---------------------------------------------------------------------------
# validate_run_plan
# ---------------------------------------------------------------------------

def test_validate_run_plan_accepts_frozen_main_plan():
    freeze = _freeze()
    assert validate_run_plan(freeze, MAIN_ROLE, '', 'A',
                             _run_plan(config_id='A')) is None


def test_validate_run_plan_accepts_special_plan():
    freeze = _freeze()
    assert validate_run_plan(freeze, SPECIAL_ROLE, 'ttl_near', '',
                             _special_run_plan('ttl_near')) is None


def test_validate_run_plan_rejects_field_mismatch():
    freeze = _freeze()
    with pytest.raises(LatencyFreezeError, match='RUN_PLAN_MISMATCH'):
        try:
            validate_run_plan(freeze, MAIN_ROLE, '', 'A',
                              _run_plan(config_id='A', stop_distance_m=1.38))
        except LatencyFreezeError as error:
            assert 'stop_distance_m' in str(error)
            raise


def test_validate_run_plan_accepts_rounded_float_noise():
    freeze = _freeze()
    assert validate_run_plan(freeze, MAIN_ROLE, '', 'A',
                             _run_plan(config_id='A', obs_delay_s=0.1500004)) is None


def test_validate_run_plan_accepts_case_id_reordering():
    freeze = _freeze()
    plan = _run_plan(config_id='A',
                     case_ids=['dynamic_B_north_0', 'dynamic_A_south_0'])
    assert validate_run_plan(freeze, MAIN_ROLE, '', 'A', plan) is None


def test_validate_run_plan_rejects_unknown_config():
    with pytest.raises(LatencyFreezeError, match='PLAN_NOT_FROZEN'):
        validate_run_plan(_freeze(), MAIN_ROLE, '', 'C', _run_plan(config_id='A'))


def test_validate_run_plan_rejects_unknown_segment():
    with pytest.raises(LatencyFreezeError, match='PLAN_NOT_FROZEN'):
        validate_run_plan(_freeze(), SPECIAL_ROLE, 'ttl_over', '',
                          _special_run_plan('ttl_over'))


def test_validate_run_plan_rejects_invalid_role():
    with pytest.raises(LatencyFreezeError, match='ROLE'):
        validate_run_plan(_freeze(), 'pair', '', 'A', _run_plan(config_id='A'))


def test_validate_run_plan_rejects_bad_schema():
    freeze = dict(_freeze())
    freeze['schema_version'] = 'boom_birds.latency_freeze.v1'
    with pytest.raises(LatencyFreezeError, match='SCHEMA'):
        validate_run_plan(freeze, MAIN_ROLE, '', 'A', _run_plan(config_id='A'))


def test_validate_run_plan_rejects_incomplete_actual_plan():
    plan = _run_plan(config_id='A')
    plan.pop('ttl_ms')
    with pytest.raises(LatencyFreezeError, match='MISSING'):
        validate_run_plan(_freeze(), MAIN_ROLE, '', 'A', plan)


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
        'schema_version': LATENCY_FREEZE_SCHEMA,
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
        'configs/latency_pair_freeze_v2.json'])
    assert extra['status_text_sha256'] != base['status_text_sha256']
    again = worktree_state(git_repo, extra_untracked_paths=[
        'configs/latency_pair_freeze_v2.json'])
    assert again['status_text_sha256'] == extra['status_text_sha256']


def test_worktree_state_ignores_untracked_paths_outside_tracked_roots(git_repo):
    base = worktree_state(git_repo)
    ignored = worktree_state(git_repo,
                             extra_untracked_paths=['outputs/freeze.json',
                                                    'tmp/freeze.json'])
    assert ignored['status_text_sha256'] == base['status_text_sha256']


def test_check_freeze_lineage_accepts_current_state(git_repo):
    freeze = _lineage_freeze(git_repo)
    assert check_freeze_lineage(freeze, _now_iso(), git_repo) is None


def test_check_freeze_lineage_rejects_future_frozen_at(git_repo):
    freeze = _lineage_freeze(git_repo, frozen_at=_now_iso(300))
    with pytest.raises(LatencyFreezeError, match='FUTURE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_backdated_generation(git_repo):
    freeze = _lineage_freeze(git_repo)
    with pytest.raises(LatencyFreezeError, match='FUTURE'):
        check_freeze_lineage(freeze, _now_iso(-3600), git_repo)


def test_check_freeze_lineage_rejects_commit_mismatch(git_repo):
    freeze = _lineage_freeze(git_repo, code_commit='0' * 40)
    with pytest.raises(LatencyFreezeError, match='COMMIT'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_worktree_change(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    with pytest.raises(LatencyFreezeError, match='WORKTREE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_new_untracked_file(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'new_module.py').write_text('VALUE = 3\n',
                                                    encoding='utf-8')
    with pytest.raises(LatencyFreezeError, match='WORKTREE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_new_commit(git_repo):
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    _git(git_repo, 'add', '-A')
    _git(git_repo, '-c', 'user.email=test@example.com',
         '-c', 'user.name=Test', 'commit', '-q', '-m', 'second')
    with pytest.raises(LatencyFreezeError, match='COMMIT'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_naive_now(git_repo):
    freeze = _lineage_freeze(git_repo)
    with pytest.raises(LatencyFreezeError, match='TIMEZONE'):
        check_freeze_lineage(freeze, '2026-11-02T12:00:00', git_repo)


def test_check_freeze_lineage_rejects_bad_status(git_repo):
    freeze = _lineage_freeze(git_repo, status='FROZEN_AFTER_RUNS_RECORDED')
    with pytest.raises(LatencyFreezeError, match='STATUS'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_bad_schema(git_repo):
    freeze = _lineage_freeze(git_repo)
    freeze['schema_version'] = 'boom_birds.latency_pair_freeze.v1'
    with pytest.raises(LatencyFreezeError, match='SCHEMA'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


# ---------------------------------------------------------------------------
# make_latency_freeze 脚本：--dry-run 与禁止覆盖
# ---------------------------------------------------------------------------

SCRIPT = ROOT / 'scripts' / 'make_latency_freeze.py'


@pytest.fixture()
def freeze_script(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'make_latency_freeze_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_contract = SimpleNamespace(
        asset_id='rmuc2027-isaacsim-20261028',
        terrain_sha256=TERRAIN_SHA,
        preview_sha256=PREVIEW_SHA,
        bounds_min_m=(-14.0005, -8.0016, -0.3010),
        bounds_max_m=(14.0005, 8.0016, 3.4977),
    )
    # 避免在单元测试里哈希 90 MB 地形；cases/map config 仍用仓库真实文件。
    monkeypatch.setattr(module, 'load_map_contract',
                        lambda *args, **kwargs: fake_contract)
    return module


def test_script_refuses_to_overwrite_existing_pair_freeze(freeze_script,
                                                          tmp_path, capsys):
    out = tmp_path / 'out'
    out.mkdir()
    pair = out / 'latency_pair_freeze_v2.json'
    marker = '{"marker": "keep"}\n'
    pair.write_text(marker, encoding='utf-8')
    special = out / 'latency_special_freeze_v2.json'
    assert freeze_script.main(['--output-root', str(out)]) == 2
    assert pair.read_text(encoding='utf-8') == marker
    assert not special.exists()
    assert 'refusing' in capsys.readouterr().err


def test_script_refuses_to_overwrite_existing_special_freeze(freeze_script,
                                                             tmp_path, capsys):
    out = tmp_path / 'out'
    out.mkdir()
    special = out / 'latency_special_freeze_v2.json'
    marker = '{"marker": "keep-special"}\n'
    special.write_text(marker, encoding='utf-8')
    assert freeze_script.main(['--output-root', str(out)]) == 2
    assert special.read_text(encoding='utf-8') == marker
    assert not (out / 'latency_pair_freeze_v2.json').exists()
    assert 'refusing' in capsys.readouterr().err


def test_script_dry_run_prints_json_and_writes_nothing(freeze_script,
                                                       tmp_path, capsys):
    out = tmp_path / 'out'
    assert freeze_script.main(['--dry-run', '--output-root', str(out)]) == 0
    assert not out.exists()
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {'pair', 'special'}
    pair = payload['pair']
    special = payload['special']
    assert pair['schema_version'] == LATENCY_FREEZE_SCHEMA
    assert pair['status'] == FREEZE_STATUS
    assert pair['artifact'] == 'main_pair'
    assert pair['evaluation_version'] == LATENCY_EVAL_VERSION
    assert list(pair['main_run_plans']) == ['A', 'B']
    assert pair['main_run_plans']['A']['stop_distance_m'] == 1.1
    assert pair['main_run_plans']['B']['stop_distance_m'] == 1.38
    assert pair['main_run_plans']['A']['role'] == 'main'
    assert pair['main_run_plans']['A']['segment_id'] == ''
    assert pair['main_run_plans']['A']['ttl_ms'] == 150
    assert pair['main_run_plans']['A']['clock_offset_ms'] == 20.0
    assert pair['main_run_plans']['A']['clock_drift_ppm'] == 200.0
    assert pair['main_run_plans']['A']['clock_uncertainty_ms'] == 5.0
    assert pair['main_run_plans']['A']['transport_stall_delay_s'] == 0.15
    assert pair['main_run_plans']['A']['case_ids'] == sorted(
        pair['main_run_plans']['A']['case_ids'])
    assert len(pair['main_run_plans']['A']['case_ids']) == 12
    assert pair['special_segments']['ttl_near']['run_plan']['ttl_ms'] == 120
    assert pair['special_segments']['ttl_over']['run_plan'][
        'transport_stall_step'] == 300
    assert pair['special_segments']['ttl_over']['run_plan'][
        'post_abort_observe_s'] == 3.0
    assert pair['special_segments']['clock_sync']['run_plan'][
        'sync_fail_step'] == 300
    assert pair['special_segments']['clock_mapping']['run_plan'][
        'obs_mapping_fail_step'] == 280
    assert set(special['special_segments']) == {'ttl_near', 'ttl_over',
                                                'clock_sync', 'clock_mapping'}
    assert special['artifact'] == 'special'
    assert special['cases_file'] == SPECIAL_CASES_FILE
    assert special['cases_sha256'] == pair['special_segments']['ttl_near'][
        'cases_sha256']
    # 预期非结论标注必须存在
    assert '预期非结论' in json.dumps(pair, ensure_ascii=False)


def test_script_writes_fresh_outputs_then_refuses_second_run(freeze_script,
                                                             tmp_path, capsys):
    out = tmp_path / 'freeze_check'
    assert freeze_script.main(['--output-root', str(out)]) == 0
    pair_path = out / 'latency_pair_freeze_v2.json'
    special_path = out / 'latency_special_freeze_v2.json'
    assert pair_path.is_file() and special_path.is_file()
    pair_bytes = pair_path.read_bytes()
    pair = json.loads(pair_path.read_text(encoding='utf-8'))
    special = json.loads(special_path.read_text(encoding='utf-8'))
    # 真实 HEAD / 真实 UTC 时间 / 工作树状态由脚本自算
    assert pair['code_commit'] == git_head(ROOT)
    # 生成与断言之间其他并行成员可能改动工作树，这里只校验形状；
    # 状态文本的确定性由临时 git 仓库用例覆盖（test_worktree_state_*）。
    assert pair['worktree_state']['tracked_paths'] == list(TRACKED_PATHS)
    assert len(pair['worktree_state']['status_text_sha256']) == 64
    assert isinstance(pair['worktree_state']['clean'], bool)
    frozen_at = datetime.fromisoformat(pair['frozen_at'])
    assert frozen_at.tzinfo is not None
    assert frozen_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert pair['main_run_plans']['A'] != pair['main_run_plans']['B']
    # 再次运行必须拒绝覆盖并保持原文件逐字节不变
    assert freeze_script.main(['--output-root', str(out)]) == 2
    assert pair_path.read_bytes() == pair_bytes
    assert special['schema_version'] == LATENCY_FREEZE_SCHEMA

