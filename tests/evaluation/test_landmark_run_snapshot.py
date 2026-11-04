"""Immutable run-snapshot contract tests.

Covers scripts/landmark_run_snapshot.py (create/verify/record-check, immutability,
tamper detection, CLI exit codes) and the training-CLI integration helpers that
create the snapshot before training, verify before checkpoint selection and after
training, and turn a mismatch into an INVALID run.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPT = REPO_ROOT / 'scripts' / 'landmark_run_snapshot.py'
TRAIN_SCRIPT = REPO_ROOT / 'scripts' / 'landmark_train_cli.py'
SNAPSHOT_CONFIG = REPO_ROOT / 'configs' / 'perception' / 'landmark_run_snapshot_v1.json'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def snapshot():
    assert SNAPSHOT_SCRIPT.is_file()
    return _load(SNAPSHOT_SCRIPT, 'landmark_run_snapshot_contract')


@pytest.fixture(scope='module')
def train_cli():
    return _load(TRAIN_SCRIPT, 'landmark_train_cli_snapshot_contract')


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / 'artifact_a.json').write_text('{"a": 1}\n', encoding='utf-8')
    (tmp_path / 'artifact_b.txt').write_text('frozen labels\n', encoding='utf-8')
    config = {
        'schema_version': 'dsh.landmark_run_snapshot.v1',
        'status': 'FROZEN',
        'tracked_artifacts': [
            {'id': 'artifact_a', 'path': 'artifact_a.json', 'kind': 'protocol'},
            {'id': 'artifact_b', 'path': 'artifact_b.txt', 'kind': 'labels'},
        ],
        'checks': {'phases': ['pre_train', 'pre_selection', 'post_train']},
    }
    config_path = tmp_path / 'snapshot_config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    return {'root': tmp_path, 'config': config_path}


def test_shipped_snapshot_config_is_valid_and_repository_relative(snapshot):
    config = json.loads(SNAPSHOT_CONFIG.read_text(encoding='utf-8'))
    assert snapshot.validate_snapshot_config(config) == []
    assert config['checks']['phases'] == ['pre_train', 'pre_selection', 'post_train']
    for artifact in config['tracked_artifacts']:
        assert not Path(artifact['path']).is_absolute()


def test_validate_rejects_absolute_path_and_duplicate_ids(snapshot):
    config = {'schema_version': 'dsh.landmark_run_snapshot.v1',
              'tracked_artifacts': [{'id': 'x', 'path': 'E:/abs.json'},
                                    {'id': 'x', 'path': 'rel.json'}]}
    problems = snapshot.validate_snapshot_config(config)
    assert any('repository-relative' in problem for problem in problems)
    assert any('duplicate artifact id' in problem for problem in problems)


def test_create_verify_and_detect_tamper(snapshot, repo):
    out = repo['root'] / 'run_snapshot.json'
    result = snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    assert result['status'] == 'CREATED' and out.is_file()
    verify = snapshot.verify_snapshot(out, repo['root'])
    assert verify['ok'] and verify['status'] == 'VALID'
    assert verify['checked_artifacts'] == 2
    (repo['root'] / 'artifact_b.txt').write_text('changed labels\n', encoding='utf-8')
    verify = snapshot.verify_snapshot(out, repo['root'])
    assert not verify['ok'] and verify['status'] == 'INVALID'
    assert verify['mismatches'][0]['id'] == 'artifact_b'
    assert verify['mismatches'][0]['reason'] == 'sha/size mismatch'


def test_missing_artifact_makes_run_invalid(snapshot, repo):
    out = repo['root'] / 'run_snapshot.json'
    snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    (repo['root'] / 'artifact_a.json').unlink()
    verify = snapshot.verify_snapshot(out, repo['root'])
    assert not verify['ok']
    assert verify['mismatches'][0]['reason'] == 'missing'


def test_snapshot_is_immutable_conflict_on_different_content(snapshot, repo):
    out = repo['root'] / 'run_snapshot.json'
    assert snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)['status'] == 'CREATED'
    same = snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    assert same['status'] == 'EXISTING_IDENTICAL'
    (repo['root'] / 'artifact_a.json').write_text('{"a": 2}\n', encoding='utf-8')
    conflict = snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    assert conflict['status'] == 'CONFLICT'


def test_snapshot_config_change_is_detected(snapshot, repo):
    out = repo['root'] / 'run_snapshot.json'
    snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    original = repo['config'].read_text(encoding='utf-8')
    repo['config'].write_text(original + '\n', encoding='utf-8')
    verify = snapshot.verify_snapshot(out, repo['root'])
    assert not verify['ok']
    assert any(item['id'] == 'snapshot_config' and item['reason'] == 'snapshot_config_changed'
               for item in verify['mismatches'])


def test_record_check_appends_phase_log(snapshot, repo):
    out = repo['root'] / 'run_snapshot.json'
    log = repo['root'] / 'snapshot_checks.jsonl'
    snapshot.create_snapshot(repo['config'], repo['root'], 'seed0', out)
    first = snapshot.record_check(out, repo['root'], 'pre_train', log)
    assert first['ok'] and first['run_valid']
    (repo['root'] / 'artifact_a.json').write_text('{"a": 3}\n', encoding='utf-8')
    second = snapshot.record_check(out, repo['root'], 'pre_selection', log)
    assert not second['ok'] and not second['run_valid']
    lines = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert [line['phase'] for line in lines] == ['pre_train', 'pre_selection']
    assert [line['ok'] for line in lines] == [True, False]


def test_fingerprint_ignores_created_at_but_tracks_run_id(snapshot, repo):
    first = snapshot.build_snapshot(json.loads(repo['config'].read_text(encoding='utf-8')),
                                    repo['root'], 'seed0', repo['config'])
    first['created_at_utc'] = '2026-01-01T00:00:00+00:00'
    second = snapshot.build_snapshot(json.loads(repo['config'].read_text(encoding='utf-8')),
                                     repo['root'], 'seed0', repo['config'])
    second['created_at_utc'] = '2030-01-01T00:00:00+00:00'
    assert first['snapshot_sha256'] == second['snapshot_sha256']
    other = snapshot.build_snapshot(json.loads(repo['config'].read_text(encoding='utf-8')),
                                    repo['root'], 'seed1', repo['config'])
    assert other['snapshot_sha256'] != first['snapshot_sha256']


def test_cli_create_verify_and_exit_codes(snapshot, repo, capsys):
    out = repo['root'] / 'run_snapshot.json'
    assert snapshot.main(['--create', '--config', str(repo['config']), '--run-id', 'seed0',
                          '--out', str(out), '--repo-root', str(repo['root'])]) == 0
    assert snapshot.main(['--verify', '--snapshot', str(out),
                          '--repo-root', str(repo['root'])]) == 0
    (repo['root'] / 'artifact_b.txt').write_text('tampered\n', encoding='utf-8')
    assert snapshot.main(['--verify', '--snapshot', str(out),
                          '--repo-root', str(repo['root'])]) == 2
    assert snapshot.main(['--verify', '--snapshot', str(repo['root'] / 'nope.json'),
                          '--repo-root', str(repo['root'])]) == 3
    assert snapshot.main(['--create', '--config', str(repo['root'] / 'nope.json'),
                          '--run-id', 'seed0', '--out', str(repo['root'] / 'x.json'),
                          '--repo-root', str(repo['root'])]) == 4


def test_train_cli_snapshot_helpers_flag_change_as_invalid(train_cli, repo):
    out = repo['root'] / 'run_snapshot.json'
    log = repo['root'] / 'snapshot_checks.jsonl'
    preflight = train_cli.run_snapshot_preflight(repo['config'], repo['root'], 'seed0', out, log)
    assert preflight['ok'], preflight
    (repo['root'] / 'artifact_a.json').write_text('{"a": 99}\n', encoding='utf-8')
    phase = train_cli.run_snapshot_phase(out, repo['root'], 'pre_selection', log)
    assert not phase['ok']
    assert phase['exit_code'] == 2


def test_train_cli_preflight_with_snapshot_exit_codes(train_cli, repo, capsys):
    out = repo['root'] / 'run_snapshot.json'
    log = repo['root'] / 'snapshot_checks.jsonl'
    common = ['--preflight', '--config', str(REPO_ROOT / 'configs/perception/landmark_train_cli_v1.json'),
              '--run-snapshot-config', str(SNAPSHOT_CONFIG), '--snapshot-out', str(out),
              '--snapshot-check-log', str(log),
              '--dataset-dir', str(REPO_ROOT / 'outputs/landmark_train/dataset/dev_v4_1'),
              '--data-yaml', str(REPO_ROOT / 'outputs/landmark_train/dataset/dev_v4_1/data.yaml'),
              '--val-labels', str(REPO_ROOT / 'outputs/perception/dev_annotations_20261104/labels_val_validation163.json')]
    code = train_cli.main(common)
    assert code == 0, capsys.readouterr().out[-2000:]
    assert out.is_file() and log.is_file()
    # immutability: a tampered snapshot cannot be silently rebuilt at the same run path
    document = json.loads(out.read_text(encoding='utf-8'))
    document['artifacts'][0]['sha256'] = '0' * 64
    out.write_text(json.dumps(document, indent=2), encoding='utf-8')
    code = train_cli.main(common)
    assert code == 3
