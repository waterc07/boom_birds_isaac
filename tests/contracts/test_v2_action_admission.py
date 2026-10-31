"""V2.2 10.4/16.6/27.3 action envelope, admission and resend contracts."""
import math
import threading

import pytest

from boom_birds.contracts import reasons
from boom_birds.contracts.action_v2 import (
    ActionEnvelope,
    VelocityPayload,
    build_velocity_envelope,
    from_velocity_v1,
)
from boom_birds.contracts.admission import (
    ActionAdmissionConfig,
    ActionArbiter,
    LatestValidActionQueue,
    validate_action,
)
from boom_birds.contracts.context import ContractContext, EstimatorState, MessageHeader
from boom_birds.contracts.frames import decode_action
from boom_birds.contracts.types import ActionLimits
from boom_birds.contracts.versions import ACTION_SCHEMA_ID, MESSAGE_SCHEMA_ID

CAPTURE_NS = 1_000_000_000
ISSUED_NS = CAPTURE_NS + 5_000_000
DEADLINE_NS = CAPTURE_NS + 200_000_000
NOW_NS = ISSUED_NS + 10_000_000
TTL_NS = 150_000_000


def full_estimates(**overrides):
    values = dict(
        attitude_valid=True,
        angular_rate_valid=True,
        thrust_source_valid=True,
        xy_velocity_valid=True,
        z_velocity_valid=True,
        height_valid=True,
        local_position_valid=True,
        visual_bearing_valid=True,
        visual_servo_valid=True,
        yaw_valid=True,
    )
    values.update(overrides)
    return EstimatorState(**values)


def make_context(**overrides):
    values = dict(
        system_boot_id=1,
        mission_epoch=2,
        localization_epoch=3,
        control_epoch=4,
        clock_id='host_monotonic',
        px4_boot_id=5,
        sync_generation=6,
        schema_version=MESSAGE_SCHEMA_ID,
        estimates=full_estimates(),
    )
    values.update(overrides)
    return ContractContext(**values)


def make_header(seq=1, capture_ns=CAPTURE_NS, **overrides):
    values = dict(
        system_boot_id=1,
        mission_epoch=2,
        localization_epoch=3,
        control_epoch=4,
        clock_id='host_monotonic',
        px4_boot_id=5,
        sync_generation=6,
        sync_valid=True,
        sequence_id=seq,
        capture_timestamp_ns=capture_ns,
        receive_timestamp_ns=capture_ns + 1_000_000,
        publish_timestamp_ns=capture_ns + 2_000_000,
        source_id=7,
        schema_version=MESSAGE_SCHEMA_ID,
    )
    values.update(overrides)
    return MessageHeader(**values)


def payload(**overrides):
    values = dict(vx_forward_mps=0.5, vy_left_mps=0.0, vz_up_mps=0.1,
                  yaw_rate_ccw_world_radps=0.05, axis_validity=(True, True, True, True))
    values.update(overrides)
    return VelocityPayload(**values)


def build(seq=1, *, header=None, motion=None, capture_ns=CAPTURE_NS, issued_at=ISSUED_NS,
          ttl_ns=TTL_NS, deadline_ns=DEADLINE_NS, source='STUDENT',
          observation_id='obs-1', interval=None):
    header = header or make_header(seq=seq, capture_ns=capture_ns)
    interval = interval or (capture_ns - 20_000_000, capture_ns)
    return build_velocity_envelope(
        header,
        motion or payload(),
        observation_id=observation_id,
        input_capture_interval_ns=interval,
        earliest_input_safe_deadline_ns=deadline_ns,
        issued_at_monotonic_ns=issued_at,
        ttl_ns=ttl_ns,
        max_age_ms=150,
        source=source,
        policy_version='test-policy-0',
    )


def make_config(**overrides):
    values = dict(limits=None, ttl_ns=TTL_NS, max_age_ms=150,
                  allowed_observation_age_ns=250_000_000,
                  require_vertical_integrity=True, allow_partial_axes=False)
    values.update(overrides)
    return ActionAdmissionConfig(**values)


def test_ttl_expiry_is_earliest_of_ttl_and_input_deadline():
    short_ttl = build(ttl_ns=50_000_000)
    assert short_ttl.expires_at_monotonic_ns == ISSUED_NS + 50_000_000
    long_ttl = build(ttl_ns=400_000_000)
    assert long_ttl.expires_at_monotonic_ns == DEADLINE_NS
    with pytest.raises(ValueError):
        build_velocity_envelope(
            make_header(), payload(), observation_id='obs-1',
            input_capture_interval_ns=(CAPTURE_NS - 20_000_000, CAPTURE_NS),
            earliest_input_safe_deadline_ns=DEADLINE_NS,
            issued_at_monotonic_ns=ISSUED_NS, ttl_ns=TTL_NS, max_age_ms=150,
            source='STUDENT', policy_version='p', expires_at_monotonic_ns=DEADLINE_NS + 1)


