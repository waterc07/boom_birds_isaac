"""Unified episode metrics and run manifests (V2.2 20.2/20.9/20.11).

Success rates always state their denominator; invalid infrastructure episodes
are reported separately and are never silently dropped or counted as success.
"""
import json
from dataclasses import dataclass
from pathlib import Path

EVALUATION_SCHEMA_ID = 'boom_birds.evaluation.v1'
EVALUATION_SCHEMA_ID_V2 = 'boom_birds.evaluation.v2'
SUPPORTED_EVALUATION_SCHEMAS = frozenset({EVALUATION_SCHEMA_ID,
                                          EVALUATION_SCHEMA_ID_V2})
OUTCOMES = ('SUCCESS', 'COLLISION', 'TIMEOUT', 'OUT_OF_BOUNDS', 'INVALID')

MANIFEST_SCHEMA_ID = 'boom_birds.manifest.v1'
REQUIRED_MANIFEST_KEYS = (
    'schema_version', 'code_commit', 'working_tree', 'config_sha256',
    'asset_versions', 'seeds', 'command', 'started_at', 'exit_code',
    'outputs_sha256',
)


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    seed: int
    outcome: str
    steps: int
    duration_s: float
    final_distance_m: float
    peak_speed_mps: float
    reason: str = ''
    schema_version: str = EVALUATION_SCHEMA_ID
    method: str = 'unknown'
    scenario_id: str = ''
    distance_bin: str = ''
    bearing_bin: str = ''
    time_to_goal_s: float | None = None
    scene_class: str = ''
    contact_evidence: bool = False
    contact_force_n: float = 0.0
    degradation_invalid_steps: int = 0
    disturbance_applied: bool = False

    def __post_init__(self):
        if not isinstance(self.episode_id, str) or not self.episode_id:
            raise ValueError('episode_id must be a nonempty string')
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError('seed must be a nonnegative integer')
        if self.outcome not in OUTCOMES:
            raise ValueError('unsupported outcome: ' + str(self.outcome))
        if self.schema_version not in SUPPORTED_EVALUATION_SCHEMAS:
            raise ValueError('unsupported evaluation schema: ' + str(self.schema_version))
        if not isinstance(self.steps, int) or isinstance(self.steps, bool) or self.steps < 0:
            raise ValueError('steps must be a nonnegative integer')
        for name in ('duration_s', 'final_distance_m', 'peak_speed_mps'):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(name + ' must be numeric')
        for name in ('method', 'scenario_id', 'distance_bin', 'bearing_bin'):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(name + ' must be a string')
        if self.time_to_goal_s is not None:
            value = self.time_to_goal_s
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError('time_to_goal_s must be numeric or None')
        if not isinstance(self.scene_class, str):
            raise ValueError('scene_class must be a string')
        if not isinstance(self.contact_evidence, bool):
            raise ValueError('contact_evidence must be a bool')
        if not isinstance(self.disturbance_applied, bool):
            raise ValueError('disturbance_applied must be a bool')
        if not isinstance(self.contact_force_n, (int, float)) \
                or isinstance(self.contact_force_n, bool) \
                or not self.contact_force_n == self.contact_force_n \
                or self.contact_force_n < 0:
            raise ValueError('contact_force_n must be a nonnegative number')
        if not isinstance(self.degradation_invalid_steps, int) \
                or isinstance(self.degradation_invalid_steps, bool) \
                or self.degradation_invalid_steps < 0:
            raise ValueError('degradation_invalid_steps must be a nonnegative integer')

    @property
    def success(self):
        return self.outcome == 'SUCCESS'


def summarize(results):
    """Aggregate with explicit denominators; invalid episodes stay visible."""
    results = list(results)
    if not results:
        raise ValueError('cannot summarize an empty result set')
    schemas = {result.schema_version for result in results}
    if len(schemas) != 1:
        raise ValueError('cannot merge results with different schemas: ' + str(sorted(schemas)))
    total = len(results)
    counts = {outcome: 0 for outcome in OUTCOMES}
    for result in results:
        counts[result.outcome] += 1
    invalid = counts['INVALID']
    valid = total - invalid
    success = counts['SUCCESS']
    summary = {
        'schema_version': results[0].schema_version,
        'total_episodes': total,
        'valid_episodes': valid,
        'invalid_episodes': invalid,
        'valid_denominator': valid,
        'success': success,
        'collision': counts['COLLISION'],
        'timeout': counts['TIMEOUT'],
        'out_of_bounds': counts['OUT_OF_BOUNDS'],
        'success_rate_of_valid': (success / valid) if valid else None,
        'success_rate_of_total': success / total,
        'collision_rate_of_valid': (counts['COLLISION'] / valid) if valid else None,
        'timeout_rate_of_valid': (counts['TIMEOUT'] / valid) if valid else None,
        'out_of_bounds_rate_of_valid': ((counts['OUT_OF_BOUNDS'] / valid)
                                        if valid else None),
        'invalid_rate_of_total': invalid / total,
        'mean_duration_s': sum(result.duration_s for result in results) / total,
        'mean_final_distance_m': sum(result.final_distance_m for result in results) / total,
        'worst_final_distance_m': max(result.final_distance_m for result in results),
        'failure_cases': [result.episode_id for result in results if not result.success],
    }
    return summary


def validate_manifest(metadata):
    if not isinstance(metadata, dict):
        raise ValueError('metadata must be a dict')
    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in metadata]
    if missing:
        raise ValueError('manifest missing keys: ' + ', '.join(missing))
    if metadata['schema_version'] != MANIFEST_SCHEMA_ID:
        raise ValueError('unsupported manifest schema: ' + str(metadata['schema_version']))
    return True


def write_manifest(run_dir, metadata, *, allow_overwrite=False):
    """Refuse to overwrite an existing manifest unless explicitly allowed."""
    validate_manifest(metadata)
    path = Path(run_dir) / 'manifest.json'
    if path.exists() and not allow_overwrite:
        raise FileExistsError('manifest already exists: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    return path