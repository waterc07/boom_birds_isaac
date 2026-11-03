"""Decode PhysX force samples without importing Torch or the simulator.

Force tensors are (N, B, 3) and (N, B, M, 3). A successful read is not
proof that a sensor covers every contact. In particular raw zero samples
remain observable but do not establish a NO_CONTACT verdict here.
"""
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Sequence

from boom_birds.evaluation import contact_contract


CONTACT_READOUT_SCHEMA_ID = 'boom_birds.contact_readout.v1'
Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class ForceSample:
    """Peak body vector per target, not a sum or time-window maximum."""

    net_vectors_n: tuple[Vector3, ...]
    filtered_by_target_n: dict[str, Vector3]

    @property
    def max_net_n(self) -> float:
        return max((math.hypot(*v) for v in self.net_vectors_n), default=0.0)

    @property
    def max_filtered_n(self) -> float:
        return max((math.hypot(*v) for v in self.filtered_by_target_n.values()),
                   default=0.0)


@dataclass(frozen=True)
class ContactRead:
    sample: ForceSample | None
    error: str | None


def _array(value: Any, label: str) -> list:
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(label + ' must be a nonempty array')
    return list(value)


def _vector(value: Any, label: str) -> Vector3:
    values = _array(value, label)
    if len(values) != 3 or any(
            isinstance(v, bool) or not isinstance(v, Real)
            or not math.isfinite(v) for v in values):
        raise ValueError(label + ' must be a finite three-vector')
    return tuple(float(v) for v in values)


def decode_contact_forces(*, net_forces_w: Any, force_matrix_w: Any,
                          target_paths: Sequence[str],
                          env_index: int = 0) -> ForceSample:
    """Validate the entire selected sample before returning any force.

    Target order must match the resolved PhysX filter order. Mismatches fail
    explicitly; callers must not infer a target from proximity or net force.
    """
    if isinstance(env_index, bool) or not isinstance(env_index, int) or env_index < 0:
        raise ValueError('env_index must be a nonnegative integer')
    if isinstance(target_paths, str):
        raise ValueError('target_paths must be an ordered sequence')
    targets = tuple(target_paths)
    if any(not isinstance(p, str) or not p for p in targets) or len(set(targets)) != len(targets):
        raise ValueError('filter target paths must be unique nonempty strings')
    if net_forces_w is None and force_matrix_w is None:
        raise ValueError('no contact force arrays available')
    net_vectors = ()
    body_count = None
    env_count = None
    if net_forces_w is not None:
        net_envs = _array(net_forces_w, 'net_forces_w')
        if env_index >= len(net_envs):
            raise ValueError('net environment index out of bounds')
        net_bodies = _array(net_envs[env_index], 'net bodies')
        net_vectors = tuple(_vector(v, 'net force') for v in net_bodies)
        body_count, env_count = len(net_bodies), len(net_envs)
    filtered = {}
    if force_matrix_w is not None:
        matrix_envs = _array(force_matrix_w, 'force_matrix_w')
        if env_index >= len(matrix_envs) or (env_count is not None and len(matrix_envs) != env_count):
            raise ValueError('filtered environment count/index mismatch')
        bodies = _array(matrix_envs[env_index], 'filtered bodies')
        if body_count is not None and len(bodies) != body_count:
            raise ValueError('filtered body count mismatch')
        for body in bodies:
            filters = _array(body, 'filtered targets')
            if len(filters) != len(targets):
                raise ValueError('resolved filter count does not match target paths')
            for target, value in zip(targets, filters):
                vector = _vector(value, 'filtered force')
                if target not in filtered or math.hypot(*vector) > math.hypot(*filtered[target]):
                    filtered[target] = vector
    return ForceSample(net_vectors_n=net_vectors,
                       filtered_by_target_n=filtered)


