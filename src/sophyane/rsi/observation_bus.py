"""Bounded diagnostic observations; never mutation instructions."""
from dataclasses import dataclass
from enum import Enum
import hashlib
from collections import OrderedDict
from threading import Lock

class ImprovementSource(str, Enum):
    MODE6 = 'mode6'
    RUNTIME = 'runtime'
    TEST = 'test'
    PROVIDER = 'provider'
    PERFORMANCE = 'performance'
    BENCHMARK = 'benchmark'
    SLI = 'sli'
    USER_FRICTION = 'user_friction'
    DIAGNOSTIC = 'diagnostic'

@dataclass(frozen=True)
class ImprovementObservation:
    source: ImprovementSource
    problem: str
    component: str
    evidence: tuple[str, ...]
    suggested_direction: str = ''

    @property
    def fingerprint(self):
        return hashlib.sha256((self.component.strip().casefold() + '\0' +
                               ' '.join(self.problem.casefold().split())).encode()).hexdigest()

class ObservationBus:
    def __init__(self, capacity=256, wake=lambda: None):
        if capacity < 1:
            raise ValueError('positive capacity required')
        self.capacity, self.wake = capacity, wake
        self._pending, self._lock = OrderedDict(), Lock()

    def submit(self, observation):
        if (not isinstance(observation, ImprovementObservation) or not observation.problem.strip()
                or not observation.component.strip() or not observation.evidence):
            return False
        with self._lock:
            key = observation.fingerprint
            if key not in self._pending and len(self._pending) >= self.capacity:
                return False
            previous = self._pending.get(key)
            self._pending[key] = (observation, min(1000000, previous[1] + 1) if previous else 1)
        self.wake()
        return True

    def drain(self, limit=16):
        with self._lock:
            return tuple(self._pending.popitem(last=False)[1]
                         for _ in range(min(max(0, limit), len(self._pending))))

# Shared ingress, constructed without threads, providers or filesystem writes.
autonomous_bus = ObservationBus()
