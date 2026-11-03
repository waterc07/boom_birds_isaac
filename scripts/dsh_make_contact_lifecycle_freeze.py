"""Pre-run freeze for the DSH minimal contact-freshness matrix (no Isaac needed).

Creates a pre-run frozen document for:
  contact_W_wall3    (3 consecutive wall contacts, hard physics reset per episode)
  contact_S_static3  (3 consecutive static obstacle contacts, hard reset per episode)
It records reset mode, readout source hash, contact evidence version, cases and
expected hashes, and the exact per-episode run plan consumed by the runner.
Existing files are never overwritten.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'boom_birds.dsh_contact_lifecycle_freeze.v1'
READER = Path('src/boom_birds/evaluation/contact_readout.py')
SEGMENTS = ('contact_W_wall3', 'contact_S_static3')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_head():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True,
                          text=True, check=True).stdout.strip()


def git_status():
    out = subprocess.run(['git', 'status', '--porcelain'], capture_output=True,
                         text=True, check=True).stdout
    return {'dirty': bool(out.strip()),
            'porcelain_sha256': hashlib.sha256(out.encode('utf-8')).hexdigest(),
            'entries': len([line for line in out.splitlines() if line.strip()])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path,
                        default=Path('configs/scenarios/dsh_contact_lifecycle_minimal_cases_v1.json'))
    parser.add_argument('--expected', type=Path,
                        default=Path('configs/scenarios/dsh_contact_lifecycle_minimal_expected_v1.json'))
    parser.add_argument('--vehicle-config', default='configs/vehicles/sim_reference.yaml')
    parser.add_argument('--map-config', default='configs/maps/rmuc2027.yaml')
    parser.add_argument('--local-config', default='configs/maps/rmuc2027.local.yaml')
    parser.add_argument('--output', type=Path,
                        default=Path('configs/scenarios/dsh_contact_lifecycle_freeze_v1.json'))
    parser.add_argument('--code-commit', default=None)
    parser.add_argument('--working-tree', default='recorded by the operator')
    parser.add_argument('--note', default='DSH minimal contact freshness matrix pre-run freeze')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if args.output.exists() and not args.dry_run:
        print('ERROR: freeze already exists, refusing to overwrite: ' + str(args.output))
        raise SystemExit(2)
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    expected = json.loads(args.expected.read_text(encoding='utf-8'))
    cases_by_seg = {seg['segment_id']: seg for seg in cases['segments']}
    if set(cases_by_seg) != set(SEGMENTS):
        raise SystemExit('cases segments must be exactly ' + repr(SEGMENTS))
    if expected.get('schema_version') != 'dsh.contact_lifecycle_expected.v2':
        raise SystemExit('expected schema mismatch')
    if expected.get('status') != 'EXPECTED_NOT_CONCLUSION':
        raise SystemExit('expected status mismatch')
    reset_mode = expected.get('physics_reset_mode')
    handshake = expected.get('handshake')
    if reset_mode != 'hard':
        raise SystemExit('expected physics_reset_mode must be hard')
    if not isinstance(handshake, dict) or 'max_steps' not in handshake:
        raise SystemExit('expected handshake config missing')
    contact_readout = {
        'schema_version': 'boom_birds.contact_readout.v1',
        'source_sha256': sha256_file(READER),
        'negative_coverage': 'unverified',
        'event_basis': 'force_threshold_inference',
    }
    cases_sha = sha256_file(args.cases)
    expected_sha = sha256_file(args.expected)
    code_commit = args.code_commit or git_head()
    frozen_at = datetime.now(timezone.utc).isoformat()
    segments = {}
    for segment_id in SEGMENTS:
        seg = cases_by_seg[segment_id]
        case_ids = [case['case_id'] for case in seg['cases']]
        if len(case_ids) != int(expected['segments'][segment_id]['episodes']):
            raise SystemExit('episode count mismatch for ' + segment_id)
        if len(set(case_ids)) != len(case_ids):
            raise SystemExit('duplicate case ids for ' + segment_id)
        missing = [cid for cid in case_ids if cid not in expected['cases']]
        if missing:
            raise SystemExit('expected missing cases: ' + repr(missing))
        segments[segment_id] = {
            'segment_id': segment_id,
            'role': seg['role'],
            'mode': seg['mode'],
            'case_ids': case_ids,
            'episodes': len(case_ids),
            'run_plan': {
                'segment_id': segment_id,
                'role': seg['role'],
                'mode': seg['mode'],
                'cases_file': args.cases.as_posix(),
                'cases_sha256': cases_sha,
                'case_ids': case_ids,
                'expected_file': args.expected.as_posix(),
                'expected_sha256': expected_sha,
                'contact_contract_version': cases['contact_contract_version'],
                'envelope_contract_version': cases['envelope_contract_version'],
                'vehicle_config': args.vehicle_config,
                'vehicle_config_sha256': sha256_file(args.vehicle_config),
                'map_config': args.map_config,
                'map_config_sha256': sha256_file(args.map_config),
                'physics_reset_mode': reset_mode,
                'handshake': {'max_steps': int(handshake['max_steps']),
                              'zero_tolerance_n': float(handshake['zero_tolerance_n'])},
                'contact_evidence_version': cases['contact_contract_version'],
                'contact_readout': contact_readout,
                'run_params': {
                    'contact_threshold_n': float(cases.get('contact_threshold_n', 0.02)),
                    'post_contact_observe_s': 0.0,
                    'cases': seg['cases'],
                },
            },
            'expected': expected['segments'][segment_id],
        }
    freeze = {
        'schema_version': SCHEMA,
        'status': 'PRE_RUN_FROZEN',
        'frozen_at': frozen_at,
        'code_commit': code_commit,
        'worktree_state': git_status(),
        'working_tree_note': args.working_tree,
        'contact_readout': contact_readout,
        'contact_evidence_version': cases['contact_contract_version'],
        'envelope_contract_version': cases['envelope_contract_version'],
        'physics_reset_mode': reset_mode,
        'handshake': {'max_steps': int(handshake['max_steps']),
                      'zero_tolerance_n': float(handshake['zero_tolerance_n'])},
        'cases_file': args.cases.as_posix(),
        'cases_sha256': cases_sha,
        'expected_file': args.expected.as_posix(),
        'expected_sha256': expected_sha,
        'vehicle_config': args.vehicle_config,
        'vehicle_config_sha256': sha256_file(args.vehicle_config),
        'map_config': args.map_config,
        'map_config_sha256': sha256_file(args.map_config),
        'segments': segments,
        'budget': {'segments': 2, 'episodes': 6},
        'support_scope': {
            'scope': 'CURRENT_SIM_MODEL_SINGLE_ENV_ONLY',
            'gui_evidence_domain': 'Isaac Sim GUI DirectX/D3D12; no headless',
            'reset_mode': 'hard physics reset at each episode start; no mid-episode reset',
            'contact_evidence': 'contact_readout.v1 + force_threshold_inference; negative coverage unverified',
            'low_force': 'below 0.02 N is measured force, not no-contact',
            'limitations': ['single environment only', 'not multi-env training',
                            'no native contact callback evidence',
                            'old freeze/results unchanged', 'no Gate promotion'],
        },
        'note': args.note,
    }
    if args.dry_run:
        print(json.dumps({'dry_run': True, 'segments': list(segments),
                          'code_commit': code_commit,
                          'readout_sha256': contact_readout['source_sha256']},
                         indent=2))
        return
    args.output.write_text(json.dumps(freeze, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print('FROZEN ' + str(args.output))
    print('frozen_at=' + frozen_at)
    print('code_commit=' + code_commit)
    print('readout_sha256=' + contact_readout['source_sha256'])
    for segment_id, entry in segments.items():
        print('SEGMENT ' + segment_id + ' episodes=' + str(entry['episodes']))
    print('cases_sha256=' + cases_sha)
    print('expected_sha256=' + expected_sha)


if __name__ == '__main__':
    main()
