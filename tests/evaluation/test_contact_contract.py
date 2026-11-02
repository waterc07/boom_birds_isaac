"""Tests for the layered contact-evidence contract (boom_birds.contact_evidence.v2).

The contract keeps four PhysX/geometry evidence layers strictly separate and
makes "sensor invalid" distinguishable from "valid zero output":

* ``PHYSX_CONTACT_EVENT``    - a PhysX contact event was observed.
* ``PHYSX_CONTACT_FORCE``    - a PhysX force / net force magnitude was measured.
* ``PHYSX_CONTACT_IMPULSE``  - a PhysX impulse (N*s) was measured.
* ``GEOMETRY_OVERLAP``       - a sphere overlap was inferred; never a contact.

These tests are failing-first: they pin the public field contract, the
classification precedence, the attribution rules (attributed vs unattributed
force vs fabricated prim paths) and the episode summary before the
implementation exists.
"""
import math

import pytest

from boom_birds.evaluation import contact_contract


SCHEMA_ID = 'boom_birds.contact_evidence.v2'
THRESHOLD = 0.02
OBSTACLE = '/World/envs/env_0/Obstacle'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _record(**overrides):
    """Build a baseline measured-contact record with sensible defaults."""
    kwargs = dict(
        step=0,
        time_s=0.1,
        sensor_available=True,
        sensor_status='available',
        event_available=True,
        event=True,
        prim_attributions=[OBSTACLE],
        force_per_prim_n={OBSTACLE: [0.03, 0.0, 0.0]},
        force_window_s=0.05,
        impulse_available=False,
        impulse_ns=None,
        geometry=None,
        notes=None,
    )
    kwargs.update(overrides)
    return contact_contract.build_contact_record(**kwargs)


def _upright_record(**overrides):
    """Measured but unattributed net-force contact record."""
    kwargs = dict(
        step=3,
        time_s=0.3,
        sensor_available=True,
        sensor_status='filtered_unavailable_net_force_available',
        event_available=True,
        event=True,
        prim_attributions=[],
        force_per_prim_n=None,
        net_force_n=[0.04, 0.0, 0.0],
        force_window_s=0.05,
        notes='filtered contact sensor unsupported on obstacle child prims',
    )
    kwargs.update(overrides)
    return contact_contract.build_contact_record(**kwargs)


def _errors(record):
    return contact_contract.validate_contact_record(record)


# ---------------------------------------------------------------------------
# constants and schema
# ---------------------------------------------------------------------------

def test_schema_constants_are_pinned():
    assert contact_contract.CONTACT_EVIDENCE_SCHEMA_ID == SCHEMA_ID
    assert contact_contract.LAYER_PHYSX_CONTACT_EVENT == 'PHYSX_CONTACT_EVENT'
    assert contact_contract.LAYER_PHYSX_CONTACT_FORCE == 'PHYSX_CONTACT_FORCE'
    assert contact_contract.LAYER_PHYSX_CONTACT_IMPULSE \
        == 'PHYSX_CONTACT_IMPULSE'
    assert contact_contract.LAYER_GEOMETRY_OVERLAP == 'GEOMETRY_OVERLAP'
    assert contact_contract.LAYER_UNKNOWN == 'UNKNOWN'
    assert contact_contract.FORCE_UNIT == 'N'
    assert contact_contract.IMPULSE_UNIT == 'N*s'
    assert contact_contract.CONTACT_FORCE_THRESHOLD_N == pytest.approx(0.02)
    assert contact_contract.CONTACT_FORCE_THRESHOLD_N == THRESHOLD


