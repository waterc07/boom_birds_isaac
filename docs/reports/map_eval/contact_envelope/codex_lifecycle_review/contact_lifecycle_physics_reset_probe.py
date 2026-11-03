"""DSH wall lifecycle probe: sustained wall contact across consecutive episodes.

Robot flies forward into the frozen map wall collision_014 and keeps pushing for
the rest of each episode.  Variants change exactly one lifecycle factor:
  fixed / env_reset / sensor_reset / view_rebuild / scene_rebuild(optional)
Raw sensor tensors, read health, view identity, timestamps and robot poses are
recorded for every step; zero readout is never used as proof of no contact.
"""
import argparse
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--variant', required=True,
                    choices=('fixed', 'env_reset', 'sensor_reset',
                             'view_rebuild', 'reapply_reporter',
                             'late_view_rebuild'))
parser.add_argument('--scene', choices=('wall', 'static_obstacle'),
                    default='wall')
parser.add_argument('--episodes', type=int, default=3)
parser.add_argument('--steps', type=int, default=300)
parser.add_argument('--output', type=Path, required=True)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if getattr(args, 'headless', False):
    raise RuntimeError('GUI is required; --headless is forbidden')
args.output.mkdir(parents=True, exist_ok=True)
app = AppLauncher(args).app

try:
    import omni.usd
    import torch
    import yaml
    import isaaclab.sim as sim_utils
    from isaaclab.assets import RigidObjectCfg
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.sensors import ContactSensor, ContactSensorCfg
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)
    from pxr import Usd, UsdPhysics, PhysxSchema

    sys.path.insert(0, str(Path('src').resolve()))
    from boom_birds.sim.map_contract import load_map_contract
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    vehicle_config = yaml.safe_load(Path(
        'configs/vehicles/sim_reference.yaml').read_text(encoding='utf-8'))
    gains = VelocityGains(**{k: float(v) for k, v in
                             vehicle_config['gains'].items()})
    vehicle_cfg = vehicle_config['vehicle']

    @dataclass
    class ProbeSceneCfg(InteractiveSceneCfg):
        obstacle: RigidObjectCfg = field(default_factory=lambda: RigidObjectCfg(
            prim_path='{ENV_REGEX_NS}/Obstacle',
            spawn=sim_utils.CuboidCfg(
                size=(0.6, 0.6, 0.6),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True, disable_gravity=True),
                mass_props=sim_utils.MassPropertiesCfg(mass=5.0),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                activate_contact_sensors=True)))

    def build_env():
        cfg = QuadcopterEnvCfg()
        cfg.sim.device = args.device
        cfg.seed = 0
        cfg.decimation = 5
        cfg.episode_length_s = 120.0
        cfg.robot.spawn.activate_contact_sensors = True
        cfg.scene = ProbeSceneCfg(num_envs=1, env_spacing=2.5,
                                  replicate_physics=False, clone_in_fabric=False)
        env = QuadcopterEnv(cfg)
        env.reset(seed=0)
        return cfg, env

    cfg, env = build_env()
    dt = env.step_dt
    physics_dt = float(env.sim.get_physics_dt())
    origin = env.scene.env_origins[0].tolist()
    stage = omni.usd.get_context().get_stage()
    robot_root = '/World/envs/env_0/Robot'
    wall_prim = '/World/RMUC2027/Collisions/collision_014'

    target_prim = '/World/envs/env_0/Obstacle' if args.scene == 'static_obstacle' else '/World/RMUC2027/Collisions/collision_014'
    if args.scene == 'wall':
        contract = load_map_contract(Path('configs/maps/rmuc2027.yaml'),
                                     Path('configs/maps/rmuc2027.local.yaml'))
        ground = stage.GetPrimAtPath(cfg.terrain.prim_path)
        if ground.IsValid():
            ground.SetActive(False)
        map_cfg = sim_utils.UsdFileCfg(usd_path=str(contract.terrain_path))
        map_cfg.func('/World/RMUC2027', map_cfg)
        for _ in range(10):
            app.update()
        reporter_root = '/World/RMUC2027'
    else:
        reporter_root = '/World/envs/env_0/Obstacle'
    for prim in Usd.PrimRange(stage.GetPrimAtPath(reporter_root)):
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            PhysxSchema.PhysxContactReportAPI.Apply(prim)
    for _ in range(3):
        app.update()
    obstacle = env.scene['obstacle'] if args.scene == 'static_obstacle' else None

    def set_obstacle_pose(position):
        pose = torch.tensor([[float(position[0]), float(position[1]),
                              float(position[2]), 1.0, 0.0, 0.0, 0.0]],
                            dtype=torch.float32, device=env.device)
        obstacle.write_root_pose_to_sim(pose, index)

    zero6 = torch.zeros((1, 6), device=env.device)
    index = torch.tensor([0], device=env.device)

    def make_executor():
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
        return params, VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)

    params, executor = make_executor()

    def prim_report(prim_path):
        prim = stage.GetPrimAtPath(prim_path)
        return {'path': prim_path,
                'valid': bool(prim and prim.IsValid()),
                'collision': bool(prim and prim.HasAPI(UsdPhysics.CollisionAPI)),
                'rigid': bool(prim and prim.HasAPI(UsdPhysics.RigidBodyAPI)),
                'contact_report': bool(prim and prim.HasAPI(
                    PhysxSchema.PhysxContactReportAPI))}

    log = {
        'schema_version': 'dsh.wall_lifecycle_probe.v1',
        'variant': args.variant,
        'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'physics_dt_s': physics_dt,
        'sim_dt_s': dt,
        'env_origin': origin,
        'scene': args.scene,
        'target_prim': prim_report(target_prim),
        'episodes': [],
        'sensor_events': [],
    }

    sensor_state = {'sensor': None}

    def make_sensor():
        sensor = ContactSensor(ContactSensorCfg(
            prim_path=robot_root + '/body',
            filter_prim_paths_expr=[target_prim],
            update_period=0.0, debug_vis=False, history_length=0))
        sensor._initialize_callback(None)
        sensor.update(dt=dt)
        return sensor

    def ensure_sensor(episode):
        if sensor_state['sensor'] is None:
            sensor_state['sensor'] = make_sensor()
            log['sensor_events'].append({
                'event': 'create', 'episode': episode,
                'sensor_object_id': id(sensor_state['sensor']),
                'view_object_id': id(sensor_state['sensor'].contact_physx_view)
                if sensor_state['sensor'].contact_physx_view is not None else None})
        return sensor_state['sensor']

    def set_robot_pose(x, y=0.0, z=1.0, yaw_rad=0.0):
        quat = (math.cos(yaw_rad / 2.0), 0.0, 0.0,
                math.sin(yaw_rad / 2.0))
        pose = torch.tensor([[origin[0] + x, origin[1] + y, origin[2] + z,
                              quat[0], quat[1], quat[2], quat[3]]],
                            dtype=torch.float32, device=env.device)
        env._robot.write_root_pose_to_sim(pose, index)
        env._robot.write_root_velocity_to_sim(zero6, index)

    def read_state():
        position = env._robot.data.root_pos_w[0].tolist()
        velocity = env._robot.data.root_lin_vel_w[0].tolist()
        quat = env._robot.data.root_quat_w[0].tolist()
        omega = env._robot.data.root_ang_vel_b[0].tolist()
        return VehicleState(
            position_world_m=tuple(position[i] - origin[i] for i in range(3)),
            velocity_world_mps=tuple(velocity), quat_wxyz=tuple(quat),
            angular_velocity_body_radps=tuple(omega))

    def step_forward(forward_mps):
        control = executor.step(VelocitySetpoint(
            forward_mps, 0.0, 0.0, 0.0, issued_at_s=0.0, expires_at_s=10.0,
            control_epoch=0), read_state(), 0.0)
        env.step(torch.tensor([control.to_actuator_action(params)],
                              dtype=torch.float32, device=env.device))
        return read_state()

    def read_sensor(sensor):
        record = {
            'read_wall_time_ns': time.time_ns(),
            'sensor_object_id': id(sensor),
            'view_object_id': (id(sensor.contact_physx_view)
                               if sensor.contact_physx_view is not None else None),
            'filter_count': None,
            'body_names': None,
            'force_matrix_shape': None,
            'force_matrix_raw': None,
            'force_matrix_l2_n': None,
            'force_matrix_l1_n': None,
            'force_matrix_correct_vector': None,
            'buggy_float_error': None,
            'net_forces_shape': None,
            'net_forces_raw': None,
            'net_forces_l2_n': None,
            'net_forces_l1_n': None,
            'sensor_timestamp': None,
            'timestamp_last_update': None,
            'is_outdated': None,
            'read_ok': False,
            'exception': None,
        }
        try:
            record['filter_count'] = int(sensor.contact_physx_view.filter_count)
            record['body_names'] = list(sensor.body_names)
            record['sensor_timestamp'] = float(sensor._timestamp.item())
            record['timestamp_last_update'] = float(
                sensor._timestamp_last_update.item())
            record['is_outdated'] = bool(sensor._is_outdated)
            sensor.update(dt=dt, force_recompute=True)
            raw_view = sensor.contact_physx_view
            low_matrix = raw_view.get_contact_force_matrix(dt=physics_dt)
            record['low_matrix_n'] = low_matrix.detach().cpu().tolist()
            try:
                forces, points, normals, distances, counts, starts = raw_view.get_contact_data(dt=physics_dt)
                record['raw_contact_counts'] = counts.detach().cpu().tolist()
                record['raw_contact_starts'] = starts.detach().cpu().tolist()
                record['raw_contact_total'] = int(counts.sum().item())
                record['raw_contact_forces_n'] = forces.detach().cpu().tolist()
                record['raw_contact_data_error'] = None
            except Exception as raw_error:
                record['raw_contact_data_error'] = repr(raw_error)
            matrix = sensor.data.force_matrix_w
            net = sensor.data.net_forces_w
            if matrix is not None:
                raw = matrix.detach().cpu()
                record['force_matrix_shape'] = list(matrix.shape)
                record['force_matrix_raw'] = raw.tolist()
                record['force_matrix_l2_n'] = float(torch.norm(raw, dim=-1).max())
                record['force_matrix_l1_n'] = float(raw.abs().sum(dim=-1).max())
                vector = matrix[0, 0].tolist()
                try:
                    record['buggy_float_error'] = repr(float(vector))
                except Exception as error:
                    record['buggy_float_error'] = type(error).__name__ + ': ' + str(error)
                if matrix.shape[-2] > 0:
                    record['force_matrix_correct_vector'] = matrix[0, 0, 0].tolist()
            if net is not None:
                net_raw = net.detach().cpu()
                record['net_forces_shape'] = list(net_raw.shape)
                record['net_forces_raw'] = net_raw.tolist()
                record['net_forces_l2_n'] = float(torch.norm(net_raw, dim=-1).max())
                record['net_forces_l1_n'] = float(net_raw.abs().sum(dim=-1).max())
            record['read_ok'] = True
        except Exception as error:
            record['exception'] = (type(error).__name__ + ': ' + str(error)
                                   + ' | ' + traceback.format_exc(limit=2))
        return record

    for episode in range(args.episodes):
        episode_log = {'episode': episode, 'variant': args.variant,
                       'rows': []}
        if episode > 0:
            if args.variant == 'env_reset':
                print('[codex] physics hard reset begin', episode, flush=True)
                env.sim.reset(soft=False)
                env.reset(seed=0)
                print('[codex] physics hard reset end', episode, flush=True)
                episode_log['env_reset_done'] = True
            elif args.variant == 'sensor_reset':
                sensor_state['sensor'].reset()
                episode_log['sensor_reset_done'] = True
            elif args.variant == 'late_view_rebuild':
                if episode > 0:
                    sensor_state['sensor'] = None
                    if args.scene == 'static_obstacle':
                        set_obstacle_pose((0.0, 0.0, 1.0))
                        set_robot_pose(-2.0, 0.0, 1.0, 0.0)
                    else:
                        set_robot_pose(-4.0, 0.0, 1.0, 0.0)
                    step_forward(0.0)
                    episode_log['late_view_rebuild'] = True
            elif args.variant == 'reapply_reporter':
                for prim in Usd.PrimRange(stage.GetPrimAtPath(reporter_root)):
                    if prim.HasAPI(UsdPhysics.CollisionAPI):
                        PhysxSchema.PhysxContactReportAPI.Apply(prim)
                episode_log['reporters_reapplied'] = True
            elif args.variant == 'view_rebuild':
                old = sensor_state['sensor']
                log['sensor_events'].append({
                    'event': 'drop_for_rebuild', 'episode': episode,
                    'old_sensor_object_id': id(old),
                    'old_view_object_id': (id(old.contact_physx_view)
                                           if old.contact_physx_view is not None
                                           else None)})
                sensor_state['sensor'] = None
                episode_log['view_rebuilt'] = True
        sensor = ensure_sensor(episode)
        episode_log['sensor_at_start'] = {
            'sensor_object_id': id(sensor),
            'view_object_id': (id(sensor.contact_physx_view)
                               if sensor.contact_physx_view is not None else None),
            'body_names': list(sensor.body_names),
            'filter_count': (int(sensor.contact_physx_view.filter_count)
                             if sensor.contact_physx_view is not None else None)}
        if args.scene == 'static_obstacle':
            set_obstacle_pose((0.0, 0.0, 1.0))
            set_robot_pose(-2.0, 0.0, 1.0, 0.0)
        else:
            set_obstacle_pose((0.0, 0.0, 50.0))
            set_robot_pose(-4.0, 0.0, 1.0, 0.0)
        step_forward(0.0)
        try:
            executor.reset(read_state())
        except Exception:
            pass
        rows = []
        near_wall_rows = []
        altitude_corrections = 0
        for step in range(1, args.steps + 1):
            pre_state = read_state()
            if abs(pre_state.position_world_m[2] - 1.0) > 0.02:
                set_robot_pose(pre_state.position_world_m[0],
                               pre_state.position_world_m[1], 1.0, 0.0)
                altitude_corrections += 1
            if args.scene == 'static_obstacle':
                set_obstacle_pose((0.0, 0.0, 1.0))
            state = step_forward(0.6 if args.scene == 'wall' else 0.4)
            robot_position = [state.position_world_m[i] + origin[i]
                              for i in range(3)]
            reading = read_sensor(sensor)
            row = {
                'step': step,
                'sim_time_s': step * dt,
                'robot_world_m': [round(v, 6) for v in robot_position],
                'robot_speed_mps': round(math.sqrt(sum(
                    v * v for v in state.velocity_world_mps)), 6),
                'sensor': reading,
            }
            rows.append(row)
            if args.scene == 'wall':
                if robot_position[0] > -0.75:
                    near_wall_rows.append(row)
            else:
                if robot_position[0] > -0.75:
                    near_wall_rows.append(row)
        nonzero = sum(1 for row in near_wall_rows
                      if (row['sensor'].get('force_matrix_l2_n') or 0) > 0)
        errors = {}
        for row in rows:
            error = row['sensor'].get('exception')
            if error:
                key = error.split(':')[0]
                errors[key] = errors.get(key, 0) + 1
        episode_log.update({
            'wall_contact_window_rows': len(near_wall_rows),
            'wall_window_nonzero_force_steps': nonzero,
            'wall_window_nonzero_net_steps': sum(
                1 for row in near_wall_rows
                if (row['sensor'].get('net_forces_l2_n') or 0) > 0),
            'read_ok_steps': sum(1 for row in rows
                                 if row['sensor'].get('read_ok')),
            'exception_counts': errors,
            'max_force_l2_n': max((row['sensor'].get('force_matrix_l2_n') or 0.0)
                                  for row in rows),
            'max_net_l2_n': max((row['sensor'].get('net_forces_l2_n') or 0.0)
                                for row in rows),
            'first_force_step': next(
                (row['step'] for row in rows
                 if (row['sensor'].get('force_matrix_l2_n') or 0) > 0), None),
            'first_force_robot_x': next(
                (row['robot_world_m'][0] for row in rows
                 if (row['sensor'].get('force_matrix_l2_n') or 0) > 0), None),
            'altitude_corrections': altitude_corrections,
            'sensor_at_end': {
                'sensor_object_id': id(sensor),
                'view_object_id': (id(sensor.contact_physx_view)
                                   if sensor.contact_physx_view is not None
                                   else None)},
            'rows': rows,
        })
        log['episodes'].append(episode_log)

    log['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    (args.output / 'wall_lifecycle_probe.json').write_text(
        json.dumps(log, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('CODEX_HARD_RESET_PROBE_DONE ' + json.dumps({
        'variant': args.variant,
        'episodes': [{'episode': item['episode'],
                      'contact_window_rows': item['wall_contact_window_rows'],
                      'nonzero_force_steps': item['wall_window_nonzero_force_steps'],
                      'max_force_l2': item['max_force_l2_n'],
                      'first_force_robot_x': item['first_force_robot_x']}
                     for item in log['episodes']]}, ensure_ascii=False), flush=True)
finally:
    try:
        env.close()
    except Exception:
        pass
    app.close()
