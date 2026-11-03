"""Shadow landmark-consumer adapter over the existing v2 observation records.

The consumer reads only the declared RGB observation, its intrinsics and a
static template prior.  It does not read robot pose, region labels, target
coordinates, future steps, or evaluation labels.  It never feeds control.
"""
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from boom_birds.contracts.context import (ContractContext, EstimatorState,
                                          MessageHeader)
from boom_birds.contracts import reasons
from boom_birds.evaluation import sensor_observation as obs_mod
from boom_birds.evaluation.landmark_detector import TowerTemplateDetector

CONSUMER_VERSION = 'dsh.landmark_consumer.v1'
DEFAULT_CAPTURE_INTERVAL_NS = 250_000_000


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _context_from_dict(value):
    data = dict(value)
    estimates = EstimatorState(**data.pop('estimates', {}))
    return ContractContext(**data, estimates=estimates)


def _header_from_dict(value):
    data = dict(value)
    return MessageHeader(**data)


class LandmarkConsumer:
    """Ordered, generation-aware consumer; no truth input anywhere."""

    def __init__(self, *, template_path: Path = None, threshold: float = None,
                 detector=None, allowed_age_ns: int = 250_000_000,
                 capture_interval_ns: int = DEFAULT_CAPTURE_INTERVAL_NS):
        if detector is None:
            if template_path is None or threshold is None:
                raise ValueError('provide detector or template_path+threshold')
            detector = TowerTemplateDetector(template_path, threshold=threshold)
        self.detector = detector
        self.template_path = Path(template_path) if template_path is not None else None
        self.allowed_age_ns = int(allowed_age_ns)
        self.capture_interval_ns = int(capture_interval_ns)
        self.gate = obs_mod.ObservationGate(self.allowed_age_ns)
        self.last_generation = None
        self.last_sequence = {}
        self.cache = {}
        self.reset_count = 0
        self.template_path = Path(template_path)
        self.template_hash = (hashlib.sha256(
            self.template_path.read_bytes()).hexdigest()
            if self.template_path is not None else None)

    def reset(self):
        self.gate = obs_mod.ObservationGate(self.allowed_age_ns)
        self.last_generation = None
        self.last_sequence.clear()
        self.cache.clear()

    def _normalize(self, raw):
        version = raw.get('record_version')
        if version == obs_mod.RECORD_VERSION:
            return obs_mod.ObservationRecord(
                version, _header_from_dict(raw['header']),
                _context_from_dict(raw['context']), dict(raw['sensor']),
                dict(raw['timestamps']), dict(raw['payload']),
                dict(raw['validity'])), {'time_semantics': 'v2_declared'}
        if version == obs_mod.LEGACY_RECORD_VERSION:
            timestamps = dict(raw['timestamps'])
            legacy_exposure = timestamps.pop('exposure_uncertainty_ns', None)
            timestamps.update({
                'capture_time_source': 'SIM_UPDATE_SAMPLE_TIME',
                'exposure_time_status': 'UNKNOWN',
                'capture_interval_ns': self.capture_interval_ns,
                'capture_time_uncertainty_ns': 0,
            })
            header = dict(raw['header'])
            header['timestamp_uncertainty_ns'] = 0
            return obs_mod.ObservationRecord(
                obs_mod.RECORD_VERSION, _header_from_dict(header),
                _context_from_dict(raw['context']), dict(raw['sensor']),
                timestamps, dict(raw['payload']),
                dict(raw['validity'])), {
                    'time_semantics': 'legacy_v1_normalized',
                    'legacy_exposure_uncertainty_ns': legacy_exposure,
                    'exposure_time_status': 'UNKNOWN',
                    'note': 'legacy host capture is after camera update; '
                            'not an exposure timestamp; full latency unknown'}
        raise ValueError('unsupported observation record version')

    def process(self, raw, *, now_sim_ns=None):
        try:
            record, time_meta = self._normalize(raw)
        except Exception as error:  # noqa: BLE001
            return self._result('REJECTED', 'INVALID_OBSERVATION', raw, {
                'error': repr(error)})
        generation = record.header.sync_generation
        if self.last_generation is not None and generation < self.last_generation:
            return self._result('REJECTED', 'OLD_GENERATION', raw,
                                {'generation': generation})
        if generation != self.last_generation:
            self.gate.reset(context=record.context, generation=generation)
            self.cache.clear()
            self.last_generation = generation
            self.reset_count += 1
        now = (record.timestamps['consume_sim_ns']
               if now_sim_ns is None else int(now_sim_ns))
        decision = self.gate.accept(record, now)
        if not decision['accepted']:
            return self._result('REJECTED', decision['reason'], raw, {
                'gate': decision, 'time': time_meta})
        if not record.sensor.get('intrinsics'):
            return self._result('UNKNOWN', 'MISSING_CALIBRATION', raw,
                                {'time': time_meta})
        image_path = Path(record.payload.get('ref', ''))
        if not image_path.is_file():
            return self._result('UNKNOWN', 'INVALID_IMAGE', raw,
                                {'time': time_meta})
        try:
            detection = self.detector.detect(image_path,
                                             record.sensor['intrinsics'])
        except Exception as error:  # noqa: BLE001
            return self._result('UNKNOWN', 'DETECTOR_ERROR', raw,
                                {'error': repr(error), 'time': time_meta})
        status = detection.status
        if status == 'DETECTED':
            result_reason = 'TARGET_DETECTED'
        elif status == 'NOT_DETECTED':
            result_reason = 'TARGET_NOT_DETECTED'
        else:
            result_reason = 'UNKNOWN_DETECTION'
        result = self._result(status, result_reason, raw, {
            'detection': asdict(detection), 'gate': decision,
            'time': time_meta, 'intrinsics_hash': _json_hash(
                record.sensor.get('intrinsics'))})
        self.cache[record.header.sequence_id] = result
        return result

    def _result(self, status, reason, raw, extra):
        now_sim = raw.get('timestamps', {}).get('consume_sim_ns')
        capture_sim = raw.get('timestamps', {}).get('capture_sim_ns')
        result = {
            'result_version': 'dsh.landmark_result.v1',
            'consumer_version': CONSUMER_VERSION,
            'shadow_only': True,
            'control_participation': 'NONE',
            'status': status,
            'reason': reason,
            'algorithm': self.detector.metadata(),
            'calibration_version': 'intrinsics_from_observation',
            'camera_intrinsics': raw.get('sensor', {}).get('intrinsics'),
            'source': {
                'sensor_id': raw.get('sensor', {}).get('sensor_id'),
                'frame_id': raw.get('sensor', {}).get('frame_id'),
                'sequence_id': raw.get('header', {}).get('sequence_id'),
                'generation': raw.get('header', {}).get('sync_generation'),
                'payload_sha256': raw.get('payload', {}).get('sha256'),
                'observation_record_sha256': _json_hash(raw),
            },
            'capture_time_semantics': {
                'capture_sim_ns': capture_sim,
                'consume_sim_ns': now_sim,
                'capture_time_source': raw.get('timestamps', {}).get(
                    'capture_time_source', 'SIM_UPDATE_SAMPLE_TIME_LEGACY_V1'),
                'exposure_time_status': 'UNKNOWN',
                'capture_interval_ns': raw.get('timestamps', {}).get(
                    'capture_interval_ns', self.capture_interval_ns),
                'note': 'age is a sim sample/consume measure; full camera '
                        'capture-to-consumer latency and exposure are unknown',
            },
            'validity': {
                'valid_until_ns': (None if capture_sim is None
                                   else capture_sim + self.allowed_age_ns),
                'age_ns': extra.get('gate', {}).get('age_ns'),
                'age_semantics': 'SIM_SAMPLE_TIME_NOT_FULL_LATENCY',
            },
            'distance': {
                'available': False,
                'reason': 'single center depth is not a valid distance for an '
                          'arbitrary detection box',
            },
            'context': raw.get('context'),
            'extra': extra,
        }
        return result
