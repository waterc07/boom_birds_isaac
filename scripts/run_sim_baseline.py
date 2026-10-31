"""Project velocity -> outer loop -> body thrust/moment -> PhysX response chain.

Evidence domain: SIMULATION MODEL. It does not prove PX4, SITL/HIL, real
actuator or flight behaviour. The KINEMATIC scenario writes velocity directly
and is a reference only; it is never used for dynamics or transfer acceptance.
"""
import argparse
import datetime
import hashlib
import inspect
import json
import math
import sys
import traceback
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--task', default='velocity_step', choices=['velocity_step', 'reach', 'compare', 'layered'])
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--scenarios', default='all')
parser.add_argument('--seed', type=int, default=0)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--csv', type=Path, default=None)
parser.add_argument('--episodes', type=int, default=6)
parser.add_argument('--goal', default='1.5,1.0,0.75')
parser.add_argument('--timeout-s', type=float, default=20.0)
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--working-tree', default='recorded by the operator')
parser.add_argument('--scenario-manifest', type=Path, default=None)
parser.add_argument('--methods', default='proportional')
parser.add_argument('--run-kind', default='final', choices=['tuning', 'final', 'fault'])
parser.add_argument('--fault', default='none')
parser.add_argument('--fault-step', type=int, default=10)
parser.add_argument('--fault-timeout-s', type=float, default=1.5)
parser.add_argument('--scenario-limit', type=int, default=0)
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--classes', default='all')
parser.add_argument('--limit-per-class', type=int, default=0)
parser.add_argument('--min-valid-per-class', type=int, default=20)
parser.add_argument('--min-valid-total', type=int, default=100)
parser.add_argument('--contact-threshold-n', type=float, default=0.02)
parser.add_argument('--require-coverage', action='store_true')
parser.add_argument('--clone-in-usd', action='store_true')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
app = AppLauncher(args).app

STAGES = ['imports']
error_path = (Path(args.output) / 'summary.error.txt'
              if args.task in ('compare', 'layered')
              else args.output.with_suffix('.error.txt'))


def mark(name):
    STAGES.append(name)
    print('[stage] ' + name, flush=True)


