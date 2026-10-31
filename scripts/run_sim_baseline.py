"""Project velocity -> outer loop -> body thrust/moment -> PhysX response chain.

Evidence domain: SIMULATION MODEL. It does not prove PX4, SITL/HIL, real
actuator or flight behaviour. The KINEMATIC scenario writes velocity directly
and is a reference only; it is never used for dynamics or transfer acceptance.
"""
import argparse
import hashlib
import inspect
import json
import math
import sys
import traceback
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--task', default='velocity_step', choices=['velocity_step'])
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--scenarios', default='all')
parser.add_argument('--seed', type=int, default=0)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--csv', type=Path, default=None)
parser.add_argument('--clone-in-usd', action='store_true')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if args.task != 'velocity_step':
    parser.error('only the velocity_step task is implemented')
app = AppLauncher(args).app

STAGES = ['imports']
error_path = args.output.with_suffix('.error.txt')


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
