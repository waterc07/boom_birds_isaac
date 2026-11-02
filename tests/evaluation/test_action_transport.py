"""Tests for the deterministic delayed action arrival gate (latency envelope T1)."""
import dataclasses

import pytest

from boom_birds.evaluation.action_transport import (
    ActionTicket, DelayedActionQueue, DelayedVelocityExecutor)
from boom_birds.sim.velocity_control import (
    VehicleParams, VehicleState, VelocityExecutor, VelocitySetpoint)

EPOCHS = (1, 0, 0, 0, 100, 0)
OWNER = 'STUDENT'


def params():
    return VehicleParams(mass_kg=0.0282,
                         inertia_kgm2=(1.4e-5, 1.4e-5, 2.1e-5))


def state():
    return VehicleState((0.0, 0.0, 1.0), (0.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def make_executor(delay_s=0.10, epochs=EPOCHS, owner=OWNER):
    executor = DelayedVelocityExecutor(VelocityExecutor(params()), delay_s)
    if epochs is not None:
        executor.update_context(epochs=epochs, owner=owner)
    return executor


def make_setpoint(action_id='a1', *, issued_at_s=0.0, expires_at_s=0.50,
                  control_epoch=0, sync_generation=0, epochs=EPOCHS,
                  vx_forward_mps=0.5):
    return VelocitySetpoint(
        vx_forward_mps, 0.0, 0.0, 0.0, issued_at_s, expires_at_s,
        control_epoch, action_id=action_id,
        sync_generation=sync_generation, epochs=epochs)


def test_delayed_action_order_and_clear():
    q = DelayedActionQueue()
    q.schedule(0.2, 'late', (0.2,)); q.schedule(0.1, 'early', (0.1,))
    assert [a for a, _ in q.take_due(0.05)] == []
    due = q.take_due(0.15)
    assert len(due) == 1 and due[0][0] == 'early'
    assert q.pending() == 1
    assert q.clear() == 1 and q.pending() == 0


def test_action_ticket_is_frozen_dataclass():
    ticket = ActionTicket(
        setpoint=make_setpoint(), action_id='a1', issued_at_s=0.0,
        expires_at_s=0.5, control_epoch=0, epochs=EPOCHS,
        sync_generation=0, owner=OWNER, dispatch_s=0.0,
        scheduled_arrival_s=0.1)
    assert dataclasses.is_dataclass(ticket)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ticket.action_id = 'rewritten'


def test_delayed_executor_delivers_after_delay_and_rejects_expired_at_arrival():
    wrapper = make_executor(0.10, epochs=None)
    sp = make_setpoint(issued_at_s=0.0, expires_at_s=0.20, epochs=None,
                       sync_generation=-1)
    first = wrapper.step(sp, state(), 0.05)
    assert first.reason == 'REJECT_NO_CACHED_ACTION'
    assert wrapper.last_transport['status'] == 'NONE'
    second = wrapper.step(None, state(), 0.16)
    assert second.reason == 'ACCEPT'
    assert wrapper.last_transport['status'] == 'APPLIED'
    # the action was already expired when the delayed copy arrived
    late = make_setpoint('late', issued_at_s=0.0, expires_at_s=0.10,
                         epochs=None, sync_generation=-1)
    wrapper.step(late, state(), 0.30)
    third = wrapper.step(None, state(), 0.45)
    # the gate rejects the arrival itself, so the inner executor only sees "no active"
    assert third.reason == 'REJECT_NO_CACHED_ACTION'
    transport = wrapper.last_transport
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == 'ACTION_EXPIRED'
    assert transport['executed'] is False
    assert transport['executed_action_id'] == ''
    assert wrapper.rejections['ACTION_EXPIRED'] == 1


def test_arrival_accepted_becomes_active_and_is_recorded():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=0.50),
                 state(), 0.0)
    assert wrapper.pending == 1
    result = wrapper.step(None, state(), 0.10)
    assert result.reason == 'ACCEPT'
    transport = wrapper.last_transport
    assert transport['status'] == 'APPLIED'
    assert transport['action_id'] == 'a1'
    assert transport['executed_action_id'] == 'a1'
    assert transport['executed'] is True
    assert transport['reason'] == 'ACCEPT'
    assert transport['issued_at_s'] == 0.0
    assert transport['expires_at_s'] == 0.50
    assert transport['scheduled_arrival_s'] == pytest.approx(0.10)
    assert transport['arrival_s'] == pytest.approx(0.10)
    assert transport['dispatch_delay_s'] == pytest.approx(0.10)
    assert transport['arrival_age_s'] == pytest.approx(0.10)
    assert transport['applied']['action_id'] == 'a1'
    assert transport['applied']['is_held'] is False
    assert transport['applied']['vx_forward_mps'] == 0.5
    assert transport['rejections_this_step'] == []
    assert len(wrapper.arrivals) == 1
    assert wrapper.arrivals[0]['status'] == 'APPLIED'
    assert wrapper.arrivals[0]['reason'] == 'ACCEPT'


