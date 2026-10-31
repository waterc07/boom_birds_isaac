"""V2.2 16.4/16.8/26.7 impact, restart, ownership and hidden-state invalidation."""
import pytest

from boom_birds.contracts import reasons
from boom_birds.contracts.action_v2 import VelocityPayload, build_velocity_envelope
from boom_birds.contracts.admission import ActionAdmissionConfig, ActionArbiter, validate_action
from boom_birds.contracts.context import EstimatorState, MessageHeader
from boom_birds.contracts.lifecycle import (
    EpochManager,
    EpochQueue,
    ImpactEvent,
    StudentState,
    TrackerState,
)
from boom_birds.contracts.ownership import ControlOwner, OwnershipState
from boom_birds.contracts.types import ActionLimits
from boom_birds.contracts.versions import MESSAGE_SCHEMA_ID

CAPTURE_NS = 1_000_000_000
IMPACT_NS = 2_000_000_000
NOW_NS = 2_100_000_000


def full_estimates(**overrides):
    values = dict(
        attitude_valid=True, angular_rate_valid=True, thrust_source_valid=True,
        xy_velocity_valid=True, z_velocity_valid=True, height_valid=True,
        local_position_valid=True, visual_bearing_valid=True,
        visual_servo_valid=True, yaw_valid=True,
    )
    values.update(overrides)
    return EstimatorState(**values)


def make_manager():
    return EpochManager(
        system_boot_id=1, mission_epoch=2, localization_epoch=3, control_epoch=4,
        px4_boot_id=5, sync_generation=6, sync_valid=True,
        clock_id='host_monotonic', now_ns=CAPTURE_NS,
    )


def make_config():
    return ActionAdmissionConfig(limits=ActionLimits(), ttl_ns=150_000_000, max_age_ms=150,
                                 allowed_observation_age_ns=250_000_000,
                                 require_vertical_integrity=True, allow_partial_axes=False)


def make_action(seq=1, *, source='STUDENT', loc_epoch=3, ctrl_epoch=4,
                capture_ns=CAPTURE_NS, px4_boot_id=5, sync_generation=6):
    header = MessageHeader(
        system_boot_id=1, mission_epoch=2, localization_epoch=loc_epoch,
        control_epoch=ctrl_epoch, clock_id='host_monotonic', px4_boot_id=px4_boot_id,
        sync_generation=sync_generation, sync_valid=True, sequence_id=seq,
        capture_timestamp_ns=capture_ns, receive_timestamp_ns=capture_ns + 1,
        publish_timestamp_ns=capture_ns + 2, source_id=7,
        schema_version=MESSAGE_SCHEMA_ID,
    )
    return build_velocity_envelope(
        header,
        VelocityPayload(vx_forward_mps=0.2, vy_left_mps=0.0, vz_up_mps=0.0,
                        yaw_rate_ccw_world_radps=0.0, axis_validity=(True, True, True, True)),
        observation_id='obs-impact', input_capture_interval_ns=(capture_ns - 10_000_000, capture_ns),
        earliest_input_safe_deadline_ns=capture_ns + 200_000_000,
        issued_at_monotonic_ns=capture_ns + 5_000_000, ttl_ns=150_000_000,
        max_age_ms=150, source=source, policy_version='test-policy-0',
    )


def test_handover_is_pending_then_active_and_changes_control_epoch():
    state = OwnershipState(ControlOwner.STUDENT, control_epoch=4, now_ns=0)
    record = state.request_handover(ControlOwner.IMPACT_RECOVERY, 1_000, timeout_ns=500_000,
                                    requested_px4_mode='OFFBOARD')
    assert record.previous_owner == ControlOwner.STUDENT
    assert record.new_owner == ControlOwner.IMPACT_RECOVERY
    assert record.control_epoch_before == 4
    assert state.owner == ControlOwner.STUDENT
    assert state.pending is not None
    assert state.publishable_source() == ControlOwner.IMPACT_RECOVERY
    assert state.can_publish(ControlOwner.IMPACT_RECOVERY, 4)
    assert not state.can_publish(ControlOwner.STUDENT, 4)
    completed = state.complete_handover(1_500, ack_received=True, actual_px4_mode='OFFBOARD')
    assert completed.control_epoch_after == 5
    assert state.owner == ControlOwner.IMPACT_RECOVERY and state.control_epoch == 5
    assert not state.can_publish(ControlOwner.STUDENT, 5)
    with pytest.raises(ValueError):
        state.request_handover('MISSION_MANAGER', 2_000, timeout_ns=100)


