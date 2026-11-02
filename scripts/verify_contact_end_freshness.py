"""Independent verifier for the contact-end freshness probe (natural vs teleport)."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.contact_raw_audit import audit_row


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify(path, *, expected_mode):
    data = load(path / 'contact_end_freshness.json')
    checks = []

    def check(name, passed, detail):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})

    rows = data.get('rows') or []
    check('mode', data.get('separation_mode') == expected_mode,
          'separation_mode=' + str(data.get('separation_mode')))
    check('natural_flag', data.get('natural_separation')
          == (expected_mode == 'obstacle_motion'), 'natural_separation flag')
    check('handshake', (data.get('handshake') or {}).get('ok') is True,
          'handshake=' + str((data.get('handshake') or {}).get('ok')))
    check('no_mid_reset', data.get('mid_episode_hard_reset') is False
          and data.get('physics_generation') == 1,
          'generation/mid-reset flags')
    cycles = data.get('phases') or []
    check('cycles', len(cycles) == 3, 'cycles=' + str(len(cycles)))
    raw_errors = []
    step_values = []
    for row in rows:
        try:
            measured = audit_row(row)
            if not math.isclose(measured['measured_force_n'],
                                row['measure']['measured_force_n'],
                                abs_tol=1e-9, rel_tol=1e-7):
                raise ValueError('measurement cache mismatch')
        except Exception as error:  # noqa: BLE001
            raw_errors.append(str(error))
        step_values.append(int(row.get('physics_step', -1)))
    check('raw_vector_consistency', not raw_errors,
          'raw errors=' + repr(raw_errors[:3]))
    check('physics_step_monotonic', all(b >= a for a, b in
                                        zip(step_values, step_values[1:])),
          'physics steps=' + str(len(step_values)))
    natural = expected_mode == 'obstacle_motion'
    teleport_stale_cycles = 0
    for cycle in cycles:
        cid = cycle.get('cycle')
        cycle_rows = [row for row in rows if row.get('cycle') == cid]
        separation = [row for row in cycle_rows
                      if row.get('phase') == 'separation']
        contact = bool(cycle.get('contact'))
        recontact = bool(cycle.get('recontact'))
        separated = bool(cycle.get('separated_zero'))
        after_sep = [row for row in separation
                     if row.get('box_separation_m', 0.0) > 0.1]
        max_after = max((row['measure']['measured_force_n']
                         for row in after_sep), default=0.0)
        if natural:
            check('cycle_contact_' + str(cid), contact,
                  'contact=' + str(contact))
            check('cycle_separation_zero_' + str(cid),
                  separated and max_after <= 1e-6,
                  'separated_zero=' + str(separated)
                  + ' max_after_sep=' + format(max_after, '.9f'))
            check('cycle_recontact_' + str(cid), recontact,
                  'recontact=' + str(recontact))
        else:
            # Explicit teleport control: stale force is expected in at least one
            # teleport cycle; it is never mixed with the natural result.
            if max_after > 0.0:
                teleport_stale_cycles += 1
    if not natural:
        check('teleport_control_stale_any_cycle', teleport_stale_cycles > 0,
              'stale teleport cycles=' + str(teleport_stale_cycles)
              + '/3')
    status = 'PASS' if all(item['passed'] for item in checks) else 'FAIL'
    return {'status': status, 'mode': expected_mode,
            'rows': len(rows), 'checks': checks,
            'failures': [item for item in checks if not item['passed']],
            'sha256': sha(path / 'contact_end_freshness.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--natural', type=Path, required=True)
    parser.add_argument('--teleport-control', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    natural = verify(args.natural, expected_mode='obstacle_motion')
    teleport = verify(args.teleport_control, expected_mode='robot_teleport')
    report = {'schema_version': 'dsh.contact_end_verify.v1',
              'status': ('PASS' if natural['status'] == 'PASS'
                         and teleport['status'] == 'PASS' else 'FAIL'),
              'natural': natural, 'teleport_control': teleport}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'],
                      'natural': natural['status'],
                      'teleport': teleport['status'],
                      'natural_failures': natural['failures'],
                      'teleport_failures': teleport['failures']},
                     ensure_ascii=False))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
