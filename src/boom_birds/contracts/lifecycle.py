"""V2.2 16.4 / 16.3.2 / 17.6 impact, restart and hidden-state invalidation."""
from dataclasses import dataclass

from . import reasons
from .context import ContractContext, EstimatorState
from .ownership import ControlOwner, OwnershipState
from .types import is_counter
from .versions import MESSAGE_SCHEMA_ID


def _counter(name, value):
    if not is_counter(value):
        raise ValueError(name + ' must be a nonnegative integer')


def _text(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(name + ' must be a nonempty string')


@dataclass(frozen=True)
class ImpactEvent:
    event_id: str
    timestamp_ns: int
    uncertainty_ns: int = 0
    source: str = 'impact_detector'

    def __post_init__(self):
        _text('event_id', self.event_id)
        _counter('timestamp_ns', self.timestamp_ns)
        _counter('uncertainty_ns', self.uncertainty_ns)
        _text('source', self.source)

    def quarantine_window(self):
        return (max(0, self.timestamp_ns - self.uncertainty_ns),
                self.timestamp_ns + self.uncertainty_ns)


@dataclass(frozen=True)
class EpochChangeReport:
    reason: str
    changed: bool
    system_boot_id_before: int
    system_boot_id_after: int
    mission_epoch_before: int
    mission_epoch_after: int
    localization_epoch_before: int
    localization_epoch_after: int
    control_epoch_before: int
    control_epoch_after: int
    px4_boot_id_before: int
    px4_boot_id_after: int
    sync_generation_before: int
    sync_generation_after: int
    student_generation_after: int
    tracker_generation_after: int
    actions_revoked: bool
    messages_flushed: int
    handover: object
    invalidated: tuple


class GenerationGate:
    def __init__(self, name='generation'):
        _text('name', name)
        self._name = name
        self._generation = 0

    @property
    def generation(self):
        return self._generation

    def bump(self):
        self._generation += 1
        return self._generation

    def check(self, generation):
        return (isinstance(generation, int) and not isinstance(generation, bool)
                and generation == self._generation)


class TrackerState:
    def __init__(self):
        self._gate = GenerationGate('tracker')

    @property
    def generation(self):
        return self._gate.generation

    def invalidate(self):
        return self._gate.bump()

    def check(self, generation):
        return self._gate.check(generation)


class StudentState:
    """GRU hidden state and previous action die with their generation."""

    def __init__(self):
        self._gate = GenerationGate('student')
        self._previous_action = None

    @property
    def generation(self):
        return self._gate.generation

    def check(self, generation):
        return self._gate.check(generation)

    def reset(self, previous_action=None):
        generation = self._gate.bump()
        self._previous_action = (None if previous_action is None
                                 else tuple(previous_action))
        return generation

    def write_previous_action(self, generation, action):
        if not self._gate.check(generation):
            raise ValueError('stale student generation: ' + str(generation))
        self._previous_action = (None if action is None else tuple(action))

    def read_previous_action(self, generation):
        if not self._gate.check(generation):
            return None
        return self._previous_action


class EpochQueue:
    def __init__(self):
        self._items = []

    def push(self, item, *, localization_epoch, control_epoch):
        _counter('localization_epoch', localization_epoch)
        _counter('control_epoch', control_epoch)
        self._items.append((localization_epoch, control_epoch, item))

    def __len__(self):
        return len(self._items)

    def snapshot(self):
        return tuple(item for _loc, _ctrl, item in self._items)

    def clear(self):
        count = len(self._items)
        self._items = []
        return count

    def flush_older_than(self, *, localization_epoch=None, control_epoch=None):
        def keep(entry):
            loc, ctrl, _item = entry
            if localization_epoch is not None and loc < localization_epoch:
                return False
            if control_epoch is not None and ctrl < control_epoch:
                return False
            return True

        kept = [entry for entry in self._items if keep(entry)]
        removed = len(self._items) - len(kept)
        self._items = kept
        return removed


class EpochManager:
    """Atomic epoch transitions; old generations are never readable again."""

    def __init__(self, *, system_boot_id=0, mission_epoch=0, localization_epoch=0,
                 control_epoch=0, px4_boot_id=0, clock_id='host_monotonic',
                 sync_generation=0, sync_valid=False, now_ns=0):
        for name, value in (('system_boot_id', system_boot_id),
                            ('mission_epoch', mission_epoch),
                            ('localization_epoch', localization_epoch),
                            ('control_epoch', control_epoch),
                            ('px4_boot_id', px4_boot_id),
                            ('sync_generation', sync_generation),
                            ('now_ns', now_ns)):
            _counter(name, value)
        _text('clock_id', clock_id)
        if not isinstance(sync_valid, bool):
            raise ValueError('sync_valid must be a bool')
        self.system_boot_id = system_boot_id
        self.mission_epoch = mission_epoch
        self.localization_epoch = localization_epoch
        self.px4_boot_id = px4_boot_id
        self.clock_id = clock_id
        self.sync_generation = sync_generation
        self.sync_valid = sync_valid
        self.px4_state_revalidated = False
        self.ownership = OwnershipState(ControlOwner.STUDENT,
                                        control_epoch=control_epoch, now_ns=now_ns)
        self.student = StudentState()
        self.tracker = TrackerState()
        self.last_impact = None

    @property
    def control_epoch(self):
        return self.ownership.control_epoch

    def context(self, estimates=None):
        pending = self.ownership.pending
        return ContractContext(
            system_boot_id=self.system_boot_id,
            mission_epoch=self.mission_epoch,
            localization_epoch=self.localization_epoch,
            control_epoch=self.control_epoch,
            clock_id=self.clock_id,
            px4_boot_id=self.px4_boot_id,
            sync_generation=self.sync_generation,
            schema_version=MESSAGE_SCHEMA_ID,
            control_owner=self.ownership.owner,
            pending_owner=(pending.new_owner if pending is not None else None),
            estimates=estimates if estimates is not None else EstimatorState())

    def _snapshot(self):
        return {
            'system_boot_id': self.system_boot_id,
            'mission_epoch': self.mission_epoch,
            'localization_epoch': self.localization_epoch,
            'control_epoch': self.control_epoch,
            'px4_boot_id': self.px4_boot_id,
            'sync_generation': self.sync_generation,
        }

    def _report(self, reason, before, changed, *, actions_revoked=False,
                messages_flushed=0, handover=None, invalidated=()):
        return EpochChangeReport(
            reason=reason, changed=changed,
            system_boot_id_before=before['system_boot_id'],
            system_boot_id_after=self.system_boot_id,
            mission_epoch_before=before['mission_epoch'],
            mission_epoch_after=self.mission_epoch,
            localization_epoch_before=before['localization_epoch'],
            localization_epoch_after=self.localization_epoch,
            control_epoch_before=before['control_epoch'],
            control_epoch_after=self.control_epoch,
            px4_boot_id_before=before['px4_boot_id'],
            px4_boot_id_after=self.px4_boot_id,
            sync_generation_before=before['sync_generation'],
            sync_generation_after=self.sync_generation,
            student_generation_after=self.student.generation,
            tracker_generation_after=self.tracker.generation,
            actions_revoked=actions_revoked, messages_flushed=messages_flushed,
            handover=handover, invalidated=tuple(invalidated))

    def on_impact(self, event, now_ns, *, queue=None, arbiter=None,
                  handover_timeout_ns=500_000_000):
        if not isinstance(event, ImpactEvent):
            raise ValueError('event must be an ImpactEvent')
        _counter('now_ns', now_ns)
        before = self._snapshot()
        self.last_impact = event
        if self.ownership.pending is not None:
            self.ownership.fail_handover(now_ns, result='SUPERSEDED_BY_IMPACT')
        self.localization_epoch += 1
        self.ownership.bump_control_epoch()
        revoked = False
        if arbiter is not None:
            revoked = arbiter.revoke(reasons.ACTION_REVOKED_BY_IMPACT)
        flushed = 0
        if queue is not None:
            flushed = queue.flush_older_than(
                localization_epoch=self.localization_epoch,
                control_epoch=self.control_epoch)
        self.tracker.invalidate()
        self.student.reset()
        handover = self.ownership.request_handover(
            ControlOwner.IMPACT_RECOVERY, now_ns, timeout_ns=handover_timeout_ns,
            requested_px4_mode='OFFBOARD')
        return self._report('IMPACT', before, True, actions_revoked=revoked,
                            messages_flushed=flushed, handover=handover,
                            invalidated=('position_estimate', 'velocity_integral',
                                         'map_path', 'tracker_state',
                                         'student_hidden_state', 'previous_action',
                                         'message_queues'))

    def on_localization_reset(self, reason, now_ns, *, queue=None, arbiter=None):
        _text('reason', reason)
        _counter('now_ns', now_ns)
        before = self._snapshot()
        self.localization_epoch += 1
        revoked = arbiter.revoke(reasons.ACTION_REVOKED_BY_RESET) if arbiter is not None else False
        flushed = 0
        if queue is not None:
            flushed = queue.flush_older_than(localization_epoch=self.localization_epoch)
        self.tracker.invalidate()
        self.student.reset()
        return self._report('LOCALIZATION_RESET:' + reason, before, True,
                            actions_revoked=revoked, messages_flushed=flushed,
                            invalidated=('position_estimate', 'velocity_integral',
                                         'map_path', 'tracker_state',
                                         'student_hidden_state', 'previous_action'))

    def on_mission_reset(self, now_ns, *, queue=None, arbiter=None):
        _counter('now_ns', now_ns)
        before = self._snapshot()
        self.mission_epoch += 1
        revoked = arbiter.revoke(reasons.ACTION_REVOKED_BY_RESET) if arbiter is not None else False
        flushed = queue.clear() if queue is not None else 0
        self.tracker.invalidate()
        self.student.reset()
        return self._report('MISSION_RESET', before, True, actions_revoked=revoked,
                            messages_flushed=flushed,
                            invalidated=('mission_context', 'tracker_state',
                                         'student_hidden_state', 'previous_action'))

    def on_px4_restart(self, new_px4_boot_id, now_ns, *, queue=None, arbiter=None,
                       handover_timeout_ns=500_000_000):
        _counter('new_px4_boot_id', new_px4_boot_id)
        _counter('now_ns', now_ns)
        before = self._snapshot()
        if new_px4_boot_id == self.px4_boot_id:
            return self._report('PX4_RESTART', before, False)
        if self.ownership.pending is not None:
            self.ownership.fail_handover(now_ns, result='SUPERSEDED_BY_PX4_RESTART')
        self.px4_boot_id = new_px4_boot_id
        self.sync_generation += 1
        self.sync_valid = False
        self.px4_state_revalidated = False
        self.localization_epoch += 1
        self.ownership.bump_control_epoch()
        revoked = arbiter.revoke(reasons.ACTION_REVOKED_BY_RESET) if arbiter is not None else False
        flushed = 0
        if queue is not None:
            flushed = queue.flush_older_than(
                localization_epoch=self.localization_epoch,
                control_epoch=self.control_epoch)
        self.tracker.invalidate()
        self.student.reset()
        handover = self.ownership.request_handover(
            ControlOwner.SAFETY_SUPERVISOR, now_ns, timeout_ns=handover_timeout_ns,
            requested_px4_mode=None)
        return self._report('PX4_RESTART', before, True, actions_revoked=revoked,
                            messages_flushed=flushed, handover=handover,
                            invalidated=('time_mapping', 'px4_state_cache', 'actions',
                                         'in_flight_inference', 'tracker_state',
                                         'student_hidden_state'))

    def confirm_px4_state(self, now_ns, *, uncertainty_ns=0):
        _counter('now_ns', now_ns)
        _counter('uncertainty_ns', uncertainty_ns)
        before = self._snapshot()
        self.sync_generation += 1
        self.sync_valid = True
        self.px4_state_revalidated = True
        return self._report('PX4_STATE_CONFIRMED', before, True,
                            invalidated=('stale_time_mapping',))

    def on_companion_restart(self, new_system_boot_id, now_ns):
        _counter('new_system_boot_id', new_system_boot_id)
        _counter('now_ns', now_ns)
        before = self._snapshot()
        if new_system_boot_id == self.system_boot_id:
            return self._report('COMPANION_RESTART', before, False)
        self.system_boot_id = new_system_boot_id
        self.mission_epoch = 0
        self.localization_epoch = 0
        self.sync_generation += 1
        self.sync_valid = False
        self.px4_state_revalidated = False
        self.ownership = OwnershipState(ControlOwner.NONE, control_epoch=0, now_ns=now_ns)
        self.student = StudentState()
        self.tracker = TrackerState()
        self.last_impact = None
        return self._report('COMPANION_RESTART', before, True,
                            invalidated=('all_cached_context', 'control_ownership',
                                         'time_mapping', 'tracker_state',
                                         'student_hidden_state'))

    def is_quarantined(self, timestamp_ns):
        if self.last_impact is None:
            return False
        start, end = self.last_impact.quarantine_window()
        return start <= timestamp_ns <= end

    def accept_student_inference(self, *, observation_localization_epoch,
                                 observation_control_epoch, capture_interval_ns,
                                 now_ns, max_age_ns, student_generation):
        if observation_localization_epoch != self.localization_epoch:
            return reasons.REJECT_LOCALIZATION_EPOCH
        if observation_control_epoch != self.control_epoch:
            return reasons.REJECT_CONTROL_EPOCH
        if not self.student.check(student_generation):
            return reasons.REJECT_STUDENT_STATE_GENERATION
        interval = capture_interval_ns
        if (not isinstance(interval, tuple) or len(interval) != 2
                or not all(is_counter(value) for value in interval)
                or interval[0] > interval[1]):
            return reasons.REJECT_INVALID
        if self.is_quarantined(interval[0]) or self.is_quarantined(interval[1]):
            return reasons.REJECT_QUARANTINE
        if not self.sync_valid:
            return reasons.REJECT_SYNC_OR_PX4_BOOT
        age_ns = now_ns - interval[1]
        if age_ns < 0:
            return reasons.REJECT_FUTURE_TIMESTAMP
        if age_ns > max_age_ns:
            return reasons.REJECT_STALE
        return reasons.ACCEPT
