"""Clearance geometry contract for supervisor decision records.

Implements the field contract of
``docs/superpowers/plans/2026-11-02-clearance-boundary.md`` section 2 with pure
standard-library code and no simulator dependency.

The contract keeps four geometric quantities strictly separate; one field only
ever carries one meaning:

``center_distance_m``
    distance between the robot center now and the observed obstacle center.
``envelope_gap_sphere_m``
    ``center_distance_m`` minus the two conservative spherical envelopes.
``path_clearance_m``
    the production supervisor quantity: minimum point-to-segment distance from
    the predicted obstacle centers to ``[robot_center_now -> waypoint_center]``.
``path_clearance_gap_sphere_m``
    ``path_clearance_m`` minus the two conservative spherical envelopes.

Envelope radius rule: the robot AABB uses ``box_conservative_sphere_radius`` of
the half extents, i.e. the half diagonal ``sqrt(sum(h_i ** 2))``.  A sphere
around the box center with that radius contains the box for any rigid rotation
about the center (the 8 vertices keep their distance from the center under
rotation).  A max-half-extent radius is *not* rotation-conservative for the
robot AABB: the box corners lie outside such a sphere.  The obstacle case
cuboid keeps the frozen ``sphere_over_case_cuboid`` rule
``max(size) / 2`` (upright case cuboid, rotations about the vertical axis; the
0.4 x 0.4 x 0.6 m case gives 0.3 m), which is the envelope the previous dynamic
reports used and is not a rotation-conservative bound for arbitrary 3D
rotations.  The AABB itself is a spawn-pose bound on the asset; a sphere/AABB
bound is not a triangle-mesh sweep proof.
"""
import math

CLEARANCE_SCHEMA_VERSION = 'boom_birds.clearance.v1'
CLEARANCE_ALGORITHM_ID = 'supervisor_predicted_path_clearance'
CLEARANCE_ALGORITHM_VERSION = '1.0.0'
CLEARANCE_UNITS = 'm'
CLEARANCE_FRAME = 'world_ENU_Z_up'
CLEARANCE_TIME_BASE = 'simulation_time_s'
PREDICTION_HORIZON_S = 1.0
PREDICTION_STEP_S = 0.1

# Measured USD AABB half extents of ``/World/envs/env_0/Robot`` recorded by the
# 2026-11-02 latency formal run (``body_envelope`` in the run manifest).  Kept
# as a documented default so a supervisor without explicit envelopes still
# emits a complete record; callers (the evaluation runner) should pass the
# envelope measured in their own run.
DEFAULT_ROBOT_AABB_HALF_EXTENTS_M = (0.05454223374277353,
                                     0.03820826672017574,
                                     0.013588040310423821)
DEFAULT_ROBOT_AABB_PRIM = '/World/envs/env_0/Robot'
DEFAULT_ROBOT_AABB_SOURCE = 'measured_usd_aabb_at_runtime'
# ``case_obstacle_size`` from the dynamic obstacle cases (0.4 x 0.4 x 0.6 m).
DEFAULT_OBSTACLE_SIZE_M = (0.4, 0.4, 0.6)
DEFAULT_OBSTACLE_ENVELOPE_SOURCE = 'case_obstacle_size'

ROBOT_ENVELOPE_KIND = 'sphere_over_spawn_aabb_half_diagonal'
OBSTACLE_ENVELOPE_KIND = 'sphere_over_case_cuboid'
ROBOT_ENVELOPE_ATTITUDE_SCOPE = 'any_rigid_rotation_about_center'
ROBOT_ENVELOPE_LIMITATION = 'AABB approximation; not a triangle-mesh sweep'
ALGORITHM_DEFINITION = ('min point-to-segment distance from predicted obstacle '
                        'centers to [robot_center_now -> '
                        'current_waypoint_center]')
PATH_CLEARANCE_NOTE = 'path clearance is not center distance or surface gap'
ENVELOPE_NOTE = ('robot sphere is the AABB half diagonal (conservative for any '
                 'rigid rotation about the center); obstacle sphere is '
                 'max(case size) / 2 (upright case cuboid assumption); neither '
                 'is a triangle-mesh sweep')


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _is_vector3(value):
    try:
        return (value is not None and len(value) == 3
                and all(_is_number(component) for component in value))
    except TypeError:
        return False


def _vector3(value):
    return [float(component) for component in value]


def box_conservative_sphere_radius(half_extents_m):
    """Conservative sphere radius around a box center: the half diagonal.

    ``sqrt(sum(h_i ** 2))`` contains the box for any rigid rotation about the
    center, unlike ``max(h_i)``.
    """
    values = [float(value) for value in half_extents_m]
    if len(values) != 3:
        raise ValueError('half_extents_m must hold three values')
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError('half_extents_m must be finite and non-negative')
    return math.sqrt(sum(value * value for value in values))


def point_to_segment_distance(point, start, end):
    """Distance from ``point`` to the clamped projection on ``[start, end]``."""
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(value * value for value in segment)
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = sum((point[index] - start[index]) * segment[index]
            for index in range(3)) / length_sq
    t = min(1.0, max(0.0, t))
    projection = [start[index] + segment[index] * t for index in range(3)]
    return math.dist(point, projection)