def test_arrival_sync_generation_change_rejected_and_never_executed():
    wrapper = make_executor()
    sp = make_setpoint('a1', expires_at_s=1.0, sync_generation=0)
    wrapper.step(sp, state(), 0.0)
    wrapper.update_context(epochs=(1, 0, 0, 0, 100, 1), owner=OWNER)
    result = wrapper.step(None, state(), 0.10)
    transport = wrapper.last_transport
    assert result.reason == 'REJECT_NO_CACHED_ACTION'
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == 'REJECT_SYNC_OR_PX4_BOOT'
    assert transport['executed'] is False
    assert transport['executed_action_id'] == ''
    assert transport['action_id'] == ''
    assert wrapper.rejections['REJECT_SYNC_OR_PX4_BOOT'] == 1
    assert [item['action_id'] for item in transport['rejections_this_step']] == ['a1']
    assert transport['rejections_this_step'][0]['reason'] == 'REJECT_SYNC_OR_PX4_BOOT'
    assert transport['rejections_this_step'][0]['arrival_age_s'] == pytest.approx(0.10)


def test_epochs_change_before_arrival_rejects_and_invalidates_old_active():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=1.0),
                 state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['executed_action_id'] == 'a1'
    wrapper.step(make_setpoint('a2', issued_at_s=0.15, expires_at_s=1.0),
                 state(), 0.15)
    wrapper.update_context(epochs=(1, 1, 0, 0, 100, 0), owner=OWNER)
    result = wrapper.step(None, state(), 0.25)
    transport = wrapper.last_transport
    assert result.reason == 'REJECT_NO_CACHED_ACTION'
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == 'REJECT_MISSION_EPOCH'
    assert transport['executed'] is False
    assert transport['executed_action_id'] == ''
    assert wrapper.rejections['REJECT_MISSION_EPOCH'] == 1
    # the previously accepted a1 is invalid as well: old context is gone
    assert wrapper.active_setpoint is None
    executed_ids = [ticket for ticket in
                    (wrapper.last_transport['executed_action_id'],)]
    assert 'a2' not in executed_ids
    wrapper.step(None, state(), 0.30)
    assert wrapper.last_transport['executed_action_id'] == ''


@pytest.mark.parametrize('index,expected', [
    (0, 'REJECT_BOOT_MISMATCH'),
    (1, 'REJECT_MISSION_EPOCH'),
    (2, 'REJECT_LOCALIZATION_EPOCH'),
    (3, 'REJECT_CONTROL_EPOCH'),
    (4, 'REJECT_SYNC_OR_PX4_BOOT'),
    (5, 'REJECT_SYNC_OR_PX4_BOOT'),
])
def test_epoch_mismatch_reason_codes(index, expected):
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', expires_at_s=1.0), state(), 0.0)
    changed = list(EPOCHS)
    changed[index] += 1
    wrapper.update_context(epochs=tuple(changed), owner=OWNER)
    wrapper.step(None, state(), 0.10)
    transport = wrapper.last_transport
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == expected
    assert transport['executed'] is False
    assert wrapper.rejections[expected] == 1


def test_owner_change_or_revocation_rejects_arrival():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', expires_at_s=1.0), state(), 0.0)
    wrapper.update_context(epochs=EPOCHS, owner='IMPACT_RECOVERY')
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'REJECTED'
    assert wrapper.last_transport['reason'] == 'REJECT_OWNER'
    assert wrapper.last_transport['executed'] is False

    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', expires_at_s=1.0), state(), 0.0)
    wrapper.update_context(epochs=EPOCHS, owner='NONE')
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['reason'] == 'REJECT_OWNER'
    assert wrapper.rejections['REJECT_OWNER'] == 1


