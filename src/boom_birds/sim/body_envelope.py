"""Body envelope geometry contract (``boom_birds.body_envelope.v2``).

Why this module exists
----------------------
The previous round defined the robot envelope as a sphere over the spawn-pose
AABB *half diagonal*::

    r_previous = || half_extents_m ||_2          (sphere centered at the AABB center)

That radius is an around-origin radius only when the AABB center coincides with
the robot reference origin.  The USD ``BBoxCache`` measurement returns a
world-aligned AABB whose center can be offset from the root origin, and in that
case a sphere of radius ``r_previous`` around the origin does not contain the
box.  The conservative around-origin radius is the largest distance from the
origin to any AABB corner::

    r_origin = || |center_offset_m| + half_extents_m ||_2

with the sphere centered at the robot reference origin, not at the AABB center.
A rigid rotation about the reference origin preserves every corner distance to
the origin, so ``r_origin`` contains the AABB for any such rotation.

Production rule
---------------
* clearance / stop-requirement envelopes use ``sphere_about_origin``
  (``r_origin``), recorded under ``production.envelope_field``;
* ``sphere_about_aabb_center`` (``r_previous``) is kept only to compare with the
  previous round and must never be used as an around-origin radius;
* the AABB is a bound at one measured joint state; a sphere/AABB bound is not an
  all-attitude triangle-mesh sweep proof;
* ``coverage`` records which geometry the AABB was measured over.  The runtime
  USD ``BBoxCache`` can be asked for collision-geometry prims
  (``HasAPI(UsdPhysics.CollisionAPI)``) or visual mesh prims; mixing them, or
  measuring only one of them, changes what the envelope can claim, so the source
  and the per-category prim lists are part of the record.

Runtime measurement recipe (Isaac runner, documented here for reuse)
--------------------------------------------------------------------
1. collect world-space AABB corners for collision-geometry prims and visual
   mesh prims separately (``UsdGeom.BBoxCache`` with the recorded purposes and
   time code);
2. inverse-transform those corners with the robot root pose into the robot
   reference frame (:func:`to_reference_frame`) -- do *not* keep the world-frame
   half extents next to a robot-frame center, because a world-aligned AABB is a
   rotated box in the robot frame;
3. reduce the reference-frame corners to ``(half_extents_m, center_offset_m)``
   with :func:`aabb_from_points`;
4. build the record with :func:`body_envelope_record` and check it with
   :func:`validate_body_envelope_record`.

The record's ``measurement`` mapping is free-form but should carry at least the
fields listed in :data:`RUNTIME_MEASUREMENT_FIELDS`.
"""
import math
from collections.abc import Mapping
from dataclasses import dataclass

BODY_ENVELOPE_SCHEMA_VERSION = 'boom_birds.body_envelope.v2'
BODY_ENVELOPE_UNITS = 'm'
AABB_REFERENCE_ORIGIN = 'robot_root_prim_origin'
AABB_FRAME = 'robot_reference_frame'
REFERENCE_ORIGIN_KIND = 'robot_reference_origin'
AABB_CENTER_KIND = 'aabb_center'

ENVELOPE_SOURCE_COLLISION_GEOMETRY = 'collision_geometry'
ENVELOPE_SOURCE_VISUAL_MESH = 'visual_mesh'
ENVELOPE_SOURCE_MIXED = 'mixed'
ENVELOPE_SOURCE_UNKNOWN = 'unknown'
ENVELOPE_SOURCES = (ENVELOPE_SOURCE_COLLISION_GEOMETRY,
                    ENVELOPE_SOURCE_VISUAL_MESH,
                    ENVELOPE_SOURCE_MIXED,
                    ENVELOPE_SOURCE_UNKNOWN)

ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN = \
    'any_rigid_rotation_about_reference_origin'
ATTITUDE_SCOPE_AABB_CENTER_ONLY = 'rigid_rotation_about_aabb_center_only'
JOINT_STATE_SCOPE_FIXED_AT_MEASUREMENT = 'fixed_joint_state_at_measurement'
JOINT_STATE_SCOPE_ANY = 'any_joint_state'

SPHERE_ABOUT_ORIGIN_RULE = 'sphere_about_reference_origin_max_aabb_corner'
SPHERE_ABOUT_AABB_CENTER_RULE = 'sphere_about_aabb_center_half_diagonal'
PRODUCTION_ENVELOPE_FIELD = 'sphere_about_origin'
PREVIOUS_RULE_NAME = 'box_conservative_sphere_radius'
PREVIOUS_RULE_CENTER_KIND = AABB_CENTER_KIND
UNDERESTIMATE_FORMULA = ('|| |center_offset_m| + half_extents_m ||_2'
                         ' - || half_extents_m ||_2')