def test_build_record_has_full_layered_structure():
    record = _record()
    assert record['schema_version'] == SCHEMA_ID
    assert record['step'] == 0
    assert record['time_s'] == pytest.approx(0.1)
    assert record['sensor'] == {'available': True, 'status': 'available'}
    sampling = record['sampling']
    assert sampling['window_s'] == pytest.approx(0.05)
    assert sampling['source'] == 'policy_step_aggregated_physx_contact'
    assert sampling['aggregation'] == 'max_over_window'
    layers = record['layers']
    assert set(layers) >= {'event', 'force', 'impulse', 'geometry',
                           'attribution'}
    assert layers['event']['layer'] == 'PHYSX_CONTACT_EVENT'
    assert layers['force']['layer'] == 'PHYSX_CONTACT_FORCE'
    assert layers['impulse']['layer'] == 'PHYSX_CONTACT_IMPULSE'
    assert layers['geometry']['layer'] == 'GEOMETRY_OVERLAP'
    assert layers['force']['unit'] == 'N'
    assert layers['impulse']['unit'] == 'N*s'
    assert layers['geometry']['inference'] == 'sphere_overlap_only'
    assert record['classification'] == 'CONTACT_FORCE_MEASURED'
    assert record['validity']['valid'] is True
    assert record['validity']['reasons'] == []
    assert record['unknown_reasons'] == []
    assert _errors(record) == []


# ---------------------------------------------------------------------------
# measured force (attributed)
# ---------------------------------------------------------------------------

def test_attributed_force_measured_keeps_per_prim_vectors_and_raw_magnitude():
    record = _record()
    force = record['layers']['force']
    assert force['available'] is True
    assert force['basis'] == 'filtered_force'
    assert force['per_prim_n'] == {
        OBSTACLE: pytest.approx([0.03, 0.0, 0.0]),
    }
    assert force['magnitude_n'] == pytest.approx(0.03)
    attribution = record['layers']['attribution']
    assert attribution['status'] == 'ATTRIBUTED'
    assert attribution['method'] == 'contact_sensor_filter'
    assert attribution['prim_paths'] == [OBSTACLE]
    assert record['layers']['event']['source'] == \
        'physx_contact_sensor_filtered'
    assert record['layers']['event']['force_basis'] == 'filtered_force'
    assert record['layers']['event']['prim_attributions'] == [OBSTACLE]
    assert record['layers']['event']['contact_count'] == 1


def test_force_magnitude_is_max_per_prim_vector_norm_and_raw_value_is_kept():
    a = '/World/envs/env_0/Robot/a'
    b = '/World/envs/env_0/Robot/b'
    record = _record(force_per_prim_n={a: [3.0, 4.0, 0.0],   # norm 5.0
                                       b: [0.0, 0.0, 0.5]},  # norm 0.5
                     prim_attributions=[a, b])
    force = record['layers']['force']
    assert force['magnitude_n'] == pytest.approx(5.0)
    assert force['magnitude_n'] > THRESHOLD
    assert record['classification'] == 'CONTACT_FORCE_MEASURED'
    assert record['layers']['event']['contact_count'] == 2
    # Threshold is only a decision rule; it never rewrites the raw magnitude.
    assert force['magnitude_n'] == pytest.approx(5.0)


def test_event_and_geometry_overlap_coexist_without_promoting_geometry():
    record = _record(geometry={'sphere_overlap_m': 0.08})
    assert record['layers']['geometry']['available'] is True
    assert record['layers']['geometry']['sphere_overlap_m'] == pytest.approx(
        0.08)
    assert record['layers']['geometry']['inference'] == 'sphere_overlap_only'
    # Both an event and geometry overlap are present; force still wins.
    assert record['classification'] == 'CONTACT_FORCE_MEASURED'
    # Geometry is a layer of its own, not a PhysX event/force substitute.
    assert record['layers']['event']['event'] is True
    assert record['layers']['force']['available'] is True


# ---------------------------------------------------------------------------
# event-only
# ---------------------------------------------------------------------------

def test_event_true_but_force_unavailable_is_event_only_and_force_is_none():
    record = _record(force_per_prim_n=None, prim_attributions=[])
    force = record['layers']['force']
    assert force['available'] is False
    assert force['per_prim_n'] is None
    assert force['magnitude_n'] is None            # never faked as 0
    assert force['basis'] == 'none'
    assert record['classification'] == 'CONTACT_EVENT_ONLY'
    assert record['layers']['event']['event'] is True
    assert record['layers']['event']['source'] == \
        'physx_contact_sensor_unfiltered'
    assert record['layers']['attribution']['status'] == 'UNATTRIBUTED'
    assert record['layers']['attribution']['method'] == 'none'
    assert record['validity']['valid'] is True
    assert _errors(record) == []