def read_contact_sensor(sensor: Any, *, dt_s: float,
                        target_paths: Sequence[str]) -> ContactRead:
    """Read once atomically; errors remain errors instead of synthetic zero."""
    try:
        sensor.update(dt=dt_s, force_recompute=True)
        data = sensor.data
        sample = decode_contact_forces(
            net_forces_w=data.net_forces_w,
            force_matrix_w=data.force_matrix_w,
            target_paths=target_paths)
    except Exception as error:
        return ContactRead(sample=None, error=type(error).__name__ + ': ' + str(error))
    return ContactRead(sample=sample, error=None)


def build_readout_record(reads: Sequence[ContactRead], *, step: int,
                         time_s: float, sample_dt_s: float,
                         geometry: dict | None = None) -> dict:
    """Adapt positive force evidence to v2; negative/failed reads stay UNKNOWN.

    The v2 event bool is derived from a force threshold, not a separately
    subscribed PhysX contact event. Its derivation is explicit in notes.
    Coverage of negative readings is not established by this adapter.
    """
    errors = [r.error for r in reads if r.error or r.sample is None]
    samples = [r.sample for r in reads if r.sample is not None]
    filtered: dict[str, Vector3] = {}
    for sample in samples:
        for target, vector in sample.filtered_by_target_n.items():
            if target not in filtered or math.hypot(*vector) > math.hypot(*filtered[target]):
                filtered[target] = vector
    filtered_max = max((math.hypot(*v) for v in filtered.values()), default=0.0)
    net_vectors = [v for sample in samples for v in sample.net_vectors_n]
    net_vector = max(net_vectors, key=lambda v: math.hypot(*v), default=None)
    net_max = 0.0 if net_vector is None else math.hypot(*net_vector)
    threshold = contact_contract.CONTACT_FORCE_THRESHOLD_N
    positive = max(filtered_max, net_max) > threshold
    available = bool(reads) and not errors and positive
    force_payload = filtered if available and filtered_max > threshold else None
    net_payload = net_vector if available and force_payload is None else None
    status = ('read_failed' if errors or not reads else
              'positive_force_read' if positive else
              'read_success_contact_coverage_unverified')
    return contact_contract.build_contact_record(
        step=step, time_s=time_s,
        sensor_available=available, sensor_status=status,
        event_available=available, event=True if available else None,
        prim_attributions=list(filtered) if force_payload else [],
        force_per_prim_n=force_payload, net_force_n=net_payload,
        force_window_s=sample_dt_s if available else None,
        geometry=geometry,
        notes=('event_basis=force_threshold_inference; '
               'sample_basis=last_physics_step; negative_coverage=unverified; '
               'read_errors=' + repr(errors)))


def episode_contact_verdict(records: Sequence[dict], *, mode: str) -> dict:
    """Do not upgrade a diagnostic probe into closed-loop replay evidence."""
    if mode not in ('wall', 'obstacle', 'clearance', 'geometry', 'replay'):
        raise ValueError('unsupported controlled contact mode')
    contact_contract.summarize_contact_records(records)  # Validate inputs.
    classes = {r['classification'] for r in records}
    if contact_contract.CLASS_CONTACT_FORCE_MEASURED in classes:
        physical = 'PHYSX_CONTACT_FORCE_MEASURED'
    elif contact_contract.CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED in classes:
        physical = 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
    else:
        return {'physical_outcome': 'UNKNOWN', 'outcome': 'UNDECIDABLE',
                'reason': 'CONTACT_COVERAGE_UNVERIFIED'}
    if mode == 'replay':
        return {'physical_outcome': physical, 'outcome': 'UNDECIDABLE',
                'reason': 'GEOMETRY_PROBE_IS_NOT_CLOSED_LOOP_REPLAY'}
    expected = mode in ('wall', 'obstacle')
    return {'physical_outcome': physical,
            'outcome': 'SUCCESS' if expected else 'FAIL',
            'reason': 'PHYSX_CONTACT' if expected else 'UNEXPECTED_CONTACT'}
