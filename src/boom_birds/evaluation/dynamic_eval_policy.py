"""Single-environment dynamic evaluation defaults and compatibility guards.

The measured contact/geometry path is now the default for the single-environment
dynamic evaluation entry point.  Historical runs must opt in to the legacy
policies explicitly; they are never selected silently.
"""
from typing import Any, Mapping

DEFAULT_GEOMETRY_POLICY = 'reference_origin_v2'
DEFAULT_CONTACT_MODE = 'measured_hard_reset'
LEGACY_GEOMETRY_POLICY = 'legacy'
LEGACY_CONTACT_MODE = 'legacy_inference'

MIGRATION_FREEZE_SCHEMA_V1 = 'boom_birds.dynamic_migration_freeze.v1'
MIGRATION_FREEZE_SCHEMA_V2 = 'boom_birds.dynamic_migration_freeze.v2'
MIGRATION_FREEZE_SCHEMA = MIGRATION_FREEZE_SCHEMA_V2
HASH_ALGORITHM = 'sha256'
TEXT_CANONICALIZATION = 'crlf_to_lf_v1'
TEXT_SCOPE = 'declared_text_source_and_config_only'


def resolve_modes(geometry_policy: str | None,
                  contact_mode: str | None) -> dict[str, Any]:
    """Resolve CLI values, recording whether each value was explicit."""
    geometry_explicit = geometry_policy is not None
    contact_explicit = contact_mode is not None
    resolved_geometry = (geometry_policy if geometry_explicit
                         else DEFAULT_GEOMETRY_POLICY)
    resolved_contact = (contact_mode if contact_explicit
                        else DEFAULT_CONTACT_MODE)
    if resolved_geometry not in (LEGACY_GEOMETRY_POLICY,
                                 DEFAULT_GEOMETRY_POLICY):
        raise ValueError('unsupported geometry policy: ' + str(resolved_geometry))
    if resolved_contact not in (LEGACY_CONTACT_MODE, DEFAULT_CONTACT_MODE):
        raise ValueError('unsupported contact mode: ' + str(resolved_contact))
    return {
        'geometry_policy': resolved_geometry,
        'contact_mode': resolved_contact,
        'argument_sources': {
            'geometry_policy': 'explicit' if geometry_explicit else 'default',
            'contact_mode': 'explicit' if contact_explicit else 'default',
        },
    }


def require_single_env(num_envs: int) -> None:
    if int(num_envs) != 1:
        raise RuntimeError(
            'single-env only: the measured contact/geometry mode does not '
            'support multi-environment or training runs (num_envs=' +
            str(num_envs) + ')')


def legacy_freeze_flags_ok(geometry_explicit: bool, contact_explicit: bool,
                           geometry_policy: str, contact_mode: str) -> bool:
    return bool(geometry_explicit and contact_explicit
                and geometry_policy == LEGACY_GEOMETRY_POLICY
                and contact_mode == LEGACY_CONTACT_MODE)


def migration_freeze_mode(schema: str, geometry_explicit: bool,
                          contact_explicit: bool, geometry_policy: str,
                          contact_mode: str) -> str:
    """Accept v2 always; accept legacy raw-hash/schema freezes only explicitly."""
    if schema == MIGRATION_FREEZE_SCHEMA_V2:
        return 'v2'
    if not legacy_freeze_flags_ok(geometry_explicit, contact_explicit,
                                  geometry_policy, contact_mode):
        raise RuntimeError(
            'legacy freeze requires explicit --geometry-policy legacy '
            '--contact-mode legacy_inference; the default measured mode will '
            'not silently reinterpret an old freeze')
    return 'v1' if schema == MIGRATION_FREEZE_SCHEMA_V1 else 'legacy'
