"""Stop-requirement boundary model built on measured brake data.

Implements ``docs/superpowers/plans/2026-11-02-clearance-boundary.md`` section 3
with the standard library only, using the field contract agreed with the
verification/runner work packages.

The brake model is a piecewise-linear envelope of the 36 measured braking
episodes in ``docs/reports/map_eval/brake/verify_brake_final.json`` (frozen into
``configs/scenarios/brake_model_v1.json`` together with the source SHA-256).
Inside ``supported_speed_range_mps`` the brake distance and stop time are
interpolated linearly in speed between the per-tier worst-case measured points.
Outside that range no physical extrapolation is allowed: ``brake_distance_m``,
``required_clearance_m`` and ``margin_to_threshold_m`` are ``null`` and the
status is ``UNSUPPORTED`` (``ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT`` or
``ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT``).

Two bases are kept strictly separate to avoid double counting the transport
delay:

``actuation``
    the measured brake distance starts at actuation, so
    ``robot_speed * action_delay`` is added once as ``transport_reaction_m``.
``trigger``
    an analysis-only measured trigger-to-stop distance already contains the
    transport delay, so ``transport_reaction_m`` is ``0.0``.

The threshold applies to the supervisor's predicted **path clearance**, never
to robot-obstacle center distance or surface gap.  Invalid observations must be
reported by the caller; the requirement is then ``UNSUPPORTED`` with
``OBSERVATION_AGE_UNKNOWN``.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

STOP_REQUIREMENT_SCHEMA_VERSION = 'boom_birds.stop_requirement.v1'
BRAKE_MODEL_SCHEMA_VERSION = 'boom_birds.brake_model.v1'
DEFAULT_PROPOSED_MARGIN_M = 0.2
DEFAULT_PREDICTION_HORIZON_S = 1.0
BASIS_ACTUATION = 'actuation'
BASIS_TRIGGER = 'trigger'
_BASIS_ALIASES = {
    'actuation': BASIS_ACTUATION,
    'actuation_basis': BASIS_ACTUATION,
    'trigger': BASIS_TRIGGER,
    'trigger_basis': BASIS_TRIGGER,
}
STATUS_SUPPORTED = 'SUPPORTED'
STATUS_UNSUPPORTED = 'UNSUPPORTED'

# Blocking reasons (any of these makes the status UNSUPPORTED).
ROBOT_SPEED_ABOVE_REASON = 'ROBOT_SPEED_ABOVE_BRAKE_MODEL_SUPPORT'
ROBOT_SPEED_BELOW_REASON = 'ROBOT_SPEED_BELOW_BRAKE_MODEL_SUPPORT'
OBSERVATION_AGE_UNKNOWN_REASON = 'OBSERVATION_AGE_UNKNOWN'
ACTION_TTL_EXPIRED_REASON = 'ACTION_TTL_EXPIRED_BEFORE_ARRIVAL'
# Non-blocking markers.
CLOSING_SPEED_NOT_MODELLED_REASON = 'CLOSING_SPEED_NOT_MODELLED'
PREDICTION_HORIZON_SHORT_REASON = 'PREDICTION_HORIZON_SHORTER_THAN_STOP_TIME'

DEFAULT_BRAKE_MODEL_PATH = (Path(__file__).resolve().parents[3] / 'configs'
                            / 'scenarios' / 'brake_model_v1.json')

_TERM_KEYS = ('brake_distance_m', 'transport_reaction_m',
              'observation_age_motion_m', 'envelope_sum_m')
_INPUT_KEYS = ('robot_speed_mps', 'closing_speed_mps',
               'observation_age_bound_s', 'action_delay_s',
               'action_ttl_remaining_s', 'robot_radius_m', 'obstacle_radius_m',
               'stop_threshold_m', 'proposed_margin_m')


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _require_number(name, value, minimum=None):
    if not _is_number(value):
        raise ValueError(name + ' must be a finite number')
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(name + ' must be >= ' + str(minimum))
    return number


@dataclass(frozen=True)
class BrakeModelPoint:
    robot_speed_mps: float
    brake_distance_m: float
    stop_time_s: float


@dataclass(frozen=True)
class BrakeModel:
    schema_version: str
    model_id: str
    source_path: str
    source_sha256: str
    measured_episode_count: int
    support_min_speed_mps: float
    support_max_speed_mps: float
    min_measured_distance_m: float
    points: tuple

    @classmethod
    def from_payload(cls, payload):
        if payload.get('schema_version') != BRAKE_MODEL_SCHEMA_VERSION:
            raise ValueError('unexpected brake model schema_version')
        if payload.get('interpolation') != 'piecewise_linear_in_speed':
            raise ValueError('brake model interpolation must be '
                             'piecewise_linear_in_speed')
        if payload.get('extrapolation') != 'forbidden':
            raise ValueError('brake model extrapolation must be forbidden')
        points = []
        for item in payload['points']:
            points.append(BrakeModelPoint(
                robot_speed_mps=float(item['speed_mps']),
                brake_distance_m=float(item['brake_distance_m']),
                stop_time_s=float(item['stop_time_s'])))
        if len(points) < 3:
            raise ValueError('brake model needs at least three speed points')
        for left, right in zip(points, points[1:]):
            if not left.robot_speed_mps < right.robot_speed_mps:
                raise ValueError('brake model speeds must be strictly increasing')
        for point in points:
            if not math.isfinite(point.brake_distance_m) \
                    or point.brake_distance_m < 0.0:
                raise ValueError('brake distances must be finite and >= 0')
            if not math.isfinite(point.stop_time_s) or point.stop_time_s <= 0.0:
                raise ValueError('stop times must be finite and > 0')
        support = payload['supported_speed_range_mps']
        if len(support) != 2:
            raise ValueError('supported_speed_range_mps must hold two values')
        support_min = float(support[0])
        support_max = float(support[1])
        if not support_min < support_max:
            raise ValueError('supported speed range must be increasing')
        source = payload['source']
        return cls(
            schema_version=payload['schema_version'],
            model_id=payload['model_id'],
            source_path=source['path'],
            source_sha256=source['sha256'],
            measured_episode_count=int(source.get('measured_episode_count',
                                                  len(points))),
            support_min_speed_mps=support_min,
            support_max_speed_mps=support_max,
            min_measured_distance_m=float(
                payload.get('min_measured_distance_m',
                            min(point.brake_distance_m for point in points))),
            points=tuple(points))

    @classmethod
    def load(cls, path=None):
        model_path = Path(path) if path is not None else DEFAULT_BRAKE_MODEL_PATH
        payload = json.loads(model_path.read_text(encoding='utf-8'))
        return cls.from_payload(payload)

    def _interpolate(self, speed_mps, attribute):
        points = self.points
        first = points[0]
        last = points[-1]
        if speed_mps <= first.robot_speed_mps:
            return getattr(first, attribute)
        if speed_mps >= last.robot_speed_mps:
            return getattr(last, attribute)
        for left, right in zip(points, points[1:]):
            if left.robot_speed_mps <= speed_mps <= right.robot_speed_mps:
                span = right.robot_speed_mps - left.robot_speed_mps
                ratio = (speed_mps - left.robot_speed_mps) / span
                left_value = getattr(left, attribute)
                right_value = getattr(right, attribute)
                return left_value + ratio * (right_value - left_value)
        raise ValueError('speed is not bracketed by the brake model points')

    def _speed_reason(self, speed_mps):
        if not _is_number(speed_mps) or float(speed_mps) < 0.0:
            return 'ROBOT_SPEED_INVALID'
        speed = float(speed_mps)
        # 1e-9 tolerance matches the independent verifier recomputation so a
        # speed within rounding distance of a support boundary is interpolated,
        # not silently rejected.
        if speed > self.support_max_speed_mps + 1e-9:
            return ROBOT_SPEED_ABOVE_REASON
        if speed < self.support_min_speed_mps - 1e-9:
            return ROBOT_SPEED_BELOW_REASON
        return None

    def brake_distance(self, speed_mps):
        """Return ``(distance_m, reason)``; ``None`` outside the support range.

        No value is extrapolated above or below the measured support interval.
        """
        reason = self._speed_reason(speed_mps)
        if reason is not None:
            return None, reason
        return self._interpolate(float(speed_mps), 'brake_distance_m'), None

    def stop_time(self, speed_mps):
        """Return ``(stop_time_s, reason)``; used only for horizon diagnostics."""
        reason = self._speed_reason(speed_mps)
        if reason is not None:
            return None, reason
        return self._interpolate(float(speed_mps), 'stop_time_s'), None

    def conservative_below_min_distance_m(self):
        """Minimum measured distance, kept only as an analysis reference.

        Not used to build stop requirements: below the support interval the
        requirement is UNSUPPORTED instead of substituting this value, so no
        out-of-model distance can silently re-enter the production record.
        """
        return self.min_measured_distance_m


def load_brake_model(path=None):
    """Load the frozen brake model (default: repository config path)."""
    return BrakeModel.load(path)


def evaluate_stop_requirement(*, robot_speed_mps, closing_speed_mps,
                              observation_age_bound_s, action_delay_s,
                              action_ttl_remaining_s, robot_radius_m,
                              obstacle_radius_m, stop_threshold_m,
                              proposed_margin_m=DEFAULT_PROPOSED_MARGIN_M,
                              brake_model=None, observation_valid=True,
                              basis=BASIS_ACTUATION,
                              measured_stop_distance_m=None,
                              prediction_horizon_s=DEFAULT_PREDICTION_HORIZON_S):
    """Evaluate the stop requirement for one step (see module docstring).

    ``observation_age_bound_s=None`` (or ``observation_valid=False``) means the
    observation age is unknown; the returned record then echoes ``None`` for the
    age input and is ``UNSUPPORTED`` with ``OBSERVATION_AGE_UNKNOWN``.
    ``closing_speed_mps=None`` marks ``CLOSING_SPEED_NOT_MODELLED`` (the
    age-motion term is then unknown and the requirement value stays ``null``,
    without blocking).  ``action_ttl_remaining_s=None`` means the remaining TTL
    is not known in this context; no TTL reason is emitted because expiry cannot
    be proven.  Any blocking reason makes the status ``UNSUPPORTED`` and leaves
    ``required_clearance_m``/``margin_to_threshold_m`` ``null`` (no certified
    requirement value outside the supported model).
    """
    model = brake_model if brake_model is not None else load_brake_model()
    speed = _require_number('robot_speed_mps', robot_speed_mps, minimum=0.0)
    closing = None
    if closing_speed_mps is not None:
        closing = _require_number('closing_speed_mps', closing_speed_mps)
    delay = _require_number('action_delay_s', action_delay_s, minimum=0.0)
    robot_radius = _require_number('robot_radius_m', robot_radius_m,
                                   minimum=0.0)
    obstacle_radius = _require_number('obstacle_radius_m', obstacle_radius_m,
                                      minimum=0.0)
    threshold = _require_number('stop_threshold_m', stop_threshold_m)
    proposed_margin = _require_number('proposed_margin_m', proposed_margin_m,
                                      minimum=0.0)
    basis_name = _BASIS_ALIASES.get(basis)
    if basis_name is None:
        raise ValueError("basis must be 'actuation' or 'trigger'")
    age = None
    if bool(observation_valid) and observation_age_bound_s is not None:
        age = _require_number('observation_age_bound_s', observation_age_bound_s,
                              minimum=0.0)
    ttl = action_ttl_remaining_s
    if ttl is not None:
        ttl = _require_number('action_ttl_remaining_s', ttl)
    horizon = _require_number('prediction_horizon_s', prediction_horizon_s,
                              minimum=0.0)

    reasons = []
    blocking = []

    def _mark(reason, is_blocking):
        if reason not in reasons:
            reasons.append(reason)
        if is_blocking and reason not in blocking:
            blocking.append(reason)

    if age is None:
        _mark(OBSERVATION_AGE_UNKNOWN_REASON, True)
    if ttl is not None and ttl + 1e-12 < delay:
        _mark(ACTION_TTL_EXPIRED_REASON, True)

    brake_distance_m = None
    transport_reaction_m = None
    if basis_name == BASIS_ACTUATION:
        value, reason = model.brake_distance(speed)
        if reason == ROBOT_SPEED_ABOVE_REASON:
            _mark(ROBOT_SPEED_ABOVE_REASON, True)
        elif reason == ROBOT_SPEED_BELOW_REASON:
            _mark(ROBOT_SPEED_BELOW_REASON, True)
        brake_distance_m = value
        transport_reaction_m = speed * delay
    else:  # trigger basis: measured trigger-to-stop distance
        if measured_stop_distance_m is None:
            raise ValueError('measured_stop_distance_m is required for the '
                             'trigger basis')
        brake_distance_m = _require_number(
            'measured_stop_distance_m', measured_stop_distance_m, minimum=0.0)
        transport_reaction_m = 0.0

    if closing is None:
        # The brake model only covers robot speed; if the closing speed is not
        # available the requirement cannot include an age-motion term, which is
        # marked (non-blocking) instead of blocking the whole record.
        _mark(CLOSING_SPEED_NOT_MODELLED_REASON, False)
    stop_time_s, _stop_reason = model.stop_time(speed)
    if stop_time_s is not None and stop_time_s > horizon:
        _mark(PREDICTION_HORIZON_SHORT_REASON, False)

    observation_age_motion_m = None if age is None or closing is None \
        else closing * age
    envelope_sum_m = robot_radius + obstacle_radius
    terms = {
        'brake_distance_m': brake_distance_m,
        'transport_reaction_m': transport_reaction_m,
        'observation_age_motion_m': observation_age_motion_m,
        'envelope_sum_m': envelope_sum_m,
    }
    required_clearance_m = None
    margin_to_threshold_m = None
    age_zero = age is not None and age == 0.0
    if (not blocking and brake_distance_m is not None
            and transport_reaction_m is not None
            and envelope_sum_m is not None
            and (observation_age_motion_m is not None or age_zero)):
        # A UNSUPPORTED record carries no certified requirement value.  An
        # unknown closing speed still allows the requirement when the age is
        # zero (the age-motion term contributes exactly zero).
        observation_motion_term = observation_age_motion_m
        if observation_motion_term is None:
            observation_motion_term = 0.0
        required_clearance_m = (brake_distance_m + transport_reaction_m
                                + observation_motion_term + envelope_sum_m)
        margin_to_threshold_m = (threshold - required_clearance_m
                                 - proposed_margin)
    inputs = {
        'robot_speed_mps': speed,
        'closing_speed_mps': closing,
        'observation_age_bound_s': age,
        'action_delay_s': delay,
        'action_ttl_remaining_s': ttl,
        'robot_radius_m': robot_radius,
        'obstacle_radius_m': obstacle_radius,
        'stop_threshold_m': threshold,
        'proposed_margin_m': proposed_margin,
    }
    return {
        'schema_version': STOP_REQUIREMENT_SCHEMA_VERSION,
        'model_id': model.model_id,
        'basis': basis_name,
        'inputs': inputs,
        'terms': terms,
        'required_clearance_m': required_clearance_m,
        'margin_to_threshold_m': margin_to_threshold_m,
        'status': STATUS_UNSUPPORTED if blocking else STATUS_SUPPORTED,
        'status_reasons': reasons,
    }
