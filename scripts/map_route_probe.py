"""GUI map geometry/corridor probe for multi-region and route planning."""
import argparse
import json
import math
from pathlib import Path

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--preview', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--hold-s', type=float, default=5.0)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
app = SimulationApp({'headless': False, 'width': 1280, 'height': 800,
                     'window_width': 1400, 'window_height': 900,
                     'extra_args': ['--/app/vulkan=false'], 'multi_gpu': False,
                     'renderer': 'RaytracedLighting'})
try:
    import numpy as np
    import omni.usd
    import omni.timeline
    import omni.physx
    from pxr import Usd, UsdGeom, UsdPhysics
    from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file

    assert omni.usd.get_context().open_stage(str(args.preview)), 'stage open failed'
    for _ in range(100):
        app.update()
    stage = omni.usd.get_context().get_stage()
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(30):
        app.update()
    query = omni.physx.get_physx_scene_query_interface()

    def hit(origin, direction, distance):
        result = query.raycast_closest((float(origin[0]), float(origin[1]),
                                        float(origin[2])),
                                       (float(direction[0]), float(direction[1]),
                                        float(direction[2])), float(distance))
        return result if result.get('hit') else None

    def ground_z(x, y):
        result = hit((x, y, 10.0), (0.0, 0.0, -1.0), 30.0)
        return (float(result['position'][2]), str(result.get('collision', ''))) \
            if result else (None, '')

    directions = [(1, 0), (-1, 0), (0, 1), (0, -1),
                  (0.7071, 0.7071), (-0.7071, 0.7071),
                  (0.7071, -0.7071), (-0.7071, -0.7071)]

    def clearance(x, y, z):
        up = hit((x, y, z), (0.0, 0.0, 1.0), 4.0)
        horizontal = []
        for dx, dy in directions:
            result = hit((x, y, z), (dx, dy, 0.0), 1.5)
            horizontal.append(float(result['distance']) if result else 1.5)
        return {'up_m': float(up['distance']) if up else 4.0,
                'min_horizontal_m': min(horizontal),
                'blocked_prim': str(hit((x, y, z), (0.0, 0.0, 1.0), 4.0).get('collision', ''))
                if up else ''}

    regions = {
        'W': {'x': (-10.6, -8.9), 'y': (-2.3, 2.3)},
        'E': {'x': (7.9, 10.6), 'y': (-1.6, 1.6)},
        'S': {'x': (-6.2, -1.8), 'y': (-7.2, -5.7)},
        'N': {'x': (-6.2, -1.8), 'y': (5.7, 7.2)},
    }
    region_results = {}
    for name, box in regions.items():
        cells = []
        x_values = np.arange(box['x'][0], box['x'][1] + 1e-9, 0.5)
        y_values = np.arange(box['y'][0], box['y'][1] + 1e-9, 0.5)
        for x in x_values:
            for y in y_values:
                ground, prim = ground_z(float(x), float(y))
                if ground is None:
                    continue
                samples = []
                for height in (0.4, 1.0, 1.6):
                    samples.append(clearance(float(x), float(y), ground + height))
                usable = all(item['up_m'] > 1.2 and item['min_horizontal_m'] > 0.55
                             for item in samples)
                cells.append({'x': float(x), 'y': float(y), 'ground_z': ground,
                              'ground_prim': prim, 'samples': samples,
                              'usable': usable})
        region_results[name] = {
            'box': box, 'cell_count': len(cells),
            'usable_cells': sum(1 for item in cells if item['usable']),
            'min_ground_z': min((item['ground_z'] for item in cells), default=None),
            'max_ground_z': max((item['ground_z'] for item in cells), default=None),
            'cells': cells,
        }

    routes = {
        'south': [[-10.0, 0.0, 1.0], [-10.0, -4.0, 1.0], [-6.0, -6.2, 1.0],
                  [6.0, -6.2, 1.0], [9.5, -4.0, 1.0], [9.5, 0.0, 1.0]],
        'north': [[-10.0, 0.0, 1.0], [-10.0, 3.5, 1.0], [-6.0, 5.8, 1.0],
                  [5.5, 5.8, 1.0], [9.5, 3.5, 1.0], [9.5, 0.0, 1.0]],
        'center_high': [[-10.0, 0.0, 1.0], [-6.0, 0.5, 1.0], [-3.0, 2.5, 1.0],
                        [3.0, 2.5, 1.0], [7.0, 0.5, 1.0], [9.5, 0.0, 1.0]],
        'west_south': [[-10.0, 0.0, 1.0], [-10.0, -3.5, 1.0], [-7.0, -5.8, 1.0],
                       [-3.0, -6.2, 1.0]],
        'east_north': [[9.5, 0.0, 1.0], [9.5, 3.5, 1.0], [6.0, 5.8, 1.0],
                       [0.0, 5.8, 1.0]],
    }
    route_results = {}
    for name, waypoints in routes.items():
        points = []
        blocked = []
        for start, end in zip(waypoints, waypoints[1:]):
            segment = [end[index] - start[index] for index in range(3)]
            length = math.sqrt(sum(value * value for value in segment))
            count = max(2, int(length / 0.25))
            for step in range(count + 1):
                fraction = step / count
                point = [start[index] + segment[index] * fraction
                         for index in range(3)]
                samples = []
                for dz in (-0.25, 0.0, 0.25):
                    samples.append(clearance(point[0], point[1], point[2] + dz))
                usable = all(item['up_m'] > 1.0 and item['min_horizontal_m'] > 0.5
                             for item in samples)
                record = {'point': point, 'samples': samples, 'usable': usable}
                points.append(record)
                if not usable:
                    blocked.append(record)
        route_results[name] = {'waypoints': waypoints, 'sample_count': len(points),
                               'blocked_count': len(blocked),
                               'blocked_examples': blocked[:12]}

    visual_meshes = []
    collision_meshes = []
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                   [UsdGeom.Tokens.default_, UsdGeom.Tokens.render,
                                    UsdGeom.Tokens.guide])
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        path = str(prim.GetPath())
        bound = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        record = {'prim': path, 'min': list(bound.GetMin()), 'max': list(bound.GetMax()),
                  'collision_api': prim.HasAPI(UsdPhysics.CollisionAPI)}
        if '/Visuals/' in path:
            visual_meshes.append(record)
        if '/Collisions/' in path:
            collision_meshes.append(record)
    timeline.pause()
    for _ in range(20):
        app.update()
    viewport = get_active_viewport()
    viewport.camera_path = '/World/Overview'
    viewport.resolution = (1280, 800)
    png = args.output / 'route_probe_overview.png'
    capture_viewport_to_file(viewport, str(png))
    for _ in range(120):
        app.update()
        if png.exists():
            break
    result = {
        'status': 'PASS',
        'scope': 'MAP_GEOMETRY_REGION_ROUTE_RAYCAST_GUI',
        'preview_sha256': __import__('hashlib').sha256(args.preview.read_bytes()).hexdigest(),
        'regions': region_results,
        'routes': route_results,
        'visual_meshes': len(visual_meshes),
        'collision_meshes': len(collision_meshes),
        'visual_bbox': [min(item['min'][0] for item in visual_meshes),
                        min(item['min'][1] for item in visual_meshes),
                        min(item['min'][2] for item in visual_meshes),
                        max(item['max'][0] for item in visual_meshes),
                        max(item['max'][1] for item in visual_meshes),
                        max(item['max'][2] for item in visual_meshes)],
        'collision_bbox': [min(item['min'][0] for item in collision_meshes),
                           min(item['min'][1] for item in collision_meshes),
                           min(item['min'][2] for item in collision_meshes),
                           max(item['max'][0] for item in collision_meshes),
                           max(item['max'][1] for item in collision_meshes),
                           max(item['max'][2] for item in collision_meshes)],
        'geometry_note': 'visual and collision checked as independent prim/bounds lists; no visual-mesh intersection performed',
        'screenshot_exists': png.exists(),
    }
    (args.output / 'route_probe.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (args.output / 'visual_meshes.json').write_text(
        json.dumps(visual_meshes, indent=2) + '\n', encoding='utf-8')
    (args.output / 'collision_meshes.json').write_text(
        json.dumps(collision_meshes, indent=2) + '\n', encoding='utf-8')
    print('ROUTE_PROBE_DONE ' + json.dumps({
        'regions': {name: {'usable': item['usable_cells'],
                           'cells': item['cell_count']}
                    for name, item in region_results.items()},
        'routes': {name: {'blocked': item['blocked_count'],
                          'samples': item['sample_count']}
                   for name, item in route_results.items()},
        'visual': len(visual_meshes), 'collision': len(collision_meshes)}), flush=True)
    if args.hold_s > 0:
        import time
        deadline = time.time() + args.hold_s
        while time.time() < deadline and app.is_running():
            app.update()
finally:
    app.close()