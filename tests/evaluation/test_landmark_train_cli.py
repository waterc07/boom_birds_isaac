"""Repository-entry-point tests: training CLI, stop rule and threshold freeze.

These pin the reproducible replacement for the 2026-11-04 ad-hoc scripts:
scripts/landmark_train_cli.py (config validation, dataset build from frozen
annotations, pre-registered stop rule), scripts/landmark_freeze_thresholds.py
(validation-only threshold sweep + refusal behaviour) and
configs/perception/landmark_train_cli_v1.json (relative paths only).
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / 'scripts'
TRAIN_SCRIPT = SCRIPTS / 'landmark_train_cli.py'
FREEZE_SCRIPT = SCRIPTS / 'landmark_freeze_thresholds.py'
CLI_CONFIG = REPO_ROOT / 'configs' / 'perception' / 'landmark_train_cli_v1.json'
DEV_LABELS = REPO_ROOT / 'outputs' / 'perception' / 'dev_annotations_20261104'
LABELS_TRAIN = DEV_LABELS / 'labels_train.json'
LABELS_VAL = DEV_LABELS / 'labels_val.json'


def _load_script(path, name):
    assert path.is_file(), 'missing script: %s' % path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def train_cli():
    return _load_script(TRAIN_SCRIPT, 'landmark_train_cli_contract')


@pytest.fixture(scope='module')
def freeze_cli():
    return _load_script(FREEZE_SCRIPT, 'landmark_freeze_thresholds_contract')


# --- CLI config --------------------------------------------------------------

def test_shipped_cli_config_is_valid_and_repository_relative(train_cli):
    config = train_cli.load_config(CLI_CONFIG)
    assert train_cli.validate_config(config) == []
    for key, value in config['paths'].items():
        assert not Path(value).is_absolute(), key
    resolved = train_cli.resolve_config(config, REPO_ROOT)
    assert resolved['dataset_dir'].startswith(str(REPO_ROOT))
    assert resolved['pretrained'] == config['paths']['pretrained']


def test_cli_config_rejects_absolute_paths(train_cli):
    config = copy.deepcopy(train_cli.load_config(CLI_CONFIG))
    config['paths']['data_yaml'] = str(REPO_ROOT / config['paths']['data_yaml'])
    problems = train_cli.validate_config(config)
    assert any('repository-relative' in problem for problem in problems)


def test_cli_config_rejects_missing_train_keys(train_cli):
    config = copy.deepcopy(train_cli.load_config(CLI_CONFIG))
    del config['train']['patience']
    problems = train_cli.validate_config(config)
    assert any('train.patience' in problem for problem in problems)


def test_cli_config_rejects_wrong_schema_version(train_cli):
    config = copy.deepcopy(train_cli.load_config(CLI_CONFIG))
    config['schema_version'] = 'dsh.something.else'
    assert train_cli.validate_config(config)[0].startswith('unsupported schema_version')


# --- pre-registered stop rule ------------------------------------------------

def test_stopper_never_stops_inside_warmup(train_cli):
    stopper = train_cli.PatienceStopper(warmup_epochs=15, patience=20)
    for epoch in range(1, 16):
        assert stopper.update(epoch, 1.0 - 0.01 * epoch) is False
    assert stopper.best_epoch is None
    assert stopper.stopped_at is None


def test_stopper_starts_counting_after_warmup(train_cli):
    stopper = train_cli.PatienceStopper(warmup_epochs=15, patience=20)
    assert stopper.update(16, 0.9) is False
    assert stopper.best_epoch == 16
    for epoch in range(17, 36):
        assert stopper.update(epoch, 0.5) is False
    assert stopper.update(36, 0.5) is True
    assert stopper.stopped_at == 36
    assert stopper.state()['best_epoch'] == 16


def test_stopper_does_not_stop_while_improving(train_cli):
    stopper = train_cli.PatienceStopper(warmup_epochs=15, patience=20)
    for epoch in range(16, 60):
        assert stopper.update(epoch, 0.5 + 0.001 * epoch) is False
    assert stopper.best_epoch == 59
    assert stopper.stopped_at is None


def test_stopper_rejects_non_positive_patience(train_cli):
    with pytest.raises(ValueError):
        train_cli.PatienceStopper(warmup_epochs=15, patience=0)


# --- dataset build from frozen annotations ----------------------------------

@pytest.mark.skipif(not (LABELS_TRAIN.is_file() and LABELS_VAL.is_file()),
                    reason='dev annotation documents are gitignored and not present')
def test_prepare_dataset_uses_repository_converter(train_cli, tmp_path):
    train_doc = json.loads(LABELS_TRAIN.read_text(encoding='utf-8'))
    val_doc = json.loads(LABELS_VAL.read_text(encoding='utf-8'))
    subset_train = dict(train_doc)
    subset_train['annotations'] = train_doc['annotations'][:8]
    subset_val = dict(val_doc)
    subset_val['annotations'] = val_doc['annotations'][:6]
    train_path = tmp_path / 'labels_train_subset.json'
    val_path = tmp_path / 'labels_val_subset.json'
    train_path.write_text(json.dumps(subset_train), encoding='utf-8')
    val_path.write_text(json.dumps(subset_val), encoding='utf-8')
    out_dir = tmp_path / 'dataset'
    summary = train_cli.prepare_dataset(train_path, val_path, out_dir, REPO_ROOT)
    data_yaml = (out_dir / 'data.yaml').read_text(encoding='utf-8')
    assert 'names:\n  0: tower' in data_yaml
    assert 'kpt_shape: [1, 3]' in data_yaml
    assert 'train: images/train' in data_yaml and 'val: images/val' in data_yaml
    for split in ('train', 'val'):
        counts = summary['splits'][split]['counts']
        included = counts['positive_labels'] + counts['negative_empty_labels']
        labels = sorted((out_dir / 'labels' / split).glob('*.txt'))
        images = sorted((out_dir / 'images' / split).glob('*.png'))
        assert len(labels) == included == summary['splits'][split]['label_files']
        assert len(images) == included
        assert counts['excluded'] == (summary['splits'][split]['annotations']['path']
                                      and counts['excluded'])
    # explicit empty labels must exist for confirmed absences, never for excluded frames
    train_labels = {(out_dir / 'labels' / 'train' / (a['frame_id'].replace('.png', '.txt')))
                    for a in subset_train['annotations']}
    excluded = [a for a in subset_train['annotations']
                if a.get('target', {}).get('undecidable') is True]
    for annotation in excluded:
        assert (out_dir / 'labels' / 'train' / (annotation['frame_id'].replace('.png', '.txt'))
                ).is_file() is False


def test_prepare_dataset_reports_missing_annotations(train_cli, tmp_path):
    with pytest.raises(ValueError):
        train_cli.prepare_dataset(tmp_path / 'nope.json', tmp_path / 'nope2.json',
                                  tmp_path / 'dataset', REPO_ROOT)


# --- protocol hash guard -----------------------------------------------------

def test_verify_protocol_detects_mismatch(train_cli, tmp_path):
    artifact = tmp_path / 'artifact.txt'
    artifact.write_text('frozen\n', encoding='utf-8')
    good = {'path': str(artifact), 'sha256': train_cli.sha256_file(artifact)}
    protocol = tmp_path / 'protocol.json'
    protocol.write_text(json.dumps({'refs': {'artifact': good}}), encoding='utf-8')
    result = train_cli.verify_protocol(protocol, REPO_ROOT)
    assert result['ok'] and result['checked'] == 1
    artifact.write_text('changed\n', encoding='utf-8')
    result = train_cli.verify_protocol(protocol, REPO_ROOT)
    assert not result['ok'] and result['mismatches'][0]['path'] == str(artifact)


# --- threshold freeze --------------------------------------------------------

def _synthetic_inputs():
    labels = {'schema_version': 'dsh.tower_annotation.v2_1',
              'annotations': [
                  {'frame_id': 'p1.png', 'target': {'present': True},
                   'geometry': {'bbox_xywh': [10, 10, 20, 20]}},
                  {'frame_id': 'p2.png', 'target': {'present': True},
                   'geometry': {'bbox_xywh': [10, 10, 20, 20]}},
                  {'frame_id': 'p3.png', 'target': {'present': True},
                   'geometry': {'bbox_xywh': [10, 10, 20, 20]}},
                  {'frame_id': 'n1.png', 'target': {'present': False}, 'geometry': {}},
                  {'frame_id': 'n2.png', 'target': {'present': False}, 'geometry': {}},
                  {'frame_id': 'u1.png', 'target': {'present': True, 'occluded': True},
                   'geometry': {'bbox_xywh': None}},
              ]}
    scores = {'p1.png': 0.90, 'p2.png': 0.80, 'p3.png': 0.70,
              'n1.png': 0.65, 'n2.png': 0.20, 'u1.png': 0.90}
    rows = [{'frame_id': frame, 'observation': {'candidates': [{'score': score}]}}
            for frame, score in scores.items()]
    return labels, rows


def test_freeze_excludes_gt_unobservable_and_sweeps_scores(freeze_cli, tmp_path):
    labels, rows = _synthetic_inputs()
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    predictions_path = tmp_path / 'predictions.jsonl'
    predictions_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n',
                                encoding='utf-8')
    document = freeze_cli.build_freeze_document(
        rows, labels, predictions_path=predictions_path, labels_path=labels_path,
        checkpoint_sha256='0' * 64)
    assert document['gt_observable_frames'] == 5
    assert document['gt_unobservable_frames'] == 1
    assert document['gt_unobservable_frame_ids'] == ['u1.png']
    assert document['frozen']['tau_det'] == pytest.approx(0.70)
    assert document['frozen']['tau_conf'] == pytest.approx(0.70)
    assert document['precision_at_frozen']['tp'] == 3
    assert document['precision_at_frozen']['fp'] == 0
    assert document['multi_candidate_validation']['frames'] == 0
    assert document['frozen']['tau_margin']['status'] == 'PROPOSED_NO_MULTI_CANDIDATE_FRAMES'


def test_freeze_no_qualifying_threshold_stays_null(freeze_cli, tmp_path):
    labels, rows = _synthetic_inputs()
    for row in rows:
        if row['frame_id'] in ('n1.png', 'n2.png'):
            row['observation'] = {'candidates': [{'score': 0.99}]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    predictions_path = tmp_path / 'predictions.jsonl'
    predictions_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n',
                                encoding='utf-8')
    document = freeze_cli.build_freeze_document(
        rows, labels, predictions_path=predictions_path, labels_path=labels_path,
        checkpoint_sha256='0' * 64, tau_precision=0.95)
    assert document['status'] == 'NO_QUALIFYING_THRESHOLD'
    assert document['frozen']['tau_det'] is None


def test_freeze_rejects_tau_px_below_annotation_noise(freeze_cli, tmp_path):
    labels, rows = _synthetic_inputs()
    with pytest.raises(ValueError):
        freeze_cli.build_freeze_document(
            rows, labels, predictions_path=tmp_path / 'p.jsonl',
            labels_path=tmp_path / 'l.json', checkpoint_sha256='0' * 64,
            tau_px=2.0, annotation_noise_px=2.236)


def test_freeze_cli_refuses_to_overwrite(freeze_cli, tmp_path):
    labels, rows = _synthetic_inputs()
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    predictions_path = tmp_path / 'predictions.jsonl'
    predictions_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n',
                                encoding='utf-8')
    out = tmp_path / 'freeze.json'
    argv = ['--predictions', str(predictions_path), '--labels', str(labels_path),
            '--checkpoint-sha256', '0' * 64, '--out', str(out)]
    assert freeze_cli.main(argv) == freeze_cli.EXIT_OK
    assert out.is_file()
    assert freeze_cli.main(argv) == freeze_cli.EXIT_OVERWRITE_REFUSED
    assert freeze_cli.main(argv + ['--overwrite']) == freeze_cli.EXIT_OK
    written = json.loads(out.read_text(encoding='utf-8'))
    assert written['schema_version'] == 'dsh.landmark_threshold_freeze.v1'
    assert written['frozen']['tau_det'] == pytest.approx(0.70)


def test_freeze_cli_requires_checkpoint_identity(freeze_cli, tmp_path):
    labels, rows = _synthetic_inputs()
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    predictions_path = tmp_path / 'predictions.jsonl'
    predictions_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n',
                                encoding='utf-8')
    argv = ['--predictions', str(predictions_path), '--labels', str(labels_path),
            '--out', str(tmp_path / 'freeze.json')]
    assert freeze_cli.main(argv) == freeze_cli.EXIT_INVALID_INPUT


# --- executable entry points -------------------------------------------------

def test_train_cli_help_runs():
    completed = subprocess.run([sys.executable, str(TRAIN_SCRIPT), '--help'],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0
    assert '--prepare-dataset' in completed.stdout


def test_freeze_cli_help_runs():
    completed = subprocess.run([sys.executable, str(FREEZE_SCRIPT), '--help'],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0
    assert '--tau-precision' in completed.stdout


def test_train_cli_preflight_rejects_missing_dataset(tmp_path):
    missing = tmp_path / 'no-such-dataset'
    completed = subprocess.run(
        [sys.executable, str(TRAIN_SCRIPT), '--preflight',
         '--dataset-dir', str(missing)],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT))
    assert completed.returncode == 2
    assert 'dataset is not ready' in (completed.stdout + completed.stderr)
