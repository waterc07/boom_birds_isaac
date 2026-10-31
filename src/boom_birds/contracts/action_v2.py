"""V2.2 10.4 Action Schema v2.0 with provenance and non-renewable TTL."""
import hashlib
import json
import math
from dataclasses import dataclass

from .context import MessageHeader
from .types import SCHEMA_ID as VELOCITY_V1_SCHEMA_ID
from .types import VelocityCommand, is_counter
from .versions import ACTION_FRAME, ACTION_SCHEMA_ID, ACTION_UNITS, SUPPORTED_ACTION_SCHEMAS

_ACTION_TYPES = ('BODY_VELOCITY', 'ATTITUDE_THRUST', 'BODY_RATE_THRUST')


def _finite(name, value):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value)):
        raise ValueError(name + ' must be a finite number')


def _text(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(name + ' must be a nonempty string')


@dataclass(frozen=True)
class VelocityPayload:
    """Physical units only; axis validity is explicit and never inferred."""
    vx_forward_mps: float = 0.0
    vy_left_mps: float = 0.0
    vz_up_mps: float = 0.0
    yaw_rate_ccw_world_radps: float = 0.0
    axis_validity: tuple[bool, bool, bool, bool] = (False, False, False, False)
    frame: str = ACTION_FRAME
    units: str = ACTION_UNITS

    def __post_init__(self):
        for name in ('vx_forward_mps', 'vy_left_mps', 'vz_up_mps',
                     'yaw_rate_ccw_world_radps'):
            _finite(name, getattr(self, name))
        if (not isinstance(self.axis_validity, tuple) or len(self.axis_validity) != 4
                or any(not isinstance(flag, bool) for flag in self.axis_validity)):
            raise ValueError('axis_validity must be a 4-bool tuple')
        if self.frame != ACTION_FRAME:
            raise ValueError('frame must be ' + ACTION_FRAME)
        if self.units != ACTION_UNITS:
            raise ValueError('units must be ' + ACTION_UNITS)

    def fields(self):
        return (self.vx_forward_mps, self.vy_left_mps, self.vz_up_mps,
                self.yaw_rate_ccw_world_radps)

    def is_finite(self):
        try:
            return all(math.isfinite(value) for value in self.fields())
        except TypeError:
            return False

    def valid_mask(self):
        mask = 0
        for index, flag in enumerate(self.axis_validity):
            if flag:
                mask |= 1 << index
        return mask

    def to_ned(self, yaw_ned_rad, *, yaw_valid=True):
        """V2.2 10.4.1 matrix; None when heading is not valid."""
        if not yaw_valid:
            return None
        try:
            yaw = float(yaw_ned_rad)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(yaw):
            return None
        c, s = math.cos(yaw), math.sin(yaw)
        vx, vy, vz = self.vx_forward_mps, self.vy_left_mps, self.vz_up_mps
        return (c * vx + s * vy, s * vx - c * vy, -vz)


def _canonical(payload):
    return {
        'vx_forward_mps': payload.vx_forward_mps,
        'vy_left_mps': payload.vy_left_mps,
        'vz_up_mps': payload.vz_up_mps,
        'yaw_rate_ccw_world_radps': payload.yaw_rate_ccw_world_radps,
        'axis_validity': list(payload.axis_validity),
        'frame': payload.frame,
        'units': payload.units,
    }


@dataclass(frozen=True)
class ActionEnvelope:
    """Every executable action is wrapped; identity and digest are immutable."""
    header: MessageHeader
    action_id: str
    observation_id: str
    input_capture_interval_ns: tuple[int, int]
    earliest_input_safe_deadline_ns: int
    issued_at_monotonic_ns: int
    expires_at_monotonic_ns: int
    max_age_ms: int
    source: str
    policy_version: str
    payload: VelocityPayload
    action_type: str = 'BODY_VELOCITY'
    schema_version: str = ACTION_SCHEMA_ID

    def __post_init__(self):
        if not isinstance(self.header, MessageHeader):
            raise ValueError('header must be a MessageHeader')
        if self.schema_version not in SUPPORTED_ACTION_SCHEMAS:
            raise ValueError('unsupported action schema: ' + str(self.schema_version))
        _text('action_id', self.action_id)
        _text('observation_id', self.observation_id)
        _text('source', self.source)
        _text('policy_version', self.policy_version)
        if self.action_type not in _ACTION_TYPES:
            raise ValueError('unsupported action_type: ' + str(self.action_type))
        interval = self.input_capture_interval_ns
        if (not isinstance(interval, tuple) or len(interval) != 2
                or not all(is_counter(value) for value in interval)
                or interval[0] > interval[1]):
            raise ValueError('input_capture_interval_ns must be an ordered 2-counter tuple')
        if not interval[0] <= self.header.capture_timestamp_ns <= interval[1]:
            raise ValueError('header capture timestamp must lie inside the input interval')
        if not is_counter(self.earliest_input_safe_deadline_ns):
            raise ValueError('earliest_input_safe_deadline_ns must be a counter')
        if not is_counter(self.issued_at_monotonic_ns):
            raise ValueError('issued_at_monotonic_ns must be a counter')
        if not is_counter(self.expires_at_monotonic_ns):
            raise ValueError('expires_at_monotonic_ns must be a counter')
        if self.issued_at_monotonic_ns < interval[1]:
            raise ValueError('action cannot be issued before its input capture ends')
        if self.expires_at_monotonic_ns <= self.issued_at_monotonic_ns:
            raise ValueError('expires_at must be later than issued_at')
        if self.expires_at_monotonic_ns > self.earliest_input_safe_deadline_ns:
            raise ValueError('expires_at must not exceed the earliest input safe deadline')
        if not is_counter(self.max_age_ms) or self.max_age_ms == 0:
            raise ValueError('max_age_ms must be a positive integer')
        if not isinstance(self.payload, VelocityPayload):
            raise ValueError('payload must be a VelocityPayload')

    @property
    def sequence_id(self):
        return self.header.sequence_id

    @property
    def system_boot_id(self):
        return self.header.system_boot_id

    @property
    def mission_epoch(self):
        return self.header.mission_epoch

    @property
    def localization_epoch(self):
        return self.header.localization_epoch

    @property
    def control_epoch(self):
        return self.header.control_epoch

    @property
    def clock_id(self):
        return self.header.clock_id

    @property
    def px4_boot_id(self):
        return self.header.px4_boot_id

    @property
    def sync_generation(self):
        return self.header.sync_generation

    def identity(self):
        return (self.header.system_boot_id, self.header.control_epoch,
                self.source, self.header.sequence_id, self.action_id)

    def digest(self):
        document = {
            'schema_version': self.schema_version,
            'action_type': self.action_type,
            'action_id': self.action_id,
            'observation_id': self.observation_id,
            'input_capture_interval_ns': list(self.input_capture_interval_ns),
            'earliest_input_safe_deadline_ns': self.earliest_input_safe_deadline_ns,
            'issued_at_monotonic_ns': self.issued_at_monotonic_ns,
            'expires_at_monotonic_ns': self.expires_at_monotonic_ns,
            'max_age_ms': self.max_age_ms,
            'source': self.source,
            'policy_version': self.policy_version,
            'payload': _canonical(self.payload),
            'system_boot_id': self.header.system_boot_id,
            'mission_epoch': self.header.mission_epoch,
            'localization_epoch': self.header.localization_epoch,
            'control_epoch': self.header.control_epoch,
            'clock_id': self.header.clock_id,
            'px4_boot_id': self.header.px4_boot_id,
            'sync_generation': self.header.sync_generation,
            'sequence_id': self.header.sequence_id,
            'capture_timestamp_ns': self.header.capture_timestamp_ns,
            'source_id': self.header.source_id,
        }
        encoded = json.dumps(document, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True)
        return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def build_velocity_envelope(header, payload, *, observation_id,
                            input_capture_interval_ns,
                            earliest_input_safe_deadline_ns, ttl_ns, max_age_ms,
                            source, policy_version, issued_at_monotonic_ns=None,
                            action_id=None, expires_at_monotonic_ns=None):
    """TTL starts at issue time and is clipped by the earliest safe input deadline."""
    if not isinstance(header, MessageHeader):
        raise ValueError('header must be a MessageHeader')
    if not isinstance(payload, VelocityPayload):
        raise ValueError('payload must be a VelocityPayload')
    if not is_counter(ttl_ns) or ttl_ns == 0:
        raise ValueError('ttl_ns must be a positive integer')
    issued = header.capture_timestamp_ns if issued_at_monotonic_ns is None else issued_at_monotonic_ns
    if not is_counter(issued):
        raise ValueError('issued_at_monotonic_ns must be a counter')
    computed = min(issued + ttl_ns, earliest_input_safe_deadline_ns)
    expires = computed if expires_at_monotonic_ns is None else expires_at_monotonic_ns
    if action_id is None:
        action_id = '{}-{}-{}-{}'.format(source, header.system_boot_id,
                                         header.control_epoch, header.sequence_id)
    return ActionEnvelope(
        header=header, action_id=action_id, observation_id=observation_id,
        input_capture_interval_ns=input_capture_interval_ns,
        earliest_input_safe_deadline_ns=earliest_input_safe_deadline_ns,
        issued_at_monotonic_ns=issued, expires_at_monotonic_ns=expires,
        max_age_ms=max_age_ms, source=source, policy_version=policy_version,
        payload=payload)


def from_velocity_v1(command, *, yaw_enu_rad, header, observation_id,
                     earliest_input_safe_deadline_ns, max_age_ms, axis_validity,
                     policy_version, ttl_ns=150_000_000,
                     issued_at_monotonic_ns=None, action_id=None):
    """Explicit v1 -> v2 adapter. Validity and provenance cannot be defaulted."""
    if not isinstance(command, VelocityCommand) or command.schema_id != VELOCITY_V1_SCHEMA_ID:
        raise ValueError('command must be a boom_birds.velocity.v1 VelocityCommand')
    _text('observation_id', observation_id)
    _text('policy_version', policy_version)
    if (not isinstance(axis_validity, tuple) or len(axis_validity) != 4
            or any(not isinstance(flag, bool) for flag in axis_validity)):
        raise ValueError('axis_validity must be a 4-bool tuple provided by the caller')
    if not is_counter(earliest_input_safe_deadline_ns):
        raise ValueError('earliest_input_safe_deadline_ns must be a counter')
    try:
        yaw = float(yaw_enu_rad)
    except (TypeError, ValueError):
        raise ValueError('yaw_enu_rad must be a finite number')
    if not math.isfinite(yaw):
        raise ValueError('yaw_enu_rad must be a finite number')
    east, north, up = command.velocity_enu_mps
    c, s = math.cos(yaw), math.sin(yaw)
    payload = VelocityPayload(
        vx_forward_mps=c * east + s * north,
        vy_left_mps=-s * east + c * north,
        vz_up_mps=up,
        yaw_rate_ccw_world_radps=command.yaw_rate_rad_s,
        axis_validity=axis_validity)
    capture = header.capture_timestamp_ns
    return build_velocity_envelope(
        header, payload, observation_id=observation_id,
        input_capture_interval_ns=(capture, capture),
        earliest_input_safe_deadline_ns=earliest_input_safe_deadline_ns,
        ttl_ns=ttl_ns, max_age_ms=max_age_ms, source='STUDENT',
        policy_version=policy_version,
        issued_at_monotonic_ns=issued_at_monotonic_ns, action_id=action_id)