def predict_obstacle_positions(center_world_m, velocity_world_mps,
                               horizon_s=PREDICTION_HORIZON_S,
                               step_s=PREDICTION_STEP_S):
    """Constant-velocity obstacle center prediction on the supervisor grid.

    Mirrors the historical supervisor ``_risk`` loop exactly: ``steps`` is
    ``max(1, ceil(horizon / step))`` and sample ``index`` is taken at
    ``index * step`` seconds (so the default 1.0 s / 0.1 s grid has 11 points).
    """
    if not _is_vector3(center_world_m):
        raise ValueError('center_world_m must be a finite 3-vector')
    if not _is_vector3(velocity_world_mps):
        raise ValueError('velocity_world_mps must be a finite 3-vector')
    horizon = float(horizon_s)
    step = float(step_s)
    if not math.isfinite(horizon) or horizon < 0.0:
        raise ValueError('horizon_s must be finite and non-negative')
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError('step_s must be finite and positive')
    steps = max(1, int(math.ceil(horizon / step)))
    return [[float(center_world_m[axis])
             + float(velocity_world_mps[axis]) * (index * step)
             for axis in range(3)] for index in range(steps + 1)]


def predicted_path_clearance(robot_position_world_m,
                             target_waypoint_world_m,
                             obstacle_center_world_m,
                             obstacle_velocity_world_mps,
                             horizon_s=PREDICTION_HORIZON_S,
                             step_s=PREDICTION_STEP_S):
    """Predicted obstacle-center path clearance against the current segment.

    Returns the production value ``path_clearance_m`` plus the prediction
    centers, per-point distances and the first minimum index.
    """
    if not _is_vector3(robot_position_world_m):
        raise ValueError('robot_position_world_m must be a finite 3-vector')
    if not _is_vector3(target_waypoint_world_m):
        raise ValueError('target_waypoint_world_m must be a finite 3-vector')
    centers = predict_obstacle_positions(obstacle_center_world_m,
                                         obstacle_velocity_world_mps,
                                         horizon_s, step_s)
    distances = [point_to_segment_distance(point, robot_position_world_m,
                                           target_waypoint_world_m)
                 for point in centers]
    minimum = min(distances)
    return {
        'prediction_horizon_s': float(horizon_s),
        'prediction_step_s': float(step_s),
        'obstacle_predicted_centers_world_m': centers,
        'point_distances_m': distances,
        'min_index': distances.index(minimum),
        'path_clearance_m': minimum,
    }


def build_robot_envelope(half_extents_m=None, measured_prim=None, source=None):
    """Robot envelope record: conservative sphere over the spawn-pose AABB."""
    half_extents = (DEFAULT_ROBOT_AABB_HALF_EXTENTS_M if half_extents_m is None
                    else half_extents_m)
    return {
        'kind': ROBOT_ENVELOPE_KIND,
        'radius_m': box_conservative_sphere_radius(half_extents),
        'aabb_half_extents_m': _vector3(half_extents),
        'measured_prim': (DEFAULT_ROBOT_AABB_PRIM if measured_prim is None
                          else measured_prim),
        'source': DEFAULT_ROBOT_AABB_SOURCE if source is None else source,
        'attitude_scope': ROBOT_ENVELOPE_ATTITUDE_SCOPE,
        'limitation': ROBOT_ENVELOPE_LIMITATION,
    }


def build_obstacle_envelope(size_m=None, source=None):
    """Obstacle envelope record: frozen ``max(size) / 2`` case-cuboid sphere."""
    size = DEFAULT_OBSTACLE_SIZE_M if size_m is None else size_m
    values = [float(value) for value in size]
    if len(values) != 3 or any(not math.isfinite(value) or value <= 0.0
                               for value in values):
        raise ValueError('obstacle size_m must hold three positive values')
    return {
        'kind': OBSTACLE_ENVELOPE_KIND,
        'radius_m': max(values) / 2.0,
        'size_m': values,
        'source': (DEFAULT_OBSTACLE_ENVELOPE_SOURCE if source is None
                   else source),
    }


def _resolve_robot_envelope(payload):
    if payload is None:
        return build_robot_envelope()
    half_extents = payload.get('aabb_half_extents_m',
                               payload.get('half_extents_m'))
    return build_robot_envelope(
        half_extents_m=half_extents,
        measured_prim=payload.get('measured_prim'),
        source=payload.get('source'))


def _resolve_obstacle_envelope(payload):
    if payload is None:
        return build_obstacle_envelope()
    return build_obstacle_envelope(size_m=payload.get('size_m'),
                                   source=payload.get('source'))