def test_event_only_with_attributed_prims_stays_event_only():
    record = _record(force_per_prim_n=None, prim_attributions=[OBSTACLE])
    assert record['layers']['attribution']['status'] == 'ATTRIBUTED'
    assert record['layers']['attribution']['prim_paths'] == [OBSTACLE]
    assert record['layers']['force']['magnitude_n'] is None
    assert record['classification'] == 'CONTACT_EVENT_ONLY'
    assert record['layers']['event']['source'] == \
        'physx_contact_sensor_filtered'


# ---------------------------------------------------------------------------
# sensor invalid vs valid zero
# ---------------------------------------------------------------------------

def test_sensor_unavailable_is_unknown_and_never_no_contact_from_zero():
    record = contact_contract.build_contact_record(
        step=1,
        time_s=0.2,
        sensor_available=False,
        sensor_status='contact_filter_unsupported',
        event_available=False,
        event=None,
        prim_attributions=[],
        force_per_prim_n=None,
        net_force_n=None,
        geometry=None,
    )
    assert record['classification'] == 'UNKNOWN'
    assert record['sensor']['available'] is False
    assert record['sensor']['status'] == 'contact_filter_unsupported'
    assert record['layers']['event']['available'] is False
    assert record['layers']['event']['event'] is None
    assert record['layers']['force']['available'] is False
    assert record['layers']['force']['magnitude_n'] is None
    assert record['validity']['valid'] is False
    assert 'SENSOR_UNAVAILABLE' in record['unknown_reasons']
    assert 'EVENT_UNAVAILABLE' in record['unknown_reasons']
    assert record['classification'] != 'NO_CONTACT'


def test_valid_zero_output_is_no_contact_and_force_zero_is_explicit():
    record = _record(
        event=False,
        prim_attributions=[],
        force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]},
    )
    force = record['layers']['force']
    assert record['sensor']['available'] is True
    assert record['layers']['event']['event'] is False
    assert force['available'] is True
    assert force['magnitude_n'] == pytest.approx(0.0)
    assert force['per_prim_n'] is not None
    assert record['classification'] == 'NO_CONTACT'
    assert record['layers']['attribution']['status'] == 'ATTRIBUTED'
    assert record['validity']['valid'] is True
    assert record['unknown_reasons'] == []
    assert _errors(record) == []


def test_valid_zero_net_force_is_no_contact_but_unattributed():
    record = contact_contract.build_contact_record(
        step=2, time_s=0.2,
        sensor_available=True,
        sensor_status='filtered_unavailable_net_force_available',
        event_available=True,
        event=False,
        prim_attributions=[],
        force_per_prim_n=None,
        net_force_n=0.0,
        geometry=None,
    )
    assert record['classification'] == 'NO_CONTACT'
    assert record['layers']['force']['available'] is True
    assert record['layers']['force']['basis'] == 'net_force'
    assert record['layers']['force']['magnitude_n'] == pytest.approx(0.0)
    assert record['layers']['force']['per_prim_n'] is None
    assert record['layers']['attribution']['status'] == 'UNATTRIBUTED'


def test_invalid_and_valid_zero_are_distinguishable():
    invalid = contact_contract.build_contact_record(
        step=0, time_s=0.1,
        sensor_available=False, sensor_status='unavailable',
        event_available=False, event=None, prim_attributions=[])
    valid_zero = _record(
        event=False, prim_attributions=[],
        force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]})
    assert invalid['layers']['force']['magnitude_n'] is None
    assert valid_zero['layers']['force']['magnitude_n'] == pytest.approx(0.0)
    assert invalid['classification'] == 'UNKNOWN'
    assert valid_zero['classification'] == 'NO_CONTACT'


# ---------------------------------------------------------------------------
# geometry only
# ---------------------------------------------------------------------------

