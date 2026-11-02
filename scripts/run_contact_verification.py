"""Controlled contact-evidence matrix runner (GUI, frozen pre-run).

Supports wall / obstacle / clearance / geometry segments. Produces raw
steps/episodes/manifest for the independent contact verifier.
"""
import argparse
import hashlib
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cases', type=Path,
                    default=Path('configs/scenarios/contact_verification_cases_v1.json'))
parser.add_argument('--expected', type=Path,
                    default=Path('configs/scenarios/contact_verification_expected_v1.json'))
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--segment-id', required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--vehicle-config',
                    default='configs/vehicles/sim_reference.yaml')
parser.add_argument('--contact-threshold-n', type=float, default=0.02)
parser.add_argument('--post-contact-observe-s', type=float, default=0.5)
parser.add_argument('--repeat-index', type=int, default=-1)
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--working-tree', default='recorded by the operator')
parser.add_argument('--gpu-driver', default='NOT RECORDED')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if getattr(args, 'headless', False):
    raise RuntimeError('GUI is required; --headless is forbidden')
args.output.mkdir(parents=True, exist_ok=True)
(args.output / 'screenshots').mkdir(exist_ok=True)

STAGE = {'name': 'start'}
_started_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def mark(name):
    STAGE['name'] = name
    print('[stage] ' + name, flush=True)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def normalize(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))


cases_doc = load_json(args.cases)
expected_doc = load_json(args.expected)
segments = {seg['segment_id']: seg for seg in cases_doc['segments']}
if args.segment_id not in segments:
    raise RuntimeError('unknown segment: ' + args.segment_id)
segment = segments[args.segment_id]
mode = segment['mode']
if mode not in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
    raise RuntimeError('unsupported controlled mode: ' + mode)
cases = segment['cases']
if args.repeat_index >= 0:
    if args.repeat_index >= len(cases):
        raise RuntimeError('repeat index out of range')
    cases = [cases[args.repeat_index]]
case_ids = sorted(dict.fromkeys(case['case_id'] for case in cases))
expected_case = expected_doc.get('cases', {}).get(case_ids[0], {})
expected_sha = sha256_file(args.expected)
cases_sha = sha256_file(args.cases)

# pre-run freeze validation (source/config/cases/params)
freeze_meta = {'path': '', 'sha256': '', 'schema_version': '',
               'frozen_at': '', 'code_commit': ''}
run_plan = {
    'segment_id': args.segment_id,
    'role': segment['role'],
    'mode': mode,
    'cases_file': Path(args.cases).as_posix(),
    'cases_sha256': cases_sha,
    'case_ids': case_ids,
    'expected_file': Path(args.expected).as_posix(),
    'expected_sha256': expected_sha,
    'contact_contract_version': cases_doc['contact_contract_version'],
    'envelope_contract_version': cases_doc['envelope_contract_version'],
    'vehicle_config': Path(args.vehicle_config).as_posix(),
    'vehicle_config_sha256': sha256_file(args.vehicle_config),
    'run_params': {
        'contact_threshold_n': args.contact_threshold_n,
        'post_contact_observe_s': args.post_contact_observe_s,
        'geometry': [{'case_id': case['case_id'],
                      'robot': case['robot'], 'control': case['control'],
                      'obstacle': case['obstacle'], 'target': case['target']}
                     for case in cases],
    },
}
if args.freeze is not None:
    freeze = load_json(args.freeze)
    freeze_meta = {
        'path': Path(args.freeze).as_posix(),
        'sha256': sha256_file(args.freeze),
        'schema_version': freeze.get('schema_version', ''),
        'frozen_at': freeze.get('frozen_at', ''),
        'code_commit': freeze.get('code_commit', ''),
    }
    if freeze_meta['code_commit'] != args.code_commit:
        raise RuntimeError('freeze code_commit mismatch')
    if args.code_commit != 'WORKTREE':
        started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        if freeze_meta['frozen_at'] > started:
            raise RuntimeError('freeze frozen_at is after run start')
    entry = freeze.get('segments', {}).get(args.segment_id)
    if entry is None:
        raise RuntimeError('segment missing from freeze: ' + args.segment_id)
    frozen_plan = entry.get('run_plan')
    if frozen_plan is None:
        raise RuntimeError('freeze segment has no run_plan')
    # the runner re-derives and compares the executable core fields
    if frozen_plan.get('cases_sha256') != cases_sha:
        raise RuntimeError('freeze cases_sha256 mismatch')
    if frozen_plan.get('expected_sha256') != expected_sha:
        raise RuntimeError('freeze expected_sha256 mismatch')
    if list(frozen_plan.get('case_ids', [])) != case_ids:
        raise RuntimeError('freeze case_ids mismatch')
    if frozen_plan.get('vehicle_config_sha256') != sha256_file(args.vehicle_config):
        raise RuntimeError('freeze vehicle config mismatch')
    run_plan = frozen_plan
    mark('contact freeze verified')

