import unittest

from sophyane.release_evidence_gate import (
    Evidence,
    EvidenceGateError,
    ReleaseEvidenceGate,
    Requirement,
    default_requirements,
)


class ReleaseEvidenceGateTests(unittest.TestCase):
    def test_missing_evidence_blocks_release(self):
        gate = ReleaseEvidenceGate([Requirement("xerus", "memory", "persistence")])
        result = gate.evaluate([])
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"][0]["ok"])

    def test_matching_evidence_allows_requirement(self):
        gate = ReleaseEvidenceGate([Requirement("xerus", "memory", "persistence")])
        result = gate.evaluate([Evidence("xerus", "memory", "persistence", "pass")])
        self.assertTrue(result["ready"])

    def test_health_is_not_strong_enough_for_native_requirement(self):
        gate = ReleaseEvidenceGate([Requirement("worker", "execute", "native")])
        result = gate.evaluate([Evidence("worker", "execute", "health", "pass")])
        self.assertFalse(result["ready"])

    def test_native_evidence_satisfies_weaker_requirement(self):
        gate = ReleaseEvidenceGate([Requirement("peer", "cap", "health")])
        result = gate.evaluate([Evidence("peer", "cap", "native", "pass")])
        self.assertTrue(result["ready"])

    def test_fail_blocks_even_if_pass_exists(self):
        gate = ReleaseEvidenceGate([Requirement("peer", "cap", "health")])
        result = gate.evaluate([
            Evidence("peer", "cap", "health", "pass"),
            Evidence("peer", "cap", "native", "fail"),
        ])
        self.assertFalse(result["ready"])

    def test_wrong_capability_does_not_satisfy_requirement(self):
        gate = ReleaseEvidenceGate([Requirement("peer", "compile", "compiler")])
        result = gate.evaluate([Evidence("peer", "render", "native", "pass")])
        self.assertFalse(result["ready"])

    def test_evidence_hash_is_deterministic(self):
        gate = ReleaseEvidenceGate([Requirement("peer", "cap", "health")])
        evidence = [Evidence("peer", "cap", "health", "pass")]
        self.assertEqual(gate.evaluate(evidence), gate.evaluate(evidence))

    def test_duplicate_requirement_rejected(self):
        with self.assertRaises(EvidenceGateError):
            ReleaseEvidenceGate([
                Requirement("peer", "cap", "health"),
                Requirement("peer", "cap", "native"),
            ])

    def test_bad_artifact_hash_rejected(self):
        with self.assertRaises(EvidenceGateError):
            Evidence("peer", "cap", "health", "pass", "bad")

    def test_default_requirements_cover_core_external_owners(self):
        reqs = default_requirements()
        peers = {req.peer for req in reqs}
        self.assertEqual(peers, {"xerus", "nifdu", "Veyron", "Lexane", "Cosmos"})


if __name__ == "__main__":
    unittest.main()
