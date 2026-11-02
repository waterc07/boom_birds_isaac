"""Tests for scripts/verify_contact_verification_runs.py.

The fixture builds a signed synthetic run for the five contact-verification
segment roles (wall / obstacle / clearance / geometry / replay) using the real
``contact_contract`` and ``body_envelope`` builders, so the positive fixture is
contract-valid and each negative test tampers exactly one documented field to
prove that the corresponding independent check fires.

Covered branches:

* data integrity: manifest/freeze lineage and hashes, GUI evidence, episode
  identity/denominator, step↔physics timing, EpisodeBoundary, artifact hashes;
* contact contract: independent classification, units/threshold, invalid sensor
  vs valid zero, attribution fabrication/inventory, geometry promotion, impulse
  unit, net-vs-per-prim, episode contact-summary recomputation;
* envelope geometry: around-origin radius recompute, coverage vs prim inventory,
  non-mesh limitations, legacy clearance delta (INFO);
* scenario expectation: wall/obstacle/clearance/geometry role rules, must
  conditions, acceptable outcomes, replay verdicts with basis;
* performance boundary aggregates.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'verify_contact_verification_runs.py'


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'verify_contact_verification_ut', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()
CC = MODULE.contact_contract
BE = MODULE.body_envelope

ROBOT = '/World/envs/env_0/Robot'
ROBOT_COLLISION = (ROBOT + '/body', ROBOT + '/m1/body')
WALL = '/World/envs/env_0/Wall'
OBSTACLE = '/World/envs/env_0/Obstacle'
HALF = (0.05454223374277353, 0.03820826672017574, 0.013588040310423821)
OFFSET = (0.012, -0.007, 0.004)
HALF_DIAGONAL = math.sqrt(sum(value * value for value in HALF))
ORIGIN_RADIUS = math.sqrt(sum((abs(OFFSET[index]) + HALF[index]) ** 2
                              for index in range(3)))
PHYSICS_DT = 0.005
DECIMATION = 4
CONTROL_DT = PHYSICS_DT * DECIMATION
CODE_COMMIT = 'a' * 40
FROZEN_AT = '2026-11-02T10:00:00+00:00'
STARTED_AT = '2026-11-02T10:10:00+00:00'
CASE_IDS = {
    'wall': 'case_wall_0',
    'obstacle': 'case_obstacle_0',
    'clearance': 'case_clearance_0',
    'geometry': 'case_geometry_0',
    'replay': 'case_replay_0',
}
PHYSICAL = {
    'wall': MODULE.PHYSX_FORCE_MEASURED,
    'obstacle': MODULE.FORCE_MEASURED_UNATTRIBUTED,
    'clearance': MODULE.NO_CONTACT,
    'geometry': MODULE.GEOMETRY_OVERLAP_ONLY,
    'replay': MODULE.PHYSX_FORCE_MEASURED,
}
ACCEPTABLE = {role: [physical] for role, physical in PHYSICAL.items()}
MUST = {
    'wall': ['sensor_available_true', 'event_true',
             'force_measured_gt_0.02_n',
             {'kind': 'attribution_prim_in', 'value': WALL}],
    'obstacle': ['sensor_available_true', 'event_true_or_force_available',
                 'not_geometry_only'],
    'clearance': ['sensor_available_true', 'event_false',
                  'force_available_with_valid_zero',
                  'geometry_overlap_le_0.02_m'],
    'geometry': ['sensor_available_true', 'event_false',
                 'force_available_with_valid_zero',
                 'geometry_overlap_gt_0.02_m', 'not_physx_force'],
    'replay': ['replay_verdict_recorded', 'replay_basis_from_raw_contact_record'],
}


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')


def _write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _read_jsonl(path):
    return [json.loads(line) for line in
            Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def _build_contact_records(role):
    records = []
    for index in range(3):
        step = index
        time_s = round((index + 1) * CONTROL_DT, 9)
        common = dict(step=step, time_s=time_s, sensor_available=True,
                      event_available=True, force_window_s=0.05)
        if role in ('wall', 'replay'):
            records.append(CC.build_contact_record(
                **common, sensor_status='available', event=True,
                prim_attributions=[WALL],
                force_per_prim_n={WALL: [0.2, 0.0, 0.0]}))
        elif role == 'obstacle':
            records.append(CC.build_contact_record(
                **common,
                sensor_status='filtered_unavailable_net_force_available',
                event=True, prim_attributions=[], net_force_n=[0.3, 0.0, 0.0]))
        elif role == 'clearance':
            records.append(CC.build_contact_record(
                **common, sensor_status='available', event=False,
                prim_attributions=[],
                force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]}))
        elif role == 'geometry':
            records.append(CC.build_contact_record(
                **common, sensor_status='available', event=False,
                prim_attributions=[],
                force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]},
                geometry=0.05))
        else:
            raise AssertionError('unknown role ' + role)
    return records


def _body_envelope_record():
    coverage = BE.EnvelopeCoverage(
        source=BE.ENVELOPE_SOURCE_COLLISION_GEOMETRY,
        collision_prim_paths=ROBOT_COLLISION,
        sub_bodies=('body', 'm1'),
        limitations=('collision prim paths resolved via '
                     'UsdPhysics.CollisionAPI',))
    return BE.body_envelope_record(
        half_extents_m=HALF, center_offset_m=OFFSET, coverage=coverage,
        measurement={'robot_root_prim': ROBOT,
                     'frame': 'robot_reference_frame',
                     'bbox_cache_purpose': ['default']})


def _prim_inventory():
    return {
        'robot': [
            {'path': path, 'collision': True, 'rigid_body': True,
             'contact_report': True}
            for path in ROBOT_COLLISION],
        'obstacle': [
            {'path': OBSTACLE, 'collision': True, 'rigid_body': True,
             'contact_report': True}],
        'map': [
            {'path': WALL, 'collision': True, 'rigid_body': False,
             'contact_report': True}],
    }


def _run_plan(role, case_id):
    return {'segment_id': role, 'role': role, 'case_ids': [case_id],
            'repeats': 1}


def _contact_sensor():
    return {
        'available': True,
        'mode': 'filtered_per_prim_with_net_force_fallback',
        'prim_paths': [ROBOT],
        'filter_prim_paths': [OBSTACLE],
        'update_order': 'physics_step_then_control_step',
        'physics': {'physics_dt_s': PHYSICS_DT, 'decimation': DECIMATION,
                    'substeps_per_step': 1},
    }


def _steps(segment_id, episode_id, records):
    rows = []
    for index, record in enumerate(records):
        record = dict(record)
        record['step'] = index
        record['time_s'] = round((index + 1) * CONTROL_DT, 9)
        geometry = record['layers']['geometry']
        overlap = geometry.get('sphere_overlap_m') if geometry.get(
            'available') else 0.0
        rows.append({
            'episode_id': episode_id,
            'step': index,
            'time_s': round((index + 1) * CONTROL_DT, 9),
            'physics_step': (index + 1) * DECIMATION,
            'position_world_m': [float(index), 0.0, 1.0],
            'velocity_world_mps': [0.1, 0.0, 0.0],
            'speed_mps': 0.1,
            'contact_record': record,
            'geometry_overlap_sphere_m': float(overlap or 0.0),
            'obstacle_position_world_m': [float(index) + 1.0, 0.0, 1.0],
            'phase': 'RUN',
        })
    return rows


def _episode(role, episode_id, records):
    episode = {
        'episode_id': episode_id,
        'case_id': CASE_IDS[role],
        'mode': 'measured',
        'outcome': PHYSICAL[role],
        'business_outcome': PHYSICAL[role],
        'physical_outcome': PHYSICAL[role],
        'contact_summary': CC.summarize_contact_records(records),
        'envelope_sphere_about_origin_m': ORIGIN_RADIUS,
    }
    if role == 'replay':
        episode['replay'] = {
            'source_run': 'outputs/map_eval/contact_previous',
            'source_episode_id': 'previous_episode_0',
            'previous_physical_label': MODULE.NO_CONTACT,
            'verdict': 'MISREPORT',
            'basis': 'raw contact record shows a measured force while the '
                     'previous label was NO_CONTACT',
        }
    return episode


def _expected_payload():
    segments = {}
    for role in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
        segments[role] = {
            'role': role,
            'cases': [CASE_IDS[role]],
            'expected_episodes': 1,
        }
    cases = {}
    for role in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
        case = {
            'segment_id': role,
            'mode': role,
            'acceptable_physical': ACCEPTABLE[role],
            'must_conditions': MUST[role],
            'unsupported_allowed': role in ('wall', 'obstacle', 'replay'),
            'note': 'synthetic fixture',
        }
        cases[CASE_IDS[role]] = case
        # The actual expected file keys the segment-level expectation by the
        # segment id; keep that shape too for the replay segment.
        cases.setdefault(role, case)
    return {
        'schema_version': MODULE.CONTACT_EXPECTED_SCHEMA,
        'status': 'EXPECTED_NOT_CONCLUSION',
        'contact_contract_version': CC.CONTACT_EVIDENCE_SCHEMA_ID,
        'envelope_contract_version': BE.BODY_ENVELOPE_SCHEMA_VERSION,
        'cases': cases,
        'replay_verdicts': {
            CASE_IDS['replay']: {
                'previous_physical_label': MODULE.NO_CONTACT,
                'allowed': ['CONSISTENT', 'MISREPORT', 'MISS', 'UNDECIDABLE'],
                'rule': 'fixture rule: compare replay evidence with the previous '
                        'label',
            },
        },
        'segments': segments,
    }


def _freeze_payload(expected_path, cases_path):
    segments = {}
    for role in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
        segments[role] = {
            'segment_id': role,
            'role': role,
            'case_ids': [CASE_IDS[role]],
            'repeats': 1,
            'run_plan': _run_plan(role, CASE_IDS[role]),
        }
    return {
        'schema_version': MODULE.CONTACT_FREEZE_SCHEMA,
        'status': 'PRE_RUN_FROZEN',
        'frozen_at': FROZEN_AT,
        'code_commit': CODE_COMMIT,
        'worktree_state': {'tracked_paths': [], 'status_text_sha256': 'b' * 64,
                           'clean': True},
        'cases_file': str(cases_path),
        'cases_sha256': _sha(cases_path),
        'expected_file': str(expected_path),
        'expected_sha256': _sha(expected_path),
        'segments': segments,
    }


def _manifest(role, freeze_path, episode_id):
    return {
        'schema_version': MODULE.CONTACT_MANIFEST_SCHEMA,
        'evaluation_version': 'boom_birds.contact_verification.v1',
        'code_commit': CODE_COMMIT,
        'working_tree': 'fixture',
        'gui_mode': True,
        'renderer': 'DirectX (--/app/vulkan=false)',
        'started_at': STARTED_AT,
        'segment_id': role,
        'role': role,
        'cases_file': 'fixture_cases.json',
        'cases_sha256': 'c' * 64,
        'episode_ids': [episode_id],
        'run_plan': _run_plan(role, CASE_IDS[role]),
        'contact_contract_version': CC.CONTACT_EVIDENCE_SCHEMA_ID,
        'envelope_contract_version': BE.BODY_ENVELOPE_SCHEMA_VERSION,
        'contact_sensor': _contact_sensor(),
        'body_envelope': _body_envelope_record(),
        'prim_inventory': _prim_inventory(),
        'episode_boundary': {'started_from_reset': True,
                             'no_silent_reset': True},
        'freeze': {'path': str(freeze_path), 'sha256': _sha(freeze_path)},
        'outputs_sha256': {},
    }


def build_fixture(tmp_path):
    tmp_path = Path(tmp_path)
    cases_path = tmp_path / 'fixture_cases.json'
    _write_json(cases_path, {'schema_version': 'fixture.cases.v1',
                             'cases': list(CASE_IDS.values())})
    expected = _expected_payload()
    expected_path = tmp_path / 'fixture_expected.json'
    _write_json(expected_path, expected)
    freeze = _freeze_payload(expected_path, cases_path)
    freeze_path = tmp_path / 'fixture_freeze.json'
    _write_json(freeze_path, freeze)
    fixture = {
        'tmp': tmp_path,
        'cases': cases_path,
        'expected': expected_path,
        'freeze': freeze_path,
        'freeze_payload': freeze,
        'runs': {},
        'manifests': {},
        'episodes': {},
        'steps': {},
    }
    for role in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
        run_dir = tmp_path / ('run_' + role)
        (run_dir / 'screenshots').mkdir(parents=True)
        records = _build_contact_records(role)
        episode_id = CASE_IDS[role] + '-supervisor'
        episode = _episode(role, episode_id, records)
        steps = _steps(role, episode_id, records)
        manifest = _manifest(role, freeze_path, episode_id)
        manifest['cases_file'] = str(cases_path)
        manifest['cases_sha256'] = _sha(cases_path)
        _write_json(run_dir / 'manifest.json', manifest)
        _write_jsonl(run_dir / 'episodes.jsonl', [episode])
        _write_jsonl(run_dir / 'steps.jsonl', steps)
        manifest['outputs_sha256'] = {
            'episodes.jsonl': _sha(run_dir / 'episodes.jsonl'),
            'steps.jsonl': _sha(run_dir / 'steps.jsonl'),
        }
        _write_json(run_dir / 'manifest.json', manifest)
        _write_json(run_dir / 'summary.json', {'status': 'PASS'})
        fixture['runs'][role] = run_dir
        fixture['manifests'][role] = manifest
        fixture['episodes'][role] = episode
        fixture['steps'][role] = steps
    return fixture


def run_verify(fixture):
    parser = MODULE.build_parser()
    args = parser.parse_args([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--repo-root', str(fixture['tmp']),
    ] + [item for role in ('wall', 'obstacle', 'clearance', 'geometry',
                           'replay')
         for item in ('--run', '%s=%s' % (role, fixture['runs'][role]))])
    return MODULE.run_verification(args, parser)


def _check(result, category, name):
    return result['checks'][category][name]


def _mutate_manifest(fixture, role, mutate):
    path = fixture['runs'][role] / 'manifest.json'
    manifest = _read_json(path)
    mutate(manifest)
    _write_json(path, manifest)


def _mutate_episodes(fixture, role, mutate):
    path = fixture['runs'][role] / 'episodes.jsonl'
    episodes = _read_jsonl(path)
    mutate(episodes)
    _write_jsonl(path, episodes)
    _refresh_outputs(fixture, role)


def _mutate_steps(fixture, role, mutate):
    path = fixture['runs'][role] / 'steps.jsonl'
    steps = _read_jsonl(path)
    mutate(steps)
    _write_jsonl(path, steps)
    _refresh_outputs(fixture, role)


def _refresh_outputs(fixture, role):
    run_dir = fixture['runs'][role]
    manifest_path = run_dir / 'manifest.json'
    manifest = _read_json(manifest_path)
    manifest['outputs_sha256'] = {
        'episodes.jsonl': _sha(run_dir / 'episodes.jsonl'),
        'steps.jsonl': _sha(run_dir / 'steps.jsonl')}
    _write_json(manifest_path, manifest)


# ---------------------------------------------------------------------------
# positive fixture
# ---------------------------------------------------------------------------

def test_positive_fixture_passes(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])
    assert result['failures'] == []
    assert result['deviations'] == []
    assert result['missing_fields'] == []
    assert set(result['checks']) == set(MODULE.CATEGORIES)
    for category, checks in result['checks'].items():
        for name, entry in checks.items():
            assert entry['passed'] is True, (category, name, entry)
            assert entry['category'] == category


def test_positive_output_contract_and_segments(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    assert result['lineage']['schema_version'] == MODULE.CONTACT_FREEZE_SCHEMA
    assert result['recomputed']['contracts']['contact'] \
        == CC.CONTACT_EVIDENCE_SCHEMA_ID
    assert result['recomputed']['contracts']['envelope'] \
        == BE.BODY_ENVELOPE_SCHEMA_VERSION
    assert set(result['segments']) == set(PHYSICAL)
    assert result['segments']['wall']['role'] == 'wall'
    assert result['recomputed']['performance']['wall'][
        'contact_event_steps'] == 3
    assert result['recomputed']['performance']['clearance'][
        'valid_zero_steps'] == 3


def test_positive_checks_cover_all_categories_and_names(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    present = {name for checks in result['checks'].values()
               for name in checks}
    assert present == set(MODULE.CHECK_NAMES)


# ---------------------------------------------------------------------------
# data integrity
# ---------------------------------------------------------------------------

def test_missing_manifest_field_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall', lambda m: m.pop('prim_inventory'))
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('prim_inventory' in item for item in result['missing_fields'])


def test_missing_expected_file_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    fixture['expected'].unlink()
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('expected' in item for item in result['missing_fields'])


def test_missing_run_dir_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    parser = MODULE.build_parser()
    args = parser.parse_args([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--run', 'wall=%s' % fixture['runs']['wall'],
    ])
    result = MODULE.run_verification(args, parser)
    assert result['status'] == 'INCOMPLETE'
    assert any('run directory for segment' in item
               for item in result['missing_fields'])


def test_freeze_schema_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    freeze = _read_json(fixture['freeze'])
    freeze['schema_version'] = 'boom_birds.contact_verification_freeze.v0'
    _write_json(fixture['freeze'], freeze)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'freeze_lineage')['passed'] is False


def test_freeze_sha_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall',
                     lambda m: m['freeze'].__setitem__('sha256', '0' * 64))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'freeze_lineage')['passed'] is False


def test_freeze_after_started_at_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall',
                     lambda m: m.__setitem__('started_at',
                                             '2026-11-02T09:00:00+00:00'))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'freeze_lineage')['passed'] is False


def test_gui_renderer_must_be_directx(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall',
                     lambda m: m.__setitem__('renderer', 'Vulkan'))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'gui_evidence')['passed'] is False


def test_screenshots_directory_is_required(tmp_path):
    fixture = build_fixture(tmp_path)
    (fixture['runs']['wall'] / 'screenshots').rmdir()
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('screenshots' in item for item in result['missing_fields'])


def test_duplicate_episode_ids_fail(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        manifest['episode_ids'] = manifest['episode_ids'] * 2

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity',
                  'episode_identity_and_denominator')['passed'] is False


def test_denominator_case_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        manifest['run_plan']['case_ids'] = ['case_wall_0', 'case_wall_1']

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity',
                  'episode_identity_and_denominator')['passed'] is False


def test_step_time_must_be_monotonic(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[1]['time_s'] = steps[0]['time_s']

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity',
                  'step_physics_timing')['passed'] is False


def test_physics_step_must_match_decimation(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[1]['physics_step'] = 5

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity',
                  'step_physics_timing')['passed'] is False


def test_episode_boundary_must_be_clean(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall', lambda m: m['episode_boundary']
                     .__setitem__('no_silent_reset', False))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'episode_boundary')['passed'] \
        is False


def test_artifact_hash_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)
    path = fixture['runs']['wall'] / 'steps.jsonl'
    steps = _read_jsonl(path)
    steps[0]['speed_mps'] = 0.2
    _write_jsonl(path, steps)  # deliberately no manifest hash refresh
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'data_integrity', 'artifact_hashes')['passed'] \
        is False


# ---------------------------------------------------------------------------
# contact contract
# ---------------------------------------------------------------------------

def test_tampered_classification_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[0]['contact_record']['classification'] = MODULE.NO_CONTACT

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_classification')['passed'] is False


def test_force_unit_tamper_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[0]['contact_record']['layers']['force']['unit'] = 'N*s'

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_units_and_threshold')['passed'] is False


def test_impulse_unit_tamper_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[0]['contact_record']['layers']['impulse']['unit'] = 'N'

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_units_and_threshold')['passed'] is False


def test_event_source_enum_must_be_known(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[0]['contact_record']['layers']['event']['source'] = 'magic'

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_units_and_threshold')['passed'] is False


def test_sensor_unavailable_with_zero_force_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = steps[0]['contact_record']
        record['sensor']['available'] = False

    _mutate_steps(fixture, 'clearance', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'sensor_invalid_vs_valid_zero')['passed'] is False


def test_sensor_unavailable_with_numeric_force_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = steps[0]['contact_record']
        record['sensor']['available'] = False
        record['layers']['force']['magnitude_n'] = 0.4

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'sensor_invalid_vs_valid_zero')['passed'] is False


def test_fabricated_attribution_paths_fail(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['contact_summary']['attributed_steps'] = 3

    _mutate_episodes(fixture, 'obstacle', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_summary_recompute')['passed'] is False


def test_attribution_path_must_be_in_inventory(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = CC.build_contact_record(
            step=steps[0]['step'], time_s=steps[0]['time_s'],
            sensor_available=True, sensor_status='available',
            event_available=True, event=True,
            prim_attributions=['/World/envs/env_0/Ghost'],
            force_per_prim_n={'/World/envs/env_0/Ghost': [0.3, 0.0, 0.0]},
            force_window_s=0.05)
        steps[0]['contact_record'] = record

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'attribution_contract')['passed'] is False


def test_unattributed_must_not_fabricate_prims(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = steps[0]['contact_record']
        record['layers']['attribution']['prim_paths'] = [WALL]

    _mutate_steps(fixture, 'obstacle', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'attribution_contract')['passed'] is False


def test_net_force_must_not_be_stored_as_per_prim(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = steps[0]['contact_record']
        record['layers']['force']['per_prim_n'] = {OBSTACLE: [0.3, 0.0, 0.0]}

    _mutate_steps(fixture, 'obstacle', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'net_vs_per_prim')['passed'] is False


def test_geometry_event_promotion_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = steps[0]['contact_record']
        record['layers']['event']['event'] = True

    _mutate_steps(fixture, 'geometry', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'geometry_never_promoted')['passed'] is False


def test_contact_summary_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['contact_summary']['total_steps'] = 99

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_summary_recompute')['passed'] is False


def test_contact_record_step_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        steps[0]['contact_record']['step'] = 99

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_record_schema')['passed'] is False


def test_missing_contact_record_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        del steps[0]['contact_record']

    _mutate_steps(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('contact_record' in item for item in result['missing_fields'])


def test_threshold_equality_is_not_force_measured(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        record = CC.build_contact_record(
            step=steps[0]['step'], time_s=steps[0]['time_s'],
            sensor_available=True, sensor_status='available',
            event_available=True, event=False, prim_attributions=[],
            net_force_n=CC.CONTACT_FORCE_THRESHOLD_N, force_window_s=0.05)
        record['classification'] = CC.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED
        steps[0]['contact_record'] = record

    _mutate_steps(fixture, 'obstacle', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'contact_contract',
                  'contact_units_and_threshold')['passed'] is False


# ---------------------------------------------------------------------------
# envelope geometry
# ---------------------------------------------------------------------------

def test_underestimated_origin_radius_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        record = manifest['body_envelope']
        record['sphere_about_origin']['radius_m'] = HALF_DIAGONAL
        record['production']['radius_m'] = HALF_DIAGONAL

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'envelope_geometry',
                  'envelope_radius_recompute')['passed'] is False


def test_episode_envelope_radius_mismatch_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['envelope_sphere_about_origin_m'] = HALF_DIAGONAL

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'envelope_geometry',
                  'envelope_radius_recompute')['passed'] is False


def test_coverage_collision_paths_must_match_inventory(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        manifest['prim_inventory']['robot'] = [
            {'path': ROBOT + '/other', 'collision': True,
             'rigid_body': True, 'contact_report': True}]

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'envelope_geometry',
                  'envelope_coverage_inventory')['passed'] is False


def test_coverage_prim_outside_inventory_fails(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        manifest['body_envelope']['coverage']['prim_paths'].append(
            '/World/envs/env_0/Ghost')

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'envelope_geometry',
                  'envelope_coverage_inventory')['passed'] is False


def test_envelope_limitations_required(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(manifest):
        manifest['body_envelope']['limitations'] = []

    _mutate_manifest(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert _check(result, 'envelope_geometry',
                  'envelope_limitations')['passed'] is False


def test_legacy_delta_must_be_recorded(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['legacy_clearance_radius_m'] = HALF_DIAGONAL

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('envelope_legacy_delta_m' in item
               for item in result['missing_fields'])


def test_legacy_delta_recorded_is_info_not_failure(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['legacy_clearance_radius_m'] = HALF_DIAGONAL
        episodes[0]['envelope_legacy_delta_m'] = ORIGIN_RADIUS - HALF_DIAGONAL

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'])
    assert _check(result, 'envelope_geometry',
                  'envelope_legacy_delta')['passed'] is True
    assert result['recomputed']['segments']['wall']['role'] == 'wall'


# ---------------------------------------------------------------------------
# scenario expectation
# ---------------------------------------------------------------------------

def test_wall_requires_measured_force(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['physical_outcome'] = MODULE.GEOMETRY_OVERLAP_ONLY

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    assert any(item['kind'] == 'wall_force_measured_expected'
               for item in result['deviations'])


def test_obstacle_only_geometry_is_rejected(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        for row in steps:
            record = CC.build_contact_record(
                step=row['step'], time_s=row['time_s'],
                sensor_available=True, sensor_status='available',
                event_available=True, event=False, prim_attributions=[],
                force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]},
                geometry=0.05)
            row['contact_record'] = record
            row['geometry_overlap_sphere_m'] = 0.05

    def mutate_episode(episodes):
        episodes[0]['physical_outcome'] = MODULE.GEOMETRY_OVERLAP_ONLY

    _mutate_steps(fixture, 'obstacle', mutate)
    _mutate_episodes(fixture, 'obstacle', mutate_episode)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'obstacle_requires_physx_evidence' in kinds


def test_clearance_requires_available_sensor(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        for row in steps:
            record = CC.build_contact_record(
                step=row['step'], time_s=row['time_s'],
                sensor_available=False, sensor_status='unavailable',
                event_available=False, event=None, prim_attributions=[],
                force_per_prim_n=None, geometry=None)
            row['contact_record'] = record

    _mutate_steps(fixture, 'clearance', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'clearance_sensor_unavailable' in kinds


def test_geometry_overlap_must_exceed_threshold(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        for row in steps:
            record = CC.build_contact_record(
                step=row['step'], time_s=row['time_s'],
                sensor_available=True, sensor_status='available',
                event_available=True, event=False, prim_attributions=[],
                force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]},
                geometry=0.01)
            row['contact_record'] = record
            row['geometry_overlap_sphere_m'] = 0.01

    _mutate_steps(fixture, 'geometry', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'geometry_overlap_missing' in kinds


def test_acceptable_physical_outcome_mismatch(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['physical_outcome'] = MODULE.UNKNOWN

    _mutate_episodes(fixture, 'clearance', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'physical_outcome_not_acceptable' in kinds


def test_must_condition_failure(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(steps):
        for row in steps:
            record = CC.build_contact_record(
                step=row['step'], time_s=row['time_s'],
                sensor_available=True, sensor_status='available',
                event_available=True, event=True, prim_attributions=[WALL],
                force_per_prim_n={WALL: [0.3, 0.0, 0.0]},
                geometry=None)
            row['contact_record'] = record

    _mutate_steps(fixture, 'clearance', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'must_condition_failed' in kinds


def test_replay_verdict_outside_allowed_set_is_a_deviation(tmp_path):
    fixture = build_fixture(tmp_path)
    expected = _read_json(fixture['expected'])
    expected['replay_verdicts'][CASE_IDS['replay']]['allowed'] = ['CONSISTENT']
    _write_json(fixture['expected'], expected)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'replay_verdict_mismatch' in kinds


def test_replay_previous_label_must_match_expected(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['replay']['previous_physical_label'] = \
            MODULE.PHYSX_FORCE_MEASURED

    _mutate_episodes(fixture, 'replay', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'replay_previous_label_mismatch' in kinds


def test_replay_verdict_and_basis_must_be_recorded(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['replay'].pop('verdict', None)
        episodes[0]['replay'].pop('basis', None)

    _mutate_episodes(fixture, 'replay', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'
    kinds = {item['kind'] for item in result['deviations']}
    assert 'must_condition_failed' in kinds


def test_physical_outcome_alias_is_accepted(tmp_path):
    fixture = build_fixture(tmp_path)

    def mutate(episodes):
        episodes[0]['physical_outcome'] = 'PHYSX_CONTACT_FORCE_MEASURED'

    _mutate_episodes(fixture, 'wall', mutate)
    result = run_verify(fixture)
    assert result['status'] == 'PASS', (
        result['missing_fields'], result['failures'], result['deviations'])


def test_unknown_must_condition_kind_is_incomplete(tmp_path):
    fixture = build_fixture(tmp_path)
    expected = _read_json(fixture['expected'])
    expected['cases'][CASE_IDS['wall']]['must_conditions'].append(
        'mystery_kind')
    _write_json(fixture['expected'], expected)
    result = run_verify(fixture)
    assert result['status'] == 'INCOMPLETE'
    assert any('must_conditions kind' in item
               for item in result['missing_fields'])


ACTUAL_EXPECTED = (ROOT / 'configs' / 'scenarios'
                   / 'contact_verification_expected_v1.json')


@pytest.mark.skipif(not ACTUAL_EXPECTED.is_file(),
                    reason='pre-frozen expected file not present')
def test_actual_expected_file_shape_is_supported():
    """Compatibility with the Lead's actual expected file (aliases + kinds)."""
    payload = _read_json(ACTUAL_EXPECTED)
    index = MODULE.ExpectedIndex()
    index.add_payload(payload)
    seen_cases = 0
    for segment_id, node in payload['segments'].items():
        for case_id in node['cases']:
            spec = index.lookup(segment_id, case_id)
            assert spec is not None, (segment_id, case_id)
            assert MODULE._acceptable_outcomes(spec), (segment_id, case_id)
            for condition in spec.get('must_conditions') or []:
                kind, _value = MODULE._parse_condition(condition)
                assert kind in MODULE.MUST_CONDITION_KINDS, (case_id, kind)
            if node.get('role') == 'replay':
                assert spec.get('replay_allowed')
                assert spec.get('replay_previous_label') is not None
            seen_cases += 1
    assert seen_cases >= 9


