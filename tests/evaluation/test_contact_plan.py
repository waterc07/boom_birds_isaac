"""Regression tests: contact-evidence/envelope pre-run freeze contract.

Covers ``contact_plan`` (freeze/plan/lineage) and
``scripts/make_contact_verification_freeze.py``:

* cases normalization against the fixed six-segment table (roles, modes,
  repeats, 11 episodes), replay ``replay_params`` equal to the previous
  ``boundary_default`` parameters and replay references (path strings only);
* run plan normalization (float rounding, posix paths, sorted unique case ids,
  frozen contract versions, vehicle/map config hashes, JSON-comparable
  ``run_params``) and rejection of inconsistent plans;
* expected file coverage (every case id, physical outcome sets, verifier must
  condition kinds, replay verdicts) and per-segment merged expectations;
* freeze assembly (six segments, budget 11, support scope, embedded expected,
  replay references) and rejection of missing/extra/tampered inputs;
* ``validate_run_plan`` full normalized-JSON comparison;
* ``check_freeze_lineage`` (future frozen_at, backdated now, HEAD mismatch,
  worktree digest mismatch);
* ``worktree_state``/``git_head``/``sha256_file`` helpers (digest identical to
  the previous work packages' normalization);
* generator CLI: ``--dry-run`` writes nothing, existing output refuses with exit
  2, missing cases/expected files fail with a clear error.
"""
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

from boom_birds.evaluation.contact_plan import (  # noqa: E402
    CONTACT_CASES_SCHEMA,
    CONTACT_CONTRACT_VERSION,
    CONTACT_EXPECTED_SCHEMA,
    CONTACT_FREEZE_SCHEMA,
    ENVELOPE_CONTRACT_VERSION,
    FREEZE_STATUS,
    MIN_EPISODES_REQUIRED,
    MUST_CONDITION_KINDS,
    PHYSICAL_OUTCOMES,
    PREVIOUS_PHYSICAL_LABELS,
    REPLAY_PARAM_FIELDS,
    REPLAY_PARAMS_BOUNDARY_DEFAULT,
    REPLAY_SEGMENT_IDS,
    REPLAY_VERDICTS,
    RUN_PLAN_FIELDS,
    SEGMENT_IDS,
    SEGMENT_TABLE,
    TRACKED_PATHS,
    ContactPlanError,
    build_freeze,
    build_run_plan,
    check_freeze_lineage,
    git_head,
    load_cases_file,
    load_expected_file,
    normalize_cases_payload,
    normalize_expected_payload,
    sha256_file,
    validate_run_plan,
    worktree_state,
)

CASES_FILE = 'configs/scenarios/contact_verification_cases_v1.json'
EXPECTED_FILE = 'configs/scenarios/contact_verification_expected_v1.json'
VEHICLE_FILE = 'configs/vehicles/sim_reference.yaml'
MAP_FILE = 'configs/maps/rmuc2027.yaml'
SOURCE_CASES = 'configs/scenarios/clearance_boundary_cases_v1.json'
WORKTREE_SHA = 'c' * 64
CASES_SHA = 'a' * 64
EXPECTED_SHA = 'b' * 64
VEHICLE_SHA = 'd' * 64
MAP_SHA = 'e' * 64
TERRAIN_SHA = '1' * 64
PREVIEW_SHA = '2' * 64
MAP_CONFIG_SHA = '3' * 64

WALL_PRIM = '/World/envs/env_0/Map/wall_south'
ROBOT = {'start_position_world_m': [-10.2, 0.5, 0.512], 'yaw_rad': 0.0}
CONTROL = {'mode': 'forward_velocity', 'forward_mps': 0.5, 'max_steps': 120}
OBSTACLE = {
    'size_m': [0.4, 0.4, 0.6],
    'start_position_world_m': [0.0, 0.0, 1.0],
    'velocity_world_mps': [0.0, 0.4, 0.0],
    'kinematic': True,
}
TARGET = {
    'kind': 'map_wall',
    'prim_path': WALL_PRIM,
    'map_config': 'configs/maps/rmuc2027.yaml',
    'local_config': 'configs/maps/rmuc2027.local.yaml',
}
EXPECTED_BY_ROLE = {
    'wall': {
        'acceptable_physical_outcomes': ['PHYSX_CONTACT_FORCE_MEASURED'],
        'must_conditions': ['force_measured', 'attribution_attributed',
                            'attribution_within_inventory'],
        'attribution_prim_paths': [WALL_PRIM],
    },
    'obstacle': {
        'acceptable_physical_outcomes': [
            'PHYSX_CONTACT_FORCE_MEASURED',
            'CONTACT_FORCE_MEASURED_UNATTRIBUTED',
            'PHYSX_CONTACT_EVENT_ONLY',
        ],
        'must_conditions': ['event_or_force', 'sensor_available'],
    },
    'clearance': {
        'acceptable_physical_outcomes': ['NO_CONTACT'],
        'must_conditions': ['no_contact', 'sensor_available', 'event_false',
                            'force_valid_zero'],
    },
    'geometry': {
        'acceptable_physical_outcomes': ['GEOMETRY_OVERLAP_ONLY'],
        'must_conditions': ['overlap_gt_0.02', 'event_false',
                            'force_valid_zero', 'not_geometry_only'],
    },
    'replay': {
        'acceptable_physical_outcomes': [
            'PHYSX_CONTACT_FORCE_MEASURED',
            'CONTACT_FORCE_MEASURED_UNATTRIBUTED',
            'PHYSX_CONTACT_EVENT_ONLY',
            'NO_CONTACT',
        ],
        'must_conditions': ['event_or_force'],
    },
}


def _now_iso(offset_s=0.0):
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_s)).isoformat(timespec='microseconds')


def _replay_dir(tmp_path, name):
    path = tmp_path / 'previous_runs' / name
    path.mkdir(parents=True, exist_ok=True)
    return path.as_posix()


def _wall_segment(repeats=2):
    cases = []
    for repeat in range(repeats):
        cases.append({
            'case_id': 'contact_A_wall_front',
            'repeat': repeat,
            'robot': dict(ROBOT),
            'control': dict(CONTROL),
            'obstacle': None,
            'target': dict(TARGET),
            'expected_physical': ['PHYSX_CONTACT_FORCE_MEASURED'],
        })
    return {'segment_id': 'contact_A_wall', 'role': 'wall', 'mode': 'wall',
            'repeats': repeats, 'cases': cases}


