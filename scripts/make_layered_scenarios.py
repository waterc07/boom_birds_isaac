"""Generate the layered (v2) scenario manifest for one run family."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.sim.layered import (  # noqa: E402
    SCENE_CLASSES,
    RandomizationSpecV2,
    build_layered_manifest,
    generate_layered_scenarios,
    write_layered_manifest,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--per-class', type=int, default=25)
parser.add_argument('--base-seed', type=int, required=True)
parser.add_argument('--generated-at', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()

spec = RandomizationSpecV2()
by_class = {}
for index, name in enumerate(SCENE_CLASSES):
    by_class[name] = generate_layered_scenarios(
        name, args.per_class, base_seed=args.base_seed + index * 1000, spec=spec)
manifest = build_layered_manifest(by_class, spec=spec, generated_at=args.generated_at)
path = write_layered_manifest(args.output, manifest)
print('LAYERED_MANIFEST_WRITTEN', path)
print('content_sha256', manifest['content_sha256'])
for name in SCENE_CLASSES:
    print(name, len(by_class[name]))
