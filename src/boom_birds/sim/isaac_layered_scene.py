"""Isaac-side layered scene: static obstacles, entities and contact evidence.

Imported only inside an Isaac app. Physics assets are spawned before the robot
environment so PhysX sees them at initialisation; per-scenario poses, entity
velocities and contact filters are reset through their physics views.
"""
import math

import torch

import isaaclab.sim as sim_utils
from isaaclab.sim import schemas as sim_schemas
from isaaclab.sensors import ContactSensor, ContactSensorCfg
from isaacsim.core.prims import RigidPrim

from .contact_evidence import (
    contact_evidence_from_forces,
    restrict_contact_evidence,
)
from .disturbance import DisturbanceSpec, wrench_at
from .layered import (
    DYNAMIC_MASS_KG,
    nearby_asset_names,
    DYNAMIC_RADIUS_M,
    KINEMATIC_SIZE_M,
    OBSTACLE_SIZES_M,
    LayeredScenario,
)

PARK_Z_M = 50.0
LAYERED_ROOT = '/World/layered_assets'
OBSTACLE_PATHS = ('{}/obs0'.format(LAYERED_ROOT), '{}/obs1'.format(LAYERED_ROOT))
MOVER_PATH = '{}/mover'.format(LAYERED_ROOT)
BALL_PATH = '{}/ball'.format(LAYERED_ROOT)
ALL_PATHS = OBSTACLE_PATHS + (MOVER_PATH, BALL_PATH)


def spawn_layered_assets():
    """Spawn fixed-size kinematic/dynamic physics assets before env creation."""
    import omni.usd  # noqa: F401
    stage = omni.usd.get_context().get_stage()
    for path in ALL_PATHS:
        if stage.GetPrimAtPath(path).IsValid():
            if path == ALL_PATHS[0]:
                from isaaclab.sim.utils import delete_prim
                delete_prim(LAYERED_ROOT)
            break
    common = dict(
        collision_props=sim_utils.CollisionPropertiesCfg(),
        mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
    )
    for index, path in enumerate(OBSTACLE_PATHS):
        sim_utils.spawn_cuboid(
            path,
            sim_utils.CuboidCfg(
                size=OBSTACLE_SIZES_M[index],
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    kinematic_enabled=True, disable_gravity=True),
                activate_contact_sensors=True,
                **common),
            translation=(0.0, 0.0, PARK_Z_M))
    sim_utils.spawn_cuboid(
        MOVER_PATH,
        sim_utils.CuboidCfg(
            size=KINEMATIC_SIZE_M,
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                kinematic_enabled=True, disable_gravity=True),
            activate_contact_sensors=True,
            **common),
        translation=(0.0, PARK_Z_M, PARK_Z_M))
    sim_utils.spawn_sphere(
        BALL_PATH,
        sim_utils.SphereCfg(
            radius=DYNAMIC_RADIUS_M,
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                kinematic_enabled=False, disable_gravity=False),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=DYNAMIC_MASS_KG),
            activate_contact_sensors=True),
        translation=(0.0, PARK_Z_M, PARK_Z_M))
    for path in ALL_PATHS:
        sim_schemas.activate_contact_sensors(path)
    from pxr import PhysxSchema
    for path in ALL_PATHS:
        prim = stage.GetPrimAtPath(path)
        print('[layered] reporter {} valid={} api={}'.format(
            path, prim.IsValid(), prim.HasAPI(PhysxSchema.PhysxContactReportAPI)),
            flush=True)
    return ALL_PATHS


