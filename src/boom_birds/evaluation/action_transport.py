"""Deterministic delayed action arrival gate (V2.2 16/17 TTL, epochs, ownership).

A fixed transport delay is replayed in simulation time (no sleeping). Every
setpoint is wrapped in an immutable :class:`ActionTicket` at dispatch time; when
the ticket becomes due the gate re-checks, in ``V2.2 27.2`` order:

1. expiry (``now_s >= expires_at_s`` -> ``ACTION_EXPIRED``),
2. the six-tuple context epochs ``(system_boot, mission, localization, control,
   px4_boot, sync_generation)`` -> the matching ``REJECT_*`` code,
3. sync generation -> ``REJECT_SYNC_OR_PX4_BOOT``,
4. control owner -> ``REJECT_OWNER``.

Only arrivals that pass become active. A rejected action never reaches the
wrapped executor. The active setpoint keeps its original ``expires_at_s`` and is
replayed unchanged (no renewal, no TTL extension) until it expires or its
context/ownership turns invalid; at that moment the executor receives ``None``.
Rejection is not an immediate physical stop, and an accepted old setpoint is
still executed (``HOLDING``) while it is valid.

``last_transport`` is refreshed after every :meth:`DelayedVelocityExecutor.step`
with the fixed keys below so the runner/verifier can record the raw arrival
facts:

    status: 'APPLIED' | 'HOLDING' | 'REJECTED' | 'NONE'
    action_id, executed_action_id, issued_at_s, expires_at_s,
    scheduled_arrival_s, arrival_s, dispatch_delay_s, arrival_age_s,
    reason, executed, applied, rejections_this_step

``status`` semantics: ``APPLIED`` = a new arrival was accepted and is now
active; ``HOLDING`` = no arrival event this step, the still-valid active
setpoint was executed again; ``REJECTED`` = at least one arrival was rejected
and none was accepted this step; ``NONE`` = no setpoint reached the executor.
Timing contract (verifier recomputes it): ``scheduled_arrival_s`` is
``issued_at_s + delay at queue time`` (a later ``set_delay`` never moves an
already queued item), ``arrival_s`` is the ``now_s`` at which the ticket became
due, ``arrival_age_s = arrival_s - issued_at_s`` and
``dispatch_delay_s = scheduled_arrival_s - issued_at_s``. For ``HOLDING`` the
timing fields describe the active ticket's *original* arrival (so the ages stay
constant) and ``applied['age_s']`` grows. For ``REJECTED`` the timing fields
describe the last rejected arrival, ``executed`` is ``False``,
``executed_action_id`` never names the rejected action, and ``applied`` is the
still-valid old active snapshot (``is_held=True``) when the executor kept
receiving it.
"""
import math
from collections import Counter
from dataclasses import dataclass, replace

from boom_birds.contracts import reasons
from boom_birds.contracts.ownership import ControlOwner

_EPOCH_FIELDS = ('system_boot', 'mission', 'localization', 'control',
                 'px4_boot', 'sync_generation')
_EPOCH_REASONS = (
    reasons.REJECT_BOOT_MISMATCH,
    reasons.REJECT_MISSION_EPOCH,
    reasons.REJECT_LOCALIZATION_EPOCH,
    reasons.REJECT_CONTROL_EPOCH,
    reasons.REJECT_SYNC_OR_PX4_BOOT,
    reasons.REJECT_SYNC_OR_PX4_BOOT,
)
_UNPUBLISHABLE_OWNERS = frozenset({ControlOwner.NONE,
                                   ControlOwner.PX4_CONFIGURED_FAILSAFE})
# Control steps are sampled at e.g. 50 ms; `now_s + delay_s` can exceed the
# intended tick by ~1e-15 s in binary float. Without a guard the ticket would be
# delivered one whole tick late, which would silently change arrival age/TTL
# verdicts (100 ms -> 150 ms). The epsilon only absorbs representation error,
# it never reorders items.
_TIME_EPSILON_S = 1e-9


def _finite_nonnegative(value, name):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0):
        raise ValueError(name + ' must be a nonnegative finite number')
    return float(value)


