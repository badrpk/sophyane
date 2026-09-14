"""Targeted SLI discovery yields untrusted source-bearing claims."""
from dataclasses import dataclass
from itertools import islice
from .resource_governor import ResourceGovernor, ResourceDecision

@dataclass(frozen=True)
class ResearchClaim:
    weakness_fingerprint: str
    claim: str
    reference: str
    source: str = 'sli'
    trusted: bool = False
    mutation_authority: bool = False

class TargetedSLIResearch:
    def __init__(self, search=None, limit=3):
        self.search, self.limit, self.calls = search or sli_search, max(1, min(limit, 5)), 0
    def discover(self, weakness, resources):
        if (not weakness.evidence or not weakness.problem or
            ResourceGovernor().decide(resources, research=True) is not ResourceDecision.INTERNET_RESEARCH):
            return ()
        query = (weakness.component + ': ' + weakness.problem)[:500]
        self.calls += 1
        results = self.search(query, self.limit)
        claims = []
        for result in islice(results, self.limit):
            if isinstance(result, dict) and result.get('claim') and result.get('reference'):
                claims.append(ResearchClaim(weakness.fingerprint, str(result['claim'])[:3000],
                                            str(result['reference'])[:2000]))
        return tuple(claims)


def sli_search(query, limit):
    # Existing SLI acquisition discovery only: no clone, ingestion or execution.
    from sophyane.code_memory.internet_acquire import search_repositories
    return ({'claim': repository.description,
             'reference': repository.clone_url, 'source': repository.full_name}
            for repository in islice(search_repositories(query), limit))