try:
    mark('import isaac modules')
    import torch
    import yaml
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import QuadcopterEnv, QuadcopterEnvCfg

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains, VelocitySetpoint,
    )

    mark('read config')
    config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
    gains_cfg = config['gains']
    vehicle_cfg = config['vehicle']
    controller_cfg = config['controller']

    mark('build env config')
    cfg = QuadcopterEnvCfg()
    cfg.scene.num_envs = 1
    cfg.sim.device = args.device
    cfg.seed = args.seed
    cfg.debug_vis = False
    cfg.decimation = 5
    cfg.episode_length_s = 60.0
    if args.clone_in_usd:
        cfg.scene.clone_in_fabric = False

    layered_paths = None
    if args.task == 'layered':
        if not hasattr(cfg.robot.spawn, 'activate_contact_sensors'):
            raise RuntimeError('robot spawn config lacks activate_contact_sensors')
        cfg.robot.spawn.activate_contact_sensors = True
        mark('spawn layered assets')
        from boom_birds.sim.isaac_layered_scene import spawn_layered_assets
        layered_paths = spawn_layered_assets()
    mark('create env')
    env = QuadcopterEnv(cfg)
    try:
        mark('reset env')
        env.reset(seed=args.seed)

        mark('read plant parameters')
        dt = env.step_dt
        if abs(dt - 0.05) > 1e-9:
            raise RuntimeError('expected a 20 Hz control step, got ' + str(dt))
        mass = float(env._robot_mass.item())
        inertias = env._robot.root_physx_view.get_inertias()
        raw_body_id = env._body_id[0]
        body_id = int(raw_body_id.item()) if hasattr(raw_body_id, 'item') else int(raw_body_id)
        shape = tuple(inertias.shape)
        if len(shape) == 3:
            inertia_matrix = inertias[0, body_id].tolist()
        elif len(shape) == 2:
            inertia_matrix = inertias[0].tolist()
        else:
            raise RuntimeError('unexpected inertia shape ' + str(shape))
        inertia = (inertia_matrix[0], inertia_matrix[4], inertia_matrix[8])
        gravity = math.sqrt(sum(value * value for value in cfg.sim.gravity))
        params = VehicleParams(
            mass_kg=mass, inertia_kgm2=inertia,
            thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
            moment_scale_nm=float(vehicle_cfg['moment_scale_nm']),
            gravity_mps2=float(gravity),
            max_tilt_rad=float(vehicle_cfg['max_tilt_rad']),
        )
        gains = VelocityGains(**{key: float(value) for key, value in gains_cfg.items()})
        executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)
        origin = env.scene.env_origins[0].tolist()
        zero_velocity = torch.zeros((1, 6), device=env.device)
        index = torch.tensor([0], device=env.device)

        def reset_pose(yaw_rad):
            quat = (math.cos(yaw_rad / 2.0), 0.0, 0.0, math.sin(yaw_rad / 2.0))
            pose = torch.tensor([[origin[0], origin[1], origin[2] + 0.75,
                                  quat[0], quat[1], quat[2], quat[3]]],
                                dtype=torch.float32, device=env.device)
            env._robot.write_root_pose_to_sim(pose, index)
            env._robot.write_root_velocity_to_sim(zero_velocity, index)

        def read_state():
            position = env._robot.data.root_pos_w[0].tolist()
            velocity = env._robot.data.root_lin_vel_w[0].tolist()
            quat = env._robot.data.root_quat_w[0].tolist()
            ang_vel = env._robot.data.root_ang_vel_b[0].tolist()
            return VehicleState(
                position_world_m=tuple(position[i] - origin[i] for i in range(3)),
                velocity_world_mps=tuple(velocity),
                quat_wxyz=tuple(quat),
                angular_velocity_body_radps=tuple(ang_vel),
            )

        def yaw_of(state):
            w, x, y, z = state.quat_wxyz
            return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

        if args.task == 'reach':
            mark('run reach episodes')
            from boom_birds.evaluation.episodes import (
                MANIFEST_SCHEMA_ID, EpisodeResult, summarize, write_manifest)
            from boom_birds.sim.reach import (
                OUTCOME_RUNNING, GuidanceSpec, ReachEvaluator, ReachSpec, guidance_command)

            goal = tuple(float(value) for value in args.goal.split(','))
            if len(goal) != 3:
                raise RuntimeError('--goal needs three comma separated values')
            spec = ReachSpec(goal_position_world_m=goal, timeout_s=args.timeout_s)
            guidance = GuidanceSpec()
            evaluator = ReachEvaluator(spec, dt)
            reach_ttl = float(controller_cfg['ttl_s'])
            started_at = datetime.datetime.now().astimezone().isoformat()
            results = []
            episode_rows = []
            max_steps = int(math.ceil(args.timeout_s / dt))
            with torch.inference_mode():
                for episode_index in range(args.episodes):
                    env.reset(seed=episode_index)
                    reset_pose(0.0)
                    state = read_state()
                    executor.reset(state)
                    evaluator.reset()
                    episode_peak = 0.0
                    outcome, reason = OUTCOME_RUNNING, 'RUNNING'
                    steps = 0
                    decision = None
                    for step in range(max_steps):
                        elapsed = (step + 1) * dt
                        state = read_state()
                        command = guidance_command(
                            position_world_m=state.position_world_m,
                            quat_wxyz=state.quat_wxyz,
                            goal_position_world_m=goal, spec=guidance)
                        setpoint = VelocitySetpoint(
                            *command, issued_at_s=step * dt,
                            expires_at_s=step * dt + reach_ttl, control_epoch=0)
                        control = executor.step(setpoint, state, step * dt)
                        action = control.to_actuator_action(params)
                        _, _, terminated, _, _ = env.step(
                            torch.tensor([action], dtype=torch.float32, device=env.device))
                        after = read_state()
                        speed = math.sqrt(sum(value * value
                                              for value in after.velocity_world_mps))
                        episode_peak = max(episode_peak, speed)
                        env_terminated = bool(terminated[0].item())
                        collision = (env_terminated
                                     and after.position_world_m[2] <= spec.collision_height_m)
                        decision = evaluator.update(
                            position_world_m=after.position_world_m, speed_mps=speed,
                            now_s=elapsed, collision=collision)
                        steps = step + 1
                        episode_rows.append({
                            'episode': episode_index, 'step': step,
                            'time_s': round(elapsed, 4),
                            'command': list(command),
                            'position_world_m': list(after.position_world_m),
                            'velocity_world_mps': list(after.velocity_world_mps),
                            'yaw_rad': yaw_of(after), 'speed_mps': speed,
                            'outcome': decision.outcome, 'reason': decision.reason,
                            'distance_m': decision.distance_m,
                            'hold_time_s': decision.hold_time_s,
                        })
                        if decision.outcome == OUTCOME_RUNNING and env_terminated:
                            outcome, reason = 'INVALID', 'ENV_TERMINATED_ALTITUDE'
                            break
                        if decision.terminated:
                            outcome, reason = decision.outcome, decision.reason
                            break
                    results.append(EpisodeResult(
                        episode_id='reach-' + str(episode_index), seed=episode_index,
                        outcome=outcome, steps=steps, duration_s=steps * dt,
                        final_distance_m=decision.distance_m if decision else float('nan'),
                        peak_speed_mps=episode_peak, reason=reason))
            summary = summarize(results)
            summary.update({
                'status': 'INCOMPLETE' if args.episodes < 100 else 'PASS',
                'sample_size_rule': ('INCOMPLETE below the PROPOSED 100-episode '
                                     'frozen sample in V2.2 20.11'),
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
                'task': 'obstacle_free_reach_stop',
                'proposed_thresholds': {
                    'success_distance_m': spec.success_distance_m,
                    'success_speed_mps': spec.success_speed_mps,
                    'hold_time_s': spec.hold_time_s,
                    'timeout_s': spec.timeout_s,
                    'collision_height_m': spec.collision_height_m,
                    'arrival_radius_m': guidance.arrival_radius_m,
                },
                'frozen_threshold': None,
                'seeds': list(range(args.episodes)),
            })
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
            if args.csv:
                args.csv.parent.mkdir(parents=True, exist_ok=True)
                columns = ['episode', 'step', 'time_s', 'command', 'position_world_m',
                           'velocity_world_mps', 'yaw_rad', 'speed_mps', 'outcome',
                           'reason', 'distance_m', 'hold_time_s']
                with args.csv.open('w', encoding='utf-8') as handle:
                    handle.write(','.join(columns) + '\n')
                    for row in episode_rows:
                        handle.write(','.join(json.dumps(row[column])
                                              for column in columns) + '\n')
            summary_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
            manifest = {
                'schema_version': MANIFEST_SCHEMA_ID,
                'code_commit': args.code_commit,
                'working_tree': 'recorded by the operator when invoking the script',
                'config_sha256': {
                    str(args.config): hashlib.sha256(args.config.read_bytes()).hexdigest()},
                'asset_versions': {
                    'isaac_sim': '5.1.0.0 (host manifest)',
                    'task_source_sha256': hashlib.sha256(
                        Path(inspect.getfile(QuadcopterEnv)).read_bytes()).hexdigest(),
                    'asset_uri': str(getattr(cfg.robot.spawn, 'usd_path', None)),
                },
                'seeds': {'episodes': list(range(args.episodes))},
                'command': ' '.join(sys.argv),
                'started_at': started_at,
                'exit_code': 0,
                'outputs_sha256': {args.output.name: summary_sha},
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
            }
            write_manifest(args.output.parent, manifest)
            print('BOOM_BIRDS_SIM_REACH_' + summary['status'], flush=True)
            print(json.dumps(summary, indent=2), flush=True)
            raise SystemExit(0)

        if args.task == 'compare':
            mark('run guidance comparison')
            from boom_birds.evaluation.comparison import (
                fault_classification_summary, method_summary, paired_comparison,
                stratified_summary)
            from boom_birds.evaluation.episodes import (
                MANIFEST_SCHEMA_ID, EpisodeResult, write_manifest)
            from boom_birds.sim.faults import (
                COLLISION_CONTACT, COLLISION_FLAG, FAULT_NONE, INVALID_OBSERVATION,
                TIMEOUT, FaultSpec, apply_observation_fault, collision_flag,
                effective_timeout_s)
            from boom_birds.sim.guidance import (
                METHODS, BrakingGuidanceSpec, make_guidance)
            from boom_birds.sim.reach import GuidanceSpec, ReachEvaluator, ReachSpec
            from boom_birds.sim.scenarios import (
                load_scenario_manifest, scenarios_from_manifest)

            if args.scenario_manifest is None:
                raise RuntimeError('--scenario-manifest is required for --task compare')
            scenario_manifest = load_scenario_manifest(args.scenario_manifest)
            scenarios = list(scenarios_from_manifest(scenario_manifest))
            if args.scenario_limit > 0:
                scenarios = scenarios[:args.scenario_limit]
            requested_methods = [item.strip() for item in args.methods.split(',')
                                 if item.strip()]
            for name in requested_methods:
                if name not in METHODS:
                    raise RuntimeError('unknown guidance method: ' + name)
            guidance_cfg = config.get('guidance', {})
            proportional_spec = GuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('proportional', {}).items()})
            braking_spec = BrakingGuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('braking', {}).items()})
            guidance_params = {
                'proportional': {
                    key: float(value)
                    for key, value in guidance_cfg.get('proportional', {}).items()},
                'braking': {
                    key: float(value)
                    for key, value in guidance_cfg.get('braking', {}).items()},
            }
            threshold_spec = ReachSpec()
            thresholds = {
                'success_distance_m': threshold_spec.success_distance_m,
                'success_speed_mps': threshold_spec.success_speed_mps,
                'hold_time_s': threshold_spec.hold_time_s,
                'timeout_s': args.timeout_s,
                'collision_height_m': threshold_spec.collision_height_m,
                'max_abs_position_m': threshold_spec.max_abs_position_m,
            }
            fault_kinds = [item.strip() for item in args.fault.split(',') if item.strip()]
            faults = []
            for kind in fault_kinds:
                if kind == FAULT_NONE:
                    faults.append(FaultSpec())
                elif kind == TIMEOUT:
                    faults.append(FaultSpec(TIMEOUT, step=0, timeout_s=args.fault_timeout_s))
                else:
                    faults.append(FaultSpec(kind, step=args.fault_step))
            if args.freeze is not None:
                freeze = json.loads(args.freeze.read_text(encoding='utf-8'))
                if freeze.get('config_sha256') != hashlib.sha256(
                        args.config.read_bytes()).hexdigest():
                    raise RuntimeError('frozen config hash mismatch')
                if freeze.get('scenario_sha256') != scenario_manifest['content_sha256']:
                    raise RuntimeError('frozen scenario hash mismatch')
                if freeze.get('guidance') != guidance_params:
                    raise RuntimeError('frozen guidance parameters mismatch')
                if freeze.get('thresholds') != thresholds:
                    raise RuntimeError('frozen thresholds mismatch')
                mark('freeze verified')

            def reset_scenario(scenario):
                start = scenario.start_position_world_m
                yaw = scenario.start_yaw_rad
                quat = (math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0))
                pose = torch.tensor([[origin[0] + start[0], origin[1] + start[1],
                                      origin[2] + start[2], quat[0], quat[1],
                                      quat[2], quat[3]]],
                                    dtype=torch.float32, device=env.device)
                env._robot.write_root_pose_to_sim(pose, index)
                env._robot.write_root_velocity_to_sim(zero_velocity, index)

            original_dones = env._get_dones
            results = []
            episode_records = []
            started_at = datetime.datetime.now().astimezone().isoformat()
            ttl_compare = float(controller_cfg['ttl_s'])
            effect_scope = {
                COLLISION_FLAG: 'CONTRACT_PATH_ONLY',
                COLLISION_CONTACT: 'PHYSX_CONTACT',
                TIMEOUT: 'TIMEOUT_TRUNCATION',
                INVALID_OBSERVATION: 'INTERFACE_LAYER',
                FAULT_NONE: 'NATURAL',
            }
            expected_outcome = {
                COLLISION_FLAG: 'COLLISION',
                COLLISION_CONTACT: 'COLLISION',
                TIMEOUT: 'TIMEOUT',
                INVALID_OBSERVATION: 'INVALID',
                FAULT_NONE: 'SUCCESS',
            }
            with torch.inference_mode():
                for fault in faults:
                    if fault.kind == COLLISION_CONTACT:
                        env._get_dones = lambda: (
                            torch.zeros(env.num_envs, dtype=torch.bool,
                                        device=env.device),
                            env.episode_length_buf >= env.max_episode_length - 1)
                    else:
                        env._get_dones = original_dones
                    for scenario in scenarios:
                        for method_name in requested_methods:
                            env.reset(seed=scenario.seed)
                            reset_scenario(scenario)
                            state = read_state()
                            executor.reset(state)
                            timeout_s = effective_timeout_s(args.timeout_s, fault)
                            spec = ReachSpec(
                                goal_position_world_m=scenario.goal_position_world_m,
                                timeout_s=timeout_s)
                            evaluator = ReachEvaluator(spec, dt)
                            guidance = make_guidance(
                                method_name, scenario.goal_position_world_m,
                                proportional_spec=proportional_spec,
                                braking_spec=braking_spec)
                            outcome, reason = 'RUNNING', 'RUNNING'
                            steps = 0
                            peak_speed = 0.0
                            min_z = state.position_world_m[2]
                            last_position = state.position_world_m
                            decision = None
                            contact_observed = False
                            plateau = 0
                            last_z = None
                            injected = False
                            max_steps = int(math.ceil(timeout_s / dt)) + 5
                            for step in range(max_steps):
                                elapsed = (step + 1) * dt
                                state = read_state()
                                last_position = state.position_world_m
                                observation = apply_observation_fault(
                                    state.position_world_m, state.velocity_world_mps,
                                    state.quat_wxyz, fault, step)
                                if fault.kind == COLLISION_CONTACT:
                                    command = (0.0, 0.0, -0.3, 0.0)
                                else:
                                    try:
                                        command = guidance.command(
                                            position_world_m=observation[0],
                                            velocity_world_mps=observation[1],
                                            quat_wxyz=observation[2])
                                    except ValueError:
                                        outcome, reason = 'INVALID', 'NONFINITE'
                                        injected = True
                                        break
                                setpoint = VelocitySetpoint(
                                    *command, issued_at_s=step * dt,
                                    expires_at_s=step * dt + ttl_compare,
                                    control_epoch=0)
                                control = executor.step(setpoint, state, step * dt)
                                action = control.to_actuator_action(params)
                                _, _, terminated, _, _ = env.step(
                                    torch.tensor([action], dtype=torch.float32,
                                                 device=env.device))
                                after = read_state()
                                last_position = after.position_world_m
                                speed = math.sqrt(sum(value * value
                                                      for value in after.velocity_world_mps))
                                peak_speed = max(peak_speed, speed)
                                min_z = min(min_z, after.position_world_m[2])
                                steps = step + 1
                                if fault.kind == COLLISION_CONTACT:
                                    if (last_z is not None
                                            and abs(after.position_world_m[2] - last_z) < 1e-5
                                            and after.position_world_m[2] < 0.2):
                                        plateau += 1
                                    else:
                                        plateau = 0
                                    last_z = after.position_world_m[2]
                                    if after.position_world_m[2] <= 0.02 or plateau >= 3:
                                        contact_observed = True
                                        decision = evaluator.update(
                                            position_world_m=after.position_world_m,
                                            speed_mps=speed, now_s=elapsed,
                                            collision=True)
                                        outcome, reason = decision.outcome, decision.reason
                                        break
                                    if bool(terminated[0].item()):
                                        decision = evaluator.update(
                                            position_world_m=after.position_world_m,
                                            speed_mps=speed, now_s=elapsed,
                                            collision=True)
                                        outcome, reason = decision.outcome, decision.reason
                                        break
                                    continue
                                collision = collision_flag(fault, step) or (
                                    bool(terminated[0].item())
                                    and after.position_world_m[2] <= spec.collision_height_m)
                                decision = evaluator.update(
                                    position_world_m=after.position_world_m,
                                    speed_mps=speed, now_s=elapsed, collision=collision)
                                if decision.terminated:
                                    outcome, reason = decision.outcome, decision.reason
                                    break
                                if bool(terminated[0].item()):
                                    outcome, reason = 'INVALID', 'ENV_TERMINATED_ALTITUDE'
                                    break
                            if outcome == 'RUNNING':
                                outcome, reason = 'INVALID', 'NO_TERMINAL_OBSERVED'
                            distance = math.sqrt(sum(
                                (scenario.goal_position_world_m[i] - last_position[i]) ** 2
                                for i in range(3)))
                            if decision is not None and math.isfinite(decision.distance_m):
                                distance = decision.distance_m
                            results.append(EpisodeResult(
                                episode_id='{}-{}-{}'.format(fault.kind, method_name,
                                                             scenario.scenario_id),
                                seed=scenario.seed, outcome=outcome, steps=steps,
                                duration_s=steps * dt, final_distance_m=distance,
                                peak_speed_mps=peak_speed, reason=reason,
                                method=method_name, scenario_id=scenario.scenario_id,
                                distance_bin=scenario.distance_bin,
                                bearing_bin=scenario.bearing_bin,
                                time_to_goal_s=(steps * dt if outcome == 'SUCCESS'
                                                else None)))
                            episode_records.append({
                                'run_kind': args.run_kind,
                                'fault': fault.kind,
                                'fault_effect_scope': effect_scope[fault.kind],
                                'expected_outcome': expected_outcome[fault.kind],
                                'method': method_name,
                                'scenario_id': scenario.scenario_id,
                                'seed': scenario.seed,
                                'outcome': outcome,
                                'reason': reason,
                                'steps': steps,
                                'duration_s': steps * dt,
                                'time_to_goal_s': (steps * dt if outcome == 'SUCCESS'
                                                   else None),
                                'final_distance_m': distance,
                                'peak_speed_mps': peak_speed,
                                'min_z_m': min_z,
                                'contact_observed': contact_observed,
                                'injected_observation_step': (fault.step if injected
                                                              else None),
                                'distance_bin': scenario.distance_bin,
                                'bearing_bin': scenario.bearing_bin,
                                'start_position_world_m': list(
                                    scenario.start_position_world_m),
                                'start_yaw_rad': scenario.start_yaw_rad,
                                'goal_position_world_m': list(
                                    scenario.goal_position_world_m),
                            })
            env._get_dones = original_dones
            fault_kinds_present = sorted({item.kind for item in faults})
            summary = {
                'schema_version': 'boom_birds.comparison.v1',
                'task': 'guidance_compare',
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
                'run_kind': args.run_kind,
                'methods': requested_methods,
                'scenarios': {
                    'manifest': str(args.scenario_manifest),
                    'content_sha256': scenario_manifest['content_sha256'],
                    'count': len(scenarios),
                    'spec': scenario_manifest['spec'],
                },
                'guidance_params': guidance_params,
                'thresholds': thresholds,
                'faults': fault_kinds_present,
                'total_episodes': len(results),
                'episodes_per_method': {name: sum(1 for item in results
                                                  if item.method == name)
                                        for name in requested_methods},
                'natural_performance_rates_excluded': any(
                    item != FAULT_NONE for item in fault_kinds_present),
                'proposed_not_frozen': False,
            }
            if fault_kinds_present == [FAULT_NONE]:
                summary['methods_summary'] = {
                    name: method_summary([item for item in results
                                          if item.method == name])
                    for name in requested_methods}
                summary['strata'] = {
                    stratum: {
                        name: stratified_summary(
                            [item for item in results if item.method == name], stratum)
                        for name in requested_methods}
                    for stratum in ('distance_bin', 'bearing_bin')}
                if len(requested_methods) == 2:
                    summary['paired'] = paired_comparison(
                        [item for item in results
                         if item.method == requested_methods[0]],
                        [item for item in results
                         if item.method == requested_methods[1]])
                    summary['pair_rows'] = [
                        {
                            'scenario_id': scenario.scenario_id,
                            'distance_bin': scenario.distance_bin,
                            'bearing_bin': scenario.bearing_bin,
                            **{'{}_{}'.format(name, key): value
                               for name in requested_methods
                               for key, value in next(
                                   (record for record in episode_records
                                    if record['scenario_id'] == scenario.scenario_id
                                    and record['method'] == name), {}).items()
                               if key in ('outcome', 'time_to_goal_s',
                                          'final_distance_m')},
                        }
                        for scenario in scenarios]
                summary['status'] = ('INCOMPLETE'
                                     if len(scenarios) * len(requested_methods) < 100
                                     else 'PASS')
                summary['sample_size_rule'] = (
                    'INCOMPLETE below the PROPOSED 100 valid-episode sample in V2.2 20.11')
            else:
                summary['fault_summary'] = fault_classification_summary(
                    episode_records,
                    expected_outcomes={kind: value
                                       for kind, value in expected_outcome.items()
                                       if kind in fault_kinds_present},
                    effect_scopes={kind: value
                                   for kind, value in effect_scope.items()
                                   if kind in fault_kinds_present})
                summary['status'] = ('PASS'
                                     if all(value['classification_ok']
                                            for value in summary['fault_summary'].values())
                                     else 'FAIL')
            out_dir = Path(args.output)
            out_dir.mkdir(parents=True, exist_ok=True)
            summary_path = out_dir / 'summary.json'
            episodes_path = out_dir / 'episodes.jsonl'
            summary_path.write_text(json.dumps(summary, indent=2) + '\n',
                                    encoding='utf-8')
            with episodes_path.open('w', encoding='utf-8') as handle:
                for record in episode_records:
                    handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            (out_dir / 'scenario_manifest.json').write_text(
                json.dumps(scenario_manifest, indent=2, ensure_ascii=False) + '\n',
                encoding='utf-8')
            manifest = {
                'schema_version': MANIFEST_SCHEMA_ID,
                'code_commit': args.code_commit,
                'working_tree': args.working_tree,
                'config_sha256': {
                    str(args.config): hashlib.sha256(
                        args.config.read_bytes()).hexdigest()},
                'asset_versions': {
                    'isaac_sim': '5.1.0.0 (host manifest)',
                    'task_source_sha256': hashlib.sha256(
                        Path(inspect.getfile(QuadcopterEnv)).read_bytes()).hexdigest(),
                    'asset_uri': str(getattr(cfg.robot.spawn, 'usd_path', None)),
                },
                'seeds': {'scenario_seeds': [item.seed for item in scenarios]},
                'command': ' '.join(sys.argv),
                'started_at': started_at,
                'exit_code': 0,
                'outputs_sha256': {
                    'summary.json': hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                    'episodes.jsonl': hashlib.sha256(episodes_path.read_bytes()).hexdigest(),
                },
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
                'scenario_sha256': scenario_manifest['content_sha256'],
            }
            write_manifest(out_dir, manifest)
            print('BOOM_BIRDS_GUIDANCE_COMPARE_' + summary['status'], flush=True)
            print(json.dumps({key: value for key, value in summary.items()
                              if key not in ('strata', 'pair_rows')}, indent=2),
                  flush=True)
            raise SystemExit(0 if summary['status'] != 'FAIL' else 1)

        if args.task == 'layered':
            mark('run layered evaluation')
            from collections import Counter
            from boom_birds.evaluation.comparison import layered_summary
            from boom_birds.evaluation.episodes import (
                EVALUATION_SCHEMA_ID_V2, MANIFEST_SCHEMA_ID, EpisodeResult,
                write_manifest)
            from boom_birds.sim.disturbance import DisturbanceSpec
            from boom_birds.sim.isaac_layered_scene import (
                DisturbanceInjector, LayeredScene)
            from boom_birds.sim.layered import (
                SCENE_CLASSES, layered_scenarios_from_manifest, load_layered_manifest)
            from boom_birds.sim.observation_interface import ObservationInterface
            from boom_birds.sim.reach import GuidanceSpec, ReachEvaluator, ReachSpec

            if args.scenario_manifest is None:
                raise RuntimeError('--scenario-manifest is required for --task layered')
            if layered_paths is None:
                raise RuntimeError('layered assets were not spawned')
            layered_manifest = load_layered_manifest(args.scenario_manifest)
            by_class = layered_scenarios_from_manifest(layered_manifest)
            if args.classes.strip() in ('all', ''):
                classes = list(SCENE_CLASSES)
            else:
                classes = [item.strip() for item in args.classes.split(',')
                           if item.strip()]
            for name in classes:
                if name not in SCENE_CLASSES:
                    raise RuntimeError('unknown scene class: ' + name)
            scenarios = []
            for name in classes:
                subset = list(by_class[name])
                if args.limit_per_class > 0:
                    subset = subset[:args.limit_per_class]
                scenarios.extend(subset)
            if not scenarios:
                raise RuntimeError('no layered scenarios selected')
            requested_methods = [item.strip() for item in args.methods.split(',')
                                 if item.strip()]
            from boom_birds.sim.guidance import METHODS, make_guidance
            for name in requested_methods:
                if name not in METHODS:
                    raise RuntimeError('unknown guidance method: ' + name)
            guidance_cfg = config.get('guidance', {})
            from boom_birds.sim.guidance import BrakingGuidanceSpec
            proportional_spec = GuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('proportional', {}).items()})
            braking_spec = BrakingGuidanceSpec(**{
                key: float(value)
                for key, value in guidance_cfg.get('braking', {}).items()})
            guidance_params = {
                'proportional': {key: float(value) for key, value in
                                 guidance_cfg.get('proportional', {}).items()},
                'braking': {key: float(value) for key, value in
                            guidance_cfg.get('braking', {}).items()},
            }
            threshold_spec = ReachSpec()
            thresholds = {
                'success_distance_m': float(threshold_spec.success_distance_m),
                'success_speed_mps': float(threshold_spec.success_speed_mps),
                'hold_time_s': float(threshold_spec.hold_time_s),
                'timeout_s': float(args.timeout_s),
                'collision_height_m': float(threshold_spec.collision_height_m),
                'max_abs_position_m': float(threshold_spec.max_abs_position_m),
                'contact_threshold_n': float(args.contact_threshold_n),
                'evaluation_version': EVALUATION_SCHEMA_ID_V2,
            }
            if args.freeze is not None:
                freeze = json.loads(args.freeze.read_text(encoding='utf-8'))
                if freeze.get('schema_version') != 'boom_birds.layered_freeze.v1':
                    raise RuntimeError('not a layered freeze file')
                if freeze.get('config_sha256') != hashlib.sha256(
                        args.config.read_bytes()).hexdigest():
                    raise RuntimeError('frozen config hash mismatch')
                if freeze.get('scenario_sha256') != layered_manifest['content_sha256']:
                    raise RuntimeError('frozen scenario hash mismatch')
                if freeze.get('guidance') != guidance_params:
                    raise RuntimeError('frozen guidance parameters mismatch')
                if freeze.get('thresholds') != thresholds:
                    raise RuntimeError('frozen thresholds mismatch')
                if freeze.get('evaluation_version') != EVALUATION_SCHEMA_ID_V2:
                    raise RuntimeError('frozen evaluation version mismatch')
                if freeze.get('class_counts') != {
                        name: len(by_class[name]) for name in SCENE_CLASSES}:
                    raise RuntimeError('frozen class counts mismatch')
                if freeze.get('min_valid_per_class') != args.min_valid_per_class \
                        or freeze.get('min_valid_total') != args.min_valid_total:
                    raise RuntimeError('frozen minimum sample settings mismatch')
                mark('layered freeze verified')

            mark('build layered scene')
            layered_scene = LayeredScene(
                env, contact_threshold_n=args.contact_threshold_n)
            injector = DisturbanceInjector(env)
            results = []
            episode_records = []
            step_records = []
            started_at = datetime.datetime.now().astimezone().isoformat()
            ttl_layered = float(controller_cfg['ttl_s'])
            max_steps = int(math.ceil(args.timeout_s / dt))
            with torch.inference_mode():
                for scenario in scenarios:
                    injector.begin(None)
                    env.reset(seed=scenario.seed)
                    layered_scene.reset_scenario(scenario)
                    start = scenario.start_position_world_m
                    yaw = scenario.start_yaw_rad
                    quat = (math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0))
                    pose = torch.tensor([[origin[0] + start[0], origin[1] + start[1],
                                          origin[2] + start[2], quat[0], quat[1],
                                          quat[2], quat[3]]],
                                        dtype=torch.float32, device=env.device)
                    env._robot.write_root_pose_to_sim(pose, index)
                    env._robot.write_root_velocity_to_sim(zero_velocity, index)
                    truth = read_state()
                    executor.reset(truth)
                    degradation = scenario.degradation
                    if degradation is None:
                        from boom_birds.sim.layered import DegradationSpec
                        degradation = DegradationSpec()
                    interface = ObservationInterface(degradation, dt,
                                                     seed=scenario.seed)
                    spec = ReachSpec(
                        goal_position_world_m=scenario.goal_position_world_m,
                        timeout_s=args.timeout_s)
                    evaluator = ReachEvaluator(spec, dt)
                    guidance = make_guidance(
                        'proportional', scenario.goal_position_world_m,
                        proportional_spec=proportional_spec,
                        braking_spec=braking_spec)
                    injector.begin(scenario.disturbance)
                    outcome, reason = 'RUNNING', 'RUNNING'
                    steps = 0
                    peak_speed = 0.0
                    decision = None
                    invalid_steps = 0
                    max_observation_age_s = 0.0
                    contact_seen = False
                    contact_step = None
                    max_contact_force_n = 0.0
                    min_z = truth.position_world_m[2]
                    last_position = truth.position_world_m
                    for step in range(max_steps):
                        elapsed = (step + 1) * dt
                        injector.tick(step * dt)
                        truth = read_state()
                        last_position = truth.position_world_m
                        observation = interface.observe(
                            position=truth.position_world_m,
                            velocity=truth.velocity_world_mps,
                            quat_wxyz=truth.quat_wxyz, step_index=step)
                        max_observation_age_s = max(max_observation_age_s,
                                                    observation.age_s)
                        if observation.valid:
                            command = guidance.command(
                                position_world_m=observation.position,
                                velocity_world_mps=observation.velocity,
                                quat_wxyz=observation.quat_wxyz)
                        else:
                            command = (0.0, 0.0, 0.0, 0.0)
                            invalid_steps += 1
                        setpoint = VelocitySetpoint(
                            *command, issued_at_s=step * dt,
                            expires_at_s=step * dt + ttl_layered, control_epoch=0)
                        control = executor.step(setpoint, truth, step * dt)
                        action = control.to_actuator_action(params)
                        _, _, terminated, _, _ = env.step(
                            torch.tensor([action], dtype=torch.float32,
                                         device=env.device))
                        layered_scene.update(scenario, elapsed)
                        after = read_state()
                        evidence = layered_scene.contact_evidence(
                            scenario, after.position_world_m, step=step)
                        last_position = after.position_world_m
                        speed = math.sqrt(sum(value * value
                                              for value in after.velocity_world_mps))
                        peak_speed = max(peak_speed, speed)
                        min_z = min(min_z, after.position_world_m[2])
                        env_terminated = bool(terminated[0].item())
                        if evidence.contact:
                            contact_seen = True
                            max_contact_force_n = max(max_contact_force_n,
                                                      evidence.force_n)
                            if contact_step is None:
                                contact_step = step
                        collision = evidence.contact or (
                            env_terminated
                            and after.position_world_m[2] <= spec.collision_height_m)
                        decision = evaluator.update(
                            position_world_m=after.position_world_m,
                            speed_mps=speed, now_s=elapsed, collision=collision)
                        steps = step + 1
                        step_records.append({
                            'scenario_id': scenario.scenario_id,
                            'scene_class': scenario.scene_class,
                            'seed': scenario.seed,
                            'method': 'proportional',
                            'step': step,
                            'time_s': round(elapsed, 4),
                            'position_world_m': list(after.position_world_m),
                            'velocity_world_mps': list(after.velocity_world_mps),
                            'yaw_rad': yaw_of(after),
                            'speed_mps': speed,
                            'quat_wxyz': list(after.quat_wxyz),
                            'angular_velocity_body_radps': list(
                                after.angular_velocity_body_radps),
                            'disturbance_force_body_n': list(injector.last_force),
                            'disturbance_torque_body_nm': list(injector.last_torque),
                            'observation_valid': observation.valid,
                            'observation_age_s': observation.age_s,
                            'observation_reason': observation.reason,
                            'command': list(command),
                            'contact_evidence': evidence.contact,
                            'contact_force_n': evidence.force_n,
                            'contacting_obstacles': list(evidence.contacting_obstacles),
                            'entity_poses': layered_scene.entity_states(),
                            'outcome': decision.outcome,
                            'reason': decision.reason,
                            'distance_m': decision.distance_m,
                        })
                        if decision.terminated:
                            outcome, reason = decision.outcome, decision.reason
                            break
                        if env_terminated:
                            outcome, reason = 'OUT_OF_BOUNDS', 'ENV_ALTITUDE_LIMIT'
                            break
                    if outcome == 'RUNNING':
                        outcome, reason = 'INVALID', 'NO_TERMINAL_OBSERVED'
                    distance = math.sqrt(sum(
                        (scenario.goal_position_world_m[i] - last_position[i]) ** 2
                        for i in range(3)))
                    if decision is not None and math.isfinite(decision.distance_m):
                        distance = decision.distance_m
                    results.append(EpisodeResult(
                        episode_id='proportional-' + scenario.scenario_id,
                        seed=scenario.seed, outcome=outcome, steps=steps,
                        duration_s=steps * dt, final_distance_m=distance,
                        peak_speed_mps=peak_speed, reason=reason,
                        schema_version=EVALUATION_SCHEMA_ID_V2,
                        method='proportional', scenario_id=scenario.scenario_id,
                        distance_bin=scenario.distance_bin,
                        bearing_bin=scenario.bearing_bin,
                        time_to_goal_s=(steps * dt if outcome == 'SUCCESS' else None),
                        scene_class=scenario.scene_class,
                        contact_evidence=contact_seen,
                        contact_force_n=max_contact_force_n,
                        degradation_invalid_steps=invalid_steps,
                        disturbance_applied=bool(injector.applied)))
                    episode_records.append({
                        'scenario_id': scenario.scenario_id,
                        'scene_class': scenario.scene_class,
                        'seed': scenario.seed,
                        'method': 'proportional',
                        'outcome': outcome,
                        'reason': reason,
                        'steps': steps,
                        'duration_s': steps * dt,
                        'time_to_goal_s': (steps * dt if outcome == 'SUCCESS' else None),
                        'final_distance_m': distance,
                        'peak_speed_mps': peak_speed,
                        'min_z_m': min_z,
                        'contact_evidence': contact_seen,
                        'contact_force_n': max_contact_force_n,
                        'contact_step': contact_step,
                        'degradation_invalid_steps': invalid_steps,
                        'max_observation_age_s': max_observation_age_s,
                        'disturbance_applied': bool(injector.applied),
                        'scenario': scenario.to_dict(),
                    })
            summary = layered_summary(
                results, expected_classes=classes,
                min_valid_per_class=args.min_valid_per_class)
            summary.update({
                'schema_version': 'boom_birds.layered_evaluation.v1',
                'evaluation_version': EVALUATION_SCHEMA_ID_V2,
                'task': 'layered_natural_evaluation',
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
                'gate': 'SIMULATION_EVALUATION_EXTENSION_ONLY_NOT_G4',
                'manifest_sha256': layered_manifest['content_sha256'],
                'guidance_params': guidance_params,
                'thresholds': thresholds,
                'classes_run': classes,
                'scenario_count': len(scenarios),
                'class_scenario_counts': {
                    name: sum(1 for item in scenarios if item.scene_class == name)
                    for name in classes},
                'min_valid_per_class': args.min_valid_per_class,
                'min_valid_total': args.min_valid_total,
                'scenario_family': 'layered_v2',
                'class_specs': layered_manifest['class_specs'],
                'quota': layered_manifest['quota'],
            })
            coverage_ok = (
                not summary['coverage']['classes_below_minimum']
                and summary['coverage']['total_valid_episodes'] >= args.min_valid_total)
            summary['coverage_ok'] = bool(coverage_ok)
            summary['status'] = ('PASS' if coverage_ok and args.require_coverage
                                 else ('DEBUG_INCOMPLETE' if not args.require_coverage
                                       else 'FAIL'))
            out_dir = Path(args.output)
            out_dir.mkdir(parents=True, exist_ok=True)
            episodes_path = out_dir / 'episodes.jsonl'
            steps_path = out_dir / 'steps.jsonl'
            summary_path = out_dir / 'summary.json'
            summary_path.write_text(json.dumps(summary, indent=2) + '\n',
                                    encoding='utf-8')
            with episodes_path.open('w', encoding='utf-8') as handle:
                for record in episode_records:
                    handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            with steps_path.open('w', encoding='utf-8') as handle:
                for record in step_records:
                    handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            (out_dir / 'scenario_manifest.json').write_text(
                json.dumps(layered_manifest, indent=2, ensure_ascii=False) + '\n',
                encoding='utf-8')
            manifest = {
                'schema_version': MANIFEST_SCHEMA_ID,
                'code_commit': args.code_commit,
                'working_tree': args.working_tree,
                'config_sha256': {
                    str(args.config): hashlib.sha256(
                        args.config.read_bytes()).hexdigest()},
                'asset_versions': {
                    'isaac_sim': '5.1.0.0 (host manifest)',
                    'task_source_sha256': hashlib.sha256(
                        Path(inspect.getfile(QuadcopterEnv)).read_bytes()).hexdigest(),
                    'asset_uri': str(getattr(cfg.robot.spawn, 'usd_path', None)),
                },
                'seeds': {'scenario_seeds': [item.seed for item in scenarios]},
                'command': ' '.join(sys.argv),
                'started_at': started_at,
                'exit_code': 0,
                'outputs_sha256': {
                    'summary.json': hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                    'episodes.jsonl': hashlib.sha256(episodes_path.read_bytes()).hexdigest(),
                    'steps.jsonl': hashlib.sha256(steps_path.read_bytes()).hexdigest(),
                },
                'evidence_domain': 'SIMULATION_MODEL_ORACLE_STATE',
                'scenario_sha256': layered_manifest['content_sha256'],
                'evaluation_version': EVALUATION_SCHEMA_ID_V2,
            }
            write_manifest(out_dir, manifest)
            print('BOOM_BIRDS_LAYERED_EVAL_' + summary['status'], flush=True)
            print(json.dumps({
                'status': summary['status'],
                'evaluation_version': EVALUATION_SCHEMA_ID_V2,
                'coverage': summary['coverage'],
                'class_metrics': {
                    name: {key: summary['classes'][name][key] for key in
                           ('total_episodes', 'valid_episodes', 'invalid_episodes',
                            'success', 'collision', 'timeout',
                            'success_rate_of_valid', 'mean_time_to_goal_s',
                            'collision_with_contact', 'collision_without_contact')}
                    for name in summary['classes']},
            }, indent=2), flush=True)
            raise SystemExit(0 if summary['status'] != 'FAIL' else 1)

        scenarios = [
            {'name': 'hover_trim', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.0), (0, 0, 0, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'forward_step', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.0), (0.5, 0, 0, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'left_step', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.0), (0, 0.4, 0, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'up_step', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.0), (0, 0, 0.2, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'yaw_step', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.0), (0, 0, 0, 0.5)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'combined_step', 'yaw_rad': 0.0,
             'phases': [((0.0, 1.5), (0.3, 0.2, 0.1, 0.2)), ((1.5, 2.0), (0, 0, 0, 0))]},
            {'name': 'heading_yaw90_forward', 'yaw_rad': math.pi / 2,
             'phases': [((0.0, 1.0), (0.5, 0, 0, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
            {'name': 'expiry_single_command', 'yaw_rad': 0.0, 'expiry': True,
             'phases': [((0.0, 2.0), (0.5, 0, 0, 0))]},
            {'name': 'reset_old_epoch', 'yaw_rad': 0.0, 'reset_at': 1.0,
             'phases': [((0.0, 1.0), (0.5, 0, 0, 0)), ((1.0, 2.0), (0.5, 0, 0, 0))]},
            {'name': 'kinematic_reference', 'yaw_rad': 0.0, 'kinematic': True,
             'phases': [((0.0, 1.0), (0.5, 0, 0, 0)), ((1.0, 2.0), (0, 0, 0, 0))]},
        ]
        selected = None if args.scenarios in ('all', '') else set(args.scenarios.split(','))
        if selected is not None:
            scenarios = [item for item in scenarios if item['name'] in selected]
        if not scenarios:
            parser.error('no scenarios selected')

        ttl_s = float(controller_cfg['ttl_s'])
        total_steps = int(round(2.0 / dt))
        rows = []
        summaries = []
        mark('run scenarios')
        with torch.inference_mode():
            for scenario in scenarios:
                env.reset(seed=args.seed)
                reset_pose(scenario['yaw_rad'])
                for _ in range(3):
                    env.step(torch.zeros((1, 4), device=env.device))
                state = read_state()
                executor.reset(state)
                executor.control_epoch = 0
                epoch = 0
                start_position = state.position_world_m
                start_yaw = yaw_of(state)
                scenario_rows = []
                expired_steps = 0
                rejected_epoch_steps = 0
                expiry_setpoint = None
                peak_speed = 0.0
                for step in range(total_steps):
                    now_s = step * dt
                    if 'reset_at' in scenario and now_s >= scenario['reset_at'] and epoch == 0:
                        env.reset(seed=args.seed)
                        reset_pose(scenario['yaw_rad'])
                        state = read_state()
                        executor.reset(state)
                        executor.control_epoch = 1
                        epoch = 1
                        start_position = state.position_world_m
                        start_yaw = yaw_of(state)
                        stale = VelocitySetpoint(0.5, 0.0, 0.0, 0.0,
                                                 issued_at_s=now_s,
                                                 expires_at_s=now_s + ttl_s,
                                                 control_epoch=0)
                        stale_output = executor.step(stale, state, now_s)
                        if stale_output.reason != 'REJECT_CONTROL_EPOCH':
                            raise RuntimeError('old epoch action was not rejected after reset')
                        rejected_epoch_steps += 1
                    command = (0.0, 0.0, 0.0, 0.0)
                    phase_name = 'none'
                    for (begin, end), values in scenario['phases']:
                        if begin <= now_s < end:
                            command = values
                            phase_name = '{:.1f}-{:.1f}'.format(begin, end)
                            break
                    state = read_state()
                    setpoint = None
                    if 'expiry' in scenario:
                        if expiry_setpoint is None:
                            expiry_setpoint = VelocitySetpoint(
                                *command, issued_at_s=now_s,
                                expires_at_s=now_s + ttl_s, control_epoch=epoch)
                        setpoint = expiry_setpoint
                    elif scenario.get('kinematic'):
                        setpoint = None
                    else:
                        setpoint = VelocitySetpoint(
                            *command, issued_at_s=now_s,
                            expires_at_s=now_s + ttl_s, control_epoch=epoch)
                    speed = math.sqrt(sum(value * value for value in state.velocity_world_mps))
                    peak_speed = max(peak_speed, speed)
                    if scenario.get('kinematic'):
                        c, s = math.cos(yaw_of(state)), math.sin(yaw_of(state))
                        target = torch.tensor([[
                            c * command[0] - s * command[1],
                            s * command[0] + c * command[1],
                            command[2], 0.0, 0.0, 0.0]],
                            dtype=torch.float32, device=env.device)
                        env._robot.write_root_velocity_to_sim(target, index)
                        env.step(torch.zeros((1, 4), device=env.device))
                        output = {'reason': 'KINEMATIC_REFERENCE', 'degraded': False,
                                  'thrust_body_n': 0.0,
                                  'torque_body_nm': (0.0, 0.0, 0.0),
                                  'action': (0.0, 0.0, 0.0, 0.0)}
                    else:
                        control = executor.step(setpoint, state, now_s)
                        action = control.to_actuator_action(params)
                        env.step(torch.tensor([action], dtype=torch.float32,
                                              device=env.device))
                        output = {'reason': control.reason,
                                  'degraded': control.degraded,
                                  'thrust_body_n': control.thrust_body_n,
                                  'torque_body_nm': control.torque_body_nm,
                                  'action': action}
                    if output['reason'] == 'ACTION_EXPIRED':
                        expired_steps += 1
                    if output['reason'] == 'REJECT_CONTROL_EPOCH':
                        rejected_epoch_steps += 1
                    after = read_state()
                    row = {
                        'scenario': scenario['name'], 'step': step,
                        'time_s': round(now_s, 4), 'phase': phase_name,
                        'reason': output['reason'], 'degraded': bool(output['degraded']),
                        'command_forward_left_up_yawrate': list(command),
                        'setpoint_issued_s': None if setpoint is None else setpoint.issued_at_s,
                        'setpoint_expires_s': None if setpoint is None else setpoint.expires_at_s,
                        'thrust_body_n': output['thrust_body_n'],
                        'torque_body_nm': list(output['torque_body_nm']),
                        'action': list(output['action']),
                        'position_world_m': list(after.position_world_m),
                        'velocity_world_mps': list(after.velocity_world_mps),
                        'quat_wxyz': list(after.quat_wxyz),
                        'yaw_rad': yaw_of(after),
                    }
                    for key, value in row.items():
                        if isinstance(value, float) and not math.isfinite(value):
                            raise RuntimeError('nonfinite ' + key + ' at '
                                               + scenario['name'] + ' step ' + str(step))
                    rows.append(row)
                    scenario_rows.append(row)
                final_state = read_state()
                delta = tuple(final_state.position_world_m[i] - start_position[i]
                              for i in range(3))
                final_yaw = yaw_of(final_state)
                summaries.append({
                    'scenario': scenario['name'],
                    'label': 'KINEMATIC' if scenario.get('kinematic') else 'DYNAMIC',
                    'delta_position_world_m': list(delta),
                    'delta_east_m': delta[0], 'delta_north_m': delta[1],
                    'delta_up_m': delta[2],
                    'yaw_change_rad': final_yaw - start_yaw,
                    'peak_speed_mps': peak_speed,
                    'final_velocity_world_mps': list(final_state.velocity_world_mps),
                    'expired_rejected_steps': expired_steps,
                    'rejected_old_epoch_steps': rejected_epoch_steps,
                    'rows': len(scenario_rows),
                    'no_basis_for_flight_acceptance': True,
                })

        mark('evaluate checks')
        by_name = {item['scenario']: item for item in summaries}
        checks = {}
        if 'forward_step' in by_name:
            item = by_name['forward_step']
            checks['forward_moves_east'] = (
                item['delta_east_m'] > 0.05
                and abs(item['delta_north_m']) < max(0.3, 0.5 * item['delta_east_m']))
        if 'left_step' in by_name:
            item = by_name['left_step']
            checks['left_moves_north'] = (
                item['delta_north_m'] > 0.05
                and abs(item['delta_east_m']) < max(0.3, 0.5 * item['delta_north_m']))
        if 'up_step' in by_name:
            checks['up_climbs'] = by_name['up_step']['delta_up_m'] > 0.02
        if 'yaw_step' in by_name:
            checks['positive_yaw_rate_is_ccw'] = \
                by_name['yaw_step']['yaw_change_rad'] > 0.2
        if 'combined_step' in by_name:
            item = by_name['combined_step']
            direction = math.atan2(item['delta_north_m'], item['delta_east_m'])
            checks['combined_direction_within_45deg_of_commanded'] = \
                abs(direction - math.atan2(0.2, 0.3)) < math.pi / 4
        if 'heading_yaw90_forward' in by_name:
            item = by_name['heading_yaw90_forward']
            checks['forward_at_yaw90_moves_north'] = (
                item['delta_north_m'] > 0.05 and abs(item['delta_east_m']) < 0.3)
        if 'expiry_single_command' in by_name:
            item = by_name['expiry_single_command']
            checks['expired_command_rejected_and_not_renewed'] = \
                item['expired_rejected_steps'] > 0
            checks['motion_stops_after_expiry'] = \
                abs(item['final_velocity_world_mps'][0]) < 0.2
        if 'reset_old_epoch' in by_name:
            checks['reset_old_action_rejected'] = \
                by_name['reset_old_epoch']['rejected_old_epoch_steps'] > 0
        if 'hover_trim' in by_name:
            checks['hover_holds_altitude'] = abs(by_name['hover_trim']['delta_up_m']) < 0.05
        finite_ok = True
        for row in rows:
            for value in (row['position_world_m'] + row['velocity_world_mps']
                          + row['quat_wxyz'] + [row['yaw_rad'], row['thrust_body_n']]):
                if not math.isfinite(value):
                    finite_ok = False
        checks['all_recorded_values_finite'] = finite_ok

        mark('write result')
        task_source = Path(inspect.getfile(QuadcopterEnv))
        result = {
            'scope': 'PROJECT_VELOCITY_OUTER_LOOP_TO_BODY_THRUST_MOMENT_IN_PHYSX',
            'evidence_domain': 'SIMULATION_MODEL',
            'status': 'PASS' if all(checks.values()) else 'FAIL',
            'gate': 'BB22:G4_PRECURSOR_ONLY_NOT_A_GATE_PASS',
            'flight_or_sitl_acceptance': False,
            'kinematic_reference_note': ('kinematic_reference rows are KINEMATIC and '
                                         'excluded from dynamics acceptance'),
            'proposed_not_frozen': True,
            'checks': checks,
            'task_source': str(task_source),
            'task_source_sha256': hashlib.sha256(task_source.read_bytes()).hexdigest(),
            'asset_uri': str(getattr(cfg.robot.spawn, 'usd_path', None)),
            'config': str(args.config),
            'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
            'seed': args.seed, 'num_envs': 1, 'step_dt_s': dt,
            'control_hz': round(1.0 / dt, 3),
            'action_semantics': 'normalized_total_thrust_plus_three_body_moments',
            'mass_kg': mass, 'inertia_kgm2': list(inertia),
            'thrust_to_weight': params.thrust_to_weight,
            'moment_scale_nm': params.moment_scale_nm,
            'max_tilt_rad': params.max_tilt_rad,
            'gains': {key: float(value) for key, value in gains_cfg.items()},
            'ttl_s': ttl_s,
            'scenarios': summaries,
            'row_count': len(rows),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            columns = ['scenario', 'step', 'time_s', 'phase', 'reason', 'degraded',
                       'command_forward_left_up_yawrate', 'setpoint_issued_s',
                       'setpoint_expires_s', 'thrust_body_n', 'torque_body_nm', 'action',
                       'position_world_m', 'velocity_world_mps', 'quat_wxyz', 'yaw_rad']
            with args.csv.open('w', encoding='utf-8') as handle:
                handle.write(','.join(columns) + '\n')
                for row in rows:
                    handle.write(','.join(json.dumps(row[column]) for column in columns) + '\n')
        print('BOOM_BIRDS_SIM_VELOCITY_CHAIN_' + result['status'], flush=True)
        print(json.dumps({'checks': checks, 'scenarios': summaries}, indent=2), flush=True)
        raise SystemExit(0 if result['status'] == 'PASS' else 1)
    finally:
        env.close()
except SystemExit:
    raise
except BaseException:
    error_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.write_text('stages: ' + json.dumps(STAGES) + '\n\n'
                          + traceback.format_exc(), encoding='utf-8')
    raise
finally:
    app.close()