def test_handover_timeout_keeps_previous_owner_and_epoch():
    state = OwnershipState(ControlOwner.STUDENT, control_epoch=4, now_ns=0)
    state.request_handover(ControlOwner.IMPACT_RECOVERY, 0, timeout_ns=100)
    assert state.pending is not None
    timed_out = state.tick(101)
    assert timed_out is not None and timed_out.timeout is True
    assert timed_out.result == 'TIMEOUT'
    assert state.pending is None
    assert state.owner == ControlOwner.STUDENT and state.control_epoch == 4
    assert state.publishable_source() == ControlOwner.STUDENT


def test_failsafe_handover_stops_external_publishing():
    state = OwnershipState(ControlOwner.IMPACT_RECOVERY, control_epoch=5, now_ns=0)
    state.request_handover(ControlOwner.PX4_CONFIGURED_FAILSAFE, 0, timeout_ns=100)
    state.complete_handover(10)
    assert state.publishable_source() is None
    assert not state.can_publish(ControlOwner.IMPACT_RECOVERY, state.control_epoch)


def test_impact_atomically_bumps_epochs_and_invalidates_everything():
    manager = make_manager()
    arbiter = ActionArbiter(make_config())
    queue = EpochQueue()
    queue.push('old-frame', localization_epoch=3, control_epoch=4)
    context = manager.context(estimates=full_estimates())
    assert arbiter.admit_new(make_action(seq=1), context, CAPTURE_NS + 10_000_000).accepted
    report = manager.on_impact(ImpactEvent('ev-1', IMPACT_NS, 50_000_000), NOW_NS,
                               queue=queue, arbiter=arbiter)
    assert report.changed is True
    assert report.localization_epoch_after == 4
    assert report.control_epoch_after == 5
    assert report.actions_revoked is True
    assert arbiter.cached_action is None
    assert report.messages_flushed == 1
    assert len(queue) == 0
    assert report.student_generation_after == 1
    assert report.tracker_generation_after == 1
    assert report.handover.new_owner == ControlOwner.IMPACT_RECOVERY


def test_after_impact_normal_student_is_rejected_but_pending_recovery_may_presend():
    manager = make_manager()
    manager.on_impact(ImpactEvent('ev-1', IMPACT_NS, 0), NOW_NS)
    context = manager.context(estimates=full_estimates())
    config = make_config()
    capture = NOW_NS - 20_000_000
    student = make_action(seq=1, loc_epoch=4, ctrl_epoch=5, capture_ns=capture)
    assert validate_action(student, context, NOW_NS, stage='ADMIT_NEW',
                           config=config) == reasons.REJECT_OWNER
    recovery = make_action(seq=1, source='IMPACT_RECOVERY', loc_epoch=4, ctrl_epoch=5,
                           capture_ns=capture)
    assert validate_action(recovery, context, NOW_NS, stage='ADMIT_NEW', config=config) == reasons.ACCEPT


def test_impact_quarantine_rejects_samples_inside_uncertainty_window():
    manager = make_manager()
    manager.on_impact(ImpactEvent('ev-1', IMPACT_NS, 50_000_000), NOW_NS)
    assert manager.is_quarantined(IMPACT_NS - 40_000_000)
    assert not manager.is_quarantined(IMPACT_NS - 100_000_000)
    assert manager.accept_student_inference(
        observation_localization_epoch=4, observation_control_epoch=5,
        capture_interval_ns=(IMPACT_NS - 45_000_000, IMPACT_NS - 40_000_000),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=manager.student.generation) == reasons.REJECT_QUARANTINE


def test_inference_result_is_rejected_for_old_epoch_generation_or_age():
    manager = make_manager()
    manager.on_impact(ImpactEvent('ev-1', IMPACT_NS, 0), NOW_NS)
    good_capture = NOW_NS - 20_000_000
    generation = manager.student.generation
    assert manager.accept_student_inference(
        observation_localization_epoch=3, observation_control_epoch=5,
        capture_interval_ns=(good_capture - 10_000_000, good_capture),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=generation) == reasons.REJECT_LOCALIZATION_EPOCH
    assert manager.accept_student_inference(
        observation_localization_epoch=4, observation_control_epoch=4,
        capture_interval_ns=(good_capture - 10_000_000, good_capture),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=generation) == reasons.REJECT_CONTROL_EPOCH
    assert manager.accept_student_inference(
        observation_localization_epoch=4, observation_control_epoch=5,
        capture_interval_ns=(good_capture - 10_000_000, good_capture),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=generation - 1) == reasons.REJECT_STUDENT_STATE_GENERATION
    assert manager.accept_student_inference(
        observation_localization_epoch=4, observation_control_epoch=5,
        capture_interval_ns=(CAPTURE_NS, CAPTURE_NS + 5_000_000),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=generation) == reasons.REJECT_STALE
    assert manager.accept_student_inference(
        observation_localization_epoch=4, observation_control_epoch=5,
        capture_interval_ns=(good_capture - 10_000_000, good_capture),
        now_ns=NOW_NS, max_age_ns=300_000_000,
        student_generation=generation) == reasons.ACCEPT