# Measured robot AABB quoted by the 2026-11-02 latency / clearance-boundary runs
# (``body_envelope`` in the run manifest, prim ``/World/envs/env_0/Robot``).
PREVIOUS_ROUND_AABB_PRIM = '/World/envs/env_0/Robot'
PREVIOUS_ROUND_HALF_EXTENTS_M = (0.05454223374277353, 0.03820826672017574,
                                 0.013588040310423821)
PREVIOUS_ROUND_SPHERE_RADIUS_M = math.sqrt(
    sum(value * value for value in PREVIOUS_ROUND_HALF_EXTENTS_M))

LIMITATION_NOT_MESH_SWEEP = ('AABB/sphere bound is not an all-attitude '
                             'triangle-mesh sweep proof')
LIMITATION_FIXED_JOINT_STATE = ('AABB is measured at one fixed joint state; rotor '
                                'spin, flex and other joint states are not swept')
LIMITATION_SUB_BODY_COVERAGE = ('propeller/sub-body geometry is covered only '
                                'through the aggregate AABB; per-sub-body '
                                'collision coverage is not proven')
LIMITATION_VISUAL_ONLY = ('envelope source is visual mesh, not collision '
                          'geometry; the bound may differ from the PhysX '
                          'collision shape')
LIMITATION_MIXED_SOURCE = ('coverage mixes visual mesh and collision geometry; '
                           'the aggregate bound does not isolate collision '
                           'geometry')
LIMITATION_UNKNOWN_SOURCE = ('envelope coverage source is unknown; inclusion of '
                             'collision geometry is not established')
LIMITATION_AABB_CENTER_ONLY = ('valid only with the sphere centered at the AABB '
                               'center; not an around-origin radius')
MANDATORY_LIMITATIONS = (LIMITATION_NOT_MESH_SWEEP, LIMITATION_FIXED_JOINT_STATE)

# Fields the runtime measurement should emit alongside the geometry so a later
# reader can reproduce the AABB without re-running Isaac.
RUNTIME_MEASUREMENT_FIELDS = (
    'measurement.robot_root_prim',
    'measurement.robot_root_pose_world',
    'measurement.bbox_cache_purpose',
    'measurement.bbox_cache_time_code',
    'measurement.frame',
    'measurement.reference_origin',
    'measurement.transform',
    'measurement.sim_time_s',
    'measurement.joint_positions',
    'coverage.source',
    'coverage.collision_prim_paths',
    'coverage.visual_prim_paths',
    'coverage.sub_bodies',
    'coverage.joint_state_scope',
    'coverage.limitations',
    'aabb.half_extents_m',
    'aabb.center_offset_m',
)

_PROP_SUB_BODY_TOKENS = ('prop', 'props', 'propeller', 'rotor', 'motor')


def _as_float(value, name):
    if isinstance(value, bool) or isinstance(value, (str, bytes)):
        raise ValueError(name + ' must be a real number')
    try:
        converted = float(value)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be a real number')
    if not math.isfinite(converted):
        raise ValueError(name + ' must be finite')
    return converted


def _as_vector3(value, name):
    if isinstance(value, (str, bytes)):
        raise ValueError(name + ' must be a three-component vector')
    try:
        items = list(value)
    except TypeError:
        raise ValueError(name + ' must be a three-component vector')
    if len(items) != 3:
        raise ValueError(name + ' must hold exactly three components')
    return tuple(_as_float(item, name + ' component') for item in items)


def _as_half_extents(half_extents_m):
    values = _as_vector3(half_extents_m, 'half_extents_m')
    if any(value < 0.0 for value in values):
        raise ValueError('half_extents_m must be non-negative')
    return values


def _as_offset(center_offset_m):
    if center_offset_m is None:
        return (0.0, 0.0, 0.0)
    return _as_vector3(center_offset_m, 'center_offset_m')


def _as_point_list(points, name='points'):
    if isinstance(points, (str, bytes)):
        raise ValueError(name + ' must be an iterable of three-component vectors')
    try:
        items = list(points)
    except TypeError:
        raise ValueError(name + ' must be an iterable of three-component vectors')
    if not items:
        raise ValueError(name + ' must not be empty')
    return tuple(_as_vector3(item, name + ' entry') for item in items)


