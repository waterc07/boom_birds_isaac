"""Bounded P0 diagnostic of the installed official task; no project policy."""
import argparse
import hashlib
import json
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--steps', type=int, default=100)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--clone-in-usd', action='store_true', help='Disable Fabric cloning only; keep physics/Fabric I/O')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if args.steps < 1:
    parser.error('--steps must be positive')
app = AppLauncher(args).app

try:
    import inspect
    import torch
    from isaaclab_tasks.direct.quadcopter.quadcopter_env import QuadcopterEnv, QuadcopterEnvCfg

    cfg = QuadcopterEnvCfg()
    cfg.scene.num_envs = 1
    cfg.sim.device = args.device
    cfg.debug_vis = False
    cfg.seed = 0
    if args.clone_in_usd:
        cfg.scene.clone_in_fabric = False
    env = QuadcopterEnv(cfg)
    try:
        obs, _ = env.reset()
        actions = torch.zeros((1, 4), device=env.device)
        samples = []
        with torch.inference_mode():
            for step in range(args.steps):
                obs, reward, terminated, truncated, _ = env.step(actions)
                if not torch.isfinite(obs['policy']).all() or not torch.isfinite(reward).all():
                    raise RuntimeError(f'Nonfinite official output at step {step}')
                samples.append({'step': step, 'position_world_m': env._robot.data.root_pos_w[0].tolist(),
                                'reward': reward.item(), 'terminated': terminated.item(),
                                'truncated': truncated.item()})
        source = Path(inspect.getfile(QuadcopterEnv))
        result = {'scope': 'OFFICIAL_TASK_ZERO_ACTION_SMOKE_ONLY', 'status': 'PASS',
                  'project_velocity_controller': 'NOT RUN', 'task_source': str(source),
                  'task_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'asset_uri': cfg.robot.spawn.usd_path, 'steps': args.steps, 'num_envs': 1,
                  'seed': cfg.seed, 'observation_shape': list(obs['policy'].shape),
                  'action_semantics': 'total_body_thrust_and_three_body_moments',
                  'clone_in_fabric': cfg.scene.clone_in_fabric,
                  'step_dt_s': env.step_dt, 'mass_kg': env._robot_mass.item(),
                  'gravity_mps2': list(cfg.sim.gravity), 'samples': samples}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(f'BOOM_BIRDS_OFFICIAL_SMOKE_PASS steps={args.steps}', flush=True)
    finally:
        env.close()
finally:
    app.close()