def test_payload_and_envelope_reject_invalid_values():
    with pytest.raises(ValueError):
        payload(vx_forward_mps=math.nan)
    with pytest.raises(ValueError):
        payload(axis_validity=[True, True, True, True])
    with pytest.raises(ValueError):
        payload(frame='LOCAL_ENU')
    with pytest.raises(ValueError):
        build(issued_at=CAPTURE_NS - 5_000_000)
    with pytest.raises(ValueError):
        build(interval=(CAPTURE_NS + 1, CAPTURE_NS + 2))
    with pytest.raises(ValueError):
        build(deadline_ns=CAPTURE_NS - 1)


def test_admit_new_and_strict_sequence():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    first = arbiter.admit_new(build(seq=1), ctx, NOW_NS)
    assert first.accepted and first.is_new_admission
    assert first.sequence_id == 1
    second = arbiter.admit_new(build(seq=2), ctx, NOW_NS)
    assert second.accepted and second.is_new_admission


def test_legal_resend_is_not_a_new_admission_and_does_not_extend_ttl():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    action = build(seq=1)
    arbiter.admit_new(action, ctx, NOW_NS)
    resend = arbiter.admit_new(action, ctx, NOW_NS + 20_000_000)
    assert resend.accepted and not resend.is_new_admission
    assert resend.reason == reasons.ACCEPT_RESEND
    assert arbiter.cached_action.expires_at_monotonic_ns == action.expires_at_monotonic_ns
    assert arbiter.admit_new(build(seq=2), ctx, NOW_NS + 21_000_000).is_new_admission


def test_sequence_reuse_out_of_order_and_rollback_are_rejected():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    arbiter.admit_new(build(seq=1), ctx, NOW_NS)
    arbiter.admit_new(build(seq=2), ctx, NOW_NS)
    reused = arbiter.admit_new(build(seq=2, motion=payload(vx_forward_mps=0.2)), ctx, NOW_NS)
    assert not reused.accepted and reused.reason == reasons.REJECT_SEQUENCE_REUSE
    rollback = arbiter.admit_new(build(seq=1, motion=payload(vx_forward_mps=0.3)), ctx, NOW_NS)
    assert not rollback.accepted and rollback.reason == reasons.REJECT_SUPERSEDED
    assert arbiter.cached_action.sequence_id == 2
    arbiter.revoke(reasons.ACTION_REVOKED)
    assert arbiter.cached_action is None
    stale = arbiter.admit_new(build(seq=1), ctx, NOW_NS)
    assert not stale.accepted and stale.reason == reasons.REJECT_OUT_OF_ORDER


def test_sequence_restarts_with_new_control_epoch():
    arbiter = ActionArbiter(make_config())
    arbiter.admit_new(build(seq=9), make_context(), NOW_NS)
    next_epoch = make_context(control_epoch=5)
    accepted = arbiter.admit_new(build(seq=1, header=make_header(seq=1, control_epoch=5)),
                                 next_epoch, NOW_NS)
    assert accepted.accepted and accepted.is_new_admission


def test_send_cached_requires_identical_identity_and_digest():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    action = build(seq=1)
    assert arbiter.send_cached(action, ctx, NOW_NS).reason == reasons.REJECT_NO_CACHED_ACTION
    arbiter.admit_new(action, ctx, NOW_NS)
    assert arbiter.send_cached(action, ctx, NOW_NS + 1_000_000).accepted
    tampered = build(seq=1, motion=payload(vx_forward_mps=0.6))
    result = arbiter.send_cached(tampered, ctx, NOW_NS + 2_000_000)
    assert not result.accepted and result.reason == reasons.REJECT_CACHE_DIGEST_MISMATCH


def test_expired_cache_is_revoked_with_action_expired():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    action = build(seq=1)
    arbiter.admit_new(action, ctx, NOW_NS)
    assert arbiter.send_cached(action, ctx, action.expires_at_monotonic_ns - 1).accepted
    expired = arbiter.send_cached(action, ctx, action.expires_at_monotonic_ns)
    assert not expired.accepted and expired.reason == reasons.ACTION_EXPIRED
    assert arbiter.cached_action is None


@pytest.mark.parametrize('overrides,code', [
    ({'control_owner': 'IMPACT_RECOVERY'}, reasons.REJECT_OWNER),
    ({'localization_epoch': 99}, reasons.REJECT_LOCALIZATION_EPOCH),
    ({'system_boot_id': 99}, reasons.REJECT_BOOT_MISMATCH),
    ({'sync_generation': 99}, reasons.REJECT_SYNC_OR_PX4_BOOT),
    ({'px4_boot_id': 99}, reasons.REJECT_SYNC_OR_PX4_BOOT),
    ({'estimates': full_estimates(xy_velocity_valid=False)}, reasons.REJECT_ESTIMATE_INVALID),
    ({'estimates': full_estimates(z_velocity_valid=False)}, reasons.REJECT_ESTIMATE_INVALID),
    ({'estimates': full_estimates(yaw_valid=False)}, reasons.REJECT_ESTIMATE_INVALID),
    ({'estimates': full_estimates(height_valid=False)}, reasons.REJECT_ESTIMATE_INVALID),
])
def test_validate_action_context_and_estimator_gates(overrides, code):
    ctx = make_context(**overrides)
    assert validate_action(build(seq=1), ctx, NOW_NS, stage='ADMIT_NEW',
                           config=make_config()) == code


