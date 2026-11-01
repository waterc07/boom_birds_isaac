"""Tests for simulated clocks/event queue and envelope requirements."""
import pytest
from boom_birds.evaluation.dual_clock import SimClock, SimMapping, EventQueue
from boom_birds.evaluation.envelope import Envelope, StopRequirement

def test_sim_clock_offset_and_drift():
    clock = SimClock('camera', offset_ns=1_000_000, drift_ppm=100.0)
    assert clock.read_ns(0) == 1_000_000
    assert clock.read_ns(10_000_000) == 11_001_000

def test_mapping_validity_and_uncertainty():
    mapping = SimMapping('camera', 'host', 100, 10, 3, 0, 1000)
    assert mapping.usable(500, 3) and not mapping.usable(500, 2)
    assert mapping.usable(1001, 3) is False
    assert mapping.map_uncertainty_ns() == 110

def test_event_queue_delay_reorder_duplicate_clear():
    q = EventQueue()
    q.push(20, {'id': 'late'})
    q.push(5, {'id': 'early'})
    q.push(5, {'id': 'duplicate'}, duplicate_of='early')
    assert [e.payload['payload']['id'] for e in q.pop_due(10)] == ['early', 'duplicate']
    assert q.pending() == 1
    assert q.clear() == 1 and q.pending() == 0

def test_envelope_center_to_gap():
    body = Envelope((0.25, 0.2, 0.1), 'body')
    obstacle = Envelope((0.2, 0.2, 0.3), 'obstacle')
    assert body.conservative_radius_m() == 0.25
    assert body.sphere_gap_m(1.0, obstacle) == pytest.approx(0.45)

def test_stop_requirement_no_double_counting():
    req = StopRequirement(0.585, 0.85, 0.15, 0.1, 0.05, 0.05, 0.45, 0.2)
    assert req.reaction_distance_m() == pytest.approx(0.2975)
    assert req.required_center_distance_m() == pytest.approx(1.5325)

def test_requirement_terms_are_additive():
    base = StopRequirement(0.5, 0.5, 0.1, 0.1, 0.1, 0.1, 0.4, 0.1)
    more_latency = StopRequirement(0.5, 0.5, 0.2, 0.1, 0.1, 0.1, 0.4, 0.1)
    assert more_latency.required_center_distance_m() - base.required_center_distance_m() == pytest.approx(0.05)