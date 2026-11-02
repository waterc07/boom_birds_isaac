"""Layered contact-evidence contract for evaluation step records.

Implements ``boom_birds.contact_evidence.v2`` with pure standard-library code
and no simulator dependency.  The contract exists because a PhysX contact
signal can be unavailable in several independent ways, and a zero reading is
only meaningful once the sensing channel is known to be valid:

``PHYSX_CONTACT_EVENT``
    A PhysX contact event was observed (``event``) and the channel that
    produced it is known (``source`` / ``force_basis``).
``PHYSX_CONTACT_FORCE``
    A force magnitude in newtons was measured.  When the per-prim filtered
    force matrix is available the magnitude is the maximum per-prim world
    vector norm; when only unfiltered ``net_forces_w`` is available the
    magnitude comes from the net force and ``per_prim_n`` stays ``None``.
``PHYSX_CONTACT_IMPULSE``
    A PhysX impulse in ``N*s`` was measured.  It is never used as a force.
``GEOMETRY_OVERLAP``
    A spherical overlap inference.  It is always ``sphere_overlap_only`` and
    is never promoted to a PhysX event or force.

A fifth ``attribution`` layer states whether the contacting prim/object is
known: ``ATTRIBUTED`` (per-prim filtered force or named filter contacts),
``UNATTRIBUTED`` (event/force measured through a channel that cannot name the
prim, e.g. unfiltered net force) or ``UNKNOWN``.  Prim paths are never
invented for an unattributed step.

Invalid vs valid-zero
    ``sensor.available=False`` (or ``event.available=False``) makes the step
    ``UNKNOWN``: a zero force is *not* evidence of no contact, and an
    unavailable force is stored as ``None``, never ``0``.  A working sensor
    that genuinely reads zero stores ``available=True``, ``event=False`` and a
    real ``magnitude_n == 0.0``; that step classifies as ``NO_CONTACT``.

Classification precedence (``classify_contact``)
    ``UNKNOWN`` > force measured > ``CONTACT_EVENT_ONLY`` > geometry overlap >
    ``NO_CONTACT``.  Force measurement requires ``magnitude_n >
    CONTACT_FORCE_THRESHOLD_N`` (strictly greater); the threshold is only a
    decision rule and never rewrites the raw magnitude.
"""
import math
from collections.abc import Mapping

CONTACT_EVIDENCE_SCHEMA_ID = 'boom_birds.contact_evidence.v2'

LAYER_PHYSX_CONTACT_EVENT = 'PHYSX_CONTACT_EVENT'
LAYER_PHYSX_CONTACT_FORCE = 'PHYSX_CONTACT_FORCE'
LAYER_PHYSX_CONTACT_IMPULSE = 'PHYSX_CONTACT_IMPULSE'
LAYER_GEOMETRY_OVERLAP = 'GEOMETRY_OVERLAP'
LAYER_UNKNOWN = 'UNKNOWN'

FORCE_UNIT = 'N'
IMPULSE_UNIT = 'N*s'
CONTACT_FORCE_THRESHOLD_N = 0.02

SAMPLING_SOURCE = 'policy_step_aggregated_physx_contact'
SAMPLING_AGGREGATION = 'max_over_window'
GEOMETRY_INFERENCE = 'sphere_overlap_only'

EVENT_SOURCE_FILTERED = 'physx_contact_sensor_filtered'
EVENT_SOURCE_UNFILTERED = 'physx_contact_sensor_unfiltered'
EVENT_SOURCE_NONE = 'none'
EVENT_SOURCES = frozenset({EVENT_SOURCE_FILTERED, EVENT_SOURCE_UNFILTERED,
                           EVENT_SOURCE_NONE})

FORCE_BASIS_FILTERED = 'filtered_force'
FORCE_BASIS_NET = 'net_force'
FORCE_BASIS_NONE = 'none'
FORCE_BASES = frozenset({FORCE_BASIS_FILTERED, FORCE_BASIS_NET,
                         FORCE_BASIS_NONE})

ATTRIBUTION_ATTRIBUTED = 'ATTRIBUTED'
ATTRIBUTION_UNATTRIBUTED = 'UNATTRIBUTED'
ATTRIBUTION_UNKNOWN = 'UNKNOWN'
ATTRIBUTION_STATUSES = frozenset({ATTRIBUTION_ATTRIBUTED,
                                  ATTRIBUTION_UNATTRIBUTED,
                                  ATTRIBUTION_UNKNOWN})

METHOD_FILTER = 'contact_sensor_filter'
METHOD_NET_FORCE_PROXIMITY = 'net_force_plus_proximity'
METHOD_NONE = 'none'
ATTRIBUTION_METHODS = frozenset({METHOD_FILTER, METHOD_NET_FORCE_PROXIMITY,
                                 METHOD_NONE})

