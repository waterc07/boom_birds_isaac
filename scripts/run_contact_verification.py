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
from dataclasses import asdict, dataclass, field
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
parser.add_argument('--physics-reset-mode', choices=('none', 'hard'),
                    default='none')
parser.add_argument('--handshake-max-steps', type=int, default=20)
parser.add_argument('--handshake-zero-tolerance-n', type=float, default=1e-6)
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
    'physics_reset_mode': args.physics_reset_mode,
    'handshake': {'max_steps': int(args.handshake_max_steps),
                  'zero_tolerance_n': float(args.handshake_zero_tolerance_n)},
    'contact_evidence_version': cases_doc.get('contact_contract_version'),
    'contact_readout': {
        'schema_version': 'boom_birds.contact_readout.v1',
        'source_sha256': sha256_file(
            'src/boom_birds/evaluation/contact_readout.py'),
        'negative_coverage': 'unverified',
        'event_basis': 'force_threshold_inference',
    },
    'run_params': {
        'contact_threshold_n': args.contact_threshold_n,
        'post_contact_observe_s': args.post_contact_observe_s,
        'geometry': [{'case_id': case['case_id'],
                      'robot': case.get('robot'),
                      'control': case.get('control'),
                      'obstacle': case.get('obstacle'),
                      'target': case.get('target')}
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
    if frozen_plan.get('contact_readout') != run_plan['contact_readout']:
        raise RuntimeError('freeze contact_readout mismatch; new pre-run freeze required')
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

physics_reset_mode = run_plan.get('physics_reset_mode', 'none')
handshake_cfg = run_plan.get('handshake', {
    'max_steps': int(args.handshake_max_steps),
    'zero_tolerance_n': float(args.handshake_zero_tolerance_n)})
handshake_max_steps = int(handshake_cfg.get('max_steps', 20))
handshake_zero_tolerance_n = float(
    handshake_cfg.get('zero_tolerance_n', 1e-6))
if physics_reset_mode not in ('none', 'hard'):
    raise RuntimeError('unsupported physics_reset_mode: ' + repr(physics_reset_mode))

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
    from boom_birds.evaluation import contact_readout as readout_mod
    if args.contact_threshold_n != contact_mod.CONTACT_FORCE_THRESHOLD_N:
        raise ValueError('contact threshold must match the evidence contract')
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
        def build_executor():
            current_mass = float(env._robot_mass.item())
            current_inertias = env._robot.root_physx_view.get_inertias()
            current_body_id = int(
                env._body_id[0].item() if hasattr(env._body_id[0], 'item')
                else env._body_id[0])
            current_matrix = (current_inertias[0, current_body_id].tolist()
                              if len(tuple(current_inertias.shape)) == 3
                              else current_inertias[0].tolist())
            current_params = VehicleParams(
                mass_kg=current_mass,
                inertia_kgm2=(current_matrix[0], current_matrix[4],
                              current_matrix[8]),
                thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
                moment_scale_nm=float(vehicle_cfg['moment_scale_nm']),
                gravity_mps2=9.81,
                max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
            return current_params, VelocityExecutor(
                current_params, gains, dt_s=dt, control_epoch=0)

        params, executor = build_executor()

        wall_target = None
        wall_geometry = None

        def apply_contact_reporters():
            root = '/World/RMUC2027' if mode == 'wall' else '/World/envs/env_0/Obstacle'
            for prim in Usd.PrimRange(stage.GetPrimAtPath(root)):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    PhysxSchema.PhysxContactReportAPI.Apply(prim)
            for _ in range(3):
                app.update()

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
            wall_target = segment['cases'][0]['target']['prim_path']
            if not stage.GetPrimAtPath(wall_target).IsValid():
                raise RuntimeError('wall prim missing: ' + wall_target)
            apply_contact_reporters()
            # confirm the actual wall geometry at the test height: bbox + raycast
            wall_prim = stage.GetPrimAtPath(wall_target)
            wall_bbox = UsdGeom.BBoxCache(
                Usd.TimeCode.Default(),
                [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]
            ).ComputeWorldBound(wall_prim).ComputeAlignedRange()
            wall_min = list(wall_bbox.GetMin())
            wall_max = list(wall_bbox.GetMax())
            start = segment['cases'][0]['robot']['start_position_world_m']
            try:
                import omni.physx
                query = omni.physx.get_physx_scene_query_interface()
                hit = query.raycast_closest(
                    (float(start[0] + 0.0), float(start[1]),
                     float(start[2])), (1.0, 0.0, 0.0), 20.0)
                ray_hit = {
                    'origin': [float(start[0]), float(start[1]), float(start[2])],
                    'direction': [1.0, 0.0, 0.0],
                    'distance_m': (float(hit.get('distance', -1.0))
                                   if hit.get('hit') else None),
                    'collision': str(hit.get('collision', ''))
                    if hit.get('hit') else '',
                    'hit': bool(hit.get('hit')),
                }
            except Exception as error:
                ray_hit = {'error': repr(error)}
            wall_geometry = {
                'target_prim': wall_target,
                'prim_type': wall_prim.GetTypeName(),
                'collision_api': wall_prim.HasAPI(UsdPhysics.CollisionAPI),
                'contact_report_api': wall_prim.HasAPI(
                    PhysxSchema.PhysxContactReportAPI),
                'world_bbox_min_m': wall_min,
                'world_bbox_max_m': wall_max,
                'raycast': ray_hit,
                'test_height_m': float(start[2]),
                'geometry_source': 'competition_map_collision_prim',
            }
        else:
            apply_contact_reporters()
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
            'update_order': 'after_env_step_force_recompute',
            'readout_schema': readout_mod.CONTACT_READOUT_SCHEMA_ID,
            'sample_basis': 'last_physics_step_not_policy_window_max',
            'negative_coverage': 'unverified',
            'event_basis': 'force_threshold_inference_not_raw_contact_report',
            'physics': {'physics_dt_s': physics_dt,
                        'decimation': int(cfg.decimation),
                        'substeps_per_step': int(round(dt / physics_dt))},
            'threshold_n': args.contact_threshold_n,
            'errors': [item['error'] for item in sensors if 'error' in item],
            'reinit_count': 1,
        }

        def read_contacts():
            reads = []
            for item in sensors:
                if 'sensor' not in item:
                    reads.append(readout_mod.ContactRead(
                        sample=None, error=item.get('error', 'sensor not created')))
                    continue
                reads.append(readout_mod.read_contact_sensor(
                    item['sensor'], dt_s=dt, target_paths=(target_path,)))
            return reads

        def raw_contact_measure(reads):
            errors = []
            net_vectors = []
            filtered = {}
            for read in reads:
                if read.sample is None:
                    errors.append(read.error or 'sample unavailable')
                    continue
                net_vectors.extend(read.sample.net_vectors_n)
                for target, vector in read.sample.filtered_by_target_n.items():
                    previous = filtered.get(target)
                    if previous is None or math.hypot(*vector) > math.hypot(*previous):
                        filtered[target] = vector
            max_net = max((math.hypot(*v) for v in net_vectors), default=0.0)
            max_filtered = max((math.hypot(*v) for v in filtered.values()),
                               default=0.0)
            return {
                'read_ok': not errors,
                'errors': errors,
                'max_net_force_n': max_net,
                'max_filtered_force_n': max_filtered,
                'measured_force_n': max(max_net, max_filtered),
                'filtered_targets': sorted(filtered),
            }

        physics_generation = 1 if physics_reset_mode == 'none' else 0
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
            episode_generation = physics_generation
            if physics_reset_mode == 'hard':
                env.sim.reset(soft=False)
                env.reset(seed=0)
                physics_generation += 1
                episode_generation = physics_generation
                origin = env.scene.env_origins[0].tolist()
                obstacle = env.scene['obstacle']
                dt = env.step_dt
                try:
                    physics_dt = float(env.sim.get_physics_dt())
                except Exception:
                    physics_dt = 0.01
                params, executor = build_executor()
                apply_contact_reporters()
                sensors = create_sensors()
                sensor_reinit = {
                    'event': 'after_physics_hard_reset',
                    'physics_generation': episode_generation,
                    'sensors': [{'link': item['link'],
                                 'created': 'sensor' in item,
                                 'error': item.get('error'),
                                 'body_names': (list(item['sensor'].body_names)
                                                if 'sensor' in item else None),
                                 'filter_count': (
                                     int(item['sensor'].contact_physx_view.filter_count)
                                     if 'sensor' in item else None)}
                                for item in sensors],
                    'executor_epoch': 0,
                    'gate_epoch': 'not_used_in_this_entry',
                    'action_queue': 'not_used_in_this_entry',
                }
            else:
                physics_generation = max(physics_generation, 1)
                episode_generation = physics_generation
                sensor_reinit = {'event': 'no_hard_reset',
                                 'physics_generation': episode_generation,
                                 'sensors': [{'link': item['link'],
                                              'created': 'sensor' in item,
                                              'error': item.get('error')}
                                             for item in sensors]}
            set_robot_pose(robot_start, yaw)
            try:
                executor.reset(read_state())
            except Exception:
                pass
            if mode == 'wall':
                set_obstacle_pose((0.0, 0.0, 50.0))
            elif obstacle_case is not None:
                set_obstacle_pose(obstacle_case['start_position_world_m'])
            # bounded freshness handshake at a known separated pose
            handshake_rows = []
            handshake_ok = False
            handshake_success_step = None
            for handshake_step in range(1, handshake_max_steps + 1):
                state = step_hover(0.0)
                reads = read_contacts()
                measure = raw_contact_measure(reads)
                robot_position_world = [state.position_world_m[i] + origin[i]
                                        for i in range(3)]
                handshake_row = {
                    'episode_id': episode_id,
                    'phase': 'HANDSHAKE',
                    'handshake_step': handshake_step,
                    'physics_generation': episode_generation,
                    'step': 0,
                    'time_s': 0.0,
                    'host_wall_time_ns': time.time_ns(),
                    'position_world_m': robot_position_world,
                    'obstacle_position_world_m': (
                        [0.0, 0.0, 50.0] if mode == 'wall'
                        else (list(obstacle_case['start_position_world_m'])
                              if obstacle_case is not None else None)),
                    'contact_readout': {
                        'schema_version': readout_mod.CONTACT_READOUT_SCHEMA_ID,
                        'reads': [asdict(read) for read in reads],
                        'measure': measure,
                        'fresh_zero_tolerance_n': handshake_zero_tolerance_n,
                    },
                    'fresh_zero': bool(measure['read_ok']
                                       and measure['measured_force_n']
                                       <= handshake_zero_tolerance_n),
                    'read_ok': measure['read_ok'],
                    'read_errors': measure['errors'],
                    'measured_force_n': measure['measured_force_n'],
                }
                handshake_rows.append(handshake_row)
                records.append(handshake_row)
                if handshake_row['fresh_zero']:
                    handshake_ok = True
                    handshake_success_step = handshake_step
                    break
            if not handshake_ok:
                episode = {
                    'episode_id': episode_id,
                    'case_id': case['case_id'],
                    'mode': mode,
                    'outcome': 'INITIALIZATION_FAILED',
                    'business_outcome': 'FAIL',
                    'physical_outcome': 'UNKNOWN',
                    'contact_summary': None,
                    'envelope_sphere_about_origin_m': sphere_radius,
                    'max_force_n': 0.0,
                    'max_measured_force_n': 0.0,
                    'contact_observed': False,
                    'first_contact_time_s': None,
                    'max_geometry_overlap_m': None,
                    'steps': 0,
                    'physics_generation': episode_generation,
                    'handshake': {
                        'ok': False,
                        'steps': handshake_rows,
                        'max_steps': handshake_max_steps,
                        'zero_tolerance_n': handshake_zero_tolerance_n,
                    },
                    'sensor_reinit': sensor_reinit,
                    'replay': None,
                }
                results.append(episode)
                print('[episode] ' + episode_id
                      + ' INITIALIZATION_FAILED HANDSHAKE_NOT_FRESH', flush=True)
                continue
            # measurement starts only after the fresh-zero handshake
            set_robot_pose(robot_start, yaw)
            try:
                executor.reset(read_state())
            except Exception:
                pass
            if mode == 'wall':
                set_obstacle_pose((0.0, 0.0, 50.0))
            elif obstacle_case is not None:
                set_obstacle_pose(obstacle_case['start_position_world_m'])
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
                if physics_generation != episode_generation:
                    raise RuntimeError('mid-episode physics reset detected: '
                                       + str(episode_generation) + ' -> '
                                       + str(physics_generation))
                reads = read_contacts()
                measure = raw_contact_measure(reads)
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
                record = readout_mod.build_readout_record(
                    reads, step=step, time_s=time_s, sample_dt_s=physics_dt,
                    geometry=(None if overlap is None else {
                        'sphere_overlap_m': overlap,
                        'robot_radius_m': sphere_radius,
                        'obstacle_radius_m': (
                            max(obstacle_case['size_m']) / 2.0
                            if obstacle_case else None)}))
                force = record['layers']['force']['magnitude_n'] or 0.0
                max_force = max(max_force, force)
                event = force > args.contact_threshold_n
                if event and first_contact_time is None:
                    first_contact_time = time_s
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
                    'contact_prim': (target_path if record['layers']['attribution']['status']
                                     == 'ATTRIBUTED' else ''),
                    'contact_readout': {
                        'schema_version': readout_mod.CONTACT_READOUT_SCHEMA_ID,
                        'reads': [asdict(read) for read in reads],
                        'measure': measure,
                        'physics_sample_dt_s': physics_dt,
                        'coverage_verified': False,
                    },
                    'physics_generation': episode_generation,
                    'host_wall_time_ns': time.time_ns(),
                    'measured_force_n': measure['measured_force_n'],
                    'read_ok': measure['read_ok'],
                    'read_errors': measure['errors'],
                    'threshold_event': bool(event),
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
            measured_force = max((row['measured_force_n']
                                  for row in episode_rows), default=0.0)
            read_error_rows = [row for row in episode_rows
                               if not row.get('read_ok')]
            contact_observed = measured_force > 0.0
            threshold_event_steps = [row['step'] for row in episode_rows
                                     if row.get('threshold_event')]
            if read_error_rows:
                physical = 'UNKNOWN'
                outcome, reason = 'UNDECIDABLE', 'CONTACT_READ_ERROR'
            elif contact_observed:
                if measured_force > args.contact_threshold_n:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED'
                else:
                    physical = 'PHYSX_CONTACT_FORCE_MEASURED_BELOW_THRESHOLD'
                if mode in ('wall', 'obstacle'):
                    outcome, reason = 'SUCCESS', 'PHYSX_CONTACT_FORCE_OBSERVED'
                elif mode == 'clearance':
                    outcome, reason = 'FAIL', 'UNEXPECTED_CONTACT'
                else:
                    outcome, reason = 'UNDECIDABLE', 'GEOMETRY_PROBE_CONTACT'
            else:
                physical = 'UNKNOWN'
                outcome, reason = ('UNDECIDABLE',
                                   'READ_ZERO_COVERAGE_UNVERIFIED')
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
                'max_measured_force_n': measured_force,
                'contact_observed': contact_observed,
                'threshold_event_steps': threshold_event_steps,
                'first_contact_time_s': first_contact_time,
                'max_geometry_overlap_m': (None if max_overlap <= -1e8
                                           else max_overlap),
                'steps': len(episode_rows),
                'physics_generation': episode_generation,
                'handshake': {
                    'ok': handshake_ok,
                    'success_step': handshake_success_step,
                    'max_steps': handshake_max_steps,
                    'zero_tolerance_n': handshake_zero_tolerance_n,
                    'rows': handshake_rows,
                },
                'sensor_reinit': sensor_reinit,
                'time_domains': {
                    'host_wall_time_utc': time.strftime(
                        '%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'policy_steps': len(episode_rows),
                    'physics_dt_s': physics_dt,
                    'policy_dt_s': dt,
                },
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
            'physics_reset_mode': physics_reset_mode,
            'handshake': {'max_steps': handshake_max_steps,
                          'zero_tolerance_n': handshake_zero_tolerance_n},
            'physics_generations': {item['episode_id']: item['physics_generation']
                                    for item in results},
            'contact_contract_version': cases_doc['contact_contract_version'],
            'envelope_contract_version': cases_doc['envelope_contract_version'],
            'contact_readout': run_plan.get('contact_readout'),
            'contact_evidence_version': run_plan.get(
                'contact_evidence_version'),
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
                        'replicate_physics': False,
                        'reset_mode': physics_reset_mode},
            'physics_reset_mode': physics_reset_mode,
            'physics_generations': {item['episode_id']: item['physics_generation']
                                    for item in results},
            'handshake': {'max_steps': handshake_max_steps,
                          'zero_tolerance_n': handshake_zero_tolerance_n},
            'sensor_reinit': {item['episode_id']: item.get('sensor_reinit')
                              for item in results
                              if item.get('sensor_reinit') is not None},
            'wall_geometry': wall_geometry,
            'contact_readout': run_plan.get('contact_readout'),
            'contact_evidence_version': run_plan.get(
                'contact_evidence_version'),
            'time_domains': {
                'host_start_utc': _started_at,
                'host_end_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                              time.gmtime()),
                'policy_steps_total': sum(item['steps'] for item in results),
                'physics_dt_s': physics_dt,
                'policy_dt_s': dt,
            },
            'body_envelope': body_envelope,
            'prim_inventory': {
                'robot': prim_inventory(robot_root),
                'obstacle': prim_inventory('/World/envs/env_0/Obstacle'),
                'map': (prim_inventory('/World/RMUC2027')
                        if mode == 'wall' else []),
            },
            'episode_boundary': {
                'started_from_reset': True,
                'no_silent_reset': (physics_reset_mode == 'hard'),
                'reset_mode': physics_reset_mode,
                'physics_generations': {item['episode_id']: item['physics_generation']
                                        for item in results},
                'env_terminated_counts': {item['episode_id']: 0
                                          for item in results},
                'wrist': 'controlled diagnostic episodes; no mid-episode reset allowed',
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
