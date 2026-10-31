"""GUI probe of candidate map regions: ground grid, horizontal obstacle rays."""
import argparse
import json
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
    from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file

    ctx = omni.usd.get_context()
    assert ctx.open_stage(str(args.preview)), 'Stage open failed'
    for _ in range(90):
        app.update()
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(30):
        app.update()
    query = omni.physx.get_physx_scene_query_interface()

    samples = []
    for x in np.arange(-13.0, -8.0 + 1e-9, 0.25):
        for y in np.arange(-2.0, 3.0 + 1e-9, 0.25):
            down = query.raycast_closest((float(x), float(y), 10.0),
                                         (0.0, 0.0, -1.0), 30.0)
            if not down.get('hit'):
                continue
            samples.append({'x': float(x), 'y': float(y),
                            'ground_z': float(down['position'][2]),
                            'prim': str(down.get('collision', ''))})

    wall_rays = []
    for y in (-1.5, -0.75, 0.0, 0.75, 1.5, 2.25):
        for z in (0.5, 1.0, 1.5):
            hit = query.raycast_closest((-4.0, float(y), float(z)),
                                        (1.0, 0.0, 0.0), 12.0)
            wall_rays.append({'y': float(y), 'z': float(z),
                              'hit': bool(hit.get('hit')),
                              'distance_m': (float(hit['distance'])
                                             if hit.get('hit') else None),
                              'prim': str(hit.get('collision', ''))})
    timeline.pause()
    for _ in range(20):
        app.update()
    viewport = get_active_viewport()
    viewport.camera_path = '/World/Overview'
    viewport.resolution = (1280, 800)
    png = args.output / 'region_overview.png'
    capture_viewport_to_file(viewport, str(png))
    for _ in range(120):
        app.update()
        if png.exists():
            break
    result = {
        'status': 'PASS' if samples else 'FAIL',
        'samples': len(samples),
        'ground_z_min_m': min(item['ground_z'] for item in samples),
        'ground_z_max_m': max(item['ground_z'] for item in samples),
        'ground_z_by_site': {
            '(-11.5, 0.5)': next((item['ground_z'] for item in samples
                                  if abs(item['x'] + 11.5) < 1e-6
                                  and abs(item['y'] - 0.5) < 1e-6), None),
            '(-11.5, 1.5)': next((item['ground_z'] for item in samples
                                  if abs(item['x'] + 11.5) < 1e-6
                                  and abs(item['y'] - 1.5) < 1e-6), None),
        },
        'wall_rays': wall_rays,
        'screenshot_exists': png.exists(),
    }
    (args.output / 'site_probe.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (args.output / 'ground_grid.json').write_text(
        json.dumps({'samples': samples}, indent=2) + '\n', encoding='utf-8')
    print('SITE_PROBE_DONE ' + json.dumps({key: result[key] for key in
          ('status', 'samples', 'ground_z_min_m', 'ground_z_max_m')}), flush=True)
    if args.hold_s > 0:
        import time
        deadline = time.time() + args.hold_s
        while time.time() < deadline and app.is_running():
            app.update()
finally:
    app.close()
