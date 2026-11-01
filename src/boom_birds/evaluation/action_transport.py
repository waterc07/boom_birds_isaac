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
