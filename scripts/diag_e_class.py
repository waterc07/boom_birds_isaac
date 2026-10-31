"""E-class diagnostic entry: force-interface probes and minimal replay.

Records commands, measured state, requested and applied wrench, saturation and
termination ordering. This is a diagnostic tool, not an acceptance evaluator.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mode', choices=['probes', 'replay'], required=True)
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--scenario-manifest', type=Path, default=None)
parser.add_argument('--scenario-id', action='append', default=[])
parser.add_argument('--repeats', type=int, default=1)
parser.add_argument('--no-disturbance', action='store_true')
parser.add_argument('--timeout-s', type=float, default=12.0)
parser.add_argument('--probe-force-n', type=float, default=0.02)
parser.add_argument('--probe-torque-nm', type=float, default=0.0002)
parser.add_argument('--probe-window', default='0.5,1.5')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
app = AppLauncher(args).app

try:
    import torch
    import yaml
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from boom_birds.sim.disturbance import DisturbanceSpec
    from boom_birds.sim.guidance import BrakingGuidanceSpec, make_guidance
    from boom_birds.sim.isaac_layered_scene import (
        DisturbanceInjector, LayeredScene, spawn_layered_assets)
    from boom_birds.sim.layered import (
        DegradationSpec, LayeredScenario, layered_scenarios_from_manifest,
        load_layered_manifest)
    from boom_birds.sim.observation_interface import ObservationInterface
    from boom_birds.sim.reach import GuidanceSpec, ReachEvaluator, ReachSpec
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
    gains_cfg = config['gains']
    vehicle_cfg = config['vehicle']
    guidance_cfg = config.get('guidance', {})
    controller_cfg = config['controller']

    cfg = QuadcopterEnvCfg()
    cfg.scene.num_envs = 1
    cfg.sim.device = args.device
    cfg.seed = 0
    cfg.debug_vis = False
    cfg.decimation = 5
    cfg.episode_length_s = 60.0
    cfg.scene.clone_in_fabric = False
    if args.mode == 'probes':
        pass
    else:
        if not hasattr(cfg.robot.spawn, 'activate_contact_sensors'):
            raise RuntimeError('robot spawn config lacks contact sensors')
        cfg.robot.spawn.activate_contact_sensors = True
        spawn_layered_assets()
    env = QuadcopterEnv(cfg)
    env.reset(seed=0)
    try:
        dt = env.step_dt
        mass = float(env._robot_mass.item())
        inertias = env._robot.root_physx_view.get_inertias()
        body_id = int(env._body_id[0]) if not hasattr(env._body_id[0], 'item') \
            else int(env._body_id[0].item())
        if inertias.dim() == 3:
            matrix = inertias[0, body_id].tolist()
        else:
            matrix = inertias[0].tolist()
        params = VehicleParams(
            mass_kg=mass, inertia_kgm2=(matrix[0], matrix[4], matrix[8]),
            thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
            moment_scale_nm=float(vehicle_cfg['moment_scale_nm']),
            gravity_mps2=float(abs(sum(cfg.sim.gravity))),
            max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
        gains = VelocityGains(**{key: float(value) for key, value in gains_cfg.items()})
        executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)
        origin = env.scene.env_origins[0].tolist()
        zero_velocity = torch.zeros((1, 6), device=env.device)
        index = torch.tensor([0], device=env.device)
        hover_action = 2.0 / params.thrust_to_weight - 1.0

        def reset_pose(x, y, z, yaw_rad):
            quat = (math.cos(yaw_rad / 2.0), 0.0, 0.0, math.sin(yaw_rad / 2.0))
            pose = torch.tensor([[origin[0] + x, origin[1] + y, origin[2] + z,
                                  quat[0], quat[1], quat[2], quat[3]]],
                                dtype=torch.float32, device=env.device)
            env._robot.write_root_pose_to_sim(pose, index)
            env._robot.write_root_velocity_to_sim(zero_velocity, index)

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

        def state_row(step, state, injector, extra=None):
            row = {
                'step': step,
                'time_s': round(step * dt, 4),
                'position_world_m': list(state.position_world_m),
                'velocity_world_mps': list(state.velocity_world_mps),
                'quat_wxyz': list(state.quat_wxyz),
                'angular_velocity_body_radps': list(state.angular_velocity_body_radps),
                'yaw_rad': yaw_of(state),
                'applied_thrust_body_n': env._thrust[0, 0, :].tolist(),
                'applied_moment_body_nm': env._moment[0, 0, :].tolist(),
                'disturbance_force_body_n': list(injector.last_force),
                'disturbance_torque_body_nm': list(injector.last_torque),
            }
            if extra:
                row.update(extra)
            return row

        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        rows = []
        episodes = []
        metadata = {
            'mode': args.mode, 'config': str(args.config), 'dt_s': dt,
            'mass_kg': mass, 'inertia_kgm2': [matrix[0], matrix[4], matrix[8]],
            'gravity_mps2': params.gravity_mps2,
            'thrust_to_weight': params.thrust_to_weight,
            'moment_scale_nm': params.moment_scale_nm,
            'max_tilt_rad': params.max_tilt_rad,
            'hover_action_thrust': hover_action,
        }

        if args.mode == 'probes':
            start_s, end_s = (float(value) for value in args.probe_window.split(','))
            probes = [
                ('probe_none', 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0),
                ('probe_force_x_yaw0', args.probe_force_n,
                 (args.probe_force_n, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0),
                ('probe_force_x_yaw90', args.probe_force_n,
                 (args.probe_force_n, 0.0, 0.0), (0.0, 0.0, 0.0), math.pi / 2),
                ('probe_torque_z', 0.0, (0.0, 0.0, 0.0),
                 (0.0, 0.0, args.probe_torque_nm), 0.0),
            ]
            injector = DisturbanceInjector(env)
            metadata['disturbance_com_offset_body_m'] = \
                getattr(injector, 'com_offset_body_m', None)
            try:
                from isaaclab.utils.math import quat_rotate_inverse as _qri
                _data = env._robot.data
                _masses = env._robot.root_physx_view.get_masses()[0]
                _positions = _data.body_com_pos_w[0]
                _total = (_positions * _masses.unsqueeze(-1)).sum(dim=0) / _masses.sum()
                _delta_world = _total - _positions[injector._body_id]
                _delta_body = _qri(_data.root_quat_w[0], _delta_world)
                metadata['system_com_probe'] = {
                    'masses_kg': _masses.tolist(),
                    'body_com_pos_w': _positions.tolist(),
                    'system_com_w': _total.tolist(),
                    'delta_com_body_m': _delta_body.tolist(),
                }
            except Exception as error:
                metadata['system_com_probe'] = {'error': repr(error)}
            steps = int(round(2.0 / dt))
            with torch.inference_mode():
                for name, _mag, force, torque, yaw in probes:
                    env.reset(seed=0)
                    reset_pose(0.0, 0.0, 0.75, yaw)
                    spec = None
                    if name != 'probe_none':
                        spec = DisturbanceSpec(force_body_n=force,
                                               torque_body_nm=torque,
                                               start_s=start_s,
                                               duration_s=end_s - start_s)
                    injector.begin(spec)
                    action = torch.tensor([[hover_action, 0.0, 0.0, 0.0]],
                                          dtype=torch.float32, device=env.device)
                    episode_rows = []
                    for step in range(steps):
                        injector.tick(step * dt)
                        env.step(action)
                        state = read_state()
                        row = state_row(step, state, injector,
                                        {'episode': name})
                        rows.append(row)
                        episode_rows.append(row)
                    episodes.append({
                        'episode': name, 'steps': steps,
                        'force_body_n': list(force), 'torque_body_nm': list(torque),
                        'yaw_rad': yaw, 'window_s': [start_s, end_s],
                        'final_position_world_m': list(read_state().position_world_m),
                        'final_velocity_world_mps': list(read_state().velocity_world_mps),
                    })
        else:
            if args.scenario_manifest is None or not args.scenario_id:
                raise RuntimeError('replay needs --scenario-manifest and --scenario-id')
            manifest = load_layered_manifest(args.scenario_manifest)
            by_class = layered_scenarios_from_manifest(manifest)
            scenario_by_id = {}
            for items in by_class.values():
                for item in items:
                    scenario_by_id[item.scenario_id] = item
            selected = [scenario_by_id[item] for item in args.scenario_id]
            scene = LayeredScene(env, contact_threshold_n=0.02)
            injector = DisturbanceInjector(env)
            metadata['disturbance_com_offset_body_m'] = \
                getattr(injector, 'com_offset_body_m', None)
            proportional_spec = GuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('proportional', {}).items()})
            braking_spec = BrakingGuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('braking', {}).items()})
            timeout_s = args.timeout_s
            max_steps = int(math.ceil(timeout_s / dt))
            with torch.inference_mode():
                for scenario in selected:
                    variants = [True] if args.no_disturbance else [True, False]
                    for disturbance_on in variants:
                        for repeat in range(args.repeats):
                            env.reset(seed=scenario.seed)
                            scene.reset_scenario(scenario)
                            start = scenario.start_position_world_m
                            reset_pose(start[0], start[1], start[2],
                                       scenario.start_yaw_rad)
                            state = read_state()
                            executor.reset(state)
                            interface = ObservationInterface(
                                DegradationSpec(), dt, seed=scenario.seed)
                            spec = ReachSpec(
                                goal_position_world_m=scenario.goal_position_world_m,
                                timeout_s=timeout_s)
                            evaluator = ReachEvaluator(spec, dt)
                            guidance = make_guidance(
                                'proportional', scenario.goal_position_world_m,
                                proportional_spec=proportional_spec,
                                braking_spec=braking_spec)
                            disturbance = (scenario.disturbance
                                           if disturbance_on else None)
                            injector.begin(disturbance)
                            label = '{}{}r{}'.format(
                                scenario.scenario_id,
                                '_dist' if disturbance_on else '_nodist', repeat)
                            outcome, reason = 'RUNNING', 'RUNNING'
                            decision = None
                            steps = 0
                            for step in range(max_steps):
                                elapsed = (step + 1) * dt
                                injector.tick(step * dt)
                                truth = read_state()
                                observation = interface.observe(
                                    position=truth.position_world_m,
                                    velocity=truth.velocity_world_mps,
                                    quat_wxyz=truth.quat_wxyz, step_index=step)
                                command = guidance.command(
                                    position_world_m=observation.position,
                                    velocity_world_mps=observation.velocity,
                                    quat_wxyz=observation.quat_wxyz)
                                setpoint = VelocitySetpoint(
                                    *command, issued_at_s=step * dt,
                                    expires_at_s=step * dt + float(controller_cfg['ttl_s']),
                                    control_epoch=0)
                                control = executor.step(setpoint, truth, step * dt)
                                action = control.to_actuator_action(params)
                                before = truth
                                env.step(torch.tensor([action], dtype=torch.float32,
                                                      device=env.device))
                                scene.update(scenario, elapsed)
                                after = read_state()
                                evidence = scene.contact_evidence(
                                    scenario, after.position_world_m, step=step)
                                speed = math.sqrt(sum(value * value
                                                      for value in after.velocity_world_mps))
                                env_terminated = False
                                steps = step + 1
                                collision = evidence.contact
                                decision = evaluator.update(
                                    position_world_m=after.position_world_m,
                                    speed_mps=speed, now_s=elapsed,
                                    collision=collision)
                                desired_force = control.desired_thrust_world_n
                                horizontal = math.hypot(desired_force[0],
                                                        desired_force[1])
                                tilt_limit_force = (params.mass_kg * params.gravity_mps2
                                                    * math.tan(params.max_tilt_rad))
                                saturation = {
                                    'tilt': horizontal >= tilt_limit_force * 0.999,
                                    'thrust': (control.thrust_body_n
                                               >= params.max_thrust_n * 0.999),
                                    'torque': any(abs(value)
                                                  >= params.moment_scale_nm * 0.999
                                                  for value in control.torque_body_nm),
                                }
                                rows.append(state_row(
                                    step, after, injector, {
                                        'episode': label,
                                        'scenario_id': scenario.scenario_id,
                                        'disturbance_on': disturbance_on,
                                        'repeat': repeat,
                                        'before_position_world_m': list(
                                            before.position_world_m),
                                        'before_velocity_world_mps': list(
                                            before.velocity_world_mps),
                                        'command_forward_left_up_yawrate': list(command),
                                        'desired_velocity_world_mps': list(
                                            control.desired_velocity_world_mps),
                                        'control_thrust_body_n': control.thrust_body_n,
                                        'control_torque_body_nm': list(
                                            control.torque_body_nm),
                                        'control_desired_thrust_world_n': list(
                                            desired_force),
                                        'actuator_action': list(action),
                                        'saturation': saturation,
                                        'distance_m': decision.distance_m,
                                        'speed_mps': speed,
                                        'contact_evidence': evidence.contact,
                                        'contact_force_n': evidence.force_n,
                                        'contacting_obstacles': list(
                                            evidence.contacting_obstacles),
                                        'outcome': decision.outcome,
                                        'reason': decision.reason,
                                    }))
                                if decision.terminated:
                                    outcome, reason = decision.outcome, decision.reason
                                    break
                            if outcome == 'RUNNING':
                                outcome, reason = 'OUT_OF_BOUNDS', 'NO_TERMINAL'
                            episodes.append({
                                'episode': label,
                                'scenario_id': scenario.scenario_id,
                                'disturbance_on': disturbance_on,
                                'repeat': repeat,
                                'outcome': outcome,
                                'reason': reason,
                                'steps': steps,
                                'final_distance_m': (decision.distance_m
                                                     if decision else None),
                                'disturbance': (None if scenario.disturbance is None
                                                else scenario.disturbance.__dict__),
                            })
                del scene
        (output / 'steps.jsonl').write_text(
            '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n',
            encoding='utf-8')
        summary = {'metadata': metadata, 'episodes': episodes,
                   'row_count': len(rows)}
        (output / 'summary.json').write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        print('DIAG_DONE', args.mode, output, flush=True)
        print(json.dumps({'episodes': episodes, 'row_count': len(rows)},
                         indent=2), flush=True)
        raise SystemExit(0)
    finally:
        env.close()
finally:
    app.close()