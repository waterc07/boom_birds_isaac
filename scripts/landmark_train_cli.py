"""Version-controlled CLI for the bounded landmark training experiment.

Wraps the same recipe that produced the recorded 2026-11-04 bounded runs, but as a
reproducible repository entry point:

  1. (optional) build a YOLO pose dataset from frozen annotation documents
     (--prepare-dataset), using boom_birds.evaluation.landmark_yolo only;
  2. train one seed with the pre-registered warmup/patience rule
     (patience counted from the first evaluation AFTER warmup, not from the
     all-time best epoch, which is what ultralytics' internal stopper does);
  3. evaluate the candidate checkpoints (last, best, selected epoch saves) with
     scripts/evaluate_landmark_yolo.py on the validation split only;
  4. write one evidence JSON per seed (never overwrites without --overwrite).

No machine-private absolute paths: every path comes from the CLI or from
configs/perception/landmark_train_cli_v1.json, resolved against --repo-root
(default: the repository containing this script).  Weights and big logs stay in
ignored outputs/.  The final pool is never read.

Exit codes: 0 ok, 2 invalid input/config, 3 refused to overwrite evidence,
4 missing optional ML backend (ultralytics).
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3
EXIT_MISSING_BACKEND = 4

SCHEMA_VERSION = 'dsh.landmark_bounded_training.v1'
CONFIG_SCHEMA = 'dsh.landmark_train_cli.v1'

REQUIRED_CONFIG_PATHS = ('dataset_dir', 'data_yaml', 'val_labels',
                         'model_yaml', 'evidence_root')
REQUIRED_TRAIN_KEYS = ('epochs', 'batch', 'imgsz', 'warmup_epochs', 'patience')
TRAIN_KEYS = REQUIRED_TRAIN_KEYS + ('save_period', 'eval_epochs', 'amp', 'workers')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def load_config(path):
    return load_json(Path(path))


def _is_absolute_path_value(value):
    text = str(value)
    if '://' in text:
        return False
    return Path(text).is_absolute()


def validate_config(config):
    """Return a list of human-readable problems with a parsed CLI config."""
    problems = []
    if not isinstance(config, dict):
        return ['config must be a JSON object']
    if config.get('schema_version') != CONFIG_SCHEMA:
        problems.append('unsupported schema_version: %r (expected %r)'
                        % (config.get('schema_version'), CONFIG_SCHEMA))
    paths = config.get('paths')
    if not isinstance(paths, dict):
        problems.append('paths section missing')
        return problems
    for key in REQUIRED_CONFIG_PATHS:
        value = paths.get(key)
        if not value:
            problems.append('paths.%s is missing' % key)
            continue
        if _is_absolute_path_value(value):
            problems.append('paths.%s must be repository-relative, got %r'
                            % (key, value))
    if paths.get('pretrained') and _is_absolute_path_value(paths.get('pretrained')):
        problems.append('paths.pretrained must be a model name or repository-relative path')
    train = config.get('train')
    if not isinstance(train, dict):
        problems.append('train section missing')
        return problems
    for key in REQUIRED_TRAIN_KEYS:
        if key not in train:
            problems.append('train.%s is missing' % key)
    for key in ('epochs', 'batch', 'imgsz'):
        if key in train and not isinstance(train[key], int):
            problems.append('train.%s must be an integer' % key)
    if isinstance(train.get('eval_epochs'), list):
        for value in train['eval_epochs']:
            if not isinstance(value, int) or value <= 0:
                problems.append('train.eval_epochs values must be positive integers')
    elif 'eval_epochs' in train:
        problems.append('train.eval_epochs must be a list of integers')
    return problems


def resolve_config(config, repo_root, overrides=None):
    """Resolve config paths against repo_root; CLI overrides win."""
    repo_root = Path(repo_root).resolve()
    paths = dict(config.get('paths') or {})
    resolved = {}
    for key, value in paths.items():
        if not value:
            resolved[key] = None
        elif key == 'pretrained' and not _is_absolute_path_value(value) and '/' not in value and '\\' not in value:
            # bare model name (e.g. yolov8n-pose.pt): ultralytics resolves/downloads it;
            # never silently convert it into a machine-local absolute path
            resolved[key] = str(value)
        else:
            resolved[key] = str((repo_root / value).resolve())
    if overrides:
        resolved.update({key: value for key, value in overrides.items() if value is not None})
    return resolved


# --- optional dataset preparation (repository-only pipeline) ------------------

DATA_YAML_TEMPLATE = """# Generated by scripts/landmark_train_cli.py --prepare-dataset (gitignored output).
# One class tower, one green roof-light keypoint, model keypoint shape [1, 3].
path: {root}
train: images/train
val: images/val
names:
  0: tower