class _StubEvidence:
    def __init__(self, segment_id, manifest, episodes):
        self.segment_id = segment_id
        self.manifest = manifest
        self.episodes = episodes
        self.run_dir = Path('.')


def _denominator_result(manifest, episodes, freeze_segments):
    verifier = MODULE.Verifier()
    evidence = _StubEvidence('contact_A_wall', manifest, episodes)
    freeze = {'segments': freeze_segments}
    MODULE.check_episode_identity(evidence, freeze, verifier)
    return verifier


def test_denominator_unique_cases_with_repeats():
    manifest = {'episode_ids': ['ep0', 'ep1'],
                'run_plan': {'case_ids': ['case_A']}}
    episodes = [{'episode_id': 'ep0', 'case_id': 'case_A'},
                {'episode_id': 'ep1', 'case_id': 'case_A'}]
    freeze = {'contact_A_wall': {'repeats': 2, 'expected_episodes': 2}}
    verifier = _denominator_result(manifest, episodes, freeze)
    assert verifier.checks['data_integrity'][
        'episode_identity_and_denominator']['passed'] is True


def test_denominator_repeated_case_ids_with_expected_episodes():
    manifest = {'episode_ids': ['ep0', 'ep1'],
                'run_plan': {'case_ids': ['case_A', 'case_A']}}
    episodes = [{'episode_id': 'ep0', 'case_id': 'case_A'},
                {'episode_id': 'ep1', 'case_id': 'case_A'}]
    freeze = {'contact_A_wall': {'repeats': 1, 'episodes': 2}}
    verifier = _denominator_result(manifest, episodes, freeze)
    assert verifier.checks['data_integrity'][
        'episode_identity_and_denominator']['passed'] is True


