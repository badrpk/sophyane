from sophyane.rsi.cloud_review import CloudReviewer, EvidencePackage
from sophyane.rsi.pre_verifier import VerificationEvidence
from sophyane.rsi.resource_governor import ResourceSnapshot


def test_cloud_fallback_requires_independent_preverification():
    calls = []
    cloud = CloudReviewer({'nifdu_browser': lambda package: calls.append('nifdu') or {'action': 'approve', 'tests_passed': True}})
    resources = ResourceSnapshot(user_active=False, online=True, cloud_budget_available=True, nifdu_available=True)
    invalid = EvidencePackage({'problem': 'bug'}, VerificationEvidence(), 'diff')
    assert cloud.review(invalid, resources).action != 'approve'
    assert calls == []
    package = EvidencePackage({'problem': 'bug'}, VerificationEvidence(accepted=True, fingerprint='exact'), 'diff')
    decision = cloud.review(package, resources)
    assert decision.provider == 'nifdu_browser' and decision.action == 'approve'
    assert calls == ['nifdu']
    assert CloudReviewer().review(package, resources).action != 'approve'