kpt_shape: [1, 3]
"""


def prepare_dataset(train_labels, val_labels, out_dir, repo_root,
                    model_size=640):
    """Build a YOLO pose dataset from frozen annotation documents.

    Labels are produced only by boom_birds.evaluation.landmark_yolo; images are
    copied next to them.  Confirmed-absent frames become explicit empty labels,
    ambiguous/undecidable/GT-unobservable frames are excluded entirely.
    """
    from boom_birds.evaluation.landmark_yolo import (
        convert_annotation_document,
        write_sidecar,
        write_yolo_dataset,
    )
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir)
    summary = {'schema_version': 'dsh.landmark_yolo_dataset_build.v1',
               'splits': {}, 'model_size': int(model_size)}
    for split, labels_path in (('train', train_labels), ('val', val_labels)):
        labels_path = Path(labels_path)
        if not labels_path.is_file():
            raise ValueError('annotation document not found: %s' % labels_path)
        document = load_json(labels_path)
        result = convert_annotation_document(document, root=repo_root, split=split,
                                             model_width=model_size,
                                             model_height=model_size)
        labels_dir = out_dir / 'labels' / split
        images_dir = out_dir / 'images' / split
        images_dir.mkdir(parents=True, exist_ok=True)
        manifest = write_yolo_dataset(result, labels_dir)
        write_sidecar(result, out_dir / 'sidecars' / ('%s_sidecar.jsonl' % split))
        image_of = {annotation['frame_id']: annotation.get('image')
                    for annotation in document.get('annotations', [])}
        copied = 0
        for frame_id in result['labels']:
            relative = image_of.get(frame_id)
            if not relative:
                raise ValueError('annotation %r has no image path' % frame_id)
            source = (repo_root / relative).resolve()
            if not source.is_file():
                raise ValueError('image not found for %r: %s' % (frame_id, source))
            target = images_dir / frame_id
            if not target.is_file():
                shutil.copyfile(source, target)
                copied += 1
        summary['splits'][split] = {
            'annotations': {'path': str(labels_path),
                            'sha256': sha256_file(labels_path)},
            'counts': result['counts'],
            'label_files': manifest['label_count'],
            'images_copied': copied,
            'counts_by_family': result.get('counts_by_family'),
        }
    data_yaml = out_dir / 'data.yaml'
    data_yaml.write_text(
        DATA_YAML_TEMPLATE.format(root=str(out_dir.resolve()).replace('\\', '/')),
        encoding='utf-8')
    summary['data_yaml'] = {'path': str(data_yaml), 'sha256': sha256_file(data_yaml)}
    (out_dir / 'dataset_build.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return summary


# --- stop rule -----------------------------------------------------------------

class PatienceStopper:
    """Pre-registered stop rule: patience counted only after warmup epochs.

    ultralytics' EarlyStopping compares against the all-time best epoch, so a
    lucky warmup epoch can stop a run early (observed on 2026-11-04).  This
    stopper ignores warmup epochs for the best-so-far baseline and starts
    counting patience from the first post-warmup evaluation.
    """

    def __init__(self, warmup_epochs, patience):
        if patience <= 0:
            raise ValueError('patience must be positive')
        self.warmup_epochs = int(warmup_epochs)
        self.patience = int(patience)
        self.best_fitness = None
        self.best_epoch = None
        self.stopped_at = None

    def update(self, epoch, fitness):
        """Feed one 1-based epoch result; return True when training must stop."""
        if epoch <= self.warmup_epochs:
            return False
        fitness = float(fitness)
        if self.best_fitness is None or fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_epoch = epoch
            return False
        if self.stopped_at is None and epoch - self.best_epoch >= self.patience:
            self.stopped_at = epoch
            return True
        return False

    def state(self):
        return {'rule': 'patience counted from the first evaluation after warmup',
                'warmup_epochs': self.warmup_epochs,
                'patience': self.patience,
                'best_fitness': self.best_fitness,
                'best_epoch': self.best_epoch,
                'stopped_at': self.stopped_at}


# --- training + candidate evaluation ------------------------------------------

def import_yolo():
    from ultralytics import YOLO
    return YOLO


def read_results_csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with open(path, 'r', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        return [{key.strip(): value.strip() for key, value in row.items()} for row in reader]


def project_candidates(save_dir, eval_epochs):
    save_dir = Path(save_dir)
    candidates = []
    last = save_dir / 'weights' / 'last.pt'
    best = save_dir / 'weights' / 'best.pt'
    if last.is_file():
        candidates.append(('last', last))
    if best.is_file():
        candidates.append(('best', best))
    for epoch in eval_epochs:
        path = save_dir / 'weights' / ('epoch%d.pt' % epoch)
        if path.is_file():
            candidates.append(('epoch%d' % epoch, path))
    return candidates


def candidate_rank(summary):
    joint = (summary or {}).get('joint_narrow_rate')
    fp = (summary or {}).get('presence_fp')
    return (-(joint if isinstance(joint, (int, float)) else -1),
            fp if isinstance(fp, (int, float)) else 10 ** 9)


def summarise_metrics(metrics):
    if not metrics:
        return None
    overall = metrics.get('overall') or {}
    presence = overall.get('presence') or {}
    reference = overall.get('reference') or {}
    identity = overall.get('identity') or {}
    joint = overall.get('joint') or {}
    return {
        'status': metrics.get('status'),
        'joint_narrow_rate': joint.get('narrow_rate'),
        'joint_all_positive_lower_bound': joint.get('all_positive_lower_bound'),
        'joint_coverage': joint.get('coverage'),
        'joint_evaluable': (overall.get('denominators') or {}).get('joint_evaluable'),
        'positives': (overall.get('denominators') or {}).get('positives'),
        'negatives': (overall.get('denominators') or {}).get('negatives'),
        'gt_unobservable': (overall.get('denominators') or {}).get('gt_unobservable'),
        'presence_tp': presence.get('tp'), 'presence_fp': presence.get('fp'),
        'presence_fn': presence.get('fn'), 'presence_tn': presence.get('tn'),
        'presence_precision': presence.get('precision'),
        'presence_recall': presence.get('recall'),
        'reference_coverage': reference.get('coverage'),
        'reference_available': reference.get('available_denominator'),
        'identity_precision': identity.get('precision'),
    }


def evaluate_candidate(weights, images_dir, labels_path, out_dir, repo_root,
                       extra_args=None):
    repo_root = Path(repo_root)
    command = [sys.executable, str(repo_root / 'scripts' / 'evaluate_landmark_yolo.py'),
               '--model', str(weights), '--images', str(images_dir),
               '--labels', str(labels_path), '--split', 'val',
               '--output-dir', str(out_dir)]
    if extra_args:
        command.extend(extra_args)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(repo_root / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(command, capture_output=True, text=True, timeout=7200, env=env)
    metrics_path = Path(out_dir) / 'metrics.json'
    metrics = load_json(metrics_path) if metrics_path.is_file() else None
    return {'command': command, 'returncode': result.returncode,
            'weights': str(weights),
            'weights_sha256': sha256_file(weights) if Path(weights).is_file() else None,
            'metrics_path': str(metrics_path) if metrics_path.is_file() else None,
            'metrics': metrics, 'summary': summarise_metrics(metrics),
            'stdout_tail': result.stdout[-800:], 'stderr_tail': result.stderr[-800:]}


def verify_protocol(protocol_path, repo_root):
    """Check that the hashes recorded in a protocol/freeze file still match."""
    protocol_path = Path(protocol_path)
    document = load_json(protocol_path)
    repo_root = Path(repo_root).resolve()
    mismatches = []
    checked = 0

    def walk(node):
        nonlocal checked
        if isinstance(node, dict):
            path = node.get('path')
            digest = node.get('sha256')
            if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
                candidate = Path(path)
                if not candidate.is_absolute():
                    candidate = repo_root / path
                if candidate.is_file():
                    checked += 1
                    actual = sha256_file(candidate)
                    if actual != digest:
                        mismatches.append({'path': path, 'expected': digest, 'actual': actual})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    return {'protocol': str(protocol_path), 'sha256': sha256_file(protocol_path),
            'checked': checked, 'mismatches': mismatches,
            'ok': not mismatches}


def load_run_snapshot_module(repo_root):
    """Load scripts/landmark_run_snapshot.py without requiring a package layout."""
    import importlib.util
    snapshot_path = Path(repo_root) / 'scripts' / 'landmark_run_snapshot.py'
    if not snapshot_path.is_file():
        raise FileNotFoundError('run snapshot script not found: %s' % snapshot_path)
    spec = importlib.util.spec_from_file_location('landmark_run_snapshot_runtime', snapshot_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_snapshot_preflight(snapshot_config, repo_root, run_id, snapshot_out, check_log=None,
                           code_root=None):
    """Create (or immutably reuse) the run snapshot and record the pre_train check."""
    try:
        module = load_run_snapshot_module(code_root or Path(__file__).resolve().parents[1])
        created = module.create_snapshot(snapshot_config, repo_root, run_id, snapshot_out)
    except (ValueError, FileNotFoundError) as error:
        return {'ok': False, 'stage': 'create', 'error': str(error), 'exit_code': EXIT_INVALID_INPUT}
    if created.get('status') == 'CONFLICT':
        return {'ok': False, 'stage': 'create', 'conflict': created, 'exit_code': EXIT_OVERWRITE_REFUSED}
    check = module.record_check(snapshot_out, repo_root, 'pre_train', check_log)
    return {'ok': bool(check['ok']), 'stage': 'pre_train', 'created': created,
            'check': check, 'snapshot': str(snapshot_out),
            'exit_code': EXIT_OK if check['ok'] else EXIT_INVALID_INPUT}


def run_snapshot_phase(snapshot_out, repo_root, phase, check_log=None, code_root=None):
    """Verify the immutable snapshot at a later phase (pre_selection / post_train)."""
    if not snapshot_out:
        return {'ok': True, 'stage': phase, 'skipped': True, 'reason': 'no snapshot configured'}
    try:
        module = load_run_snapshot_module(code_root or Path(__file__).resolve().parents[1])
        check = module.record_check(snapshot_out, repo_root, phase, check_log)
    except (ValueError, FileNotFoundError) as error:
        return {'ok': False, 'stage': phase, 'error': str(error),
                'exit_code': EXIT_INVALID_INPUT}
    return {'ok': bool(check['ok']), 'stage': phase, 'check': check,
            'exit_code': EXIT_OK if check['ok'] else EXIT_INVALID_INPUT}


def build_evidence(config, resolved, seed, run_dir, model, rows, stopper,
                   wall_seconds, peak_allocated, peak_reserved, candidates):
    scored = [item for item in candidates if item.get('summary')]
    scored.sort(key=lambda item: candidate_rank(item['summary']))
    selected = scored[0] if scored else None
    final_row = rows[-1] if rows else {}
    return {
        'schema_version': SCHEMA_VERSION,
        'status': 'BOUNDED_TRAINING_DEV_VALIDATION_ONLY',
        'generated_at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'config_source': config.get('_source'),
        'config': {
            'seed': seed,
            'epochs': config['train']['epochs'],
            'batch': config['train']['batch'],
            'imgsz': config['train']['imgsz'],
            'amp': bool(config['train'].get('amp', True)),
            'workers': config['train'].get('workers', 0),
            'warmup_epochs': config['train']['warmup_epochs'],
            'patience': config['train']['patience'],
            'save_period': config['train'].get('save_period'),
            'pretrained': resolved.get('pretrained'),
        },
        'timing': {'wall_seconds': round(wall_seconds, 2),
                   'epochs_completed': len(rows),
                   'epoch_seconds_mean': round(wall_seconds / max(len(rows), 1), 3)},
        'memory': {'peak_allocated_mib': peak_allocated,
                   'peak_reserved_mib': peak_reserved},
        'early_stop': stopper.state(),
        'epochs_completed': len(rows),
        'final_epoch_row': final_row,
        'candidates': [{key: item.get(key) for key in
                        ('candidate', 'weights', 'weights_sha256', 'returncode',
                         'metrics_path', 'summary')}
                       for item in candidates],
        'selection': {
            'rule': 'highest validation joint narrow-primary; tie-break lower validation FP',
            'selected_candidate': selected['candidate'] if selected else None,
            'selected_weights': selected['weights'] if selected else None,
            'selected_weights_sha256': selected['weights_sha256'] if selected else None,
            'selected_summary': selected['summary'] if selected else None,
        },
        'dataset': {
            'dataset_dir': str(resolved.get('dataset_dir')),
            'data_yaml_sha256': sha256_file(resolved['data_yaml']),
            'val_labels': {'path': resolved['val_labels'],
                           'sha256': sha256_file(resolved['val_labels'])},
        },
        'run_dir': str(run_dir),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Train one bounded landmark seed and evaluate candidate checkpoints on val.')
    parser.add_argument('--config', default='configs/perception/landmark_train_cli_v1.json',
                        help='CLI config (repository-relative by default)')
    parser.add_argument('--repo-root', default=None,
                        help='repository root (default: the repo containing this script)')
    parser.add_argument('--dataset-dir', default=None)
    parser.add_argument('--data-yaml', default=None)
    parser.add_argument('--val-labels', default=None)
    parser.add_argument('--model-yaml', default=None)
    parser.add_argument('--pretrained', default=None)
    parser.add_argument('--epochs', type=int, default=None)
    parser.add_argument('--batch', type=int, default=None)
    parser.add_argument('--imgsz', type=int, default=None)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--warmup-epochs', type=int, default=None)
    parser.add_argument('--patience', type=int, default=None)
    parser.add_argument('--save-period', type=int, default=None)
    parser.add_argument('--eval-epochs', default=None,
                        help='comma-separated epoch numbers whose checkpoints are evaluated')
    parser.add_argument('--out', default=None, help='seed output directory (evidence root/seedN)')
    parser.add_argument('--train-labels', default=None,
                        help='annotation document for the train split (for --prepare-dataset)')
    parser.add_argument('--prepare-dataset', action='store_true',
                        help='build the YOLO dataset from annotation documents, then exit')
    parser.add_argument('--preflight', action='store_true',
                        help='validate config/paths/protocol hashes, then exit')
    parser.add_argument('--dry-run', action='store_true', help='print the resolved plan, then exit')
    parser.add_argument('--skip-existing', action='store_true',
                        help='reuse an existing evidence file instead of retraining')
    parser.add_argument('--overwrite', action='store_true',
                        help='allow replacing an existing evidence file')
    parser.add_argument('--workers', type=int, default=None,
                        help='dataloader workers (default: train.workers from the config)')
    parser.add_argument('--cache', default=None,
                        help='dataset cache mode: ram / disk / false (default: train.cache or false)')
    parser.add_argument('--run-snapshot-config', default=None,
                        help='immutable run snapshot config (default: paths.run_snapshot in the CLI config)')
    parser.add_argument('--snapshot-out', default=None,
                        help='snapshot JSON path (default: <out>/run_snapshot.json)')
    parser.add_argument('--snapshot-check-log', default=None,
                        help='append-only snapshot check log (default: <out>/snapshot_checks.jsonl)')
    parser.add_argument('--run-id', default=None,
                        help='run id recorded in the snapshot (default: seed<N>)')
    parser.add_argument('--verify-protocol', default=None,
                        help='protocol/freeze JSON whose recorded hashes must still match')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    if not config_path.is_file():
        print('invalid input: config not found: %s' % config_path)
        return EXIT_INVALID_INPUT
    config = load_config(config_path)
    config['_source'] = str(config_path)
    problems = validate_config(config)
    if problems:
        for problem in problems:
            print('config problem: %s' % problem)
        return EXIT_INVALID_INPUT
    overrides = {
        'dataset_dir': args.dataset_dir, 'data_yaml': args.data_yaml,
        'val_labels': args.val_labels, 'model_yaml': args.model_yaml,
        'pretrained': args.pretrained,
    }
    resolved = resolve_config(config, repo_root, overrides)
    train = dict(config['train'])
    if args.epochs is not None:
        train['epochs'] = args.epochs
    if args.batch is not None:
        train['batch'] = args.batch
    if args.imgsz is not None:
        train['imgsz'] = args.imgsz
    if args.warmup_epochs is not None:
        train['warmup_epochs'] = args.warmup_epochs
    if args.patience is not None:
        train['patience'] = args.patience
    if args.save_period is not None:
        train['save_period'] = args.save_period
    if args.eval_epochs is not None:
        train['eval_epochs'] = [int(value) for value in args.eval_epochs.split(',') if value.strip()]
    config['train'] = train
    evidence_root = Path(resolved['evidence_root'])
    out_dir = Path(args.out) if args.out else evidence_root / ('seed%d' % args.seed)
    evidence_path = out_dir / ('bounded_evidence_seed%d.json' % args.seed)

    if args.prepare_dataset:
        train_labels = args.train_labels or resolved.get('train_labels')
        val_labels = args.val_labels or resolved.get('val_labels')
        if not train_labels or not val_labels:
            print('invalid input: --prepare-dataset needs --train-labels and --val-labels '
                  '(or paths.train_labels / paths.val_labels in the config)')
            return EXIT_INVALID_INPUT
        try:
            summary = prepare_dataset(Path(train_labels),
                                      Path(val_labels),
                                      Path(resolved['dataset_dir']), repo_root,
                                      model_size=train.get('imgsz', 640))
        except (ValueError, OSError) as error:
            print('invalid input: %s' % error)
            return EXIT_INVALID_INPUT
        print(json.dumps(summary, indent=2)[:4000])
        return EXIT_OK

    protocol = None
    if args.verify_protocol:
        protocol = verify_protocol(Path(args.verify_protocol), repo_root)
        if not protocol['ok']:
            print(json.dumps(protocol, indent=2))
            print('invalid input: protocol/freeze hashes no longer match')
            return EXIT_INVALID_INPUT

    required = [('dataset_dir', resolved.get('dataset_dir')),
                ('data_yaml', resolved.get('data_yaml')),
                ('val_labels', resolved.get('val_labels')),
                ('model_yaml', resolved.get('model_yaml'))]
    missing = [(name, value) for name, value in required
               if not value or (name != 'dataset_dir' and not Path(value).is_file())]
    if missing or not Path(resolved.get('dataset_dir') or '').is_dir():
        print('invalid input: dataset is not ready: %s' % (missing or 'dataset_dir missing'))
        print('hint: run --prepare-dataset with --train-labels/--val-labels first')
        return EXIT_INVALID_INPUT

    snapshot_config = args.run_snapshot_config or resolved.get('run_snapshot')
    snapshot_out = Path(args.snapshot_out) if args.snapshot_out else out_dir / 'run_snapshot.json'
    snapshot_log = (Path(args.snapshot_check_log) if args.snapshot_check_log
                    else out_dir / 'snapshot_checks.jsonl')
    run_id = args.run_id or ('seed%d' % args.seed)
    snapshot_state = None
    if snapshot_config:
        snapshot_config_path = Path(snapshot_config)
        if not snapshot_config_path.is_absolute():
            snapshot_config_path = repo_root / snapshot_config_path
        if not snapshot_config_path.is_file():
            print('invalid input: run snapshot config not found: %s' % snapshot_config_path)
            return EXIT_INVALID_INPUT
        snapshot_state = run_snapshot_preflight(snapshot_config_path, repo_root, run_id,
                                                snapshot_out, snapshot_log)
        if not snapshot_state.get('ok'):
            print(json.dumps(snapshot_state, indent=2, default=str)[:4000])
            print('INVALID run: immutable run snapshot check failed before training')
            return snapshot_state.get('exit_code', EXIT_INVALID_INPUT)
    plan = {'config': str(config_path), 'repo_root': str(repo_root),
            'resolved': resolved, 'train': train, 'seed': args.seed,
            'evidence_path': str(evidence_path), 'protocol': protocol,
            'run_snapshot': {'config': str(snapshot_config) if snapshot_config else None,
                             'snapshot': str(snapshot_out) if snapshot_config else None,
                             'check_log': str(snapshot_log) if snapshot_config else None,
                             'pre_train': snapshot_state}}
    if args.preflight or args.dry_run:
        print(json.dumps(plan, indent=2, default=str)[:6000])
        return EXIT_OK

    if evidence_path.is_file() and not args.overwrite:
        if args.skip_existing:
            print(json.dumps(load_json(evidence_path), indent=2)[:4000])
            return EXIT_OK
        print('refusing to overwrite %s (pass --overwrite to retrain this seed)' % evidence_path)
        return EXIT_OVERWRITE_REFUSED
    try:
        YOLO = import_yolo()
    except ImportError:
        print('missing backend: ultralytics is required for training; install it in the isolated '
              'training venv (.venv/landmark-train), never in the Isaac venv')
        return EXIT_MISSING_BACKEND

    import datetime
    import torch
    model = YOLO(resolved['pretrained']) if resolved.get('pretrained') else YOLO(resolved['model_yaml'])
    stopper = PatienceStopper(train['warmup_epochs'], train['patience'])

    def on_fit_epoch_end(trainer):
        if stopper.update(trainer.epoch + 1, trainer.fitness):
            trainer.stop = True

    model.add_callback('on_fit_epoch_end', on_fit_epoch_end)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = __import__('time').perf_counter()
    model.train(
        data=resolved['data_yaml'], epochs=train['epochs'], imgsz=train['imgsz'],
        batch=train['batch'], device=train.get('device', 0),
        workers=(args.workers if args.workers is not None else train.get('workers', 0)),
        cache=(args.cache if args.cache is not None else train.get('cache', False)),
        amp=bool(train.get('amp', True)),
        project=str(out_dir), name='seed%d' % args.seed, exist_ok=True,
        plots=False, val=True,
        patience=train['epochs'],  # ultralytics internal stopper made inert
        warmup_epochs=train['warmup_epochs'],
        save_period=train.get('save_period'),
        seed=args.seed, deterministic=True, verbose=True)
    torch.cuda.synchronize()
    wall_seconds = __import__('time').perf_counter() - started
    peak_allocated = round(torch.cuda.max_memory_allocated() / (1024 ** 2), 1)
    peak_reserved = round(torch.cuda.max_memory_reserved() / (1024 ** 2), 1)
    save_dir = Path(model.trainer.save_dir)
    rows = read_results_csv(save_dir / 'results.csv')
    snapshot_checks = [snapshot_state] if snapshot_state else []
    if snapshot_state:
        pre_selection = run_snapshot_phase(snapshot_out, repo_root, 'pre_selection', snapshot_log)
        snapshot_checks.append(pre_selection)
        if not pre_selection.get('ok'):
            invalid_evidence = {'schema_version': SCHEMA_VERSION,
                                'status': 'INVALID_RUN_SNAPSHOT',
                                'seed': args.seed, 'run_id': run_id,
                                'reason': 'immutable run snapshot changed before checkpoint selection',
                                'run_snapshot': {'snapshot': str(snapshot_out),
                                                 'checks': snapshot_checks},
                                'candidates': []}
            out_dir.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(invalid_evidence, indent=2, ensure_ascii=False) + '\n',
                                     encoding='utf-8')
            print(json.dumps(invalid_evidence, indent=2)[:3000])
            print('INVALID run: snapshot mismatch before selection; no checkpoint may be selected')
            return EXIT_INVALID_INPUT
    candidates = []
    for name, path in project_candidates(save_dir, train.get('eval_epochs', [])):
        evaluation = evaluate_candidate(
            path, Path(resolved['dataset_dir']) / 'images' / 'val',
            resolved['val_labels'], out_dir / ('eval_%s' % name), repo_root)
        evaluation['candidate'] = name
        candidates.append(evaluation)
        print('candidate', name, 'joint',
              (evaluation.get('summary') or {}).get('joint_narrow_rate'),
              'returncode', evaluation['returncode'])
    evidence = build_evidence(config, resolved, args.seed, save_dir, model, rows,
                              stopper, wall_seconds, peak_allocated, peak_reserved,
                              candidates)
    if snapshot_state:
        post_train = run_snapshot_phase(snapshot_out, repo_root, 'post_train', snapshot_log)
        snapshot_checks.append(post_train)
        evidence['run_snapshot'] = {
            'config': str(snapshot_config),
            'snapshot': str(snapshot_out),
            'check_log': str(snapshot_log),
            'run_id': run_id,
            'valid': bool(post_train.get('ok')),
            'checks': snapshot_checks,
        }
        if not post_train.get('ok'):
            evidence['status'] = 'INVALID_RUN_SNAPSHOT'
            evidence['invalid_reason'] = 'immutable run snapshot changed after training'
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n',
                             encoding='utf-8')
    print(json.dumps({'selected': evidence['selection'],
                      'timing': evidence['timing'],
                      'early_stop': evidence['early_stop'],
                      'run_snapshot': evidence.get('run_snapshot')},
                     indent=2)[:4000])
    print('wrote', evidence_path)
    if evidence.get('status') == 'INVALID_RUN_SNAPSHOT':
        print('INVALID run: snapshot mismatch after training; evidence written but not selectable')
        return EXIT_INVALID_INPUT
    return EXIT_OK


if __name__ == '__main__':
    raise SystemExit(main())