def test_setpoint_metadata_epochs_take_precedence_over_context():
    wrapper = make_executor(epochs=(2, 0, 0, 0, 100, 0))
    # setpoint was built under the old system boot; the current context differs
    wrapper.step(make_setpoint('a1', expires_at_s=1.0, epochs=EPOCHS),
                 state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'REJECTED'
    assert wrapper.last_transport['reason'] == 'REJECT_BOOT_MISMATCH'


def test_setpoint_without_metadata_falls_back_to_context_epochs():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', expires_at_s=1.0, sync_generation=-1,
                               epochs=None), state(), 0.0)
    wrapper.update_context(epochs=(1, 0, 0, 0, 100, 1), owner=OWNER)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'REJECTED'
    assert wrapper.last_transport['reason'] == 'REJECT_SYNC_OR_PX4_BOOT'


def test_old_active_holds_until_expiry_then_becomes_none():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=0.25),
                 state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'APPLIED'

    result = wrapper.step(None, state(), 0.20)
    transport = wrapper.last_transport
    assert result.reason == 'ACCEPT'
    assert transport['status'] == 'HOLDING'
    assert transport['action_id'] == ''
    assert transport['executed_action_id'] == 'a1'
    assert transport['executed'] is True
    assert transport['issued_at_s'] == 0.0
    assert transport['expires_at_s'] == 0.25
    assert transport['applied']['is_held'] is True
    assert transport['applied']['age_s'] == pytest.approx(0.20)

    # expires is strictly `now_s >= expires_at_s`: no renewal, no rewrite
    result = wrapper.step(None, state(), 0.25)
    transport = wrapper.last_transport
    assert result.reason == 'REJECT_NO_CACHED_ACTION'
    assert transport['status'] == 'NONE'
    assert transport['reason'] == 'ACTION_EXPIRED'
    assert transport['executed'] is False
    assert transport['executed_action_id'] == ''
    assert transport['applied'] is None
    assert wrapper.active_setpoint is None


def test_resend_does_not_renew_expiry():
    wrapper = make_executor()
    sp = make_setpoint('a1', issued_at_s=0.0, expires_at_s=0.15)
    wrapper.step(sp, state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'APPLIED'
    # resending the same action must not move the original expiry
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=0.15),
                 state(), 0.11)
    assert wrapper.last_transport['expires_at_s'] == 0.15
    wrapper.step(None, state(), 0.16)
    assert wrapper.last_transport['status'] == 'NONE'
    assert wrapper.last_transport['reason'] == 'ACTION_EXPIRED'
    wrapper.step(None, state(), 0.25)
    transport = wrapper.last_transport
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == 'ACTION_EXPIRED'
    assert transport['executed'] is False
    assert transport['issued_at_s'] == 0.0
    assert transport['expires_at_s'] == 0.15
    # resend does not extend the admitted lifetime
    assert transport['expires_at_s'] - transport['issued_at_s'] == pytest.approx(0.15)
    assert wrapper.rejections['ACTION_EXPIRED'] == 1


def test_reset_clears_queue_and_active_and_isolates_episode():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=1.0),
                 state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'APPLIED'
    wrapper.step(make_setpoint('a2', issued_at_s=0.10, expires_at_s=1.0),
                 state(), 0.12)
    assert wrapper.pending == 1

    wrapper.reset(state())
    assert wrapper.pending == 0
    assert wrapper.active_setpoint is None
    assert wrapper.last_transport['status'] == 'NONE'
    assert wrapper.last_transport['executed'] is False
    result = wrapper.step(None, state(), 0.30)
    assert result.reason == 'REJECT_NO_CACHED_ACTION'
    assert wrapper.last_transport['status'] == 'NONE'
    assert 'a2' != wrapper.last_transport['executed_action_id']


def test_clear_drops_queued_and_active_but_keeps_history():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', expires_at_s=1.0), state(), 0.0)
    wrapper.step(None, state(), 0.10)
    arrivals_before = len(wrapper.arrivals)
    assert wrapper.pending == 0
    wrapper.step(make_setpoint('a2', issued_at_s=0.10, expires_at_s=1.0),
                 state(), 0.12)
    assert wrapper.clear() == 1
    assert wrapper.pending == 0
    assert wrapper.active_setpoint is None
    assert len(wrapper.arrivals) == arrivals_before


