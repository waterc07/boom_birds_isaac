"""Braking and post-fault physical observation for the map v2 execution chain."""
import argparse, hashlib, json, math, sys, traceback
from datetime import datetime
from pathlib import Path

from isaaclab.app import AppLauncher
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--map-config', type=Path, default=Path('configs/maps/rmuc2027.yaml'))
parser.add_argument('--local-config', type=Path, default=Path('configs/maps/rmuc2027.local.yaml'))
parser.add_argument('--cases', type=Path, default=Path('configs/scenarios/brake_cases_v1.json'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--screenshots', action='store_true')
parser.add_argument('--only-cases', default='')
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--working-tree', default='recorded by operator')
parser.add_argument('--gpu-driver', default='NOT RECORDED')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
app = AppLauncher(args).app
STAGES = []
def mark(x):
    STAGES.append(x); print('[stage] ' + x, flush=True)
try:
    import torch, yaml
    import omni.usd, omni.physx
    import isaaclab.sim as sim_utils
    from isaaclab.sensors import ContactSensor, ContactSensorCfg
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import QuadcopterEnv, QuadcopterEnvCfg
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from boom_birds.evaluation.episode_boundary import EpisodeBoundary
    from boom_birds.sim.guidance import GuidanceSpec, make_guidance
    from boom_birds.sim.map_contract import load_map_contract
    from boom_birds.sim.v2_execution import V2ActionGate, V2ExecutionConfig
    from boom_birds.sim.velocity_control import (VehicleParams, VehicleState,
        VelocityExecutor, VelocityGains, VelocitySetpoint)
    mark('load cases')
    contract = load_map_contract(args.map_config, args.local_config)
    payload = json.loads(args.cases.read_text(encoding='utf-8'))
    cases = payload['brake_cases'] + payload['fault_cases']
    if args.only_cases:
        wanted = {item.strip() for item in args.only_cases.split(',') if item.strip()}
        cases = [item for item in cases if item['case_id'] in wanted]
    params_cfg = payload['parameters']
    config = yaml.safe_load(Path('configs/vehicles/sim_reference.yaml').read_text(encoding='utf-8'))
    gains = VelocityGains(**{k: float(v) for k, v in config['gains'].items()})
    vehicle_cfg = config['vehicle']; controller_cfg = config['controller']
    cfg = QuadcopterEnvCfg(); cfg.scene.num_envs = 1; cfg.sim.device = args.device
    cfg.seed = 0; cfg.debug_vis = False; cfg.decimation = 5; cfg.episode_length_s = 120
    cfg.robot.spawn.activate_contact_sensors = True
    mark('create env'); env = QuadcopterEnv(cfg); env.reset(seed=0); dt = env.step_dt
    origin = env.scene.env_origins[0].tolist(); mass = float(env._robot_mass.item())
    inertias = env._robot.root_physx_view.get_inertias(); raw = env._body_id[0]
    bid = int(raw.item()) if hasattr(raw, 'item') else int(raw)
    matrix = inertias[0, bid].tolist() if len(tuple(inertias.shape)) == 3 else inertias[0].tolist()
    gravity = math.sqrt(sum(v * v for v in cfg.sim.gravity))
    params = VehicleParams(mass_kg=mass, inertia_kgm2=(matrix[0], matrix[4], matrix[8]),
        thrust_to_weight=float(vehicle_cfg['thrust_to_weight']),
        moment_scale_nm=float(vehicle_cfg['moment_scale_nm']), gravity_mps2=gravity,
        max_tilt_rad=float(vehicle_cfg['max_tilt_rad']))
    executor = VelocityExecutor(params, gains, dt_s=dt, control_epoch=0)
    zero6 = torch.zeros((1, 6), device=env.device); index = torch.tensor([0], device=env.device)
    stage = omni.usd.get_context().get_stage()
    ground = stage.GetPrimAtPath(cfg.terrain.prim_path)
    if ground.IsValid(): ground.SetActive(False)
    map_cfg = sim_utils.UsdFileCfg(usd_path=str(contract.terrain_path)); map_cfg.func('/World/RMUC2027', map_cfg)
    for _ in range(10): app.update()
    try:
        from pxr import PhysxSchema, Usd, UsdPhysics
        for prim in Usd.PrimRange(stage.GetPrimAtPath('/World/RMUC2027')):
            if prim.HasAPI(UsdPhysics.CollisionAPI): PhysxSchema.PhysxContactReportAPI.Apply(prim)
    except Exception as e: print('[brake] reporters ' + repr(e), flush=True)
    query = omni.physx.get_physx_scene_query_interface()
    hit = query.raycast_closest((-10.0, 0.0, 10.0), (0.0, 0.0, -1.0), 30.0)
    ground_prim = str(hit.get('collision', '')) if hit.get('hit') else ''
    robot_root = '/World/envs/env_0/Robot'
    sensor = ContactSensor(ContactSensorCfg(prim_path=robot_root + '/body',
        filter_prim_paths_expr=[ground_prim], update_period=0.0, debug_vis=False))
    sensor._initialize_callback(None); sensor.update(dt=dt)
    def contact_force():
        try:
            sensor.update(dt=dt); m = sensor.data.force_matrix_w
            return 0.0 if m is None else float(m[0].abs().sum(dim=-1).max())
        except Exception: return 0.0
    def read_state():
        p = env._robot.data.root_pos_w[0].tolist(); v = env._robot.data.root_lin_vel_w[0].tolist()
        q = env._robot.data.root_quat_w[0].tolist(); w = env._robot.data.root_ang_vel_b[0].tolist()
        return VehicleState(tuple(p[i]-origin[i] for i in range(3)), tuple(v), tuple(q), tuple(w))
    def set_pose(pos, yaw):
        q = (math.cos(yaw/2), 0.0, 0.0, math.sin(yaw/2))
        pose = torch.tensor([[origin[0]+pos[0], origin[1]+pos[1], origin[2]+pos[2], *q]],
                            dtype=torch.float32, device=env.device)
        env._robot.write_root_pose_to_sim(pose, index)
        env._robot.write_root_velocity_to_sim(zero6, index)
    def capture(name):
        if not args.screenshots: return None
        try:
            from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file
            p = args.output / 'screenshots' / (name + '.png'); p.parent.mkdir(parents=True, exist_ok=True)
            capture_viewport_to_file(get_active_viewport(), str(p))
            for _ in range(60):
                app.update()
                if p.exists(): break
            return str(p) if p.exists() else None
        except Exception as e: print('[brake] screenshot ' + repr(e), flush=True); return None
    def body_command(world_direction, heading, speed):
        dx, dy = world_direction
        c, s = math.cos(heading), math.sin(heading)
        return (speed * (c*dx + s*dy), speed * (-s*dx + c*dy), 0.0, 0.0)
    def gyro(command, elapsed, step, gate, phase):
        now = int(round(elapsed * 1_000_000_000))
        obs = 'brake-' + str(step) + '-' + phase
        action = gate.build(command, now, step, obs, observation_time_ns=now)
        result = gate.admit(action, gate.context(), now)
        if not result.accepted:
            return None, result, action
        gate.mark_executed(action, now)
        setpoint = VelocitySetpoint(*command, issued_at_s=elapsed,
            expires_at_s=action.expires_at_monotonic_ns / 1e9, control_epoch=0)
        return setpoint, result, action
    boundary = EpisodeBoundary(env); results = []; records = []
    started = datetime.now().astimezone().isoformat()
    mark('run brake cases')
    with torch.inference_mode():
        for case in cases:
            case_id = case['case_id']; kind = case['kind']
            boundary.start(seed=9000)
            set_pose(case['start_position_world_m'], case.get('start_yaw_rad', 0.0))
            state = read_state(); executor.reset(state)
            gate = V2ActionGate(V2ExecutionConfig(ttl_ns=int(params_cfg['ttl_ms'])*1_000_000,
                max_age_ms=int(params_cfg['ttl_ms']), allowed_observation_age_ns=250_000_000))
            executor.control_epoch = gate.config.control_epoch
            last_setpoint = None; last_action = None; last_admission = ''; last_reject = ''
            brake_start = None; stop_hold = 0.0; fault_start = None; fault_done = False
            physical_outcome = 'RUNNING'; business_outcome = 'RUNNING'
            phase_name = 'ACCEL'; steps = 0; max_offset = 0.0
            fault_types = {'A': 'NO_NEW_ACTION', 'B': 'CACHE_RESEND',
                           'C': 'NEW_REJECTED_OLD_CACHE', 'D': 'OWNERSHIP_REVOKED'}
            max_steps = int(10.0 / dt)
            for step in range(max_steps):
                elapsed = (step + 1) * dt; state = read_state()
                speed = math.sqrt(sum(v*v for v in state.velocity_world_mps))
                command = None; setpoint = None
                if kind == 'brake':
                    if phase_name == 'ACCEL':
                        command = body_command(case['direction_world'], case['heading_rad'], case['speed_mps'])
                        setpoint, result, action = gyro(command, elapsed, step, gate, 'accel')
                        if setpoint is None:
                            business_outcome = 'ABORT'; last_reject = result.reason; break
                        last_setpoint, last_action = setpoint, action
                        last_admission = 'ADMITTED'; last_reject = ''
                        if abs(speed - case['speed_mps']) <= float(params_cfg['target_speed_tolerance']):
                            if brake_start is None:
                                brake_start = {'step': step, 'time_s': elapsed,
                                               'position': list(state.position_world_m),
                                               'speed_mps': speed,
                                               'velocity': list(state.velocity_world_mps)}
                            stop_hold = 0.0
                            phase_name = 'BRAKE'
                        elif elapsed > float(params_cfg['acceleration_timeout_s']):
                            business_outcome = 'ABORT'; physical_outcome = 'TARGET_UNREACHED'; break
                    else:
                        command = (0.0, 0.0, 0.0, 0.0)
                        setpoint, result, action = gyro(command, elapsed, step, gate, 'brake')
                        if setpoint is None:
                            business_outcome = 'ABORT'; last_reject = result.reason; break
                        last_setpoint, last_action = setpoint, action
                        last_admission = 'ADMITTED'; last_reject = ''
                        if speed <= float(params_cfg['stop_speed_mps']):
                            stop_hold += dt
                            if stop_hold >= float(params_cfg['stop_hold_s']):
                                business_outcome = 'SUCCESS'; physical_outcome = 'STOPPED'; break
                        else:
                            stop_hold = 0.0
                        if brake_start is not None:
                            max_offset = max(max_offset, math.dist(state.position_world_m, brake_start['position']))
                        if elapsed - brake_start['time_s'] > float(params_cfg['max_brake_time_s']):
                            business_outcome = 'ABORT'; physical_outcome = 'OBS_TIMEOUT'; break
                else:
                    if phase_name == 'ACCEL':
                        command = body_command(case['direction_world'], case['heading_rad'], case['target_speed_mps'])
                        setpoint, result, action = gyro(command, elapsed, step, gate, 'accel')
                        if setpoint is None:
                            business_outcome = 'ABORT'; last_reject = result.reason; break
                        last_setpoint, last_action = setpoint, action
                        last_admission = 'ADMITTED'; last_reject = ''
                        if abs(speed - case['target_speed_mps']) <= float(params_cfg['target_speed_tolerance']):
                            fault_start = {'step': step, 'time_s': elapsed,
                                           'position': list(state.position_world_m),
                                           'speed_mps': speed,
                                           'velocity': list(state.velocity_world_mps)}
                            business_outcome = 'ABORT'
                            phase_name = 'FAULT_OBSERVE'
                            fault_done = False
                            if case['fault_type'] == 'D':
                                gate.bump_context(control=True)
                                executor.control_epoch = gate.config.control_epoch
                        elif elapsed > float(params_cfg['acceleration_timeout_s']):
                            business_outcome = 'ABORT'; physical_outcome = 'TARGET_UNREACHED'; break
                    else:
                        if not fault_done:
                            if case['fault_type'] == 'B':
                                res = gate.send_cached(last_action, gate.context(),
                                                       int(round(elapsed*1_000_000_000)))
                                last_admission = 'ADMITTED' if res.accepted else 'REJECTED'
                                last_reject = '' if res.accepted else res.reason
                            elif case['fault_type'] == 'C':
                                bad = gate.build((0.0, 0.0, 0.0, 0.0), int(round(elapsed*1_000_000_000)),
                                    step, 'bad', header_overrides={'clock_id': 'px4_boot_clock'})
                                res = gate.admit(bad, gate.context(), int(round(elapsed*1_000_000_000)))
                                last_admission = 'REJECTED'; last_reject = res.reason
                                fault_done = True
                            elif case['fault_type'] == 'A':
                                last_admission = 'NO_NEW_ACTION'; last_reject = ''
                                fault_done = True
                            else:
                                last_admission = 'REVOKED'; last_reject = 'CONTROL_EPOCH'
                                fault_done = True
                        if last_setpoint is None:
                            physical_outcome = 'NO_SETPOINT'; break
                        setpoint = last_setpoint
                        if speed <= float(params_cfg['stop_speed_mps']):
                            stop_hold += dt
                            if stop_hold >= float(params_cfg['stop_hold_s']):
                                physical_outcome = 'STOPPED'; break
                        else:
                            stop_hold = 0.0
                        if fault_start is not None:
                            max_offset = max(max_offset, math.dist(state.position_world_m, fault_start['position']))
                        if elapsed - fault_start['time_s'] > float(params_cfg['max_fault_observation_s']):
                            physical_outcome = 'OBS_TIMEOUT'; break
                control = executor.step(setpoint, state, elapsed)
                act = control.to_actuator_action(params)
                _, _, term, trunc, _ = env.step(torch.tensor([act], dtype=torch.float32, device=env.device))
                bs = boundary.after_step(term[0].item(), trunc[0].item())
                after = read_state(); contact = contact_force(); steps = step + 1
                records.append({'episode_id': case_id, 'case_id': case_id, 'kind': kind,
                    'phase': phase_name, 'step': step, 'time_s': round(elapsed, 4),
                    'position_world_m': list(after.position_world_m),
                    'velocity_world_mps': list(after.velocity_world_mps),
                    'speed_mps': math.sqrt(sum(v*v for v in after.velocity_world_mps)),
                    'command': list(command) if command else None,
                    'setpoint_reason': control.reason, 'degraded': control.degraded,
                    'thrust_n': control.thrust_body_n, 'torque_nm': list(control.torque_body_nm),
                    'actuator_action': list(act),
                    'v2_admission': last_admission, 'v2_reject_reason': last_reject,
                    'v2_action_id': (last_action.action_id if last_action else ''),
                    'v2_issued_at_ns': (last_action.issued_at_monotonic_ns if last_action else 0),
                    'v2_expires_at_ns': (last_action.expires_at_monotonic_ns if last_action else 0),
                    'contact_force_n': contact, 'env_terminated': bs['terminated'],
                    'env_truncated': bs['truncated'], 'boundary_count_ok': bs['count_ok'],
                    'episode_length_buf': bs['episode_length_buf'],
                    'fault_type': case.get('fault_type')})
                if contact > 0.02:
                    physical_outcome = 'COLLISION'; break
                if bs['truncated'] or bs['unexpected_reset']:
                    physical_outcome = 'ENV_RESET'; break
                if not (-14 <= after.position_world_m[0] <= 14 and -8 <= after.position_world_m[1] <= 8):
                    physical_outcome = 'OUT_OF_BOUNDS'; break
                if kind == 'brake' and phase_name == 'BRAKE':
                    if not any(r['case_id'] == case_id and r['phase'] == 'BRAKE' for r in records[:-1]):
                        capture(case_id + '_brake_start')
                    if physical_outcome == 'STOPPED': capture(case_id + '_stopped')
            if business_outcome == 'RUNNING':
                business_outcome = 'ABORT'; physical_outcome = 'OBS_TIMEOUT'
            if kind == 'brake' and physical_outcome not in ('STOPPED', 'COLLISION',
                    'OUT_OF_BOUNDS', 'ENV_RESET', 'OBS_TIMEOUT'):
                physical_outcome = 'INCOMPLETE'
            results.append({'episode_id': case_id, 'kind': kind,
                'case_id': case_id, 'business_outcome': business_outcome,
                'physical_outcome': physical_outcome, 'steps': steps,
                'duration_s': steps * dt, 'speed_mps': case.get('speed_mps',
                    case.get('target_speed_mps')), 'heading_rad': case.get('heading_rad'),
                'direction_world': case.get('direction_world'),
                'fault_type': case.get('fault_type'), 'fault_label': case.get('fault_label'),
                'brake_start': brake_start, 'fault_start': fault_start,
                'max_offset_m': max_offset,
                'contact_max_force_n': max((r['contact_force_n'] for r in records
                                            if r['case_id'] == case_id), default=0.0),
                'start_position_world_m': case['start_position_world_m']})
            print('[episode] ' + case_id + ' ' + kind + ' ' + physical_outcome, flush=True)
        mark('write outputs')
        def stop_metrics(item):
            rows = [r for r in records if r['case_id'] == item['case_id']]
            if item['kind'] == 'brake' and item['brake_start']:
                start = item['brake_start']
                final = rows[-1]['position_world_m'] if rows else start['position']
                v = start['velocity']; norm = math.sqrt(sum(x*x for x in v))
                unit = [x/norm for x in v] if norm > 1e-9 else [0,0,0]
                delta = [final[i]-start['position'][i] for i in range(3)]
                along = sum(delta[i]*unit[i] for i in range(3))
                lateral = math.sqrt(max(0.0, sum(x*x for x in delta)-along*along))
                stop_time = rows[-1]['time_s']-start['time_s'] if rows else None
                return {'stop_distance_m': along, 'lateral_drift_m': lateral,
                        'stop_time_s': stop_time, 'initial_speed_mps': start['speed_mps'],
                        'final_speed_mps': rows[-1]['speed_mps'] if rows else None,
                        'max_offset_m': item['max_offset_m']}
            if item['kind'] == 'fault' and item['fault_start']:
                start = item['fault_start']; rows = [r for r in records if r['case_id'] == item['case_id']
                                                    and r['phase'] == 'FAULT_OBSERVE']
                final = rows[-1]['position_world_m'] if rows else start['position']
                v = start['velocity']; norm = math.sqrt(sum(x*x for x in v)); unit = [x/norm for x in v] if norm>1e-9 else [0,0,0]
                delta = [final[i]-start['position'][i] for i in range(3)]
                along = sum(delta[i]*unit[i] for i in range(3))
                lateral = math.sqrt(max(0.0, sum(x*x for x in delta)-along*along))
                return {'post_fault_distance_m': along, 'post_fault_lateral_m': lateral,
                        'post_fault_time_s': (rows[-1]['time_s']-start['time_s'] if rows else None),
                        'initial_speed_mps': start['speed_mps'],
                        'final_speed_mps': rows[-1]['speed_mps'] if rows else None,
                        'max_offset_m': item['max_offset_m']}
            return {}
        for item in results: item['metrics'] = stop_metrics(item)
        summary = {'schema_version': 'boom_birds.brake_eval.v1',
            'status': 'PASS' if not any(item['physical_outcome'] == 'INCOMPLETE' for item in results) else 'FAIL',
            'execution_path': 'v2', 'scope': 'CURRENT_SIM_MODEL_BRAKING_AND_POST_FAULT',
            'map': {'asset_id': contract.asset_id,
                    'terrain_sha256': contract.terrain_sha256,
                    'preview_sha256': contract.preview_sha256,
                    'map_config_sha256': hashlib.sha256(args.map_config.read_bytes()).hexdigest(),
                    'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest()},
            'counts': {'brake': sum(1 for x in results if x['kind']=='brake'),
                       'fault': sum(1 for x in results if x['kind']=='fault')},
            'gui_mode': not bool(getattr(args, 'headless', False)),
            'brake': [x for x in results if x['kind']=='brake'],
            'fault': [x for x in results if x['kind']=='fault']}
        (args.output/'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        with (args.output/'episodes.jsonl').open('w', encoding='utf-8') as f:
            for x in results: f.write(json.dumps(x, ensure_ascii=False)+'\n')
        with (args.output/'steps.jsonl').open('w', encoding='utf-8') as f:
            for x in records: f.write(json.dumps(x, ensure_ascii=False)+'\n')
        manifest = {'schema_version': 'boom_birds.manifest.v1', 'code_commit': args.code_commit,
            'working_tree': args.working_tree, 'gui_mode': summary['gui_mode'],
            'renderer': 'DirectX (--/app/vulkan=false)', 'gpu_driver': args.gpu_driver,
            'map_asset_id': contract.asset_id, 'terrain_sha256': contract.terrain_sha256,
            'preview_sha256': contract.preview_sha256,
            'map_config_sha256': summary['map']['map_config_sha256'],
            'cases_sha256': summary['map']['cases_sha256'], 'command': ' '.join(sys.argv),
            'started_at': started,
            'outputs_sha256': {name: hashlib.sha256((args.output/name).read_bytes()).hexdigest()
                               for name in ('summary.json','episodes.jsonl','steps.jsonl')}}
        (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        print('BRAKE_EVAL_' + summary['status'] + ' ' + json.dumps(summary['counts']), flush=True)
        raise SystemExit(0 if summary['status'] == 'PASS' else 1)
    env._get_dones = env._get_dones
    env.close()
except SystemExit:
    raise
except BaseException:
    (args.output/'summary.error.txt').write_text('stages: '+json.dumps(STAGES)+'\n\n'+traceback.format_exc(), encoding='utf-8')
    raise
finally:
    app.close()