def build_clearance_record(robot_center_world_m, target_waypoint_world_m,
                           observation, *, robot_velocity_world_mps=None,
                           waypoint_index=None, robot_envelope=None,
                           obstacle_envelope=None,
                           horizon_s=PREDICTION_HORIZON_S,
                           step_s=PREDICTION_STEP_S,
                           observation_valid=True,
                           validity_reasons=None):
    """Build the full clearance record for one supervisor decision.

    ``observation_valid`` lets the caller (the supervisor) mark a stale
    observation invalid even though the observation dictionary itself is still
    flagged valid; ``validity_reasons`` carries those caller-side reasons.
    """
    if not _is_vector3(robot_center_world_m):
        raise ValueError('robot_center_world_m must be a finite 3-vector')
    robot_center = _vector3(robot_center_world_m)
    observation = observation or {}
    observation_flag = bool(observation.get('valid', False))
    observation_reason = observation.get('reason')
    position = observation.get('position_world_m')
    velocity = observation.get('velocity_world_mps')
    target_valid = _is_vector3(target_waypoint_world_m)
    position_valid = _is_vector3(position)
    velocity_valid = _is_vector3(velocity)
    robot_envelope_record = _resolve_robot_envelope(robot_envelope)
    obstacle_envelope_record = _resolve_obstacle_envelope(obstacle_envelope)

    reasons = []

    def _add_reason(reason):
        reason = str(reason)
        if reason and reason not in reasons:
            reasons.append(reason)

    for reason in (validity_reasons or ()):
        _add_reason(reason)
    if not target_valid:
        _add_reason('TARGET_INVALID')
    if not observation_flag:
        if observation_reason in (None, '', 'ACCEPT'):
            _add_reason('OBSERVATION_INVALID')
        else:
            _add_reason(observation_reason)
    elif not position_valid:
        _add_reason('OBSERVATION_POSITION_INVALID')
    elif not velocity_valid:
        _add_reason('OBSERVATION_VELOCITY_INVALID')
    if not bool(observation_valid) and not reasons:
        _add_reason('OBSERVATION_INVALID')
    valid = (bool(observation_valid) and observation_flag
             and position_valid and velocity_valid and target_valid)

    age_point = observation.get('age_point_s')
    age_bound = observation.get('age_s')
    record = {
        'schema_version': CLEARANCE_SCHEMA_VERSION,
        'algorithm': {
            'id': CLEARANCE_ALGORITHM_ID,
            'version': CLEARANCE_ALGORITHM_VERSION,
            'units': CLEARANCE_UNITS,
            'frame': CLEARANCE_FRAME,
            'time_base': CLEARANCE_TIME_BASE,
            'prediction_horizon_s': float(horizon_s),
            'prediction_step_s': float(step_s),
            'definition': ALGORITHM_DEFINITION,
        },
        'inputs': {
            'robot_center_world_m': robot_center,
            'robot_velocity_world_mps': (_vector3(robot_velocity_world_mps)
                                         if _is_vector3(
                                             robot_velocity_world_mps)
                                         else None),
            'target_waypoint_world_m': (_vector3(target_waypoint_world_m)
                                        if target_valid else None),
            'waypoint_index': waypoint_index,
            'obstacle_observed_center_world_m': (_vector3(position)
                                                 if position_valid else None),
            'obstacle_observed_velocity_world_mps': (
                _vector3(velocity) if velocity_valid else None),
            'observation_age_point_s': (_finite_or_none(age_point)),
            'observation_age_bound_s': (_finite_or_none(age_bound)),
            'observation_valid': observation_flag,
            'observation_reason': observation_reason,
        },
        'prediction': {
            'obstacle_predicted_centers_world_m': [],
            'point_distances_m': [],
            'min_index': None,
        },
        'metrics': {
            'center_distance_m': None,
            'envelope_gap_sphere_m': None,
            'path_clearance_m': None,
            'path_clearance_gap_sphere_m': None,
        },
        'envelopes': {
            'robot': robot_envelope_record,
            'obstacle': obstacle_envelope_record,
        },
        'validity': {'valid': valid, 'reasons': reasons},
        'applicability': {
            'status': 'SUPPORTED' if valid else 'UNSUPPORTED',
            'reasons': [] if valid else list(reasons),
            'notes': [
                PATH_CLEARANCE_NOTE,
                ENVELOPE_NOTE,
                ('prediction covers {horizon:.3f} s at {step:.3f} s steps from '
                 'the observation sample; not a complete stop-time horizon'
                 ).format(horizon=float(horizon_s), step=float(step_s)),
            ],
        },
    }
    if valid:
        result = predicted_path_clearance(
            robot_center, target_waypoint_world_m,
            _vector3(position), _vector3(velocity), horizon_s, step_s)
        robot_radius = robot_envelope_record['radius_m']
        obstacle_radius = obstacle_envelope_record['radius_m']
        center_distance = math.dist(robot_center, _vector3(position))
        record['prediction'] = {
            'obstacle_predicted_centers_world_m':
                result['obstacle_predicted_centers_world_m'],
            'point_distances_m': result['point_distances_m'],
            'min_index': result['min_index'],
        }
        record['metrics'] = {
            'center_distance_m': center_distance,
            'envelope_gap_sphere_m':
                center_distance - robot_radius - obstacle_radius,
            'path_clearance_m': result['path_clearance_m'],
            'path_clearance_gap_sphere_m':
                result['path_clearance_m'] - robot_radius - obstacle_radius,
        }
    return record


def _finite_or_none(value):
    return float(value) if _is_number(value) else None