def test_set_delay_changes_new_actions_but_keeps_queued_delivery():
    wrapper = make_executor(0.10)
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=1.0),
                 state(), 0.0)
    wrapper.set_delay(0.20)
    wrapper.step(make_setpoint('a2', issued_at_s=0.05, expires_at_s=1.0),
                 state(), 0.05)
    # a1 was queued for 0.10 and is unaffected by the later set_delay
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'APPLIED'
    assert wrapper.last_transport['action_id'] == 'a1'
    # a2 was queued after the change and only arrives at 0.25
    wrapper.step(None, state(), 0.24)
    assert wrapper.last_transport['status'] == 'HOLDING'
    wrapper.step(None, state(), 0.25)
    assert wrapper.last_transport['status'] == 'APPLIED'
    assert wrapper.last_transport['action_id'] == 'a2'


def test_delay_zero_accepts_without_queueing_across_steps():
    wrapper = make_executor(0.0)
    result = wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=1.0),
                          state(), 0.0)
    assert result.reason == 'ACCEPT'
    transport = wrapper.last_transport
    assert transport['status'] == 'APPLIED'
    assert transport['executed_action_id'] == 'a1'
    assert transport['arrival_s'] == 0.0
    assert wrapper.pending == 0


def test_transport_timing_fields_separate_issue_from_dispatch():
    wrapper = make_executor(0.10)
    # issued before it was dispatched: scheduled_arrival uses issue + delay
    wrapper.step(make_setpoint('a1', issued_at_s=0.06, expires_at_s=1.0),
                 state(), 0.10)
    wrapper.step(None, state(), 0.20)
    transport = wrapper.last_transport
    assert transport['status'] == 'APPLIED'
    assert transport['issued_at_s'] == pytest.approx(0.06)
    assert transport['scheduled_arrival_s'] == pytest.approx(0.16)
    assert transport['arrival_s'] == pytest.approx(0.20)
    assert transport['arrival_age_s'] == pytest.approx(0.14)
    assert transport['dispatch_delay_s'] == pytest.approx(0.10)
    assert (transport['dispatch_delay_s']
            == pytest.approx(transport['scheduled_arrival_s']
                             - transport['issued_at_s']))
    assert transport['expires_at_s'] == pytest.approx(1.0)


def test_rejected_arrival_keeps_old_active_running_but_marks_not_executed():
    wrapper = make_executor()
    wrapper.step(make_setpoint('a1', issued_at_s=0.0, expires_at_s=2.0),
                 state(), 0.0)
    wrapper.step(None, state(), 0.10)
    assert wrapper.last_transport['status'] == 'APPLIED'
    # a2 is already expired when it arrives; a1 (still valid) keeps running
    wrapper.step(make_setpoint('a2', issued_at_s=0.10, expires_at_s=0.12),
                 state(), 0.15)
    assert wrapper.last_transport['status'] == 'HOLDING'
    wrapper.step(None, state(), 0.25)
    transport = wrapper.last_transport
    assert transport['status'] == 'REJECTED'
    assert transport['reason'] == 'ACTION_EXPIRED'
    assert transport['executed'] is False
    assert transport['executed_action_id'] != 'a2'
    assert transport['action_id'] == ''
    assert transport['applied'] is not None
    assert transport['applied']['action_id'] == 'a1'
    assert transport['applied']['is_held'] is True
    assert [item['action_id'] for item in transport['rejections_this_step']] == ['a2']


def test_arrival_lands_on_intended_tick_despite_float_quantization():
    # 16.1 + 0.10 == 16.200000000000003 in binary float; the control tick at
    # 16.2 is the intended arrival and must not slip a whole 50 ms step.
    wrapper = make_executor(0.10)
    assert 16.1 + 0.10 > 16.2
    wrapper.step(make_setpoint('a1', issued_at_s=16.1, expires_at_s=100.0),
                 state(), 16.1)
    wrapper.step(None, state(), 16.2)
    transport = wrapper.last_transport
    assert transport['status'] == 'APPLIED'
    assert transport['arrival_s'] == pytest.approx(16.2)
    assert transport['arrival_age_s'] == pytest.approx(0.10)


def test_control_epoch_is_proxied_to_inner_executor():
    wrapper = make_executor()
    assert wrapper.control_epoch == 0
    wrapper.control_epoch = 4
    assert wrapper._inner.control_epoch == 4
    assert wrapper.control_epoch == 4
