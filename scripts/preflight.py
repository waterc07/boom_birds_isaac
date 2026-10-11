"""Read-only metadata/CUDA inspection; never installs dependencies or starts Kit."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys


def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=60)
        return {'command': [str(x) for x in argv], 'returncode': p.returncode,
                'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'command': [str(x) for x in argv], 'returncode': None, 'error': str(exc)}


def collect_environment(isaaclab_root=None):
    root = Path(isaaclab_root) if isaaclab_root else None
    packages = {}
    for name in ('isaaclab', 'isaaclab_tasks', 'isaaclab_rl', 'isaaclab_assets',
                 'isaacsim', 'isaacsim-rl', 'torch', 'torchvision', 'rsl-rl-lib',
                 'skrl', 'rl-games', 'stable-baselines3', 'pytest'):
        try:
            dist = metadata.distribution(name)
            packages[name] = {'version': dist.version, 'location': str(dist.locate_file('')),
                              'direct_url': dist.read_text('direct_url.json')}
        except metadata.PackageNotFoundError:
            packages[name] = {'version': 'unknown', 'reason': 'distribution not found'}
    cuda = {'status': 'unknown'}
    try:
        import torch
        cuda = {'torch_version': torch.__version__, 'build_cuda': torch.version.cuda,
                'available': torch.cuda.is_available()}
        if cuda['available']:
            cuda['device'] = torch.cuda.get_device_name(0)
            cuda['tensor_sum'] = torch.ones(4, device='cuda').sum().item()
    except Exception as exc:
        cuda['error'] = f'{type(exc).__name__}: {exc}'
    lab = {'root': str(root) if root else 'unknown'}
    if root:
        version_file = root / 'VERSION'
        lab['version_file'] = version_file.read_text().strip() if version_file.exists() else 'unknown'
        lab['commit'] = command(['git', '-C', str(root), 'rev-parse', 'HEAD'])
        lab['status'] = command(['git', '-C', str(root), 'status', '--porcelain'])
        launcher = root / 'isaaclab.bat'
        lab['launcher'] = {'path': str(launcher), 'exists': launcher.exists(),
                           'sha256': hashlib.sha256(launcher.read_bytes()).hexdigest() if launcher.exists() else 'unknown'}
    return {'schema_version': 1, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'metadata_and_cuda_only_not_flight_validation',
            'host': {'os': platform.platform(), 'machine': platform.machine()},
            'python': {'executable': sys.executable, 'version': sys.version, 'prefix': sys.prefix},
            'packages': packages, 'isaaclab': lab, 'cuda': cuda,
            'gpu_driver': command(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader']),
            'dependency_consistency': command([sys.executable, '-m', 'pip', 'check']),
            'project_source': command(['git', 'rev-parse', 'HEAD']),
            'project_worktree_status': command(['git', 'status', '--porcelain']),
            'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'official_example': 'NOT RUN BY THIS SCRIPT', 'ppo_training': 'NOT RUN BY THIS SCRIPT'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--isaaclab-root', type=Path)
    args = parser.parse_args()
    result = collect_environment(args.isaaclab_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Environment recorded: {args.output} (see evidence fields; not a G0 PASS)')
