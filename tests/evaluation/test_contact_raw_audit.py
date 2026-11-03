"""Raw vector recomputation must reject self-reported measurement tampering."""
import copy

import pytest

from boom_birds.evaluation import contact_raw_audit


def row():
    return {'read_ok': True, 'measured_force_n': 0.03,
            'contact_readout': {
                'reads': [{'error': None, 'sample': {
                    'net_vectors_n': [[0.03, 0.0, 0.0]],
                    'filtered_by_target_n': {'/Obstacle': [0.03, 0.0, 0.0]}}}],
                'measure': {'read_ok': True, 'measured_force_n': 0.03}}}


def test_recomputes_from_vectors():
    assert contact_raw_audit.audit_row(row())['measured_force_n'] == 0.03


@pytest.mark.parametrize('location', ['row', 'measure'])
def test_tampered_force_cache_does_not_pass(location):
    sample = row()
    target = sample if location == 'row' else sample['contact_readout']['measure']
    target['measured_force_n'] = 0.0
    with pytest.raises(ValueError, match='measured_force'):
        contact_raw_audit.audit_row(sample)


def test_empty_reads_cannot_be_a_healthy_zero():
    sample = row()
    sample['contact_readout']['reads'] = []
    with pytest.raises(ValueError):
        contact_raw_audit.audit_row(sample)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True])
def test_invalid_raw_component_rejected(value):
    sample = row()
    sample['contact_readout']['reads'][0]['sample']['net_vectors_n'][0][0] = value
    with pytest.raises(ValueError):
        contact_raw_audit.audit_row(sample)


def test_hidden_sensor_error_rejected_even_if_cached_read_ok_true():
    sample = row()
    sample['contact_readout']['reads'][0]['error'] = 'view invalid'
    with pytest.raises(ValueError):
        contact_raw_audit.audit_row(sample)


def test_live_dataclass_tuple_vectors_and_json_lists_have_same_result():
    sample = row()
    sample['contact_readout']['reads'][0]['sample']['net_vectors_n'] = ((0.03, 0.0, 0.0),)
    assert contact_raw_audit.audit_row(sample)['measured_force_n'] == 0.03
