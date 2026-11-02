"""Dynamic-obstacle stop-wait-resume paired evaluation (ORACLE, GUI).

Latency-envelope extension (2026-11-02): simulated camera clock domain + mapping
error bound, action arrival gate with TTL/context/ownership checks, actual
executed-setpoint records and post-abort physical observation.  The extension is
inactive for --action-delay-s 0 with zero clock parameters (legacy path), except
that the raw records carry the extra fields.
"""
import argparse
import hashlib
import json
import math
import sys
import traceback
from datetime import datetime, timezone
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
parser.add_argument('--obs-delay-s', type=float, default=0.0)
parser.add_argument('--action-delay-s', type=float, default=0.0)
parser.add_argument('--clock-offset-ms', type=float, default=0.0)
parser.add_argument('--clock-drift-ppm', type=float, default=0.0)
parser.add_argument('--clock-uncertainty-ms', type=float, default=0.0)
parser.add_argument('--sync-fail-step', type=int, default=-1)
parser.add_argument('--stop-distance-m', type=float, default=1.1)
parser.add_argument('--only-cases', default='')
parser.add_argument('--limit-cases', type=int, default=0)
parser.add_argument('--freeze', type=Path, default=None)
parser.add_argument('--code-commit', default='WORKTREE')
parser.add_argument('--working-tree', default='recorded by the operator')
parser.add_argument('--gpu-driver', default='NOT RECORDED')
parser.add_argument('--screenshots', action='store_true')
parser.add_argument('--vehicle-config', type=Path,
                    default=Path('configs/vehicles/sim_reference.yaml'))
parser.add_argument('--obstacle-time-clamp', action='store_true')
# Latency-envelope extension arguments (see docs/superpowers/plans/2026-11-02-latency-envelope.md).
parser.add_argument('--config-id', default='')
parser.add_argument('--segment-id', default='')
parser.add_argument('--ttl-ms', type=int, default=150)
parser.add_argument('--max-age-ms', type=int, default=150)
parser.add_argument('--allowed-observation-age-ms', type=int, default=250)
parser.add_argument('--post-abort-observe-s', type=float, default=0.0)
parser.add_argument('--obs-mapping-fail-step', type=int, default=-1)
parser.add_argument('--transport-stall-step', type=int, default=-1)
parser.add_argument('--transport-stall-delay-s', type=float, default=0.15)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if getattr(args, 'headless', False):
    raise RuntimeError('GUI runs are required; --headless is forbidden by the project rules')
args.output.mkdir(parents=True, exist_ok=True)
app = AppLauncher(args).app
STAGES = []


def mark(stage):
    STAGES.append(stage)
    print('[stage] ' + stage, flush=True)


def _iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat()


