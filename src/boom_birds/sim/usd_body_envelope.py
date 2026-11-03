"""Runtime USD collision bounds; imports USD only inside the measurement."""
import math
from typing import Any

from boom_birds.sim.body_envelope import EnvelopeCoverage, body_envelope_record


def measure_collision_envelope(stage: Any, robot_root: str) -> dict:
    """Bound authored collision prims in the robot reference frame.

    AABB corners are inverse transformed before reducing. Missing/nonfinite
    bounds fail explicitly; visual-only props are not silently included.
    """
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    root = stage.GetPrimAtPath(robot_root)
    if not root or not root.IsValid():
        raise ValueError('robot reference prim unavailable')
    inverse = UsdGeom.Xformable(root).ComputeLocalToWorldTransform(
        Usd.TimeCode.Default()).GetInverse()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                             [UsdGeom.Tokens.default_, UsdGeom.Tokens.render,
                              UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide])
    points, paths, bodies = [], [], []
    for prim in Usd.PrimRange(root):
        if not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        # Collision meshes can have proxy/guide purpose and be hidden from
        # default/render BBoxCache. Read their actual vertices independently.
        mesh = UsdGeom.Mesh(prim)
        mesh_points = mesh.GetPointsAttr().Get() if mesh else None
        if mesh_points:
            world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default())
            world_points = [list(world.Transform(Gf.Vec3d(*p))) for p in mesh_points]
            low = [min(p[i] for p in world_points) for i in range(3)]
            high = [max(p[i] for p in world_points) for i in range(3)]
        else:
            bound = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            low, high = list(bound.GetMin()), list(bound.GetMax())
        if not all(math.isfinite(v) for v in low + high) or any(
                high[i] < low[i] for i in range(3)):
            raise ValueError('invalid collision bound: ' + str(prim.GetPath()))
        paths.append(str(prim.GetPath()))
        ancestor = prim
        while ancestor and ancestor.IsValid():
            if ancestor.HasAPI(UsdPhysics.RigidBodyAPI):
                bodies.append(ancestor.GetName())
                break
            ancestor = ancestor.GetParent()
        for x in (low[0], high[0]):
            for y in (low[1], high[1]):
                for z in (low[2], high[2]):
                    points.append(list(inverse.Transform(Gf.Vec3d(x, y, z))))
    if not points:
        raise ValueError('robot has no measurable collision geometry')
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    half = [(high[i] - low[i]) / 2.0 for i in range(3)]
    offset = [(high[i] + low[i]) / 2.0 for i in range(3)]
    coverage = EnvelopeCoverage(source='collision_geometry', prim_paths=tuple(paths),
                                collision_prim_paths=tuple(paths),
                                sub_bodies=tuple(sorted(set(bodies))))
    return body_envelope_record(
        half, offset, coverage=coverage,
        measurement={'source': 'usd_collision_mesh_points_or_all_purpose_bound',
                     'frame': 'robot_reference_frame', 'robot_root_prim': robot_root,
                     'limitation': 'authored transforms and fixed joint state; not a swept mesh'})