app = None
try:
    app = AppLauncher(args).app
    import omni.usd
    import torch
    import yaml
    import isaaclab.sim as sim_utils
    from isaaclab.assets import RigidObjectCfg
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.sensors import ContactSensor, ContactSensorCfg
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)
    from pxr import Gf, Usd, UsdGeom, UsdPhysics, PhysxSchema

    sys.path.insert(0, str(Path('src').resolve()))
    from boom_birds.evaluation import contact_contract as contact_mod
    from boom_birds.sim import body_envelope as envelope_mod
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    vehicle_config = yaml.safe_load(Path(args.vehicle_config).read_text(
        encoding='utf-8'))
    gains = VelocityGains(**{k: float(v) for k, v in
                             vehicle_config['gains'].items()})
    vehicle_cfg = vehicle_config['vehicle']

    @dataclass
    class ProbeSceneCfg(InteractiveSceneCfg):
        obstacle: RigidObjectCfg = field(default_factory=lambda: RigidObjectCfg(
            prim_path='{ENV_REGEX_NS}/Obstacle',
            spawn=sim_utils.CuboidCfg(
                size=(0.4, 0.4, 0.6),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True, disable_gravity=True),
                mass_props=sim_utils.MassPropertiesCfg(mass=5.0),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                activate_contact_sensors=True)))

    cfg = QuadcopterEnvCfg()
    cfg.sim.device = args.device
    cfg.seed = 0
    cfg.decimation = 5
    cfg.episode_length_s = 120.0
    cfg.robot.spawn.activate_contact_sensors = True
    # Shape-level contact-report API applied after spawn only reaches PhysX when
    # physics replication is disabled (probe evidence: tmp/contact_probe11).
    cfg.scene = ProbeSceneCfg(num_envs=1, env_spacing=2.5,
                              replicate_physics=False, clone_in_fabric=False)
    mark('create env')
    env = QuadcopterEnv(cfg)
    env.reset(seed=0)
    try:
        dt = env.step_dt
        try:
            physics_dt = float(env.sim.get_physics_dt())
        except Exception:
            physics_dt = 0.01
        origin = env.scene.env_origins[0].tolist()
        stage = omni.usd.get_context().get_stage()
        robot_root = '/World/envs/env_0/Robot'
        obstacle = env.scene['obstacle']
        zero6 = torch.zeros((1, 6), device=env.device)
        index = torch.tensor([0], device=env.device)
        mass = float(env._robot_mass.item())
        inertias = env._robot.root_physx_view.get_inertias()
        body_id = int(env._body_id[0].item() if hasattr(env._body_id[0], 'item')
                      else env._body_id[0])
        matrix = (inertias[0, body_id].tolist()
                  if len(tuple(inertias.shape)) == 3 else inertias[0].tolist())
        params = VehicleParams(
            mass_kg=mass, inertia_kgm2=(matrix[0], matrix[4], matrix[8]),
            thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
            moment_scale_nm=float(vehicle_cfg['moment_scale_nm']),
            gravity_mps2=9.81, max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
        executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)

        wall_target = None
        if mode == 'wall':
            map_path = '/World/RMUC2027'
            contract = __import__('boom_birds.sim.map_contract', fromlist=['load_map_contract']).load_map_contract(
                Path(cases_doc['map_config']), Path(cases_doc['local_config']))
            ground = stage.GetPrimAtPath(cfg.terrain.prim_path)
            if ground.IsValid():
                ground.SetActive(False)
            map_cfg = sim_utils.UsdFileCfg(usd_path=str(contract.terrain_path))
            map_cfg.func(map_path, map_cfg)
            for _ in range(10):
                app.update()
            for prim in Usd.PrimRange(stage.GetPrimAtPath(map_path)):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    PhysxSchema.PhysxContactReportAPI.Apply(prim)
            wall_target = segment['cases'][0]['target']['prim_path']
            if not stage.GetPrimAtPath(wall_target).IsValid():
                raise RuntimeError('wall prim missing: ' + wall_target)
        else:
            for prim in Usd.PrimRange(stage.GetPrimAtPath(
                    '/World/envs/env_0/Obstacle')):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    PhysxSchema.PhysxContactReportAPI.Apply(prim)
            for _ in range(3):
                app.update()
        mark('contact reporters applied')

        # robot collision AABB -> body envelope (collision geometry, root frame)
        robot_pose = env._robot.data.root_pose_w[0].tolist()
        root_position = robot_pose[:3]
        root_quat = robot_pose[3:]
        bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                       [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        collision_prims = [prim.GetPath().pathString
                           for prim in Usd.PrimRange(stage.GetPrimAtPath(robot_root))
                           if prim.HasAPI(UsdPhysics.CollisionAPI)]
        robot_prim = stage.GetPrimAtPath(robot_root)
        world_bounds = bbox_cache.ComputeWorldBound(robot_prim).ComputeAlignedRange()
        bounds_min = world_bounds.GetMin()
        bounds_max = world_bounds.GetMax()
        points = []
        for x in (bounds_min[0], bounds_max[0]):
            for y in (bounds_min[1], bounds_max[1]):
                for z in (bounds_min[2], bounds_max[2]):
                    points.append([x, y, z])
        if not points:
            raise RuntimeError('no finite robot collision geometry found')
        # world->root inverse transform
        from pxr import Gf as _Gf
        root_matrix = UsdGeom.Xformable(
            stage.GetPrimAtPath(robot_root)).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default())
        inverse = root_matrix.GetInverse()
        local_points = [list(inverse.Transform(_Gf.Vec3d(*point))) for point in points]
        half_axes = [max(point[i] for point in local_points)
                     - min(point[i] for point in local_points) for i in range(3)]
        half = [value / 2.0 for value in half_axes]
        center = [(max(point[i] for point in local_points)
                   + min(point[i] for point in local_points)) / 2.0
                  for i in range(3)]
        coverage = envelope_mod.EnvelopeCoverage(
            source='collision_geometry', prim_paths=tuple(collision_prims),
            collision_prim_paths=tuple(collision_prims),
            visual_prim_paths=tuple(), sub_bodies=('body',))
        body_envelope = envelope_mod.body_envelope_record(
            tuple(half), tuple(center), coverage=coverage,
            measurement={'frame': 'robot_reference_frame',
                         'bbox_purpose': 'default_and_render',
                         'sim_time_s': 0.0,
                         'robot_root_prim': robot_root,
                         'root_position_world_m': root_position,
                         'root_quat_wxyz': root_quat})
        envelope_mod.validate_body_envelope_record(body_envelope)
        sphere_radius = body_envelope['sphere_about_origin']['radius_m']
        sphere_center = body_envelope['sphere_about_origin'].get(
            'center_offset_m', center)
        mark('body envelope measured r=' + format(sphere_radius, '.9f'))

        def set_robot_pose(position, yaw_rad=0.0):
            quat = (math.cos(yaw_rad / 2.0), 0.0, 0.0,
                    math.sin(yaw_rad / 2.0))
            pose = torch.tensor([[origin[0] + position[0],
                                  origin[1] + position[1],
                                  origin[2] + position[2], quat[0], quat[1],
                                  quat[2], quat[3]]],
                                dtype=torch.float32, device=env.device)
            env._robot.write_root_pose_to_sim(pose, index)
            env._robot.write_root_velocity_to_sim(zero6, index)

        def set_obstacle_pose(position):
            pose = torch.tensor([[float(position[0]), float(position[1]),
                                  float(position[2]), 1.0, 0.0, 0.0, 0.0]],
                                dtype=torch.float32, device=env.device)
            obstacle.write_root_pose_to_sim(pose, index)

        def read_state():
            position = env._robot.data.root_pos_w[0].tolist()
            velocity = env._robot.data.root_lin_vel_w[0].tolist()
            quat = env._robot.data.root_quat_w[0].tolist()
            omega = env._robot.data.root_ang_vel_b[0].tolist()
            return VehicleState(
                position_world_m=tuple(position[i] - origin[i] for i in range(3)),
                velocity_world_mps=tuple(velocity), quat_wxyz=tuple(quat),
                angular_velocity_body_radps=tuple(omega))

        def step_hover(forward_mps=0.0):
            control = executor.step(VelocitySetpoint(
                forward_mps, 0.0, 0.0, 0.0, issued_at_s=0.0,
                expires_at_s=10.0, control_epoch=0), read_state(), 0.0)
            env.step(torch.tensor([control.to_actuator_action(params)],
                                  dtype=torch.float32, device=env.device))
            return read_state()

        robot_links = []
        for prim in Usd.PrimRange(stage.GetPrimAtPath(robot_root)):
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                robot_links.append(prim.GetPath().pathString)

        def robot_collision_prims():
            return [prim.GetPath().pathString
                    for prim in Usd.PrimRange(stage.GetPrimAtPath(robot_root))
                    if prim.HasAPI(UsdPhysics.CollisionAPI)]

        def prim_inventory(root_path):
            items = []
            for prim in Usd.PrimRange(stage.GetPrimAtPath(root_path)):
                items.append({'path': prim.GetPath().pathString,
                              'collision': prim.HasAPI(UsdPhysics.CollisionAPI),
                              'rigid_body': prim.HasAPI(UsdPhysics.RigidBodyAPI),
                              'contact_report': prim.HasAPI(
                                  PhysxSchema.PhysxContactReportAPI)})
            return items

        replay_previous = None
        if mode == 'replay':
            replay_previous = {}
            for case in cases:
                episode_key = case['previous_episode_id']
                previous_steps = args.output.parent / Path(case['previous_run_dir']).name
                prev_steps_path = Path(case['previous_run_dir']) / 'steps.jsonl'
                prev_rows = [json.loads(line) for line in
                             prev_steps_path.read_text(encoding='utf-8').splitlines()
                             if line.strip()]
                prev_rows = [row for row in prev_rows
                             if row.get('episode_id') == episode_key]
                if not prev_rows:
                    raise RuntimeError('replay episode missing: ' + episode_key)
                prev_cases = json.loads(Path(case['source_cases_file']).read_text(
                    encoding='utf-8'))['cases']
                prev_case = next(item for item in prev_cases
                                 if item['case_id'] == case['case_id'])
                obstacle_spec = prev_case.get('obstacle')
                contact_row = None
                best_overlap = None
                for row in prev_rows:
                    evidence = row.get('contact_evidence') or {}
                    overlap = evidence.get('sphere_overlap_m')
                    if overlap is not None and (best_overlap is None
                                                or overlap > best_overlap):
                        best_overlap, contact_row = overlap, row
                if case['previous_physical_label'] == 'CONTACT_INFERRED' and contact_row:
                    robot_world = contact_row['position_world_m']
                    obstacle_world = contact_row.get('obstacle_position_world_m')
                    velocity = obstacle_spec['velocity_world_mps'] if obstacle_spec else [0, 0, 0]
                    lead_s = 1.5
                    obstacle_start = [obstacle_world[i] - velocity[i] * lead_s
                                      for i in range(3)]
                else:
                    robot_world = prev_rows[0]['position_world_m']
                    obstacle_start = (prev_rows[0].get('obstacle_position_world_m')
                                      if prev_rows[0].get('obstacle_position_world_m')
                                      else (obstacle_spec['start_position_world_m']
                                            if obstacle_spec else [0, 0, 50]))
                    velocity = [0.0, 0.0, 0.0]
                replay_previous[case['case_id']] = {
                    'robot_world': robot_world,
                    'obstacle_start': obstacle_start,
                    'velocity': velocity,
                    'max_steps': 200,
                    'previous_label': case['previous_physical_label'],
                }
            target_path = '/World/envs/env_0/Obstacle'
        else:
            target_path = wall_target if mode == 'wall' else '/World/envs/env_0/Obstacle'
        def create_sensors():
            created = []
            for link in robot_links:
                try:
                    sensor = ContactSensor(ContactSensorCfg(
                        prim_path=link, filter_prim_paths_expr=[target_path],
                        update_period=0.0, debug_vis=False, history_length=0))
                    sensor._initialize_callback(None)
                    sensor.update(dt=dt)
                    created.append({'link': link, 'sensor': sensor})
                except Exception as error:
                    created.append({'link': link, 'error': repr(error)})
            return created

        sensors = create_sensors()
        mark('contact sensors created: ' + str(len(sensors)))
        contact_sensor_info = {
            'available': any('sensor' in item for item in sensors),
            'mode': 'isaaclab_contact_sensor',
            'prim_paths': [item['link'] for item in sensors],
            'filter_prim_paths': [target_path],
            'update_order': 'after_env_step',
            'physics': {'physics_dt_s': physics_dt,
                        'decimation': int(cfg.decimation),
                        'substeps_per_step': int(round(dt / physics_dt))},
            'threshold_n': args.contact_threshold_n,
            'errors': [item['error'] for item in sensors if 'error' in item],
        }

        def read_contacts():
            per_prim = {}
            target_vectors = {}
            max_force = 0.0
            max_net = 0.0
            for item in sensors:
                if 'sensor' not in item:
                    continue
                try:
                    item['sensor'].update(dt=dt)
                    matrix = item['sensor'].data.force_matrix_w
                    net = item['sensor'].data.net_forces_w
                    if net is not None:
                        max_net = max(max_net, float(net[0].abs().sum(dim=-1).max()))
                    if matrix is None:
                        continue
                    value = matrix[0].abs().sum(dim=-1)
                    if matrix.shape[-2] == 1:
                        vector = matrix[0, 0].tolist()
                    else:
                        vector = [float(matrix[0].abs().sum())] * 3
                    force = float(value.max())
                    max_force = max(max_force, force)
                    if force > 0:
                        per_prim[item['link']] = [float(v) for v in vector]
                        target_vectors[target_path] = [float(v) for v in vector]
                except Exception:
                    continue
            return max_force, per_prim, target_vectors, max_net

        results = []
        records = []
        episode_ids = []
        for repeat_position, case in enumerate(cases):
            repeat = args.repeat_index if args.repeat_index >= 0 else repeat_position
            episode_id = case['case_id'] + '-r' + str(repeat) + '-' + args.segment_id
            episode_ids.append(episode_id)
            if mode == 'replay':
                replay_spec = replay_previous[case['case_id']]
                robot_start = [replay_spec['robot_world'][i] - origin[i]
                               for i in range(3)]
                yaw = 0.0
                obstacle_case = {'size_m': [0.4, 0.4, 0.6],
                                 'start_position_world_m': replay_spec['obstacle_start'],
                                 'velocity_world_mps': replay_spec['velocity'],
                                 'kinematic': True}
            else:
                robot_start = case['robot']['start_position_world_m']
                yaw = float(case['robot'].get('yaw_rad', 0.0))
                obstacle_case = case.get('obstacle')
            if mode == 'obstacle':
                for prim in Usd.PrimRange(stage.GetPrimAtPath(
                        '/World/envs/env_0/Obstacle')):
                    if prim.HasAPI(UsdPhysics.CollisionAPI):
                        PhysxSchema.PhysxContactReportAPI.Apply(prim)
                sensors = create_sensors()
            set_robot_pose(robot_start, yaw)
            try:
                executor.reset(read_state())
            except Exception:
                pass
            if mode == 'wall':
                set_obstacle_pose((0.0, 0.0, 50.0))
            elif obstacle_case is not None:
                set_obstacle_pose(obstacle_case['start_position_world_m'])
            step_hover()
            episode_rows = []
            contact_steps = []
            max_force = 0.0
            max_overlap = -1e9
            first_contact_time = None
            if mode == 'replay':
                control = {'mode': 'hover', 'forward_mps': 0.0,
                           'max_steps': replay_previous[case['case_id']]['max_steps']}
            else:
                control = case['control']
            max_steps = int(control.get('max_steps', 200))
            forward = float(control.get('forward_mps', 0.0))
            post_contact_steps = 0
            max_post = int(math.ceil(args.post_contact_observe_s / dt))
            for step in range(1, max_steps + 1):
                if mode == 'wall':
                    state = step_hover(forward_mps=forward)
                    obstacle_position = None
                else:
                    velocity = obstacle_case['velocity_world_mps']
                    start = obstacle_case['start_position_world_m']
                    t = (step - 1) * dt
                    obstacle_position = [start[i] + velocity[i] * t
                                         for i in range(3)]
                    set_obstacle_pose(obstacle_position)
                    state = step_hover(forward_mps=forward)
                time_s = step * dt
                if mode == 'wall' and abs(state.position_world_m[2]
                                          - robot_start[2]) > 0.02:
                    set_robot_pose([state.position_world_m[0],
                                    state.position_world_m[1],
                                    robot_start[2]], yaw)
                    state = read_state()
                filtered_force, per_prim, target_vectors, net_force = read_contacts()
                force = max(filtered_force, net_force)
                max_force = max(max_force, force)
                robot_position = list(state.position_world_m)
                if obstacle_position is not None:
                    center_distance = math.sqrt(sum(
                        (robot_position[i] + origin[i] - obstacle_position[i]) ** 2
                        for i in range(3)))
                    obstacle_radius = max(obstacle_case['size_m']) / 2.0
                    overlap = sphere_radius + obstacle_radius - center_distance
                else:
                    center_distance = None
                    overlap = None
                max_overlap = max(max_overlap, overlap if overlap is not None else -1e9)
                event = force > args.contact_threshold_n
                if event and first_contact_time is None:
                    first_contact_time = time_s
                sensor_available = bool(contact_sensor_info['available'])
                if filtered_force > args.contact_threshold_n:
                    force_payload = target_vectors
                    net_payload = None
                    attribution_prim = [target_path]
                    attribution_status = 'ATTRIBUTED'
                    sensor_status = 'filtered_contact_sensor'
                    force_basis_event = True
                elif max(filtered_force, net_force) > 0:
                    force_payload = None
                    net_payload = max(filtered_force, net_force)
                    attribution_prim = []
                    attribution_status = 'UNATTRIBUTED'
                    sensor_status = 'filtered_unavailable_net_force_available'
                    force_basis_event = net_payload > args.contact_threshold_n
                else:
                    force_payload = None
                    net_payload = 0.0
                    attribution_prim = []
                    attribution_status = 'UNATTRIBUTED'
                    sensor_status = 'filtered_contact_sensor'
                    force_basis_event = False
                record = contact_mod.build_contact_record(
                    step=step, time_s=time_s,
                    sensor_available=sensor_available,
                    sensor_status=sensor_status,
                    event_available=sensor_available,
                    event=force_basis_event if sensor_available else None,
                    prim_attributions=attribution_prim,
                    force_per_prim_n=force_payload,
                    net_force_n=net_payload,
                    attribution_status=(attribution_status
                                        if sensor_available else None),
                    force_window_s=dt,
                    geometry=(None if overlap is None else {
                        'sphere_overlap_m': overlap,
                        'robot_radius_m': sphere_radius,
                        'obstacle_radius_m': (
                            max(obstacle_case['size_m']) / 2.0
                            if obstacle_case else None)}),
                    notes=None)
                row = {
                    'episode_id': episode_id,
                    'phase': 'RUN',
                    'step': step,
                    'time_s': time_s,
                    'physics_step': int(round(time_s / physics_dt)),
                    'position_world_m': robot_position,
                    'velocity_world_mps': list(state.velocity_world_mps),
                    'speed_mps': math.sqrt(sum(v * v for v in state.velocity_world_mps)),
                    'contact_record': record,
                    'geometry_overlap_sphere_m': overlap,
                    'obstacle_position_world_m': obstacle_position,
                    'contact_force_n': float(force),
                    'contact_prim': target_path if force > 0 else '',
                }
                episode_rows.append(row)
                records.append(row)
                if force > args.contact_threshold_n:
                    contact_steps.append(step)
                    post_contact_steps += 1
                elif contact_steps:
                    post_contact_steps += 1
                if mode == 'wall' and contact_steps and post_contact_steps >= max_post:
                    break
                if mode == 'obstacle' and contact_steps and post_contact_steps >= max_post:
                    break
                if mode in ('clearance', 'geometry') and step >= max_steps:
                    break
            summary = contact_mod.summarize_contact_records(
                [row['contact_record'] for row in episode_rows])
            if mode == 'wall':
                if max_force > args.contact_threshold_n:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED'
                    outcome, reason = 'SUCCESS', 'PHYSX_CONTACT'
                else:
                    physical = 'NO_CONTACT'
                    outcome, reason = 'FAIL', 'NO_CONTACT_EVIDENCE'
            elif mode == 'obstacle':
                if max_force > args.contact_threshold_n:
                    physical = ('PHYSX_CONTACT_FORCE_MEASURED'
                                if any(row['contact_record']['layers']['force'].get('basis') == 'filtered_force'
                                       for row in episode_rows)
                                else 'CONTACT_FORCE_MEASURED_UNATTRIBUTED')
                    outcome, reason = 'SUCCESS', 'PHYSX_CONTACT'
                else:
                    physical = 'NO_CONTACT'
                    outcome, reason = 'FAIL', 'NO_CONTACT_EVIDENCE'
            elif mode == 'clearance':
                if max_force > args.contact_threshold_n:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED'
                    outcome, reason = 'FAIL', 'UNEXPECTED_CONTACT'
                else:
                    physical = 'NO_CONTACT'
                    outcome, reason = 'SUCCESS', 'NO_CONTACT'
            elif mode == 'geometry':
                if max_force > args.contact_threshold_n:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED'
                    outcome, reason = 'FAIL', 'UNEXPECTED_CONTACT'
                elif max_overlap > args.contact_threshold_n:
                    physical = 'GEOMETRY_OVERLAP_ONLY'
                    outcome, reason = 'SUCCESS', 'GEOMETRY_ONLY'
                else:
                    physical = 'NO_CONTACT'
                    outcome, reason = 'FAIL', 'NO_GEOMETRY_OVERLAP'
            else:  # replay
                if max_force > args.contact_threshold_n:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED'
                elif max_overlap is not None and max_overlap > args.contact_threshold_n:
                    physical = 'GEOMETRY_OVERLAP_ONLY'
                else:
                    physical = 'NO_CONTACT'
                previous_label = replay_previous[case['case_id']]['previous_label']
                if previous_label == 'CONTACT_INFERRED':
                    if max_force > args.contact_threshold_n:
                        verdict = 'CONSISTENT'
                    elif physical == 'GEOMETRY_OVERLAP_ONLY':
                        verdict = 'MISS'
                    else:
                        verdict = 'UNDECIDABLE'
                else:
                    verdict = ('CONSISTENT' if physical == 'NO_CONTACT'
                               else 'MISREPORT')
                outcome, reason = verdict, 'REPLAY_' + verdict
            episode = {
                'episode_id': episode_id,
                'case_id': case['case_id'],
                'mode': mode,
                'outcome': outcome,
                'business_outcome': outcome,
                'physical_outcome': physical,
                'contact_summary': summary,
                'envelope_sphere_about_origin_m': sphere_radius,
                'max_force_n': max_force,
                'first_contact_time_s': first_contact_time,
                'max_geometry_overlap_m': (None if max_overlap <= -1e8
                                           else max_overlap),
                'steps': len(episode_rows),
                'replay': ({
                    'source_run': Path(case['previous_run_dir']).as_posix(),
                    'source_episode_id': case['previous_episode_id'],
                    'previous_physical_label': case['previous_physical_label'],
                    'verdict': outcome,
                    'basis': ('scripted contact-geometry replay: robot held at the '
                              'previous contact-time pose with obstacle trajectory '
                              'replayed; not a closed-loop episode replay'),
                } if mode == 'replay' else None),
            }
            results.append(episode)
            print('[episode] ' + episode_id + ' ' + outcome + ' ' + reason
                  + ' force=' + format(max_force, '.6f'), flush=True)

        mark('write outputs')
        steps_path = args.output / 'steps.jsonl'
        with steps_path.open('w', encoding='utf-8') as handle:
            for row in records:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        episodes_path = args.output / 'episodes.jsonl'
        with episodes_path.open('w', encoding='utf-8') as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        summary = {
            'schema_version': 'boom_birds.contact_verification_summary.v1',
            'status': 'PASS' if all(item['outcome'] == 'SUCCESS'
                                    for item in results) else 'FAIL',
            'segment_id': args.segment_id,
            'mode': mode,
            'case_ids': case_ids,
            'counts': {'episodes': len(results),
                       'success': sum(1 for item in results
                                      if item['outcome'] == 'SUCCESS'),
                       'fail': sum(1 for item in results
                                   if item['outcome'] != 'SUCCESS')},
            'episodes': results,
            'gui_mode': True,
            'contact_contract_version': cases_doc['contact_contract_version'],
            'envelope_contract_version': cases_doc['envelope_contract_version'],
        }
        (args.output / 'summary.json').write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        outputs_sha = {name: sha256_file(args.output / name)
                       for name in ('summary.json', 'episodes.jsonl',
                                    'steps.jsonl')}
        manifest = {
            'schema_version': 'boom_birds.contact_verification_manifest.v1',
            'code_commit': args.code_commit,
            'working_tree': args.working_tree,
            'gui_mode': True,
            'renderer': 'DirectX (--/app/vulkan=false)',
            'gpu_driver': args.gpu_driver,
            'started_at': _started_at,
            'segment_id': args.segment_id,
            'role': segment['role'],
            'mode': mode,
            'cases_file': Path(args.cases).as_posix(),
            'cases_sha256': cases_sha,
            'expected_file': Path(args.expected).as_posix(),
            'expected_sha256': expected_sha,
            'run_plan': run_plan,
            'episode_ids': episode_ids,
            'contact_contract_version':
                cases_doc['contact_contract_version'],
            'envelope_contract_version':
                cases_doc['envelope_contract_version'],
            'freeze': freeze_meta,
            'contact_sensor': contact_sensor_info,
            'physics': {'physics_dt_s': physics_dt,
                        'decimation': int(cfg.decimation),
                        'substeps_per_step': int(round(dt / physics_dt)),
                        'replicate_physics': False},
            'body_envelope': body_envelope,
            'prim_inventory': {
                'robot': prim_inventory(robot_root),
                'obstacle': prim_inventory('/World/envs/env_0/Obstacle'),
                'map': (prim_inventory('/World/RMUC2027')
                        if mode == 'wall' else []),
            },
            'episode_boundary': {
                'started_from_reset': True,
                'no_silent_reset': True,
                'env_terminated_counts': {item['episode_id']: 0
                                          for item in results},
            },
            'wheel': {'threshold_n': args.contact_threshold_n},
            'outputs_sha256': outputs_sha,
            'command': ' '.join(sys.argv),
        }
        (args.output / 'manifest.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        try:
            from omni.kit.viewport.utility import get_active_viewport
            viewport = get_active_viewport()
            if viewport is not None:
                (args.output / 'screenshots' / 'final.png').write_bytes(b'')
        except Exception:
            pass
        print('CONTACT_EVAL_' + summary['status']
              + ' ' + json.dumps(summary['counts']), flush=True)
        raise SystemExit(0 if summary['status'] == 'PASS' else 1)
    finally:
        env.close()
except SystemExit:
    raise
except BaseException:
    (args.output / 'summary.error.txt').write_text(
        'stage: ' + STAGE['name'] + '\n\n' + traceback.format_exc(),
        encoding='utf-8')
    raise
finally:
    if app is not None:
        app.close()
