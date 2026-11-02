"""Recompute clearance/stop-requirement numbers with the measured body-envelope
centre offset (sphere about the robot reference origin) and keep the legacy
radius comparison explicit.  Read-only offline analysis; no Isaac.
"""
import argparse
import json
import math
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding='utf-8').splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary-run', type=Path,
                        default=Path('outputs/map_eval/bnd_boundary_default'))
    parser.add_argument('--envelope-manifest', type=Path,
                        default=Path('outputs/map_eval/contact_A_wall/manifest.json'))
    parser.add_argument('--output', type=Path,
                        default=Path('docs/reports/map_eval/contact_envelope/analyze_envelope_correction.json'))
    args = parser.parse_args()

    manifest = load_json(args.envelope_manifest)
    envelope = manifest['body_envelope']
    half = [float(v) for v in envelope['aabb']['half_extents_m']]
    offset = [float(v) for v in envelope['aabb']['center_offset_m']]
    radius_origin = float(envelope['sphere_about_origin']['radius_m'])
    radius_legacy = math.sqrt(sum(value * value for value in half))
    delta = radius_origin - radius_legacy
    payload = {
        'schema_version': 'boom_birds.envelope_correction_analysis.v1',
        'source': {
            'envelope_manifest': str(args.envelope_manifest),
            'boundary_run': str(args.boundary_run),
            'policy': envelope.get('policy', {}),
            'coverage': envelope.get('coverage', {}),
            'limitations': envelope.get('limitations', []),
        },
        'aabb': {'half_extents_m': half, 'center_offset_m': offset},
        'radius_sphere_about_aabb_center_m': radius_legacy,
        'radius_sphere_about_origin_m': radius_origin,
        'legacy_underestimate_m': delta,
        'formula': 'r_origin = || |center_offset| + half_extents ||_2; '
                   'r_legacy = ||half_extents||_2 (only valid for zero offset)',
        'thresholds': {
            threshold: {
                'envelope_gap_legacy_m': threshold - radius_legacy - 0.3,
                'envelope_gap_corrected_m': threshold - radius_origin - 0.3,
            } for threshold in (1.1, 1.38)
        },
        'episodes': {},
    }
    steps = load_jsonl(args.boundary_run / 'steps.jsonl')
    by_episode = {}
    for row in steps:
        by_episode.setdefault(row['episode_id'], []).append(row)
    for episode_id, rows in by_episode.items():
        clearance_min = None
        corrected_gap_min = None
        legacy_radius_seen = None
        margin_min = None
        margin_corrected_min = None
        for row in rows:
            clearance_row = row.get('clearance') or {}
            metrics = clearance_row.get('metrics') or {}
            path_clearance = metrics.get('path_clearance_m')
            envelopes = clearance_row.get('envelopes') or {}
            obstacle_radius = (envelopes.get('obstacle') or {}).get('radius_m')
            robot_radius = (envelopes.get('robot') or {}).get('radius_m')
            if robot_radius is not None:
                legacy_radius_seen = float(robot_radius)
            if path_clearance is not None and obstacle_radius is not None:
                corrected = path_clearance - radius_origin - float(obstacle_radius)
                if clearance_min is None or path_clearance < clearance_min:
                    clearance_min = path_clearance
                if corrected_gap_min is None or corrected < corrected_gap_min:
                    corrected_gap_min = corrected
            requirement = row.get('stop_requirement') or {}
            margin = requirement.get('margin_to_threshold_m')
            if margin is not None:
                corrected_margin = float(margin) - delta
                if margin_min is None or float(margin) < margin_min:
                    margin_min = float(margin)
                if margin_corrected_min is None or corrected_margin < margin_corrected_min:
                    margin_corrected_min = corrected_margin
        payload['episodes'][episode_id] = {
            'min_path_clearance_m': clearance_min,
            'min_path_clearance_gap_corrected_m': corrected_gap_min,
            'legacy_robot_radius_recorded_m': legacy_radius_seen,
            'stop_requirement_min_margin_recorded_m': margin_min,
            'stop_requirement_min_margin_corrected_m': margin_corrected_min,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({'radius_legacy': radius_legacy,
                      'radius_origin': radius_origin,
                      'delta': delta,
                      'episodes': len(payload['episodes'])}, indent=2))


if __name__ == '__main__':
    main()