def _validate_epochs(epochs):
    if epochs is None:
        return None
    try:
        epochs = tuple(epochs)
    except TypeError:
        raise ValueError('epochs must be a 6-tuple of nonnegative integers')
    if len(epochs) != 6:
        raise ValueError('epochs must be a 6-tuple: ' + ', '.join(_EPOCH_FIELDS))
    for name, value in zip(_EPOCH_FIELDS, epochs):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError('epochs.' + name + ' must be a nonnegative integer')
    return epochs


def _empty_transport():
    return {
        'status': 'NONE',
        'action_id': '',
        'executed_action_id': '',
        'issued_at_s': 0.0,
        'expires_at_s': 0.0,
        'scheduled_arrival_s': 0.0,
        'arrival_s': 0.0,
        'dispatch_delay_s': 0.0,
        'arrival_age_s': 0.0,
        'reason': reasons.REJECT_NO_CACHED_ACTION,
        'executed': False,
        'applied': None,
        'rejections_this_step': [],
    }


@dataclass(order=True)
class _Item:
    delivery_s: float
    sequence: int
    action: object = None
    command: tuple = ()


class DelayedActionQueue:
    """Monotonic due-time delivery queue; keeps every scheduled item."""
    def __init__(self):
        self._items = []
        self._seq = 0
        self.rejected = []
    def schedule(self, delivery_s, action, command=()):
        _finite_nonnegative(delivery_s, 'delivery_s')
        self._seq += 1
        self._items.append(_Item(float(delivery_s), self._seq, action,
                                 tuple(command)))
        self._items.sort()
    def take_due(self, now_s):
        deadline = now_s + _TIME_EPSILON_S
        due = [x for x in self._items if x.delivery_s <= deadline]
        self._items = [x for x in self._items if x.delivery_s > deadline]
        return [(x.action, x.command) for x in due]
    def clear(self):
        n = len(self._items); self._items = []; return n
    def pending(self):
        return len(self._items)


@dataclass(frozen=True)
class ActionTicket:
    """Immutable dispatch record; arrival checks use exactly these values."""
    setpoint: object
    action_id: str
    issued_at_s: float
    expires_at_s: float
    control_epoch: int
    epochs: tuple | None
    sync_generation: int
    owner: str | None
    dispatch_s: float
    scheduled_arrival_s: float
    delivery_s: float = 0.0
    arrival_s: float = 0.0


