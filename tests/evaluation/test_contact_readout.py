"""Regression cases for PhysX tensor decoding and failed-read evidence."""
import math
from types import SimpleNamespace

import pytest

from boom_birds.evaluation import contact_readout


TARGET = '/World/Obstacle'


def decode(net=None, matrix=None, targets=(TARGET,)):
    return contact_readout.decode_contact_forces(
        net_forces_w=net, force_matrix_w=matrix, target_paths=targets)


def test_single_filter_preserves_signed_three_vector():
    sample = decode([[[0.03, -0.04, 0.0]]], [[[[0.03, -0.04, 0.0]]]])
    assert sample.filtered_by_target_n[TARGET] == (0.03, -0.04, 0.0)
    assert sample.max_filtered_n == pytest.approx(0.05)


def test_threshold_uses_euclidean_norm_not_l1():
    sample = decode([[[0.01, 0.01, 0.01]]], None)
    assert sample.max_net_n == pytest.approx(math.sqrt(3) * 0.01)
    assert sample.max_net_n < 0.02


def test_multiple_bodies_and_filters_are_not_fabricated_vectors():
    sample = decode(
        [[[0.0, 0.0, 0.0], [0.0, 0.06, 0.0]]],
        [[[[0.03, 0.0, 0.0], [0.0, -0.04, 0.0]],
          [[0.05, 0.0, 0.0], [0.0, 0.01, 0.0]]]],
        ('/World/A', '/World/B'))
    assert sample.filtered_by_target_n == {
        '/World/A': (0.05, 0.0, 0.0), '/World/B': (0.0, -0.04, 0.0)}
    assert sample.max_net_n == pytest.approx(0.06)
    assert sample.max_filtered_n == pytest.approx(0.05)


@pytest.mark.parametrize('net,matrix', [
    ([[0.03, 0.0, 0.0]], None),
    ([[[0.03, 0.0]]], None),
    ([[[float('nan'), 0.0, 0.0]]], None),
    ([[[True, 0.0, 0.0]]], None),
    ([[[0.03, 0.0, 0.0]]], [[[0.03, 0.0, 0.0]]]),
    ([[[0.03, 0.0, 0.0]]], [[[[float('inf'), 0.0, 0.0]]]]),
    (None, None),
])
def test_malformed_or_missing_data_raises_without_partial_force(net, matrix):
    with pytest.raises(ValueError):
        decode(net, matrix)


def test_filter_count_mismatch_cannot_assign_force_to_wrong_target():
    with pytest.raises(ValueError, match='filter'):
        decode(None, [[[[0.03, 0.0, 0.0], [0.01, 0.0, 0.0]]]])


def test_body_count_mismatch_is_rejected():
    with pytest.raises(ValueError, match='body'):
        decode([[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]],
               [[[[0.03, 0.0, 0.0]]]])


def test_available_zero_is_not_a_claim_of_valid_contact_coverage():
    sample = decode([[[0.0, 0.0, 0.0]]], [[[[0.0, 0.0, 0.0]]]])
    result = contact_readout.ContactRead(sample=sample, error=None)
    record = contact_readout.build_readout_record(
        [result], step=1, time_s=0.05, sample_dt_s=0.01)
    assert record['classification'] == 'UNKNOWN'
    assert record['sensor']['available'] is False
    assert sample.max_net_n == 0.0  # Preserve successful raw zero separately.


def test_positive_net_does_not_invent_target_attribution():
    sample = decode([[[0.03, 0.0, 0.0]]], [[[[0.0, 0.0, 0.0]]]])
    record = contact_readout.build_readout_record(
        [contact_readout.ContactRead(sample=sample, error=None)],
        step=1, time_s=0.05, sample_dt_s=0.01)
    assert record['classification'] == 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
    assert record['layers']['force']['per_prim_n'] is None


def test_filtered_force_keeps_target_and_uses_physics_sample_interval():
    sample = decode(None, [[[[0.03, 0.0, 0.0]]]])
    record = contact_readout.build_readout_record(
        [contact_readout.ContactRead(sample=sample, error=None)],
        step=1, time_s=0.05, sample_dt_s=0.01)
    assert record['classification'] == 'CONTACT_FORCE_MEASURED'
    assert record['layers']['force']['window_s'] == 0.01
    assert record['layers']['force']['per_prim_n'][TARGET] == [0.03, 0.0, 0.0]
    assert 'force_threshold' in record['notes']


def test_read_error_does_not_hide_behind_another_sensor_zero():
    sample = decode([[[0.0, 0.0, 0.0]]], None)
    record = contact_readout.build_readout_record(
        [contact_readout.ContactRead(sample=sample, error=None),
         contact_readout.ContactRead(sample=None, error='read failed')],
        step=1, time_s=0.05, sample_dt_s=0.01)
    assert record['classification'] == 'UNKNOWN'
    assert record['layers']['force']['magnitude_n'] is None


def test_sensor_update_exception_is_recorded_not_converted_to_zero():
    class Broken:
        def update(self, dt, force_recompute):
            raise RuntimeError('view invalidated')

    read = contact_readout.read_contact_sensor(Broken(), dt_s=0.05,
                                              target_paths=(TARGET,))
    assert read.sample is None
    assert 'view invalidated' in read.error


def test_sensor_read_forces_recompute_without_tensor_dependency():
    class Sensor:
        data = SimpleNamespace(net_forces_w=[[[0.03, 0.0, 0.0]]],
                               force_matrix_w=None)

        def update(self, dt, force_recompute):
            assert dt == 0.05
            assert force_recompute is True

    read = contact_readout.read_contact_sensor(Sensor(), dt_s=0.05,
                                              target_paths=(TARGET,))
    assert read.error is None
    assert read.sample.max_net_n == 0.03


@pytest.mark.parametrize('mode', ['wall', 'obstacle', 'clearance', 'geometry', 'replay'])
def test_episode_cannot_upgrade_unverified_zero_to_no_contact(mode):
    record = contact_readout.build_readout_record(
        [contact_readout.ContactRead(
            sample=decode([[[0.0, 0.0, 0.0]]], None), error=None)],
        step=1, time_s=0.05, sample_dt_s=0.01,
        geometry={'sphere_overlap_m': 0.022})
    verdict = contact_readout.episode_contact_verdict([record], mode=mode)
    assert verdict['physical_outcome'] == 'UNKNOWN'
    assert verdict['outcome'] == 'UNDECIDABLE'


def test_episode_net_force_never_gains_target_attribution():
    record = contact_readout.build_readout_record(
        [contact_readout.ContactRead(
            sample=decode([[[0.03, 0.0, 0.0]]], None), error=None)],
        step=1, time_s=0.05, sample_dt_s=0.01)
    verdict = contact_readout.episode_contact_verdict([record], mode='obstacle')
    assert verdict['physical_outcome'] == 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
    assert verdict['outcome'] == 'SUCCESS'


def test_snapshot_records_remain_valid_under_existing_v2_contract():
    from boom_birds.evaluation import contact_contract
    samples = [decode([[[0.0, 0.0, 0.0]]], None),
               decode(None, [[[[0.03, 0.0, 0.0]]]])]
    records = [contact_readout.build_readout_record(
        [contact_readout.ContactRead(sample=s, error=None)],
        step=i, time_s=i * 0.05, sample_dt_s=0.01)
        for i, s in enumerate(samples)]
    summary = contact_contract.summarize_contact_records(records)
    assert summary['unknown_steps'] == 1
    assert summary['attributed_steps'] == 1
