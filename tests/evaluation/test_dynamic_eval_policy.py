"""Default-upgrade policy and compatibility guards (no Isaac app)."""
import pytest

from boom_birds.evaluation import dynamic_eval_policy as policy


def test_default_modes_are_the_measured_reference_origin_pair():
    resolved = policy.resolve_modes(None, None)
    assert resolved["geometry_policy"] == "reference_origin_v2"
    assert resolved["contact_mode"] == "measured_hard_reset"
    assert resolved["argument_sources"] == {
        "geometry_policy": "default", "contact_mode": "default"}


def test_explicit_new_modes_are_recorded_as_explicit():
    resolved = policy.resolve_modes("reference_origin_v2", "measured_hard_reset")
    assert resolved["geometry_policy"] == "reference_origin_v2"
    assert resolved["contact_mode"] == "measured_hard_reset"
    assert resolved["argument_sources"] == {
        "geometry_policy": "explicit", "contact_mode": "explicit"}


def test_explicit_legacy_modes_remain_available():
    resolved = policy.resolve_modes("legacy", "legacy_inference")
    assert resolved["geometry_policy"] == "legacy"
    assert resolved["contact_mode"] == "legacy_inference"
    assert all(value == "explicit"
               for value in resolved["argument_sources"].values())


def test_legacy_freeze_flags_require_both_explicit_legacy_values():
    assert policy.legacy_freeze_flags_ok(
        True, True, "legacy", "legacy_inference") is True
    assert policy.legacy_freeze_flags_ok(
        False, False, "legacy", "legacy_inference") is False
    assert policy.legacy_freeze_flags_ok(
        True, True, "reference_origin_v2", "measured_hard_reset") is False


def test_multi_environment_is_rejected_explicitly():
    policy.require_single_env(1)
    with pytest.raises(RuntimeError, match="single-env"):
        policy.require_single_env(2)


def test_migration_freeze_schema_accepts_only_v2_for_default():
    assert policy.migration_freeze_mode(
        policy.MIGRATION_FREEZE_SCHEMA_V2, True, True,
        "reference_origin_v2", "measured_hard_reset") == "v2"
    with pytest.raises(RuntimeError, match="legacy"):
        policy.migration_freeze_mode(
            policy.MIGRATION_FREEZE_SCHEMA_V1, False, False,
            "reference_origin_v2", "measured_hard_reset")


def test_legacy_raw_freeze_requires_explicit_legacy_flags():
    assert policy.migration_freeze_mode(
        policy.MIGRATION_FREEZE_SCHEMA_V1, True, True,
        "legacy", "legacy_inference") == "v1"
    with pytest.raises(RuntimeError, match="legacy"):
        policy.migration_freeze_mode(
            "boom_birds.clearance_boundary_freeze.v1", False, False,
            "reference_origin_v2", "measured_hard_reset")

def test_mixed_legacy_and_new_policies_are_rejected():
    with pytest.raises(ValueError, match="mixed"):
        policy.resolve_modes("legacy", "measured_hard_reset")
    with pytest.raises(ValueError, match="mixed"):
        policy.resolve_modes("reference_origin_v2", "legacy_inference")
