"""RMUC2027 map dynamics entry: map load, phases, frozen cases, evidence."""
import argparse
import hashlib
import json
import math
import sys
import traceback
from datetime import datetime
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--map-config', type=Path, default=Path('configs/maps/rmuc2027.yaml'))
parser.add_argument('--local-config', type=Path,
                    default=Path('configs/maps/rmuc2027.local.yaml'))
parser.add_argument('--cases', type=Path, default=Path('configs/scenarios/map_cases_v1.json'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--mode', choices=['smoke', 'run'], default='run')
parser.add_argument('--limit-cases', type=int, default=0)
parser.add_argument('--only-cases', default='')
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--working-tree', default='recorded by the operator')
parser.add_argument('--gpu-driver', default='NOT RECORDED')
parser.add_argument('--screenshots', action='store_true')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
app = AppLauncher(args).app

STAGES = []


def scenario_seed(case_index, repeat):
    return 9000 + case_index * 10 + repeat


def mark(stage):
    STAGES.append(stage)
    print('[stage] ' + stage, flush=True)


try:
    import torch
    import omni.usd
    from pxr import Usd, UsdGeom
    import isaaclab.sim as sim_utils
    from isaaclab.sensors import ContactSensor, ContactSensorCfg
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from boom_birds.evaluation.episode_boundary import EpisodeBoundary
    from boom_birds.evaluation.map_eval import (
        MapReachEvaluator, MapReachSpec, TakeoffLandingEvaluator)
    from boom_birds.sim.guidance import GuidanceSpec, make_guidance
    from boom_birds.sim.map_contract import load_map_cases, load_map_contract
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    mark('load map contract')
    contract = load_map_contract(args.map_config, args.local_config)
    cases = load_map_cases(args.cases, contract)
    if args.limit_cases > 0:
        cases = cases[:args.limit_cases]
    if args.only_cases:
        wanted = {item.strip() for item in args.only_cases.split(',') if item.strip()}
        cases = [case for case in cases if case.case_id in wanted]
        if not cases:
            raise RuntimeError('no cases selected')
    case_sha = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    map_cfg_sha = hashlib.sha256(args.map_config.read_bytes()).hexdigest()

    if args.freeze is not None:
        freeze = json.loads(args.freeze.read_text(encoding='utf-8'))
        checks = {
            'map_asset_id': contract.asset_id,
            'terrain_sha256': contract.terrain_sha256,
            'preview_sha256': contract.preview_sha256,
            'map_config_sha256': map_cfg_sha,
            'cases_sha256': case_sha,
        }
        for key, value in checks.items():
            if freeze.get(key) != value:
                raise RuntimeError('freeze mismatch: ' + key)
        mark('map freeze verified')

    mark('build env config')
    import yaml
    config = yaml.safe_load(Path('configs/vehicles/sim_reference.yaml')
                            .read_text(encoding='utf-8'))
    gains_cfg = config['gains']
    vehicle_cfg = config['vehicle']
    controller_cfg = config['controller']
    controller_cfg = controller_cfg
    gains = VelocityGains(**{key: float(value) for key, value in gains_cfg.items()})

    cfg = QuadcopterEnvCfg()
    cfg.scene.num_envs = 1
    cfg.sim.device = args.device
    cfg.seed = 0
    cfg.debug_vis = False
    cfg.decimation = 5
    cfg.episode_length_s = 60.0
    cfg.scene.clone_in_fabric = False
    if not hasattr(cfg.robot.spawn, 'activate_contact_sensors'):
        raise RuntimeError('robot spawn config lacks contact sensors')
    cfg.robot.spawn.activate_contact_sensors = True

    mark('create env')
    env = QuadcopterEnv(cfg)
    env.reset(seed=0)
    try:
        dt = env.step_dt
        origin = env.scene.env_origins[0].tolist()
        mass = float(env._robot_mass.item())
        inertias = env._robot.root_physx_view.get_inertias()
        raw_body_id = env._body_id[0]
        body_id = int(raw_body_id.item()) if hasattr(raw_body_id, 'item') else int(raw_body_id)
        shape = tuple(inertias.shape)
        if len(shape) == 3:
            matrix = inertias[0, body_id].tolist()
        else:
            matrix = inertias[0].tolist()
        inertia = (matrix[0], matrix[4], matrix[8])
        gravity = math.sqrt(sum(value * value for value in cfg.sim.gravity))
        params = VehicleParams(
            mass_kg=mass, inertia_kgm2=inertia,
            thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
            moment_scale_nm=float(vehicle_cfg['moment_scale_nm']),
            gravity_mps2=float(gravity),
            max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
        executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)
        zero_velocity = torch.zeros((1, 6), device=env.device)
        index = torch.tensor([0], device=env.device)

        mark('disable default ground plane')
        stage = omni.usd.get_context().get_stage()
        ground = stage.GetPrimAtPath(cfg.terrain.prim_path)
        if ground.IsValid():
            ground.SetActive(False)
            print('[map] disabled default ground at ' + cfg.terrain.prim_path, flush=True)
        else:
            raise RuntimeError('default ground prim not found')

        mark('spawn map terrain')
        map_prim_path = '/World/RMUC2027'
        map_cfg = sim_utils.UsdFileCfg(usd_path=str(contract.terrain_path))
        map_cfg.func(map_prim_path, map_cfg)
        for _ in range(10):
            app.update()
        map_prim = stage.GetPrimAtPath(map_prim_path)
        if not map_prim.IsValid():
            raise RuntimeError('map prim missing after spawn')
        try:
            from pxr import PhysxSchema, UsdPhysics
            report_count = 0
            for prim in Usd.PrimRange(map_prim):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    if not prim.HasAPI(PhysxSchema.PhysxContactReportAPI):
                        PhysxSchema.PhysxContactReportAPI.Apply(prim)
                    report_count += 1
            print('[map] contact reporters enabled on ' + str(report_count) + ' collision prims',
                  flush=True)
        except Exception as error:
            print('[map] reporter warning: ' + repr(error), flush=True)
        print('[map] spawned ' + map_prim_path + ' active=' + str(map_prim.IsActive()), flush=True)

        mark('add light and camera')
        try:
            sun = sim_utils.DistantLightCfg(intensity=2500.0, angle=0.53)
            sun.func('/World/MapSun', sun)
        except Exception as error:
            print('[map] light warning: ' + repr(error), flush=True)
        try:
            from isaacsim.core.utils.viewports import set_camera_view
            from omni.kit.viewport.utility import get_active_viewport
            viewport = get_active_viewport()
            if viewport is not None:
                set_camera_view(eye=[18.0, -20.0, 16.0], target=[-4.0, 0.0, 0.5])
                viewport.camera_path = '/OmniverseKit_Persp'
        except Exception as error:
            print('[map] camera warning: ' + repr(error), flush=True)

        mark('create map contact sensors')
        import omni.physx
        query = omni.physx.get_physx_scene_query_interface()
        robot_root = '/World/envs/env_0/Robot'

        def find_ground_prim(x, y):
            hit = query.raycast_closest((float(x), float(y), 10.0),
                                        (0.0, 0.0, -1.0), 30.0)
            return str(hit.get('collision', '')) if hit.get('hit') else ''

        def find_wall_prim(x, y, z):
            hit = query.raycast_closest((float(x), float(y), float(z)),
                                        (1.0, 0.0, 0.0), 6.0)
            return str(hit.get('collision', '')) if hit.get('hit') else ''

        takeoff_case = next((item for item in cases
                             if item.kind == 'takeoff_landing'), None)
        contact_case = next((item for item in cases if item.kind == 'contact'), None)
        ground_prim = find_ground_prim(
            takeoff_case.start_position_world_m[0],
            takeoff_case.start_position_world_m[1]) if takeoff_case else ''
        wall_prim = find_wall_prim(
            contact_case.start_position_world_m[0],
            contact_case.start_position_world_m[1],
            contact_case.start_position_world_m[2]) if contact_case else ''
        if not wall_prim:
            wall_prim = '/World/RMUC2027/Collisions/collision_014'
        wall_prim_valid = bool(wall_prim) and stage.GetPrimAtPath(wall_prim).IsValid()
        print('[map] ground prim=' + ground_prim + ' wall prim=' + wall_prim
              + ' valid=' + str(wall_prim_valid), flush=True)
        sensors = []
        for prim in (ground_prim, wall_prim):
            if not prim:
                continue
            sensor_cfg = ContactSensorCfg(
                prim_path=robot_root + '/body',
                filter_prim_paths_expr=[prim], update_period=0.0, debug_vis=False)
            item = ContactSensor(sensor_cfg)
            item._initialize_callback(None)
            item.update(dt=dt)
            sensors.append((prim, item))

        def read_sensor_contact():
            best_force = 0.0
            best_prim = ''
            for prim, item in sensors:
                try:
                    item.update(dt=dt)
                    matrix = item.data.force_matrix_w
                    if matrix is None:
                        continue
                    force = float(matrix[0].abs().sum(dim=-1).max())
                    if force > best_force:
                        best_force, best_prim = force, prim
                except Exception:
                    continue
            return best_force, best_prim

        def nearest_map_prim(position, velocity):
            direction = [velocity[0], velocity[1], velocity[2]]
            norm = math.sqrt(sum(value * value for value in direction))
            candidates = []
            if norm > 1e-6:
                candidates.append([value / norm for value in direction])
            candidates.extend([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
                               [0.0, 1.0, 0.0], [0.0, -1.0, 0.0]])
            for item in candidates:
                hit = query.raycast_closest(
                    (float(position[0]), float(position[1]), float(position[2])),
                    (float(item[0]), float(item[1]), float(item[2])), 3.0)
                if hit.get('hit'):
                    prim = str(hit.get('collision', ''))
                    if 'Collisions' in prim or 'RMUC2027' in prim:
                        return prim, float(hit.get('distance', 0.0))
            return '', 0.0

        mark('patch map dones')
        original_dones = env._get_dones

        def map_dones():
            time_out = env.episode_length_buf >= env.max_episode_length - 1
            died = torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)
            return died, time_out

        env._get_dones = map_dones

        def read_state():
            position = env._robot.data.root_pos_w[0].tolist()
            velocity = env._robot.data.root_lin_vel_w[0].tolist()
            quat = env._robot.data.root_quat_w[0].tolist()
            omega = env._robot.data.root_ang_vel_b[0].tolist()
            return VehicleState(
                position_world_m=tuple(position[i] - origin[i] for i in range(3)),
                velocity_world_mps=tuple(velocity), quat_wxyz=tuple(quat),
                angular_velocity_body_radps=tuple(omega))

        def yaw_of(state):
            w, x, y, z = state.quat_wxyz
            return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

        def set_pose(position, yaw_rad):
            quat = (math.cos(yaw_rad / 2.0), 0.0, 0.0, math.sin(yaw_rad / 2.0))
            pose = torch.tensor([[origin[0] + position[0], origin[1] + position[1],
                                  origin[2] + position[2], quat[0], quat[1],
                                  quat[2], quat[3]]],
                                dtype=torch.float32, device=env.device)
            env._robot.write_root_pose_to_sim(pose, index)
            env._robot.write_root_velocity_to_sim(zero_velocity, index)

        def capture(label):
            if not args.screenshots:
                return None
            try:
                from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
                viewport = get_active_viewport()
                path = args.output / 'screenshots' / (label + '.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                capture_viewport_to_file(viewport, str(path))
                for _ in range(60):
                    app.update()
                    if path.exists():
                        break
                return str(path) if path.exists() else None
            except Exception as error:
                print('[map] screenshot warning: ' + repr(error), flush=True)
                return None

        proportional = GuidanceSpec(**{
            key: float(value) for key, value in
            config.get('guidance', {}).get('proportional', {}).items()})
        ttl = float(controller_cfg['ttl_s'])
        boundary = EpisodeBoundary(env)
        results = []
        step_records = []
        started_at = datetime.now().astimezone().isoformat()
        mark('run map cases')
        with torch.inference_mode():
            for case_index, case in enumerate(cases):
                for repeat in range(case.repeats):
                    episode_id = case.case_id + '-r' + str(repeat)
                    boundary.start(seed=scenario_seed(case_index, repeat))
                    set_pose(case.start_position_world_m, case.start_yaw_rad)
                    state = read_state()
                    executor.reset(state)
                    if case.kind == 'reach':
                        spec = MapReachSpec(
                            goal_position_world_m=case.goal_position_world_m,
                            bounds_min_m=contract.bounds_min_m,
                            bounds_max_m=contract.bounds_max_m,
                            floor_z_m=contract.bounds_min_m[2],
                            success_distance_m=0.2, success_speed_mps=0.2,
                            hold_time_s=0.5, timeout_s=case.timeout_s)
                        evaluator = MapReachEvaluator(spec, dt)
                        guidance = make_guidance(
                            'proportional', case.goal_position_world_m,
                            proportional_spec=proportional, braking_spec=None)
                    elif case.kind == 'takeoff_landing':
                        evaluator = TakeoffLandingEvaluator(case, case.timeout_s)
                        guidance = None
                    else:
                        evaluator = None
                        guidance = None
                    outcome, reason = 'RUNNING', 'RUNNING'
                    contact_max = 0.0
                    contact_prim = ''
                    contact_step = None
                    phase = 'RUNNING'
                    steps = 0
                    max_steps = int(math.ceil(case.timeout_s / dt))
                    for step in range(max_steps):
                        elapsed = (step + 1) * dt
                        state = read_state()
                        if case.kind == 'reach':
                            command = guidance.command(
                                position_world_m=state.position_world_m,
                                velocity_world_mps=state.velocity_world_mps,
                                quat_wxyz=state.quat_wxyz)
                        elif case.kind == 'takeoff_landing':
                            phase = evaluator.state
                            if phase in ('GROUND', 'HOVER'):
                                command = (0.0, 0.0, 0.3, 0.0)
                            elif phase == 'DESCEND':
                                command = (0.0, 0.0, -0.35, 0.0)
                            else:
                                command = (0.0, 0.0, 0.0, 0.0)
                        else:
                            command = case.command_forward_left_up_yawrate
                        setpoint = VelocitySetpoint(
                            *command, issued_at_s=step * dt,
                            expires_at_s=step * dt + ttl, control_epoch=0)
                        control = executor.step(setpoint, state, step * dt)
                        action = control.to_actuator_action(params)
                        before = state
                        _, _, terminated, truncated, _ = env.step(
                            torch.tensor([action], dtype=torch.float32,
                                         device=env.device))
                        boundary_state = boundary.after_step(
                            terminated[0].item(), truncated[0].item())
                        after = read_state()
                        speed = math.sqrt(sum(value * value
                                              for value in after.velocity_world_mps))
                        contact_force, sensor_prim = read_sensor_contact()
                        if contact_force > 0.02:
                            contact_max = max(contact_max, contact_force)
                            if contact_step is None:
                                contact_step = step
                                contact_prim = (sensor_prim or nearest_map_prim(
                                    after.position_world_m,
                                    after.velocity_world_mps)[0])
                        if boundary_state['truncated']:
                            outcome, reason = 'INVALID', 'ENV_TRUNCATED'
                        elif boundary_state['unexpected_reset']:
                            outcome, reason = 'INVALID', 'ENV_UNEXPECTED_RESET'
                        elif case.kind == 'reach':
                            decision = evaluator.update(
                                after.position_world_m, speed, elapsed,
                                collision=contact_force > 0.02)
                            outcome, reason = decision['outcome'], decision['reason']
                            phase = 'REACH'
                        elif case.kind == 'takeoff_landing':
                            decision = evaluator.update(
                                after.position_world_m, speed, contact_force, elapsed)
                            outcome, reason = decision['outcome'], decision['reason']
                            phase = decision['phase']
                        else:
                            phase = 'CONTACT'
                            bounds = contract
                            if (not (bounds.bounds_min_m[0] <= after.position_world_m[0]
                                     <= bounds.bounds_max_m[0])
                                    or not (bounds.bounds_min_m[1] <= after.position_world_m[1]
                                            <= bounds.bounds_max_m[1])):
                                outcome, reason = 'OUT_OF_BOUNDS', 'MAP_BOUNDS'
                            elif contact_force > 0.02:
                                outcome, reason = 'COLLISION', 'MAP_CONTACT'
                            elif elapsed >= case.timeout_s:
                                outcome, reason = 'TIMEOUT', 'CONTACT_TIMEOUT'
                        steps = step + 1
                        step_records.append({
                            'episode_id': episode_id, 'case_id': case.case_id,
                            'kind': case.kind, 'repeat': repeat, 'step': step,
                            'time_s': round(elapsed, 4),
                            'position_world_m': list(after.position_world_m),
                            'velocity_world_mps': list(after.velocity_world_mps),
                            'quat_wxyz': list(after.quat_wxyz),
                            'angular_velocity_body_radps': list(
                                after.angular_velocity_body_radps),
                            'command': list(command),
                            'phase': phase,
                            'contact_force_n': contact_force,
                            'contact_prim': contact_prim if contact_step is not None else '',
                            'outcome': outcome, 'reason': reason,
                            'env_terminated': boundary_state['terminated'],
                            'env_truncated': boundary_state['truncated'],
                            'episode_length_buf': boundary_state['episode_length_buf'],
                            'boundary_count_ok': boundary_state['count_ok'],
                        })
                        if outcome != 'RUNNING':
                            break
                    if outcome == 'RUNNING':
                        outcome, reason = 'INVALID', 'NO_TERMINAL_OBSERVED'
                    if case.kind == 'takeoff_landing' and outcome == 'SUCCESS':
                        capture(episode_id + '_landed')
                    if case.kind == 'contact' and contact_step is not None:
                        capture(episode_id + '_contact')
                    if case.kind == 'reach' and outcome == 'SUCCESS':
                        capture(episode_id + '_goal')
                    last = read_state()
                    results.append({
                        'episode_id': episode_id, 'case_id': case.case_id,
                        'kind': case.kind, 'repeat': repeat,
                        'outcome': outcome, 'reason': reason,
                        'steps': steps, 'duration_s': steps * dt,
                        'final_position_world_m': list(last.position_world_m),
                        'final_speed_mps': math.sqrt(sum(value * value
                                                         for value in last.velocity_world_mps)),
                        'phase': phase,
                        'contact_max_force_n': contact_max,
                        'contact_step': contact_step,
                        'contact_prim': contact_prim,
                        'start_position_world_m': list(case.start_position_world_m),
                        'goal_position_world_m': (None if case.goal_position_world_m
                                                  is None
                                                  else list(case.goal_position_world_m)),
                    })
        env._get_dones = original_dones

        mark('write outputs')
        invalid_episodes = sum(1 for item in results
                               if item['outcome'] == 'INVALID')
        summary = {
            'schema_version': 'boom_birds.map_eval.v1',
            'status': ('PASS' if invalid_episodes == 0 else 'FAIL'),
            'scope': 'RMUC2027_MAP_DYNAMICS_SMOKE_AND_FROZEN_CASES',
            'evidence_domain': 'SIMULATION_MODEL_GUI_MAP',
            'map': {
                'asset_id': contract.asset_id,
                'terrain_sha256': contract.terrain_sha256,
                'preview_sha256': contract.preview_sha256,
                'map_config_sha256': map_cfg_sha,
                'cases_sha256': case_sha,
                'bounds_min_m': list(contract.bounds_min_m),
                'bounds_max_m': list(contract.bounds_max_m),
                'world_frame': contract.world_frame,
                'body_frame': contract.body_frame,
                'units': 'm',
            },
            'counts': {
                kind: sum(1 for item in results if item['kind'] == kind)
                for kind in ('reach', 'takeoff_landing', 'contact')},
            'outcomes': {
                kind: {outcome: sum(1 for item in results
                                    if item['kind'] == kind and item['outcome'] == outcome)
                       for outcome in ('SUCCESS', 'COLLISION', 'TIMEOUT',
                                       'OUT_OF_BOUNDS', 'INVALID')}
                for kind in ('reach', 'takeoff_landing', 'contact')},
            'episodes': results,
            'invalid_episodes': invalid_episodes,
            'gui_mode': not bool(getattr(args, 'headless', False)),
            'screenshots': [str(path) for path in
                            (args.output / 'screenshots').glob('*.png')]
            if (args.output / 'screenshots').exists() else [],
        }
        (args.output / 'summary.json').write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        with (args.output / 'episodes.jsonl').open('w', encoding='utf-8') as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        with (args.output / 'steps.jsonl').open('w', encoding='utf-8') as handle:
            for item in step_records:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        (args.output / 'cases.json').write_text(
            json.dumps({'cases': [case.case_id for case in cases]}, indent=2) + '\n',
            encoding='utf-8')
        manifest = {
            'schema_version': 'boom_birds.manifest.v1',
            'code_commit': args.code_commit,
            'working_tree': args.working_tree,
            'gui_mode': not bool(getattr(args, 'headless', False)),
            'renderer': 'DirectX (--/app/vulkan=false)',
            'gpu_driver': args.gpu_driver,
            'isaac_sim': '5.1.0.0',
            'map_asset_id': contract.asset_id,
            'terrain_sha256': contract.terrain_sha256,
            'preview_sha256': contract.preview_sha256,
            'map_config_sha256': map_cfg_sha,
            'cases_sha256': case_sha,
            'command': ' '.join(sys.argv),
            'started_at': started_at,
            'outputs_sha256': {
                name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                for name in ('summary.json', 'episodes.jsonl', 'steps.jsonl')},
        }
        (args.output / 'manifest.json').write_text(
            json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        print('MAP_EVAL_' + summary['status'] + ' ' + json.dumps(summary['outcomes']),
              flush=True)
        raise SystemExit(0 if summary['status'] != 'FAIL' else 1)
    finally:
        env.close()
except SystemExit:
    raise
except BaseException:
    (args.output / 'summary.error.txt').write_text(
        'stages: ' + json.dumps(STAGES) + '\n\n' + traceback.format_exc(),
        encoding='utf-8')
    raise
finally:
    app.close()


def scenario_seed(case_index, repeat):
    return 9000 + case_index * 10 + repeat