def _as_string_tuple(values, name):
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError(name + ' must be a sequence of strings, not one string')
    try:
        items = list(values)
    except TypeError:
        raise ValueError(name + ' must be a sequence of strings')
    converted = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(name + ' entries must be non-empty strings')
        converted.append(item)
    return tuple(converted)


def _as_scope(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be a non-empty string')
    return value


def _as_enum(value, allowed, name):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(name + ' must be one of: ' + ', '.join(allowed))
    return value


def _as_rotation_matrix(value):
    if value is None:
        return None
    try:
        rows = list(value)
    except TypeError:
        raise ValueError('rotation_world_from_reference must be a 3x3 matrix')
    if len(rows) != 3:
        raise ValueError('rotation_world_from_reference must be a 3x3 matrix')
    return tuple(_as_vector3(row, 'rotation_world_from_reference row')
                 for row in rows)


def aabb_corners(half_extents_m, center_offset_m=None):
    """Eight corners of the axis-aligned box in the reference frame."""
    half = _as_half_extents(half_extents_m)
    offset = _as_offset(center_offset_m)
    return tuple((offset[0] + sx * half[0],
                  offset[1] + sy * half[1],
                  offset[2] + sz * half[2])
                 for sx in (-1.0, 1.0)
                 for sy in (-1.0, 1.0)
                 for sz in (-1.0, 1.0))


def aabb_from_points(points, reference_origin_m=None):
    """Reduce sample points to ``(half_extents_m, center_offset_m)``.

    ``points`` are axis-aligned samples of the geometry -- typically the eight
    corners of a USD ``BBoxCache`` world AABB after inverse-transforming them
    into the robot reference frame.  ``center_offset_m`` is the AABB center
    relative to ``reference_origin_m`` (the world origin when omitted), which
    is the quantity the around-origin sphere rule needs.
    """
    samples = _as_point_list(points)
    origin = ((0.0, 0.0, 0.0) if reference_origin_m is None
              else _as_vector3(reference_origin_m, 'reference_origin_m'))
    minimums = tuple(min(sample[axis] for sample in samples) for axis in range(3))
    maximums = tuple(max(sample[axis] for sample in samples) for axis in range(3))
    half_extents = tuple((maximums[axis] - minimums[axis]) / 2.0
                         for axis in range(3))
    center = tuple((maximums[axis] + minimums[axis]) / 2.0 for axis in range(3))
    center_offset = tuple(center[axis] - origin[axis] for axis in range(3))
    return half_extents, center_offset


def to_reference_frame(points, *, origin_world_m,
                       rotation_world_from_reference=None):
    """Inverse-transform world points into the robot reference frame.

    ``rotation_world_from_reference`` is the rotation ``R`` with
    ``p_world = origin_world + R @ p_reference``; it defaults to identity.  The
    runtime passes the measured root pose here before :func:`aabb_from_points`
    so a world-aligned AABB is not mistaken for a robot-frame AABB.
    """
    origin = _as_vector3(origin_world_m, 'origin_world_m')
    matrix = _as_rotation_matrix(rotation_world_from_reference)
    samples = _as_point_list(points)
    transformed = []
    for sample in samples:
        delta = tuple(sample[axis] - origin[axis] for axis in range(3))
        if matrix is None:
            transformed.append(delta)
        else:
            transformed.append(tuple(
                sum(matrix[row][column] * delta[row] for row in range(3))
                for column in range(3)))
    return tuple(transformed)


def body_envelope_from_world_aabb(world_half_extents_m, world_center_m, *,
                                  origin_world_m,
                                  rotation_world_from_reference=None,
                                  coverage=None, measurement=None):
    """Build a record from a world-aligned AABB measured by ``BBoxCache``.

    The eight world AABB corners are inverse-transformed into the robot
    reference frame and reduced again with :func:`aabb_from_points`, so a
    non-reference robot attitude cannot leak world-frame half extents into the
    robot-frame AABB.  The reduced bound contains the true geometry (it is the
    AABB of a rotated box that already contained the geometry), so the
    around-origin sphere derived from it stays conservative, at the cost of
    tightness when the measured attitude is not the reference attitude.
    """
    world_corners = aabb_corners(world_half_extents_m, world_center_m)
    reference_corners = to_reference_frame(
        world_corners, origin_world_m=origin_world_m,
        rotation_world_from_reference=rotation_world_from_reference)
    half_extents, center_offset = aabb_from_points(reference_corners)
    return body_envelope_record(half_extents, center_offset,
                                coverage=coverage, measurement=measurement)


def conservative_sphere_about_origin(half_extents_m, center_offset_m=None):
    """Sphere centered at the robot reference origin that contains the AABB.

    ``radius_m = || |center_offset_m| + half_extents_m ||_2`` is the distance
    from the origin to the farthest AABB corner, so the sphere contains the AABB
    for any rigid rotation about the origin.  The sphere center is the origin,
    not the AABB center.
    """
    half = _as_half_extents(half_extents_m)
    offset = _as_offset(center_offset_m)
    radius = math.sqrt(sum((abs(offset[axis]) + half[axis]) ** 2
                           for axis in range(3)))
    return {
        'radius_m': radius,
        'center_offset_m': [0.0, 0.0, 0.0],
        'center_kind': REFERENCE_ORIGIN_KIND,
        'aabb_center_offset_m': list(offset),
        'rule': SPHERE_ABOUT_ORIGIN_RULE,
        'rule_definition': ('max over the eight AABB corners of ||corner||_2'
                            ' = || |center_offset_m| + half_extents_m ||_2'
                            ' about the robot reference origin'),
        'attitude_scope': ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN,
        'units': BODY_ENVELOPE_UNITS,
        'proof_notes': [
            ('the farthest point of an axis-aligned box from the origin is the '
             'corner whose coordinate signs match the box center offset, so the '
             'max corner distance is || |center_offset_m| + half_extents_m ||_2'),
            ('a rigid rotation about the reference origin preserves every corner '
             'distance to the origin, so the sphere centered at the origin '
             'contains the box for any such rotation'),
            ('the sphere center is the robot reference origin, not the AABB '
             'center; the half diagonal about the AABB center is not an '
             'around-origin radius when the center offset is non-zero'),
        ],
    }


def sphere_about_aabb_center(half_extents_m, center_offset_m=None):
    """Previous-round rule: half diagonal about the AABB center.

    Only valid when the sphere center is explicitly the AABB center; it must
    not be used as an around-origin radius.  Kept to compare with the previous
    round and to quantify the underestimate.
    """
    half = _as_half_extents(half_extents_m)
    offset = _as_offset(center_offset_m)
    radius = math.sqrt(sum(value * value for value in half))
    return {
        'radius_m': radius,
        'center_offset_m': list(offset),
        'center_kind': AABB_CENTER_KIND,
        'aabb_center_offset_m': list(offset),
        'rule': SPHERE_ABOUT_AABB_CENTER_RULE,
        'rule_definition': ('radius_m = || half_extents_m ||_2 with the sphere '
                            'centered at the AABB center'),
        'attitude_scope': ATTITUDE_SCOPE_AABB_CENTER_ONLY,
        'units': BODY_ENVELOPE_UNITS,
        'proof_notes': [
            ('the distance from the AABB center to any corner is the half '
             'diagonal, and rotation about the center preserves it'),
        ],
        'limitations': [LIMITATION_AABB_CENTER_ONLY, LIMITATION_NOT_MESH_SWEEP],
    }


def compare_with_previous_rule(half_extents_m, center_offset_m=None,
                               tolerance_m=1e-12):
    """Quantify how the previous half-diagonal radius relates to the rule.

    The previous radius is exact when ``center_offset_m == 0`` and
    underestimates the around-origin radius by
    ``|| |center_offset_m| + half_extents_m ||_2 - || half_extents_m ||_2``
    as soon as any offset component is non-zero.
    """
    half = _as_half_extents(half_extents_m)
    offset = _as_offset(center_offset_m)
    tolerance = _as_float(tolerance_m, 'tolerance_m')
    if tolerance < 0.0:
        raise ValueError('tolerance_m must be non-negative')
    previous = math.sqrt(sum(value * value for value in half))
    corrected = math.sqrt(sum((abs(offset[axis]) + half[axis]) ** 2
                              for axis in range(3)))
    difference = corrected - previous
    return {
        'previous_rule': PREVIOUS_RULE_NAME,
        'previous_rule_center_kind': PREVIOUS_RULE_CENTER_KIND,
        'previous_radius_m': previous,
        'previous_round_reported_radius_m': PREVIOUS_ROUND_SPHERE_RADIUS_M,
        'corrected_rule': SPHERE_ABOUT_ORIGIN_RULE,
        'corrected_center_kind': REFERENCE_ORIGIN_KIND,
        'corrected_radius_m': corrected,
        'underestimate_m': difference,
        'underestimate_formula': UNDERESTIMATE_FORMULA,
        'equal_within_tolerance': abs(difference) <= tolerance,
        'tolerance_m': tolerance,
        'previous_rule_exact_when': ('center_offset_m == (0, 0, 0): the AABB '
                                     'center coincides with the robot '
                                     'reference origin'),
        'previous_rule_underestimates_when': ('any center_offset_m component is '
                                              'non-zero: the AABB center is '
                                              'offset from the robot reference '
                                              'origin'),
        'note': ('the previous 0.067966 m half-diagonal radius is an '
                 'around-origin radius only for a centered AABB; otherwise it '
                 'underestimates by underestimate_m'),
    }


def _has_prop_sub_body(sub_bodies):
    for name in sub_bodies:
        token = name.lower()
        if token in _PROP_SUB_BODY_TOKENS:
            return True
        if any(fragment in token for fragment in ('prop', 'rotor', 'motor')):
            return True
        if token.startswith('m') and token[1:].isdigit():
            return True
    return False


def _dedupe(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _merged_limitations(coverage):
    limitations = list(MANDATORY_LIMITATIONS)
    if _has_prop_sub_body(coverage.sub_bodies):
        limitations.append(LIMITATION_SUB_BODY_COVERAGE)
    if coverage.source == ENVELOPE_SOURCE_VISUAL_MESH:
        limitations.append(LIMITATION_VISUAL_ONLY)
    elif coverage.source == ENVELOPE_SOURCE_MIXED:
        limitations.append(LIMITATION_MIXED_SOURCE)
    elif coverage.source == ENVELOPE_SOURCE_UNKNOWN:
        limitations.append(LIMITATION_UNKNOWN_SOURCE)
    limitations.extend(coverage.limitations)
    return _dedupe(limitations)


@dataclass(frozen=True)
class EnvelopeCoverage:
    """Which geometry the AABB measurement covered, and its scopes.

    ``source`` is the measurement category: collision geometry, visual mesh, a
    mix of both, or unknown.  ``collision_prim_paths``/``visual_prim_paths``
    list the prims measured per category (``prim_paths`` is the union used for
    the AABB).  ``sub_bodies`` names the measured sub-bodies (for example
    ``body`` and ``m1``..``m4``).  ``attitude_scope`` and ``joint_state_scope``
    state the attitude/joint range the coverage claim is limited to, and
    ``limitations`` records what the envelope does not prove.
    """

    source: str = ENVELOPE_SOURCE_UNKNOWN
    prim_paths: tuple = ()
    sub_bodies: tuple = ()
    attitude_scope: str = ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN
    joint_state_scope: str = JOINT_STATE_SCOPE_FIXED_AT_MEASUREMENT
    limitations: tuple = ()
    collision_prim_paths: tuple = ()
    visual_prim_paths: tuple = ()

    def __post_init__(self):
        source = _as_enum(self.source, ENVELOPE_SOURCES, 'coverage.source')
        collision_paths = _as_string_tuple(self.collision_prim_paths,
                                           'coverage.collision_prim_paths')
        visual_paths = _as_string_tuple(self.visual_prim_paths,
                                        'coverage.visual_prim_paths')
        prim_paths = _as_string_tuple(self.prim_paths, 'coverage.prim_paths')
        if not prim_paths:
            prim_paths = _dedupe(collision_paths + visual_paths)
        sub_bodies = _as_string_tuple(self.sub_bodies, 'coverage.sub_bodies')
        limitations = _as_string_tuple(self.limitations, 'coverage.limitations')
        attitude_scope = _as_scope(self.attitude_scope, 'coverage.attitude_scope')
        joint_state_scope = _as_scope(self.joint_state_scope,
                                      'coverage.joint_state_scope')
        object.__setattr__(self, 'source', source)
        object.__setattr__(self, 'collision_prim_paths', collision_paths)
        object.__setattr__(self, 'visual_prim_paths', visual_paths)
        object.__setattr__(self, 'prim_paths', prim_paths)
        object.__setattr__(self, 'sub_bodies', sub_bodies)
        object.__setattr__(self, 'limitations', limitations)
        object.__setattr__(self, 'attitude_scope', attitude_scope)
        object.__setattr__(self, 'joint_state_scope', joint_state_scope)

    def to_dict(self):
        return {
            'source': self.source,
            'prim_paths': list(self.prim_paths),
            'collision_prim_paths': list(self.collision_prim_paths),
            'visual_prim_paths': list(self.visual_prim_paths),
            'sub_bodies': list(self.sub_bodies),
            'attitude_scope': self.attitude_scope,
            'joint_state_scope': self.joint_state_scope,
            'limitations': list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload):
        if isinstance(payload, cls):
            return payload
        if not isinstance(payload, Mapping):
            raise ValueError('coverage must be an EnvelopeCoverage or a mapping')
        return cls(source=payload.get('source', ENVELOPE_SOURCE_UNKNOWN),
                   prim_paths=payload.get('prim_paths', ()),
                   sub_bodies=payload.get('sub_bodies', ()),
                   attitude_scope=payload.get(
                       'attitude_scope',
                       ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN),
                   joint_state_scope=payload.get(
                       'joint_state_scope',
                       JOINT_STATE_SCOPE_FIXED_AT_MEASUREMENT),
                   limitations=payload.get('limitations', ()),
                   collision_prim_paths=payload.get('collision_prim_paths', ()),
                   visual_prim_paths=payload.get('visual_prim_paths', ()))


class BodyEnvelopeValidationError(ValueError):
    """Record validation failure with a stable ``reason`` code."""

    def __init__(self, reason, message):
        super().__init__('[' + reason + '] ' + message)
        self.reason = reason


def _mapping_field(container, key, name):
    value = container.get(key)
    if not isinstance(value, Mapping):
        raise BodyEnvelopeValidationError(
            'RECORD_FIELD_MISSING', name + ' must be a mapping')
    return value


def _vector_field(container, key, reason, name, half_extents=False):
    if key not in container:
        raise BodyEnvelopeValidationError(
            reason, name + ' is required')
    try:
        if half_extents:
            return _as_half_extents(container[key])
        return _as_vector3(container[key], name)
    except ValueError as error:
        raise BodyEnvelopeValidationError(reason, str(error))


def _scalar_field(container, key, reason, name):
    try:
        return _as_float(container.get(key), name)
    except ValueError as error:
        raise BodyEnvelopeValidationError(reason, str(error))


def _limitations_field(value, name):
    try:
        limitations = _as_string_tuple(value, name)
    except ValueError as error:
        raise BodyEnvelopeValidationError('COVERAGE_LIMITATIONS', str(error))
    if not limitations:
        raise BodyEnvelopeValidationError(
            'COVERAGE_LIMITATIONS',
            name + ' must not be empty: the record must not claim unqualified '
                   'full coverage')
    return limitations


def _path_field(container, key):
    try:
        return _as_string_tuple(container.get(key, ()), 'coverage.' + key)
    except ValueError as error:
        raise BodyEnvelopeValidationError('COVERAGE_PRIM_PATHS', str(error))


def validate_body_envelope_record(record, tolerance_m=1e-9):
    """Validate a body-envelope record; raise on an unsafe/incoherent one.

    Rejects, in particular: an around-origin radius below
    ``|| |center_offset_m| + half_extents_m ||_2`` (which catches the previous
    half-diagonal radius being used as an around-origin radius), the AABB-center
    rule stored in the around-origin field, a production radius that is not the
    around-origin radius, a coverage claim of collision geometry with no
    collision prim paths, and records without the mandatory non-sweep
    limitation.
    """
    if not isinstance(record, Mapping):
        raise BodyEnvelopeValidationError('RECORD_TYPE',
                                          'record must be a mapping')
    tolerance = _as_float(tolerance_m, 'tolerance_m')
    if tolerance < 0.0:
        raise ValueError('tolerance_m must be non-negative')
    if record.get('schema_version') != BODY_ENVELOPE_SCHEMA_VERSION:
        raise BodyEnvelopeValidationError(
            'SCHEMA_VERSION',
            'schema_version must be ' + BODY_ENVELOPE_SCHEMA_VERSION)

    aabb = _mapping_field(record, 'aabb', 'aabb')
    half = _vector_field(aabb, 'half_extents_m', 'AABB_HALF_EXTENTS_INVALID',
                         'aabb.half_extents_m', half_extents=True)
    offset = _vector_field(aabb, 'center_offset_m', 'AABB_CENTER_OFFSET_INVALID',
                           'aabb.center_offset_m')
    lengths = _vector_field(aabb, 'lengths_m', 'AABB_LENGTHS_INVALID',
                            'aabb.lengths_m')
    for axis in range(3):
        if not math.isclose(lengths[axis], 2.0 * half[axis],
                            rel_tol=0.0, abs_tol=max(tolerance, 1e-12)):
            raise BodyEnvelopeValidationError(
                'AABB_LENGTHS_MISMATCH',
                'aabb.lengths_m must equal twice aabb.half_extents_m')

    sphere = _mapping_field(record, 'sphere_about_origin',
                            'sphere_about_origin')
    if sphere.get('rule') != SPHERE_ABOUT_ORIGIN_RULE:
        raise BodyEnvelopeValidationError(
            'SPHERE_ABOUT_ORIGIN_RULE',
            'sphere_about_origin.rule must be ' + SPHERE_ABOUT_ORIGIN_RULE)
    radius = _scalar_field(sphere, 'radius_m', 'SPHERE_ABOUT_ORIGIN_RADIUS_INVALID',
                           'sphere_about_origin.radius_m')
    required = math.sqrt(sum((abs(offset[axis]) + half[axis]) ** 2
                             for axis in range(3)))
    if radius < required - tolerance:
        raise BodyEnvelopeValidationError(
            'SPHERE_ABOUT_ORIGIN_TOO_SMALL',
            'sphere_about_origin.radius_m {radius!r} is below the required '
            'around-origin radius {required!r} = || |center_offset_m| + '
            'half_extents_m ||_2; do not use the AABB-center half diagonal '
            'radius as an around-origin radius'.format(radius=radius,
                                                       required=required))
    center_offset = _vector_field(sphere, 'center_offset_m',
                                  'SPHERE_ABOUT_ORIGIN_CENTER',
                                  'sphere_about_origin.center_offset_m')
    if any(abs(value) > tolerance for value in center_offset):
        raise BodyEnvelopeValidationError(
            'SPHERE_ABOUT_ORIGIN_CENTER',
            'sphere_about_origin must be centered at the robot reference '
            'origin (center_offset_m == [0, 0, 0])')
    attitude_scope = sphere.get('attitude_scope')
    if attitude_scope != ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN:
        raise BodyEnvelopeValidationError(
            'SPHERE_ABOUT_ORIGIN_ATTITUDE_SCOPE',
            'sphere_about_origin.attitude_scope must be ' +
            ATTITUDE_SCOPE_ANY_ROTATION_ABOUT_REFERENCE_ORIGIN)
    if record.get('attitude_scope') != attitude_scope:
        raise BodyEnvelopeValidationError(
            'ATTITUDE_SCOPE_MISMATCH',
            'record.attitude_scope must match '
            'sphere_about_origin.attitude_scope')

    center_sphere = _mapping_field(record, 'sphere_about_aabb_center',
                                   'sphere_about_aabb_center')
    if center_sphere.get('rule') != SPHERE_ABOUT_AABB_CENTER_RULE:
        raise BodyEnvelopeValidationError(
            'AABB_CENTER_SPHERE_RULE',
            'sphere_about_aabb_center.rule must be ' +
            SPHERE_ABOUT_AABB_CENTER_RULE)
    center_radius = _scalar_field(center_sphere, 'radius_m',
                                  'AABB_CENTER_SPHERE_RADIUS_INVALID',
                                  'sphere_about_aabb_center.radius_m')
    half_diagonal = math.sqrt(sum(value * value for value in half))
    if abs(center_radius - half_diagonal) > max(tolerance, 1e-12):
        raise BodyEnvelopeValidationError(
            'AABB_CENTER_SPHERE_RADIUS',
            'sphere_about_aabb_center.radius_m must be the half diagonal '
            '|| half_extents_m ||_2')

    production = _mapping_field(record, 'production', 'production')
    if production.get('envelope_field') != PRODUCTION_ENVELOPE_FIELD:
        raise BodyEnvelopeValidationError(
            'PRODUCTION_RADIUS_FIELD',
            'production.envelope_field must be ' + PRODUCTION_ENVELOPE_FIELD)
    production_radius = _scalar_field(production, 'radius_m',
                                      'PRODUCTION_RADIUS_MISMATCH',
                                      'production.radius_m')
    if abs(production_radius - radius) > tolerance:
        raise BodyEnvelopeValidationError(
            'PRODUCTION_RADIUS_MISMATCH',
            'production.radius_m must equal '
            'sphere_about_origin.radius_m')
    if production.get('center_kind') != REFERENCE_ORIGIN_KIND:
        raise BodyEnvelopeValidationError(
            'PRODUCTION_RADIUS_FIELD',
            'production.center_kind must be ' + REFERENCE_ORIGIN_KIND)

    coverage = _mapping_field(record, 'coverage', 'coverage')
    source = coverage.get('source')
    if source not in ENVELOPE_SOURCES:
        raise BodyEnvelopeValidationError(
            'COVERAGE_SOURCE',
            'coverage.source must be one of: ' + ', '.join(ENVELOPE_SOURCES))
    collision_paths = _path_field(coverage, 'collision_prim_paths')
    visual_paths = _path_field(coverage, 'visual_prim_paths')
    prim_paths = _path_field(coverage, 'prim_paths')
    for path in collision_paths + visual_paths:
        if path not in prim_paths:
            raise BodyEnvelopeValidationError(
                'COVERAGE_PRIM_PATHS',
                'coverage.prim_paths must include every collision/visual prim '
                'path')
    if source == ENVELOPE_SOURCE_COLLISION_GEOMETRY and not collision_paths:
        raise BodyEnvelopeValidationError(
            'COVERAGE_PRIM_PATHS',
            'coverage.source collision_geometry requires non-empty '
            'coverage.collision_prim_paths')
    if source == ENVELOPE_SOURCE_VISUAL_MESH and not visual_paths:
        raise BodyEnvelopeValidationError(
            'COVERAGE_PRIM_PATHS',
            'coverage.source visual_mesh requires non-empty '
            'coverage.visual_prim_paths')
    if source == ENVELOPE_SOURCE_MIXED and not (collision_paths and visual_paths):
        raise BodyEnvelopeValidationError(
            'COVERAGE_PRIM_PATHS',
            'coverage.source mixed requires both collision_prim_paths and '
            'visual_prim_paths')

    limitations = _limitations_field(record.get('limitations'), 'limitations')
    _limitations_field(coverage.get('limitations'), 'coverage.limitations')
    joined = ' '.join(limitations).lower()
    if not ('triangle-mesh sweep' in joined and 'not' in joined):
        raise BodyEnvelopeValidationError(
            'NON_SWEEP_LIMITATION',
            'limitations must state that the bound is not an all-attitude '
            'triangle-mesh sweep proof')

    if record.get('joint_state_scope') != coverage.get('joint_state_scope'):
        raise BodyEnvelopeValidationError(
            'JOINT_STATE_SCOPE_MISMATCH',
            'record.joint_state_scope must match coverage.joint_state_scope')
    return record


def body_envelope_record(half_extents_m, center_offset_m, *, coverage=None,
                         measurement=None, include_previous_rule_comparison=True):
    """Complete serializable body-envelope record (``body_envelope.v2``).

    ``half_extents_m``/``center_offset_m`` are the measured AABB in the robot
    reference frame.  ``coverage`` is an :class:`EnvelopeCoverage` or mapping
    describing which prims/sub-bodies were measured; when omitted the coverage
    source is ``unknown`` and the limitations say so.  The production radius is
    always ``sphere_about_origin.radius_m``.
    """
    half = _as_half_extents(half_extents_m)
    offset = _as_offset(center_offset_m)
    coverage_record = (EnvelopeCoverage()
                       if coverage is None
                       else EnvelopeCoverage.from_dict(coverage))
    limitations = _merged_limitations(coverage_record)
    sphere_origin = conservative_sphere_about_origin(half, offset)
    sphere_center = sphere_about_aabb_center(half, offset)
    if measurement is not None and not isinstance(measurement, Mapping):
        raise ValueError('measurement must be a mapping or None')
    measurement_record = None if measurement is None else dict(measurement)
    coverage_record_dict = coverage_record.to_dict()
    coverage_record_dict['limitations'] = list(limitations)
    record = {
        'schema_version': BODY_ENVELOPE_SCHEMA_VERSION,
        'units': BODY_ENVELOPE_UNITS,
        'frame': AABB_FRAME,
        'aabb': {
            'half_extents_m': list(half),
            'center_offset_m': list(offset),
            'lengths_m': [2.0 * value for value in half],
            'reference_origin': AABB_REFERENCE_ORIGIN,
            'frame': AABB_FRAME,
            'units': BODY_ENVELOPE_UNITS,
        },
        'sphere_about_origin': sphere_origin,
        'sphere_about_aabb_center': sphere_center,
        'production': {
            'envelope_field': PRODUCTION_ENVELOPE_FIELD,
            'radius_m': sphere_origin['radius_m'],
            'center_kind': REFERENCE_ORIGIN_KIND,
            'rule': SPHERE_ABOUT_ORIGIN_RULE,
            'attitude_scope': sphere_origin['attitude_scope'],
        },
        'coverage': coverage_record_dict,
        'attitude_scope': sphere_origin['attitude_scope'],
        'joint_state_scope': coverage_record.joint_state_scope,
        'limitations': list(limitations),
        'measurement': measurement_record,
    }
    if include_previous_rule_comparison:
        record['previous_rule_comparison'] = compare_with_previous_rule(
            half, offset)
    validate_body_envelope_record(record)
    return record
