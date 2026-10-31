"""Deterministic start/goal randomization and replayable scenario manifests."""
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

SCENARIO_SCHEMA_ID = 'boom_birds.scenarios.v1'
DISTANCE_BINS = ('short', 'medium', 'long')
BEARING_BINS = ('front', 'side', 'rear')
DISTANCE_THRESHOLDS_M = (1.2, 1.8)


def _finite(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


def _range(values, name):
    try:
        low, high = (float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be a two-number range')
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        raise ValueError(name + ' must satisfy low < high')
    return (low, high)


def _counter(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(name + ' must be a nonnegative integer')


def distance_bin_for(distance_m):
    if distance_m < DISTANCE_THRESHOLDS_M[0]:
        return 'short'
    if distance_m < DISTANCE_THRESHOLDS_M[1]:
        return 'medium'
    return 'long'


def bearing_bin_for(bearing_rad):
    bearing = abs((bearing_rad + math.pi) % (2 * math.pi) - math.pi)
    if bearing <= math.pi / 4:
        return 'front'
    if bearing <= 3 * math.pi / 4:
        return 'side'
    return 'rear'


@dataclass(frozen=True)
class RandomizationSpec:
    """PROPOSED sampling ranges; recorded with every generated scenario."""
    start_xy_range_m: tuple = (-0.5, 0.5)
    start_z_range_m: tuple = (0.65, 0.85)
    start_yaw_range_rad: tuple = (-math.pi, math.pi)
    goal_xy_range_m: tuple = ((0.9, 1.6), (-1.0, 1.0))
    goal_z_range_m: tuple = (0.65, 0.95)
    min_goal_distance_m: float = 0.8
    max_goal_distance_m: float = 2.5

    def __post_init__(self):
        _range(self.start_xy_range_m, 'start_xy_range_m')
        _range(self.start_z_range_m, 'start_z_range_m')
        _range(self.start_yaw_range_rad, 'start_yaw_range_rad')
        try:
            goal_x, goal_y = self.goal_xy_range_m
        except (TypeError, ValueError):
            raise ValueError('goal_xy_range_m must hold two ranges')
        _range(goal_x, 'goal_xy_range_m[0]')
        _range(goal_y, 'goal_xy_range_m[1]')
        _range(self.goal_z_range_m, 'goal_z_range_m')
        _finite(self.min_goal_distance_m, 'min_goal_distance_m')
        _finite(self.max_goal_distance_m, 'max_goal_distance_m')
        if self.min_goal_distance_m <= 0:
            raise ValueError('min_goal_distance_m must be positive')
        if self.min_goal_distance_m >= self.max_goal_distance_m:
            raise ValueError('min_goal_distance_m must be below max_goal_distance_m')


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    seed: int
    start_position_world_m: tuple
    start_yaw_rad: float
    goal_position_world_m: tuple
    distance_m: float
    bearing_rad: float
    distance_bin: str
    bearing_bin: str

    def __post_init__(self):
        if not isinstance(self.scenario_id, str) or not self.scenario_id:
            raise ValueError('scenario_id must be a nonempty string')
        _counter(self.seed, 'seed')
        for name in ('start_position_world_m', 'goal_position_world_m'):
            values = tuple(getattr(self, name))
            if len(values) != 3 or any(not math.isfinite(value) for value in values):
                raise ValueError(name + ' must contain three finite values')
        _finite(self.start_yaw_rad, 'start_yaw_rad')
        _finite(self.distance_m, 'distance_m')
        _finite(self.bearing_rad, 'bearing_rad')
        if self.distance_bin not in DISTANCE_BINS:
            raise ValueError('unsupported distance_bin: ' + str(self.distance_bin))
        if self.bearing_bin not in BEARING_BINS:
            raise ValueError('unsupported bearing_bin: ' + str(self.bearing_bin))

    def to_dict(self):
        return {
            'scenario_id': self.scenario_id,
            'seed': self.seed,
            'start_position_world_m': list(self.start_position_world_m),
            'start_yaw_rad': self.start_yaw_rad,
            'goal_position_world_m': list(self.goal_position_world_m),
            'distance_m': self.distance_m,
            'bearing_rad': self.bearing_rad,
            'distance_bin': self.distance_bin,
            'bearing_bin': self.bearing_bin,
        }

    @classmethod
    def from_dict(cls, payload):
        return cls(
            scenario_id=payload['scenario_id'], seed=payload['seed'],
            start_position_world_m=tuple(payload['start_position_world_m']),
            start_yaw_rad=payload['start_yaw_rad'],
            goal_position_world_m=tuple(payload['goal_position_world_m']),
            distance_m=payload['distance_m'], bearing_rad=payload['bearing_rad'],
            distance_bin=payload['distance_bin'], bearing_bin=payload['bearing_bin'])


def generate_scenarios(count, *, base_seed, spec=None):
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ValueError('count must be a positive integer')
    _counter(base_seed, 'base_seed')
    spec = spec if spec is not None else RandomizationSpec()
    if not isinstance(spec, RandomizationSpec):
        raise ValueError('spec must be a RandomizationSpec')
    rng = random.Random(base_seed)
    scenarios = []
    attempts = 0
    limit = count * 1000
    while len(scenarios) < count:
        attempts += 1
        if attempts > limit:
            raise ValueError('could not sample enough valid scenarios')
        start = (rng.uniform(*spec.start_xy_range_m),
                 rng.uniform(*spec.start_xy_range_m),
                 rng.uniform(*spec.start_z_range_m))
        yaw = rng.uniform(*spec.start_yaw_range_rad)
        goal = (rng.uniform(*spec.goal_xy_range_m[0]),
                rng.uniform(*spec.goal_xy_range_m[1]),
                rng.uniform(*spec.goal_z_range_m))
        distance = math.sqrt(sum((goal[index] - start[index]) ** 2 for index in range(3)))
        if not spec.min_goal_distance_m <= distance <= spec.max_goal_distance_m:
            continue
        bearing = math.atan2(goal[1] - start[1], goal[0] - start[0])
        relative = (bearing - yaw + math.pi) % (2 * math.pi) - math.pi
        scenarios.append(Scenario(
            scenario_id='sc-{}-{:03d}'.format(base_seed, len(scenarios)),
            seed=base_seed + len(scenarios),
            start_position_world_m=start, start_yaw_rad=yaw,
            goal_position_world_m=goal, distance_m=distance, bearing_rad=relative,
            distance_bin=distance_bin_for(distance),
            bearing_bin=bearing_bin_for(relative)))
    return tuple(scenarios)


def _spec_dict(spec):
    return {
        'start_xy_range_m': list(spec.start_xy_range_m),
        'start_z_range_m': list(spec.start_z_range_m),
        'start_yaw_range_rad': list(spec.start_yaw_range_rad),
        'goal_xy_range_m': [list(spec.goal_xy_range_m[0]), list(spec.goal_xy_range_m[1])],
        'goal_z_range_m': list(spec.goal_z_range_m),
        'min_goal_distance_m': spec.min_goal_distance_m,
        'max_goal_distance_m': spec.max_goal_distance_m,
    }


def manifest_sha256(payload):
    body = {key: value for key, value in payload.items() if key != 'content_sha256'}
    encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    import hashlib
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def build_scenario_manifest(scenarios, *, spec, base_seed, generated_at):
    payload = {
        'schema_version': SCENARIO_SCHEMA_ID,
        'base_seed': base_seed,
        'count': len(scenarios),
        'generated_at': generated_at,
        'spec': _spec_dict(spec),
        'scenarios': [scenario.to_dict() for scenario in scenarios],
    }
    payload['content_sha256'] = manifest_sha256(payload)
    return payload


def write_scenario_manifest(path, manifest):
    if manifest.get('content_sha256') != manifest_sha256(manifest):
        raise ValueError('scenario manifest hash does not match its content')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    return path


def load_scenario_manifest(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != SCENARIO_SCHEMA_ID:
        raise ValueError('unsupported scenario schema: ' + str(payload.get('schema_version')))
    if payload.get('content_sha256') != manifest_sha256(payload):
        raise ValueError('scenario manifest hash mismatch: ' + str(path))
    return payload


def scenarios_from_manifest(manifest):
    return tuple(Scenario.from_dict(item) for item in manifest['scenarios'])
