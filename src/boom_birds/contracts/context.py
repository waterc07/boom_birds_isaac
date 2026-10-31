"""V2.2 16.1-16.3: message header, clock domains and four-level context."""
import math
from dataclasses import dataclass

from . import reasons
from .types import is_counter
from .versions import MESSAGE_SCHEMA_ID, SUPPORTED_MESSAGE_SCHEMAS

COUNTER_FIELDS = (
    'system_boot_id', 'mission_epoch', 'localization_epoch', 'control_epoch',
    'sync_generation', 'sequence_id', 'capture_timestamp_ns',
    'receive_timestamp_ns', 'publish_timestamp_ns', 'source_id',
    'timestamp_uncertainty_ns',
)
ESTIMATE_FIELDS = (
    'attitude_valid', 'angular_rate_valid', 'thrust_source_valid',
    'xy_velocity_valid', 'z_velocity_valid', 'height_valid',
    'local_position_valid', 'visual_bearing_valid', 'visual_servo_valid',
    'yaw_valid',
)


def _counter(name, value):
    if not is_counter(value):
        raise ValueError(name + ' must be a nonnegative integer')


def _text(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(name + ' must be a nonempty string')


def _flag(name, value):
    if not isinstance(value, bool):
        raise ValueError(name + ' must be a bool')


@dataclass(frozen=True)
class ClockMapping:
    """Validated cross-device mapping; age uses the worst-case error bound."""
    source_clock_id: str
    target_clock_id: str
    offset_ns: int
    uncertainty_ns: int
    valid_from_ns: int
    valid_until_ns: int
    sync_generation: int
    valid: bool = True

    def __post_init__(self):
        _text('source_clock_id', self.source_clock_id)
        _text('target_clock_id', self.target_clock_id)
        for name in ('offset_ns', 'uncertainty_ns', 'valid_from_ns',
                     'valid_until_ns', 'sync_generation'):
            value = getattr(self, name)
            if name == 'offset_ns':
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError('offset_ns must be an int')
            else:
                _counter(name, value)
        if self.valid_from_ns > self.valid_until_ns:
            raise ValueError('mapping validity window is inverted')
        _flag('valid', self.valid)

    def usable(self, now_ns, sync_generation):
        return (self.valid and isinstance(sync_generation, int)
                and self.sync_generation == sync_generation
                and self.valid_from_ns <= now_ns <= self.valid_until_ns)


@dataclass(frozen=True)
class MessageHeader:
    """Unified header; px4_boot_id None explicitly means not applicable."""
    system_boot_id: int
    mission_epoch: int
    localization_epoch: int
    control_epoch: int
    clock_id: str
    px4_boot_id: int | None
    sync_generation: int
    sync_valid: bool
    sequence_id: int
    capture_timestamp_ns: int
    receive_timestamp_ns: int
    publish_timestamp_ns: int
    source_id: int
    schema_version: str = MESSAGE_SCHEMA_ID
    timestamp_uncertainty_ns: int = 0
    quarantine: bool = False
    valid: bool = True

    def __post_init__(self):
        for name in COUNTER_FIELDS:
            _counter(name, getattr(self, name))
        if self.px4_boot_id is not None:
            _counter('px4_boot_id', self.px4_boot_id)
        _text('clock_id', self.clock_id)
        _text('schema_version', self.schema_version)
        _flag('sync_valid', self.sync_valid)
        _flag('quarantine', self.quarantine)
        _flag('valid', self.valid)


@dataclass(frozen=True)
class EstimatorState:
    """Normalized validity flags; False is unknown, never zero-valued valid."""
    attitude_valid: bool = False
    angular_rate_valid: bool = False
    thrust_source_valid: bool = False
    xy_velocity_valid: bool = False
    z_velocity_valid: bool = False
    height_valid: bool = False
    local_position_valid: bool = False
    visual_bearing_valid: bool = False
    visual_servo_valid: bool = False
    yaw_valid: bool = False

    def __post_init__(self):
        for name in ESTIMATE_FIELDS:
            _flag(name, getattr(self, name))


@dataclass(frozen=True)
class ContractContext:
    """Everything a consumer must match before accepting async data/actions."""
    system_boot_id: int
    mission_epoch: int
    localization_epoch: int
    control_epoch: int
    clock_id: str
    px4_boot_id: int
    sync_generation: int
    schema_version: str = MESSAGE_SCHEMA_ID
    control_owner: str = 'STUDENT'
    pending_owner: str | None = None
    estimates: EstimatorState = EstimatorState()

    def __post_init__(self):
        for name in ('system_boot_id', 'mission_epoch', 'localization_epoch',
                     'control_epoch', 'px4_boot_id', 'sync_generation'):
            _counter(name, getattr(self, name))
        _text('clock_id', self.clock_id)
        _text('schema_version', self.schema_version)
        _text('control_owner', self.control_owner)
        if self.pending_owner is not None:
            _text('pending_owner', self.pending_owner)
        if not isinstance(self.estimates, EstimatorState):
            raise ValueError('estimates must be an EstimatorState')


def worst_case_age_ns(header, context, now_ns, mapping=None):
    """Upper-bound age including timestamp and mapping uncertainty; None if unknown."""
    if not isinstance(header, MessageHeader) or not isinstance(context, ContractContext):
        return None
    if not is_counter(now_ns):
        return None
    if header.clock_id == context.clock_id:
        if header.capture_timestamp_ns > now_ns:
            return None
        return now_ns - header.capture_timestamp_ns + header.timestamp_uncertainty_ns
    if not isinstance(mapping, ClockMapping):
        return None
    if not mapping.usable(now_ns, context.sync_generation):
        return None
    if mapping.source_clock_id != header.clock_id:
        return None
    if mapping.target_clock_id != context.clock_id:
        return None
    if not header.sync_valid or header.sync_generation != mapping.sync_generation:
        return None
    estimate = header.capture_timestamp_ns + mapping.offset_ns
    if estimate > now_ns:
        return None
    return now_ns - estimate + header.timestamp_uncertainty_ns + mapping.uncertainty_ns


def validate_message(header, context, now_ns, allowed_age_ns=None, *,
                     mapping=None, require_px4_boot=False):
    """V2.2 27.2 order. Returns a reason code; never raises for data verdicts."""
    if not isinstance(header, MessageHeader) or not isinstance(context, ContractContext):
        return reasons.REJECT_INVALID
    if not is_counter(now_ns):
        return reasons.REJECT_INVALID
    if header.system_boot_id != context.system_boot_id:
        return reasons.REJECT_BOOT_MISMATCH
    if header.mission_epoch != context.mission_epoch:
        return reasons.REJECT_MISSION_EPOCH
    if header.localization_epoch != context.localization_epoch:
        return reasons.REJECT_LOCALIZATION_EPOCH
    if header.control_epoch != context.control_epoch:
        return reasons.REJECT_CONTROL_EPOCH
    if header.clock_id != context.clock_id and mapping is None:
        return reasons.REJECT_CLOCK_DOMAIN
    if not header.sync_valid or header.sync_generation != context.sync_generation:
        return reasons.REJECT_SYNC_OR_PX4_BOOT
    if header.px4_boot_id is None:
        if require_px4_boot:
            return reasons.REJECT_SYNC_OR_PX4_BOOT
    elif header.px4_boot_id != context.px4_boot_id:
        return reasons.REJECT_SYNC_OR_PX4_BOOT
    if header.quarantine:
        return reasons.REJECT_QUARANTINE
    if header.capture_timestamp_ns > now_ns:
        return reasons.REJECT_FUTURE_TIMESTAMP
    age_ns = worst_case_age_ns(header, context, now_ns, mapping)
    if age_ns is None:
        return reasons.REJECT_CLOCK_DOMAIN
    limit = allowed_age_ns
    if isinstance(limit, dict):
        if header.source_id not in limit:
            return reasons.REJECT_STALE
        limit = limit[header.source_id]
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            return reasons.REJECT_INVALID
        if age_ns > limit:
            return reasons.REJECT_STALE
    if not header.valid:
        return reasons.REJECT_INVALID
    if header.schema_version not in SUPPORTED_MESSAGE_SCHEMAS:
        return reasons.REJECT_SCHEMA_UNSUPPORTED
    return reasons.ACCEPT
