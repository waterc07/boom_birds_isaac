"""Deterministic delayed action arrival queue; original action TTL is preserved."""
from dataclasses import dataclass, field

@dataclass(order=True)
class _Item:
    delivery_s: float
    sequence: int
    action: object = field(compare=False)
    command: tuple = field(compare=False)

class DelayedActionQueue:
    def __init__(self):
        self._items=[]; self._seq=0; self.rejected=[]
    def schedule(self, delivery_s, action, command):
        self._seq += 1
        self._items.append(_Item(float(delivery_s), self._seq, action, tuple(command)))
        self._items.sort()
    def take_due(self, now_s):
        due=[x for x in self._items if x.delivery_s <= now_s]
        self._items=[x for x in self._items if x.delivery_s > now_s]
        return [(x.action, x.command) for x in due]
    def clear(self):
        n=len(self._items); self._items=[]; return n
    def pending(self): return len(self._items)

class DelayedVelocityExecutor:
    """Wrap an executor with deterministic fixed transport delay.

    Setpoints keep their original expires_at; the wrapped executor rejects an
    expired setpoint at arrival. No renewal happens in this wrapper.
    """
    def __init__(self, executor, delay_s):
        if delay_s < 0:
            raise ValueError('delay_s must be nonnegative')
        object.__setattr__(self, '_inner', executor)
        object.__setattr__(self, '_delay_s', float(delay_s))
        object.__setattr__(self, '_queue', DelayedActionQueue())

    def clear(self):
        return self._queue.clear()

    def reset(self, state=None):
        self._queue.clear()
        return self._inner.reset(state)

    @property
    def control_epoch(self):
        return self._inner.control_epoch

    @control_epoch.setter
    def control_epoch(self, value):
        self._inner.control_epoch = value

    def step(self, setpoint, state, now_s):
        if setpoint is not None:
            self._queue.schedule(now_s + self._delay_s, setpoint, ())
        due = self._queue.take_due(now_s)
        selected = due[-1][0] if due else None
        return self._inner.step(selected, state, now_s)

    def __getattr__(self, name):
        return getattr(self._inner, name)