def _obstacle_segment(repeats=2):
    cases = []
    for repeat in range(repeats):
        cases.append({
            'case_id': 'contact_B_obstacle_cross',
            'repeat': repeat,
            'robot': dict(ROBOT),
            'control': dict(CONTROL),
            'obstacle': dict(OBSTACLE),
            'target': None,
            'expected_physical': ['PHYSX_CONTACT_FORCE_MEASURED',
                                  'PHYSX_CONTACT_EVENT_ONLY'],
        })
    return {'segment_id': 'contact_B_obstacle', 'role': 'obstacle',
            'mode': 'obstacle', 'repeats': repeats, 'cases': cases}


def _clearance_segment(repeats=2):
    cases = []
    for repeat in range(repeats):
        cases.append({
            'case_id': 'contact_C_clearance_near',
            'repeat': repeat,
            'robot': dict(ROBOT),
            'control': dict(CONTROL),
            'obstacle': dict(OBSTACLE),
            'target': None,
            'expected_physical': ['NO_CONTACT'],
        })
    return {'segment_id': 'contact_C_clearance', 'role': 'clearance',
            'mode': 'clearance', 'repeats': repeats, 'cases': cases}


def _geometry_segment(repeats=2):
    cases = []
    for repeat in range(repeats):
        cases.append({
            'case_id': 'contact_D_geometry_overlap',
            'repeat': repeat,
            'robot': dict(ROBOT),
            'control': dict(CONTROL),
            'obstacle': dict(OBSTACLE),
            'target': None,
            'expected_physical': ['GEOMETRY_OVERLAP_ONLY'],
        })
    return {'segment_id': 'contact_D_geometry', 'role': 'geometry',
            'mode': 'geometry', 'repeats': repeats, 'cases': cases}


def _replay_params():
    return dict(REPLAY_PARAMS_BOUNDARY_DEFAULT)


def _mutate_replay_previous_dir(payload, segment_index, new_dir):
    for case in payload['segments'][segment_index]['cases']:
        case['previous_run_dir'] = new_dir


def _replay_segment(tmp_path, segment_id='replay_contact_inferred',
                    repeats=2, label='CONTACT_INFERRED', name=None):
    cases = []
    for repeat in range(repeats):
        cases.append({
            'case_id': segment_id + '_source',
            'repeat': repeat,
            'source_cases_file': SOURCE_CASES,
            'previous_run_dir': _replay_dir(tmp_path, name or segment_id),
            'previous_episode_id': 'boundary_A_static_far_r0-supervisor',
            'previous_physical_label': label,
        })
    return {'segment_id': segment_id, 'role': 'replay', 'mode': 'replay',
            'repeats': repeats, 'replay_params': _replay_params(),
            'cases': cases}


def _cases_payload(tmp_path):
    return {
        'schema_version': CONTACT_CASES_SCHEMA,
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'segments': [
            _wall_segment(),
            _obstacle_segment(),
            _clearance_segment(),
            _geometry_segment(),
            _replay_segment(tmp_path),
            _replay_segment(tmp_path, segment_id='replay_no_contact',
                            repeats=1, label='NO_CONTACT'),
        ],
    }


def _case_ids(cases_payload):
    case_ids = {}
    for segment in cases_payload['segments']:
        ids = []
        for case in segment['cases']:
            if case['case_id'] not in ids:
                ids.append(case['case_id'])
        case_ids[segment['segment_id']] = sorted(ids)
    return case_ids


def _expected_payload(cases_payload):
    cases = {}
    ids = _case_ids(cases_payload)
    for segment_id, segment in zip(SEGMENT_IDS, cases_payload['segments']):
        role = segment['role']
        for case_id in ids[segment_id]:
            spec = dict(EXPECTED_BY_ROLE[role])
            if role == 'replay':
                spec['replay_verdict'] = 'UNDECIDABLE' if 'inferred' in \
                    segment_id else 'CONSISTENT'
            cases[case_id] = spec
    return {
        'schema_version': CONTACT_EXPECTED_SCHEMA,
        'status': 'EXPECTED_NOT_CONCLUSION',
        'note': '预期非结论，实际以独立核验为准。',
        'freeze_rule': '运行前冻结、不得事后扩展。',
        'cases': cases,
    }


def _plan_kwargs_for(segment_id, segment):
    run_params = {'repeats': segment['repeats'],
                  'cases': segment['cases']}
    if segment['replay_params'] is not None:
        run_params['replay_params'] = segment['replay_params']
    if any(len(indices) > 1
           for indices in segment['repeat_indices'].values()):
        run_params['repeat_indices'] = segment['repeat_indices']
    return dict(
        segment_id=segment_id,
        role=segment['role'],
        mode=segment['mode'],
        cases_file=CASES_FILE,
        cases_sha256=CASES_SHA,
        case_ids=segment['case_ids'],
        expected_file=EXPECTED_FILE,
        expected_sha256=EXPECTED_SHA,
        contact_contract_version=CONTACT_CONTRACT_VERSION,
        envelope_contract_version=ENVELOPE_CONTRACT_VERSION,
        vehicle_config=VEHICLE_FILE,
        vehicle_config_sha256=VEHICLE_SHA,
        map_config=MAP_FILE,
        map_config_sha256=MAP_SHA,
        run_params=run_params,
    )


def _plans_and_cases(cases_payload):
    normalized = normalize_cases_payload(cases_payload)
    plans = {
        segment_id: build_run_plan(
            **_plan_kwargs_for(segment_id,
                               normalized['segments'][segment_id]))
        for segment_id in SEGMENT_IDS
    }
    return normalized, plans


def _freeze_kwargs(tmp_path, cases_payload=None, expected_payload=None):
    cases_payload = cases_payload or _cases_payload(tmp_path)
    normalized, plans = _plans_and_cases(cases_payload)
    expected = expected_payload or _expected_payload(cases_payload)
    return dict(
        frozen_at=_now_iso(),
        code_commit='f' * 40,
        worktree_state={'tracked_paths': list(TRACKED_PATHS),
                        'status_text_sha256': WORKTREE_SHA, 'clean': False},
        map_state={'map_asset_id': 'rmuc2027-isaacsim-20261028',
                   'terrain_sha256': TERRAIN_SHA,
                   'preview_sha256': PREVIEW_SHA,
                   'map_config_sha256': MAP_CONFIG_SHA,
                   'map_config_file': MAP_FILE},
        cases=normalized,
        segment_run_plans=plans,
        expected=expected,
        expected_file=EXPECTED_FILE,
        expected_sha256=EXPECTED_SHA,
        note='接触证据/包络预运行冻结：预期非结论，实际以独立核验为准。',
    )


