"""Layered scenario contract v2: scene classes, controlled strata and manifests."""
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from .disturbance import DisturbanceSpec

LAYERED_SCENARIO_SCHEMA_ID = 'boom_birds.scenarios.v2'
SCENE_CLASSES = ('A_clear', 'B_static', 'C_dynamic', 'D_observation',
                 'E_disturbance')
DISTANCE_BINS = ('near', 'mid', 'far')
BEARING_BINS = ('front', 'side', 'rear')
DISTANCE_EDGES_M = (1.2, 1.6)
DISTANCE_RANGE_M = (0.8, 2.0)
BEARING_EDGES_RAD = (math.pi / 4, 3 * math.pi / 4)
STRATA_QUOTAS = ((3, 3, 2), (3, 3, 2), (3, 3, 3))
CLEARANCE_M = 0.35
OBSTACLE_SIZES_M = ((0.35, 0.35, 1.0), (0.30, 0.30, 0.9))
KINEMATIC_SIZE_M = (0.30, 0.30, 0.9)
DYNAMIC_RADIUS_M = 0.10
DYNAMIC_MASS_KG = 0.05


def _finite(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


def _counter(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(name + ' must be a nonnegative integer')


def _triple(values, name):
    try:
        converted = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain three numbers')
    if len(converted) != 3 or any(not math.isfinite(value) for value in converted):
        raise ValueError(name + ' must contain three finite values')
    return converted


def _range(values, name):
    try:
        low, high = (float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be a two-number range')
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        raise ValueError(name + ' must satisfy low < high')
    return (low, high)


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def distance_bin_for_v2(distance_m):
    if distance_m < DISTANCE_EDGES_M[0]:
        return 'near'
    if distance_m < DISTANCE_EDGES_M[1]:
        return 'mid'
    return 'far'


def bearing_bin_for_v2(bearing_rad):
    bearing = abs(_wrap(bearing_rad))
    if bearing <= BEARING_EDGES_RAD[0]:
        return 'front'
    if bearing <= BEARING_EDGES_RAD[1]:
        return 'side'
    return 'rear'


@dataclass(frozen=True)
class ClassSpec:
    scene_class: str
    description: str
    capability_requirement: str
    input_permission: str
    expected_outcomes: str
    boundary: str


CLASS_SPECS = {
    'A_clear': ClassSpec(
        scene_class='A_clear',
        description='Obstacle-free randomized reach/stop',
        capability_requirement='velocity outer loop + stop at goal',
        input_permission='ORACLE position/velocity/attitude',
        expected_outcomes='high success rate; short time to goal',
        boundary='does not demonstrate perception or obstacle avoidance'),
    'B_static': ClassSpec(
        scene_class='B_static',
        description='Two static cuboid obstacles blocking the direct path',
        capability_requirement='same baseline; no avoidance capability',
        input_permission='ORACLE position/velocity/attitude',
        expected_outcomes='possible PhysX collisions; collision rate measures limits',
        boundary='not an obstacle-avoidance acceptance test'),
    'C_dynamic': ClassSpec(
        scene_class='C_dynamic',
        description='One kinematic crossing entity and one dynamic sphere',
        capability_requirement='same baseline; no dynamic avoidance',
        input_permission='ORACLE position/velocity/attitude + entity poses',
        expected_outcomes='possible collisions and timing failures',
        boundary='kinematic and dynamic entities are recorded separately'),
    'D_observation': ClassSpec(
        scene_class='D_observation',
        description='Controller input noise, delay and dropout; evaluation uses truth',
        capability_requirement='same baseline with degraded input interface',
        input_permission='degraded ORACLE-derived observation; eval uses raw truth',
        expected_outcomes='success rate/time degradation, stale-input holds',
        boundary='not a real camera or perception-pipeline validation'),
    'E_disturbance': ClassSpec(
        scene_class='E_disturbance',
        description='Body-frame external force/torque window applied through the wrench interface',
        capability_requirement='same baseline with physical disturbance',
        input_permission='ORACLE position/velocity/attitude',
        expected_outcomes='tracking deviation, possible timeout',
        boundary='not a wind-field model; forces are body-frame, in N and N*m'),
}


@dataclass(frozen=True)
class ObstacleSpec:
    kind: str
    center_world_m: tuple
    size_m: tuple
    velocity_world_mps: tuple = (0.0, 0.0, 0.0)

    def __post_init__(self):
        if self.kind not in ('static', 'kinematic'):
            raise ValueError('obstacle kind must be static or kinematic')
        _triple(self.center_world_m, 'center_world_m')
        size = _triple(self.size_m, 'size_m')
        if any(value <= 0 for value in size):
            raise ValueError('obstacle size must be positive')
        _triple(self.velocity_world_mps, 'velocity_world_mps')


@dataclass(frozen=True)
class DynamicEntitySpec:
    radius_m: float
    mass_kg: float
    center_world_m: tuple
    velocity_world_mps: tuple

    def __post_init__(self):
        _finite(self.radius_m, 'radius_m')
        _finite(self.mass_kg, 'mass_kg')
        if self.radius_m <= 0 or self.mass_kg <= 0:
            raise ValueError('dynamic entity radius and mass must be positive')
        _triple(self.center_world_m, 'center_world_m')
        _triple(self.velocity_world_mps, 'velocity_world_mps')


@dataclass(frozen=True)
class DegradationSpec:
    position_noise_std_m: float = 0.0
    velocity_noise_std_mps: float = 0.0
    delay_steps: int = 0
    dropout_probability: float = 0.0
    max_stale_s: float = 0.3

    def __post_init__(self):
        _finite(self.position_noise_std_m, 'position_noise_std_m')
        _finite(self.velocity_noise_std_mps, 'velocity_noise_std_mps')
        _finite(self.dropout_probability, 'dropout_probability')
        _finite(self.max_stale_s, 'max_stale_s')
        if self.position_noise_std_m < 0 or self.velocity_noise_std_mps < 0:
            raise ValueError('noise standard deviations must be nonnegative')
        if not 0.0 <= self.dropout_probability <= 1.0:
            raise ValueError('dropout_probability must be in [0, 1]')
        if not isinstance(self.delay_steps, int) or isinstance(self.delay_steps, bool) \
                or self.delay_steps < 0:
            raise ValueError('delay_steps must be a nonnegative integer')
        if self.max_stale_s <= 0:
            raise ValueError('max_stale_s must be positive')


@dataclass(frozen=True)
class RandomizationSpecV2:
    start_xy_range_m: tuple = (-0.5, 0.5)
    start_z_range_m: tuple = (0.65, 0.85)
    start_yaw_range_rad: tuple = (-math.pi, math.pi)
    distance_range_m: tuple = DISTANCE_RANGE_M
    vertical_offset_range_m: tuple = (-0.15, 0.15)
    goal_z_range_m: tuple = (0.6, 1.0)
    position_noise_range_m: tuple = (0.02, 0.08)
    velocity_noise_range_mps: tuple = (0.02, 0.06)
    delay_steps_choices: tuple = (1, 2, 3)
    dropout_probability_range: tuple = (0.05, 0.2)
    max_stale_s: float = 0.3
    disturbance_force_range_n: tuple = (0.004, 0.012)
    disturbance_torque_range_nm: tuple = (0.0, 0.0001)
    disturbance_start_range_s: tuple = (0.2, 0.5)
    disturbance_duration_range_s: tuple = (0.2, 0.5)

    def __post_init__(self):
        for name in ('start_xy_range_m', 'start_z_range_m', 'start_yaw_range_rad',
                     'distance_range_m', 'vertical_offset_range_m',
                     'goal_z_range_m', 'position_noise_range_m',
                     'velocity_noise_range_mps', 'dropout_probability_range',
                     'disturbance_force_range_n', 'disturbance_torque_range_nm',
                     'disturbance_start_range_s', 'disturbance_duration_range_s'):
            _range(getattr(self, name), name)
        if not isinstance(self.delay_steps_choices, tuple) or not self.delay_steps_choices:
            raise ValueError('delay_steps_choices must be a nonempty tuple')
        for choice in self.delay_steps_choices:
            if not isinstance(choice, int) or isinstance(choice, bool) or choice < 0:
                raise ValueError('delay_steps_choices entries must be nonnegative ints')
        _finite(self.max_stale_s, 'max_stale_s')
        if self.max_stale_s <= 0:
            raise ValueError('max_stale_s must be positive')


@dataclass(frozen=True)
class LayeredScenario:
    scenario_id: str
    scene_class: str
    seed: int
    start_position_world_m: tuple
    start_yaw_rad: float
    goal_position_world_m: tuple
    distance_m: float
    bearing_rad: float
    distance_bin: str
    bearing_bin: str
    obstacles: tuple = ()
    kinematic_entity: ObstacleSpec | None = None
    dynamic_entity: DynamicEntitySpec | None = None
    degradation: DegradationSpec | None = None
    disturbance: DisturbanceSpec | None = None

    def __post_init__(self):
        if not isinstance(self.scenario_id, str) or not self.scenario_id:
            raise ValueError('scenario_id must be a nonempty string')
        if self.scene_class not in SCENE_CLASSES:
            raise ValueError('unknown scene_class: ' + str(self.scene_class))
        _counter(self.seed, 'seed')
        _triple(self.start_position_world_m, 'start_position_world_m')
        _triple(self.goal_position_world_m, 'goal_position_world_m')
        _finite(self.start_yaw_rad, 'start_yaw_rad')
        _finite(self.distance_m, 'distance_m')
        _finite(self.bearing_rad, 'bearing_rad')
        if self.distance_bin != distance_bin_for_v2(self.distance_m):
            raise ValueError('distance_bin does not match distance_m')
        if self.bearing_bin != bearing_bin_for_v2(self.bearing_rad):
            raise ValueError('bearing_bin does not match bearing_rad')
        obstacles = tuple(self.obstacles)
        for obstacle in obstacles:
            if not isinstance(obstacle, ObstacleSpec):
                raise ValueError('obstacles must contain ObstacleSpec entries')
        object.__setattr__(self, 'obstacles', obstacles)
        if self.scene_class == 'A_clear':
            if obstacles or self.kinematic_entity or self.dynamic_entity \
                    or self.degradation or self.disturbance:
                raise ValueError('A_clear must not carry obstacle/degradation payload')
        if self.scene_class == 'B_static':
            if len(obstacles) != 2 or any(item.kind != 'static' for item in obstacles):
                raise ValueError('B_static needs exactly two static obstacles')
        if self.scene_class == 'C_dynamic':
            if self.kinematic_entity is None or self.dynamic_entity is None:
                raise ValueError('C_dynamic needs kinematic and dynamic entities')
        if self.scene_class == 'D_observation' and self.degradation is None:
            raise ValueError('D_observation needs a degradation spec')
        if self.scene_class == 'E_disturbance' and self.disturbance is None:
            raise ValueError('E_disturbance needs a disturbance spec')

    def to_dict(self):
        return {
            'scenario_id': self.scenario_id,
            'scene_class': self.scene_class,
            'seed': self.seed,
            'start_position_world_m': list(self.start_position_world_m),
            'start_yaw_rad': self.start_yaw_rad,
            'goal_position_world_m': list(self.goal_position_world_m),
            'distance_m': self.distance_m,
            'bearing_rad': self.bearing_rad,
            'distance_bin': self.distance_bin,
            'bearing_bin': self.bearing_bin,
            'obstacles': [obstacle.__dict__ for obstacle in self.obstacles],
            'kinematic_entity': (None if self.kinematic_entity is None
                                 else self.kinematic_entity.__dict__),
            'dynamic_entity': (None if self.dynamic_entity is None
                               else self.dynamic_entity.__dict__),
            'degradation': (None if self.degradation is None
                            else self.degradation.__dict__),
            'disturbance': (None if self.disturbance is None
                            else self.disturbance.__dict__),
        }

    @classmethod
    def from_dict(cls, payload):
        def obstacle(item):
            return None if item is None else ObstacleSpec(
                kind=item['kind'],
                center_world_m=tuple(item['center_world_m']),
                size_m=tuple(item['size_m']),
                velocity_world_mps=tuple(item.get('velocity_world_mps', (0, 0, 0))))

        def dynamic(item):
            return None if item is None else DynamicEntitySpec(
                radius_m=item['radius_m'], mass_kg=item['mass_kg'],
                center_world_m=tuple(item['center_world_m']),
                velocity_world_mps=tuple(item['velocity_world_mps']))

        def degradation(item):
            return None if item is None else DegradationSpec(**item)

        def disturbance(item):
            return None if item is None else DisturbanceSpec(
                force_body_n=tuple(item['force_body_n']),
                torque_body_nm=tuple(item['torque_body_nm']),
                start_s=item['start_s'], duration_s=item['duration_s'],
                ramp_s=item.get('ramp_s', 0.1))

        return cls(
            scenario_id=payload['scenario_id'],
            scene_class=payload['scene_class'], seed=payload['seed'],
            start_position_world_m=tuple(payload['start_position_world_m']),
            start_yaw_rad=payload['start_yaw_rad'],
            goal_position_world_m=tuple(payload['goal_position_world_m']),
            distance_m=payload['distance_m'], bearing_rad=payload['bearing_rad'],
            distance_bin=payload['distance_bin'],
            bearing_bin=payload['bearing_bin'],
            obstacles=tuple(obstacle(item) for item in payload['obstacles']),
            kinematic_entity=obstacle(payload['kinematic_entity']),
            dynamic_entity=dynamic(payload['dynamic_entity']),
            degradation=degradation(payload['degradation']),
            disturbance=disturbance(payload['disturbance']))


BIN_INTERVALS = {
    'near': (DISTANCE_RANGE_M[0], DISTANCE_EDGES_M[0]),
    'mid': (DISTANCE_EDGES_M[0], DISTANCE_EDGES_M[1]),
    'far': (DISTANCE_EDGES_M[1], DISTANCE_RANGE_M[1]),
}
BEARING_INTERVALS = {
    'front': (-BEARING_EDGES_RAD[0], BEARING_EDGES_RAD[0]),
    'side': (BEARING_EDGES_RAD[0], BEARING_EDGES_RAD[1]),
    'rear': (BEARING_EDGES_RAD[1], math.pi),
}


def _class_payload(rng, scene_class, start, goal, horizontal_distance, theta,
                  spec):
    if scene_class == 'A_clear':
        return {}
    if scene_class == 'B_static':
        if horizontal_distance <= 2 * CLEARANCE_M:
            return None
        direction = (math.cos(theta), math.sin(theta))
        perpendicular = (-math.sin(theta), math.cos(theta))
        fraction_low = CLEARANCE_M / horizontal_distance
        fraction_high = 1.0 - CLEARANCE_M / horizontal_distance
        if fraction_low >= fraction_high:
            return None
        obstacles = []
        for index, size in enumerate(OBSTACLE_SIZES_M):
            fraction = rng.uniform(fraction_low, fraction_high)
            lateral = rng.uniform(-0.05, 0.05)
            center = (start[0] + fraction * horizontal_distance * direction[0]
                      + lateral * perpendicular[0],
                      start[1] + fraction * horizontal_distance * direction[1]
                      + lateral * perpendicular[1],
                      size[2] / 2.0)
            obstacles.append(ObstacleSpec(kind='static',
                                          center_world_m=center, size_m=size))
        return {'obstacles': tuple(obstacles)}
    if scene_class == 'C_dynamic':
        if horizontal_distance <= 2 * CLEARANCE_M:
            return None
        direction = (math.cos(theta), math.sin(theta))
        perpendicular = (-math.sin(theta), math.cos(theta))
        fraction = rng.uniform(0.45, 0.55)
        crossing = (start[0] + fraction * horizontal_distance * direction[0],
                    start[1] + fraction * horizontal_distance * direction[1],
                    0.45)
        side = 1.0 if rng.random() < 0.5 else -1.0
        kinematic_center = (crossing[0] + side * 1.0 * perpendicular[0],
                            crossing[1] + side * 1.0 * perpendicular[1], 0.45)
        speed = rng.uniform(0.2, 0.4)
        kinematic = ObstacleSpec(
            kind='kinematic', center_world_m=kinematic_center,
            size_m=KINEMATIC_SIZE_M,
            velocity_world_mps=(-side * speed * perpendicular[0],
                                -side * speed * perpendicular[1], 0.0))
        dynamic_side = -side
        dynamic = DynamicEntitySpec(
            radius_m=DYNAMIC_RADIUS_M, mass_kg=DYNAMIC_MASS_KG,
            center_world_m=(crossing[0] + dynamic_side * 0.6 * perpendicular[0],
                            crossing[1] + dynamic_side * 0.6 * perpendicular[1], 1.1),
            velocity_world_mps=(-dynamic_side * rng.uniform(0.4, 0.6) * perpendicular[0],
                                -dynamic_side * rng.uniform(0.4, 0.6) * perpendicular[1],
                                rng.uniform(0.1, 0.3)))
        return {'kinematic_entity': kinematic, 'dynamic_entity': dynamic}
    if scene_class == 'D_observation':
        return {'degradation': DegradationSpec(
            position_noise_std_m=rng.uniform(*spec.position_noise_range_m),
            velocity_noise_std_mps=rng.uniform(*spec.velocity_noise_range_mps),
            delay_steps=rng.choice(spec.delay_steps_choices),
            dropout_probability=rng.uniform(*spec.dropout_probability_range),
            max_stale_s=spec.max_stale_s)}
    if scene_class == 'E_disturbance':
        angle = rng.uniform(0.0, 2.0 * math.pi)
        magnitude = rng.uniform(*spec.disturbance_force_range_n)
        torque = rng.uniform(*spec.disturbance_torque_range_nm)
        return {'disturbance': DisturbanceSpec(
            force_body_n=(magnitude * math.cos(angle),
                          magnitude * math.sin(angle), 0.0),
            torque_body_nm=(0.0, 0.0, torque),
            start_s=rng.uniform(*spec.disturbance_start_range_s),
            duration_s=rng.uniform(*spec.disturbance_duration_range_s))}
    raise ValueError('unknown scene class: ' + str(scene_class))


def generate_layered_scenarios(scene_class, count, *, base_seed, spec=None):
    if scene_class not in SCENE_CLASSES:
        raise ValueError('unknown scene class: ' + str(scene_class))
    if count != sum(sum(row) for row in STRATA_QUOTAS):
        raise ValueError('count must equal the quota sum (25)')
    _counter(base_seed, 'base_seed')
    spec = spec if spec is not None else RandomizationSpecV2()
    if not isinstance(spec, RandomizationSpecV2):
        raise ValueError('spec must be a RandomizationSpecV2')
    rng = random.Random((base_seed + SCENE_CLASSES.index(scene_class) * 100000))
    scenarios = []
    attempts = 0
    for row, distance_bin in enumerate(DISTANCE_BINS):
        for col, bearing_bin in enumerate(BEARING_BINS):
            for _ in range(STRATA_QUOTAS[row][col]):
                while True:
                    attempts += 1
                    if attempts > 200000:
                        raise ValueError('could not sample legal layered scenarios')
                    start = (rng.uniform(*spec.start_xy_range_m),
                             rng.uniform(*spec.start_xy_range_m),
                             rng.uniform(*spec.start_z_range_m))
                    yaw = rng.uniform(*spec.start_yaw_range_rad)
                    low, high = BIN_INTERVALS[distance_bin]
                    distance = rng.uniform(max(low, DISTANCE_RANGE_M[0]),
                                           min(high, DISTANCE_RANGE_M[1]))
                    bearing_low, bearing_high = BEARING_INTERVALS[bearing_bin]
                    if bearing_bin == 'rear' and rng.random() < 0.5:
                        bearing = rng.uniform(-bearing_high, -bearing_low)
                    else:
                        bearing = rng.uniform(bearing_low, bearing_high)
                    theta = _wrap(yaw + bearing)
                    dz = rng.uniform(*spec.vertical_offset_range_m)
                    horizontal = math.sqrt(max(distance ** 2 - dz ** 2, 1e-9))
                    goal = (start[0] + horizontal * math.cos(theta),
                            start[1] + horizontal * math.sin(theta),
                            start[2] + dz)
                    if not spec.goal_z_range_m[0] <= goal[2] <= spec.goal_z_range_m[1]:
                        continue
                    payload = _class_payload(rng, scene_class, start, goal,
                                             horizontal, theta, spec)
                    if payload is None:
                        continue
                    allowed = True
                    for obstacle in payload.get('obstacles', ()):
                        if math.dist(start[:2], obstacle.center_world_m[:2]) <= CLEARANCE_M \
                                or math.dist(goal[:2], obstacle.center_world_m[:2]) <= CLEARANCE_M:
                            allowed = False
                    for key in ('kinematic_entity', 'dynamic_entity'):
                        entity = payload.get(key)
                        if entity is not None and math.dist(
                                start[:2], entity.center_world_m[:2]) <= CLEARANCE_M:
                            allowed = False
                    if not allowed:
                        continue
                    scenarios.append(LayeredScenario(
                        scenario_id='{}-{}-{:03d}'.format(scene_class, base_seed,
                                                          len(scenarios)),
                        scene_class=scene_class, seed=base_seed + len(scenarios),
                        start_position_world_m=start, start_yaw_rad=yaw,
                        goal_position_world_m=goal, distance_m=distance,
                        bearing_rad=bearing,
                        distance_bin=distance_bin_for_v2(distance),
                        bearing_bin=bearing_bin_for_v2(bearing), **payload))
                    break
    return tuple(scenarios)


def _spec_dict(spec):
    result = {}
    for name in ('start_xy_range_m', 'start_z_range_m', 'start_yaw_range_rad',
                 'distance_range_m', 'vertical_offset_range_m', 'goal_z_range_m',
                 'position_noise_range_m', 'velocity_noise_range_mps',
                 'dropout_probability_range', 'disturbance_force_range_n',
                 'disturbance_torque_range_nm', 'disturbance_start_range_s',
                 'disturbance_duration_range_s'):
        result[name] = list(getattr(spec, name))
    result['delay_steps_choices'] = list(spec.delay_steps_choices)
    result['max_stale_s'] = spec.max_stale_s
    return result


def layered_manifest_sha256(payload):
    body = {key: value for key, value in payload.items() if key != 'content_sha256'}
    encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def build_layered_manifest(scenarios_by_class, *, spec, generated_at):
    payload = {
        'schema_version': LAYERED_SCENARIO_SCHEMA_ID,
        'generated_at': generated_at,
        'spec': _spec_dict(spec),
        'class_specs': {
            name: {
                'description': CLASS_SPECS[name].description,
                'capability_requirement': CLASS_SPECS[name].capability_requirement,
                'input_permission': CLASS_SPECS[name].input_permission,
                'expected_outcomes': CLASS_SPECS[name].expected_outcomes,
                'boundary': CLASS_SPECS[name].boundary,
            }
            for name in SCENE_CLASSES},
        'quota': {'distance_bins': list(DISTANCE_BINS),
                  'bearing_bins': list(BEARING_BINS),
                  'quota': [list(row) for row in STRATA_QUOTAS]},
        'classes': {name: [scenario.to_dict() for scenario in scenarios_by_class[name]]
                    for name in SCENE_CLASSES},
    }
    payload['content_sha256'] = layered_manifest_sha256(payload)
    return payload


def write_layered_manifest(path, manifest):
    if manifest.get('content_sha256') != layered_manifest_sha256(manifest):
        raise ValueError('layered manifest hash does not match its content')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')
    return path


def load_layered_manifest(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != LAYERED_SCENARIO_SCHEMA_ID:
        raise ValueError('unsupported layered scenario schema: '
                         + str(payload.get('schema_version')))
    if payload.get('content_sha256') != layered_manifest_sha256(payload):
        raise ValueError('layered manifest hash mismatch: ' + str(path))
    return payload


def layered_scenarios_from_manifest(manifest):
    return {name: tuple(LayeredScenario.from_dict(item)
                        for item in manifest['classes'][name])
            for name in SCENE_CLASSES}

NEARBY_MARGIN_M = 0.3


def nearby_asset_names(scenario, robot_position_world_m, margin=NEARBY_MARGIN_M):
    """Asset names whose collision volume is within margin of the robot."""
    position = tuple(float(value) for value in robot_position_world_m)
    names = []
    for index, obstacle in enumerate(scenario.obstacles):
        reach = max(obstacle.size_m) / 2.0 + margin
        if math.dist(position, obstacle.center_world_m) <= reach:
            names.append('obs{}'.format(index))
    if scenario.kinematic_entity is not None:
        obstacle = scenario.kinematic_entity
        reach = max(obstacle.size_m) / 2.0 + margin
        if math.dist(position, obstacle.center_world_m) <= reach:
            names.append('mover')
    if scenario.dynamic_entity is not None:
        entity = scenario.dynamic_entity
        if math.dist(position, entity.center_world_m) <= entity.radius_m + margin:
            names.append('ball')
    return tuple(names)