"""Bounded fair selection over due weaknesses."""
from dataclasses import dataclass
from .resource_governor import ResourceDecision

@dataclass(frozen=True)
class Opportunity:
    fingerprint: str
    decision: ResourceDecision

class OpportunityScheduler:
    def __init__(self, ledger, governor, max_work=1):
        self.ledger, self.governor, self.max_work = ledger, governor, max_work
    def select(self, snapshot, now=0):
        decision = self.governor.decide(snapshot)
        if decision is ResourceDecision.OBSERVE_ONLY:
            return ()
        due = sorted((r for r in self.ledger.records.values()
                      if r.status != 'accepted' and r.retry_at <= now),
                     key=lambda r: (r.last_selected, -r.priority, r.fingerprint))
        selected = due[:max(0, min(self.max_work, 16))]
        for record in selected:
            record.last_selected = now
        self.ledger.save()
        return tuple(Opportunity(r.fingerprint, decision) for r in selected)
