"""V2 execution gate: route/supervisor command -> enrollment -> executor.

This is a simulation adapter. It uses explicit simulated PX4/session identities and
does not implement a PX4 Sender, firmware validation, or real-aircraft safety.
"""
from dataclasses import dataclass
from typing import Any

from boom_birds.contracts import reasons
from boom_birds.contracts.action_v2 import (
    ActionEnvelope, VelocityPayload, build_velocity_envelope)
from boom_birds.contracts.admission import (
    ADMIT_NEW, SEND_CACHED, ActionAdmissionConfig, ActionArbiter,
    AdmissionResult, validate_action)
from boom_birds.contracts.context import (
    ContractContext, EstimatorState, MessageHeader)
from boom_birds.contracts.ownership import ControlOwner, OwnershipState
from boom_birds.contracts.versions import ACTION_SCHEMA_ID, MESSAGE_SCHEMA_ID


def _all_estimates_valid():
    return EstimatorState(
        attitude_valid=True, angular_rate_valid=True, thrust_source_valid=True,
        xy_velocity_valid=True, z_velocity_valid=True, height_valid=True,
        local_position_valid=True, visual_bearing_valid=False,
        visual_servo_valid=False, yaw_valid=True)


@dataclass
class V2ExecutionConfig:
    clock_id: str = 'host_monotonic'
    system_boot_id: int = 1
    mission_epoch: int = 0
    localization_epoch: int = 0
    control_epoch: int = 0
    px4_boot_id: int = 100
    sync_generation: int = 0
    source: str = ControlOwner.STUDENT
    policy_version: str = 'route-supervisor-v2-sim'
    ttl_ns: int = 150_000_000
    max_age_ms: int = 150
    allowed_observation_age_ns: int = 250_000_000
    axis_validity: tuple = (True, True, True, True)
    simulated_px4_identity: bool = True


