"""Map contract loading for the RMUC2027 USD terrain."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

MAP_CONTRACT_VERSION = 'boom_birds.map_contract.v1'


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class MapContract:
    asset_id: str
    preview_path: Path
    terrain_path: Path
    preview_sha256: str
    terrain_sha256: str
    meters_per_unit: float
    up_axis: str
    world_frame: str
    body_frame: str
    bounds_min_m: tuple
    bounds_max_m: tuple
    evaluator_version: str


@dataclass(frozen=True)
class MapCase:
    case_id: str
    kind: str
    start_position_world_m: tuple
    start_yaw_rad: float
    goal_position_world_m: tuple | None
    ground_z_m: float
    timeout_s: float
    repeats: int
    command_forward_left_up_yawrate: tuple = (0.0, 0.0, 0.0, 0.0)
    hover_altitude_m: float = 1.0
    hover_time_s: float = 1.0
    landing_speed_max_mps: float = 0.25


def load_map_contract(config_path, local_path=None):
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    if config.get('contract_version') != MAP_CONTRACT_VERSION:
        raise ValueError('unsupported map contract version')
    units = config.get('coordinate_contract', {})
    if units.get('units') != 'm' or units.get('up_axis') != 'Z':
        raise ValueError('map must be metres and Z-up')
    assets = config.get('assets', {})
    local_path = Path(local_path) if local_path is not None else None
    if local_path is None:
        raise ValueError('local map path config is required')
    local = yaml.safe_load(local_path.read_text(encoding='utf-8'))
    root = Path(local['asset_root'])
    preview = root / assets['preview_rel']
    terrain = root / assets['terrain_rel']
    for path in (preview, terrain):
        if not path.exists():
            raise FileNotFoundError(str(path))
    preview_sha = sha256_file(preview)
    terrain_sha = sha256_file(terrain)
    if preview_sha != assets['preview_sha256']:
        raise ValueError('preview hash mismatch')
    if terrain_sha != assets['terrain_sha256']:
        raise ValueError('terrain hash mismatch')
    bounds = config['bounds_m']
    return MapContract(
        asset_id=config['asset_id'],
        preview_path=preview,
        terrain_path=terrain,
        preview_sha256=preview_sha,
        terrain_sha256=terrain_sha,
        meters_per_unit=float(units['meters_per_unit']),
        up_axis=units['up_axis'],
        world_frame=units['world_frame'],
        body_frame=units['body_frame'],
        bounds_min_m=tuple(float(value) for value in bounds['min']),
        bounds_max_m=tuple(float(value) for value in bounds['max']),
        evaluator_version=config['evaluation']['version'],
    )


def load_map_cases(path, contract=None):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != 'boom_birds.map_cases.v1':
        raise ValueError('unsupported map case schema')
    cases = []
    for item in payload['cases']:
        kind = item['kind']
        if kind not in ('reach', 'takeoff_landing', 'contact'):
            raise ValueError('unknown map case kind: ' + str(kind))
        start = tuple(float(value) for value in item['start_position_world_m'])
        if len(start) != 3:
            raise ValueError('start position must be three values')
        goal = item.get('goal_position_world_m')
        if goal is not None:
            goal = tuple(float(value) for value in goal)
            if len(goal) != 3:
                raise ValueError('goal position must be three values')
        case = MapCase(
            case_id=item['case_id'], kind=kind, start_position_world_m=start,
            start_yaw_rad=float(item['start_yaw_rad']),
            goal_position_world_m=goal, ground_z_m=float(item['ground_z_m']),
            timeout_s=float(item['timeout_s']), repeats=int(item['repeats']),
            command_forward_left_up_yawrate=tuple(
                float(value) for value in item.get(
                    'command_forward_left_up_yawrate', (0.0, 0.0, 0.0, 0.0))),
            hover_altitude_m=float(item.get('hover_altitude_m', 1.0)),
            hover_time_s=float(item.get('hover_time_s', 1.0)),
            landing_speed_max_mps=float(item.get('landing_speed_max_mps', 0.25)))
        if contract is not None:
            low = contract.bounds_min_m
            high = contract.bounds_max_m
            for name, point in (('start', start), ('goal', goal)):
                if point is None:
                    continue
                if not (low[0] <= point[0] <= high[0]
                        and low[1] <= point[1] <= high[1]
                        and low[2] - 0.5 <= point[2] <= high[2]):
                    raise ValueError(name + ' outside map bounds')
        if kind in ('reach', 'contact') and goal is None and kind == 'reach':
            raise ValueError('reach case needs a goal')
        if kind == 'reach' and goal is None:
            raise ValueError('reach case needs a goal')
        if case.repeats < 2:
            raise ValueError('frozen case needs at least two repeats')
        cases.append(case)
    return cases


def case_payload(case):
    return {
        'case_id': case.case_id, 'kind': case.kind,
        'start_position_world_m': list(case.start_position_world_m),
        'start_yaw_rad': case.start_yaw_rad,
        'goal_position_world_m': (None if case.goal_position_world_m is None
                                  else list(case.goal_position_world_m)),
        'ground_z_m': case.ground_z_m, 'timeout_s': case.timeout_s,
        'repeats': case.repeats,
        'command_forward_left_up_yawrate': list(
            case.command_forward_left_up_yawrate),
        'hover_altitude_m': case.hover_altitude_m,
        'hover_time_s': case.hover_time_s,
        'landing_speed_max_mps': case.landing_speed_max_mps,
    }