def test_geometry_overlap_only_is_not_a_physx_contact():
    record = _record(event=False, prim_attributions=[],
                     force_per_prim_n=None,
                     geometry={'sphere_overlap_m': 0.05})
    assert record['classification'] == 'GEOMETRY_OVERLAP_ONLY'
    assert record['layers']['geometry']['available'] is True
    assert record['layers']['geometry']['sphere_overlap_m'] == pytest.approx(
        0.05)
    assert record['layers']['event']['available'] is True
    assert record['layers']['event']['event'] is False
    assert record['layers']['force']['available'] is False
    assert record['layers']['force']['basis'] == 'none'
    assert record['layers']['event']['source'] == \
        'physx_contact_sensor_unfiltered'
    assert record['validity']['valid'] is True
    assert _errors(record) == []


def test_geometry_accepts_bare_overlap_number_and_negative_gap():
    overlapping = _record(event=False, prim_attributions=[],
                          force_per_prim_n=None, geometry=0.03)
    separated = _record(event=False, prim_attributions=[],
                        force_per_prim_n=None, geometry=-0.03)
    assert overlapping['layers']['geometry']['sphere_overlap_m'] \
        == pytest.approx(0.03)
    assert overlapping['classification'] == 'GEOMETRY_OVERLAP_ONLY'
    assert separated['layers']['geometry']['available'] is True
    assert separated['classification'] == 'NO_CONTACT'


# ---------------------------------------------------------------------------
# threshold boundary
# ---------------------------------------------------------------------------

def test_threshold_boundary_is_strictly_greater_than_two_hundredths():
    at = _record(event=False, prim_attributions=[],
                 force_per_prim_n={OBSTACLE: [THRESHOLD, 0.0, 0.0]})
    above = _record(prim_attributions=[OBSTACLE],
                    force_per_prim_n={OBSTACLE:
                                      [THRESHOLD + 1e-6, 0.0, 0.0]})
    assert at['layers']['force']['magnitude_n'] == pytest.approx(THRESHOLD)
    assert at['classification'] == 'NO_CONTACT'
    assert above['classification'] == 'CONTACT_FORCE_MEASURED'


def test_threshold_boundary_at_threshold_with_event_true_is_event_only():
    record = _record(event=True, prim_attributions=[],
                     force_per_prim_n={OBSTACLE: [THRESHOLD, 0.0, 0.0]})
    assert record['layers']['force']['magnitude_n'] == pytest.approx(THRESHOLD)
    assert record['classification'] == 'CONTACT_EVENT_ONLY'


# ---------------------------------------------------------------------------
# unattributed (net-force) path
# ---------------------------------------------------------------------------

def test_unattributed_net_force_is_measured_unattributed():
    record = _upright_record()
    assert record['classification'] == 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
    force = record['layers']['force']
    assert force['available'] is True
    assert force['basis'] == 'net_force'
    assert force['per_prim_n'] is None            # net is never per-prim
    assert force['magnitude_n'] == pytest.approx(0.04)
    assert force['unit'] == 'N'
    assert record['layers']['event']['source'] == \
        'physx_contact_sensor_unfiltered'
    assert record['layers']['event']['force_basis'] == 'net_force'
    assert record['layers']['event']['prim_attributions'] == []
    attribution = record['layers']['attribution']
    assert attribution['status'] == 'UNATTRIBUTED'
    assert attribution['prim_paths'] == []
    assert attribution['method'] == 'none'
    assert record['validity']['valid'] is True
    assert _errors(record) == []


def test_unattributed_net_force_below_threshold_is_no_contact():
    # With no filter the net force is the event channel, so a sub-threshold
    # reading means "no contact event" rather than a separate event-only step.
    record = _upright_record(net_force_n=[0.01, 0.0, 0.0], event=False)
    assert record['layers']['force']['magnitude_n'] == pytest.approx(0.01)
    assert record['classification'] == 'NO_CONTACT'
    assert record['layers']['event']['force_basis'] == 'net_force'


