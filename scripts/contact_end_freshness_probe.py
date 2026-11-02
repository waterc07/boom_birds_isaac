"""DSH contact-end freshness probe (GUI, single env).

Controlled kinematic obstacle moves into the robot (contact established),
presses (sustained contact), then moves away under explicit kinematic motion
(natural separation, robot is NOT teleported), then returns (re-contact).
Repeats the cycle 3 times inside one episode and records raw filtered/net
vectors, physics step numbers, timestamps, poses and geometry.

A separate `--separation-mode robot_teleport` control records the explicit
teleport/reset comparison in a separate output directory; it is never mixed
with the natural-separation result.  No mid-episode hard reset.
"""
import argparse
import json
import math
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--cycles', type=int, default=3)
parser.add_argument('--separation-mode',
                    choices=('obstacle_motion', 'robot_teleport'),
                    default='obstacle_motion')
parser.add_argument('--sustain-steps', type=int, default=20)
parser.add_argument('--separate-steps', type=int, default=30)
parser.add_argument('--approach-speed-mps', type=float, default=0.4)
parser.add_argument('--contact-threshold-n', type=float, default=1e-6)
parser.add_argument('--screenshots', action='store_true')
parser.add_argument('--zero-tolerance-n', type=float, default=1e-6)
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
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)

    sys.path.insert(0, str(Path('src').resolve()))
    from boom_birds.evaluation.contact_raw_audit import audit_row
    from boom_birds.sim.dynamic_contact_session import DynamicContactSession
    from boom_birds.sim.usd_body_envelope import measure_collision_envelope
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    config = yaml.safe_load(Path('configs/vehicles/sim_reference.yaml')
                            .read_text(encoding='utf-8'))
    gains = VelocityGains(**{k: float(v) for k, v in config['gains'].items()})
    vehicle_cfg = config['vehicle']

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
    cfg.scene = ProbeSceneCfg(num_envs=1, env_spacing=2.5,
                              replicate_physics=False, clone_in_fabric=False)
    env = QuadcopterEnv(cfg)
    env.reset(seed=0)
    stage = None
    try:
        env.sim.reset(soft=False)
        env.reset(seed=0)
        dt = env.step_dt
        try:
            physics_dt = float(env.sim.get_physics_dt())
        except Exception:
            physics_dt = 0.01
        origin = env.scene.env_origins[0].tolist()
        stage = omni.usd.get_context().get_stage()
        robot_root = '/World/envs/env_0/Robot'
        dyn_path = '/World/envs/env_0/Obstacle'
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
            gravity_mps2=9.81,
            max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
        executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)
        envelope = measure_collision_envelope(stage, robot_root)
        robot_radius = envelope['sphere_about_origin']['radius_m']
        obstacle_size = (0.4, 0.4, 0.6)
        obstacle_radius = math.sqrt(sum((v / 2.0) ** 2 for v in obstacle_size))

        def set_robot_pose(position):
            pose = torch.tensor([[origin[0] + position[0],
                                  origin[1] + position[1],
                                  origin[2] + position[2], 1.0, 0.0, 0.0, 0.0]],
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

        def hover_step():
            control = executor.step(VelocitySetpoint(
                0.0, 0.0, 0.0, 0.0, issued_at_s=0.0, expires_at_s=10.0,
                control_epoch=0), read_state(), 0.0)
            env.step(torch.tensor([control.to_actuator_action(params)],
                                  dtype=torch.float32, device=env.device))

        def hold_at(position):
            set_robot_pose(position)
            hover_step()

        def hold_step():
            # Station-keeping only: the robot is re-posed at its declared hover
            # point each step so the controlled obstacle can execute the
            # approach/sustain/separate/re-contact cycle.  This pose hold is
            # NOT used to create the natural separation; separation is produced
            # solely by obstacle motion.
            hold_at((0.0, 0.0, 1.0))

        def capture(label):
            if not args.screenshots:
                return None
            try:
                from omni.kit.viewport.utility import (
                    get_active_viewport, capture_viewport_to_file)
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
                print('[contact-end] screenshot warning: ' + repr(error),
                      flush=True)
                return None

        session = DynamicContactSession(
            env, generation=1, body_path=robot_root + '/body',
            target_path=dyn_path, dt_s=dt)
        set_robot_pose((0.0, 0.0, 1.0))
        set_obstacle_pose((0.0, 0.0, 50.0))
        handshake = session.establish_zero(hover_step, max_steps=20,
                                           zero_tolerance_n=args.zero_tolerance_n)
        rows = []
        phases = []
        step_index = 0

        def sample_row(cycle, phase, robot_position, obstacle_position,
                       obstacle_velocity, state):
            step_index = len(rows) + 1
            sample = session.read()
            measured = audit_row({'contact_readout': {'reads': sample['contact_readout']['reads']}})
            distance = math.sqrt(sum(
                (robot_position[i] + origin[i] - obstacle_position[i]) ** 2
                for i in range(3)))
            box_sep = max(abs(robot_position[i] + origin[i] - obstacle_position[i])
                          - (envelope['aabb']['half_extents_m'][i]
                             + obstacle_size[i] / 2.0) for i in range(3))
            row = {
                'schema_version': 'dsh.contact_end_sample.v1',
                'cycle': cycle, 'phase': phase,
                'sample_index': step_index,
                'physics_step': int(env._sim_step_counter),
                'physics_generation': sample['physics_generation'],
                'host_wall_time_ns': time.time_ns(),
                'sim_time_s': float(getattr(env.sim, 'current_time', 0.0)),
                'robot_world_m': [float(robot_position[i] + origin[i])
                                  for i in range(3)],
                'obstacle_world_m': [float(v) for v in obstacle_position],
                'obstacle_velocity_world_mps': [float(v) for v in obstacle_velocity],
                'robot_velocity_world_mps': list(state.velocity_world_mps),
                'center_distance_m': distance,
                'box_separation_m': box_sep,
                'robot_radius_m': robot_radius,
                'obstacle_radius_m': obstacle_radius,
                'sphere_overlap_m': robot_radius + obstacle_radius - distance,
                'target_path': dyn_path,
                'filter_count': sample['filter_count'],
                'body_names': sample['body_names'],
                'contact_readout': sample['contact_readout'],
                'measure': measured,
                'raw_consistent': (math.isclose(measured['measured_force_n'],
                                                sample['measure']['measured_force_n'],
                                                abs_tol=1e-9)),
                'natural_separation': args.separation_mode == 'obstacle_motion',
            }
            rows.append(row)
            return row

        set_robot_pose((0.0, 0.0, 1.0))
        set_obstacle_pose((1.4, 0.0, 1.0))
        hover_step()
        obstacle_x = 1.4
        for cycle in range(args.cycles):
            # 1) continuous approach from the current obstacle position; no
            # teleport jump at the cycle boundary.
            contact = False
            for approach in range(160):
                state = read_state()
                obstacle_x = max(-0.15, obstacle_x - args.approach_speed_mps * dt)
                set_obstacle_pose((obstacle_x, 0.0, 1.0))
                hold_step()
                state = read_state()
                sample = sample_row(cycle, 'approach', state.position_world_m,
                                    [obstacle_x, 0.0, 1.0],
                                    [-args.approach_speed_mps, 0, 0], state)
                if sample['measure']['measured_force_n'] > args.contact_threshold_n \
                        or sample['box_separation_m'] < 0.0:
                    contact = True
                    break
            # 2) sustained contact: obstacle tracks the robot at a contact offset
            for sustain in range(args.sustain_steps):
                state = read_state()
                robot = [state.position_world_m[i] + origin[i] for i in range(3)]
                obstacle_x = robot[0] - 0.15
                set_obstacle_pose((obstacle_x, robot[1], 1.0))
                hold_step()
                state = read_state()
                sample_row(cycle, 'sustain', state.position_world_m,
                           [obstacle_x, robot[1], 1.0], [0.0, 0.0, 0.0], state)
                if cycle == 1 and sustain == 10:
                    capture('contact_end_sustain')
            # 3) natural separation: obstacle moves away continuously; robot pose
            # is station-kept, never teleported to create the separation.
            separated_zero = False
            separation_force_zero_rows = 0
            for offset in range(args.separate_steps):
                if args.separation_mode == 'robot_teleport':
                    if offset == 0:
                        teleport_target = (0.0 + 2.0, 0.0, 1.0)
                    hold_at(teleport_target)
                    obstacle_target = (obstacle_x, 0.0, 1.0)
                else:
                    obstacle_x += args.approach_speed_mps * dt
                    set_obstacle_pose((obstacle_x, 0.0, 1.0))
                    hold_step()
                    obstacle_target = (obstacle_x, 0.0, 1.0)
                state = read_state()
                sample = sample_row(cycle, 'separation', state.position_world_m,
                                    obstacle_target,
                                    ([0.0, 0.0, 0.0] if args.separation_mode ==
                                     'robot_teleport' else
                                     [args.approach_speed_mps, 0, 0]), state)
                if sample['measure']['measured_force_n'] <= args.zero_tolerance_n \
                        and sample['box_separation_m'] > 0.1:
                    separated_zero = True
                    separation_force_zero_rows += 1
            # 4) re-contact: obstacle returns continuously from its far position
            if args.separation_mode == 'robot_teleport':
                set_robot_pose((0.0, 0.0, 1.0))
            recontact = False
            for approach in range(180):
                obstacle_x = max(-0.15, obstacle_x - args.approach_speed_mps * dt)
                set_obstacle_pose((obstacle_x, 0.0, 1.0))
                hold_step()
                state = read_state()
                sample = sample_row(cycle, 'recontact', state.position_world_m,
                                    [obstacle_x, 0.0, 1.0],
                                    [-args.approach_speed_mps, 0, 0], state)
                if sample['measure']['measured_force_n'] > args.contact_threshold_n \
                        or sample['box_separation_m'] < 0.0:
                    recontact = True
                    break
            phases.append({'cycle': cycle, 'contact': contact,
                           'separated_zero': separated_zero,
                           'separation_force_zero_rows': separation_force_zero_rows,
                           'recontact': recontact,
                           'separation_mode': args.separation_mode})
        # explicit teleport control is a separate invocation/mode, not mixed here
        result = {
            'schema_version': 'dsh.contact_end_freshness.v1',
            'status': 'DIAGNOSTIC',
            'separation_mode': args.separation_mode,
            'natural_separation': args.separation_mode == 'obstacle_motion',
            'hard_reset_at_episode_start': True,
            'mid_episode_hard_reset': False,
            'zero_tolerance_n': args.zero_tolerance_n,
            'contact_threshold_n': args.contact_threshold_n,
            'handshake': handshake,
            'physics_generation': 1,
            'envelope': envelope,
            'obstacle_size_m': list(obstacle_size),
            'obstacle_radius_m': obstacle_radius,
            'phases': phases,
            'rows': rows,
            'limitations': [
                'single environment diagnostic probe; not a formal production episode',
                'filtered target is the obstacle root; negative coverage unverified',
                'zero read is not proof of no contact',
                'natural separation is kinematic obstacle motion, not robot teleport',
                'teleport control must be run in a separate invocation/mode',
                'robot station-keeping pose hold is used only to keep the controlled geometry; natural separation is obstacle motion',
            ],
        }
        (args.output / 'contact_end_freshness.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        print('DSH_CONTACT_END_DONE ' + json.dumps({
            'mode': args.separation_mode, 'cycles': len(phases),
            'phases': phases, 'rows': len(rows)}, ensure_ascii=False), flush=True)
    finally:
        env.close()
except BaseException:
    (args.output / 'summary.error.txt').write_text(
        traceback.format_exc(), encoding='utf-8')
    raise
finally:
    app.close()
