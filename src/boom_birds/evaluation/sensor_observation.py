"""Standard-library observation envelope around V2.2 message/context contracts.

The flight-control message schema remains ``boom_birds.message.v2.0``.  This
module only wraps that header/context with sensor provenance; it is not a new
flight-control schema and does not grant control authority.
"""
from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any, Mapping

from boom_birds.contracts import reasons
from boom_birds.contracts.context import (ContractContext, MessageHeader,
                                          validate_message, worst_case_age_ns)

RECORD_VERSION = 'boom_birds.sensor_observation.v1'
MODALITIES = frozenset({'RGB_IMAGE', 'SIM_RENDER_DEPTH', 'IDEAL_RAYCAST_RANGE'})
SOURCES = frozenset({'SIM_RENDER_RGB', 'SIM_RENDER_DEPTH', 'IDEAL_RAYCAST_RANGE'})
UNITS = frozenset({'px', 'm'})
INVALID_REASONS = frozenset({
    'WARMUP', 'NO_RETURN', 'OUT_OF_RANGE', 'NON_FINITE', 'DECODE_FAILED',
    'EMPTY_IMAGE', 'PAYLOAD_HASH_MISMATCH', 'CLOCK_DOMAIN',
    'STALE', 'UNKNOWN',
})


def _require(mapping: Mapping, fields, name):
    missing = [field for field in fields if field not in mapping]
    if missing:
        raise ValueError(name + ' missing fields: ' + ','.join(missing))