def test_unattributed_net_force_event_must_match_the_threshold():
    with pytest.raises(ValueError):
        _upright_record(net_force_n=[0.01, 0.0, 0.0], event=True)
    with pytest.raises(ValueError):
        _upright_record(net_force_n=[0.04, 0.0, 0.0], event=False)


def test_filtered_force_above_threshold_cannot_report_event_false():
    with pytest.raises(ValueError):
        _record(event=False, prim_attributions=[OBSTACLE],
                force_per_prim_n={OBSTACLE: [0.03, 0.0, 0.0]})


def test_unattributed_net_force_with_proximity_method_is_allowed():
    record = _upright_record(
        attribution_method='net_force_plus_proximity',
        geometry={'sphere_overlap_m': 0.02},
        attribution_notes='proximity candidate only; prim identity unknown')
    attribution = record['layers']['attribution']
    assert attribution['status'] == 'UNATTRIBUTED'
    assert attribution['method'] == 'net_force_plus_proximity'
    assert attribution['prim_paths'] == []
    assert record['classification'] == 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
    assert _errors(record) == []


def test_measured_contact_requires_attributed_status():
    attributed = _record()
    unattributed = _upright_record()
    assert attributed['layers']['attribution']['status'] == 'ATTRIBUTED'
    assert attributed['classification'] == 'CONTACT_FORCE_MEASURED'
    assert unattributed['layers']['attribution']['status'] == 'UNATTRIBUTED'
    assert unattributed['classification'] == \
        'CONTACT_FORCE_MEASURED_UNATTRIBUTED'


# ---------------------------------------------------------------------------
# attribution integrity: never fabricate prim names
# ---------------------------------------------------------------------------

def test_unattributed_status_with_fabricated_prim_paths_is_rejected():
    bad = _upright_record()
    bad['layers']['attribution']['prim_paths'] = [OBSTACLE]
    errors = _errors(bad)
    assert any('FABRICATED_ATTRIBUTION' in error for error in errors)


def test_unattributed_status_with_event_prim_attributions_is_rejected():
    bad = _upright_record()
    bad['layers']['event']['prim_attributions'] = [OBSTACLE]
    errors = _errors(bad)
    assert any('FABRICATED_ATTRIBUTION' in error for error in errors)


def test_net_force_basis_cannot_carry_per_prim_force():
    bad = _upright_record()
    bad['layers']['force']['per_prim_n'] = {OBSTACLE: [0.04, 0.0, 0.0]}
    errors = _errors(bad)
    assert any('FORCE_LAYER_INVALID' in error for error in errors)


def test_attributed_force_with_net_basis_is_rejected():
    bad = _record()
    bad['layers']['force']['basis'] = 'net_force'
    bad['layers']['event']['force_basis'] = 'net_force'
    errors = _errors(bad)
    assert any('ATTRIBUTION_INVALID' in error
               or 'FORCE_LAYER_INVALID' in error
               or 'INCONSISTENT_EVENT' in error
               for error in errors)


def test_force_per_prim_without_named_prim_attributions_is_rejected():
    with pytest.raises(ValueError):
        contact_contract.build_contact_record(
            step=0, time_s=0.1,
            sensor_available=True, sensor_status='available',
            event_available=True, event=True, prim_attributions=[],
            force_per_prim_n={OBSTACLE: [0.5, 0.0, 0.0]},
        )


# ---------------------------------------------------------------------------
# impulse unit / no force substitution
# ---------------------------------------------------------------------------

def test_impulse_is_never_used_as_force_or_no_contact():
    record = _record(event=True, force_per_prim_n=None, prim_attributions=[],
                     impulse_available=True,
                     impulse_ns={OBSTACLE: [0.5, 0.0, 0.0]})
    impulse = record['layers']['impulse']
    assert impulse['available'] is True
    assert impulse['unit'] == 'N*s'
    assert impulse['per_prim_ns'] == {
        OBSTACLE: pytest.approx([0.5, 0.0, 0.0])}
    assert record['layers']['force']['available'] is False
    assert record['layers']['force']['magnitude_n'] is None
    # An impulse is not a force and cannot produce NO_CONTACT either.
    assert record['classification'] == 'CONTACT_EVENT_ONLY'
    assert _errors(record) == []