def _parse_iso(text):
    if not text:
        return None
    value = str(text)
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    return datetime.fromisoformat(value)


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
    from boom_birds.evaluation.action_transport import DelayedVelocityExecutor
    from boom_birds.evaluation.dual_clock import SimClock, SimMapping, mapping_age
    from boom_birds.evaluation.episode_boundary import EpisodeBoundary
    from boom_birds.evaluation.latency_plan import (
        LATENCY_EVAL_VERSION, LATENCY_FREEZE_SCHEMA, build_run_plan,
        check_freeze_lineage, validate_run_plan)
    from boom_birds.evaluation import boundary_plan
    from boom_birds.evaluation import clearance as clearance_mod
    from boom_birds.evaluation import stop_requirement as stop_req_mod
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
    if not cases:
        raise RuntimeError('no cases selected')
    case_sha = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    map_cfg_sha = hashlib.sha256(args.map_config.read_bytes()).hexdigest()
    vehicle_config_sha = hashlib.sha256(args.vehicle_config.read_bytes()).hexdigest()
    boundary_expected_path = Path(
        'configs/scenarios/clearance_boundary_expected_v1.json')
    brake_model_path = Path('configs/scenarios/brake_model_v1.json')
    boundary_expected_sha = (
        hashlib.sha256(boundary_expected_path.read_bytes()).hexdigest()
        if boundary_expected_path.exists() else '')
    brake_model_sha = (
        hashlib.sha256(brake_model_path.read_bytes()).hexdigest()
        if brake_model_path.exists() else '')
    brake_model = (stop_req_mod.load_brake_model(brake_model_path)
                   if brake_model_path.exists() else None)
    started_at = _iso_now()

    freeze_doc = None
    boundary_plan_doc = None
    freeze_meta = {'path': '', 'sha256': '', 'schema_version': '',
                   'frozen_at': '', 'code_commit': ''}

    def build_plan(role):
        return build_run_plan(
            role=role,
            segment_id=args.segment_id,
            config_id=args.config_id,
            cases_file=Path(args.cases).as_posix(),
            cases_sha256=case_sha,
            case_ids=[case.case_id for case in cases],
            methods=methods,
            execution_path=args.execution_path,
            obs_delay_s=args.obs_delay_s,
            action_delay_s=args.action_delay_s,
            ttl_ms=args.ttl_ms,
            max_age_ms=args.max_age_ms,
            allowed_observation_age_ms=args.allowed_observation_age_ms,
            stop_distance_m=args.stop_distance_m,
            post_abort_observe_s=args.post_abort_observe_s,
            clock_offset_ms=args.clock_offset_ms,
            clock_drift_ppm=args.clock_drift_ppm,
            clock_uncertainty_ms=args.clock_uncertainty_ms,
            sync_fail_step=args.sync_fail_step,
            obs_mapping_fail_step=args.obs_mapping_fail_step,
            transport_stall_step=args.transport_stall_step,
            transport_stall_delay_s=args.transport_stall_delay_s)

    if args.freeze is not None:
        freeze_bytes = Path(args.freeze).read_bytes()
        freeze_doc = json.loads(freeze_bytes)
        freeze_meta.update(
            path=Path(args.freeze).as_posix(),
            sha256=hashlib.sha256(freeze_bytes).hexdigest(),
            schema_version=str(freeze_doc.get('schema_version', '')),
            frozen_at=str(freeze_doc.get('frozen_at', '')),
            code_commit=str(freeze_doc.get('code_commit', '')))
        if freeze_doc.get('schema_version') == boundary_plan.CLEARANCE_BOUNDARY_FREEZE_SCHEMA:
            if not args.segment_id:
                raise RuntimeError('boundary freeze requires --segment-id')
            segment = freeze_doc.get('segments', {}).get(args.segment_id)
            if not isinstance(segment, dict):
                raise RuntimeError('segment missing in boundary freeze: '
                                   + str(args.segment_id))
            role = str(segment.get('role', ''))
            plan = boundary_plan.build_run_plan(
                segment_id=args.segment_id,
                role=role,
                vehicle_config=Path(args.vehicle_config).as_posix(),
                vehicle_config_sha256=vehicle_config_sha,
                cases_file=Path(args.cases).as_posix(),
                cases_sha256=case_sha,
                case_ids=[case.case_id for case in cases],
                methods=methods,
                execution_path=args.execution_path,
                obs_delay_s=args.obs_delay_s,
                action_delay_s=args.action_delay_s,
                ttl_ms=args.ttl_ms,
                max_age_ms=args.max_age_ms,
                allowed_observation_age_ms=args.allowed_observation_age_ms,
                stop_distance_m=args.stop_distance_m,
                post_abort_observe_s=args.post_abort_observe_s,
                clock_offset_ms=args.clock_offset_ms,
                clock_drift_ppm=args.clock_drift_ppm,
                clock_uncertainty_ms=args.clock_uncertainty_ms,
                sync_fail_step=args.sync_fail_step,
                obs_mapping_fail_step=args.obs_mapping_fail_step,
                transport_stall_step=args.transport_stall_step,
                transport_stall_delay_s=args.transport_stall_delay_s,
                expected_file=boundary_expected_path.as_posix(),
                expected_sha256=boundary_expected_sha,
                brake_model_sha256=brake_model_sha,
                clearance_schema_version=clearance_mod.CLEARANCE_SCHEMA_VERSION,
                stop_requirement_schema_version=(
                    stop_req_mod.STOP_REQUIREMENT_SCHEMA_VERSION))
            boundary_plan.validate_run_plan(freeze_doc, args.segment_id, plan)
            boundary_plan.check_freeze_lineage(freeze_doc, _iso_now(), Path.cwd())
            if args.code_commit not in ('WORKTREE',
                                        str(freeze_doc.get('code_commit'))):
                raise RuntimeError('--code-commit does not match the freeze commit')
            boundary_plan_doc = plan
            mark('boundary freeze verified')
        elif freeze_doc.get('schema_version') == LATENCY_FREEZE_SCHEMA:
            role = 'main' if args.config_id else ('special' if args.segment_id else '')
            if role not in ('main', 'special'):
                raise RuntimeError('latency freeze requires --config-id (main) or '
                                   '--segment-id (special)')
            plan = build_plan(role)
            validate_run_plan(freeze_doc, role=role, segment_id=args.segment_id,
                              config_id=args.config_id, run_plan=plan)
            check_freeze_lineage(freeze_doc, _iso_now(), Path.cwd())
            if args.code_commit not in ('WORKTREE', str(freeze_doc.get('code_commit'))):
                raise RuntimeError('--code-commit does not match the freeze commit')
            mark('latency freeze verified')
        else:
            expected = {
                'map_asset_id': contract.asset_id,
                'terrain_sha256': contract.terrain_sha256,
                'preview_sha256': contract.preview_sha256,
                'map_config_sha256': map_cfg_sha,
                'cases_sha256': case_sha,
            }
            for key, value in expected.items():
                if freeze_doc.get(key) != value:
                    raise RuntimeError('freeze mismatch: ' + key)
            if freeze_doc.get('methods') != methods:
                raise RuntimeError('freeze methods mismatch')
            frozen_at = _parse_iso(freeze_doc.get('frozen_at', ''))
            if frozen_at is not None and frozen_at > _parse_iso(_iso_now()):
                raise RuntimeError('freeze is in the future (not a pre-run freeze)')
            mark('dynamic freeze verified')

    import yaml
    config = yaml.safe_load(args.vehicle_config.read_text(encoding='utf-8'))
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
    obstacle_specs = [load_obstacle_spec(case.obstacle) for case in cases
                      if case.obstacle is not None]
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
        delay_wrapper = None
        if args.action_delay_s > 0:
            delay_wrapper = DelayedVelocityExecutor(executor, args.action_delay_s)
            executor = delay_wrapper
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

        mark('declare kinematic contact inference')
        robot_root = '/World/envs/env_0/Robot'
        sensors = []
        contact_sensor_info = {
            'valid': True, 'mode': 'sphere_overlap_inference',
            'force_sensor_available': False,
            'source': 'contact_force_sensor_not_reporting_in_this_environment',
            'reason': ('ContactSensor probes (robot/obstacle side, per-link, scene '
                       'and manual, with PhysxContactReportAPI applied) returned no '
                       'obstacle-robot force while physical pushing was observed; '
                       'contact is therefore inferred from conservative sphere '
                       'overlap, not measured force.'),
            'inference_rule': {'sphere_overlap_m_gt': 0.02,
                               'radii': 'robot half-diagonal + obstacle max(size)/2'},
            'prim_paths': [], 'filter': [], 'num_sensors': 0, 'errors': []}

        contact_stats = {'max_force_n': 0.0, 'max_net_n': 0.0, 'samples': 0}

        def obstacle_contact():
            # Force sensor unavailable (documented above); contact is inferred
            # from geometry in the per-step record instead.
            contact_stats['samples'] += 1
            return 0.0

        def measure_body_envelope():
            """Measured USD axis-aligned bounding box of the robot prim."""
            try:
                from pxr import Usd, UsdGeom
                prim = stage.GetPrimAtPath(robot_root)
                if not prim or not prim.IsValid():
                    return {'half_extents_m': None, 'source': 'UNAVAILABLE',
                            'measured_prim': robot_root}
                cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                          ['default', 'render'])
                bounds = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                size = bounds.GetSize()
                half = [abs(float(size[axis])) / 2.0 for axis in range(3)]
                return {'half_extents_m': half,
                        'source': 'measured_usd_aabb_at_runtime',
                        'measured_prim': robot_root}
            except Exception as error:
                print('[dynamic] body envelope warning: ' + repr(error), flush=True)
                return {'half_extents_m': None, 'source': 'UNAVAILABLE',
                        'measured_prim': robot_root}

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

        mark('measure body envelope')
        body_envelope = measure_body_envelope()
        print('[dynamic] body envelope=' + json.dumps(body_envelope), flush=True)

        clock_offset_ns = int(round(args.clock_offset_ms * 1_000_000))
        clock_uncertainty_ns = int(round(args.clock_uncertainty_ms * 1_000_000))
        camera_clock = SimClock('camera_sim', offset_ns=clock_offset_ns,
                                drift_ppm=args.clock_drift_ppm,
                                uncertainty_ns=clock_uncertainty_ns)
        obs_delay_ns = int(round(args.obs_delay_s * 1_000_000_000))

        def gate_epochs(gate):
            cfg_gate = gate.config
            return (cfg_gate.system_boot_id, cfg_gate.mission_epoch,
                    cfg_gate.localization_epoch, cfg_gate.control_epoch,
                    cfg_gate.px4_boot_id, cfg_gate.sync_generation)

        def transport_snapshot(admitted_action, now_ns):
            if delay_wrapper is None:
                executed = admitted_action is not None
                action_id = admitted_action.action_id if admitted_action is not None else ''
                issued = (admitted_action.issued_at_monotonic_ns
                          if admitted_action is not None else 0)
                expires = (admitted_action.expires_at_monotonic_ns
                           if admitted_action is not None else 0)
                return {
                    'status': 'DIRECT' if executed else 'NONE',
                    'action_id': action_id,
                    'executed_action_id': action_id if executed else '',
                    'issued_at_ns': int(issued),
                    'expires_at_ns': int(expires),
                    'scheduled_arrival_ns': int(now_ns),
                    'arrival_ns': int(now_ns),
                    'dispatch_delay_s': 0.0,
                    'arrival_age_s': 0.0,
                    'reason': 'ACCEPT' if executed else 'REJECT_NO_CACHED_ACTION',
                    'executed': executed,
                    'applied': None,
                    'rejections_this_step': [],
                }
            raw = getattr(delay_wrapper, 'last_transport', None) or {}
            return {
                'status': str(raw.get('status', 'NONE')),
                'action_id': str(raw.get('action_id', '') or ''),
                'executed_action_id': str(raw.get('executed_action_id', '') or ''),
                'issued_at_ns': int(round(float(raw.get('issued_at_s', 0.0)) * 1_000_000_000)),
                'expires_at_ns': int(round(float(raw.get('expires_at_s', 0.0)) * 1_000_000_000)),
                'scheduled_arrival_ns': int(round(
                    float(raw.get('scheduled_arrival_s', 0.0)) * 1_000_000_000)),
                'arrival_ns': int(round(float(raw.get('arrival_s', 0.0)) * 1_000_000_000)),
                'dispatch_delay_s': float(raw.get('dispatch_delay_s', 0.0)),
                'arrival_age_s': float(raw.get('arrival_age_s', 0.0)),
                'reason': str(raw.get('reason', '')),
                'executed': bool(raw.get('executed', False)),
                'applied': raw.get('applied'),
                'rejections_this_step': list(raw.get('rejections_this_step', []) or []),
            }

        def empty_transport(now_ns):
            return {
                'status': 'NONE', 'action_id': '', 'executed_action_id': '',
                'issued_at_ns': 0, 'expires_at_ns': 0,
                'scheduled_arrival_ns': int(now_ns), 'arrival_ns': int(now_ns),
                'dispatch_delay_s': 0.0, 'arrival_age_s': 0.0,
                'reason': 'REJECT_NO_CACHED_ACTION', 'executed': False,
                'applied': None, 'rejections_this_step': [],
            }

        def applied_snapshot(transport, command, admitted_action, now_ns,
                             expires_ns, issued_ns):
            applied = transport.get('applied')
            if applied is not None:
                return {
                    'vx_forward_mps': float(applied.get('vx_forward_mps', 0.0)),
                    'vy_left_mps': float(applied.get('vy_left_mps', 0.0)),
                    'vz_up_mps': float(applied.get('vz_up_mps', 0.0)),
                    'yaw_rate_ccw_world_radps': float(
                        applied.get('yaw_rate_ccw_world_radps', 0.0)),
                    'action_id': str(applied.get('action_id', '') or ''),
                    'issued_at_ns': int(applied.get('issued_at_ns', 0) or 0),
                    'expires_at_ns': int(applied.get('expires_at_ns', 0) or 0),
                    'age_s': float(applied.get('age_s', 0.0)),
                    'is_held': bool(applied.get('is_held', False)),
                }
            if delay_wrapper is None and admitted_action is not None:
                return {
                    'vx_forward_mps': float(command[0]),
                    'vy_left_mps': float(command[1]),
                    'vz_up_mps': float(command[2]),
                    'yaw_rate_ccw_world_radps': float(command[3]),
                    'action_id': str(admitted_action.action_id),
                    'issued_at_ns': int(issued_ns),
                    'expires_at_ns': int(expires_ns),
                    'age_s': 0.0,
                    'is_held': False,
                }
            return {
                'vx_forward_mps': 0.0, 'vy_left_mps': 0.0, 'vz_up_mps': 0.0,
                'yaw_rate_ccw_world_radps': 0.0, 'action_id': '',
                'issued_at_ns': 0, 'expires_at_ns': 0, 'age_s': 0.0,
                'is_held': False,
            }

        def clock_snapshot(now_ns, capture_host_ns, capture_clock_ns, mapping,
                           age_rec, header_capture_ns):
            return {
                'host_now_ns': int(now_ns),
                'capture_host_ns': int(capture_host_ns),
                'capture_clock_ns': int(capture_clock_ns),
                'camera_clock_id': camera_clock.clock_id,
                'mapping_host_ns': (None if age_rec.get('mapped_host_ns') is None
                                    else int(age_rec['mapped_host_ns'])),
                'mapping_error_ns': (None if age_rec.get('error_bound_ns') is None
                                     else int(age_rec['error_bound_ns'])),
                'mapping_sync_generation': int(mapping.sync_generation),
                'mapping_usable': bool(age_rec.get('valid')),
                'mapping_reason': str(age_rec.get('reason', '')),
                'age_point_s': (None if age_rec.get('age_point_s') is None
                                else float(age_rec['age_point_s'])),
                'age_bound_s': (None if age_rec.get('age_bound_s') is None
                                else float(age_rec['age_bound_s'])),
                'header_capture_host_ns': int(header_capture_ns),
            }

        body_half_extents = body_envelope.get('half_extents_m')
        robot_radius_conservative = (
            clearance_mod.box_conservative_sphere_radius(body_half_extents)
            if body_half_extents else None)
        robot_envelope_payload = {
            'half_extents_m': (None if body_half_extents is None
                               else [float(v) for v in body_half_extents]),
            'measured_prim': body_envelope.get('measured_prim'),
            'source': body_envelope.get('source')}

        def build_clearance_for(robot_position, target_world, observation,
                                waypoint_index, case_payload):
            size = tuple(float(v) for v in
                         ((case_payload.obstacle or {}).get('size_m',
                                                            (0.4, 0.4, 0.6))))
            obstacle_envelope = {'size_m': list(size),
                                 'source': 'case_obstacle_size'}
            valid = bool(observation.get('valid'))
            reasons = ([] if valid else
                       [str(observation.get('reason') or 'OBSERVATION_INVALID')])
            try:
                return clearance_mod.build_clearance_record(
                    robot_position, target_world, observation,
                    waypoint_index=waypoint_index,
                    robot_envelope=robot_envelope_payload,
                    obstacle_envelope=obstacle_envelope,
                    observation_valid=valid, validity_reasons=reasons)
            except Exception as error:
                return {
                    'schema_version': clearance_mod.CLEARANCE_SCHEMA_VERSION,
                    'algorithm': {
                        'id': clearance_mod.CLEARANCE_ALGORITHM_ID,
                        'version': clearance_mod.CLEARANCE_ALGORITHM_VERSION,
                        'units': clearance_mod.CLEARANCE_UNITS,
                        'frame': clearance_mod.CLEARANCE_FRAME,
                        'time_base': clearance_mod.CLEARANCE_TIME_BASE,
                        'prediction_horizon_s':
                            clearance_mod.PREDICTION_HORIZON_S,
                        'prediction_step_s': clearance_mod.PREDICTION_STEP_S},
                    'inputs': None, 'prediction': None, 'metrics': None,
                    'envelopes': {'robot': robot_envelope_payload,
                                  'obstacle': obstacle_envelope},
                    'validity': {'valid': False,
                                 'reasons': reasons + [
                                     'BUILD_ERROR:' + type(error).__name__]},
                    'applicability': {'status': 'UNSUPPORTED',
                                      'reasons': ['CLEARANCE_BUILD_ERROR'],
                                      'notes': []}}

        def build_stop_requirement_for(clearance_record, observation,
                                       robot_position, velocity, speed,
                                       ttl_remaining_s):
            envelopes = (clearance_record or {}).get('envelopes') or {}
            robot_radius = (envelopes.get('robot') or {}).get('radius_m')
            obstacle_radius = (envelopes.get('obstacle') or {}).get('radius_m')
            closing = None
            metrics = (clearance_record or {}).get('metrics') or {}
            center = metrics.get('center_distance_m')
            obs_pos = observation.get('position_world_m')
            obs_vel = observation.get('velocity_world_mps')
            if (observation.get('valid') and obs_pos is not None
                    and obs_vel is not None and center and center > 1e-9):
                relative = [obs_vel[i] - velocity[i] for i in range(3)]
                unit = [(obs_pos[i] - robot_position[i]) / center
                        for i in range(3)]
                closing = max(0.0, -sum(relative[i] * unit[i]
                                        for i in range(3)))
            try:
                return stop_req_mod.evaluate_stop_requirement(
                    robot_speed_mps=speed,
                    closing_speed_mps=closing,
                    observation_age_bound_s=(float(observation['age_s'])
                                             if observation.get('valid') else None),
                    action_delay_s=args.action_delay_s,
                    action_ttl_remaining_s=ttl_remaining_s,
                    robot_radius_m=robot_radius,
                    obstacle_radius_m=obstacle_radius,
                    stop_threshold_m=args.stop_distance_m,
                    proposed_margin_m=0.2,
                    brake_model=brake_model,
                    observation_valid=bool(observation.get('valid')),
                    basis='actuation',
                    prediction_horizon_s=1.0)
            except Exception as error:
                return {
                    'schema_version':
                        stop_req_mod.STOP_REQUIREMENT_SCHEMA_VERSION,
                    'model_id': 'brake_final4.v1', 'basis': 'actuation',
                    'inputs': None, 'terms': None,
                    'required_clearance_m': None, 'margin_to_threshold_m': None,
                    'status': 'UNSUPPORTED',
                    'status_reasons': ['EVALUATION_ERROR:'
                                       + type(error).__name__]}

        inference_overlap_m = 0.02

        def contact_evidence_for(robot_position, obstacle_position,
                                 clearance_record, applied, speed_value,
                                 time_value):
            envelopes = (clearance_record or {}).get('envelopes') or {}
            robot_radius = (envelopes.get('robot') or {}).get('radius_m')
            obstacle_radius = (envelopes.get('obstacle') or {}).get('radius_m')
            center = (math.sqrt(sum((float(robot_position[i])
                                     - float(obstacle_position[i])) ** 2
                                    for i in range(3)))
                      if obstacle_position is not None else None)
            radii_sum = ((robot_radius or 0.0) + (obstacle_radius or 0.0))
            overlap = (None if center is None else
                       max(0.0, radii_sum - center))
            applied = applied or {}
            command_zero = all(abs(float(applied.get(name) or 0.0)) <= 1e-9
                               for name in ('vx_forward_mps', 'vy_left_mps',
                                            'vz_up_mps',
                                            'yaw_rate_ccw_world_radps'))
            return {
                'force_sensor_available': False,
                'sensor_force_n': 0.0,
                'center_distance_m': center,
                'radii_sum_m': radii_sum,
                'sphere_overlap_m': overlap,
                'sphere_overlap_threshold_m': inference_overlap_m,
                'inferred_contact': bool(overlap is not None
                                         and overlap > inference_overlap_m),
                'inferred_contact_time_s': (
                    float(time_value) if overlap is not None
                    and overlap > inference_overlap_m else None),
                'command_all_zero': bool(command_zero),
                'robot_speed_mps': float(speed_value),
                'evidence_mode': 'sphere_overlap_inference',
            }

        def _dist(a, b):
            return math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))

        def compute_episode_metrics(rows, case):
            body_half = body_envelope.get('half_extents_m')
            body_radius = (clearance_mod.box_conservative_sphere_radius(body_half)
                           if body_half else 0.0)
            obstacle_payload = case.obstacle or {}
            obstacle_size_m = tuple(float(value) for value in
                                    obstacle_payload.get('size_m', (0.0, 0.0, 0.0)))
            obstacle_half = [value / 2.0 for value in obstacle_size_m]
            obstacle_radius = max(obstacle_half) if obstacle_half else 0.0
            run_rows = [row for row in rows if row.get('phase', 'RUN') == 'RUN']
            brake_start = None
            brake_index = None
            for position, row in enumerate(run_rows):
                if row.get('supervisor_action') == 'STOP':
                    brake_start = {
                        'step': int(row.get('step', 0)),
                        'time_s': float(row.get('time_s', 0.0)),
                        'position_world_m': list(row['position_world_m']),
                        'velocity_world_mps': list(row['velocity_world_mps']),
                        'speed_mps': float(row.get('speed_mps', 0.0)),
                        'supervisor_state': row.get('supervisor_state'),
                        'observation_age_s': float(row.get('observation_age_s', 0.0)),
                    }
                    brake_index = position
                    break
            stop_window = max(1, int(math.ceil(0.5 / dt)))
            stop_distance = None
            stop_time = None
            stop_speed = None
            final_speed = (float(rows[-1].get('speed_mps', 0.0)) if rows else 0.0)
            if brake_start is not None:
                tail = rows[brake_index:] if brake_index is not None else rows
                speeds = [float(row.get('speed_mps', 0.0)) for row in tail]
                stop_row = None
                for position in range(0, len(tail)):
                    window = speeds[position:position + stop_window]
                    if len(window) < stop_window:
                        break
                    if all(value <= 0.08 for value in window):
                        stop_row = tail[min(len(tail) - 1, position + stop_window - 1)]
                        break
                if stop_row is None and tail:
                    stop_row = tail[-1]
                if stop_row is not None:
                    delta = [stop_row['position_world_m'][axis]
                             - brake_start['position_world_m'][axis]
                             for axis in range(3)]
                    start_speed = float(brake_start['speed_mps'])
                    if start_speed > 1e-9:
                        unit = [value / start_speed for value in
                                brake_start['velocity_world_mps']]
                        along = sum(delta[axis] * unit[axis] for axis in range(3))
                        lateral = math.sqrt(max(0.0, sum(value * value for value in delta)
                                                - along * along))
                    else:
                        along = math.sqrt(sum(value * value for value in delta))
                        lateral = 0.0
                    stop_distance = along
                    stop_time = float(stop_row.get('time_s', 0.0)) - float(
                        brake_start['time_s'])
                    stop_speed = float(stop_row.get('speed_mps', 0.0))
                    stop_definition = ('ALONG_INITIAL_VELOCITY_TO_STABLE_SPEED_LE_0.08'
                                       '_FOR_0.5S')
                else:
                    stop_definition = 'NO_STOP_ROW'
            else:
                stop_definition = 'NO_STOP_COMMAND'
            min_distance = None
            min_distance_time = None
            min_gap = None
            max_rel = 0.0
            max_closing = 0.0
            previous = None
            contact_max = 0.0
            contact_prim = ''
            for row in rows:
                obstacle_position = row.get('obstacle_position_world_m')
                if obstacle_position is None:
                    continue
                distance = _dist(row['position_world_m'], obstacle_position)
                if min_distance is None or distance < min_distance:
                    min_distance = distance
                    min_distance_time = float(row.get('time_s', 0.0))
                gap = distance - body_radius - obstacle_radius
                if min_gap is None or gap < min_gap:
                    min_gap = gap
                velocity = row.get('velocity_world_mps')
                obstacle_velocity = row.get('obstacle_velocity_world_mps')
                if velocity is not None and obstacle_velocity is not None:
                    relative = [obstacle_velocity[axis] - velocity[axis]
                                for axis in range(3)]
                    max_rel = max(max_rel, math.sqrt(sum(v * v for v in relative)))
                if previous is not None:
                    delta_t = float(row.get('time_s', 0.0)) - previous[1]
                    if delta_t > 1e-9:
                        closing = (previous[0] - distance) / delta_t
                        max_closing = max(max_closing, closing)
                previous = (distance, float(row.get('time_s', 0.0)))
                contact = float(row.get('contact_force_n', 0.0) or 0.0)
                if contact > contact_max:
                    contact_max = contact
                if row.get('contact_prim'):
                    contact_prim = row['contact_prim']
            executed_ids = []
            rejected_rows = []
            for row in rows:
                transport = row.get('transport') or {}
                executed_id = transport.get('executed_action_id')
                if transport.get('executed') and executed_id and executed_id not in executed_ids:
                    executed_ids.append(executed_id)
                if transport.get('status') == 'REJECTED':
                    rejected_rows.append(transport.get('reason', ''))
            reject_reasons = {}
            for reason in rejected_rows:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
            post_rows = [row for row in rows if row.get('phase') == 'POST_ABORT']
            post_abort = None
            if post_rows:
                anchor = post_rows[0]
                residual = _dist(post_rows[-1]['position_world_m'],
                                 anchor['position_world_m'])
                post_stop = None
                post_speeds = [float(row.get('speed_mps', 0.0)) for row in post_rows]
                window = max(1, int(math.ceil(0.5 / dt)))
                for position in range(0, len(post_rows)):
                    segment = post_speeds[position:position + window]
                    if len(segment) < window:
                        break
                    if all(value <= 0.08 for value in segment):
                        post_stop = (float(post_rows[position + window - 1]['time_s'])
                                     - float(anchor.get('time_s', 0.0)))
                        break
                post_abort = {
                    'steps': len(post_rows),
                    'residual_distance_m': residual,
                    'time_to_stop_s': post_stop,
                    'contact_max_force_n': max(
                        [float(row.get('contact_force_n', 0.0) or 0.0)
                         for row in post_rows] or [0.0]),
                }
            clearance_min = None
            clearance_gap_min = None
            sr_margins = []
            sr_unsupported = 0
            sr_unsupported_reasons = {}
            sr_max_speed = 0.0
            for row in rows:
                clearance_row = row.get('clearance') or {}
                metrics_row = clearance_row.get('metrics') or {}
                path_clearance = metrics_row.get('path_clearance_m')
                path_gap = metrics_row.get('path_clearance_gap_sphere_m')
                if path_clearance is not None and (
                        clearance_min is None or path_clearance < clearance_min):
                    clearance_min = path_clearance
                if path_gap is not None and (
                        clearance_gap_min is None or path_gap < clearance_gap_min):
                    clearance_gap_min = path_gap
                requirement = row.get('stop_requirement') or {}
                margin = requirement.get('margin_to_threshold_m')
                if margin is not None:
                    sr_margins.append(float(margin))
                if requirement.get('status') == 'UNSUPPORTED':
                    sr_unsupported += 1
                    for reason in requirement.get('status_reasons') or []:
                        sr_unsupported_reasons[reason] = (
                            sr_unsupported_reasons.get(reason, 0) + 1)
                sr_max_speed = max(sr_max_speed, float(row.get('speed_mps', 0.0)))
            inferred_rows = []
            max_overlap = 0.0
            for row in rows:
                evidence = row.get('contact_evidence') or {}
                overlap = evidence.get('sphere_overlap_m')
                if overlap is not None:
                    max_overlap = max(max_overlap, float(overlap))
                if evidence.get('inferred_contact'):
                    inferred_rows.append(float(row.get('time_s', 0.0)))
            contact_evidence_summary = {
                'max_sensor_force_n': contact_max,
                'max_sphere_overlap_m': max_overlap,
                'inferred_contact': bool(inferred_rows),
                'first_inferred_contact_time_s': (inferred_rows[0]
                                                  if inferred_rows else None),
                'radii_sum_m': body_radius + obstacle_radius,
            }
            conservative_envelope = {
                'robot_radius_m': body_radius,
                'robot_aabb_half_extents_m': (None if body_half is None
                                              else [float(v) for v in body_half]),
                'robot_radius_rule': 'half_diagonal_of_measured_aabb',
                'robot_source': body_envelope.get('source'),
                'robot_measured_prim': body_envelope.get('measured_prim'),
                'robot_attitude_scope': 'any_rigid_rotation_about_center',
                'obstacle_radius_m': obstacle_radius,
                'obstacle_size_m': [float(v) for v in obstacle_size_m],
                'obstacle_source': 'case_obstacle_size',
                'limitation': ('sphere/AABB approximation; not a triangle-mesh '
                               'sweep and not a real-aircraft envelope'),
            }
            return {
                'brake_start': brake_start,
                'initial_speed_mps': (None if brake_start is None
                                      else brake_start['speed_mps']),
                'stop_distance_m': stop_distance,
                'stop_time_s': stop_time,
                'stop_speed_mps': stop_speed,
                'stop_definition': stop_definition,
                'final_speed_mps': final_speed,
                'min_center_distance_m': min_distance,
                'min_center_distance_time_s': min_distance_time,
                'min_envelope_gap_m': min_gap,
                'min_envelope_gap_sphere_m': min_gap,
                'min_path_clearance_m': clearance_min,
                'min_path_clearance_gap_sphere_m': clearance_gap_min,
                'conservative_envelope': conservative_envelope,
                'stop_requirement_extremes': {
                    'min_margin_m': (min(sr_margins) if sr_margins else None),
                    'unsupported_steps': sr_unsupported,
                    'unsupported_reasons': sr_unsupported_reasons,
                    'max_robot_speed_mps': sr_max_speed,
                },
                'envelope': {
                    'body_half_extents_m': (None if body_half is None
                                            else [float(v) for v in body_half]),
                    'obstacle_half_extents_m': [float(v) for v in obstacle_half],
                    'body_radius_m': body_radius,
                    'obstacle_radius_m': obstacle_radius,
                    'body_source': body_envelope.get('source'),
                },
                'max_closing_speed_mps': max_closing,
                'max_relative_speed_mps': max_rel,
                'contact_max_force_n': contact_max,
                'contact_prim': contact_prim,
                'contact_evidence_summary': contact_evidence_summary,
                'executed_action_count': len(executed_ids),
                'executed_action_ids': executed_ids,
                'arrival_rejection_count': len(rejected_rows),
                'arrival_reject_reasons': reject_reasons,
                'post_abort': post_abort,
            }

        def obstacle_observation_fields(observation):
            return {
                'observation_valid': bool(observation.get('valid')),
                'observation_reason': observation.get('reason'),
                'observation_age_s': float(observation.get('age_s', 0.0)),
                'observation_age_point_s': float(
                    observation.get('age_point_s', observation.get('age_s', 0.0))),
            }

        supervisor_config = SupervisorConfig(stop_distance_m=args.stop_distance_m)
        boundary = EpisodeBoundary(env)
        results = []
        records = []
        mark('run dynamic paired cases')
        with torch.inference_mode():
            for case in cases:
                obstacle_spec = load_obstacle_spec(case.obstacle)
                case_obs_delay_s = float(obstacle_spec.observation_delay_s)
                case_obs_delay_ns = int(round(case_obs_delay_s * 1_000_000_000))
                for method in methods:
                    boundary.start(seed=case.seed if hasattr(case, 'seed') else 9000)
                    set_robot_pose(case.start_position_world_m, case.start_yaw_rad)
                    set_obstacle_pose((0.0, 0.0, 50.0))
                    state = read_state()
                    executor.reset(state)
                    if delay_wrapper is not None:
                        delay_wrapper.clear()
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
                        ttl_ns=args.ttl_ms * 1_000_000,
                        max_age_ms=args.max_age_ms,
                        allowed_observation_age_ns=args.allowed_observation_age_ms * 1_000_000))
                        if args.execution_path == 'v2' else None)
                    if delay_wrapper is not None:
                        executor.control_epoch = 0
                        delay_wrapper.update_context(
                            epochs=gate_epochs(v2_gate),
                            owner=v2_gate.config.source)
                    episode_id = case.case_id + '-' + method
                    if args.config_id:
                        episode_id += '-' + args.config_id
                    if args.segment_id:
                        episode_id += '-' + args.segment_id
                    outcome, reason = 'RUNNING', 'RUNNING'
                    abort_time_s = None
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
                    episode_rows = []
                    admitted_by_id = {}
                    steps = 0
                    sync_generation = 0
                    max_steps = int(math.ceil(case.timeout_s / dt))
                    for step in range(max_steps):
                        elapsed = (step + 1) * dt
                        now_ns = int(round(elapsed * 1_000_000_000))
                        now_s = elapsed
                        state = read_state()
                        obstacle_t = elapsed
                        if args.obstacle_time_clamp:
                            obstacle_t = min(max(elapsed, obstacle_spec.start_time_s),
                                             obstacle_spec.end_time_s)
                        obstacle_position, obstacle_velocity = obstacle_spec.pose_at(
                            obstacle_t)
                        set_obstacle_pose(obstacle_position)
                        capture_host_ns = max(0, now_ns - obs_delay_ns - case_obs_delay_ns)
                        capture_host_ns = min(capture_host_ns, now_ns)
                        capture_clock_ns = camera_clock.read_ns(capture_host_ns)
                        sync_generation = (int(v2_gate.config.sync_generation)
                                           if v2_gate is not None else 0)
                        mapping = SimMapping(
                            'camera_sim', 'host_monotonic',
                            offset_ns=clock_offset_ns,
                            uncertainty_ns=clock_uncertainty_ns,
                            drift_ppm=args.clock_drift_ppm,
                            sync_generation=sync_generation)
                        mapping_blocked = (args.obs_mapping_fail_step >= 0
                                           and step >= args.obs_mapping_fail_step)
                        if mapping_blocked:
                            age_rec = {
                                'valid': False, 'reason': 'CLOCK_MAPPING_UNUSABLE',
                                'age_point_s': None, 'age_bound_s': None,
                                'mapped_host_ns': None, 'error_bound_ns': None}
                        else:
                            age_rec = mapping_age(capture_clock_ns, now_ns, mapping,
                                                  sync_generation)
                        observation_t = max(0.0, elapsed - args.obs_delay_s)
                        observation_sample_t = observation_t
                        if args.obstacle_time_clamp:
                            observation_sample_t = min(
                                max(observation_t, obstacle_spec.start_time_s),
                                obstacle_spec.end_time_s)
                        raw_observation = obstacle_spec.observation_at(
                            observation_sample_t)
                        if raw_observation.get('valid') and age_rec.get('valid'):
                            observation = dict(raw_observation)
                            observation['age_s'] = float(age_rec['age_bound_s'])
                            observation['age_point_s'] = float(age_rec['age_point_s'])
                        else:
                            observation = {
                                'valid': False,
                                'reason': ('CLOCK_MAPPING_UNUSABLE'
                                           if not age_rec.get('valid')
                                           else raw_observation.get('reason',
                                                                    'OBSERVATION_INVALID')),
                                'age_s': 0.0, 'age_point_s': 0.0,
                                'position_world_m': None,
                                'velocity_world_mps': None,
                                'timestamp_s': observation_t,
                            }
                        target = runner.waypoints[runner.index]
                        speed = math.sqrt(sum(value * value
                                              for value in state.velocity_world_mps))
                        decision = supervisor.update(
                            state.position_world_m, target, speed,
                            observation, route_active_s, dt,
                            robot_velocity_world_mps=state.velocity_world_mps,
                            waypoint_index=runner.index,
                            robot_envelope=robot_envelope_payload,
                            obstacle_envelope={
                                'size_m': [float(value) for value in
                                           (case.obstacle or {}).get(
                                               'size_m', (0.4, 0.4, 0.6))],
                                'source': 'case_obstacle_size'})
                        clearance_record = (decision.get('clearance_record')
                                            or build_clearance_for(
                                                state.position_world_m, target,
                                                observation, runner.index, case))
                        stop_req_record = build_stop_requirement_for(
                            clearance_record, observation,
                            state.position_world_m, state.velocity_world_mps,
                            speed, None)
                        admitted_action = None
                        if method == 'supervisor':
                            states.append(decision['state'])
                            if decision['action'] == 'STOP':
                                command = (0.0, 0.0, 0.0, 0.0)
                            elif decision['action'] == 'ABORT':
                                outcome = 'ABORT'
                                reason = (decision.get('abort_reason')
                                          or 'SUPERVISOR_ABORT')
                                abort_time_s = elapsed
                                episode_rows.append({
                                    'episode_id': episode_id,
                                    'case_id': case.case_id, 'method': method,
                                    'scenario_class': case.scenario_class,
                                    'step': step, 'time_s': round(elapsed, 4),
                                    'phase': 'RUN',
                                    'position_world_m': list(state.position_world_m),
                                    'velocity_world_mps': list(state.velocity_world_mps),
                                    'speed_mps': speed,
                                    'command': [0.0, 0.0, 0.0, 0.0],
                                    'obstacle_position_world_m': list(obstacle_position),
                                    'obstacle_velocity_world_mps': list(obstacle_velocity),
                                    'clock': clock_snapshot(
                                        now_ns, capture_host_ns, capture_clock_ns,
                                        mapping, age_rec, capture_host_ns),
                                    **obstacle_observation_fields(observation),
                                    'supervisor_state': decision['state'],
                                    'supervisor_action': decision['action'],
                                    'supervisor_wait_s': decision['wait_s'],
                                    'route_active_s': route_active_s,
                                    'contact_force_n': 0.0, 'contact_prim': '',
                                    'outcome': outcome, 'reason': reason,
                                    'env_terminated': False, 'env_truncated': False,
                                    'episode_length_buf': 0, 'boundary_count_ok': True,
                                    'execution_path': args.execution_path,
                                    'v2_admission': 'NO_NEW_ACTION',
                                    'v2_reject_reason': '',
                                    'v2_action_id': '', 'v2_executed': False,
                                    'v2_fault_type': (case.fault.get('type')
                                                      if case.fault else None),
                                    'v2_observation_id': '',
                                    'v2_context': None,
                                    'v2_context_owner': '',
                                    'v2_pending_owner': None,
                                    'v2_action_source': '',
                                    'transport': empty_transport(now_ns),
                                    'applied': applied_snapshot(
                                        {'applied': None}, (0.0, 0.0, 0.0, 0.0),
                                        None, now_ns, 0, 0),
                                    'contact_evidence': contact_evidence_for(
                                        state.position_world_m, obstacle_position,
                                        clearance_record, None, speed, elapsed),
                                    'clearance': clearance_record,
                                    'clearance_m': decision.get('clearance_m'),
                                    'stop_requirement': stop_req_record,
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
                        action = None
                        clock_record = clock_snapshot(
                            now_ns, capture_host_ns, capture_clock_ns, mapping,
                            age_rec, capture_host_ns)
                        if v2_gate is not None:
                            observation_id = 'state-' + episode_id + '-' + str(step)
                            if age_rec.get('valid'):
                                header_capture_ns = max(
                                    0, int(age_rec['mapped_host_ns'])
                                    - int(age_rec['error_bound_ns']))
                            else:
                                header_capture_ns = max(
                                    0, now_ns - (args.allowed_observation_age_ms
                                                 * 1_000_000 + 1_000_000))
                            clock_record['header_capture_host_ns'] = int(
                                header_capture_ns)
                            action = v2_gate.build(
                                command, now_ns, step, observation_id,
                                observation_time_ns=header_capture_ns)
                            if args.sync_fail_step >= 0 and step == args.sync_fail_step:
                                v2_gate.bump_context(sync=True)
                            if (delay_wrapper is not None
                                    and args.transport_stall_step >= 0
                                    and step == args.transport_stall_step):
                                delay_wrapper.set_delay(args.transport_stall_delay_s)
                            context = v2_gate.context()
                            v2_observation_id = observation_id
                            v2_context_record = {
                                'system_boot_id': context.system_boot_id,
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
                                    result = v2_gate.admit(fault_action, context,
                                                           now_ns + 1000)
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
                                    result = v2_gate.admit(action, v2_gate.context(),
                                                           now_ns)
                                elif fault_type == 'px4_boot_change':
                                    v2_gate.bump_context(px4_boot=True)
                                    result = v2_gate.admit(action, v2_gate.context(),
                                                           now_ns)
                                elif fault_type == 'clock_sync_mismatch':
                                    bad = v2_gate.build(
                                        command, now_ns, step,
                                        observation_id + '-clock',
                                        header_overrides={'clock_id': 'px4_boot_clock'})
                                    result = v2_gate.admit(bad, context, now_ns)
                                elif fault_type == 'ownership_revoke':
                                    v2_gate.revoke_ownership(now_ns=now_ns)
                                    result = v2_gate.admit(action, v2_gate.context(),
                                                           now_ns)
                                else:
                                    raise RuntimeError('unknown fault type: '
                                                       + str(fault_type))
                                if result is None or not result.accepted:
                                    v2_admission = 'REJECTED'
                                    v2_reject_reason = (result.reason
                                                        if result is not None
                                                        else 'REJECTED')
                                    outcome, reason = 'ABORT', 'V2_' + v2_reject_reason
                                    abort_time_s = elapsed
                                    episode_rows.append({
                                        'episode_id': episode_id, 'case_id': case.case_id,
                                        'method': method,
                                        'scenario_class': case.scenario_class,
                                        'step': step, 'time_s': round(elapsed, 4),
                                        'phase': 'RUN',
                                        'position_world_m': list(state.position_world_m),
                                        'velocity_world_mps': list(state.velocity_world_mps),
                                        'speed_mps': speed,
                                        'command': [0.0, 0.0, 0.0, 0.0],
                                        'obstacle_position_world_m': list(obstacle_position),
                                        'obstacle_velocity_world_mps': list(obstacle_velocity),
                                        'clock': clock_record,
                                        **obstacle_observation_fields(observation),
                                        'supervisor_state': decision['state'],
                                        'supervisor_action': decision['action'],
                                        'supervisor_wait_s': decision['wait_s'],
                                        'route_active_s': route_active_s,
                                        'contact_force_n': 0.0, 'contact_prim': '',
                                        'outcome': outcome, 'reason': reason,
                                        'env_terminated': False, 'env_truncated': False,
                                        'episode_length_buf': 0,
                                        'boundary_count_ok': True,
                                        'execution_path': 'v2',
                                        'v2_admission': 'REJECTED',
                                        'v2_reject_reason': v2_reject_reason,
                                        'v2_action_id': '', 'v2_executed': False,
                                        'v2_fault_type': fault.get('type'),
                                        'v2_observation_id': v2_observation_id,
                                        'v2_context': v2_context_record,
                                        'v2_context_owner': v2_owner,
                                        'v2_pending_owner': v2_pending_owner,
                                        'v2_action_source': v2_action_source,
                                        'transport': empty_transport(now_ns),
                                        'applied': applied_snapshot(
                                            {'applied': None}, command, None,
                                            now_ns, 0, 0),
                                        'contact_evidence': contact_evidence_for(
                                            state.position_world_m,
                                            obstacle_position, clearance_record,
                                            None, speed, elapsed),
                                        'clearance': clearance_record,
                                        'clearance_m': decision.get('clearance_m'),
                                        'stop_requirement': stop_req_record,
                                    })
                                    fault_recorded = fault.get('type')
                                    break
                                v2_admission = 'ADMITTED'
                                v2_action_id = action.action_id
                                v2_issued_ns = action.issued_at_monotonic_ns
                                v2_expires_ns = action.expires_at_monotonic_ns
                                admitted_action = action
                                admitted_by_id[action.action_id] = action
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
                                    abort_time_s = elapsed
                                    episode_rows.append({
                                        'episode_id': episode_id, 'case_id': case.case_id,
                                        'method': method,
                                        'scenario_class': case.scenario_class,
                                        'step': step, 'time_s': round(elapsed, 4),
                                        'phase': 'RUN',
                                        'position_world_m': list(state.position_world_m),
                                        'velocity_world_mps': list(state.velocity_world_mps),
                                        'speed_mps': speed,
                                        'command': [0.0, 0.0, 0.0, 0.0],
                                        'obstacle_position_world_m': list(obstacle_position),
                                        'obstacle_velocity_world_mps': list(obstacle_velocity),
                                        'clock': clock_record,
                                        **obstacle_observation_fields(observation),
                                        'supervisor_state': decision['state'],
                                        'supervisor_action': decision['action'],
                                        'supervisor_wait_s': decision['wait_s'],
                                        'route_active_s': route_active_s,
                                        'contact_force_n': 0.0, 'contact_prim': '',
                                        'outcome': outcome, 'reason': reason,
                                        'env_terminated': False, 'env_truncated': False,
                                        'episode_length_buf': 0,
                                        'boundary_count_ok': True,
                                        'execution_path': 'v2',
                                        'v2_admission': 'REJECTED',
                                        'v2_reject_reason': v2_reject_reason,
                                        'v2_action_id': '', 'v2_executed': False,
                                        'v2_fault_type': (fault.get('type')
                                                          if fault else None),
                                        'v2_observation_id': v2_observation_id,
                                        'v2_context': v2_context_record,
                                        'v2_context_owner': v2_owner,
                                        'v2_pending_owner': v2_pending_owner,
                                        'v2_action_source': v2_action_source,
                                        'transport': empty_transport(now_ns),
                                        'applied': applied_snapshot(
                                            {'applied': None}, command, None,
                                            now_ns, 0, 0),
                                        'contact_evidence': contact_evidence_for(
                                            state.position_world_m,
                                            obstacle_position, clearance_record,
                                            None, speed, elapsed),
                                        'clearance': clearance_record,
                                        'clearance_m': decision.get('clearance_m'),
                                        'stop_requirement': stop_req_record,
                                    })
                                    break
                                v2_admission = 'ADMITTED'
                                v2_action_id = action.action_id
                                v2_issued_ns = action.issued_at_monotonic_ns
                                v2_expires_ns = action.expires_at_monotonic_ns
                                admitted_action = action
                                admitted_by_id[action.action_id] = action
                                command = (action.payload.vx_forward_mps,
                                           action.payload.vy_left_mps,
                                           action.payload.vz_up_mps,
                                           action.payload.yaw_rate_ccw_world_radps)
                        if admitted_action is not None:
                            epochs = gate_epochs(v2_gate)
                            setpoint = VelocitySetpoint(
                                *command,
                                issued_at_s=now_s,
                                expires_at_s=v2_expires_ns / 1_000_000_000.0,
                                control_epoch=admitted_action.control_epoch,
                                action_id=admitted_action.action_id,
                                sync_generation=admitted_action.sync_generation,
                                epochs=epochs)
                            if delay_wrapper is not None:
                                delay_wrapper.update_context(
                                    epochs=epochs, owner=admitted_action.source)
                            control = executor.step(setpoint, state, now_s)
                        else:
                            control = executor.step(None, state, now_s)
                        transport = transport_snapshot(admitted_action, now_ns)
                        applied = applied_snapshot(transport, command,
                                                   admitted_action, now_ns,
                                                   v2_expires_ns, v2_issued_ns)
                        v2_executed = bool(transport.get('executed'))
                        executed_id = transport.get('executed_action_id')
                        if executed_id and executed_id in admitted_by_id:
                            v2_gate.mark_executed(admitted_by_id[executed_id], now_ns)
                        if v2_expires_ns:
                            stop_req_record = build_stop_requirement_for(
                                clearance_record, observation,
                                state.position_world_m, state.velocity_world_mps,
                                speed,
                                max(0.0, (v2_expires_ns - now_ns) / 1_000_000_000.0))
                        actuator_action = control.to_actuator_action(params)
                        _, _, terminated, truncated, _ = env.step(
                            torch.tensor([actuator_action], dtype=torch.float32,
                                         device=env.device))
                        boundary_state = boundary.after_step(
                            terminated[0].item(), truncated[0].item())
                        after = read_state()
                        contact = obstacle_contact()
                        if contact > 0.02:
                            contact_max = max(contact_max, contact)
                            if not contact_prim:
                                contact_prim = dyn_path
                        after_speed = math.sqrt(sum(value * value
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
                                    after.position_world_m, after_speed,
                                    route_active_s, contact=False)
                                if route_decision['outcome'] == 'SUCCESS':
                                    outcome, reason = 'SUCCESS', 'ROUTE_COMPLETE'
                                elif route_decision['outcome'] == 'TIMEOUT':
                                    outcome, reason = 'TIMEOUT', route_decision['reason']
                                if decision['action'] == 'ROUTE':
                                    route_active_s += dt
                        else:
                            route_decision = runner.update(
                                after.position_world_m, after_speed, elapsed,
                                contact=False)
                            if route_decision['outcome'] == 'SUCCESS':
                                outcome, reason = 'SUCCESS', 'ROUTE_COMPLETE'
                            elif route_decision['outcome'] == 'TIMEOUT':
                                outcome, reason = 'TIMEOUT', route_decision['reason']
                        if elapsed >= case.timeout_s and outcome == 'RUNNING':
                            outcome, reason = 'TIMEOUT', 'WALL_TIMEOUT'
                        steps = step + 1
                        episode_rows.append({
                            'episode_id': episode_id, 'case_id': case.case_id,
                            'method': method, 'scenario_class': case.scenario_class,
                            'step': step, 'time_s': round(elapsed, 4),
                            'phase': 'RUN',
                            'position_world_m': list(after.position_world_m),
                            'velocity_world_mps': list(after.velocity_world_mps),
                            'speed_mps': after_speed,
                            'command': list(command),
                            'execution_path': args.execution_path,
                            'v2_admission': v2_admission,
                            'v2_action_id': v2_action_id,
                            'v2_reject_reason': v2_reject_reason,
                            'v2_executed': v2_executed,
                            'v2_issued_at_ns': v2_issued_ns,
                            'v2_expires_at_ns': v2_expires_ns,
                            'v2_fault_type': (case.fault.get('type')
                                              if case.fault else None),
                            'v2_observation_id': v2_observation_id,
                            'v2_context': v2_context_record,
                            'v2_context_owner': v2_owner,
                            'v2_pending_owner': v2_pending_owner,
                            'v2_action_source': v2_action_source,
                            'clock': clock_record,
                            'transport': transport,
                            'applied': applied,
                            'clearance': clearance_record,
                            'clearance_m': decision.get('clearance_m'),
                            'stop_requirement': stop_req_record,
                            'contact_evidence': contact_evidence_for(
                                after.position_world_m, obstacle_position,
                                clearance_record, applied, after_speed, elapsed),
                            'obstacle_position_world_m': list(obstacle_position),
                            'obstacle_velocity_world_mps': list(obstacle_velocity),
                            **obstacle_observation_fields(observation),
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
                            if abort_time_s is None:
                                abort_time_s = elapsed
                            break
                    if outcome == 'RUNNING':
                        outcome, reason = 'TIMEOUT', 'WALL_TIMEOUT'
                        if abort_time_s is None:
                            abort_time_s = (step + 1) * dt
                    # Post-abort physical observation: rejection is not a stop.
                    if args.post_abort_observe_s > 0 and outcome in (
                            'ABORT', 'COLLISION', 'OUT_OF_BOUNDS', 'TIMEOUT'):
                        post_start = (abort_time_s if abort_time_s is not None
                                      else (step + 1) * dt)
                        extra_steps = int(math.ceil(args.post_abort_observe_s / dt))
                        for extra in range(extra_steps):
                            elapsed = post_start + (extra + 1) * dt
                            now_ns = int(round(elapsed * 1_000_000_000))
                            state = read_state()
                            obstacle_t = elapsed
                            if args.obstacle_time_clamp:
                                obstacle_t = min(
                                    max(elapsed, obstacle_spec.start_time_s),
                                    obstacle_spec.end_time_s)
                            obstacle_position, obstacle_velocity = (
                                obstacle_spec.pose_at(obstacle_t))
                            set_obstacle_pose(obstacle_position)
                            if delay_wrapper is not None:
                                delay_wrapper.update_context(
                                    epochs=gate_epochs(v2_gate),
                                    owner=(v2_gate.context().control_owner
                                           if v2_gate is not None else 'STUDENT'))
                            control = executor.step(None, state, elapsed)
                            transport = transport_snapshot(None, now_ns)
                            applied = applied_snapshot(transport, (0.0, 0.0, 0.0, 0.0),
                                                       None, now_ns, 0, 0)
                            actuator_action = control.to_actuator_action(params)
                            _, _, terminated, truncated, _ = env.step(
                                torch.tensor([actuator_action], dtype=torch.float32,
                                             device=env.device))
                            boundary_state = boundary.after_step(
                                terminated[0].item(), truncated[0].item())
                            after = read_state()
                            contact = obstacle_contact()
                            if contact > 0.02:
                                contact_max = max(contact_max, contact)
                                if not contact_prim:
                                    contact_prim = dyn_path
                            after_speed = math.sqrt(sum(
                                value * value for value in after.velocity_world_mps))
                            capture_host_ns = min(now_ns, now_ns)
                            capture_clock_ns = camera_clock.read_ns(capture_host_ns)
                            mapping = SimMapping(
                                'camera_sim', 'host_monotonic',
                                offset_ns=clock_offset_ns,
                                uncertainty_ns=clock_uncertainty_ns,
                                drift_ppm=args.clock_drift_ppm,
                                sync_generation=sync_generation)
                            age_rec = mapping_age(capture_clock_ns, now_ns, mapping,
                                                  sync_generation)
                            episode_rows.append({
                                'episode_id': episode_id, 'case_id': case.case_id,
                                'method': method, 'scenario_class': case.scenario_class,
                                'step': steps + extra, 'time_s': round(elapsed, 4),
                                'phase': 'POST_ABORT',
                                'position_world_m': list(after.position_world_m),
                                'velocity_world_mps': list(after.velocity_world_mps),
                                'speed_mps': after_speed,
                                'command': [0.0, 0.0, 0.0, 0.0],
                                'clock': clock_snapshot(
                                    now_ns, capture_host_ns, capture_clock_ns,
                                    mapping, age_rec, capture_host_ns),
                                'transport': transport,
                                'applied': applied,
                                'contact_evidence': contact_evidence_for(
                                    after.position_world_m, obstacle_position,
                                    clearance_record, applied, after_speed,
                                    elapsed),
                                'obstacle_position_world_m': list(obstacle_position),
                                'obstacle_velocity_world_mps': list(obstacle_velocity),
                                'observation_valid': False,
                                'observation_reason': 'POST_ABORT_NO_ACTION',
                                'observation_age_s': 0.0,
                                'execution_path': args.execution_path,
                                'v2_admission': 'NO_NEW_ACTION',
                                'v2_action_id': '',
                                'v2_reject_reason': '',
                                'v2_executed': False,
                                'v2_issued_at_ns': 0,
                                'v2_expires_at_ns': 0,
                                'v2_fault_type': (case.fault.get('type')
                                                  if case.fault else None),
                                'v2_observation_id': '',
                                'v2_context': None,
                                'v2_context_owner': '',
                                'v2_pending_owner': None,
                                'v2_action_source': '',
                                'supervisor_state': ('ABORT' if outcome == 'ABORT'
                                                     else 'POST_ABORT'),
                                'supervisor_action': 'NONE',
                                'supervisor_wait_s': wait_total,
                                'route_active_s': route_active_s,
                                'contact_force_n': contact,
                                'contact_prim': contact_prim,
                                'outcome': outcome, 'reason': reason,
                                'env_terminated': boundary_state['terminated'],
                                'env_truncated': boundary_state['truncated'],
                                'episode_length_buf': boundary_state['episode_length_buf'],
                                'boundary_count_ok': boundary_state['count_ok'],
                            })
                    if outcome == 'SUCCESS' and method == 'supervisor':
                        capture(episode_id + '_success')
                    if contact_prim and method == 'supervisor':
                        capture(episode_id + '_contact')
                    metrics = compute_episode_metrics(episode_rows, case)
                    if outcome in ('SUCCESS', 'ABORT', 'TIMEOUT', 'INVALID'):
                        business_outcome = outcome
                    else:
                        business_outcome = 'ABORT'
                    evidence_summary = metrics.get('contact_evidence_summary') or {}
                    if outcome == 'COLLISION' or contact_max > 0.02:
                        physical_outcome = 'CONTACT_MEASURED'
                    elif evidence_summary.get('inferred_contact'):
                        physical_outcome = 'CONTACT_INFERRED'
                    elif outcome == 'OUT_OF_BOUNDS':
                        physical_outcome = 'OUT_OF_BOUNDS'
                    else:
                        physical_outcome = 'NO_CONTACT'
                    if physical_outcome in ('CONTACT_MEASURED',
                                            'CONTACT_INFERRED') and not contact_prim:
                        contact_prim = ('OBSTACLE_FORCE_SENSOR'
                                        if physical_outcome == 'CONTACT_MEASURED'
                                        else 'INFERRED_OBSTACLE_OVERLAP')
                    records.extend(episode_rows)
                    results.append({
                        'episode_id': episode_id, 'case_id': case.case_id,
                        'business_outcome': business_outcome,
                        'physical_outcome': physical_outcome,
                        'role': (boundary_plan_doc or {}).get('role', ''),
                        'method': method, 'scenario_class': case.scenario_class,
                        'route_id': case.route_id,
                        'config_id': args.config_id,
                        'segment_id': args.segment_id,
                        'pair_key': case.case_id,
                        'outcome': outcome, 'reason': reason, 'steps': steps,
                        'duration_s': steps * dt, 'route_active_s': route_active_s,
                        'wait_total_s': wait_total,
                        'state_transitions': (len([1 for a, b in
                                                   zip(states, states[1:]) if a != b])
                                              if states else 0),
                        'states': sorted(set(states)),
                        'contact_max_force_n': contact_max,
                        'contact_prim': contact_prim,
                        'contact_evidence_summary': evidence_summary,
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
                        'metrics': metrics,
                        'phase_summary': {
                            'RUN': sum(1 for row in episode_rows
                                       if row.get('phase', 'RUN') == 'RUN'),
                            'POST_ABORT': sum(1 for row in episode_rows
                                              if row.get('phase') == 'POST_ABORT'),
                        },
                    })
                    print('[episode] ' + episode_id + ' ' + outcome + ' ' + reason,
                          flush=True)
        env._get_dones = original_dones
        mark('write outputs')
        if args.config_id or args.segment_id:
            latency_plan = build_plan('main' if args.config_id else 'special')
        else:
            latency_plan = {
                'role': 'regression', 'segment_id': '', 'config_id': '',
                'cases_file': Path(args.cases).as_posix(),
                'cases_sha256': case_sha,
                'case_ids': [case.case_id for case in cases],
                'methods': methods, 'execution_path': args.execution_path,
                'obs_delay_s': args.obs_delay_s,
                'action_delay_s': args.action_delay_s,
                'ttl_ms': args.ttl_ms, 'max_age_ms': args.max_age_ms,
                'allowed_observation_age_ms': args.allowed_observation_age_ms,
                'stop_distance_m': args.stop_distance_m,
                'post_abort_observe_s': args.post_abort_observe_s,
                'clock_offset_ms': args.clock_offset_ms,
                'clock_drift_ppm': args.clock_drift_ppm,
                'clock_uncertainty_ms': args.clock_uncertainty_ms,
                'sync_fail_step': args.sync_fail_step,
                'obs_mapping_fail_step': args.obs_mapping_fail_step,
                'transport_stall_step': args.transport_stall_step,
                'transport_stall_delay_s': args.transport_stall_delay_s,
            }
        episode_ids = [item['episode_id'] for item in results]
        if len(episode_ids) != len(set(episode_ids)):
            raise RuntimeError('duplicate episode ids')
        summary = {
            'schema_version': 'boom_birds.dynamic_eval.v1',
            'evaluation_version': LATENCY_EVAL_VERSION,
            'status': 'PASS' if all(item['outcome'] != 'INVALID' for item in results)
            else 'FAIL',
            'scope': 'ORACLE_DYNAMIC_OBSTACLE_STOP_WAIT_RESUME',
            'execution_path': args.execution_path,
            'config_id': args.config_id,
            'segment_id': args.segment_id,
            'latency_plan': latency_plan,
            'boundary_plan': boundary_plan_doc,
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
            'clock_plan': {
                'camera_clock_id': camera_clock.clock_id,
                'offset_ms': args.clock_offset_ms,
                'drift_ppm': args.clock_drift_ppm,
                'uncertainty_ms': args.clock_uncertainty_ms,
            },
            'gui_mode': not bool(getattr(args, 'headless', False)),
        }
        summary_path = args.output / 'summary.json'
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        with (args.output / 'episodes.jsonl').open('w', encoding='utf-8') as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        with (args.output / 'steps.jsonl').open('w', encoding='utf-8') as handle:
            for item in records:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        started_dt = _parse_iso(started_at)
        frozen_dt = _parse_iso(freeze_meta.get('frozen_at', ''))
        if frozen_dt is not None and started_dt is not None and frozen_dt > started_dt:
            raise RuntimeError('freeze frozen_at is after run start; refusing to '
                               'record as pre-run evidence')
        manifest = {
            'schema_version': 'boom_birds.manifest.v1',
            'evaluation_version': LATENCY_EVAL_VERSION,
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
            'started_at': started_at,
            'latency_plan': latency_plan,
            'boundary_plan': boundary_plan_doc,
            'vehicle_config': {'file': Path(args.vehicle_config).as_posix(),
                               'sha256': vehicle_config_sha},
            'expected_file': (boundary_expected_path.as_posix()
                              if boundary_plan_doc is not None else ''),
            'expected_sha256': boundary_expected_sha,
            'brake_model_file': (brake_model_path.as_posix()
                                 if boundary_plan_doc is not None else ''),
            'brake_model_sha256': brake_model_sha,
            'clearance_algorithm': {
                'id': clearance_mod.CLEARANCE_ALGORITHM_ID,
                'version': clearance_mod.CLEARANCE_ALGORITHM_VERSION,
                'schema_version': clearance_mod.CLEARANCE_SCHEMA_VERSION},
            'stop_requirement_schema_version':
                stop_req_mod.STOP_REQUIREMENT_SCHEMA_VERSION,
            'envelope_policy': {
                'robot_radius_rule': 'sqrt(sum(aabb_half_extents^2))',
                'robot_attitude_scope': 'any_rigid_rotation_about_center',
                'obstacle_radius_rule': 'max(obstacle_size)/2',
                'limitation': ('sphere/AABB approximation; not a triangle-mesh '
                               'sweep')},
            'contact_sensor': contact_sensor_info,
            'obstacle_time_clamp': bool(args.obstacle_time_clamp),
            'clock_plan': {
                'camera_clock_id': camera_clock.clock_id,
                'offset_ms': args.clock_offset_ms,
                'drift_ppm': args.clock_drift_ppm,
                'uncertainty_ms': args.clock_uncertainty_ms,
            },
            'freeze': freeze_meta,
            'body_envelope': body_envelope,
            'gui_evidence': {
                'gui_mode': not bool(getattr(args, 'headless', False)),
                'renderer': 'DirectX (--/app/vulkan=false)',
                'headless': bool(getattr(args, 'headless', False)),
                'window_required': True,
                'screenshots': bool(args.screenshots),
                'gpu_driver': args.gpu_driver,
            },
            'episode_ids': episode_ids,
            'command': ' '.join(sys.argv),
            'outputs_sha256': {
                name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                for name in ('summary.json', 'episodes.jsonl', 'steps.jsonl')},
        }
        (args.output / 'manifest.json').write_text(
            json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        print('DYNAMIC_EVAL_' + summary['status'] + ' '
              + json.dumps(summary['outcomes']), flush=True)
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
