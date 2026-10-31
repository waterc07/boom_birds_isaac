"""Fault-injection helpers; injection never writes to PhysX state."""
from dataclasses import dataclass

FAULT_NONE = 'none'
COLLISION_FLAG = 'collision_flag'
COLLISION_CONTACT = 'collision_contact'
TIMEOUT = 'timeout'
INVALID_OBSERVATION = 'invalid_observation'
FAULT_KINDS = (FAULT_NONE, COLLISION_FLAG, COLLISION_CONTACT, TIMEOUT,
               INVALID_OBSERVATION)


@dataclass(frozen=True)
class FaultSpec:
    kind: str = FAULT_NONE
    step: int = 0
    timeout_s: float | None = None

    def __post_init__(self):
        if self.kind not in FAULT_KINDS:
            raise ValueError('unsupported fault kind: ' + str(self.kind))
        if not isinstance(self.step, int) or isinstance(self.step, bool) or self.step < 0:
            raise ValueError('fault step must be a nonnegative integer')
        if self.timeout_s is not None:
            if (not isinstance(self.timeout_s, (int, float))
                    or isinstance(self.timeout_s, bool) or not self.timeout_s > 0):
                raise ValueError('timeout_s must be positive when provided')


def collision_flag(fault, step_index):
    return fault.kind == COLLISION_FLAG and fault.step == step_index


def effective_timeout_s(configured_timeout_s, fault):
    if fault.kind == TIMEOUT:
        return float(fault.timeout_s)
    return float(configured_timeout_s)


def apply_observation_fault(position_world_m, velocity_world_mps, quat_wxyz,
                            fault, step_index):
    """Return observation tuples for this step; the sim state is never mutated."""
    if fault.kind != INVALID_OBSERVATION or fault.step != step_index:
        return position_world_m, velocity_world_mps, quat_wxyz
    broken = list(position_world_m)
    broken[0] = float('nan')
    return tuple(broken), velocity_world_mps, quat_wxyz
