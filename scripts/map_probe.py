"""GUI probe of the RMUC2027 map: geometry, grid raycasts, screenshot."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from isaacsim import SimulationApp

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--preview', type=Path, required=True)
parser.add_argument('--terrain', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--grid-step-m', type=float, default=1.0)
parser.add_argument('--hold-s', type=float, default=10.0)
parser.add_argument('--backend', choices=['directx', 'vulkan'], default='directx')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)

extra = ['--/app/vulkan=false'] if args.backend == 'directx' else []
app = SimulationApp({'headless': False, 'width': 1280, 'height': 800,
                     'window_width': 1400, 'window_height': 900,
                     'extra_args': extra, 'multi_gpu': False,
                     'renderer': 'RaytracedLighting'})
print('MAP_PROBE_APP_STARTED backend=' + args.backend, flush=True)
try:
    import numpy as np
    import omni.usd
    import omni.timeline
    import omni.physx
    from pxr import Usd, UsdGeom
    from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file

    ctx = omni.usd.get_context()
    print('OPEN_STAGE_BEGIN', flush=True)
    assert ctx.open_stage(str(args.preview)), 'Stage open failed'
    print('OPEN_STAGE_DONE', flush=True)
    for _ in range(120):
        app.update()
    print('STAGE_UPDATED', flush=True)
    stage = ctx.get_stage()
    bbox = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]
    ).ComputeWorldBound(stage.GetPrimAtPath('/World/Terrain')).ComputeAlignedRange()
    low = list(bbox.GetMin())
    high = list(bbox.GetMax())
    print('BBOX_DONE', low, high, flush=True)
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(60):
        app.update()
    print('PHYSICS_PLAYED', flush=True)
    query = omni.physx.get_physx_scene_query_interface()
    step = args.grid_step_m
    xs = np.arange(low[0] + 0.5, high[0] - 0.5 + 1e-9, step)
    ys = np.arange(low[1] + 0.5, high[1] - 0.5 + 1e-9, step)
    samples = []
    print('RAYCAST_BEGIN', len(xs), len(ys), flush=True)
    for x in xs:
        for y in ys:
            down = query.raycast_closest((float(x), float(y), 10.0),
                                         (0.0, 0.0, -1.0), 30.0)
            if not down.get('hit'):
                continue
            position = down.get('position')
            z = float(position[2]) if position is not None else float('nan')
            up = query.raycast_closest((float(x), float(y), z + 0.15),
                                       (0.0, 0.0, 1.0), 6.0)
            clearance = (float(up['position'][2]) - z) if up.get('hit') else 6.0
            samples.append({'x': float(x), 'y': float(y), 'ground_z': z,
                            'clearance_m': clearance,
                            'collision_prim': str(down.get('collision', ''))})
    print('RAYCAST_DONE', len(samples), flush=True)
    timeline.pause()
    for _ in range(30):
        app.update()
    viewport = get_active_viewport()
    assert viewport, 'Missing viewport'
    viewport.camera_path = '/World/Overview'
    viewport.resolution = (1280, 800)
    png = args.output / 'map_probe_overview.png'
    capture_viewport_to_file(viewport, str(png))
    for _ in range(120):
        app.update()
        if png.exists():
            break
    heights = [item['ground_z'] for item in samples]
    flat = [item for item in samples
            if item['clearance_m'] > 1.2 and abs(item['ground_z'] - np.median(heights)) < 0.05]
    result = {
        'status': 'PASS' if samples else 'FAIL',
        'scope': 'MAP_GEOMETRY_RAYCAST_GUI_PROBE',
        'preview': str(args.preview.resolve()),
        'terrain': str(args.terrain.resolve()),
        'preview_sha256': hashlib.sha256(args.preview.read_bytes()).hexdigest(),
        'terrain_sha256': hashlib.sha256(args.terrain.read_bytes()).hexdigest(),
        'bounds_min_m': low,
        'bounds_max_m': high,
        'samples': len(samples),
        'ground_z_min_m': min(heights),
        'ground_z_max_m': max(heights),
        'ground_z_median_m': float(np.median(heights)),
        'flat_clear_samples': len(flat),
        'flat_clear_sample_examples': flat[:20],
        'screenshot': str(png),
        'screenshot_exists': png.exists(),
        'gui_mode': True,
        'backend': args.backend,
        'limitations': ['diagnostic raycasts only; no robot or dynamic contact in this probe'],
    }
    (args.output / 'map_probe.json').write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (args.output / 'map_grid.json').write_text(
        json.dumps({'samples': samples}, indent=2) + '\n', encoding='utf-8')
    print('MAP_PROBE_DONE ' + json.dumps({key: result[key] for key in
          ('status', 'samples', 'flat_clear_samples', 'ground_z_median_m')}), flush=True)
    if args.hold_s > 0:
        deadline = time.time() + args.hold_s
        while time.time() < deadline and app.is_running():
            app.update()
except BaseException:
    import traceback
    (args.output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    traceback.print_exc()
    raise
finally:
    app.close()