def test_partial_axis_actions_are_rejected_by_default():
    partial = build(seq=1, motion=payload(axis_validity=(True, False, True, True)))
    result = ActionArbiter(make_config()).admit_new(partial, make_context(), NOW_NS)
    assert not result.accepted and result.reason == reasons.REJECT_PARTIAL_AXIS_UNSUPPORTED


def test_limits_use_horizontal_vector_norm_and_vertical_axis():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    too_fast = build(seq=1, motion=payload(vx_forward_mps=1.0, vy_left_mps=1.0))
    assert arbiter.admit_new(too_fast, ctx, NOW_NS).reason == reasons.REJECT_LIMITS
    too_high = build(seq=2, motion=payload(vz_up_mps=2.0))
    assert arbiter.admit_new(too_high, ctx, NOW_NS).reason == reasons.REJECT_LIMITS


def test_observation_age_and_input_deadline_are_enforced():
    strict = make_config(allowed_observation_age_ns=10_000_000)
    stale_obs = validate_action(build(seq=1), make_context(), NOW_NS,
                                stage='ADMIT_NEW', config=strict)
    assert stale_obs == reasons.REJECT_STALE_OBSERVATION
    action = build(seq=1)
    object.__setattr__(action, 'expires_at_monotonic_ns', DEADLINE_NS + 1)
    assert validate_action(action, make_context(), NOW_NS, stage='ADMIT_NEW',
                           config=make_config()) == reasons.REJECT_INPUT_DEADLINE


def test_non_finite_tampering_is_rejected_not_clamped():
    action = build(seq=1)
    object.__setattr__(action.payload, 'vz_up_mps', math.inf)
    assert validate_action(action, make_context(), NOW_NS, stage='ADMIT_NEW',
                           config=make_config()) == reasons.REJECT_NONFINITE


def test_concurrent_admission_commits_sequence_once():
    arbiter = ActionArbiter(make_config())
    ctx = make_context()
    action = build(seq=1)
    barrier = threading.Barrier(4)
    results = []

    def worker():
        barrier.wait()
        results.append(arbiter.admit_new(action, ctx, NOW_NS))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 4
    assert all(result.accepted for result in results)
    assert sum(1 for result in results if result.is_new_admission) == 1


def test_latest_valid_queue_keeps_only_newest_action():
    queue = LatestValidActionQueue()
    first, second, third = build(seq=1), build(seq=2), build(seq=3)
    queue.push(first)
    queue.push(second)
    queue.push(third)
    assert queue.peek(NOW_NS).sequence_id == 3
    assert queue.peek(third.expires_at_monotonic_ns) is None
    assert queue.peek(NOW_NS) is None


def test_ned_transform_matches_v2_matrix():
    motion = payload(vx_forward_mps=1.0, vy_left_mps=2.0, vz_up_mps=0.5)
    assert motion.to_ned(0.0) == pytest.approx((1.0, -2.0, -0.5))
    assert motion.to_ned(math.pi / 2) == pytest.approx((2.0, 1.0, -0.5))
    assert motion.to_ned(0.0, yaw_valid=False) is None


def test_v1_migration_requires_explicit_validity_and_provenance():
    command = decode_action([1, 0, 0, 0], math.pi / 2, ActionLimits(), 0, 0)
    header = make_header()
    with pytest.raises(TypeError):
        from_velocity_v1(command, yaw_enu_rad=math.pi / 2, header=header,
                         observation_id='obs-1', earliest_input_safe_deadline_ns=DEADLINE_NS,
                         ttl_ns=TTL_NS, max_age_ms=150, policy_version='p')
    with pytest.raises(ValueError):
        from_velocity_v1(command, yaw_enu_rad=math.pi / 2, header=header,
                         observation_id='', earliest_input_safe_deadline_ns=DEADLINE_NS,
                         ttl_ns=TTL_NS, max_age_ms=150, axis_validity=(True, True, True, True),
                         policy_version='p')
    migrated = from_velocity_v1(command, yaw_enu_rad=math.pi / 2, header=header,
                                observation_id='obs-1', earliest_input_safe_deadline_ns=DEADLINE_NS,
                                ttl_ns=TTL_NS, max_age_ms=150, axis_validity=(True, True, True, True),
                                policy_version='p')
    assert migrated.schema_version == ACTION_SCHEMA_ID
    assert migrated.payload.vx_forward_mps == pytest.approx(1.0, abs=1e-9)
    assert migrated.payload.vy_left_mps == pytest.approx(0.0, abs=1e-9)
    assert migrated.payload.vz_up_mps == pytest.approx(0.0, abs=1e-9)
