"""Deterministic simulated clocks/event queue for latency diagnostics (no sleep)."""
from dataclasses import dataclass, field
import math

@dataclass(frozen=True)
class SimClock:
    clock_id: str
    offset_ns: int = 0
    drift_ppm: float = 0.0
    uncertainty_ns: int = 0
    def read_ns(self, host_ns):
        return int(round(host_ns + self.offset_ns + host_ns * self.drift_ppm / 1e6))
    def to_host_ns(self, clock_ns, host_ns):
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
    def usable(self, host_ns, sync_generation):
        return (self.valid and self.sync_generation == sync_generation
                and self.valid_from_host_ns <= host_ns <= self.valid_until_host_ns)
    def map_uncertainty_ns(self):
        return abs(self.offset_ns) + self.uncertainty_ns

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
