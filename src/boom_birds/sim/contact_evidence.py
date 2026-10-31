"""PhysX contact evidence for obstacle collisions (force threshold)."""
import math
from dataclasses import dataclass

DEFAULT_CONTACT_THRESHOLD_N = 0.02


def _triple(values, name):
    try:
        converted = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError(name + ' must contain three numbers')
    if len(converted) != 3 or any(not math.isfinite(value) for value in converted):
        raise ValueError(name + ' must contain three finite values')
    return converted


@dataclass(frozen=True)
class ContactEvidence:
    contact: bool
    force_n: float
    per_obstacle_force_n: dict
    contacting_obstacles: tuple
    step: int | None = None


def contact_evidence_from_forces(forces, *, threshold_n=DEFAULT_CONTACT_THRESHOLD_N,
                                 step=None):
    """Forces is a mapping from obstacle name to world-frame force (N)."""
    if not isinstance(threshold_n, (int, float)) or isinstance(threshold_n, bool) \
            or not math.isfinite(threshold_n) or threshold_n < 0:
        raise ValueError('threshold_n must be a nonnegative finite number')
    per_obstacle = {}
    for name, values in forces.items():
        if not isinstance(name, str) or not name:
            raise ValueError('obstacle names must be nonempty strings')
        vector = _triple(values, 'force for ' + name)
        per_obstacle[name] = math.sqrt(sum(value * value for value in vector))
    contacting = tuple(sorted(name for name, magnitude in per_obstacle.items()
                              if magnitude >= threshold_n))
    return ContactEvidence(
        contact=bool(contacting),
        force_n=max(per_obstacle.values(), default=0.0),
        per_obstacle_force_n=per_obstacle,
        contacting_obstacles=contacting,
        step=step)

def restrict_contact_evidence(evidence, allowed_names):
    """Keep only contacts whose assets are geometrically near the robot.

    This is an attribution gate, not a collision substitute: the contact
    decision still comes from PhysX forces. Stale contact reports from a body
    that has been teleported away are discarded.
    """
    if not isinstance(evidence, ContactEvidence):
        raise ValueError('evidence must be a ContactEvidence')
    allowed = {name for name in allowed_names if isinstance(name, str)}
    kept = {name: magnitude for name, magnitude in evidence.per_obstacle_force_n.items()
            if name in allowed}
    contacting = tuple(sorted(name for name, magnitude in kept.items()
                              if magnitude >= DEFAULT_CONTACT_THRESHOLD_N))
    return ContactEvidence(
        contact=bool(contacting),
        force_n=max(kept.values(), default=0.0),
        per_obstacle_force_n=kept,
        contacting_obstacles=contacting,
        step=evidence.step)
