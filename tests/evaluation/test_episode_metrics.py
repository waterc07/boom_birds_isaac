"""Unified episode metrics and manifest tests."""
import json

import pytest

from boom_birds.evaluation.episodes import (
    MANIFEST_SCHEMA_ID,
    EpisodeResult,
    summarize,
    validate_manifest,
    write_manifest,
)


def episode(index, outcome, **overrides):
    values = dict(episode_id='ep-' + str(index), seed=index, outcome=outcome,
                  steps=100, duration_s=5.0, final_distance_m=0.2,
                  peak_speed_mps=0.5, reason='')
    values.update(overrides)
    return EpisodeResult(**values)


def test_success_rate_keeps_failure_denominator():
    results = [episode(i, 'SUCCESS') for i in range(8)]
    results.append(episode(8, 'COLLISION'))
    results.append(episode(9, 'TIMEOUT'))
    summary = summarize(results)
    assert summary['total_episodes'] == 10
    assert summary['valid_denominator'] == 10
    assert summary['success_rate_of_valid'] == pytest.approx(0.8)
    assert summary['collision_rate_of_valid'] == pytest.approx(0.1)
    assert summary['timeout_rate_of_valid'] == pytest.approx(0.1)
    assert summary['failure_cases'] == ['ep-8', 'ep-9']


def test_invalid_episodes_are_separate_but_not_dropped():
    results = [episode(i, 'SUCCESS') for i in range(8)]
    results.append(episode(8, 'TIMEOUT'))
    results.append(episode(9, 'INVALID', reason='DRIVER_ERROR'))
    summary = summarize(results)
    assert summary['total_episodes'] == 10
    assert summary['invalid_episodes'] == 1
    assert summary['valid_episodes'] == 9
    assert summary['valid_denominator'] == 9
    assert summary['success_rate_of_valid'] == pytest.approx(8 / 9)
    assert summary['invalid_rate_of_total'] == pytest.approx(0.1)
    assert summary['failure_cases'] == ['ep-8', 'ep-9']


def test_unsupported_schema_and_empty_results_are_rejected():
    with pytest.raises(ValueError):
        summarize([])
    with pytest.raises(ValueError):
        EpisodeResult('ep-x', 0, 'SUCCESS', 1, 0.0, 0.0, 0.0,
                      schema_version='boom_birds.evaluation.v0')
    assert summarize([episode(0, 'SUCCESS')])['schema_version'] == 'boom_birds.evaluation.v1'


def test_bad_episode_fields_are_rejected():
    with pytest.raises(ValueError):
        episode(0, 'UNKNOWN_OUTCOME')
    with pytest.raises(ValueError):
        episode(0, 'SUCCESS', seed=-1)
    with pytest.raises(ValueError):
        episode(0, 'SUCCESS', steps=1.5)


def metadata():
    return {
        'schema_version': MANIFEST_SCHEMA_ID,
        'code_commit': 'a' * 40,
        'working_tree': 'dirty: 2 files',
        'config_sha256': {'sim_reference.yaml': 'b' * 64},
        'asset_versions': {'isaac_sim': '5.1.0.0', 'isaac_lab': 'b4c3210'},
        'seeds': {'train': [0, 1, 2], 'eval': [100]},
        'command': 'python scripts/run_sim_baseline.py --task reach',
        'started_at': '2026-10-31T17:00:00+08:00',
        'exit_code': 0,
        'outputs_sha256': {'reach_summary.json': 'c' * 64},
    }


def test_manifest_requires_keys_and_refuses_overwrite(tmp_path):
    with pytest.raises(ValueError):
        missing = metadata()
        missing.pop('exit_code')
        validate_manifest(missing)
    path = write_manifest(tmp_path, metadata())
    assert path.name == 'manifest.json'
    assert json.loads(path.read_text(encoding='utf-8'))['code_commit'] == 'a' * 40
    with pytest.raises(FileExistsError):
        write_manifest(tmp_path, metadata())
    rewritten = write_manifest(tmp_path, metadata(), allow_overwrite=True)
    assert rewritten == path