class V2ActionGate:
    """Single simulated enrollment point; rejected actions never reach a caller."""

    def __init__(self, config=None):
        self.config = config or V2ExecutionConfig()
        self.ownership = OwnershipState(
            ControlOwner.STUDENT, control_epoch=self.config.control_epoch, now_ns=0)
        self.arbiter = ActionArbiter(ActionAdmissionConfig(
            ttl_ns=self.config.ttl_ns, max_age_ms=self.config.max_age_ms,
            allowed_observation_age_ns=self.config.allowed_observation_age_ns))
        self.rejections = []
        self.accepted_actions = []
        self.executed_actions = []

    @property
    def clock_id(self):
        return self.config.clock_id

    def bump_context(self, *, mission=False, localization=False, control=False,
                     px4_boot=False, sync=False):
        if mission:
            self.config.mission_epoch += 1
        if localization:
            self.config.localization_epoch += 1
        if control:
            self.config.control_epoch += 1
        if px4_boot:
            self.config.px4_boot_id += 1
        if sync:
            self.config.sync_generation += 1
        self.arbiter.revoke(reasons.ACTION_REVOKED)

    def reset(self, now_ns=0):
        """Reset simulated session: all old actions/context are invalid."""
        self.config.system_boot_id += 1
        self.config.mission_epoch += 1
        self.config.localization_epoch += 1
        self.config.control_epoch += 1
        self.config.px4_boot_id += 1
        self.config.sync_generation += 1
        self.arbiter.revoke(reasons.ACTION_REVOKED)
        self.ownership = OwnershipState(ControlOwner.STUDENT,
                                        control_epoch=self.config.control_epoch,
                                        now_ns=now_ns)
        self.rejections = []
        self.accepted_actions = []

    def revoke_ownership(self, now_ns=0):
        state = OwnershipState(ControlOwner.NONE,
                               control_epoch=self.config.control_epoch + 1,
                               now_ns=now_ns)
        self.ownership = state
        self.config.control_epoch = state.control_epoch
        self.arbiter.revoke(reasons.ACTION_REVOKED)

    def context(self, estimates=None, *, clock_id=None, sync_generation=None,
                px4_boot_id=None, owner=None, pending_owner=None):
        current = self.ownership
        return ContractContext(
            system_boot_id=self.config.system_boot_id,
            mission_epoch=self.config.mission_epoch,
            localization_epoch=self.config.localization_epoch,
            control_epoch=self.config.control_epoch,
            clock_id=clock_id if clock_id is not None else self.config.clock_id,
            px4_boot_id=(px4_boot_id if px4_boot_id is not None
                         else self.config.px4_boot_id),
            sync_generation=(sync_generation if sync_generation is not None
                             else self.config.sync_generation),
            schema_version=MESSAGE_SCHEMA_ID,
            control_owner=owner if owner is not None else current.owner,
            pending_owner=(pending_owner if pending_owner is not None
                           else (current.pending.new_owner
                                 if current.pending is not None else None)),
            estimates=estimates if estimates is not None else _all_estimates_valid())

    def build(self, command_forward_left_up_yawrate, now_ns, sequence_id,
              observation_id, *, observation_time_ns=None, ttl_ns=None,
              source=None, action_id=None, context=None, header_overrides=None):
        values = tuple(float(value) for value in command_forward_left_up_yawrate)
        if len(values) != 4:
            raise ValueError('command must have four values')
        capture = int(observation_time_ns if observation_time_ns is not None
                      else now_ns)
        if capture > now_ns:
            raise ValueError('observation time cannot be in the future')
        ttl = int(ttl_ns if ttl_ns is not None else self.config.ttl_ns)
        earliest = int(now_ns) + ttl
        header_payload = dict(
            system_boot_id=self.config.system_boot_id,
            mission_epoch=self.config.mission_epoch,
            localization_epoch=self.config.localization_epoch,
            control_epoch=self.config.control_epoch,
            clock_id=self.config.clock_id,
            px4_boot_id=self.config.px4_boot_id,
            sync_generation=self.config.sync_generation,
            sync_valid=True,
            sequence_id=int(sequence_id),
            capture_timestamp_ns=capture,
            receive_timestamp_ns=int(now_ns),
            publish_timestamp_ns=int(now_ns),
            source_id=1,
            timestamp_uncertainty_ns=0)
        if header_overrides:
            header_payload.update(header_overrides)
        header = MessageHeader(**header_payload)
        payload = VelocityPayload(
            vx_forward_mps=values[0], vy_left_mps=values[1],
            vz_up_mps=values[2], yaw_rate_ccw_world_radps=values[3],
            axis_validity=tuple(self.config.axis_validity))
        action = build_velocity_envelope(
            header, payload, observation_id=observation_id,
            input_capture_interval_ns=(capture, capture),
            earliest_input_safe_deadline_ns=earliest, ttl_ns=ttl,
            max_age_ms=self.config.max_age_ms,
            source=(source if source is not None else self.config.source),
            policy_version=self.config.policy_version,
            issued_at_monotonic_ns=int(now_ns), action_id=action_id)
        return action

    def admit(self, action, context, now_ns):
        result = self.arbiter.admit_new(action, context, now_ns)
        if result.accepted:
            self.accepted_actions.append((action, result))
        else:
            self.rejections.append((action, result))
        return result

    def send_cached(self, action, context, now_ns):
        result = self.arbiter.send_cached(action, context, now_ns)
        if result.accepted:
            self.accepted_actions.append((action, result))
        else:
            self.rejections.append((action, result))
        return result

    def authorize(self, action, context, now_ns, *, stage=ADMIT_NEW):
        """Admission check independent of cache mutation; for tests/diagnostics."""
        return validate_action(action, context, now_ns, stage=stage,
                               config=self.arbiter.config)

    def mark_executed(self, action, now_ns):
        self.executed_actions.append((action.action_id,
                                      action.issued_at_monotonic_ns,
                                      action.expires_at_monotonic_ns, now_ns))
