"""Tests for simulated clocks/event queue, mapping age and envelope requirements."""
import pytest
from boom_birds.evaluation.dual_clock import (
    CLOCK_MAPPING_UNUSABLE, EventQueue, SimClock, SimMapping, mapping_age)
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


# --- 2026-11-02 latency envelope: simulated dual clock / mapping age ---

def test_sim_clock_uncertainty_is_absolute():
    assert SimClock('camera', uncertainty_ns=-5).read_uncertainty_ns() == 5
    assert SimClock('camera', uncertainty_ns=7).read_uncertainty_ns() == 7
    assert SimClock('camera').read_uncertainty_ns() == 0

def test_sim_mapping_positional_fields_keep_default_drift():
    mapping = SimMapping('camera', 'host', 100, 10, 3, 0, 1000)
    assert mapping.source_clock_id == 'camera' and mapping.target_clock_id == 'host'
    assert mapping.drift_ppm == 0.0
    assert mapping.map_uncertainty_ns() == 110

def test_mapping_uncertainty_grows_linearly_with_drift_and_reference_time():
    mapping = SimMapping('camera', 'host', 100, 10, 3, 0, 10 ** 18, True, 100.0)
    assert mapping.map_uncertainty_ns() == 110
    assert mapping.map_uncertainty_ns(1_000_000_000) == 110 + 100_000
    assert mapping.map_uncertainty_ns(2_000_000_000) == 110 + 200_000
    # absolute host reference: negative reference must not shrink the bound
    assert mapping.map_uncertainty_ns(-1_000_000_000) == 110 + 100_000
    growth = (mapping.map_uncertainty_ns(2_000_000_000)
              - mapping.map_uncertainty_ns(1_000_000_000))
    assert growth == 100_000

def test_sim_mapping_to_host_is_bounded_inverse_of_clock_read():
    clock = SimClock('camera', offset_ns=1_000_000, drift_ppm=100.0)
    mapping = SimMapping('camera', 'host', 1_000_000, 10, 3, 0, 10 ** 18, True, 100.0)
    host_capture_ns = 10_000_000_000
    clock_ns = clock.read_ns(host_capture_ns)
    # drift actually moves the raw clock reading away from the offset-only estimate
    assert clock_ns - mapping.offset_ns != host_capture_ns
    mapped_host_ns = mapping.to_host_ns(clock_ns)
    assert abs(mapped_host_ns - host_capture_ns) <= mapping.map_uncertainty_ns(host_capture_ns)
    assert mapped_host_ns == pytest.approx(host_capture_ns, abs=2)

def test_mapping_age_point_estimate_and_conservative_bound():
    clock = SimClock('camera', offset_ns=1_000_000, drift_ppm=200.0)
    mapping = SimMapping('camera', 'host', 1_000_000, 5, 2, 0, 10 ** 18, True, 200.0)
    capture_host_ns = 10_000_000_000
    capture_clock_ns = clock.read_ns(capture_host_ns)
    now_ns = 10_150_000_000
    result = mapping_age(capture_clock_ns, now_ns, mapping, 2)
    assert result['valid'] is True
    assert result['reason'] == 'ACCEPT'
    assert result['mapped_host_ns'] == pytest.approx(capture_host_ns, abs=2)
    assert result['age_point_s'] == pytest.approx(0.15, abs=2e-9)
    assert result['error_bound_ns'] == mapping.map_uncertainty_ns(now_ns)
    assert result['error_bound_ns'] > 0
    # mapping error must never shrink the reported age below the point estimate
    assert result['age_bound_s'] >= result['age_point_s']
    assert result['age_bound_s'] == pytest.approx(
        0.15 + result['error_bound_ns'] / 1e9, abs=1e-12)

def test_mapping_age_unusable_returns_reason_and_none_numbers():
    base = dict(source_clock_id='camera', target_clock_id='host', offset_ns=0,
                uncertainty_ns=0, sync_generation=3,
                valid_from_host_ns=0, valid_until_host_ns=1000)
    cases = (
        (SimMapping(**base), 2, 500),               # sync generation mismatch
        (SimMapping(**base), 3, 1001),              # outside validity window
        (SimMapping(**base, valid=False), 3, 500),  # mapping marked invalid
        (None, 3, 500),                             # no mapping at all
    )
    for mapping, sync_generation, now_ns in cases:
        result = mapping_age(500, now_ns, mapping, sync_generation)
        assert result['valid'] is False
        assert result['reason'] == CLOCK_MAPPING_UNUSABLE
        # unknown age is explicit None, never a zero-valued valid reading
        assert result['age_point_s'] is None
        assert result['age_bound_s'] is None
        assert result['mapped_host_ns'] is None
        assert result['error_bound_ns'] is None

def test_mapping_age_negative_age_clamped_and_flagged():
    mapping = SimMapping('camera', 'host', 0, 0, 1, 0, 10 ** 18, True, 0.0)
    result = mapping_age(2_000_000_000, 1_000_000_000, mapping, 1)
    assert result['valid'] is True
    assert 'NEGATIVE_AGE' in result['reason']
    assert result['age_point_s'] == 0.0
    assert result['age_bound_s'] >= result['age_point_s']
    assert result['age_bound_s'] == 0.0
