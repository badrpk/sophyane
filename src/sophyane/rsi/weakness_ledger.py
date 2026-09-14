"""Persistent bounded diagnostic ledger; its records grant no authority."""
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path

class WeaknessStatus(str, Enum):
    PENDING = 'pending'
    DEFERRED = 'deferred'
    REJECTED = 'rejected'
    ACCEPTED = 'accepted'

@dataclass
class WeaknessRecord:
    fingerprint: str
    problem: str
    component: str
    evidence: list[str]
    sources: list[str]
    occurrences: int = 1
    expected_gain: float = 1.0
    estimated_cost: float = 1.0
    confidence: float = 0.5
    status: str = WeaknessStatus.PENDING.value
    retry_at: float = 0
    attempts: int = 0
    last_selected: float = 0
    first_seen: float = 0
    rejection_history: list[str] = field(default_factory=list)

    @property
    def priority(self):
        return self.expected_gain * self.confidence * min(self.occurrences, 10) / max(.1, self.estimated_cost)

class WeaknessLedger:
    def __init__(self, path=None, capacity=2048):
        self.path = Path(path) if path else None
        self.capacity, self.records = capacity, {}
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            self.records = {key: WeaknessRecord(**value) for key, value in list(data.items())[:capacity]}

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({k: asdict(v) for k, v in self.records.items()}, sort_keys=True))
            temporary.replace(self.path)

    def ingest(self, observation, occurrences=1, now=0):
        key = observation.fingerprint
        if key in self.records:
            record = self.records[key]
            record.occurrences = min(1000000, record.occurrences + max(1, occurrences))
            record.evidence = list(dict.fromkeys(record.evidence + list(observation.evidence)))[:32]
            record.sources = list(dict.fromkeys(record.sources + [observation.source.value]))
        else:
            if len(self.records) >= self.capacity:
                return None
            record = WeaknessRecord(key, observation.problem[:2000], observation.component[:300],
                [str(x)[:2000] for x in observation.evidence[:32]], [observation.source.value],
                occurrences=max(1, occurrences), first_seen=now)
            self.records[key] = record
        self.save()
        return record

    def reject(self, fingerprint, reason, now=0):
        record = self.records[fingerprint]
        record.attempts += 1
        record.status = WeaknessStatus.REJECTED.value
        record.retry_at = now + min(3600, 30 * 2 ** min(record.attempts, 7))
        record.rejection_history = (record.rejection_history + [str(reason)[:1000]])[-32:]
        self.save()
