"""V2.2 16.6 / 17.3 / 27.3 action admission, resend and pre-send checks."""
import math
import threading
from dataclasses import dataclass

from . import reasons
from .action_v2 import ActionEnvelope
from .context import ContractContext
from .ownership import ControlOwner
from .types import ActionLimits, is_counter
from .versions import ACTION_FRAME, ACTION_UNITS, SUPPORTED_ACTION_SCHEMAS

ADMIT_NEW = 'ADMIT_NEW'
SEND_CACHED = 'SEND_CACHED'
STAGES = (ADMIT_NEW, SEND_CACHED)
_EPSILON = 1e-12


@dataclass(frozen=True)
class ActionAdmissionConfig:
    limits: ActionLimits | None = None
    ttl_ns: int = 150_000_000
    max_age_ms: int = 150
    allowed_observation_age_ns: int = 250_000_000
    require_vertical_integrity: bool = True
    allow_partial_axes: bool = False

    def __post_init__(self):
        if self.limits is None:
            object.__setattr__(self, 'limits', ActionLimits())
        if not isinstance(self.limits, ActionLimits):
            raise ValueError('limits must be an ActionLimits')
        for name in ('ttl_ns', 'max_age_ms', 'allowed_observation_age_ns'):
            value = getattr(self, name)
            if not is_counter(value) or value == 0:
                raise ValueError(name + ' must be a positive integer')
        for name in ('require_vertical_integrity', 'allow_partial_axes'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(name + ' must be a bool')


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    reason: str
    is_new_admission: bool
    sequence_id: int | None
    expired: bool = False


def required_estimates(action, config):
    """V2.2 26.6/26.7 plus 10.4.3 vertical-control integrity by default."""
    needed = ['attitude_valid', 'angular_rate_valid', 'yaw_valid']
    vx, vy, vz, _yaw = action.payload.axis_validity
    if vx or vy:
        needed.append('xy_velocity_valid')
    if vz:
        needed.append('z_velocity_valid')
    if config.require_vertical_integrity:
        needed.extend(['thrust_source_valid', 'height_valid'])
    return tuple(needed)


def validate_action(action, context, now_ns, *, stage, config):
    """V2.2 27.3 order. Returns a reason code; production code never asserts."""
    if stage not in STAGES:
        raise ValueError('unknown admission stage: ' + str(stage))
    if not isinstance(action, ActionEnvelope) or not isinstance(context, ContractContext):
        return reasons.REJECT_INVALID
    if not is_counter(now_ns):
        return reasons.REJECT_INVALID
    if not isinstance(config, ActionAdmissionConfig):
        raise ValueError('config must be an ActionAdmissionConfig')
    if action.schema_version not in SUPPORTED_ACTION_SCHEMAS:
        return reasons.REJECT_SCHEMA_UNSUPPORTED
    if action.system_boot_id != context.system_boot_id:
        return reasons.REJECT_BOOT_MISMATCH
    if action.mission_epoch != context.mission_epoch:
        return reasons.REJECT_MISSION_EPOCH
    if action.localization_epoch != context.localization_epoch:
        return reasons.REJECT_LOCALIZATION_EPOCH
    if action.control_epoch != context.control_epoch:
        return reasons.REJECT_CONTROL_EPOCH
    if action.clock_id != context.clock_id:
        return reasons.REJECT_CLOCK_DOMAIN
    if not action.header.sync_valid or action.sync_generation != context.sync_generation:
        return reasons.REJECT_SYNC_OR_PX4_BOOT
    if action.px4_boot_id is None or action.px4_boot_id != context.px4_boot_id:
        return reasons.REJECT_SYNC_OR_PX4_BOOT
    if action.issued_at_monotonic_ns > now_ns:
        return reasons.REJECT_NOT_YET_VALID
    if now_ns >= action.expires_at_monotonic_ns:
        return reasons.REJECT_TTL_EXPIRED
    if now_ns >= action.earliest_input_safe_deadline_ns:
        return reasons.REJECT_INPUT_DEADLINE
    if action.expires_at_monotonic_ns > action.earliest_input_safe_deadline_ns:
        return reasons.REJECT_INPUT_DEADLINE
    observation_age_ns = now_ns - action.input_capture_interval_ns[1]
    if observation_age_ns < 0 or observation_age_ns > config.allowed_observation_age_ns:
        return reasons.REJECT_STALE_OBSERVATION
    allowed_source = (context.pending_owner if context.pending_owner is not None
                      else context.control_owner)
    if allowed_source in (ControlOwner.NONE, ControlOwner.PX4_CONFIGURED_FAILSAFE):
        return reasons.REJECT_OWNER
    if action.source != allowed_source:
        return reasons.REJECT_OWNER
    if not action.payload.is_finite():
        return reasons.REJECT_NONFINITE
    if action.payload.frame != ACTION_FRAME or action.payload.units != ACTION_UNITS:
        return reasons.REJECT_FRAME
    if not config.allow_partial_axes and not all(action.payload.axis_validity):
        return reasons.REJECT_PARTIAL_AXIS_UNSUPPORTED
    for name in required_estimates(action, config):
        if not getattr(context.estimates, name, False):
            return reasons.REJECT_ESTIMATE_INVALID
    limits = config.limits
    vx, vy, vz, yaw_rate = action.payload.fields()
    if math.hypot(vx, vy) > limits.horizontal_mps + _EPSILON:
        return reasons.REJECT_LIMITS
    if abs(vz) > limits.vertical_mps + _EPSILON:
        return reasons.REJECT_LIMITS
    if abs(yaw_rate) > limits.yaw_rate_rad_s + _EPSILON:
        return reasons.REJECT_LIMITS
    return reasons.ACCEPT


class ActionArbiter:
    """Single admission point; sequence/cache commit happens under one lock."""

    def __init__(self, config=None):
        self.config = config if config is not None else ActionAdmissionConfig()
        if not isinstance(self.config, ActionAdmissionConfig):
            raise ValueError('config must be an ActionAdmissionConfig')
        self._lock = threading.Lock()
        self._last_sequence = {}
        self._cached = None
        self._cached_digest = None

    @property
    def cached_action(self):
        return self._cached

    def revoke(self, reason=reasons.ACTION_REVOKED):
        with self._lock:
            had_action = self._cached is not None
            self._cached = None
            self._cached_digest = None
            return had_action

    def admit_new(self, action, context, now_ns):
        with self._lock:
            reason = validate_action(action, context, now_ns,
                                     stage=ADMIT_NEW, config=self.config)
            if reason != reasons.ACCEPT:
                return AdmissionResult(False, reason, False, None)
            key = (action.system_boot_id, action.control_epoch, action.source)
            last = self._last_sequence.get(key, -1)
            digest = action.digest()
            if action.sequence_id <= last:
                cached = self._cached
                if (cached is not None and digest == self._cached_digest
                        and action.action_id == cached.action_id):
                    return AdmissionResult(True, reasons.ACCEPT_RESEND, False,
                                           action.sequence_id)
                if cached is not None and action.sequence_id == cached.sequence_id:
                    return AdmissionResult(False, reasons.REJECT_SEQUENCE_REUSE, False, None)
                if cached is not None and action.sequence_id < cached.sequence_id:
                    return AdmissionResult(False, reasons.REJECT_SUPERSEDED, False, None)
                return AdmissionResult(False, reasons.REJECT_OUT_OF_ORDER, False, None)
            self._last_sequence[key] = action.sequence_id
            self._cached = action
            self._cached_digest = digest
            return AdmissionResult(True, reasons.ACCEPT, True, action.sequence_id)

    def send_cached(self, action, context, now_ns):
        with self._lock:
            cached = self._cached
            if cached is None:
                return AdmissionResult(False, reasons.REJECT_NO_CACHED_ACTION, False, None)
            if not isinstance(action, ActionEnvelope) or action.identity() != cached.identity():
                return AdmissionResult(False, reasons.REJECT_CACHE_IDENTITY_MISMATCH,
                                       False, None)
            if action.digest() != self._cached_digest:
                return AdmissionResult(False, reasons.REJECT_CACHE_DIGEST_MISMATCH,
                                       False, None)
            reason = validate_action(action, context, now_ns,
                                     stage=SEND_CACHED, config=self.config)
            if reason == reasons.REJECT_TTL_EXPIRED:
                sequence = cached.sequence_id
                self._cached = None
                self._cached_digest = None
                return AdmissionResult(False, reasons.ACTION_EXPIRED, False,
                                       sequence, expired=True)
            if reason != reasons.ACCEPT:
                return AdmissionResult(False, reason, False, cached.sequence_id)
            return AdmissionResult(True, reasons.ACCEPT, False, cached.sequence_id)


class LatestValidActionQueue:
    """latest-valid policy: never accumulate executable history."""

    def __init__(self):
        self._action = None

    def push(self, action):
        if not isinstance(action, ActionEnvelope):
            raise ValueError('action must be an ActionEnvelope')
        if self._action is None:
            self._action = action
            return
        current = (self._action.control_epoch, self._action.sequence_id)
        incoming = (action.control_epoch, action.sequence_id)
        if incoming >= current:
            self._action = action

    def peek(self, now_ns):
        if self._action is None:
            return None
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        if now_ns >= self._action.expires_at_monotonic_ns:
            self._action = None
            return None
        return self._action

    def clear(self):
        had_action = self._action is not None
        self._action = None
        return had_action