class LayeredScene:
    """Per-episode scene reset, kinematic motion and PhysX contact evidence."""

    def __init__(self, env, *, contact_threshold_n=0.02):
        self.env = env
        self.contact_threshold_n = float(contact_threshold_n)
        self.rigid_views = {
            path: RigidPrim(path, name='layered_' + path.rsplit('/', 1)[-1],
                            reset_xform_properties=False)
            for path in ALL_PATHS}
        robot_root = '/World/envs/env_0/Robot'
        robot_body_paths = [robot_root + '/' + name
                            for name in list(env._robot.body_names)]
        import omni.usd
        from pxr import PhysxSchema
        robot_stage = omni.usd.get_context().get_stage()
        for path in robot_body_paths:
            prim = robot_stage.GetPrimAtPath(path)
            had = prim.IsValid() and prim.HasAPI(PhysxSchema.PhysxContactReportAPI)
            print('[layered] robot reporter {} valid={} api={}'.format(
                path, prim.IsValid(), had), flush=True)
            if prim.IsValid() and not had:
                sim_schemas.activate_contact_sensors(path)
        self.sensor = ContactSensor(ContactSensorCfg(
            prim_path=LAYERED_ROOT + '/.*',
            update_period=0.0,
            history_length=0,
            debug_vis=False,
            filter_prim_paths_expr=robot_body_paths))
        if not self.sensor.is_initialized:
            self.sensor._initialize_callback(None)
        self.sensor_body_names = list(self.sensor.body_names)
        print('[layered] contact bodies={} filters={} num_filters={}'.format(
            self.sensor_body_names, robot_body_paths,
            getattr(self.sensor, 'num_filters', 'n/a')), flush=True)
        self._contact_debug_done = False
        self._park()

    def _tensor(self, rows):
        return torch.tensor(rows, dtype=torch.float32, device=self.env.device)

    def _park(self):
        for path in ALL_PATHS:
            self.rigid_views[path].set_world_poses(
                positions=self._tensor([[0.0, 0.0, PARK_Z_M]]),
                orientations=self._tensor([[1.0, 0.0, 0.0, 0.0]]))
            try:
                self.rigid_views[path].set_velocities(
                    self._tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]))
            except Exception:
                pass

    def _place(self, path, center, orientation=(1.0, 0.0, 0.0, 0.0)):
        self.rigid_views[path].set_world_poses(
            positions=self._tensor([[float(center[0]), float(center[1]),
                                    float(center[2])]]),
            orientations=self._tensor([list(orientation)]))

    def reset_scenario(self, scenario):
        if not isinstance(scenario, LayeredScenario):
            raise ValueError('scenario must be a LayeredScenario')
        self._park()
        if scenario.scene_class == 'B_static':
            for index, obstacle in enumerate(scenario.obstacles):
                self._place(OBSTACLE_PATHS[index], obstacle.center_world_m)
        elif scenario.scene_class == 'C_dynamic':
            entity = scenario.kinematic_entity
            self._place(MOVER_PATH, entity.center_world_m)
            dynamic = scenario.dynamic_entity
            self._place(BALL_PATH, dynamic.center_world_m)
            velocity = list(dynamic.velocity_world_mps) + [0.0, 0.0, 0.0]
            self.rigid_views[BALL_PATH].set_velocities(self._tensor([velocity]))
        try:
            self.sensor.update(dt=self.env.step_dt)
            self.sensor._data.force_matrix_w.zero_()
            self.sensor._data.net_forces_w.zero_()
        except Exception:
            pass
        self.scenario = scenario
        self._initial_mover_center = (
            scenario.kinematic_entity.center_world_m
            if scenario.kinematic_entity is not None else None)

    def update(self, scenario, elapsed_s):
        if scenario.scene_class != 'C_dynamic':
            return
        entity = scenario.kinematic_entity
        center = tuple(
            self._initial_mover_center[index]
            + entity.velocity_world_mps[index] * elapsed_s
            for index in range(3))
        self._place(MOVER_PATH, center)

    def contact_evidence(self, scenario, robot_position_world_m, step=None):
        self.sensor.update(dt=self.env.step_dt)
        data = self.sensor.data
        matrix = data.force_matrix_w
        if matrix is None:
            raise RuntimeError('contact sensor force matrix unavailable')
        if not self._contact_debug_done:
            print('[layered] force_matrix shape={} max={:.6f}'.format(
                tuple(matrix.shape), float(matrix.abs().max())), flush=True)
            self._contact_debug_done = True
        totals = matrix[0].sum(dim=1)
        mapping = {}
        for index, name in enumerate(self.sensor_body_names):
            mapping[name] = tuple(totals[index].tolist())
        evidence = contact_evidence_from_forces(
            mapping, threshold_n=self.contact_threshold_n, step=step)
        allowed = nearby_asset_names(scenario, robot_position_world_m)
        return restrict_contact_evidence(evidence, allowed)

    def dynamic_entity_state(self):
        position, _orientation = self.rigid_views[BALL_PATH].get_world_poses()
        return [float(value) for value in position[0].tolist()]

    def entity_states(self):
        states = {}
        for name, path in (('mover', MOVER_PATH), ('ball', BALL_PATH)):
            position, _orientation = self.rigid_views[path].get_world_poses()
            states[name] = [float(value) for value in position[0].tolist()]
        return states


class DisturbanceInjector:
    """Adds body-frame force/torque through the env wrench path."""

    def __init__(self, env):
        self.env = env
        self.spec = None
        self.time_s = 0.0
        self.applied = False
        self.last_force = (0.0, 0.0, 0.0)
        self.last_torque = (0.0, 0.0, 0.0)
        self._original_pre_physics_step = env._pre_physics_step

        def patched(actions):
            self._original_pre_physics_step(actions)
            if self.spec is None:
                return
            force, torque = wrench_at(self.spec, self.time_s)
            self.last_force = force
            self.last_torque = torque
            if force == (0.0, 0.0, 0.0) and torque == (0.0, 0.0, 0.0):
                return
            self.env._thrust[0, 0, 0] += force[0]
            self.env._thrust[0, 0, 1] += force[1]
            self.env._thrust[0, 0, 2] += force[2]
            self.env._moment[0, 0, 0] += torque[0]
            self.env._moment[0, 0, 1] += torque[1]
            self.env._moment[0, 0, 2] += torque[2]
            self.applied = True

        env._pre_physics_step = patched

    def begin(self, spec):
        if spec is not None and not isinstance(spec, DisturbanceSpec):
            raise ValueError('spec must be a DisturbanceSpec or None')
        self.spec = spec
        self.time_s = 0.0
        self.applied = False
        self.last_force = (0.0, 0.0, 0.0)
        self.last_torque = (0.0, 0.0, 0.0)

    def tick(self, time_s):
        self.time_s = float(time_s)
