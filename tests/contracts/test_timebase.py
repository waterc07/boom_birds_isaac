from dataclasses import FrozenInstanceError, replace
import math
import pytest

from boom_birds.contracts.frames import decode_action
from boom_birds.contracts.timebase import command_is_valid, sample_age_s
from boom_birds.contracts.types import ActionLimits, VelocityCommand


def test_expiry_boundary_epoch_origin_and_clock():
    cmd = decode_action([1, 0, 0, 0], 0, ActionLimits(), 100, 3,
                        origin_epoch=8, clock_id='simulation:run-a')
    assert command_is_valid(cmd, cmd.valid_until_ns - 1, 3,
                            origin_epoch=8, clock_id='simulation:run-a')
    assert not command_is_valid(cmd, cmd.valid_until_ns, 3,
                                origin_epoch=8, clock_id='simulation:run-a')
    assert not command_is_valid(cmd, 101, 4, origin_epoch=8, clock_id='simulation:run-a')
    assert not command_is_valid(cmd, 101, 3, origin_epoch=9, clock_id='simulation:run-a')
    assert not command_is_valid(cmd, 101, 3, origin_epoch=8, clock_id='host_monotonic')
    assert not command_is_valid(cmd, 99, 3, origin_epoch=8, clock_id='simulation:run-a')


def test_immutable_resend_does_not_extend_deadline():
    cmd = decode_action([0] * 4, 0, ActionLimits(), 0, 0)
    for now in (1, 10, 100):
        assert command_is_valid(cmd, now, 0)
        assert cmd.valid_until_ns == 150_000_000
    with pytest.raises(FrozenInstanceError):
        cmd.valid_until_ns += 1
    assert not command_is_valid(cmd, 150_000_000, 0)


@pytest.mark.parametrize('now,clock,expected', [(2_000_000_000, 'camera', 1.0),
                                               (2_000_000_000, 'host', None),
                                               (999_999_999, 'camera', None)])
def test_age_only_for_same_clock_and_nonnegative_duration(now, clock, expected):
    assert sample_age_s(1_000_000_000, 'camera', now, clock) == expected


def test_invalid_physical_command_rejected():
    cmd = decode_action([0] * 4, 0, ActionLimits(), 0, 0)
    for invalid in (replace(cmd, velocity_enu_mps=(math.nan, 0, 0)),
                    replace(cmd, yaw_rate_rad_s=math.inf), replace(cmd, valid_until_ns=0)):
        assert not command_is_valid(invalid, 1, 0)


@pytest.mark.parametrize('now,epoch', [(-1, 0), (0, -1), (1.5, 0)])
def test_decoder_requires_nonnegative_integer_time_and_epoch(now, epoch):
    with pytest.raises(ValueError):
        decode_action([0] * 4, 0, ActionLimits(), now, epoch)


def test_public_command_rejects_mutable_velocity_container():
    with pytest.raises(ValueError):
        VelocityCommand([0.0, 0.0, 0.0], 0, 0, 150_000_000, 0)


def test_nonstring_clocks_never_match_by_python_coercion():
    assert sample_age_s(0, 1, 1_000_000_000, True) is None
    cmd = decode_action([0] * 4, 0, ActionLimits(), 0, 0)
    assert not command_is_valid(replace(cmd, clock_id=1), 1, 0, clock_id=True)
