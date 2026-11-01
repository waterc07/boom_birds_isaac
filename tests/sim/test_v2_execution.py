"""Pure-software tests for the sim v2 execution gate and failure boundaries."""
import pytest

from boom_birds.contracts import reasons
from boom_birds.sim.v2_execution import V2ActionGate, V2ExecutionConfig


def _gate(ttl_ns=100):
    config = V2ExecutionConfig(ttl_ns=ttl_ns, max_age_ms=1,
                               allowed_observation_age_ns=10_000)
    return V2ActionGate(config)


def _build(gate, now_ns, sequence=0, ttl_ns=None):
    return gate.build((0.2, 0.0, 0.0, 0.0), now_ns, sequence,
                      observation_id='obs-%d' % sequence,
                      observation_time_ns=now_ns, ttl_ns=ttl_ns)


def test_expiry_boundary_accepts_before_and_rejects_at_expiry():
    gate = _gate()
    action = _build(gate, 0)
    context = gate.context()
    assert gate.admit(action, context, 99).reason == reasons.ACCEPT
    expired = _build(gate, 0, sequence=1)
    result = gate.admit(expired, context, 100)
    assert result.accepted is False
    assert result.reason == reasons.REJECT_TTL_EXPIRED
    assert gate.executed_actions == []


def test_legal_resend_does_not_renew_expiry():
    gate = _gate()
    action = _build(gate, 0)
    context = gate.context()
    first = gate.admit(action, context, 0)
    assert first.accepted is True
    resend = gate.send_cached(action, context, 50)
    assert resend.accepted is True
    assert resend.reason == reasons.ACCEPT
    assert action.expires_at_monotonic_ns == 100
    expired = gate.send_cached(action, context, 100)
    assert expired.accepted is False
    assert expired.reason == reasons.ACTION_EXPIRED
    assert action.expires_at_monotonic_ns == 100


def test_out_of_order_duplicate_and_cache_rollback_are_rejected():
    gate = _gate()
    context = gate.context()
    first = _build(gate, 0, sequence=0)
    assert gate.admit(first, context, 0).accepted is True
    duplicate = gate.admit(first, context, 10)
    assert duplicate.accepted is True
    assert duplicate.reason == reasons.ACCEPT_RESEND
    second = _build(gate, 0, sequence=2)
    assert gate.admit(second, context, 10).accepted is True
    stale = _build(gate, 0, sequence=1)
    result = gate.admit(stale, context, 10)
    assert result.accepted is False
    assert result.reason in (reasons.REJECT_SUPERSEDED, reasons.REJECT_OUT_OF_ORDER)


def test_any_context_epoch_change_rejects_old_action():
    gate = _gate()
    action = _build(gate, 0)
    for field in ('mission', 'localization', 'control'):
        gate = _gate()
        action = _build(gate, 0)
        gate.bump_context(**{field: True})
        result = gate.admit(action, gate.context(), 10)
        assert result.accepted is False
        assert result.reason in (reasons.REJECT_MISSION_EPOCH,
                                 reasons.REJECT_LOCALIZATION_EPOCH,
                                 reasons.REJECT_CONTROL_EPOCH)


def test_clock_sync_and_px4_boot_mismatch_reject():
    gate = _gate()
    action = _build(gate, 0)
    wrong_clock = gate.context(clock_id='px4_boot_clock')
    assert gate.admit(action, wrong_clock, 10).reason == reasons.REJECT_CLOCK_DOMAIN
    wrong_sync = gate.context(sync_generation=99)
    assert gate.admit(action, wrong_sync, 10).reason == reasons.REJECT_SYNC_OR_PX4_BOOT
    wrong_boot = gate.context(px4_boot_id=999)
    assert gate.admit(action, wrong_boot, 10).reason == reasons.REJECT_SYNC_OR_PX4_BOOT


def test_ownership_revoke_and_pending_owner_rules():
    gate = _gate()
    action = _build(gate, 0)
    revoked = gate.context(owner='NONE')
    assert gate.admit(action, revoked, 10).reason == reasons.REJECT_OWNER
    pending_other = gate.context(pending_owner='SAFETY_SUPERVISOR')
    assert gate.admit(action, pending_other, 10).reason == reasons.REJECT_OWNER
    pending_student = gate.context(pending_owner='STUDENT')
    assert gate.admit(_build(gate, 0, sequence=1), pending_student, 10).accepted is True


def test_reset_invalidates_old_observation_action_and_cache():
    gate = _gate()
    action = _build(gate, 0)
    context = gate.context()
    assert gate.admit(action, context, 10).accepted is True
    gate.reset(now_ns=20)
    new_context = gate.context()
    result = gate.admit(action, new_context, 30)
    assert result.accepted is False
    assert result.reason in (reasons.REJECT_BOOT_MISMATCH,
                             reasons.REJECT_MISSION_EPOCH,
                             reasons.REJECT_LOCALIZATION_EPOCH,
                             reasons.REJECT_CONTROL_EPOCH,
                             reasons.REJECT_SYNC_OR_PX4_BOOT)
    assert gate.arbiter.cached_action is None


def test_sustained_wait_uses_fresh_actions_not_renewal():
    gate = _gate(ttl_ns=100)
    context = gate.context()
    old = _build(gate, 0, sequence=0, ttl_ns=100)
    assert gate.admit(old, context, 0).accepted is True
    new = _build(gate, 50, sequence=1, ttl_ns=100)
    assert gate.admit(new, context, 50).accepted is True
    assert new.expires_at_monotonic_ns == 150
    assert old.expires_at_monotonic_ns == 100
    assert old.expires_at_monotonic_ns != new.expires_at_monotonic_ns


def test_rejected_action_is_not_executed():
    gate = _gate()
    action = _build(gate, 0)
    rejected = gate.admit(action, gate.context(owner='NONE'), 10)
    assert rejected.accepted is False
    assert gate.executed_actions == []
    assert len(gate.accepted_actions) == 0


def test_simulated_identity_is_explicit_and_bounded():
    gate = _gate()
    assert gate.config.simulated_px4_identity is True
    assert gate.config.px4_boot_id >= 0
    assert gate.config.clock_id == 'host_monotonic'

def test_queued_action_is_rejected_if_it_expires_before_arrival():
    from boom_birds.evaluation.dual_clock import EventQueue
    gate = _gate(ttl_ns=100)
    action = _build(gate, 0, ttl_ns=100)
    queue = EventQueue()
    queue.push(150, {'action': action}, duplicate_of=None)
    due = queue.pop_due(200)
    assert len(due) == 1
    result = gate.admit(action, gate.context(), 200)
    assert result.accepted is False
    assert result.reason == reasons.REJECT_TTL_EXPIRED
    assert gate.executed_actions == []
