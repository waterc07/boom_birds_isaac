"""Generate deterministic, replayable reach scenarios (standard library only)."""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from boom_birds.sim.scenarios import (  # noqa: E402
    RandomizationSpec,
    build_scenario_manifest,
    generate_scenarios,
    write_scenario_manifest,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--count', type=int, required=True)
parser.add_argument('--base-seed', type=int, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--generated-at', default=None,
                    help='fixed timestamp for reproducible hashes')
args = parser.parse_args()

spec = RandomizationSpec()
scenarios = generate_scenarios(args.count, base_seed=args.base_seed, spec=spec)
timestamp = args.generated_at or datetime.datetime.now().astimezone().isoformat()
manifest = build_scenario_manifest(scenarios, spec=spec, base_seed=args.base_seed,
                                   generated_at=timestamp)
path = write_scenario_manifest(args.output, manifest)
print('SCENARIO_MANIFEST_WRITTEN', path)
print('content_sha256', manifest['content_sha256'])
print('count', manifest['count'], 'base_seed', manifest['base_seed'])
print('distance_bins', {name: sum(1 for item in scenarios if item.distance_bin == name)
                       for name in ('short', 'medium', 'long')})
print('bearing_bins', {name: sum(1 for item in scenarios if item.bearing_bin == name)
                       for name in ('front', 'side', 'rear')})
