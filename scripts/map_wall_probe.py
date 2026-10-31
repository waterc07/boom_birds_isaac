"""GUI ray probe along candidate contact lines."""
import json
from pathlib import Path
from isaacsim import SimulationApp

app = SimulationApp({'headless': False, 'width': 1024, 'height': 640,
                     'window_width': 1200, 'window_height': 800,
                     'extra_args': ['--/app/vulkan=false'], 'multi_gpu': False,
                     'renderer': 'RaytracedLighting'})
try:
    import omni.usd
    import omni.timeline
    import omni.physx
    ctx = omni.usd.get_context()
    assert ctx.open_stage(r'E:\isaac\boom_birds_storage\assets\RMUC2027_IsaacSim\rmuc2027_preview.usda')
    for _ in range(80):
        app.update()
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(30):
        app.update()
    q = omni.physx.get_physx_scene_query_interface()
    rows = []
    for z in (0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6):
        for y in (0.0, 0.5, -0.5):
            hit = q.raycast_closest((-4.0, y, z), (1.0, 0.0, 0.0), 8.0)
            rows.append({'z': z, 'y': y, 'hit': bool(hit.get('hit')),
                         'x': (float(hit['position'][0]) if hit.get('hit') else None),
                         'prim': str(hit.get('collision', ''))})
    timeline.pause()
    Path('outputs/map_eval/wall_probe1').mkdir(parents=True, exist_ok=True)
    Path('outputs/map_eval/wall_probe1/wall_probe.json').write_text(
        json.dumps({'rows': rows}, indent=2))
    print('WALL_PROBE ' + json.dumps(rows[:8]), flush=True)
finally:
    app.close()
