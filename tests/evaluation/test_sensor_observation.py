"""Observation envelope/gate tests; no Isaac, Torch or image libraries."""
import pytest

from boom_birds.contracts.context import ContractContext, MessageHeader
from boom_birds.contracts import reasons
from boom_birds.evaluation import sensor_observation as obs

NOW = 10_000_000_000


def context(**changes):
    values = dict(system_boot_id=7, mission_epoch=1, localization_epoch=2,
                  control_epoch=3, clock_id='sim_physics', px4_boot_id=0,
                  sync_generation=4)
    values.update(changes)
    return ContractContext(**values)


def header(sequence=1, capture=None, **changes):
    capture = NOW if capture is None else capture
    values = dict(system_boot_id=7, mission_epoch=1, localization_epoch=2,
                  control_epoch=3, clock_id='sim_physics', px4_boot_id=None,
                  sync_generation=4, sync_valid=True, sequence_id=sequence,
                  capture_timestamp_ns=capture,
                  receive_timestamp_ns=capture,
                  publish_timestamp_ns=capture, source_id=10,
                  timestamp_uncertainty_ns=0, valid=True)
    values.update(changes)
    return MessageHeader(**values)


def record(sequence=1, capture=None, valid=True, reason=reasons.ACCEPT,
           digest='a' * 64, **header_changes):
    capture = NOW if capture is None else capture
    return obs.ObservationRecord(
        obs.RECORD_VERSION, header(sequence, capture, **header_changes),
        context(),
        {'sensor_id': 'front_rgb', 'modality': 'RGB_IMAGE',
         'frame_id': 'body_flu', 'source': 'SIM_RENDER_RGB', 'units': 'px',
         'intrinsics': {'fx': 100.0, 'fy': 100.0, 'cx': 5.0, 'cy': 5.0},
         'extrinsics': {'position_m': [0.1, 0.0, 0.0],
                        'quat_wxyz': [1.0, 0.0, 0.0, 0.0]},
         'shape': [4, 4, 3], 'dtype': 'uint8'},
        {'capture_sim_ns': capture, 'ready_sim_ns': capture + 1_000_000,
         'consume_sim_ns': capture + 2_000_000,
         'capture_host_ns': 1, 'ready_host_ns': 2, 'consume_host_ns': 3,
         'capture_clock_id': 'sim_physics', 'ready_clock_id': 'host_monotonic',
         'consume_clock_id': 'host_monotonic',
         'capture_time_source': 'SIM_UPDATE_SAMPLE_TIME',
         'exposure_time_status': 'UNKNOWN',
         'capture_interval_ns': 250_000_000,
         'capture_time_uncertainty_ns': 0},
        {'ref': 'images/x.png', 'sha256': digest, 'shape': [4, 4, 3],
         'dtype': 'uint8', 'size_bytes': 10},
        {'valid': valid, 'reason': reason})


def test_normal_new_sample_is_accepted():
    gate = obs.ObservationGate(10_000_000)
    verdict = gate.accept(record(1), NOW + 2_000_000)
    assert verdict['accepted'] is True
    assert verdict['reason'] == reasons.ACCEPT


def test_duplicate_and_old_sequence_are_rejected():
    gate = obs.ObservationGate(10_000_000)
    assert gate.accept(record(2), NOW + 2_000_000)['accepted'] is True
    assert gate.accept(record(2), NOW + 2_000_000)['reason'] ==         reasons.REJECT_SEQUENCE_REUSE
    assert gate.accept(record(1), NOW + 2_000_000)['reason'] ==         reasons.REJECT_OUT_OF_ORDER


def test_stale_sample_is_rejected_with_explicit_reason():
    gate = obs.ObservationGate(1_000_000)
    verdict = gate.accept(record(1, capture=NOW - 2_000_000_000), NOW + 2_000_000)
    assert verdict['accepted'] is False
    assert verdict['reason'] == reasons.REJECT_STALE


def test_context_and_generation_mismatch_are_rejected():
    gate = obs.ObservationGate(10_000_000)
    gate.reset(context=context(), generation=4)
    changed_boot = record(1, system_boot_id=8)
    assert gate.accept(changed_boot, NOW + 2_000_000)['reason'] ==         reasons.REJECT_BOOT_MISMATCH
    changed_generation = record(1, sync_generation=5)
    assert gate.accept(changed_generation, NOW + 2_000_000)['reason'] ==         reasons.REJECT_SYNC_OR_PX4_BOOT


def test_invalid_sensor_sample_is_not_accepted():
    gate = obs.ObservationGate(10_000_000)
    verdict = gate.accept(record(1, valid=False, reason='NO_RETURN'),
                          NOW + 2_000_000)
    assert verdict['accepted'] is False
    assert verdict['reason'] == 'NO_RETURN'


def test_v2_capture_time_semantics_do_not_claim_exposure():
    rec = record()
    stamps = dict(rec.timestamps)
    v2 = obs.ObservationRecord(obs.RECORD_VERSION, rec.header, rec.context,
                               rec.sensor, stamps, rec.payload, rec.validity)
    assert v2.timestamps['exposure_time_status'] == 'UNKNOWN'
    assert 'exposure_uncertainty_ns' not in v2.timestamps


def test_v2_rejects_missing_capture_time_semantics():
    rec = record()
    stamps = dict(rec.timestamps)
    stamps.pop('capture_interval_ns')
    with pytest.raises(ValueError, match='timestamps'):
        obs.ObservationRecord(obs.RECORD_VERSION, rec.header, rec.context,
                              rec.sensor, stamps, rec.payload, rec.validity)


def test_depth_source_is_supported_as_distance_modality():
    rec = record()
    sensor = dict(rec.sensor)
    sensor.update({'sensor_id': 'front_depth', 'modality': 'SIM_RENDER_DEPTH',
                   'source': 'SIM_RENDER_DEPTH', 'units': 'm',
                   'shape': [1], 'dtype': 'float64'})
    replacement = obs.ObservationRecord(
        obs.RECORD_VERSION, rec.header, rec.context, sensor,
        rec.timestamps, rec.payload, rec.validity)
    assert replacement.sensor['source'] == 'SIM_RENDER_DEPTH'


def test_payload_hash_and_shape_validation():
    assert obs.payload_sha256(b'abc') == (
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    with pytest.raises(ValueError, match='sha256'):
        obs.ObservationRecord(
            obs.RECORD_VERSION, header(), context(),
            {'sensor_id': 'x', 'modality': 'RGB_IMAGE', 'frame_id': 'body_flu',
             'source': 'SIM_RENDER_RGB', 'units': 'px', 'intrinsics': {},
             'extrinsics': {}, 'shape': [1, 1, 3], 'dtype': 'uint8'},
            {'capture_sim_ns': 1, 'ready_sim_ns': 1, 'consume_sim_ns': 1,
             'capture_host_ns': 1, 'ready_host_ns': 1, 'consume_host_ns': 1,
             'capture_clock_id': 'sim_physics',
             'ready_clock_id': 'host_monotonic',
             'consume_clock_id': 'host_monotonic',
             'capture_time_source': 'SIM_UPDATE_SAMPLE_TIME',
             'exposure_time_status': 'UNKNOWN',
             'capture_interval_ns': 250_000_000,
             'capture_time_uncertainty_ns': 0},
            {'ref': 'x', 'sha256': 'nothex', 'shape': [1, 1, 3],
             'dtype': 'uint8', 'size_bytes': 1},
            {'valid': True, 'reason': reasons.ACCEPT})
