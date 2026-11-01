"""Dynamic-obstacle stop-wait-resume paired evaluation (ORACLE, GUI)."""
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
parser.add_argument('--cases', type=Path,
                    default=Path('configs/scenarios/map_dynamic_cases_v1.json'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--methods', default='follow_only,supervisor')
parser.add_argument('--execution-path', default='v2', choices=('v1', 'v2'))
parser.add_argument('--only-cases', default='')
parser.add_argument('--limit-cases', type=int, default=0)
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


def mark(stage):
    STAGES.append(stage)
    print('[stage] ' + stage, flush=True)


try:
    import torch
    import omni.usd
    import omni.physx
    import isaaclab.sim as sim_utils
    from dataclasses import dataclass, field
    from isaaclab.assets import AssetBaseCfg, RigidObjectCfg
    from isaaclab.scene import InteractiveSceneCfg
    from isaaclab.sensors import ContactSensor, ContactSensorCfg
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import (
        QuadcopterEnv, QuadcopterEnvCfg)
    from isaacsim.core.prims import RigidPrim

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from boom_birds.evaluation.episode_boundary import EpisodeBoundary
    from boom_birds.evaluation.supervisor import RouteSupervisor, SupervisorConfig
    from boom_birds.evaluation.waypoints import WaypointConfig, WaypointRunner
    from boom_birds.sim.dynamic_obstacle import load_obstacle_spec
    from boom_birds.sim.guidance import GuidanceSpec, make_guidance
    from boom_birds.sim.map_contract import load_map_cases, load_map_contract
    from boom_birds.sim.v2_execution import V2ActionGate, V2ExecutionConfig
    from boom_birds.sim.velocity_control import (
        VehicleParams, VehicleState, VelocityExecutor, VelocityGains,
        VelocitySetpoint)

    mark('load contract and cases')
    contract = load_map_contract(args.map_config, args.local_config)
    cases = load_map_cases(args.cases, contract)
    if args.limit_cases > 0:
        cases = cases[:args.limit_cases]
    if args.only_cases:
        wanted = {item.strip() for item in args.only_cases.split(',') if item.strip()}
        cases = [case for case in cases if case.case_id in wanted]
    methods = [item.strip() for item in args.methods.split(',') if item.strip()]
    if not methods or any(item not in ('follow_only', 'supervisor') for item in methods):
        raise RuntimeError('methods must be follow_only and/or supervisor')
    case_sha = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    map_cfg_sha = hashlib.sha256(args.map_config.read_bytes()).hexdigest()

    if args.freeze is not None:
        freeze = json.loads(args.freeze.read_text(encoding='utf-8'))
        expected = {
            'map_asset_id': contract.asset_id,
            'terrain_sha256': contract.terrain_sha256,
            'preview_sha256': contract.preview_sha256,
            'map_config_sha256': map_cfg_sha,
            'cases_sha256': case_sha,
        }
        for key, value in expected.items():
            if freeze.get(key) != value:
                raise RuntimeError('freeze mismatch: ' + key)
        if freeze.get('methods') != methods:
            raise RuntimeError('freeze methods mismatch')
        mark('dynamic freeze verified')

    import yaml
    config = yaml.safe_load(Path('configs/vehicles/sim_reference.yaml')
                            .read_text(encoding='utf-8'))
    gains_cfg = config['gains']
    vehicle_cfg = config['vehicle']
    controller_cfg = config['controller']
    gains = VelocityGains(**{key: float(value) for key, value in gains_cfg.items()})
    proportional = GuidanceSpec(**{
        key: float(value) for key, value in
        config.get('guidance', {}).get('proportional', {}).items()})

    cfg = QuadcopterEnvCfg()
    cfg.sim.device = args.device
    cfg.seed = 0
    cfg.debug_vis = False
    cfg.decimation = 5
    cfg.episode_length_s = 120.0
    cfg.robot.spawn.activate_contact_sensors = True
    obstacle_specs = [load_obstacle_spec(case.obstacle) for case in cases]
    if not obstacle_specs:
        raise RuntimeError('no dynamic obstacle cases')
    obstacle_size = obstacle_specs[0].size_m

    @dataclass
    class DynamicSceneCfg(InteractiveSceneCfg):
        obstacle: RigidObjectCfg = field(default_factory=lambda: RigidObjectCfg(
            prim_path='{ENV_REGEX_NS}/Obstacle',
            spawn=sim_utils.CuboidCfg(
                size=obstacle_size,
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True, disable_gravity=True),
                mass_props=sim_utils.MassPropertiesCfg(mass=5.0),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                activate_contact_sensors=True)))

    cfg.scene = DynamicSceneCfg(num_envs=1, env_spacing=2.5,
                                replicate_physics=True, clone_in_fabric=False)
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
        matrix = (inertias[0, body_id].tolist() if len(shape) == 3
                  else inertias[0].tolist())
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
        stage = omni.usd.get_context().get_stage()

        mark('disable default ground and spawn map')
        ground = stage.GetPrimAtPath(cfg.terrain.prim_path)
        if ground.IsValid():
            ground.SetActive(False)
        map_path = '/World/RMUC2027'
        map_cfg = sim_utils.UsdFileCfg(usd_path=str(contract.terrain_path))
        map_cfg.func(map_path, map_cfg)
        for _ in range(10):
            app.update()
        try:
            from pxr import PhysxSchema, Usd, UsdPhysics
            for prim in Usd.PrimRange(stage.GetPrimAtPath(map_path)):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    PhysxSchema.PhysxContactReportAPI.Apply(prim)
        except Exception as error:
            print('[dynamic] map reporter warning: ' + repr(error), flush=True)

        mark('bind obstacle from scene')
        obstacle = env.scene['obstacle']
        dyn_path = '/World/envs/env_0/Obstacle'
        print('[dynamic] obstacle prim=' + dyn_path, flush=True)

        def set_obstacle_pose(position):
            pose = torch.tensor([[float(position[0]), float(position[1]),
                                  float(position[2]), 1.0, 0.0, 0.0, 0.0]],
                                dtype=torch.float32, device=env.device)
            obstacle.write_root_pose_to_sim(pose, torch.tensor([0], device=env.device))

        mark('create obstacle contact sensor')
        robot_root = '/World/envs/env_0/Robot'
        sensor_cfg = ContactSensorCfg(
            prim_path=robot_root + '/body',
            filter_prim_paths_expr=[dyn_path], update_period=0.0,
            debug_vis=False)
        sensor = ContactSensor(sensor_cfg)
        sensor._initialize_callback(None)
        sensor.update(dt=dt)

        def obstacle_contact():
            try:
                sensor.update(dt=dt)
                matrix = sensor.data.force_matrix_w
                if matrix is None:
                    return 0.0
                return float(matrix[0].abs().sum(dim=-1).max())
            except Exception:
                return 0.0

        mark('configure map dones')
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

        def set_robot_pose(position, yaw_rad):
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
                print('[dynamic] screenshot warning: ' + repr(error), flush=True)
                return None

        supervisor_config = SupervisorConfig()
        boundary = EpisodeBoundary(env)
        results = []
        records = []
        started_at = datetime.now().astimezone().isoformat()
        mark('run dynamic paired cases')
        with torch.inference_mode():
            for case in cases:
                obstacle_spec = load_obstacle_spec(case.obstacle)
                for method in methods:
                    boundary.start(seed=case.seed if hasattr(case, 'seed') else 9000)
                    set_robot_pose(case.start_position_world_m, case.start_yaw_rad)
                    set_obstacle_pose((0.0, 0.0, 50.0))
                    state = read_state()
                    executor.reset(state)
                    runner = WaypointRunner(
                        case.waypoints,
                        WaypointConfig(arrival_radius_m=0.25,
                                       arrival_speed_mps=0.2,
                                       intermediate_hold_s=0.2,
                                       final_hold_s=0.5,
                                       segment_timeout_s=60.0, dt_s=dt),
                        timeout_s=case.timeout_s)
                    supervisor = RouteSupervisor(supervisor_config)
                    v2_gate = (V2ActionGate(V2ExecutionConfig(
                        ttl_ns=150_000_000, max_age_ms=150,
                        allowed_observation_age_ns=250_000_000))
                        if args.execution_path == 'v2' else None)
                    outcome, reason = 'RUNNING', 'RUNNING'
                    v2_action_id = ''
                    v2_admission = ''
                    v2_reject_reason = ''
                    v2_executed = False
                    v2_issued_ns = 0
                    v2_expires_ns = 0
                    v2_observation_id = ''
                    v2_context_record = None
                    v2_owner = ''
                    v2_pending_owner = None
                    v2_action_source = ''
                    fault_recorded = None
                    route_active_s = 0.0
                    wait_total = 0.0
                    states = []
                    contact_max = 0.0
                    contact_prim = ''
                    obstacle_record = []
                    episode_id = case.case_id + '-' + method
                    steps = 0
                    max_steps = int(math.ceil(case.timeout_s / dt))
                    for step in range(max_steps):
                        elapsed = (step + 1) * dt
                        state = read_state()
                        obstacle_position, obstacle_velocity = obstacle_spec.pose_at(elapsed)
                        set_obstacle_pose(obstacle_position)
                        observation = obstacle_spec.observation_at(elapsed)
                        target = runner.waypoints[runner.index]
                        decision = supervisor.update(
                            state.position_world_m, target,
                            math.sqrt(sum(value * value
                                          for value in state.velocity_world_mps)),
                            observation, route_active_s, dt)
                        if method == 'supervisor':
                            states.append(decision['state'])
                            if decision['action'] == 'STOP':
                                command = (0.0, 0.0, 0.0, 0.0)
                            elif decision['action'] == 'ABORT':
                                outcome, reason = 'ABORT', decision.get(
                                    'abort_reason') or 'SUPERVISOR_ABORT'
                                records.append({
                                    'episode_id': episode_id, 'case_id': case.case_id,
                                    'method': method,
                                    'scenario_class': case.scenario_class,
                                    'step': step, 'time_s': round(elapsed, 4),
                                    'position_world_m': list(state.position_world_m),
                                    'velocity_world_mps': list(state.velocity_world_mps),
                                    'speed_mps': math.sqrt(sum(value * value
                                                               for value in state.velocity_world_mps)),
                                    'command': [0.0, 0.0, 0.0, 0.0],
                                    'obstacle_position_world_m': list(obstacle_position),
                                    'obstacle_velocity_world_mps': list(obstacle_velocity),
                                    'observation_valid': bool(observation.get('valid')),
                                    'observation_reason': observation.get('reason'),
                                    'observation_age_s': float(observation.get('age_s', 0.0)),
                                    'supervisor_state': decision['state'],
                                    'supervisor_action': decision['action'],
                                    'supervisor_wait_s': decision['wait_s'],
                                    'route_active_s': route_active_s,
                                    'contact_force_n': 0.0, 'contact_prim': '',
                                    'outcome': outcome, 'reason': reason,
                                    'env_terminated': False, 'env_truncated': False,
                                    'episode_length_buf': 0, 'boundary_count_ok': True,
                                })
                                break
                            else:
                                guidance = make_guidance(
                                    'proportional', target,
                                    proportional_spec=proportional,
                                    braking_spec=None)
                                command = guidance.command(
                                    position_world_m=state.position_world_m,
                                    velocity_world_mps=state.velocity_world_mps,
                                    quat_wxyz=state.quat_wxyz)
                        else:
                            guidance = make_guidance(
                                'proportional', target,
                                proportional_spec=proportional,
                                braking_spec=None)
                            command = guidance.command(
                                position_world_m=state.position_world_m,
                                velocity_world_mps=state.velocity_world_mps,
                                quat_wxyz=state.quat_wxyz)
                        if v2_gate is not None:
                            now_ns = int(round(elapsed * 1_000_000_000))
                            observation_id = 'state-' + episode_id + '-' + str(step)
                            action = v2_gate.build(
                                command, now_ns, step, observation_id,
                                observation_time_ns=now_ns)
                            context = v2_gate.context()
                            v2_observation_id = observation_id
                            v2_context_record = {'system_boot_id': context.system_boot_id,
                                                 'mission_epoch': context.mission_epoch,
                                                 'localization_epoch': context.localization_epoch,
                                                 'control_epoch': context.control_epoch,
                                                 'clock_id': context.clock_id,
                                                 'px4_boot_id': context.px4_boot_id,
                                                 'sync_generation': context.sync_generation}
                            v2_owner = context.control_owner
                            v2_pending_owner = context.pending_owner
                            v2_action_source = action.source
                            fault = case.fault
                            result = None
                            if fault is not None and step >= int(fault.get('step', 100)):
                                fault_type = fault.get('type')
                                if fault_type == 'ttl_expiry':
                                    fault_action = v2_gate.build(
                                        command, now_ns, step + 1,
                                        observation_id + '-short', ttl_ns=10)
                                    result = v2_gate.admit(fault_action, context, now_ns + 1000)
                                elif fault_type == 'cache_resend':
                                    first = v2_gate.admit(action, context, now_ns)
                                    result = v2_gate.send_cached(action, context,
                                                                 now_ns + 400_000_000)
                                elif fault_type == 'out_of_order':
                                    v2_gate.admit(action, context, now_ns)
                                    stale = v2_gate.build(
                                        command, now_ns, max(0, step - 1),
                                        observation_id + '-stale')
                                    result = v2_gate.admit(stale, context, now_ns)
                                elif fault_type == 'context_reset':
                                    v2_gate.bump_context(mission=True)
                                    result = v2_gate.admit(action, v2_gate.context(), now_ns)
                                elif fault_type == 'px4_boot_change':
                                    v2_gate.bump_context(px4_boot=True)
                                    result = v2_gate.admit(action, v2_gate.context(), now_ns)
                                elif fault_type == 'clock_sync_mismatch':
                                    bad = v2_gate.build(
                                        command, now_ns, step, observation_id + '-clock',
                                        header_overrides={'clock_id': 'px4_boot_clock'})
                                    result = v2_gate.admit(bad, context, now_ns)
                                elif fault_type == 'ownership_revoke':
                                    v2_gate.revoke_ownership(now_ns=now_ns)
                                    result = v2_gate.admit(action, v2_gate.context(), now_ns)
                                else:
                                    raise RuntimeError('unknown fault type: ' + str(fault_type))
                                if result is None or not result.accepted:
                                    v2_admission = 'REJECTED'
                                    v2_reject_reason = (result.reason if result is not None
                                                        else 'REJECTED')
                                    outcome, reason = 'ABORT', 'V2_' + v2_reject_reason
                                    records.append({
                                        'episode_id': episode_id, 'case_id': case.case_id,
                                        'method': method, 'scenario_class': case.scenario_class,
                                        'step': step, 'time_s': round(elapsed, 4),
                                        'position_world_m': list(state.position_world_m),
                                        'velocity_world_mps': list(state.velocity_world_mps),
                                        'speed_mps': math.sqrt(sum(value * value for value in state.velocity_world_mps)),
                                        'command': [0.0, 0.0, 0.0, 0.0],
                                        'obstacle_position_world_m': list(obstacle_position),
                                        'obstacle_velocity_world_mps': list(obstacle_velocity),
                                        'observation_valid': bool(observation.get('valid')),
                                        'observation_reason': observation.get('reason'),
                                        'observation_age_s': float(observation.get('age_s', 0.0)),
                                        'supervisor_state': decision['state'],
                                        'supervisor_action': decision['action'],
                                        'supervisor_wait_s': decision['wait_s'],
                                        'route_active_s': route_active_s,
                                        'contact_force_n': 0.0, 'contact_prim': '',
                                        'outcome': outcome, 'reason': reason,
                                        'env_terminated': False, 'env_truncated': False,
                                        'episode_length_buf': 0, 'boundary_count_ok': True,
                                        'execution_path': 'v2', 'v2_admission': 'REJECTED',
                                        'v2_reject_reason': v2_reject_reason,
                                        'v2_action_id': '', 'v2_executed': False,
                                        'v2_fault_type': fault.get('type'),
                                        'v2_observation_id': v2_observation_id,
                                        'v2_context': v2_context_record,
                                        'v2_context_owner': v2_owner,
                                        'v2_pending_owner': v2_pending_owner,
                                        'v2_action_source': v2_action_source,
                                        'v2_action_id': '',
                                    })
                                    fault_recorded = fault.get('type')
                                    break
                                else:
                                    v2_admission = 'ADMITTED'
                                    v2_action_id = action.action_id
                                    v2_issued_ns = action.issued_at_monotonic_ns
                                    v2_expires_ns = action.expires_at_monotonic_ns
                                    command = (action.payload.vx_forward_mps,
                                               action.payload.vy_left_mps,
                                               action.payload.vz_up_mps,
                                               action.payload.yaw_rate_ccw_world_radps)
                            else:
                                result = v2_gate.admit(action, context, now_ns)
                                if not result.accepted:
                                    v2_admission = 'REJECTED'
                                    v2_reject_reason = result.reason
                                    outcome, reason = 'ABORT', 'V2_' + result.reason
                                    break
                                v2_admission = 'ADMITTED'
                                v2_action_id = action.action_id
                                v2_issued_ns = action.issued_at_monotonic_ns
                                v2_expires_ns = action.expires_at_monotonic_ns
                                command = (action.payload.vx_forward_mps,
                                           action.payload.vy_left_mps,
                                           action.payload.vz_up_mps,
                                           action.payload.yaw_rate_ccw_world_radps)
                            v2_gate.mark_executed(action, now_ns)
                            v2_executed = True
                        setpoint_expires_s = ((v2_expires_ns / 1_000_000_000.0)
                                              if v2_gate is not None
                                              else step * dt + float(controller_cfg['ttl_s']))
                        setpoint = VelocitySetpoint(
                            *command, issued_at_s=step * dt,
                            expires_at_s=setpoint_expires_s,
                            control_epoch=0)
                        control = executor.step(setpoint, state, step * dt)
                        action = control.to_actuator_action(params)
                        _, _, terminated, truncated, _ = env.step(
                            torch.tensor([action], dtype=torch.float32,
                                         device=env.device))
                        boundary_state = boundary.after_step(
                            terminated[0].item(), truncated[0].item())
                        after = read_state()
                        contact = obstacle_contact()
                        if contact > 0.02:
                            contact_max = max(contact_max, contact)
                            if not contact_prim:
                                contact_prim = dyn_path
                        speed = math.sqrt(sum(value * value
                                              for value in after.velocity_world_mps))
                        if boundary_state['truncated']:
                            outcome, reason = 'INVALID', 'ENV_TRUNCATED'
                        elif boundary_state['unexpected_reset']:
                            outcome, reason = 'INVALID', 'ENV_UNEXPECTED_RESET'
                        elif contact > 0.02:
                            outcome, reason = 'COLLISION', 'OBSTACLE_CONTACT'
                        elif method == 'supervisor':
                            if decision['state'] in ('WAIT', 'BRAKE', 'HOLD',
                                                     'DEGRADED'):
                                wait_total += dt
                            if decision['state'] == 'ABORT':
                                outcome, reason = 'ABORT', decision.get(
                                    'abort_reason') or 'SUPERVISOR_ABORT'
                            else:
                                route_decision = runner.update(
                                    after.position_world_m, speed, route_active_s,
                                    contact=False)
                                if route_decision['outcome'] == 'SUCCESS':
                                    outcome, reason = 'SUCCESS', 'ROUTE_COMPLETE'
                                elif route_decision['outcome'] == 'TIMEOUT':
                                    outcome, reason = 'TIMEOUT', route_decision['reason']
                                if decision['action'] == 'ROUTE':
                                    route_active_s += dt
                        else:
                            route_decision = runner.update(
                                after.position_world_m, speed, elapsed,
                                contact=False)
                            if route_decision['outcome'] == 'SUCCESS':
                                outcome, reason = 'SUCCESS', 'ROUTE_COMPLETE'
                            elif route_decision['outcome'] == 'TIMEOUT':
                                outcome, reason = 'TIMEOUT', route_decision['reason']
                        if elapsed >= case.timeout_s and outcome == 'RUNNING':
                            outcome, reason = 'TIMEOUT', 'WALL_TIMEOUT'
                        steps = step + 1
                        records.append({
                            'episode_id': episode_id, 'case_id': case.case_id,
                            'method': method, 'scenario_class': case.scenario_class,
                            'step': step, 'time_s': round(elapsed, 4),
                            'position_world_m': list(after.position_world_m),
                            'velocity_world_mps': list(after.velocity_world_mps),
                            'speed_mps': speed,
                            'command': list(command),
                            'execution_path': args.execution_path,
                            'v2_admission': v2_admission,
                            'v2_action_id': v2_action_id,
                            'v2_reject_reason': v2_reject_reason,
                            'v2_executed': v2_executed,
                            'v2_issued_at_ns': v2_issued_ns,
                            'v2_expires_at_ns': v2_expires_ns,
                            'v2_fault_type': (case.fault.get('type') if case.fault else None),
                            'v2_observation_id': v2_observation_id,
                            'v2_context': v2_context_record,
                            'v2_context_owner': v2_owner,
                            'v2_pending_owner': v2_pending_owner,
                            'v2_action_source': v2_action_source,
                            'obstacle_position_world_m': list(obstacle_position),
                            'obstacle_velocity_world_mps': list(obstacle_velocity),
                            'observation_valid': bool(observation.get('valid')),
                            'observation_reason': observation.get('reason'),
                            'observation_age_s': float(observation.get('age_s', 0.0)),
                            'supervisor_state': decision['state'],
                            'supervisor_action': decision['action'],
                            'supervisor_wait_s': decision['wait_s'],
                            'route_active_s': route_active_s,
                            'contact_force_n': contact,
                            'contact_prim': contact_prim,
                            'outcome': outcome, 'reason': reason,
                            'env_terminated': boundary_state['terminated'],
                            'env_truncated': boundary_state['truncated'],
                            'episode_length_buf': boundary_state['episode_length_buf'],
                            'boundary_count_ok': boundary_state['count_ok'],
                        })
                        if outcome != 'RUNNING':
                            break
                    if outcome == 'RUNNING':
                        outcome, reason = 'TIMEOUT', 'WALL_TIMEOUT'
                    if outcome == 'SUCCESS' and method == 'supervisor':
                        capture(episode_id + '_success')
                    if contact_prim and method == 'supervisor':
                        capture(episode_id + '_contact')
                    results.append({
                        'episode_id': episode_id, 'case_id': case.case_id,
                        'method': method, 'scenario_class': case.scenario_class,
                        'route_id': case.route_id,
                        'outcome': outcome, 'reason': reason, 'steps': steps,
                        'duration_s': steps * dt, 'route_active_s': route_active_s,
                        'wait_total_s': wait_total,
                        'state_transitions': (len([1 for a, b in
                                                   zip(states, states[1:]) if a != b])
                                              if states else 0),
                        'states': sorted(set(states)),
                        'contact_max_force_n': contact_max,
                        'contact_prim': contact_prim,
                        'start_position_world_m': list(case.start_position_world_m),
                        'goal_position_world_m': list(case.goal_position_world_m),
                        'waypoints': [list(point) for point in case.waypoints],
                        'expected_behavior': case.expected_behavior,
                        'obstacle': case.obstacle,
                        'execution_path': args.execution_path,
                        'fault_type': (case.fault.get('type') if case.fault else None),
                        'v2_reject_reason': v2_reject_reason,
                        'v2_admitted_count': (len(v2_gate.accepted_actions)
                                              if v2_gate is not None else 0),
                        'v2_rejected_count': (len(v2_gate.rejections)
                                              if v2_gate is not None else 0),
                    })
                    print('[episode] ' + episode_id + ' ' + outcome + ' ' + reason,
                          flush=True)
        env._get_dones = original_dones
        mark('write outputs')
        summary = {
            'schema_version': 'boom_birds.dynamic_eval.v1',
            'status': 'PASS' if all(item['outcome'] != 'INVALID' for item in results)
            else 'FAIL',
            'scope': 'ORACLE_DYNAMIC_OBSTACLE_STOP_WAIT_RESUME',
            'execution_path': args.execution_path,
            'map': {
                'asset_id': contract.asset_id,
                'terrain_sha256': contract.terrain_sha256,
                'preview_sha256': contract.preview_sha256,
                'map_config_sha256': map_cfg_sha,
                'cases_sha256': case_sha,
            },
            'methods': methods,
            'case_count': len(cases),
            'counts': {method: sum(1 for item in results
                                   if item['method'] == method)
                       for method in methods},
            'outcomes': {
                method: {outcome: sum(1 for item in results
                                      if item['method'] == method
                                      and item['outcome'] == outcome)
                         for outcome in ('SUCCESS', 'COLLISION', 'TIMEOUT',
                                         'OUT_OF_BOUNDS', 'ABORT', 'INVALID')}
                for method in methods},
            'class_counts': {name: sum(1 for case in cases
                                       if case.scenario_class == name)
                             for name in ('A', 'B', 'C', 'D', 'E')},
            'episodes': results,
            'gui_mode': not bool(getattr(args, 'headless', False)),
        }
        (args.output / 'summary.json').write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        with (args.output / 'episodes.jsonl').open('w', encoding='utf-8') as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        with (args.output / 'steps.jsonl').open('w', encoding='utf-8') as handle:
            for item in records:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        manifest = {
            'schema_version': 'boom_birds.manifest.v1',
            'code_commit': args.code_commit,
            'working_tree': args.working_tree,
            'gui_mode': not bool(getattr(args, 'headless', False)),
            'renderer': 'DirectX (--/app/vulkan=false)',
            'gpu_driver': args.gpu_driver,
            'map_asset_id': contract.asset_id,
            'terrain_sha256': contract.terrain_sha256,
            'preview_sha256': contract.preview_sha256,
            'map_config_sha256': map_cfg_sha,
            'cases_sha256': case_sha,
            'methods': methods,
            'command': ' '.join(sys.argv),
            'started_at': started_at,
            'outputs_sha256': {
                name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                for name in ('summary.json', 'episodes.jsonl', 'steps.jsonl')},
        }
        (args.output / 'manifest.json').write_text(
            json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        print('DYNAMIC_EVAL_' + summary['status'] + ' ' + json.dumps(summary['outcomes']),
              flush=True)
        raise SystemExit(0 if summary['status'] == 'PASS' else 1)
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