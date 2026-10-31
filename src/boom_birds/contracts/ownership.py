"""V2.2 16.8 / 26.7 control ownership and PENDING/ACTIVE handover."""
from dataclasses import dataclass

from .types import is_counter


class ControlOwner:
    NONE = 'NONE'
    STUDENT = 'STUDENT'
    IMPACT_RECOVERY = 'IMPACT_RECOVERY'
    SAFETY_SUPERVISOR = 'SAFETY_SUPERVISOR'
    PX4_CONFIGURED_FAILSAFE = 'PX4_CONFIGURED_FAILSAFE'
    ALL = frozenset({NONE, STUDENT, IMPACT_RECOVERY, SAFETY_SUPERVISOR,
                     PX4_CONFIGURED_FAILSAFE})


HANDOVER_PENDING = 'PENDING'
HANDOVER_CONFIRMED = 'CONFIRMED'
HANDOVER_TIMEOUT = 'TIMEOUT'
HANDOVER_FAILED = 'FAILED'


@dataclass(frozen=True)
class HandoverRecord:
    previous_owner: str
    new_owner: str
    control_epoch_before: int
    control_epoch_after: int | None
    requested_px4_mode: str | None
    ack_required: bool
    ack_received: bool
    actual_px4_mode: str | None
    handover_timestamp_ns: int
    timeout: bool
    result: str


class OwnershipState:
    """Exactly one publishable source; ownership changes must change control_epoch."""

    def __init__(self, owner=ControlOwner.STUDENT, *, control_epoch=0, now_ns=0):
        if owner not in ControlOwner.ALL:
            raise ValueError('unknown control owner: ' + str(owner))
        if not is_counter(control_epoch):
            raise ValueError('control_epoch must be a counter')
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        self._owner = owner
        self._control_epoch = control_epoch
        self._pending = None
        self._deadline_ns = None
        self._history = []

    @property
    def owner(self):
        return self._owner

    @property
    def control_epoch(self):
        return self._control_epoch

    @property
    def pending(self):
        return self._pending

    @property
    def history(self):
        return tuple(self._history)

    def bump_control_epoch(self):
        self._control_epoch += 1
        return self._control_epoch

    def request_handover(self, new_owner, now_ns, *, timeout_ns,
                         requested_px4_mode=None, ack_required=False):
        if new_owner not in ControlOwner.ALL:
            raise ValueError('unknown control owner: ' + str(new_owner))
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        if not is_counter(timeout_ns) or timeout_ns == 0:
            raise ValueError('timeout_ns must be a positive counter')
        if self._pending is not None:
            raise ValueError('a handover is already pending')
        record = HandoverRecord(
            previous_owner=self._owner, new_owner=new_owner,
            control_epoch_before=self._control_epoch, control_epoch_after=None,
            requested_px4_mode=requested_px4_mode, ack_required=bool(ack_required),
            ack_received=False, actual_px4_mode=None,
            handover_timestamp_ns=now_ns, timeout=False, result=HANDOVER_PENDING)
        self._pending = record
        self._deadline_ns = now_ns + timeout_ns
        return record

    def complete_handover(self, now_ns, *, ack_received=False, actual_px4_mode=None):
        if self._pending is None:
            raise ValueError('no handover is pending')
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        record = HandoverRecord(
            previous_owner=self._pending.previous_owner,
            new_owner=self._pending.new_owner,
            control_epoch_before=self._pending.control_epoch_before,
            control_epoch_after=self._control_epoch + 1,
            requested_px4_mode=self._pending.requested_px4_mode,
            ack_required=self._pending.ack_required,
            ack_received=bool(ack_received),
            actual_px4_mode=actual_px4_mode,
            handover_timestamp_ns=now_ns, timeout=False,
            result=HANDOVER_CONFIRMED)
        self._owner = record.new_owner
        self._control_epoch = record.control_epoch_after
        self._pending = None
        self._deadline_ns = None
        self._history.append(record)
        return record

    def fail_handover(self, now_ns, *, result=HANDOVER_FAILED):
        if self._pending is None:
            raise ValueError('no handover is pending')
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        record = HandoverRecord(
            previous_owner=self._pending.previous_owner,
            new_owner=self._pending.new_owner,
            control_epoch_before=self._pending.control_epoch_before,
            control_epoch_after=None,
            requested_px4_mode=self._pending.requested_px4_mode,
            ack_required=self._pending.ack_required,
            ack_received=False, actual_px4_mode=None,
            handover_timestamp_ns=now_ns, timeout=(result == HANDOVER_TIMEOUT),
            result=result)
        self._pending = None
        self._deadline_ns = None
        self._history.append(record)
        return record

    def tick(self, now_ns):
        if not is_counter(now_ns):
            raise ValueError('now_ns must be a counter')
        if self._pending is not None and now_ns >= self._deadline_ns:
            return self.fail_handover(now_ns, result=HANDOVER_TIMEOUT)
        return None

    def publishable_source(self):
        if self._pending is not None:
            if self._pending.new_owner == ControlOwner.PX4_CONFIGURED_FAILSAFE:
                return None
            return self._pending.new_owner
        if self._owner in (ControlOwner.NONE, ControlOwner.PX4_CONFIGURED_FAILSAFE):
            return None
        return self._owner

    def can_publish(self, source, control_epoch):
        if not is_counter(control_epoch) or control_epoch != self._control_epoch:
            return False
        allowed = self.publishable_source()
        return allowed is not None and source == allowed
