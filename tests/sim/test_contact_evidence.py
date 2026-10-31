"""PhysX contact evidence thresholds and per-obstacle attribution."""
import math

import pytest

from boom_birds.sim.contact_evidence import contact_evidence_from_forces


def test_below_threshold_is_not_contact():
    evidence = contact_evidence_from_forces({"obs0": (0.001, 0.0, 0.0)})
    assert evidence.contact is False
    assert evidence.force_n == pytest.approx(0.001)
    assert evidence.per_obstacle_force_n["obs0"] == pytest.approx(0.001)


def test_above_threshold_is_contact_and_attributed():
    evidence = contact_evidence_from_forces(
        {"obs0": (0.02, 0.0, 0.0), "obs1": (0.0, 0.03, 0.0)},
        threshold_n=0.02)
    assert evidence.contact is True
    assert evidence.force_n == pytest.approx(0.03)
    assert evidence.per_obstacle_force_n["obs1"] == pytest.approx(0.03)
    assert evidence.contacting_obstacles == ('obs0', 'obs1')


def test_any_single_axis_force_counts():
    evidence = contact_evidence_from_forces({"mover": (0.0, 0.0, -0.05)})
    assert evidence.contact is True


def test_no_forces_means_no_contact():
    evidence = contact_evidence_from_forces({})
    assert evidence.contact is False
    assert evidence.force_n == 0.0
    assert evidence.contacting_obstacles == ()


@pytest.mark.parametrize('forces', [
    {"obs": (math.nan, 0.0, 0.0)}, {"obs": (0.0, math.inf, 0.0)},
    {"obs": (0.0, 0.0)},
])
def test_invalid_force_inputs_rejected(forces):
    with pytest.raises(ValueError):
        contact_evidence_from_forces(forces)
