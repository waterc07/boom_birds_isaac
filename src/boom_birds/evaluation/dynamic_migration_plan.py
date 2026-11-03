"""Pre-run source and parameter identity for the single-env dynamic evaluator.

v2 freezes use canonical LF text hashes for declared source/config files only;
v1 raw-hash freezes remain readable only through the explicit legacy path.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from boom_birds.evaluation.dynamic_eval_policy import (
    DEFAULT_CONTACT_MODE,
    DEFAULT_GEOMETRY_POLICY,
    HASH_ALGORITHM,
    MIGRATION_FREEZE_SCHEMA,
    MIGRATION_FREEZE_SCHEMA_V1,
    TEXT_CANONICALIZATION,
    TEXT_SCOPE,
)

_EXCLUDED = {'output', 'freeze', 'write_migration_freeze', 'working_tree',
             'gpu_driver', 'code_commit', 'screenshots', 'sensor_shadow',
             'geometry_policy_explicit', 'contact_mode_explicit',
             'geometry_policy_source', 'contact_mode_source'}


def _hash(path, *, canonical_text):
    data = Path(path).read_bytes()
    if canonical_text:
        # Only declared text source/config files use this path.  USD/PNG/weights
        # are not included in the freeze and stay raw assets in the manifest.
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def _head(root):
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                            capture_output=True, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else 'NO_GIT'


def _identity(args, root, *, canonical_text):
    root = Path(root)
    files = sorted((root / 'src').rglob('*.py'))
    files.append(root / 'scripts' / 'run_dynamic_eval.py')
    source = {p.relative_to(root).as_posix(): _hash(p, canonical_text=canonical_text)
              for p in files}
    config = {}
    for name in ('cases', 'map_config', 'vehicle_config', 'local_config',
                 'sensor_shadow_config'):
        if args.get(name) is not None:
            path = Path(args[name])
            path = path if path.is_absolute() else root / path
            config[name] = _hash(path, canonical_text=canonical_text)
    brake = root / 'configs/scenarios/brake_model_v1.json'
    if brake.exists():
        config['brake_model'] = _hash(brake, canonical_text=canonical_text)
    parameters = json.loads(json.dumps({k: v for k, v in args.items()
                                       if k not in _EXCLUDED}, default=str))
    return {'source_hashes': source, 'config_hashes': config,
            'parameters': parameters, 'git_head': _head(root)}


def build_migration_freeze(args, root, *,
                           schema_version=MIGRATION_FREEZE_SCHEMA):
    canonical_text = schema_version == MIGRATION_FREEZE_SCHEMA
    freeze = {'schema_version': schema_version,
              'frozen_at': datetime.now(timezone.utc).isoformat(),
              **_identity(args, root, canonical_text=canonical_text)}
    if canonical_text:
        freeze['hash_algorithm'] = {
            'name': HASH_ALGORITHM,
            'text_canonicalization': TEXT_CANONICALIZATION,
            'scope': TEXT_SCOPE,
            'binary_assets': 'raw_sha256_not_in_freeze',
        }
        freeze['effective_config'] = {
            'geometry_policy': args.get('geometry_policy') or DEFAULT_GEOMETRY_POLICY,
            'contact_mode': args.get('contact_mode') or DEFAULT_CONTACT_MODE,
        }
        freeze['argument_sources'] = {
            'geometry_policy': args.get('geometry_policy_source', 'default'),
            'contact_mode': args.get('contact_mode_source', 'default'),
        }
    return freeze


def make_migration_freeze(args, root, output):
    payload = build_migration_freeze(args, root)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print('DYNAMIC_MIGRATION_FREEZE_WRITTEN ' + str(output), flush=True)


def validate_migration_freeze(freeze, args, root):
    schema = freeze.get('schema_version')
    if schema not in (MIGRATION_FREEZE_SCHEMA, MIGRATION_FREEZE_SCHEMA_V1):
        raise ValueError('wrong migration freeze schema')
    frozen_at = datetime.fromisoformat(freeze['frozen_at'])
    if frozen_at.tzinfo is None or frozen_at > datetime.now(timezone.utc):
        raise ValueError('invalid/future frozen_at')
    if schema == MIGRATION_FREEZE_SCHEMA:
        algorithm = freeze.get('hash_algorithm') or {}
        if (algorithm.get('name') != HASH_ALGORITHM
                or algorithm.get('text_canonicalization') != TEXT_CANONICALIZATION
                or algorithm.get('scope') != TEXT_SCOPE):
            raise ValueError('migration freeze hash algorithm is not supported')
        effective = freeze.get('effective_config') or {}
        actual = {
            'geometry_policy': args.get('geometry_policy') or DEFAULT_GEOMETRY_POLICY,
            'contact_mode': args.get('contact_mode') or DEFAULT_CONTACT_MODE,
        }
        if effective != actual:
            raise ValueError('migration freeze effective config/parameter mismatch')
        sources = freeze.get('argument_sources') or {}
        actual_sources = {
            'geometry_policy': args.get('geometry_policy_source', 'default'),
            'contact_mode': args.get('contact_mode_source', 'default'),
        }
        if sources != actual_sources:
            raise ValueError('migration freeze argument sources mismatch')
        canonical_text = True
    else:
        # v1 freezes are raw-byte hashes; never silently apply the LF rule.
        canonical_text = False
    current = _identity(args, root, canonical_text=canonical_text)
    for key in ('source_hashes', 'config_hashes', 'parameters', 'git_head'):
        if freeze.get(key) != current[key]:
            if key == 'parameters':
                expected = freeze.get(key) or {}
                actual = current[key] or {}
                diff = {k: {'frozen': expected.get(k), 'current': actual.get(k)}
                        for k in sorted(set(expected) | set(actual))
                        if expected.get(k) != actual.get(k)}
                raise ValueError('migration freeze mismatch: parameters '
                                 + json.dumps(diff, default=str))
            raise ValueError('migration freeze mismatch: ' + key)