CLASS_CONTACT_FORCE_MEASURED = 'CONTACT_FORCE_MEASURED'
CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED = 'CONTACT_FORCE_MEASURED_UNATTRIBUTED'
CLASS_CONTACT_EVENT_ONLY = 'CONTACT_EVENT_ONLY'
CLASS_GEOMETRY_OVERLAP_ONLY = 'GEOMETRY_OVERLAP_ONLY'
CLASS_NO_CONTACT = 'NO_CONTACT'
CLASS_UNKNOWN = 'UNKNOWN'

_CLASSIFICATION_ORDER = (
    CLASS_CONTACT_FORCE_MEASURED,
    CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED,
    CLASS_CONTACT_EVENT_ONLY,
    CLASS_GEOMETRY_OVERLAP_ONLY,
    CLASS_NO_CONTACT,
    CLASS_UNKNOWN,
)
CLASSIFICATIONS = frozenset(_CLASSIFICATION_ORDER)

_ATTRIBUTION_ORDER = (ATTRIBUTION_ATTRIBUTED, ATTRIBUTION_UNATTRIBUTED,
                      ATTRIBUTION_UNKNOWN)

REASON_SENSOR_UNAVAILABLE = 'SENSOR_UNAVAILABLE'
REASON_EVENT_UNAVAILABLE = 'EVENT_UNAVAILABLE'
_UNKNOWN_REASON_ORDER = (REASON_SENSOR_UNAVAILABLE, REASON_EVENT_UNAVAILABLE)


# ---------------------------------------------------------------------------
# small typed helpers
# ---------------------------------------------------------------------------

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


def _norm(vector):
    return math.sqrt(sum(component * component for component in vector))


def _is_nonneg_int(value):
    return (isinstance(value, int) and not isinstance(value, bool)
            and value >= 0)


def _is_prim_list(value):
    if not isinstance(value, list):
        return False
    if any(not isinstance(prim, str) or not prim for prim in value):
        return False
    return value == sorted(set(value))


def _is_vector_map(value):
    if not isinstance(value, Mapping) or not value:
        return False
    for prim, vector in value.items():
        if not isinstance(prim, str) or not prim:
            return False
        if not _is_vector3(vector):
            return False
    return True


def _is_none_or_nonneg_number(value):
    return value is None or (_is_number(value) and value >= 0)


def _require_bool(name, value):
    if not isinstance(value, bool):
        raise ValueError(name + ' must be a bool')
    return value


