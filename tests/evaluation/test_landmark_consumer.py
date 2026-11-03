"""Landmark detector/consumer tests: no Isaac, no evaluation truth input."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from boom_birds.contracts.context import ContractContext, EstimatorState, MessageHeader
from boom_birds.evaluation.landmark_consumer import LandmarkConsumer
from boom_birds.evaluation.landmark_detector import TowerTemplateDetector
from boom_birds.evaluation import sensor_observation as obs


def synthetic_template(tmp_path):
    template = np.zeros((40, 30), dtype=np.uint8)
    template[8:32, 8:22] = 255
    path = tmp_path / 'template.png'
    cv2.imwrite(str(path), template)
    return path, template


def test_detector_finds_template_and_returns_bearing(tmp_path):
    template_path, template = synthetic_template(tmp_path)
    image = np.zeros((120, 160), dtype=np.uint8)
    image[35:75, 65:95] = template
    image_path = tmp_path / 'image.png'
    cv2.imwrite(str(image_path), image)
    detector = TowerTemplateDetector(template_path, threshold=0.8,
                                     scales=(1.0,))
    detection = detector.detect(image_path, [[100.0, 0, 80.0],
                                             [0, 100.0, 60.0], [0, 0, 1.0]])
    assert detection.status == 'DETECTED'
    assert detection.score >= 0.8
    assert detection.bbox_xywh is not None
    assert abs(detection.bbox_xywh[0] - 65) <= 1
    assert detection.bearing_rad == pytest.approx(0.0, abs=0.02)


def test_low_similarity_is_explicit_not_detected(tmp_path):
    template_path, _ = synthetic_template(tmp_path)
    image_path = tmp_path / 'noise.png'
    rng = np.random.default_rng(3)
    cv2.imwrite(str(image_path),
                rng.integers(0, 255, (120, 160), dtype=np.uint8))
    detector = TowerTemplateDetector(template_path, threshold=0.9,
                                     scales=(1.0,))
    detection = detector.detect(image_path, [[100.0, 0, 80.0],
                                             [0, 100.0, 60.0], [0, 0, 1.0]])
    assert detection.status in ('NOT_DETECTED', 'UNKNOWN')
    assert detection.distance_m is None


def minimal_observation(tmp_path, image_path, *, generation=3, sequence=1,
                        truth_marker='DO_NOT_READ_THIS'):
    header = MessageHeader(
        system_boot_id=2201, mission_epoch=0, localization_epoch=0,
        control_epoch=0, clock_id='sim_physics', px4_boot_id=None,
        sync_generation=generation, sync_valid=True, sequence_id=sequence,
        capture_timestamp_ns=1_000_000_000,
        receive_timestamp_ns=1_000_000_000,
        publish_timestamp_ns=1_000_000_000, source_id=10,
        timestamp_uncertainty_ns=10_000_000, quarantine=False, valid=True)
    context = ContractContext(
        system_boot_id=2201, mission_epoch=0, localization_epoch=0,
        control_epoch=0, clock_id='sim_physics', px4_boot_id=0,
        sync_generation=generation, estimates=EstimatorState())
    sensor = {'sensor_id': 'front_rgb', 'modality': 'RGB_IMAGE',
              'frame_id': 'body_flu', 'source': 'SIM_RENDER_RGB',
              'units': 'px',
              'intrinsics': [[100.0, 0, 80.0], [0, 100.0, 60.0], [0, 0, 1.0]],
              'extrinsics': {},
              'shape': [120, 160, 3], 'dtype': 'uint8'}
    timestamps = {'capture_sim_ns': 1_000_000_000,
                  'ready_sim_ns': 1_000_000_000,
                  'consume_sim_ns': 1_000_000_000,
                  'capture_host_ns': 1, 'ready_host_ns': 2, 'consume_host_ns': 3,
                  'capture_clock_id': 'sim_physics',
                  'ready_clock_id': 'host_monotonic',
                  'consume_clock_id': 'host_monotonic',
                  'exposure_uncertainty_ns': 10_000_000}
    payload = {'ref': image_path.as_posix(),
               'sha256': obs.payload_sha256(Path(image_path).read_bytes()),
               'shape': [120, 160, 3], 'dtype': 'uint8',
               'size_bytes': Path(image_path).stat().st_size}
    return {'record_version': obs.LEGACY_RECORD_VERSION,
            'header': header.__dict__,
            'context': {**context.__dict__, 'estimates': context.estimates.__dict__},
            'sensor': sensor, 'timestamps': timestamps, 'payload': payload,
            'validity': {'valid': True, 'reason': 'ACCEPT'},
            'ground_truth': truth_marker}


def test_consumer_never_reads_truth_fields(tmp_path):
    template_path, template = synthetic_template(tmp_path)
    image = np.zeros((120, 160), dtype=np.uint8)
    image[35:75, 65:95] = template
    image_path = tmp_path / 'image.png'
    cv2.imwrite(str(image_path), image)
    raw = minimal_observation(tmp_path, image_path)
    consumer = LandmarkConsumer(template_path=template_path, threshold=0.5)
    result = consumer.process(raw)
    assert result['status'] == 'DETECTED'
    assert 'DO_NOT_READ_THIS' not in json.dumps(result)
    assert result['distance']['available'] is False
    assert result['shadow_only'] is True
    assert result['capture_time_semantics']['exposure_time_status'] == 'UNKNOWN'


def test_consumer_rejects_stale_and_old_generation(tmp_path):
    template_path, template = synthetic_template(tmp_path)
    image = np.zeros((120, 160), dtype=np.uint8)
    image[35:75, 65:95] = template
    image_path = tmp_path / 'image2.png'
    cv2.imwrite(str(image_path), image)
    consumer = LandmarkConsumer(template_path=template_path, threshold=0.5,
                                allowed_age_ns=1_000_000)
    raw = minimal_observation(tmp_path, image_path, generation=3, sequence=1)
    consumer.process(raw)
    old = minimal_observation(tmp_path, image_path, generation=2, sequence=1)
    assert consumer.process(old)['status'] == 'REJECTED'
    stale = minimal_observation(tmp_path, image_path, generation=3, sequence=2)
    stale['timestamps']['consume_sim_ns'] = 1_000_000_000 + 2_000_000
    assert consumer.process(stale)['status'] == 'REJECTED'
