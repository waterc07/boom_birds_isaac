"""Deterministic simulated clocks/event queue for latency diagnostics (no sleep).

Two clock domains are modelled: the host monotonic clock (the runner's ``now_ns``)
and a simulated camera/PX4-style clock whose reading is
``host_ns + offset_ns + host_ns * drift_ppm / 1e6``. A :class:`SimMapping`
inverts that relation and reports a conservative error bound that grows with
``drift_ppm`` and the host reference time. :func:`mapping_age` turns a captured
foreign-clock timestamp into a point estimate *and* an upper-bound age; callers
must use the bound for supervision decisions (V2.2 16.1-16.3).
"""
from dataclasses import dataclass, field
import math

ACCEPT = 'ACCEPT'
ACCEPT_NEGATIVE_AGE = 'ACCEPT_NEGATIVE_AGE'
CLOCK_MAPPING_UNUSABLE = 'CLOCK_MAPPING_UNUSABLE'


@dataclass(frozen=True)
class SimClock:
    clock_id: str
    offset_ns: int = 0
    drift_ppm: float = 0.0
    uncertainty_ns: int = 0
    def read_ns(self, host_ns):
        return int(round(host_ns + self.offset_ns + host_ns * self.drift_ppm / 1e6))
    def read_uncertainty_ns(self):
        """Absolute read/offset uncertainty; never a signed or zero-impostor value."""
        return abs(self.uncertainty_ns)
    def to_host_ns(self, clock_ns, host_ns=None):
        approx = (clock_ns - self.offset_ns) / (1.0 + self.drift_ppm / 1e6)
        return int(round(approx))


@dataclass(frozen=True)
class SimMapping:
    source_clock_id: str
    target_clock_id: str
    offset_ns: int
    uncertainty_ns: int
    sync_generation: int
    valid_from_host_ns: int = 0
    valid_until_host_ns: int = 10**18
    valid: bool = True
    drift_ppm: float = 0.0
    def usable(self, host_ns, sync_generation):
        return (self.valid and self.sync_generation == sync_generation
                and self.valid_from_host_ns <= host_ns <= self.valid_until_host_ns)
    def map_uncertainty_ns(self, host_reference_ns=0):
        """Worst-case mapping error; offset, observation and clock-drift terms add up."""
        drift_ns = int(math.ceil(abs(self.drift_ppm) * 1e-6 * abs(host_reference_ns)))
        return abs(self.offset_ns) + abs(self.uncertainty_ns) + drift_ns
    def to_host_ns(self, clock_ns):
        """Inverse point estimate of the forward ``SimClock.read_ns`` relation."""
        approx = (clock_ns - self.offset_ns) / (1.0 + self.drift_ppm / 1e6)
        return int(round(approx))


def mapping_age(capture_clock_ns, host_now_ns, mapping, sync_generation):
    """Map a foreign-clock capture to host time and report point/bound age.

    Returns ``dict(valid, reason, age_point_s, age_bound_s, mapped_host_ns,
    error_bound_ns)``.  An unusable mapping (invalid flag, sync generation
    mismatch or outside the validity window) yields ``valid=False`` and
    ``reason='CLOCK_MAPPING_UNUSABLE'`` with explicit ``None`` ages: unknown age
    must never be reported as a zero-valued valid reading.  ``age_bound_s`` is
    always >= ``age_point_s`` so supervisors can use it directly.
    """
    unusable = {
        'valid': False,
        'reason': CLOCK_MAPPING_UNUSABLE,
        'age_point_s': None,
        'age_bound_s': None,
        'mapped_host_ns': None,
        'error_bound_ns': None,
    }
    if not isinstance(mapping, SimMapping):
        return unusable
    if not mapping.usable(host_now_ns, sync_generation):
        return unusable
    mapped_host_ns = mapping.to_host_ns(capture_clock_ns)
    error_bound_ns = mapping.map_uncertainty_ns(host_now_ns)
    age_ns = int(round(host_now_ns - mapped_host_ns))
    negative = age_ns < 0
    if negative:
        # future/stale clock readings are clamped to zero but stay flagged
        age_ns = 0
    age_point_s = age_ns / 1e9
    age_bound_s = (age_ns + error_bound_ns) / 1e9
    if age_bound_s < age_point_s:
        age_bound_s = age_point_s
    return {
        'valid': True,
        'reason': ACCEPT_NEGATIVE_AGE if negative else ACCEPT,
        'age_point_s': age_point_s,
        'age_bound_s': age_bound_s,
        'mapped_host_ns': mapped_host_ns,
        'error_bound_ns': error_bound_ns,
    }


@dataclass(order=True)
class QueuedEvent:
    due_ns: int
    sequence: int
    payload: dict = field(compare=False, default_factory=dict)

class EventQueue:
    """Deterministic due-time queue; duplicates/out-of-order are explicit events."""
    def __init__(self):
        self._items = []
        self._next_sequence = 0
        self.rejected = []
    def push(self, due_ns, payload, *, duplicate_of=None):
        item = QueuedEvent(int(due_ns), self._next_sequence,
                           {'payload': payload, 'duplicate_of': duplicate_of})
        self._next_sequence += 1
        self._items.append(item)
        self._items.sort()
        return item
    def pop_due(self, now_ns):
        due = [item for item in self._items if item.due_ns <= now_ns]
        self._items = [item for item in self._items if item.due_ns > now_ns]
        return due
    def clear(self):
        count = len(self._items); self._items = []; return count
    def pending(self):
        return len(self._items)
