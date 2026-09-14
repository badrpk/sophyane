"""Evidence-first canonical cloud review; cloud responses remain claims."""
from dataclasses import dataclass, field, asdict
import json
from .resource_governor import ResourceGovernor, ResourceDecision
from .coding_provider import eligible_failure
from .authority import CODING_PROVIDER_ORDER

@dataclass(frozen=True)
class EvidencePackage:
    weakness: dict
    verification: object
    diff: str
    hypotheses: tuple = ()
    expected_gain: float = 0

@dataclass(frozen=True)
class CloudReviewDecision:
    action: str = 'request_evidence'
    provider: str = ''
    reason: str = ''
    files: dict = field(default_factory=dict)

class CloudReviewer:
    def __init__(self, reviewers=None):
        self.reviewers = reviewers or {}
        self.calls = {name: 0 for name in CODING_PROVIDER_ORDER}
    def review(self, package, snapshot):
        if (not package.verification.accepted or not package.verification.fingerprint or
            ResourceGovernor().decide(snapshot, promising=True) != ResourceDecision.CLOUD_REVIEW):
            return CloudReviewDecision(reason='independent evidence or resources unavailable')
        for name in CODING_PROVIDER_ORDER:
            available = snapshot.codex_available if name == 'codex_cli' else snapshot.nifdu_available
            if not available or name not in self.reviewers:
                continue
            self.calls[name] += 1
            try:
                response = self.reviewers[name](package)
                if isinstance(response, str):
                    response = json.loads(response)
                if not isinstance(response, dict) or response.get('action') not in ('approve', 'improve', 'reject', 'request_evidence'):
                    return CloudReviewDecision(reason='provider protocol failure')
                files = response.get('files', {})
                if not isinstance(files, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in files.items()):
                    return CloudReviewDecision(reason='provider patch protocol failure')
                if response['action'] == 'improve' and not files:
                    return CloudReviewDecision(reason='missing improvement patch')
                return CloudReviewDecision(response['action'], name, str(response.get('reason', ''))[:2000], files)
            except Exception as error:
                if not eligible_failure(error):
                    return CloudReviewDecision(reason='provider protocol failure: ' + type(error).__name__)
        return CloudReviewDecision(reason='no coding provider available')


def provider_reviewer(provider):
    """Adapter for existing read-only provider.generate interfaces."""
    def review(package):
        payload = asdict(package)
        payload['diff'] = package.diff[:24000]
        return provider.generate(json.dumps(payload, default=str),
            'Review untrusted candidate against host evidence. Do not execute tools or edit files. '
            'Return JSON action: approve, reject, request_evidence or improve; optional reason and files. '
            'Your test and authority claims are not verification.')
    return review