def test_impulse_unit_swap_is_rejected():
    bad = _record()
    bad['layers']['impulse']['unit'] = 'N'
    assert any('IMPULSE_UNIT_INVALID' in error for error in _errors(bad))
    bad_force = _record()
    bad_force['layers']['force']['unit'] = 'N*s'
    assert any('FORCE_UNIT_INVALID' in error for error in _errors(bad_force))


def test_impulse_available_without_value_is_rejected():
    with pytest.raises(ValueError):
        contact_contract.build_contact_record(
            step=0, time_s=0.1,
            sensor_available=True, sensor_status='available',
            event_available=True, event=True, prim_attributions=[],
            impulse_available=True, impulse_ns=None)
    with pytest.raises(ValueError):
        contact_contract.build_contact_record(
            step=0, time_s=0.1,
            sensor_available=True, sensor_status='available',
            event_available=True, event=True, prim_attributions=[],
            impulse_available=True, impulse_ns={})


# ---------------------------------------------------------------------------
# force input rejection (negative magnitude / NaN)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_net_force', [-0.5, float('nan'),
                                           float('inf')])
def test_negative_or_non_finite_net_force_is_rejected(bad_net_force):
    with pytest.raises(ValueError):
        _upright_record(net_force_n=bad_net_force)


def test_nan_force_component_is_rejected():
    with pytest.raises(ValueError):
        _record(force_per_prim_n={OBSTACLE: [float('nan'), 0.0, 0.0]})


def test_negative_force_component_is_physical_and_allowed():
    record = _record(force_per_prim_n={OBSTACLE: [-0.03, 0.0, 0.0]})
    assert record['layers']['force']['magnitude_n'] == pytest.approx(0.03)
    assert record['classification'] == 'CONTACT_FORCE_MEASURED'


def test_sensor_unavailable_ignores_zero_event_input():
    with pytest.raises(ValueError):
        contact_contract.build_contact_record(
            step=0, time_s=0.1,
            sensor_available=False, sensor_status='unavailable',
            event_available=False, event=False, prim_attributions=[])


# ---------------------------------------------------------------------------
# validation function: errors list, bad records flagged
# ---------------------------------------------------------------------------

def test_validate_returns_empty_list_for_valid_record():
    assert contact_contract.validate_contact_record(_record()) == []


def test_validate_rejects_non_mapping_and_wrong_schema():
    assert 'NOT_A_MAPPING' in contact_contract.validate_contact_record(None)
    bad = _record()
    bad['schema_version'] = 'boom_birds.contact_evidence.v1'
    assert any('SCHEMA_VERSION_INVALID' in error for error in _errors(bad))


def test_validate_detects_tampered_classification():
    bad = _record()
    bad['classification'] = 'NO_CONTACT'
    assert any('INCONSISTENT_CLASSIFICATION' in error for error in _errors(bad))


def test_validate_detects_negative_handcrafted_magnitude():
    bad = _record()
    bad['layers']['force']['magnitude_n'] = -1.0
    assert any('FORCE_NEGATIVE' in error for error in _errors(bad))


def test_validate_detects_geometry_promoted_to_event():
    bad = _record(event=False, prim_attributions=[], force_per_prim_n=None,
                  geometry={'sphere_overlap_m': 0.05})
    bad['layers']['event']['event'] = True
    errors = _errors(bad)
    assert any('INCONSISTENT_CLASSIFICATION' in error for error in errors)


