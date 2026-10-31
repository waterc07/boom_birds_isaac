"""Fault injection helpers: flags, timeout override, observation-layer NaN."""
import math

import pytest

from boom_birds.sim.faults import (
    COLLISION_CONTACT,
    COLLISION_FLAG,
    FAULT_NONE,
    INVALID_OBSERVATION,
    TIMEOUT,
    FaultSpec,
    apply_observation_fault,
    collision_flag,
    effective_timeout_s,
)


def test_fault_spec_validation():
    assert FaultSpec().kind == FAULT_NONE
    for kind in (COLLISION_FLAG, COLLISION_CONTACT, TIMEOUT, INVALID_OBSERVATION):
        assert FaultSpec(kind, step=3).kind == kind
    with pytest.raises(ValueError):
        FaultSpec('earthquake')
    with pytest.raises(ValueError):
        FaultSpec(INVALID_OBSERVATION, step=-1)
    with pytest.raises(ValueError):
        FaultSpec(TIMEOUT, timeout_s=0.0)


def test_collision_flag_only_fires_on_its_step():
    fault = FaultSpec(COLLISION_FLAG, step=5)
    assert not collision_flag(fault, 4)
    assert collision_flag(fault, 5)
    assert not collision_flag(fault, 6)
    assert not collision_flag(FaultSpec(COLLISION_CONTACT, step=5), 5)


def test_invalid_observation_injects_nan_without_touching_physics_values():
    fault = FaultSpec(INVALID_OBSERVATION, step=2)
    position = (1.0, 2.0, 0.75)
    velocity = (0.1, 0.0, 0.0)
    quat = (1.0, 0.0, 0.0, 0.0)
    before = (position, velocity, quat)
    out_position, out_velocity, out_quat = apply_observation_fault(
        position, velocity, quat, fault, 1)
    assert (out_position, out_velocity, out_quat) == before
    bad_position, _v, _q = apply_observation_fault(position, velocity, quat, fault, 2)
    assert any(math.isnan(value) for value in bad_position)
    assert (position, velocity, quat) == before
    assert not any(math.isnan(value) for value in position)


def test_timeout_override_only_for_timeout_fault():
    assert effective_timeout_s(20.0, FaultSpec()) == 20.0
    assert effective_timeout_s(20.0, FaultSpec(TIMEOUT, timeout_s=1.0)) == 1.0
    assert effective_timeout_s(20.0, FaultSpec(COLLISION_FLAG)) == 20.0