class DelayedVelocityExecutor:
    """Wrap an executor with a deterministic transport delay and arrival gate."""

    def __init__(self, executor, delay_s):
        self._inner = executor
        self._delay_s = _finite_nonnegative(delay_s, 'delay_s')
        self._queue = DelayedActionQueue()
        self._active = None
        self._epochs = None
        self._owner = None
        self.arrivals = []
        self.rejections = Counter()
        self.last_transport = _empty_transport()
        self.dropped_active = 0

    # -- configuration -------------------------------------------------
    @property
    def delay_s(self):
        return self._delay_s

    def set_delay(self, delay_s):
        """Change the delay for future dispatches; queued items keep their slot."""
        self._delay_s = _finite_nonnegative(delay_s, 'delay_s')

    def update_context(self, *, epochs, owner):
        """Record the runner's current context before the next dispatch."""
        self._epochs = _validate_epochs(epochs)
        if owner is not None and not isinstance(owner, str):
            raise ValueError('owner must be a string or None')
        self._owner = owner

    # -- state ---------------------------------------------------------
    @property
    def pending(self):
        return self._queue.pending()

    @property
    def active_setpoint(self):
        return None if self._active is None else self._active.setpoint

    @property
    def active_action_id(self):
        return '' if self._active is None else self._active.action_id

    @property
    def control_epoch(self):
        return self._inner.control_epoch

    @control_epoch.setter
    def control_epoch(self, value):
        self._inner.control_epoch = value

    def clear(self):
        """Drop queued and active actions (episode isolation); keep history."""
        count = self._queue.clear()
        self._active = None
        self.last_transport = _empty_transport()
        return count

    def reset(self, state=None):
        self.clear()
        return self._inner.reset(state)

    # -- per-step arrival gate ----------------------------------------
    def step(self, setpoint, state, now_s):
        if (not isinstance(now_s, (int, float)) or isinstance(now_s, bool)
                or not math.isfinite(now_s)):
            raise ValueError('now_s must be a finite number')
        now_s = float(now_s)
        rejections_this_step = []
        accepted = None
        rejected = None
        rejected_reason = ''

        if setpoint is not None:
            ticket = self._make_ticket(setpoint, now_s)
            self._queue.schedule(ticket.delivery_s, ticket, ())

        for ticket, _command in self._queue.take_due(now_s):
            reason = self._arrival_verdict(ticket, now_s)
            self.arrivals.append(self._arrival_record(ticket, now_s, reason))
            if reason == reasons.ACCEPT:
                accepted = replace(ticket, arrival_s=now_s)
                self._active = accepted
            else:
                self.rejections[reason] += 1
                rejected = ticket
                rejected_reason = reason
                rejections_this_step.append({
                    'action_id': ticket.action_id,
                    'reason': reason,
                    'arrival_s': now_s,
                    'arrival_age_s': now_s - ticket.issued_at_s,
                })

        drop_reason = ''
        if self._active is not None:
            reason = self._arrival_verdict(self._active, now_s)
            if reason != reasons.ACCEPT:
                drop_reason = reason
                self.dropped_active += 1
                self._active = None

        selected = None if self._active is None else self._active.setpoint
        inner_result = self._inner.step(selected, state, now_s)
        self.last_transport = self._transport_record(
            now_s, accepted, rejected, rejected_reason, drop_reason,
            selected, inner_result, rejections_this_step)
        return inner_result

    # -- helpers -------------------------------------------------------
    def _make_ticket(self, setpoint, now_s):
        metadata_epochs = _validate_epochs(getattr(setpoint, 'epochs', None))
        epochs = metadata_epochs if metadata_epochs is not None else self._epochs
        sync_generation = getattr(setpoint, 'sync_generation', -1)
        if (not isinstance(sync_generation, int)
                or isinstance(sync_generation, bool) or sync_generation < -1):
            raise ValueError('setpoint.sync_generation must be -1 or a '
                             'nonnegative integer')
        if sync_generation < 0 and self._epochs is not None:
            sync_generation = self._epochs[5]
        action_id = getattr(setpoint, 'action_id', '')
        if not isinstance(action_id, str):
            raise ValueError('setpoint.action_id must be a string')
        issued_at_s = float(getattr(setpoint, 'issued_at_s', 0.0))
        return ActionTicket(
            setpoint=setpoint,
            action_id=action_id,
            issued_at_s=issued_at_s,
            expires_at_s=float(getattr(setpoint, 'expires_at_s', 0.0)),
            control_epoch=getattr(setpoint, 'control_epoch', 0),
            epochs=epochs,
            sync_generation=sync_generation,
            owner=self._owner,
            dispatch_s=now_s,
            scheduled_arrival_s=issued_at_s + self._delay_s,
            delivery_s=now_s + self._delay_s,
        )

    def _owner_allowed(self):
        if self._owner is None:
            return True
        return self._owner not in _UNPUBLISHABLE_OWNERS

    def _arrival_verdict(self, ticket, now_s):
        """V2.2 27.2 order for a delayed arrival; returns a stable reason code."""
        if now_s >= ticket.expires_at_s:
            return reasons.ACTION_EXPIRED
        current = self._epochs
        if ticket.epochs is not None and current is not None:
            for index, expected in enumerate(ticket.epochs):
                if expected != current[index]:
                    return _EPOCH_REASONS[index]
        if (ticket.sync_generation >= 0 and current is not None
                and ticket.sync_generation != current[5]):
            return reasons.REJECT_SYNC_OR_PX4_BOOT
        if not self._owner_allowed():
            return reasons.REJECT_OWNER
        if ticket.owner is not None and self._owner != ticket.owner:
            return reasons.REJECT_OWNER
        return reasons.ACCEPT

    def _arrival_record(self, ticket, now_s, reason):
        return {
            'status': 'APPLIED' if reason == reasons.ACCEPT else 'REJECTED',
            'reason': reason,
            'action_id': ticket.action_id,
            'issued_at_s': ticket.issued_at_s,
            'expires_at_s': ticket.expires_at_s,
            'scheduled_arrival_s': ticket.scheduled_arrival_s,
            'arrival_s': now_s,
            'arrival_age_s': now_s - ticket.issued_at_s,
            'dispatch_delay_s': ticket.scheduled_arrival_s - ticket.issued_at_s,
            'control_epoch': ticket.control_epoch,
            'sync_generation': ticket.sync_generation,
            'epochs': None if ticket.epochs is None else list(ticket.epochs),
            'gate_accepted': reason == reasons.ACCEPT,
        }

    @staticmethod
    def _fill_action(record, ticket, arrival_s):
        record['issued_at_s'] = ticket.issued_at_s
        record['expires_at_s'] = ticket.expires_at_s
        record['scheduled_arrival_s'] = ticket.scheduled_arrival_s
        record['arrival_s'] = arrival_s
        record['arrival_age_s'] = arrival_s - ticket.issued_at_s
        record['dispatch_delay_s'] = ticket.scheduled_arrival_s - ticket.issued_at_s

    @staticmethod
    def _applied_snapshot(ticket, now_s, *, is_held):
        setpoint = ticket.setpoint
        return {
            'vx_forward_mps': float(getattr(setpoint, 'vx_forward_mps', 0.0)),
            'vy_left_mps': float(getattr(setpoint, 'vy_left_mps', 0.0)),
            'vz_up_mps': float(getattr(setpoint, 'vz_up_mps', 0.0)),
            'yaw_rate_ccw_world_radps': float(
                getattr(setpoint, 'yaw_rate_ccw_world_radps', 0.0)),
            'action_id': ticket.action_id,
            'issued_at_ns': int(round(ticket.issued_at_s * 1_000_000_000)),
            'expires_at_ns': int(round(ticket.expires_at_s * 1_000_000_000)),
            'age_s': now_s - ticket.issued_at_s,
            'is_held': bool(is_held),
        }

    def _transport_record(self, now_s, accepted, rejected, rejected_reason,
                          drop_reason, selected, inner_result,
                          rejections_this_step):
        executed = selected is not None and inner_result.reason == reasons.ACCEPT
        active = self._active
        record = _empty_transport()
        record['executed'] = executed
        record['rejections_this_step'] = rejections_this_step
        if accepted is not None:
            # a fresh arrival was accepted and is now the effective setpoint
            record['status'] = 'APPLIED'
            record['action_id'] = accepted.action_id
            self._fill_action(record, accepted, accepted.arrival_s)
            record['reason'] = (reasons.ACCEPT if executed
                                else inner_result.reason)
            if executed and active is not None:
                record['executed_action_id'] = active.action_id
                record['applied'] = self._applied_snapshot(
                    active, now_s, is_held=False)
        elif rejected is not None:
            # a rejected arrival is never executed; an already-valid old
            # active keeps running and is reported through `applied`
            record['status'] = 'REJECTED'
            self._fill_action(record, rejected, now_s)
            record['reason'] = rejected_reason
            record['executed'] = False
            record['executed_action_id'] = ''
            if active is not None:
                record['applied'] = self._applied_snapshot(
                    active, now_s, is_held=True)
        elif active is not None:
            record['status'] = 'HOLDING'
            self._fill_action(record, active, active.arrival_s)
            record['reason'] = (reasons.ACCEPT if executed
                                else inner_result.reason)
            if executed:
                record['executed_action_id'] = active.action_id
                record['applied'] = self._applied_snapshot(
                    active, now_s, is_held=True)
        else:
            record['status'] = 'NONE'
            record['reason'] = drop_reason or reasons.REJECT_NO_CACHED_ACTION
        return record

    def __getattr__(self, name):
        return getattr(self._inner, name)