@dataclass(frozen=True)
class ObservationRecord:
    record_version: str
    header: MessageHeader
    context: ContractContext
    sensor: dict
    timestamps: dict
    payload: dict
    validity: dict

    def __post_init__(self):
        if self.record_version != RECORD_VERSION:
            raise ValueError('unsupported observation record version')
        if not isinstance(self.header, MessageHeader):
            raise ValueError('header must be MessageHeader')
        if not isinstance(self.context, ContractContext):
            raise ValueError('context must be ContractContext')
        _require(self.sensor, ('sensor_id', 'modality', 'frame_id', 'source',
                               'units', 'intrinsics', 'extrinsics', 'shape',
                               'dtype'), 'sensor')
        if self.sensor['modality'] not in MODALITIES:
            raise ValueError('unsupported sensor modality')
        if self.sensor['source'] not in SOURCES:
            raise ValueError('unsupported sensor source')
        if self.sensor['units'] not in UNITS:
            raise ValueError('unsupported payload units')
        _require(self.timestamps, ('capture_sim_ns', 'ready_sim_ns',
                                   'consume_sim_ns', 'capture_host_ns',
                                   'ready_host_ns', 'consume_host_ns',
                                   'capture_clock_id', 'ready_clock_id',
                                   'consume_clock_id',
                                   'exposure_uncertainty_ns'), 'timestamps')
        for key in ('capture_sim_ns', 'ready_sim_ns', 'consume_sim_ns',
                    'capture_host_ns', 'ready_host_ns', 'consume_host_ns',
                    'exposure_uncertainty_ns'):
            value = self.timestamps[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError('timestamp must be a nonnegative int')
        for key in ('capture_clock_id', 'ready_clock_id', 'consume_clock_id'):
            if not isinstance(self.timestamps[key], str) or not self.timestamps[key]:
                raise ValueError('clock id must be a nonempty string')
        _require(self.payload, ('ref', 'sha256', 'shape', 'dtype',
                                'size_bytes'), 'payload')
        if not isinstance(self.payload['sha256'], str) or len(
                self.payload['sha256']) != 64:
            raise ValueError('payload sha256 must be 64 hex characters')
        if not isinstance(self.payload['shape'], (list, tuple)):
            raise ValueError('payload shape must be a sequence')
        if not isinstance(self.payload['dtype'], str):
            raise ValueError('payload dtype must be a string')
        _require(self.validity, ('valid', 'reason'), 'validity')
        if not isinstance(self.validity['valid'], bool):
            raise ValueError('validity.valid must be bool')
        if self.validity['valid'] and self.validity['reason'] != reasons.ACCEPT:
            raise ValueError('valid observation must use ACCEPT reason')
        if (not self.validity['valid']
                and self.validity['reason'] not in INVALID_REASONS):
            raise ValueError('unknown invalid reason')

    def to_dict(self):
        return {
            'record_version': self.record_version,
            'header': asdict(self.header),
            'context': {
                **asdict(self.context),
                'estimates': asdict(self.context.estimates),
            },
            'sensor': dict(self.sensor),
            'timestamps': dict(self.timestamps),
            'payload': dict(self.payload),
            'validity': dict(self.validity),
        }


def payload_sha256(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('payload must be bytes')
    return hashlib.sha256(bytes(data)).hexdigest()


def make_observation(*, header, context, sensor, timestamps, payload,
                     validity) -> ObservationRecord:
    record = ObservationRecord(RECORD_VERSION, header, context, sensor,
                               timestamps, payload, validity)
    # Reuse the v2 message verdict order; do not create a second acceptance rule.
    verdict = validate_message(header, context, timestamps['consume_sim_ns'],
                               allowed_age_ns=None, mapping=None,
                               require_px4_boot=False)
    if verdict != reasons.ACCEPT and validity['valid']:
        record = ObservationRecord(RECORD_VERSION, header, context, sensor,
                                   timestamps, payload,
                                   {'valid': False, 'reason': 'CLOCK_DOMAIN',
                                    'verdict': verdict})
    return record


class ObservationGate:
    """Small consumer-side gate for ordering, generation and freshness."""

    def __init__(self, allowed_age_ns):
        if not isinstance(allowed_age_ns, int) or isinstance(
                allowed_age_ns, bool) or allowed_age_ns < 0:
            raise ValueError('allowed_age_ns must be a nonnegative int')
        self.allowed_age_ns = allowed_age_ns
        self._last_sequence = {}
        self._context_identity = None
        self._generation = None

    def reset(self, *, context, generation):
        self._last_sequence.clear()
        self._context_identity = (context.system_boot_id, context.mission_epoch,
                                  context.localization_epoch,
                                  context.control_epoch, context.clock_id,
                                  context.sync_generation)
        self._generation = generation

    def _identity(self, record):
        c = record.context
        return (c.system_boot_id, c.mission_epoch, c.localization_epoch,
                c.control_epoch, c.clock_id, c.sync_generation)

    def accept(self, record, now_ns):
        if not isinstance(record, ObservationRecord):
            return {'accepted': False, 'reason': reasons.REJECT_INVALID,
                    'age_ns': None}
        if self._context_identity is None:
            self.reset(context=record.context, generation=record.header.sync_generation)
        if self._identity(record) != self._context_identity:
            return {'accepted': False, 'reason': reasons.REJECT_BOOT_MISMATCH,
                    'age_ns': None}
        if record.header.sync_generation != self._generation:
            return {'accepted': False, 'reason': reasons.REJECT_SYNC_OR_PX4_BOOT,
                    'age_ns': None}
        sensor_id = record.sensor['sensor_id']
        last = self._last_sequence.get(sensor_id)
        if last is not None:
            if record.header.sequence_id == last:
                return {'accepted': False, 'reason': reasons.REJECT_SEQUENCE_REUSE,
                        'age_ns': None}
            if record.header.sequence_id < last:
                return {'accepted': False, 'reason': reasons.REJECT_OUT_OF_ORDER,
                        'age_ns': None}
        verdict = validate_message(record.header, record.context, now_ns,
                                   allowed_age_ns=self.allowed_age_ns,
                                   mapping=None, require_px4_boot=False)
        if verdict != reasons.ACCEPT:
            return {'accepted': False, 'reason': verdict, 'age_ns': None}
        if not record.validity['valid']:
            return {'accepted': False, 'reason': record.validity['reason'],
                    'age_ns': worst_case_age_ns(record.header, record.context,
                                                now_ns)}
        age_ns = worst_case_age_ns(record.header, record.context, now_ns)
        if age_ns is None or age_ns > self.allowed_age_ns:
            return {'accepted': False, 'reason': reasons.REJECT_STALE,
                    'age_ns': age_ns}
        self._last_sequence[sensor_id] = record.header.sequence_id
        return {'accepted': True, 'reason': reasons.ACCEPT, 'age_ns': age_ns}