def test_validate_detects_unknown_record_with_no_unknown_reasons():
    bad = contact_contract.build_contact_record(
        step=0, time_s=0.1,
        sensor_available=False, sensor_status='unavailable',
        event_available=False, event=None, prim_attributions=[])
    bad['unknown_reasons'] = []
    bad['validity'] = {'valid': False, 'reasons': []}
    assert any('UNKNOWN_REASONS_INVALID' in error for error in _errors(bad))


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def _summary_records():
    measured = _record(step=0, time_s=0.1)
    unattributed = _upright_record(step=1, time_s=0.2)
    event_only = _record(step=2, time_s=0.3, event=True,
                         prim_attributions=[], force_per_prim_n=None)
    geometry = _record(step=3, time_s=0.4, event=False,
                       prim_attributions=[], force_per_prim_n=None,
                       geometry={'sphere_overlap_m': 0.05})
    no_contact = _record(step=4, time_s=0.5, event=False,
                         prim_attributions=[],
                         force_per_prim_n={OBSTACLE: [0.0, 0.0, 0.0]})
    unknown = contact_contract.build_contact_record(
        step=5, time_s=0.6,
        sensor_available=False, sensor_status='unavailable',
        event_available=False, event=None, prim_attributions=[])
    return [measured, unattributed, event_only, geometry, no_contact, unknown]


def test_summarize_counts_classifications_and_force_statistics():
    summary = contact_contract.summarize_contact_records(_summary_records())
    assert summary['total_steps'] == 6
    counts = summary['classification_counts']
    assert counts['CONTACT_FORCE_MEASURED'] == 1
    assert counts['CONTACT_FORCE_MEASURED_UNATTRIBUTED'] == 1
    assert counts['CONTACT_EVENT_ONLY'] == 1
    assert counts['GEOMETRY_OVERLAP_ONLY'] == 1
    assert counts['NO_CONTACT'] == 1
    assert counts['UNKNOWN'] == 1
    # 0.03 attributed, 0.04 net, 0.0 valid zero -> 3 force-available steps.
    assert summary['max_force_n'] == pytest.approx(0.04)
    assert summary['first_force_contact_time_s'] == pytest.approx(0.1)
    assert summary['unknown_steps'] == 1
    assert summary['geometry_only_steps'] == 1
    assert summary['force_available_ratio'] == pytest.approx(3 / 6)


def test_summarize_counts_unknown_reasons_and_attribution():
    summary = contact_contract.summarize_contact_records(_summary_records())
    assert summary['unknown_reasons']['SENSOR_UNAVAILABLE'] == 1
    assert summary['unknown_reasons']['EVENT_UNAVAILABLE'] == 1
    assert summary['attributed_steps'] == 2   # measured + valid-zero
    assert summary['unattributed_steps'] == 3  # net force + event only + geom
    assert summary['attribution_status_counts']['ATTRIBUTED'] == 2
    assert summary['attribution_status_counts']['UNATTRIBUTED'] == 3
    assert summary['attribution_status_counts']['UNKNOWN'] == 1


def test_summarize_first_force_contact_time_is_none_without_force_contact():
    records = _summary_records()[2:]  # event-only, geometry, no-contact, unknown
    summary = contact_contract.summarize_contact_records(records)
    assert summary['first_force_contact_time_s'] is None
    assert summary['max_force_n'] == pytest.approx(0.0)  # valid-zero only
    assert summary['force_available_ratio'] == pytest.approx(1 / 4)


def test_summarize_rejects_empty_records():
    with pytest.raises(ValueError):
        contact_contract.summarize_contact_records([])


# ---------------------------------------------------------------------------
# classify_contact recomputes from layers (not a stored echo)
# ---------------------------------------------------------------------------

def test_classify_contact_recomputes_from_layers():
    record = _record(event=False, prim_attributions=[],
                     force_per_prim_n=None,
                     geometry={'sphere_overlap_m': 0.05})
    record['classification'] = 'CONTACT_FORCE_MEASURED'  # tampered
    assert contact_contract.classify_contact(record) == 'GEOMETRY_OVERLAP_ONLY'


def test_classify_contact_returns_unknown_when_event_unavailable():
    record = contact_contract.build_contact_record(
        step=0, time_s=0.1,
        sensor_available=True, sensor_status='available',
        event_available=False, event=None, prim_attributions=[],
        force_per_prim_n=None, geometry={'sphere_overlap_m': 0.05})
    assert record['classification'] == 'UNKNOWN'
    assert contact_contract.classify_contact(record) == 'UNKNOWN'
    assert 'EVENT_UNAVAILABLE' in record['unknown_reasons']
