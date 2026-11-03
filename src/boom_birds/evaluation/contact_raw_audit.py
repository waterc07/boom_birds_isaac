"""Independent measurement-cache checks over serialized raw force vectors."""
import math
from collections.abc import Mapping


def _norm(vector):
    if (not isinstance(vector, (list, tuple)) or len(vector) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in vector)):
        raise ValueError('invalid raw force vector')
    return math.hypot(*vector)


def audit_row(row: Mapping) -> dict:
    """Recompute from vectors; cached measure fields are only comparisons.

    This checks stored data, not sensor coverage or physical freshness.
    """
    readout = row.get('contact_readout') or {}
    reads = readout.get('reads')
    if not isinstance(reads, list) or not reads:
        raise ValueError('missing raw sensor reads')
    net_norms, filtered_norms = [], []
    for read in reads:
        if not isinstance(read, Mapping) or read.get('error') is not None:
            raise ValueError('raw read error')
        sample = read.get('sample')
        if not isinstance(sample, Mapping):
            raise ValueError('missing raw sample')
        net = sample.get('net_vectors_n')
        filtered = sample.get('filtered_by_target_n')
        if not isinstance(net, (list, tuple)) or not isinstance(filtered, Mapping):
            raise ValueError('invalid raw vector containers')
        if not net and not filtered:
            raise ValueError('empty raw sample')
        net_norms.extend(_norm(v) for v in net)
        for target, vector in filtered.items():
            if not isinstance(target, str) or not target:
                raise ValueError('invalid raw target')
            filtered_norms.append(_norm(vector))
    result = {'read_ok': True,
              'max_net_force_n': max(net_norms, default=0.0),
              'max_filtered_force_n': max(filtered_norms, default=0.0),
              'measured_force_n': max(net_norms + filtered_norms, default=0.0)}
    for cache in (row, readout.get('measure') or {}):
        for name, actual in result.items():
            if name not in cache:
                continue
            reported = cache[name]
            if name == 'read_ok':
                if reported is not True:
                    raise ValueError('read_ok disagrees with raw reads')
            elif (isinstance(reported, bool) or not isinstance(reported, (int, float))
                  or not math.isfinite(reported)
                  or not math.isclose(reported, actual, abs_tol=1e-9, rel_tol=1e-7)):
                raise ValueError(name + ' disagrees with raw vectors')
    return result