def _require_str(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(name + ' must be a nonempty string')
    return value


def _require_nonneg_int(name, value):
    if not _is_nonneg_int(value):
        raise ValueError(name + ' must be a nonnegative integer')
    return value


def _require_nonneg_number(name, value):
    if not (_is_number(value) and value >= 0):
        raise ValueError(name + ' must be a non-negative finite number')
    return float(value)


def _require_none_or_nonneg_number(name, value):
    if value is None:
        return None
    return _require_nonneg_number(name, value)


def _normalize_prim_list(value):
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError('prim_attributions must be a sequence of prim paths')
    prims = []
    for prim in value:
        if not isinstance(prim, str) or not prim:
            raise ValueError('prim_attributions entries must be nonempty '
                             'strings')
        prims.append(prim)
    return sorted(set(prims))


def _normalize_vector_map(value, name):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(name + ' must be a mapping of prim path to a finite '
                         '3-vector')
    normalized = {}
    for prim, vector in value.items():
        if not isinstance(prim, str) or not prim:
            raise ValueError(name + ' keys must be nonempty prim path '
                             'strings')
        if not _is_vector3(vector):
            raise ValueError(name + ' values must be finite 3-vectors')
        normalized[prim] = _vector3(vector)
    return normalized or None


def _net_force_magnitude(net_force_n):
    if net_force_n is None:
        return None
    if _is_vector3(net_force_n):
        return _norm(_vector3(net_force_n))
    if _is_number(net_force_n) and net_force_n >= 0:
        return float(net_force_n)
    raise ValueError('net_force_n must be a non-negative finite scalar or a '
                     'finite 3-vector')


# ---------------------------------------------------------------------------
# layer builders
# ---------------------------------------------------------------------------

def _build_force_layer(force_per_prim_n, net_force_n, force_window_s):
    per_prim = _normalize_vector_map(force_per_prim_n, 'force_per_prim_n')
    net_magnitude = _net_force_magnitude(net_force_n)
    if per_prim is not None and net_magnitude is not None:
        raise ValueError('force_per_prim_n and net_force_n are mutually '
                         'exclusive')
    window = _require_none_or_nonneg_number('force_window_s', force_window_s)
    if per_prim is not None:
        basis = FORCE_BASIS_FILTERED
        magnitude = max(_norm(vector) for vector in per_prim.values())
    elif net_magnitude is not None:
        basis = FORCE_BASIS_NET
        magnitude = net_magnitude
    else:
        basis = FORCE_BASIS_NONE
        magnitude = None
    return {
        'layer': LAYER_PHYSX_CONTACT_FORCE,
        'available': basis != FORCE_BASIS_NONE,
        'unit': FORCE_UNIT,
        'per_prim_n': per_prim,
        'magnitude_n': magnitude,
        'window_s': window,
        'basis': basis,
    }


def _build_impulse_layer(impulse_available, impulse_ns):
    _require_bool('impulse_available', impulse_available)
    if not impulse_available:
        if impulse_ns is not None:
            raise ValueError('impulse_ns must be None when impulse_available '
                             'is False')
        return {
            'layer': LAYER_PHYSX_CONTACT_IMPULSE,
            'available': False,
            'unit': IMPULSE_UNIT,
            'per_prim_ns': None,
            'magnitude_ns': None,
        }
    if impulse_ns is None:
        raise ValueError('impulse_available=True requires impulse_ns')
    if isinstance(impulse_ns, Mapping):
        per_prim = _normalize_vector_map(impulse_ns, 'impulse_ns')
        if per_prim is None:
            raise ValueError('impulse_ns mapping must not be empty')
        magnitude = max(_norm(vector) for vector in per_prim.values())
    elif _is_vector3(impulse_ns):
        per_prim = None
        magnitude = _norm(_vector3(impulse_ns))
    elif _is_number(impulse_ns) and impulse_ns >= 0:
        per_prim = None
        magnitude = float(impulse_ns)
    else:
        raise ValueError('impulse_ns must be a non-negative finite scalar, a '
                         'finite 3-vector or a prim->vector mapping')
    return {
        'layer': LAYER_PHYSX_CONTACT_IMPULSE,
        'available': True,
        'unit': IMPULSE_UNIT,
        'per_prim_ns': per_prim,
        'magnitude_ns': magnitude,
    }


def _build_geometry_layer(geometry):
    if geometry is None:
        return {
            'layer': LAYER_GEOMETRY_OVERLAP,
            'available': False,
            'sphere_overlap_m': None,
            'inference': GEOMETRY_INFERENCE,
        }
    if isinstance(geometry, Mapping):
        if 'sphere_overlap_m' not in geometry:
            raise ValueError('geometry mapping requires sphere_overlap_m')
        inference = geometry.get('inference', GEOMETRY_INFERENCE)
        if inference != GEOMETRY_INFERENCE:
            raise ValueError('geometry inference must be ' + GEOMETRY_INFERENCE)
        overlap = geometry['sphere_overlap_m']
    else:
        overlap = geometry
    if not _is_number(overlap):
        raise ValueError('sphere_overlap_m must be a finite number')
    return {
        'layer': LAYER_GEOMETRY_OVERLAP,
        'available': True,
        'sphere_overlap_m': float(overlap),
        'inference': GEOMETRY_INFERENCE,
    }


def _resolve_prim_attributions(prim_attributions, force_layer):
    """Attributed contacting prims: filtered per-prim force decides them.

    A per-prim force map carries the prim names the sensor itself attributed,
    so the contacting subset (``norm > threshold``) must match any explicit
    ``prim_attributions``.  When no force map is available the explicit list is
    authoritative (event-only attribution).  Nothing is ever invented.
    """
    provided = _normalize_prim_list(prim_attributions)
    per_prim = force_layer['per_prim_n']
    if per_prim is not None:
        derived = sorted(prim for prim, vector in per_prim.items()
                         if _norm(vector) > CONTACT_FORCE_THRESHOLD_N)
        if set(provided) != set(derived):
            raise ValueError('prim_attributions must equal the per-prim '
                             'contacts above the force threshold')
        return derived
    return provided


def _resolve_attribution_status(attribution_status, prims, force_layer,
                                event_available):
    has_filtered = force_layer['basis'] == FORCE_BASIS_FILTERED
    has_net = force_layer['basis'] == FORCE_BASIS_NET
    if attribution_status is not None:
        if attribution_status not in ATTRIBUTION_STATUSES:
            raise ValueError('unsupported attribution status: '
                             + str(attribution_status))
        if has_filtered and attribution_status != ATTRIBUTION_ATTRIBUTED:
            raise ValueError('per-prim filtered force requires ATTRIBUTED '
                             'status')
        if has_net and attribution_status != ATTRIBUTION_UNATTRIBUTED:
            raise ValueError('net force requires UNATTRIBUTED status')
        if (attribution_status == ATTRIBUTION_ATTRIBUTED and not prims
                and not has_filtered):
            raise ValueError('ATTRIBUTED status requires named prim '
                             'attributions')
        if attribution_status != ATTRIBUTION_ATTRIBUTED and prims:
            raise ValueError('prim attributions are only allowed with '
                             'ATTRIBUTED status')
        return attribution_status
    if has_filtered or prims:
        return ATTRIBUTION_ATTRIBUTED
    if has_net or event_available:
        return ATTRIBUTION_UNATTRIBUTED
    return ATTRIBUTION_UNKNOWN


def _resolve_attribution_method(attribution_method, status):
    if attribution_method is not None:
        if attribution_method not in ATTRIBUTION_METHODS:
            raise ValueError('unsupported attribution method: '
                             + str(attribution_method))
        if status == ATTRIBUTION_ATTRIBUTED and attribution_method != METHOD_FILTER:
            raise ValueError('ATTRIBUTED status requires the '
                             'contact_sensor_filter method')
        if status == ATTRIBUTION_UNATTRIBUTED and attribution_method not in (
                METHOD_NONE, METHOD_NET_FORCE_PROXIMITY):
            raise ValueError('UNATTRIBUTED status requires the none or '
                             'net_force_plus_proximity method')
        if status == ATTRIBUTION_UNKNOWN and attribution_method != METHOD_NONE:
            raise ValueError('UNKNOWN status requires the none method')
        return attribution_method
    if status == ATTRIBUTION_ATTRIBUTED:
        return METHOD_FILTER
    return METHOD_NONE


def _build_event_layer(event_available, event, force_layer, attribution,
                       prims):
    if not event_available:
        if event is not None:
            raise ValueError('event must be None when event_available is '
                             'False')
        return {
            'layer': LAYER_PHYSX_CONTACT_EVENT,
            'available': False,
            'event': None,
            'source': EVENT_SOURCE_NONE,
            'force_basis': FORCE_BASIS_NONE,
            'prim_attributions': [],
            'contact_count': 0,
        }
    if not isinstance(event, bool):
        raise ValueError('event must be a bool when event_available is True')
    force_basis = force_layer['basis']
    magnitude = force_layer['magnitude_n']
    # The unfiltered net force is itself the event channel when no per-prim
    # filter is available, so its event flag must be the threshold decision.
    # A filtered contact event may be true while its force stays below the
    # measurement threshold, but it may never contradict a threshold-reaching
    # force.
    if force_basis == FORCE_BASIS_NET:
        if event != (magnitude > CONTACT_FORCE_THRESHOLD_N):
            raise ValueError('event must equal net force > threshold when the '
                             'force basis is net_force')
    elif force_basis == FORCE_BASIS_FILTERED:
        if event is False and magnitude > CONTACT_FORCE_THRESHOLD_N:
            raise ValueError('event cannot be False when the filtered force '
                             'exceeds the contact threshold')
    if force_basis == FORCE_BASIS_FILTERED:
        source = EVENT_SOURCE_FILTERED
    elif force_basis == FORCE_BASIS_NET:
        source = EVENT_SOURCE_UNFILTERED
    elif attribution['status'] == ATTRIBUTION_ATTRIBUTED:
        source = EVENT_SOURCE_FILTERED
    else:
        source = EVENT_SOURCE_UNFILTERED
    event_prims = (list(prims) if attribution['status'] == ATTRIBUTION_ATTRIBUTED
                   else [])
    return {
        'layer': LAYER_PHYSX_CONTACT_EVENT,
        'available': True,
        'event': event,
        'source': source,
        'force_basis': force_basis,
        'prim_attributions': event_prims,
        'contact_count': len(event_prims),
    }


# ---------------------------------------------------------------------------
# public builders
# ---------------------------------------------------------------------------

def build_contact_record(*, step, time_s, sensor_available, sensor_status,
                         event_available, event, prim_attributions,
                         force_per_prim_n=None, force_window_s=None,
                         impulse_available=False, impulse_ns=None,
                         geometry=None, notes=None, net_force_n=None,
                         attribution_status=None, attribution_method=None,
                         attribution_notes=None):
    """Build a complete ``boom_birds.contact_evidence.v2`` step record.

    ``sensor_available`` describes the PhysX contact-force channel actually
    used for this step: the filtered per-link sensor *or* the unfiltered net
    force sensor.  ``sensor_status`` is a free-form diagnostic string such as
    ``available``, ``contact_filter_unsupported`` or
    ``filtered_unavailable_net_force_available``.

    ``force_per_prim_n`` (mapping ``prim -> world 3-vector``) is the filtered
    per-prim force matrix and implies ``ATTRIBUTED``; ``net_force_n`` (finite
    non-negative scalar magnitude or world 3-vector) is the unfiltered net
    force and implies ``UNATTRIBUTED``.  They are mutually exclusive, and the
    net force is never stored as a per-prim force.

    ``geometry`` accepts a bare sphere overlap in metres or a mapping with
    ``sphere_overlap_m``; it is recorded as inference only.
    """
    step = _require_nonneg_int('step', step)
    time_s = _require_nonneg_number('time_s', time_s)
    _require_bool('sensor_available', sensor_available)
    _require_str('sensor_status', sensor_status)
    _require_bool('event_available', event_available)
    _require_bool('impulse_available', impulse_available)
    if notes is not None and not isinstance(notes, str):
        raise ValueError('notes must be a string or None')
    if attribution_notes is not None and not isinstance(attribution_notes, str):
        raise ValueError('attribution_notes must be a string or None')

    force_layer = _build_force_layer(force_per_prim_n, net_force_n,
                                     force_window_s)
    impulse_layer = _build_impulse_layer(impulse_available, impulse_ns)
    geometry_layer = _build_geometry_layer(geometry)
    prims = _resolve_prim_attributions(prim_attributions, force_layer)
    status = _resolve_attribution_status(attribution_status, prims,
                                         force_layer, event_available)
    method = _resolve_attribution_method(attribution_method, status)
    attribution_layer = {
        'status': status,
        'prim_paths': list(prims) if status == ATTRIBUTION_ATTRIBUTED else [],
        'method': method,
        'notes': attribution_notes or '',
    }
    event_layer = _build_event_layer(event_available, event, force_layer,
                                     attribution_layer, prims)

    unknown_reasons = []
    if not sensor_available:
        unknown_reasons.append(REASON_SENSOR_UNAVAILABLE)
    if not event_available:
        unknown_reasons.append(REASON_EVENT_UNAVAILABLE)

    record = {
        'schema_version': CONTACT_EVIDENCE_SCHEMA_ID,
        'step': step,
        'time_s': time_s,
        'sensor': {
            'available': sensor_available,
            'status': sensor_status,
        },
        'sampling': {
            'window_s': force_layer['window_s'],
            'source': SAMPLING_SOURCE,
            'aggregation': SAMPLING_AGGREGATION,
        },
        'layers': {
            'event': event_layer,
            'force': force_layer,
            'impulse': impulse_layer,
            'geometry': geometry_layer,
            'attribution': attribution_layer,
        },
        'classification': CLASS_UNKNOWN,
        'validity': {'valid': False, 'reasons': []},
        'unknown_reasons': list(unknown_reasons),
        'notes': notes,
    }
    classification = classify_contact(record)
    record['classification'] = classification
    record['validity'] = {
        'valid': classification != CLASS_UNKNOWN,
        'reasons': list(unknown_reasons),
    }
    return record


def classify_contact(record):
    """Classify one contact record from its evidence layers.

    Recomputes from the layers rather than echoing a stored label, so
    ``validate_contact_record`` can detect a tampered ``classification``.
    """
    if not isinstance(record, Mapping):
        raise ValueError('contact record must be a mapping')
    sensor = record['sensor']
    layers = record['layers']
    event_layer = layers['event']
    force_layer = layers['force']
    geometry_layer = layers['geometry']
    if not sensor.get('available') or not event_layer.get('available'):
        return CLASS_UNKNOWN
    magnitude = force_layer.get('magnitude_n')
    if (force_layer.get('available')
            and _is_number(magnitude)
            and magnitude > CONTACT_FORCE_THRESHOLD_N):
        if layers['attribution'].get('status') == ATTRIBUTION_ATTRIBUTED:
            return CLASS_CONTACT_FORCE_MEASURED
        return CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED
    if event_layer.get('event') is True:
        return CLASS_CONTACT_EVENT_ONLY
    overlap = geometry_layer.get('sphere_overlap_m')
    if (geometry_layer.get('available') and _is_number(overlap)
            and overlap > 0.0):
        return CLASS_GEOMETRY_OVERLAP_ONLY
    return CLASS_NO_CONTACT


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _validate_event_layer(event_layer, force_layer, attribution_layer):
    if not isinstance(event_layer, Mapping):
        return ['EVENT_LAYER_INVALID']
    errors = []
    ok = True
    if event_layer.get('layer') != LAYER_PHYSX_CONTACT_EVENT:
        ok = False
    available = event_layer.get('available')
    if not isinstance(available, bool):
        ok = False
    event_value = event_layer.get('event')
    if available is True:
        if not isinstance(event_value, bool):
            ok = False
    elif available is False:
        if event_value is not None:
            ok = False
    else:
        ok = False
    source = event_layer.get('source')
    if source not in EVENT_SOURCES:
        ok = False
    force_basis = event_layer.get('force_basis')
    if force_basis not in FORCE_BASES:
        ok = False
    prims = event_layer.get('prim_attributions')
    if not _is_prim_list(prims):
        ok = False
    count = event_layer.get('contact_count')
    if not (_is_nonneg_int(count) and isinstance(prims, list)
            and count == len(prims)):
        ok = False
    declared_basis = (force_layer.get('basis')
                      if isinstance(force_layer, Mapping) else None)
    if available is True:
        if force_basis != declared_basis:
            errors.append('INCONSISTENT_EVENT')
            ok = False
        layer_magnitude = (force_layer.get('magnitude_n')
                          if isinstance(force_layer, Mapping) else None)
        if declared_basis == FORCE_BASIS_NET and _is_number(layer_magnitude):
            if event_value != (layer_magnitude > CONTACT_FORCE_THRESHOLD_N):
                errors.append('INCONSISTENT_EVENT')
                ok = False
        elif declared_basis == FORCE_BASIS_FILTERED \
                and _is_number(layer_magnitude):
            if event_value is False \
                    and layer_magnitude > CONTACT_FORCE_THRESHOLD_N:
                errors.append('INCONSISTENT_EVENT')
                ok = False
        if declared_basis == FORCE_BASIS_FILTERED:
            if source != EVENT_SOURCE_FILTERED:
                ok = False
        elif declared_basis == FORCE_BASIS_NET:
            if source != EVENT_SOURCE_UNFILTERED:
                ok = False
        elif declared_basis == FORCE_BASIS_NONE:
            status = (attribution_layer.get('status')
                      if isinstance(attribution_layer, Mapping) else None)
            expected = (EVENT_SOURCE_FILTERED
                        if status == ATTRIBUTION_ATTRIBUTED
                        else EVENT_SOURCE_UNFILTERED)
            if source != expected:
                ok = False
    elif available is False:
        if source != EVENT_SOURCE_NONE or force_basis != FORCE_BASIS_NONE:
            errors.append('INCONSISTENT_EVENT')
            ok = False
    if not ok:
        errors.append('EVENT_LAYER_INVALID')
    return errors


def _validate_force_layer(force_layer):
    if not isinstance(force_layer, Mapping):
        return ['FORCE_LAYER_INVALID']
    errors = []
    ok = True
    if force_layer.get('layer') != LAYER_PHYSX_CONTACT_FORCE:
        ok = False
    if force_layer.get('unit') != FORCE_UNIT:
        errors.append('FORCE_UNIT_INVALID')
        ok = False
    basis = force_layer.get('basis')
    if basis not in FORCE_BASES:
        ok = False
    available = force_layer.get('available')
    if not isinstance(available, bool):
        ok = False
    magnitude = force_layer.get('magnitude_n')
    per_prim = force_layer.get('per_prim_n')
    if available is True:
        if not _is_number(magnitude):
            errors.append('FORCE_NOT_FINITE')
            ok = False
        elif magnitude < 0:
            errors.append('FORCE_NEGATIVE')
            ok = False
        if basis == FORCE_BASIS_FILTERED:
            if not _is_vector_map(per_prim):
                ok = False
            else:
                expected = max(_norm(vector) for vector in per_prim.values())
                if not (isinstance(magnitude, (int, float))
                        and not isinstance(magnitude, bool)
                        and math.isclose(magnitude, expected, rel_tol=1e-9,
                                         abs_tol=1e-12)):
                    ok = False
        elif basis == FORCE_BASIS_NET:
            if per_prim is not None:
                ok = False
        else:
            ok = False
    elif available is False:
        if magnitude is not None or per_prim is not None:
            ok = False
        if basis != FORCE_BASIS_NONE:
            ok = False
    if not ok:
        errors.append('FORCE_LAYER_INVALID')
    return errors


def _validate_impulse_layer(impulse_layer):
    if not isinstance(impulse_layer, Mapping):
        return ['IMPULSE_LAYER_INVALID']
    errors = []
    ok = True
    if impulse_layer.get('layer') != LAYER_PHYSX_CONTACT_IMPULSE:
        ok = False
    if impulse_layer.get('unit') != IMPULSE_UNIT:
        errors.append('IMPULSE_UNIT_INVALID')
        ok = False
    available = impulse_layer.get('available')
    if not isinstance(available, bool):
        ok = False
    per_prim = impulse_layer.get('per_prim_ns')
    magnitude = impulse_layer.get('magnitude_ns')
    if available is True:
        if not _is_number(magnitude):
            errors.append('IMPULSE_LAYER_INVALID')
            ok = False
        elif magnitude < 0:
            errors.append('IMPULSE_NEGATIVE')
            ok = False
        if per_prim is not None:
            if not _is_vector_map(per_prim):
                ok = False
            else:
                expected = max(_norm(vector) for vector in per_prim.values())
                if not (isinstance(magnitude, (int, float))
                        and not isinstance(magnitude, bool)
                        and math.isclose(magnitude, expected, rel_tol=1e-9,
                                         abs_tol=1e-12)):
                    ok = False
    elif available is False:
        if per_prim is not None or magnitude is not None:
            ok = False
    if not ok:
        errors.append('IMPULSE_LAYER_INVALID')
    return errors


def _validate_geometry_layer(geometry_layer):
    if not isinstance(geometry_layer, Mapping):
        return ['GEOMETRY_LAYER_INVALID']
    ok = True
    if geometry_layer.get('layer') != LAYER_GEOMETRY_OVERLAP:
        ok = False
    if geometry_layer.get('inference') != GEOMETRY_INFERENCE:
        ok = False
    available = geometry_layer.get('available')
    if not isinstance(available, bool):
        ok = False
    overlap = geometry_layer.get('sphere_overlap_m')
    if available is True:
        if not _is_number(overlap):
            ok = False
    elif available is False:
        if overlap is not None:
            ok = False
    return [] if ok else ['GEOMETRY_LAYER_INVALID']


def _validate_attribution_layer(attribution_layer, event_layer, force_layer):
    if not isinstance(attribution_layer, Mapping):
        return ['ATTRIBUTION_INVALID']
    errors = []
    ok = True
    status = attribution_layer.get('status')
    if status not in ATTRIBUTION_STATUSES:
        ok = False
    method = attribution_layer.get('method')
    if method not in ATTRIBUTION_METHODS:
        ok = False
    prim_paths = attribution_layer.get('prim_paths')
    if not _is_prim_list(prim_paths):
        ok = False
    if not isinstance(attribution_layer.get('notes'), str):
        ok = False
    event_prims = (event_layer.get('prim_attributions')
                   if isinstance(event_layer, Mapping) else None)
    if status != ATTRIBUTION_ATTRIBUTED and isinstance(prim_paths, list) \
            and prim_paths:
        errors.append('FABRICATED_ATTRIBUTION')
        ok = False
    if status != ATTRIBUTION_ATTRIBUTED and isinstance(event_prims, list) \
            and event_prims:
        errors.append('FABRICATED_ATTRIBUTION')
        ok = False
    if status == ATTRIBUTION_ATTRIBUTED:
        if method != METHOD_FILTER:
            ok = False
        if isinstance(force_layer, Mapping) \
                and force_layer.get('basis') == FORCE_BASIS_NET:
            errors.append('FABRICATED_ATTRIBUTION')
            ok = False
        if isinstance(force_layer, Mapping) \
                and force_layer.get('basis') == FORCE_BASIS_FILTERED:
            per_prim = force_layer.get('per_prim_n')
            if _is_vector_map(per_prim) and _is_prim_list(prim_paths):
                expected = sorted(
                    prim for prim, vector in per_prim.items()
                    if _norm(vector) > CONTACT_FORCE_THRESHOLD_N)
                if prim_paths != expected:
                    ok = False
        if isinstance(event_layer, Mapping) \
                and event_layer.get('available') is True \
                and _is_prim_list(prim_paths):
            if event_prims != prim_paths:
                ok = False
    elif status in (ATTRIBUTION_UNATTRIBUTED, ATTRIBUTION_UNKNOWN):
        if method == METHOD_FILTER:
            ok = False
    if not ok:
        errors.append('ATTRIBUTION_INVALID')
    return errors


def validate_contact_record(record):
    """Validate one contact record and return a list of error codes.

    An empty list means the record is valid.  This function reports every
    structural, unit, enum, consistency and attribution-fabrication problem it
    can find rather than raising, so callers can log all defects at once.
    """
    if not isinstance(record, Mapping):
        return ['NOT_A_MAPPING']
    errors = []
    if record.get('schema_version') != CONTACT_EVIDENCE_SCHEMA_ID:
        errors.append('SCHEMA_VERSION_INVALID')
    if not _is_nonneg_int(record.get('step')):
        errors.append('STEP_INVALID')
    if not (_is_number(record.get('time_s'))
            and record.get('time_s') >= 0):
        errors.append('TIME_INVALID')
    if record.get('notes') is not None \
            and not isinstance(record.get('notes'), str):
        errors.append('NOTES_INVALID')

    sensor = record.get('sensor')
    sensor_available = None
    if isinstance(sensor, Mapping) \
            and isinstance(sensor.get('available'), bool) \
            and isinstance(sensor.get('status'), str) \
            and sensor.get('status'):
        sensor_available = sensor['available']
    else:
        errors.append('SENSOR_INVALID')

    sampling = record.get('sampling')
    if not (isinstance(sampling, Mapping)
            and sampling.get('source') == SAMPLING_SOURCE
            and sampling.get('aggregation') == SAMPLING_AGGREGATION):
        errors.append('SAMPLING_INVALID')
    elif not _is_none_or_nonneg_number(sampling.get('window_s')):
        errors.append('SAMPLING_INVALID')

    layers = record.get('layers')
    if not isinstance(layers, Mapping):
        errors.append('LAYERS_INVALID')
        layers = {}
    event_layer = layers.get('event')
    force_layer = layers.get('force')
    impulse_layer = layers.get('impulse')
    geometry_layer = layers.get('geometry')
    attribution_layer = layers.get('attribution')

    errors.extend(_validate_event_layer(event_layer, force_layer,
                                        attribution_layer))
    errors.extend(_validate_force_layer(force_layer))
    errors.extend(_validate_impulse_layer(impulse_layer))
    errors.extend(_validate_geometry_layer(geometry_layer))
    errors.extend(_validate_attribution_layer(attribution_layer, event_layer,
                                              force_layer))

    classification = record.get('classification')
    if classification not in CLASSIFICATIONS:
        errors.append('CLASSIFICATION_INVALID')
    else:
        try:
            recomputed = classify_contact(record)
        except (KeyError, TypeError, ValueError):
            recomputed = None
        if recomputed is not None and recomputed != classification:
            errors.append('INCONSISTENT_CLASSIFICATION')

    event_available = (event_layer.get('available')
                       if isinstance(event_layer, Mapping) else None)
    expected_reasons = []
    if sensor_available is False:
        expected_reasons.append(REASON_SENSOR_UNAVAILABLE)
    if event_available is False:
        expected_reasons.append(REASON_EVENT_UNAVAILABLE)
    unknown_reasons = record.get('unknown_reasons')
    if not (isinstance(unknown_reasons, list)
            and all(isinstance(reason, str) for reason in unknown_reasons)):
        errors.append('UNKNOWN_REASONS_INVALID')
    elif set(unknown_reasons) != set(expected_reasons):
        errors.append('UNKNOWN_REASONS_INVALID')

    validity = record.get('validity')
    if not (isinstance(validity, Mapping)
            and isinstance(validity.get('valid'), bool)
            and isinstance(validity.get('reasons'), list)
            and all(isinstance(reason, str)
                    for reason in validity.get('reasons'))):
        errors.append('VALIDITY_INVALID')
    else:
        if classification in CLASSIFICATIONS:
            expected_valid = classification != CLASS_UNKNOWN
            if validity['valid'] != expected_valid:
                errors.append('INCONSISTENT_VALIDITY')
        if isinstance(unknown_reasons, list) \
                and set(validity['reasons']) != set(unknown_reasons):
            errors.append('INCONSISTENT_VALIDITY')
    return errors


# ---------------------------------------------------------------------------
# episode summary
# ---------------------------------------------------------------------------

def summarize_contact_records(records):
    """Aggregate per-step contact records with explicit coverage ratios.

    All classification, unknown-reason and attribution status keys are always
    present (zero-filled) so downstream reports have a stable schema.
    """
    records = list(records)
    if not records:
        raise ValueError('cannot summarize an empty contact-record set')
    classification_counts = {name: 0 for name in _CLASSIFICATION_ORDER}
    unknown_reason_counts = {name: 0 for name in _UNKNOWN_REASON_ORDER}
    attribution_status_counts = {name: 0 for name in _ATTRIBUTION_ORDER}
    first_force_contact_time_s = None
    max_force_n = None
    force_available_steps = 0
    for index, record in enumerate(records):
        errors = validate_contact_record(record)
        if errors:
            raise ValueError('invalid contact record at index {}: {}'.format(
                index, '; '.join(errors)))
        classification = record['classification']
        classification_counts[classification] += 1
        for reason in record['unknown_reasons']:
            unknown_reason_counts[reason] = \
                unknown_reason_counts.get(reason, 0) + 1
        attribution_status_counts[
            record['layers']['attribution']['status']] += 1
        force_layer = record['layers']['force']
        if force_layer['available']:
            force_available_steps += 1
            magnitude = force_layer['magnitude_n']
            if max_force_n is None or magnitude > max_force_n:
                max_force_n = magnitude
        if classification in (CLASS_CONTACT_FORCE_MEASURED,
                              CLASS_CONTACT_FORCE_MEASURED_UNATTRIBUTED):
            time_s = record['time_s']
            if (first_force_contact_time_s is None
                    or time_s < first_force_contact_time_s):
                first_force_contact_time_s = time_s
    total_steps = len(records)
    return {
        'schema_version': CONTACT_EVIDENCE_SCHEMA_ID,
        'total_steps': total_steps,
        'classification_counts': classification_counts,
        'first_force_contact_time_s': first_force_contact_time_s,
        'max_force_n': max_force_n,
        'unknown_steps': classification_counts[CLASS_UNKNOWN],
        'unknown_reasons': unknown_reason_counts,
        'geometry_only_steps': classification_counts[CLASS_GEOMETRY_OVERLAP_ONLY],
        'force_available_ratio': force_available_steps / total_steps,
        'attributed_steps': attribution_status_counts[ATTRIBUTION_ATTRIBUTED],
        'unattributed_steps':
            attribution_status_counts[ATTRIBUTION_UNATTRIBUTED],
        'attribution_status_counts': attribution_status_counts,
    }