def test_px4_restart_invalidates_actions_sync_and_normal_control():
    manager = make_manager()
    arbiter = ActionArbiter(make_config())
    queue = EpochQueue()
    queue.push('stale-px4-frame', localization_epoch=3, control_epoch=4)
    context = manager.context(estimates=full_estimates())
    arbiter.admit_new(make_action(seq=1), context, CAPTURE_NS + 10_000_000)
    report = manager.on_px4_restart(6, NOW_NS, queue=queue, arbiter=arbiter)
    assert report.changed is True
    assert report.px4_boot_id_after == 6
    assert report.sync_generation_after == 7
    assert report.localization_epoch_after == 4 and report.control_epoch_after == 5
    assert manager.sync_valid is False
    assert manager.px4_state_revalidated is False
    assert arbiter.cached_action is None
    assert len(queue) == 0
    unchanged = manager.on_px4_restart(6, NOW_NS + 1, queue=queue, arbiter=arbiter)
    assert unchanged.changed is False and unchanged.px4_boot_id_after == 6
    old_context = manager.context(estimates=full_estimates())
    assert validate_action(make_action(seq=2, loc_epoch=4, ctrl_epoch=5, px4_boot_id=5,
                                       capture_ns=NOW_NS - 10_000_000),
                           old_context, NOW_NS, stage='ADMIT_NEW',
                           config=make_config()) == reasons.REJECT_SYNC_OR_PX4_BOOT


def test_px4_state_confirmation_restores_sync_generation():
    manager = make_manager()
    manager.on_px4_restart(6, NOW_NS)
    manager.confirm_px4_state(NOW_NS + 1_000, uncertainty_ns=2_000_000)
    assert manager.sync_valid is True
    assert manager.px4_state_revalidated is True
    context = manager.context(estimates=full_estimates())
    assert context.sync_generation == manager.sync_generation == 8


def test_mission_reset_invalidates_previous_sortie_messages():
    manager = make_manager()
    report = manager.on_mission_reset(NOW_NS)
    assert report.mission_epoch_after == 3
    assert validate_action(make_action(seq=2, loc_epoch=3, ctrl_epoch=4,
                                       capture_ns=NOW_NS - 10_000_000),
                           manager.context(estimates=full_estimates()), NOW_NS,
                           stage='ADMIT_NEW', config=make_config()) == reasons.REJECT_MISSION_EPOCH


def test_companion_restart_rejects_every_old_message_and_freezes_publishing():
    manager = make_manager()
    report = manager.on_companion_restart(2, NOW_NS)
    assert report.system_boot_id_after == 2
    assert report.mission_epoch_after == 0
    assert report.localization_epoch_after == 0
    assert report.control_epoch_after == 0
    context = manager.context(estimates=full_estimates())
    assert context.control_owner == ControlOwner.NONE
    assert manager.ownership.publishable_source() is None
    assert validate_action(make_action(seq=2, loc_epoch=3, ctrl_epoch=4,
                                       capture_ns=NOW_NS - 10_000_000),
                           context, NOW_NS, stage='ADMIT_NEW',
                           config=make_config()) == reasons.REJECT_BOOT_MISMATCH


def test_hidden_state_generation_blocks_stale_gru_and_previous_action():
    student = StudentState()
    generation = student.generation
    student.write_previous_action(generation, (0.1, 0.2, 0.3, 0.4))
    assert student.read_previous_action(generation) == (0.1, 0.2, 0.3, 0.4)
    next_generation = student.reset()
    assert next_generation == generation + 1
    assert student.read_previous_action(generation) is None
    with pytest.raises(ValueError):
        student.write_previous_action(generation, (0.0, 0.0, 0.0, 0.0))
    tracker = TrackerState()
    old = tracker.generation
    tracker.invalidate()
    assert not tracker.check(old)
    assert tracker.check(tracker.generation)


def test_queue_flush_removes_only_older_epochs():
    queue = EpochQueue()
    queue.push('a', localization_epoch=3, control_epoch=4)
    queue.push('b', localization_epoch=4, control_epoch=5)
    queue.push('c', localization_epoch=5, control_epoch=6)
    removed = queue.flush_older_than(localization_epoch=4, control_epoch=5)
    assert removed == 1
    assert len(queue) == 2
    assert queue.snapshot() == ('b', 'c')