def _freeze(tmp_path, **overrides):
    kwargs = _freeze_kwargs(tmp_path)
    kwargs.update(overrides)
    return build_freeze(**kwargs)


# ---------------------------------------------------------------------------
# cases normalization
# ---------------------------------------------------------------------------

def test_normalize_cases_fixed_segment_table(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    assert normalized['schema_version'] == CONTACT_CASES_SCHEMA
    assert normalized['contact_contract_version'] == CONTACT_CONTRACT_VERSION
    assert normalized['envelope_contract_version'] == ENVELOPE_CONTRACT_VERSION
    assert normalized['total_episodes'] == MIN_EPISODES_REQUIRED
    assert set(normalized['segments']) == set(SEGMENT_IDS)
    for segment_id, (role, mode, episodes) in SEGMENT_TABLE.items():
        segment = normalized['segments'][segment_id]
        assert segment['role'] == role
        assert segment['mode'] == mode
        assert segment['episodes'] == episodes
        assert segment['case_ids'] == sorted(segment['case_ids'])
    assert normalized['segments']['contact_A_wall']['repeats'] == 2
    assert normalized['segments']['replay_no_contact']['repeats'] == 1
    assert normalized['segments']['replay_no_contact']['episodes'] == 1
    assert normalized['segments']['contact_A_wall']['case_ids'] == [
        'contact_A_wall_front']
    json.dumps(normalized)


def test_normalize_cases_accepts_two_unique_ids_layout(tmp_path):
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    ids = ['contact_A_wall_front_a', 'contact_A_wall_front_b']
    wall['repeats'] = 1
    for index, case in enumerate(wall['cases']):
        case['case_id'] = ids[index]
        case['repeat'] = 0
    normalized = normalize_cases_payload(payload)
    assert normalized['segments']['contact_A_wall']['case_ids'] == ids
    assert normalized['segments']['contact_A_wall']['episodes'] == 2
    assert normalized['total_episodes'] == MIN_EPISODES_REQUIRED


def test_normalize_cases_rejects_wrong_schema_and_versions(tmp_path):
    payload = _cases_payload(tmp_path)
    payload['schema_version'] = 'boom_birds.contact_verification_cases.v0'
    with pytest.raises(ContactPlanError, match='CASES_SCHEMA_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['contact_contract_version'] = 'boom_birds.contact_evidence.v1'
    with pytest.raises(ContactPlanError, match='CONTACT_CONTRACT_VERSION'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['envelope_contract_version'] = 'boom_birds.body_envelope.v1'
    with pytest.raises(ContactPlanError, match='ENVELOPE_CONTRACT_VERSION'):
        normalize_cases_payload(payload)


def test_normalize_cases_rejects_segment_table_drift(tmp_path):
    payload = _cases_payload(tmp_path)
    payload['segments'] = payload['segments'][:-1]
    with pytest.raises(ContactPlanError, match='CASES_SEGMENTS_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['segments'][0]['role'] = 'obstacle'
    with pytest.raises(ContactPlanError, match='CASES_SEGMENT_ROLE_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['segments'][1]['mode'] = 'wall'
    with pytest.raises(ContactPlanError, match='CASES_SEGMENT_MODE_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['segments'][0]['repeats'] = 0
    with pytest.raises(ContactPlanError, match='REPEATS_INVALID'):
        normalize_cases_payload(payload)


def test_normalize_cases_rejects_episode_count(tmp_path):
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['repeats'] = 2
    extra = dict(wall['cases'][0])
    extra['case_id'] = 'contact_A_wall_second'
    extra['repeat'] = 0
    wall['cases'].append(extra)
    with pytest.raises(ContactPlanError, match='CASES_EPISODES_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['segments'][5]['repeats'] = 2
    with pytest.raises(ContactPlanError, match='CASES_EPISODES_MISMATCH'):
        normalize_cases_payload(payload)


def test_normalize_cases_rejects_repeat_inconsistencies(tmp_path):
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['cases'][1]['repeat'] = 0
    with pytest.raises(ContactPlanError, match='CASE_REPEAT_DUPLICATE'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['cases'][1]['control']['forward_mps'] = 0.7
    with pytest.raises(ContactPlanError, match='CASE_REPEAT_SPEC_MISMATCH'):
        normalize_cases_payload(payload)


def test_normalize_cases_rejects_bad_case_fields(tmp_path):
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['cases'][0]['target'] = None
    with pytest.raises(ContactPlanError, match='CASE_TARGET_MISSING'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['cases'][0]['control']['mode'] = 'teleport'
    with pytest.raises(ContactPlanError, match='CONTROL_MODE'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    obstacle = payload['segments'][1]
    obstacle['cases'][0]['obstacle']['kinematic'] = False
    with pytest.raises(ContactPlanError, match='CASE_OBSTACLE'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    wall = payload['segments'][0]
    wall['cases'][0]['target']['kind'] = 'arena_wall'
    with pytest.raises(ContactPlanError, match='CASE_TARGET'):
        normalize_cases_payload(payload)


def test_normalize_cases_rejects_replay_contract(tmp_path):
    payload = _cases_payload(tmp_path)
    replay = payload['segments'][4]
    del replay['cases'][0]['previous_episode_id']
    with pytest.raises(ContactPlanError, match='REPLAY_CASE_MISSING'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    replay = payload['segments'][4]
    replay['cases'][0]['previous_physical_label'] = 'CONTACT'
    with pytest.raises(ContactPlanError, match='PREVIOUS_PHYSICAL_LABEL'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    del payload['segments'][4]['replay_params']
    with pytest.raises(ContactPlanError, match='REPLAY_PARAMS_MISSING'):
        normalize_cases_payload(payload)


def test_normalize_cases_replay_params_must_match_boundary_default(tmp_path):
    payload = _cases_payload(tmp_path)
    payload['segments'][4]['replay_params']['obs_delay_s'] = 0.5
    with pytest.raises(ContactPlanError, match='REPLAY_PARAMS_MISMATCH'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    payload['segments'][4]['replay_params']['obstacle_time_clamp'] = False
    with pytest.raises(ContactPlanError, match='REPLAY_PARAMS_INVALID'):
        normalize_cases_payload(payload)
    payload = _cases_payload(tmp_path)
    del payload['segments'][4]['replay_params']['ttl_ms']
    with pytest.raises(ContactPlanError, match='REPLAY_PARAMS_MISSING'):
        normalize_cases_payload(payload)


def test_normalize_cases_replay_references_must_exist(tmp_path):
    payload = _cases_payload(tmp_path)
    for case in payload['segments'][4]['cases']:
        case['previous_run_dir'] = (tmp_path / 'missing_run').as_posix()
    with pytest.raises(ContactPlanError, match='REPLAY_PREVIOUS_RUN_MISSING'):
        normalize_cases_payload(payload, repo_root=tmp_path)
    payload = _cases_payload(tmp_path)
    for case in payload['segments'][5]['cases']:
        case['source_cases_file'] = (tmp_path / 'missing_cases.json').as_posix()
    with pytest.raises(ContactPlanError, match='REPLAY_SOURCE_CASES_MISSING'):
        normalize_cases_payload(payload, repo_root=tmp_path)


# ---------------------------------------------------------------------------
# build_run_plan
# ---------------------------------------------------------------------------

def test_build_run_plan_normalizes_fields(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    segment = normalized['segments']['contact_A_wall']
    kwargs = _plan_kwargs_for('contact_A_wall', segment)
    kwargs['run_params'] = json.loads(json.dumps(kwargs['run_params']))
    kwargs['run_params']['cases']['contact_A_wall_front'][
        'control']['forward_mps'] = 0.123456789
    kwargs['cases_file'] = 'configs\\scenarios\\' + Path(CASES_FILE).name
    plan = build_run_plan(**kwargs)
    assert tuple(plan) == RUN_PLAN_FIELDS
    assert plan['cases_file'] == CASES_FILE
    assert plan['case_ids'] == ['contact_A_wall_front']
    assert plan['role'] == 'wall'
    assert plan['mode'] == 'wall'
    assert plan['contact_contract_version'] == CONTACT_CONTRACT_VERSION
    assert plan['run_params']['cases']['contact_A_wall_front'][
        'control']['forward_mps'] == 0.123457
    json.dumps(plan)


def test_build_run_plan_rejects_unknown_and_missing_fields(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    kwargs = _plan_kwargs_for(
        'contact_A_wall', normalized['segments']['contact_A_wall'])
    with pytest.raises(ContactPlanError, match='UNKNOWN_RUN_PLAN_FIELD'):
        build_run_plan(**dict(kwargs, surprise=1))
    incomplete = dict(kwargs)
    del incomplete['run_params']
    with pytest.raises(ContactPlanError, match='MISSING_RUN_PLAN_FIELD'):
        build_run_plan(**incomplete)


def test_build_run_plan_rejects_segment_contract_mismatch(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    kwargs = _plan_kwargs_for(
        'contact_A_wall', normalized['segments']['contact_A_wall'])
    with pytest.raises(ContactPlanError, match='SEGMENT_ID_INVALID'):
        build_run_plan(**dict(kwargs, segment_id='contact_Z_unknown'))
    with pytest.raises(ContactPlanError, match='SEGMENT_ROLE_MISMATCH'):
        build_run_plan(**dict(kwargs, role='obstacle'))
    with pytest.raises(ContactPlanError, match='SEGMENT_MODE_MISMATCH'):
        build_run_plan(**dict(kwargs, mode='replay'))
    with pytest.raises(ContactPlanError, match='CONTACT_CONTRACT_VERSION'):
        build_run_plan(**dict(kwargs,
                              contact_contract_version='boom_birds.contact_evidence.v1'))
    with pytest.raises(ContactPlanError, match='ENVELOPE_CONTRACT_VERSION'):
        build_run_plan(**dict(kwargs,
                              envelope_contract_version='boom_birds.body_envelope.v1'))


def test_build_run_plan_rejects_bad_hashes_and_case_ids(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    kwargs = _plan_kwargs_for(
        'contact_A_wall', normalized['segments']['contact_A_wall'])
    with pytest.raises(ContactPlanError, match='HASH_INVALID'):
        build_run_plan(**dict(kwargs, cases_sha256='not-a-hash'))
    with pytest.raises(ContactPlanError, match='CASE_IDS_DUPLICATE'):
        build_run_plan(**dict(
            kwargs,
            case_ids=['contact_A_wall_front', 'contact_A_wall_front']))
    with pytest.raises(ContactPlanError, match='CASE_IDS_INVALID'):
        build_run_plan(**dict(kwargs, case_ids=[]))
    with pytest.raises(ContactPlanError, match='RUN_PARAMS_CASES_MISMATCH'):
        tampered = json.loads(json.dumps(kwargs['run_params']))
        tampered['cases']['other_case'] = tampered['cases'].pop(
            'contact_A_wall_front')
        build_run_plan(**dict(kwargs, run_params=tampered))


def test_build_run_plan_rejects_episode_and_repeat_mismatch(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    kwargs = _plan_kwargs_for(
        'contact_A_wall', normalized['segments']['contact_A_wall'])
    tampered = json.loads(json.dumps(kwargs['run_params']))
    tampered['repeats'] = 3
    with pytest.raises(ContactPlanError, match='RUN_PLAN_EPISODES_MISMATCH'):
        build_run_plan(**dict(kwargs, run_params=tampered))


def test_build_run_plan_replay_keeps_references(tmp_path):
    normalized = normalize_cases_payload(_cases_payload(tmp_path))
    segment = normalized['segments']['replay_contact_inferred']
    plan = build_run_plan(**_plan_kwargs_for('replay_contact_inferred',
                                             segment))
    assert plan['role'] == 'replay'
    assert plan['mode'] == 'replay'
    spec = plan['run_params']['cases']['replay_contact_inferred_source']
    assert spec['previous_physical_label'] == 'CONTACT_INFERRED'
    assert spec['previous_episode_id'] == 'boundary_A_static_far_r0-supervisor'
    assert plan['run_params']['replay_params'] == dict(
        REPLAY_PARAMS_BOUNDARY_DEFAULT)


# ---------------------------------------------------------------------------
# expected normalization
# ---------------------------------------------------------------------------

def test_expected_covers_all_cases_and_merges_segments(tmp_path):
    payload = _cases_payload(tmp_path)
    normalized = normalize_cases_payload(payload)
    expected = _expected_payload(payload)
    normalized_expected, per_segment = normalize_expected_payload(
        expected, normalized)
    assert normalized_expected['schema_version'] == CONTACT_EXPECTED_SCHEMA
    assert normalized_expected['status'] == 'EXPECTED_NOT_CONCLUSION'
    covered = set()
    for segment_id in SEGMENT_IDS:
        covered.update(per_segment[segment_id])
        for spec in per_segment[segment_id].values():
            assert spec['acceptable_physical_outcomes']
            assert set(spec['acceptable_physical_outcomes']) <= set(
                PHYSICAL_OUTCOMES)
            if segment_id in REPLAY_SEGMENT_IDS:
                assert spec['replay_verdict'] in REPLAY_VERDICTS
    assert len(covered) == 6
    assert per_segment['replay_no_contact'][
        'replay_no_contact_source']['replay_verdict'] == 'CONSISTENT'


def test_expected_missing_case_is_rejected(tmp_path):
    payload = _cases_payload(tmp_path)
    normalized = normalize_cases_payload(payload)
    expected = _expected_payload(payload)
    del expected['cases']['contact_C_clearance_near']
    with pytest.raises(ContactPlanError, match='EXPECTED_CASE_MISSING'):
        normalize_expected_payload(expected, normalized)


def test_expected_schema_and_condition_validation(tmp_path):
    payload = _cases_payload(tmp_path)
    normalized = normalize_cases_payload(payload)
    expected = _expected_payload(payload)
    broken = json.loads(json.dumps(expected))
    broken['schema_version'] = 'boom_birds.contact_verification_expected.v0'
    with pytest.raises(ContactPlanError, match='EXPECTED_SCHEMA_MISMATCH'):
        normalize_expected_payload(broken, normalized)
    broken = json.loads(json.dumps(expected))
    broken['status'] = 'PASS'
    with pytest.raises(ContactPlanError, match='EXPECTED_STATUS_INVALID'):
        normalize_expected_payload(broken, normalized)
    broken = json.loads(json.dumps(expected))
    broken['cases']['contact_A_wall_front']['must_conditions'] = [123]
    with pytest.raises(ContactPlanError, match='EXPECTED_CONDITION_INVALID'):
        normalize_expected_payload(broken, normalized)
    broken = json.loads(json.dumps(expected))
    broken['cases']['contact_A_wall_front'][
        'acceptable_physical_outcomes'] = ['NOT_AN_OUTCOME']
    with pytest.raises(ContactPlanError, match='ACCEPTABLE_PHYSICAL_OUTCOMES'
                       ):
        normalize_expected_payload(broken, normalized)


def test_expected_accepts_lead_contact_layout(tmp_path):
    """Lead 2026-11-02 layout: segment-keyed specs, acceptable_physical alias,
    segment case-id lists and a top-level replay_verdicts rule mapping."""
    payload = _cases_payload(tmp_path)
    normalized = normalize_cases_payload(payload)
    expected = {
        'schema_version': CONTACT_EXPECTED_SCHEMA,
        'status': 'EXPECTED_NOT_CONCLUSION',
        'contact_contract_version': CONTACT_CONTRACT_VERSION,
        'envelope_contract_version': ENVELOPE_CONTRACT_VERSION,
        'notes': '预期非结论',
        'cases': {
            segment_id: {
                'segment_id': segment_id,
                'mode': SEGMENT_TABLE[segment_id][1],
                'acceptable_physical': EXPECTED_BY_ROLE[
                    SEGMENT_TABLE[segment_id][0]]['acceptable_physical_outcomes'],
                'must_conditions': ['sensor_available_true',
                                    {'kind': 'attribution_prim_in',
                                     'value': WALL_PRIM}],
                'unsupported_allowed': True,
            }
            for segment_id in SEGMENT_IDS
        },
        'replay_verdicts': {
            'replay_contact_inferred_source': {
                'previous_physical_label': 'CONTACT_INFERRED',
                'allowed': ['CONSISTENT', 'MISREPORT', 'MISS', 'UNDECIDABLE'],
                'rule': 'contact inferred must be confirmed from raw records',
            },
            'replay_no_contact_source': {
                'previous_physical_label': 'NO_CONTACT',
                'allowed': ['CONSISTENT'],
                'rule': 'no-contact replay must record valid NO_CONTACT',
            },
        },
        'segments': {
            segment_id: {
                'role': SEGMENT_TABLE[segment_id][0],
                'cases': [
                    case_id
                    for case_id in normalized['segments'][segment_id]['case_ids']
                ] * normalized['segments'][segment_id]['repeats'],
                'expected_episodes': normalized['segments'][segment_id][
                    'episodes'],
            }
            for segment_id in SEGMENT_IDS
        },
    }
    normalized_expected, per_segment = normalize_expected_payload(
        expected, normalized)
    assert normalized_expected['contact_contract_version'] == \
        CONTACT_CONTRACT_VERSION
    # segment-keyed wall spec resolves through the wall case and the
    # attribution_prim_in must condition is exposed as attribution_prim_paths.
    wall = per_segment['contact_A_wall']['contact_A_wall_front']
    assert wall['acceptable_physical_outcomes'] == [
        'PHYSX_CONTACT_FORCE_MEASURED']
    assert wall['attribution_prim_paths'] == [WALL_PRIM]
    replay = per_segment['replay_contact_inferred'][
        'replay_contact_inferred_source']
    assert replay['replay_verdict_allowed'] == [
        'CONSISTENT', 'MISREPORT', 'MISS', 'UNDECIDABLE']
    no_contact = per_segment['replay_no_contact'][
        'replay_no_contact_source']
    assert no_contact['replay_verdict'] == 'CONSISTENT'


def test_expected_replay_verdict_required(tmp_path):
    payload = _cases_payload(tmp_path)
    normalized = normalize_cases_payload(payload)
    expected = _expected_payload(payload)
    del expected['cases']['replay_contact_inferred_source']['replay_verdict']
    with pytest.raises(ContactPlanError, match='REPLAY_VERDICT_MISSING'):
        normalize_expected_payload(expected, normalized)


# ---------------------------------------------------------------------------
# build_freeze
# ---------------------------------------------------------------------------

def test_build_freeze_structure_and_budget(tmp_path):
    freeze = _freeze(tmp_path)
    assert freeze['schema_version'] == CONTACT_FREEZE_SCHEMA
    assert freeze['status'] == FREEZE_STATUS
    assert datetime.fromisoformat(freeze['frozen_at']).tzinfo is not None
    assert freeze['contact_contract_version'] == CONTACT_CONTRACT_VERSION
    assert freeze['envelope_contract_version'] == ENVELOPE_CONTRACT_VERSION
    assert set(freeze['segments']) == set(SEGMENT_IDS)
    assert list(freeze['segments']) == list(SEGMENT_IDS)
    assert freeze['cases_file'] == CASES_FILE
    assert freeze['cases_sha256'] == CASES_SHA
    assert freeze['expected_file'] == EXPECTED_FILE
    assert freeze['expected_sha256'] == EXPECTED_SHA
    assert freeze['map_state']['terrain_sha256'] == TERRAIN_SHA
    assert freeze['worktree_state']['status_text_sha256'] == WORKTREE_SHA
    assert freeze['budget']['total_episodes'] == MIN_EPISODES_REQUIRED
    assert freeze['budget']['min_episodes_required'] == MIN_EPISODES_REQUIRED
    assert freeze['budget']['by_role'] == {
        'wall': 2, 'obstacle': 2, 'clearance': 2, 'geometry': 2, 'replay': 3}
    assert sum(freeze['budget']['segment_episodes'].values()) == 11
    for segment_id, (role, mode, episodes) in SEGMENT_TABLE.items():
        segment = freeze['segments'][segment_id]
        assert segment['role'] == role
        assert segment['mode'] == mode
        assert segment['episodes'] == episodes
        assert segment['repeats'] == (
            1 if segment_id == 'replay_no_contact' else 2)
        assert segment['run_plan']['case_ids'] == segment['case_ids']
        assert segment['expected']['cases']
    replay = freeze['segments']['replay_contact_inferred']
    spec = replay['run_plan']['run_params']['cases'][
        'replay_contact_inferred_source']
    assert spec['previous_physical_label'] == 'CONTACT_INFERRED'
    assert freeze['support_scope']['contact_contract_version'] == \
        CONTACT_CONTRACT_VERSION
    assert freeze['support_scope']['envelope_contract_version'] == \
        ENVELOPE_CONTRACT_VERSION
    assert freeze['support_scope']['replay_sources']
    assert freeze['support_scope']['limitations']
    assert '预期非结论' in freeze['note']
    json.dumps(freeze)


def test_build_freeze_embeds_expected_per_case(tmp_path):
    freeze = _freeze(tmp_path)
    expected = freeze['expected']
    assert expected['schema_version'] == CONTACT_EXPECTED_SCHEMA
    assert expected['status'] == 'EXPECTED_NOT_CONCLUSION'
    wall = freeze['segments']['contact_A_wall']['expected']['cases'][
        'contact_A_wall_front']
    assert wall['acceptable_physical_outcomes'] == [
        'PHYSX_CONTACT_FORCE_MEASURED']
    assert wall['attribution_prim_paths'] == [WALL_PRIM]
    assert wall['case_id'] == 'contact_A_wall_front'
    replay = freeze['segments']['replay_no_contact']['expected']['cases'][
        'replay_no_contact_source']
    assert replay['replay_verdict'] == 'CONSISTENT'


def test_build_freeze_rejects_segment_set_and_plan_tampering(tmp_path):
    kwargs = _freeze_kwargs(tmp_path)
    plans = dict(kwargs['segment_run_plans'])
    plans.pop('contact_D_geometry')
    with pytest.raises(ContactPlanError, match='SEGMENTS_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=plans)
    kwargs = _freeze_kwargs(tmp_path)
    plans = dict(kwargs['segment_run_plans'])
    plans['contact_unknown'] = plans['contact_A_wall']
    with pytest.raises(ContactPlanError, match='SEGMENTS_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=plans)
    # Tampered case parameter inside the run plan must be rejected against cases.
    tampered = json.loads(json.dumps(kwargs['segment_run_plans']))
    tampered['contact_A_wall']['run_params']['cases'][
        'contact_A_wall_front']['control']['forward_mps'] = 0.9
    with pytest.raises(ContactPlanError, match='RUN_PLAN_CASES_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=tampered)
    # Tampered case_ids must be rejected.
    tampered = json.loads(json.dumps(kwargs['segment_run_plans']))
    tampered['contact_A_wall']['case_ids'] = ['other_case']
    with pytest.raises(ContactPlanError,
                       match='RUN_PARAMS_CASES_MISMATCH|RUN_PLAN_CASE_IDS_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=tampered)


def test_build_freeze_rejects_missing_expected(tmp_path):
    kwargs = _freeze_kwargs(tmp_path)
    expected = json.loads(json.dumps(kwargs['expected']))
    del expected['cases']['contact_B_obstacle_cross']
    with pytest.raises(ContactPlanError, match='EXPECTED_CASE_MISSING'):
        _freeze(tmp_path, expected=expected)


def test_build_freeze_rejects_bad_expected_file_hash(tmp_path):
    kwargs = _freeze_kwargs(tmp_path)
    plans = json.loads(json.dumps(kwargs['segment_run_plans']))
    plans['contact_A_wall']['expected_sha256'] = '0' * 64
    with pytest.raises(ContactPlanError, match='EXPECTED_SHA256_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=plans)
    kwargs = _freeze_kwargs(tmp_path)
    plans = json.loads(json.dumps(kwargs['segment_run_plans']))
    plans['contact_A_wall']['cases_sha256'] = '0' * 64
    with pytest.raises(ContactPlanError, match='CASES_SHA256_MISMATCH'):
        _freeze(tmp_path, segment_run_plans=plans)


def test_build_freeze_rejects_budget_and_support_scope(tmp_path):
    with pytest.raises(ContactPlanError, match='BUDGET_MISMATCH'):
        _freeze(tmp_path, budget={'total_episodes': 10})
    with pytest.raises(ContactPlanError, match='BUDGET'):
        _freeze(tmp_path, budget='many')
    with pytest.raises(ContactPlanError, match='NOTE_INVALID'):
        _freeze(tmp_path, note='')
    scope = _freeze(tmp_path)['support_scope']
    with pytest.raises(ContactPlanError, match='SUPPORT_SCOPE_MISSING'):
        _freeze(tmp_path, support_scope={'scope': 'CURRENT_SIM_MODEL_ONLY'})
    broken = dict(scope)
    broken['contact_contract_version'] = 'boom_birds.contact_evidence.v1'
    with pytest.raises(ContactPlanError, match='SUPPORT_SCOPE_MISMATCH'):
        _freeze(tmp_path, support_scope=broken)


def test_build_freeze_rejects_missing_replay_reference(tmp_path):
    payload = _cases_payload(tmp_path)
    _normalized, plans = _plans_and_cases(payload)
    _mutate_replay_previous_dir(payload, 4, (tmp_path / 'gone').as_posix())
    with pytest.raises(ContactPlanError, match='REPLAY_PREVIOUS_RUN_MISSING'):
        build_freeze(
            frozen_at=_now_iso(), code_commit='f' * 40,
            worktree_state={'tracked_paths': list(TRACKED_PATHS),
                            'status_text_sha256': WORKTREE_SHA, 'clean': False},
            map_state=_freeze_kwargs(tmp_path)['map_state'],
            cases=payload, segment_run_plans=plans,
            expected=_expected_payload(payload), expected_file=EXPECTED_FILE,
            expected_sha256=EXPECTED_SHA,
            note='接触证据预运行冻结：预期非结论。', repo_root=tmp_path)


# ---------------------------------------------------------------------------
# validate_run_plan
# ---------------------------------------------------------------------------

def test_validate_run_plan_accepts_all_frozen_plans(tmp_path):
    freeze = _freeze(tmp_path)
    for segment_id in SEGMENT_IDS:
        plan = json.loads(json.dumps(
            freeze['segments'][segment_id]['run_plan']))
        assert validate_run_plan(freeze, segment_id, plan) is None


def test_validate_run_plan_rejects_parameter_tampering(tmp_path):
    freeze = _freeze(tmp_path)
    plan = json.loads(json.dumps(
        freeze['segments']['contact_C_clearance']['run_plan']))
    plan['run_params']['cases']['contact_C_clearance_near'][
        'obstacle']['velocity_world_mps'] = [0.0, 0.9, 0.0]
    with pytest.raises(ContactPlanError, match='RUN_PLAN_MISMATCH'):
        validate_run_plan(freeze, 'contact_C_clearance', plan)


def test_validate_run_plan_rejects_hash_and_case_id_tampering(tmp_path):
    freeze = _freeze(tmp_path)
    plan = json.loads(json.dumps(
        freeze['segments']['contact_A_wall']['run_plan']))
    plan['vehicle_config_sha256'] = '0' * 64
    with pytest.raises(ContactPlanError, match='RUN_PLAN_MISMATCH'):
        validate_run_plan(freeze, 'contact_A_wall', plan)
    plan = json.loads(json.dumps(
        freeze['segments']['contact_A_wall']['run_plan']))
    plan['case_ids'] = ['other_case']
    with pytest.raises(ContactPlanError,
                       match='RUN_PARAMS_CASES_MISMATCH|RUN_PLAN_MISMATCH'):
        validate_run_plan(freeze, 'contact_A_wall', plan)


def test_validate_run_plan_rejects_bad_inputs(tmp_path):
    freeze = _freeze(tmp_path)
    plan = json.loads(json.dumps(
        freeze['segments']['contact_A_wall']['run_plan']))
    with pytest.raises(ContactPlanError, match='SEGMENT_ID_INVALID'):
        validate_run_plan(freeze, 'contact_unknown', plan)
    broken = dict(freeze)
    broken['schema_version'] = 'boom_birds.contact_verification_freeze.v0'
    with pytest.raises(ContactPlanError, match='SCHEMA_VERSION_MISMATCH'):
        validate_run_plan(broken, 'contact_A_wall', plan)
    no_plan = json.loads(json.dumps(freeze))
    del no_plan['segments']['contact_A_wall']['run_plan']
    with pytest.raises(ContactPlanError, match='SEGMENT_RUN_PLAN_MISSING'):
        validate_run_plan(no_plan, 'contact_A_wall', plan)
    incomplete = dict(plan)
    del incomplete['run_params']
    with pytest.raises(ContactPlanError, match='RUN_PLAN_FIELD_MISSING'):
        validate_run_plan(freeze, 'contact_A_wall', incomplete)


# ---------------------------------------------------------------------------
# worktree / lineage helpers
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


def test_worktree_state_reports_clean_repo(git_repo):
    state = worktree_state(git_repo)
    assert state['clean'] is True
    assert state['tracked_paths'] == list(TRACKED_PATHS)
    assert len(state['status_text_sha256']) == 64


def test_worktree_state_changes_and_extra_paths(git_repo):
    clean = worktree_state(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\n', encoding='utf-8')
    dirty = worktree_state(git_repo)
    assert dirty['clean'] is False
    assert dirty['status_text_sha256'] != clean['status_text_sha256']
    extra = worktree_state(git_repo, extra_untracked_paths=[
        'configs/contact_verification_freeze_v1.json'])
    assert extra['status_text_sha256'] != dirty['status_text_sha256']
    ignored = worktree_state(git_repo, extra_untracked_paths=[
        'outputs/run.json', 'tmp/freeze.json'])
    assert ignored['status_text_sha256'] == dirty['status_text_sha256']


def test_worktree_state_matches_previous_work_package_normalization(git_repo):
    from boom_birds.evaluation.boundary_plan import (
        worktree_state as boundary_worktree_state)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 2\r\n', encoding='utf-8')
    (git_repo / 'configs' / 'other.json').write_text('{}\n', encoding='utf-8')
    ours = worktree_state(git_repo)
    reference = boundary_worktree_state(git_repo)
    assert ours['status_text_sha256'] == reference['status_text_sha256']
    assert ours['clean'] == reference['clean']


def test_git_head_and_sha256_file(git_repo):
    head = git_head(git_repo)
    assert len(head) >= 7 and all(char in '0123456789abcdef' for char in head)
    expected = hashlib.sha256(
        (git_repo / 'src' / 'mod.py').read_bytes()).hexdigest()
    assert sha256_file(git_repo / 'src' / 'mod.py') == expected


def _lineage_freeze(root, **overrides):
    freeze = {
        'schema_version': CONTACT_FREEZE_SCHEMA,
        'status': FREEZE_STATUS,
        'frozen_at': _now_iso(),
        'code_commit': git_head(root),
        'worktree_state': worktree_state(root),
    }
    freeze.update(overrides)
    return freeze


def test_check_freeze_lineage_accepts_current_state(git_repo):
    assert check_freeze_lineage(_lineage_freeze(git_repo), _now_iso(),
                                git_repo) is None


def test_check_freeze_lineage_rejects_future_and_backdated(git_repo):
    freeze = _lineage_freeze(git_repo, frozen_at=_now_iso(300))
    with pytest.raises(ContactPlanError, match='FROZEN_AT_IN_FUTURE'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)
    with pytest.raises(ContactPlanError, match='FROZEN_AT_IN_FUTURE'):
        check_freeze_lineage(_lineage_freeze(git_repo), _now_iso(-3600), git_repo)


def test_check_freeze_lineage_rejects_head_and_worktree_changes(git_repo):
    freeze = _lineage_freeze(git_repo, code_commit='0' * 40)
    with pytest.raises(ContactPlanError, match='CODE_COMMIT_MISMATCH'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)
    freeze = _lineage_freeze(git_repo)
    (git_repo / 'src' / 'mod.py').write_text('VALUE = 3\n', encoding='utf-8')
    with pytest.raises(ContactPlanError, match='WORKTREE_STATE_MISMATCH'):
        check_freeze_lineage(freeze, _now_iso(), git_repo)


def test_check_freeze_lineage_rejects_bad_status_schema_and_naive_now(git_repo):
    with pytest.raises(ContactPlanError, match='FREEZE_STATUS_INVALID'):
        check_freeze_lineage(_lineage_freeze(git_repo, status='FROZEN'),
                             _now_iso(), git_repo)
    broken = _lineage_freeze(git_repo)
    broken['schema_version'] = 'boom_birds.contact_verification_freeze.v0'
    with pytest.raises(ContactPlanError, match='SCHEMA_VERSION_MISMATCH'):
        check_freeze_lineage(broken, _now_iso(), git_repo)
    with pytest.raises(ContactPlanError, match='TIMEZONE_REQUIRED'):
        check_freeze_lineage(_lineage_freeze(git_repo),
                             '2026-11-02T12:00:00', git_repo)


# ---------------------------------------------------------------------------
# generator CLI
# ---------------------------------------------------------------------------

SCRIPT = ROOT / 'scripts' / 'make_contact_verification_freeze.py'


@pytest.fixture()
def freeze_script(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'make_contact_verification_freeze_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_contract = SimpleNamespace(
        asset_id='rmuc2027-isaacsim-20261028',
        terrain_sha256=TERRAIN_SHA,
        preview_sha256=PREVIEW_SHA,
        bounds_min_m=(-14.0, -8.0, -0.3),
        bounds_max_m=(14.0, 8.0, 3.5),
    )
    # Avoid hashing the 90 MB terrain in unit tests; real map config files are
    # still resolved for their own sha256.
    monkeypatch.setattr(module, 'load_map_contract',
                        lambda *args, **kwargs: fake_contract)
    return module


@pytest.fixture()
def script_inputs(tmp_path):
    payload = _cases_payload(tmp_path)
    cases_path = tmp_path / 'contact_verification_cases_v1.json'
    cases_path.write_text(json.dumps(payload, ensure_ascii=False) + '\n',
                          encoding='utf-8')
    expected_path = tmp_path / 'contact_verification_expected_v1.json'
    expected_path.write_text(
        json.dumps(_expected_payload(payload), ensure_ascii=False) + '\n',
        encoding='utf-8')
    return {
        'cases': cases_path,
        'expected': expected_path,
        'output': tmp_path / 'contact_verification_freeze_v1.json',
    }


def _script_args(inputs):
    return ['--cases', str(inputs['cases']),
            '--expected', str(inputs['expected']),
            '--output', str(inputs['output'])]


def test_script_dry_run_prints_json_and_writes_nothing(freeze_script,
                                                       script_inputs, capsys):
    args = ['--dry-run'] + _script_args(script_inputs)
    assert freeze_script.main(args) == 0
    assert not script_inputs['output'].exists()
    freeze = json.loads(capsys.readouterr().out)
    assert freeze['schema_version'] == CONTACT_FREEZE_SCHEMA
    assert freeze['status'] == FREEZE_STATUS
    assert list(freeze['segments']) == list(SEGMENT_IDS)
    assert freeze['budget']['total_episodes'] == 11
    assert freeze['code_commit'] == git_head(ROOT)
    frozen_at = datetime.fromisoformat(freeze['frozen_at'])
    assert frozen_at.tzinfo is not None
    assert frozen_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert freeze['segments']['replay_contact_inferred']['role'] == 'replay'
    assert freeze['support_scope']['replay_sources']


def test_script_refuses_to_overwrite_existing_output(freeze_script,
                                                     script_inputs, capsys):
    script_inputs['output'].write_text('{"marker": "keep"}\n',
                                       encoding='utf-8')
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
    captured = capsys.readouterr().out
    for segment_id in SEGMENT_IDS:
        assert 'SEGMENT ' + segment_id in captured
    assert 'REPLAY replay_contact_inferred' in captured
    assert 'BUDGET total_episodes=11' in captured
    assert freeze_script.main(_script_args(script_inputs)) == 2
    assert out.read_bytes() == first_bytes


def test_script_reports_missing_cases_file(freeze_script, script_inputs,
                                           capsys):
    script_inputs['cases'].unlink()
    assert freeze_script.main(_script_args(script_inputs)) == 1
    error = capsys.readouterr().err
    assert 'cases 文件 不存在' in error or 'cases 文件不存在' in error
    assert not script_inputs['output'].exists()


def test_script_reports_missing_expected_file(freeze_script, script_inputs,
                                              capsys):
    script_inputs['expected'].unlink()
    assert freeze_script.main(_script_args(script_inputs)) == 1
    error = capsys.readouterr().err
    assert 'expected 文件 不存在' in error or 'expected 文件不存在' in error


def test_script_rejects_missing_replay_reference(freeze_script, script_inputs,
                                                 capsys):
    payload = json.loads(script_inputs['cases'].read_text(encoding='utf-8'))
    _mutate_replay_previous_dir(
        payload, 4,
        str(script_inputs['cases'].parent / 'missing_previous_run'))
    script_inputs['cases'].write_text(
        json.dumps(payload, ensure_ascii=False) + '\n', encoding='utf-8')
    assert freeze_script.main(_script_args(script_inputs)) == 1
    assert 'REPLAY_PREVIOUS_RUN_MISSING' in capsys.readouterr().err
