"""V2.2 16.3/27.2 message header and four-level context contracts (schema v2.0)."""
import pytest

from boom_birds.contracts import reasons
from boom_birds.contracts.context import (
    ClockMapping,
    ContractContext,
    MessageHeader,
    validate_message,
    worst_case_age_ns,
)
from boom_birds.contracts.versions import MESSAGE_SCHEMA_ID

NOW_NS = 1_100_000_000
CAPTURE_NS = 1_000_000_000
ALLOWED_AGE_NS = 150_000_000


def make_header(**overrides):
    values = dict(
        system_boot_id=1,
        mission_epoch=2,
        localization_epoch=3,
        control_epoch=4,
        clock_id='host_monotonic',
        px4_boot_id=5,
        sync_generation=6,
        sync_valid=True,
        sequence_id=10,
        capture_timestamp_ns=CAPTURE_NS,
        receive_timestamp_ns=CAPTURE_NS + 1_000_000,
        publish_timestamp_ns=CAPTURE_NS + 2_000_000,
        source_id=7,
        schema_version=MESSAGE_SCHEMA_ID,
        timestamp_uncertainty_ns=0,
        quarantine=False,
        valid=True,
    )
    values.update(overrides)
    return MessageHeader(**values)


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
    )
    values.update(overrides)
    return ContractContext(**values)


def test_accepts_matching_header():
    assert validate_message(make_header(), make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.ACCEPT


@pytest.mark.parametrize('field,code', [
    ('system_boot_id', reasons.REJECT_BOOT_MISMATCH),
    ('mission_epoch', reasons.REJECT_MISSION_EPOCH),
    ('localization_epoch', reasons.REJECT_LOCALIZATION_EPOCH),
    ('control_epoch', reasons.REJECT_CONTROL_EPOCH),
])
def test_each_context_level_is_checked(field, code):
    header = make_header(**{field: 999})
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS) == code


def test_clock_domain_mismatch_requires_valid_mapping():
    header = make_header(clock_id='camera')
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.REJECT_CLOCK_DOMAIN


def test_valid_clock_mapping_uses_worst_case_age():
    mapping = ClockMapping('camera', 'host_monotonic', 0, 1_000_000, 0, 2_000_000_000, 6, True)
    header = make_header(clock_id='camera')
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS,
                            mapping=mapping) == reasons.ACCEPT
    tight = 100_500_000
    assert validate_message(header, make_context(), NOW_NS, tight,
                            mapping=mapping) == reasons.REJECT_STALE


@pytest.mark.parametrize('mapping', [
    ClockMapping('camera', 'host_monotonic', 0, 0, 0, 2_000_000_000, 5, True),
    ClockMapping('camera', 'host_monotonic', 0, 0, 0, 2_000_000_000, 6, False),
    ClockMapping('camera', 'host_monotonic', 0, 0, 0, NOW_NS - 1, 6, True),
    ClockMapping('other', 'host_monotonic', 0, 0, 0, 2_000_000_000, 6, True),
])
def test_unusable_clock_mapping_is_rejected(mapping):
    header = make_header(clock_id='camera')
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS,
                            mapping=mapping) == reasons.REJECT_CLOCK_DOMAIN


@pytest.mark.parametrize('overrides', [
    {'sync_valid': False},
    {'sync_generation': 5},
    {'px4_boot_id': 6},
])
def test_sync_generation_and_px4_boot_are_isolated(overrides):
    header = make_header(**overrides)
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.REJECT_SYNC_OR_PX4_BOOT


def test_px4_boot_required_for_flight_control_messages():
    header = make_header(px4_boot_id=None)
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.ACCEPT
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS,
                            require_px4_boot=True) == reasons.REJECT_SYNC_OR_PX4_BOOT


@pytest.mark.parametrize('header,code', [
    (make_header(quarantine=True), reasons.REJECT_QUARANTINE),
    (make_header(capture_timestamp_ns=NOW_NS + 1), reasons.REJECT_FUTURE_TIMESTAMP),
    (make_header(valid=False), reasons.REJECT_INVALID),
    (make_header(schema_version='boom_birds.message.v1'), reasons.REJECT_SCHEMA_UNSUPPORTED),
])
def test_rejection_codes_in_contract_order(header, code):
    assert validate_message(header, make_context(), NOW_NS, ALLOWED_AGE_NS) == code


def test_staleness_includes_timestamp_uncertainty():
    fresh = make_header(capture_timestamp_ns=NOW_NS - ALLOWED_AGE_NS)
    assert validate_message(fresh, make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.ACCEPT
    uncertain = make_header(capture_timestamp_ns=NOW_NS - ALLOWED_AGE_NS, timestamp_uncertainty_ns=1)
    assert validate_message(uncertain, make_context(), NOW_NS, ALLOWED_AGE_NS) == reasons.REJECT_STALE


def test_per_source_age_allowance():
    header = make_header(capture_timestamp_ns=CAPTURE_NS)
    assert validate_message(header, make_context(), NOW_NS,
                            {7: ALLOWED_AGE_NS}) == reasons.ACCEPT
    assert validate_message(header, make_context(), NOW_NS,
                            {7: 50_000_000}) == reasons.REJECT_STALE
    assert validate_message(header, make_context(), NOW_NS, {}) == reasons.REJECT_STALE


def test_worst_case_age_is_unknown_for_future_same_clock_sample():
    header = make_header(capture_timestamp_ns=NOW_NS + 1)
    assert worst_case_age_ns(header, make_context(), NOW_NS) is None
    assert worst_case_age_ns(make_header(), make_context(), NOW_NS) == 100_000_000


@pytest.mark.parametrize('overrides', [
    {'system_boot_id': -1},
    {'mission_epoch': True},
    {'clock_id': ''},
    {'timestamp_uncertainty_ns': -1},
    {'capture_timestamp_ns': -5},
    {'schema_version': ''},
    {'sync_valid': 1},
    {'valid': 'yes'},
])
def test_header_rejects_invalid_field_types(overrides):
    with pytest.raises(ValueError):
        make_header(**overrides)
