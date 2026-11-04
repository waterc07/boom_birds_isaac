"""Immutable run snapshot for bounded landmark training runs.

Records sha256 of the frozen dataset/label/spec/protocol/gate artefacts before a
training starts, re-verifies them before checkpoint selection and after training,
and turns any mismatch into an INVALID run.  The snapshot file itself is never
rewritten after creation; verification results go to a separate check log.

CLI:
  python scripts/landmark_run_snapshot.py --create --config configs/perception/landmark_run_snapshot_v1.json \
      --run-id A_seed0 --out <run_dir>/run_snapshot.json
  python scripts/landmark_run_snapshot.py --verify --snapshot <run_snapshot.json>
  python scripts/landmark_run_snapshot.py --record-check --snapshot <run_snapshot.json> \
      --phase pre_selection --check-log <run_dir>/snapshot_checks.jsonl

Exit codes: 0 ok, 2 mismatch/invalid, 3 snapshot conflict/missing, 4 config error.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_CONFLICT = 3
EXIT_CONFIG = 4

SCHEMA_VERSION = 'dsh.landmark_run_snapshot.v1'
CONFIG_SCHEMA = 'dsh.landmark_run_snapshot.config.v1'


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write('\n')


def git_head(repo_root):
    try:
        return subprocess.run(['git', '-C', str(repo_root), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=30).stdout.strip() or None
    except Exception:  # noqa: BLE001 - evidence helper only
        return None


def resolve_artifact_path(repo_root, relative):
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError('artifact path must be repository-relative: %r' % relative)
    return Path(repo_root).resolve() / candidate


def validate_snapshot_config(config):
    problems = []
    if not isinstance(config, dict):
        return ['snapshot config must be a JSON object']
    if not str(config.get('schema_version', '')).startswith('dsh.landmark_run_snapshot'):
        problems.append('unexpected schema_version: %r' % config.get('schema_version'))
    artifacts = config.get('tracked_artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        problems.append('tracked_artifacts must be a non-empty list')
        return problems
    seen = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            problems.append('tracked_artifacts[%d] must be an object' % index)
            continue
        artifact_id = artifact.get('id')
        path = artifact.get('path')
        if not artifact_id:
            problems.append('tracked_artifacts[%d] missing id' % index)
            continue
        if artifact_id in seen:
            problems.append('duplicate artifact id: %r' % artifact_id)
        seen.add(artifact_id)
        if not path:
            problems.append('tracked_artifacts[%d] missing path' % index)
            continue
        if Path(str(path)).is_absolute():
            problems.append('tracked_artifacts[%d] path must be repository-relative: %r'
                            % (index, path))
    return problems


def build_snapshot(config, repo_root, run_id, config_path=None):
    """Collect the artefact hashes; raises ValueError on missing/mutable input."""
    problems = validate_snapshot_config(config)
    if problems:
        raise ValueError('; '.join(problems))
    repo_root = Path(repo_root).resolve()
    artifacts = []
    for artifact in config['tracked_artifacts']:
        path = resolve_artifact_path(repo_root, artifact['path'])
        if not path.is_file():
            raise FileNotFoundError('tracked artifact missing: %s (%s)'
                                    % (artifact['id'], artifact['path']))
        artifacts.append({
            'id': artifact['id'],
            'path': str(artifact['path']),
            'kind': artifact.get('kind', 'unknown'),
            'sha256': sha256_file(path),
            'size_bytes': path.stat().st_size,
        })
    payload = {
        'schema_version': SCHEMA_VERSION,
        'run_id': str(run_id),
        'repo_head': git_head(repo_root),
        'snapshot_config': {
            'path': str(Path(config_path).relative_to(repo_root)) if config_path else None,
            'sha256': sha256_file(config_path) if config_path and Path(config_path).is_file() else None,
        },
        'artifacts': artifacts,
    }
    payload['snapshot_sha256'] = fingerprint(payload)
    return payload


def fingerprint(payload):
    """Stable fingerprint over the immutable snapshot content (no timestamps)."""
    content = {
        'schema_version': payload.get('schema_version'),
        'run_id': payload.get('run_id'),
        'snapshot_config': payload.get('snapshot_config'),
        'artifacts': sorted(payload.get('artifacts') or [],
                            key=lambda item: item.get('id', '')),
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()


def create_snapshot(config_path, repo_root, run_id, out_path):
    config = load_json(config_path)
    payload = build_snapshot(config, repo_root, run_id, config_path)
    out_path = Path(out_path)
    if out_path.is_file():
        existing = load_json(out_path)
        if fingerprint(existing) == payload['snapshot_sha256']:
            return {'status': 'EXISTING_IDENTICAL', 'snapshot': str(out_path),
                    'snapshot_sha256': payload['snapshot_sha256']}
        return {'status': 'CONFLICT', 'snapshot': str(out_path),
                'existing_sha256': fingerprint(existing),
                'new_sha256': payload['snapshot_sha256'],
                'message': 'a different snapshot already exists; runs are immutable, use a new run directory'}
    payload['created_at_utc'] = __import__('datetime').datetime.now(
        __import__('datetime').timezone.utc).isoformat()
    dump_json(out_path, payload)
    return {'status': 'CREATED', 'snapshot': str(out_path),
            'snapshot_sha256': payload['snapshot_sha256']}


def verify_snapshot(snapshot_path, repo_root):
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.is_file():
        return {'ok': False, 'status': 'MISSING', 'snapshot': str(snapshot_path),
                'mismatches': [], 'message': 'snapshot file not found'}
    snapshot = load_json(snapshot_path)
    repo_root = Path(repo_root).resolve()
    mismatches = []
    for artifact in snapshot.get('artifacts', []):
        path = resolve_artifact_path(repo_root, artifact['path'])
        if not path.is_file():
            mismatches.append({'id': artifact['id'], 'path': artifact['path'],
                               'reason': 'missing'})
            continue
        actual = sha256_file(path)
        if actual != artifact.get('sha256') or path.stat().st_size != artifact.get('size_bytes'):
            mismatches.append({'id': artifact['id'], 'path': artifact['path'],
                               'reason': 'sha/size mismatch',
                               'expected_sha256': artifact.get('sha256'),
                               'actual_sha256': actual})
    config_ref = snapshot.get('snapshot_config') or {}
    if config_ref.get('path'):
        config_path = resolve_artifact_path(repo_root, config_ref['path'])
        if not config_path.is_file():
            mismatches.append({'id': 'snapshot_config', 'path': config_ref['path'],
                               'reason': 'missing'})
        else:
            actual_config_sha = sha256_file(config_path)
            if actual_config_sha != config_ref.get('sha256'):
                mismatches.append({'id': 'snapshot_config', 'path': config_ref['path'],
                                   'reason': 'snapshot_config_changed',
                                   'expected_sha256': config_ref.get('sha256'),
                                   'actual_sha256': actual_config_sha})
    current_sha = fingerprint(snapshot)
    ok = not mismatches
    return {'ok': ok,
            'status': 'VALID' if ok else 'INVALID',
            'snapshot': str(snapshot_path),
            'snapshot_sha256': snapshot.get('snapshot_sha256'),
            'recomputed_sha256': current_sha,
            'fingerprint_match': current_sha == snapshot.get('snapshot_sha256'),
            'checked_artifacts': len(snapshot.get('artifacts', [])),
            'mismatches': mismatches}


def record_check(snapshot_path, repo_root, phase, check_log=None):
    result = verify_snapshot(snapshot_path, repo_root)
    record = {
        'schema_version': SCHEMA_VERSION,
        'phase': str(phase),
        'checked_at_utc': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'snapshot': str(snapshot_path),
        'ok': bool(result['ok']),
        'status': result['status'],
        'checked_artifacts': result.get('checked_artifacts'),
        'mismatches': result.get('mismatches') or [],
        'fingerprint_match': result.get('fingerprint_match'),
        'run_valid': bool(result['ok']),
    }
    if check_log:
        log_path = Path(check_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default='configs/perception/landmark_run_snapshot_v1.json')
    parser.add_argument('--repo-root', default=None)
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--snapshot', default=None)
    parser.add_argument('--out', default=None)
    parser.add_argument('--check-log', default=None)
    parser.add_argument('--phase', default=None,
                        choices=('pre_train', 'pre_selection', 'post_train'))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--create', action='store_true')
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--record-check', action='store_true')
    parser.add_argument('--json', action='store_true', help='print the machine-readable result')
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    try:
        if args.create:
            if not args.run_id or not args.out:
                print('config error: --create needs --run-id and --out')
                return EXIT_CONFIG
            config_path = Path(args.config)
            if not config_path.is_absolute():
                config_path = repo_root / config_path
            result = create_snapshot(config_path, repo_root, args.run_id, Path(args.out))
            print(json.dumps(result, indent=2))
            return EXIT_OK if result['status'] != 'CONFLICT' else EXIT_CONFLICT
        if args.verify:
            if not args.snapshot:
                print('config error: --verify needs --snapshot')
                return EXIT_CONFIG
            result = verify_snapshot(Path(args.snapshot), repo_root)
            print(json.dumps(result, indent=2))
            return EXIT_OK if result['ok'] else (EXIT_INVALID if result['status'] == 'INVALID'
                                                 else EXIT_CONFLICT)
        if args.record_check:
            if not args.snapshot or not args.phase:
                print('config error: --record-check needs --snapshot and --phase')
                return EXIT_CONFIG
            record = record_check(Path(args.snapshot), repo_root, args.phase, args.check_log)
            print(json.dumps(record, indent=2))
            return EXIT_OK if record['ok'] else EXIT_INVALID
    except (ValueError, FileNotFoundError) as error:
        print('config error: %s' % error)
        return EXIT_CONFIG
    return EXIT_CONFIG


if __name__ == '__main__':
    raise SystemExit(main())
