"""Pre-run source and parameter identity for opt-in production migration runs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

MIGRATION_FREEZE_SCHEMA = 'boom_birds.dynamic_migration_freeze.v1'
_EXCLUDED = {'output', 'freeze', 'write_migration_freeze', 'working_tree',
             'gpu_driver', 'code_commit', 'screenshots'}


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head(root):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                            capture_output=True, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else 'NO_GIT'


def _identity(args, root):
    root = Path(root)
    files = sorted((root / 'src').rglob('*.py'))
    files.append(root / 'scripts' / 'run_dynamic_eval.py')
    source = {p.relative_to(root).as_posix(): _hash(p) for p in files}
    config = {}
    for name in ('cases', 'map_config', 'vehicle_config', 'local_config'):
        if args.get(name) is not None:
            path = Path(args[name])
            path = path if path.is_absolute() else root / path
            config[name] = _hash(path)
    brake = root / 'configs/scenarios/brake_model_v1.json'
    if brake.exists():
        config['brake_model'] = _hash(brake)
    parameters = json.loads(json.dumps({k: v for k, v in args.items()
                                       if k not in _EXCLUDED}, default=str))
    return {'source_hashes': source, 'config_hashes': config,
            'parameters': parameters, 'git_head': _head(root)}


def build_migration_freeze(args, root):
    return {'schema_version': MIGRATION_FREEZE_SCHEMA,
            'frozen_at': datetime.now(timezone.utc).isoformat(),
            **_identity(args, root)}


def make_migration_freeze(args, root, output):
    payload = build_migration_freeze(args, root)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print('DYNAMIC_MIGRATION_FREEZE_WRITTEN ' + str(output), flush=True)


def validate_migration_freeze(freeze, args, root):
    if freeze.get('schema_version') != MIGRATION_FREEZE_SCHEMA:
        raise ValueError('wrong migration freeze schema')
    frozen_at = datetime.fromisoformat(freeze['frozen_at'])
    if frozen_at.tzinfo is None or frozen_at > datetime.now(timezone.utc):
        raise ValueError('invalid/future frozen_at')
    current = _identity(args, root)
    for key in ('source_hashes', 'config_hashes', 'parameters', 'git_head'):
        if freeze.get(key) != current[key]:
            raise ValueError('migration freeze mismatch: ' + key)