# ---------------------------------------------------------------------------
# performance and CLI
# ---------------------------------------------------------------------------

def test_performance_statistics_are_independent(tmp_path):
    fixture = build_fixture(tmp_path)
    result = run_verify(fixture)
    performance = result['recomputed']['performance']
    assert set(performance) == set(PHYSICAL)
    for role, stats in performance.items():
        assert stats['total_steps'] == 3
        assert stats['episodes'][0]['episode_id']
    assert performance['wall']['max_force_n'] > 0.02
    assert performance['geometry']['geometry_only_steps'] == 3
    assert performance['obstacle']['attributed_steps'] == 0
    assert performance['clearance']['valid_zero_steps'] == 3


def test_main_writes_output_json(tmp_path):
    fixture = build_fixture(tmp_path)
    output = tmp_path / 'report' / 'verify.json'
    exit_code = MODULE.main([
        '--freeze', str(fixture['freeze']),
        '--expected', str(fixture['expected']),
        '--repo-root', str(fixture['tmp']),
        '--output', str(output),
    ] + [item for role in ('wall', 'obstacle', 'clearance', 'geometry',
                           'replay')
         for item in ('--run', '%s=%s' % (role, fixture['runs'][role]))])
    assert exit_code == 0
    payload = _read_json(output)
    assert payload['status'] == 'PASS'
    assert set(payload) >= {'status', 'checks', 'failures', 'deviations',
                            'missing_fields', 'checks_by_category',
                            'recomputed', 'segments', 'lineage'}


def test_fail_exit_code(tmp_path):
    fixture = build_fixture(tmp_path)
    _mutate_manifest(fixture, 'wall',
                     lambda m: m.__setitem__('renderer', 'Vulkan'))
    result = run_verify(fixture)
    assert result['status'] == 'FAIL'


def test_cli_rejects_malformed_run_spec(tmp_path):
    parser = MODULE.build_parser()
    args = parser.parse_args(['--run', 'not-a-segment-spec'])
    with pytest.raises(SystemExit):
        MODULE.run_verification(args, parser)
