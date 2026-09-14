from __future__ import annotations
import pytest
from sophyane.rsi.campaign import (BenchmarkManifest, CandidateGate, CampaignEvidence,
                                   RedStatus, StopReason, classify_red, evidence_level,
                                   run_campaign)
from sophyane.rsi.authority import AuthorityViolation, Operation, require, verify_mutation_authority


def good(n, parent):
    return {"provider": "codex_cli", "candidate": n, "next_state": n, "weakness": parent,
            "red_status": RedStatus.RED_CONFIRMED, "weakness_grounded": True, "focused_green": True,
            "holdout_green": True, "no_material_regression": True, "no_unauthorized_files": True,
            "no_authority_change": True, "score_before": n / 10, "score_after": (n + 1) / 10,
            "meta_score_before": n / 10, "meta_score_after": (n + 1) / 10,
            "trusted_evidence": CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, n > 0, True, False, 1, 0),
            "changed_files": (f"src/{n}.py",), "diff_fingerprint": f"diff-{n}"}


def independent_results(*, reject_first=False):
    """Host test fixture: verdicts never read attempt claims."""
    calls = 0
    baseline = 0.0

    def verify(_raw, _manifest):
        nonlocal calls, baseline
        green = not (reject_first and calls == 0)
        before = baseline
        after = before + 1.0 if green else before
        calls += 1

        if green:
            baseline = after

        return CampaignEvidence(
            True,
            RedStatus.RED_CONFIRMED,
            green,
            True,
            True,
            False,
            1,
            0,
            True,
            True,
            False,
            'codex_cli',
            before,
            after,
            None,
            None,
        )
    return verify


def test_manifest_digest_detects_change_and_is_stable():
    manifest = BenchmarkManifest(regression_checks=(("pytest", "-q"),))
    digest = manifest.digest()
    assert digest == manifest.digest()
    assert BenchmarkManifest(regression_checks=(("pytest", "-q", "changed"),)).digest() != digest
    assert "scoring_weights" in manifest.canonical()
    assert BenchmarkManifest(scoring_weights={"capability": 0.1, "meta": 0.9}).digest() != digest


def test_red_contract_classifies_required_states():
    assert classify_red(exit_code=1, expected_failure="boom", output="AssertionError: boom") is RedStatus.RED_CONFIRMED
    assert classify_red(exit_code=0, expected_failure="boom") is RedStatus.RED_ALREADY_GREEN
    assert classify_red(exit_code=1, expected_failure="boom", output="other") is RedStatus.RED_UNRELATED
    assert classify_red(exit_code=1, expected_failure="boom", output="boom", runs=(1, 0)) is RedStatus.RED_FLAKY_OR_NONDETERMINISTIC
    assert classify_red(exit_code=None) is RedStatus.RED_UNAVAILABLE


def test_gate_rejects_green_only_and_accepts_full_evidence():
    assert not CandidateGate(focused_green=True, holdout_green=True, red_status=RedStatus.RED_ALREADY_GREEN).accepted
    assert CandidateGate(True, True, RedStatus.RED_CONFIRMED, True, True, True, True, True).accepted


def test_campaign_two_accepted_generations_chain_state(tmp_path):
    seen = []
    result = run_campaign(weakness="g0", max_generations=2, evidence_dir=tmp_path, verifier=independent_results(), attempt=lambda n, parent: seen.append(parent) or good(n, parent))
    assert result.stop_reason == StopReason.MAX_GENERATIONS.value
    assert result.accepted_generations == 2
    assert seen == ["g0", 0]
    assert result.generations[-1].delta > 0  # Independently measured capability gain.
    assert (tmp_path / "ledger.jsonl").exists() and (tmp_path / "summary.json").exists()


def test_rejected_candidate_does_not_advance_state():
    seen = []
    def attempt(n, parent):
        seen.append(parent)
        if n == 0:
            return {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED, "focused_green": False, "holdout_green": True, "no_material_regression": True, "no_unauthorized_files": True, "no_authority_change": True}
        return good(n, parent)
    result = run_campaign(weakness="g0", max_generations=2, attempt=attempt, verifier=independent_results(reject_first=True))
    assert seen == ["g0", "g0"]
    assert result.generations[0].verdict == "REJECTED" and result.generations[1].verdict == "ACCEPTED"


def test_campaign_plateau_cycling_and_authority_stop():
    result = run_campaign(weakness="g0", max_generations=20, attempt=lambda n, p: {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED, "focused_green": False, "holdout_green": False, "no_material_regression": True, "no_unauthorized_files": True, "no_authority_change": True, "diff_fingerprint": str(n)})
    assert result.stop_reason == StopReason.PLATEAU.value
    cycling = run_campaign(weakness="g0", max_generations=20, attempt=lambda n, p: good(0, p))
    assert cycling.stop_reason == StopReason.CYCLING.value
    def unauthorized(_n, _p):
        raise AuthorityViolation("forbidden")
    assert run_campaign(weakness="g0", max_generations=4, attempt=unauthorized).stop_reason == StopReason.AUTHORITY_VIOLATION.value


def test_hard_cap_and_level_four_requires_meta_improvement():
    result = run_campaign(weakness="g0", max_generations=20, attempt=lambda n, p: good(n, p), verifier=independent_results())
    assert len(result.generations) <= 20
    assert result.stop_reason in {StopReason.MAX_GENERATIONS.value, StopReason.META_PLATEAU.value}
    assert evidence_level(3, (1, 1), (0, 0)) == 3
    assert evidence_level(3, (1, 1), (1, 1)) == 4


def test_maximum_is_enforced():
    with pytest.raises(ValueError):
        run_campaign(weakness="x", max_generations=21, attempt=lambda _n, _p: {})


def test_authority_constants_remain_unchanged():
    require("codex_cli", Operation.SOPHYANE_SOURCE_MUTATION)
    require("nifdu_browser", Operation.SOPHYANE_SOURCE_MUTATION)
    with pytest.raises(AuthorityViolation):
        require("local_gguf", Operation.SOPHYANE_SOURCE_MUTATION)



def test_level_four_requires_sustained_meta_improvement():
    assert evidence_level(3, (0.1, 0.1), (-0.8, -0.4, 0.01)) == 3
    assert evidence_level(3, (0.1, 0.1), (0.1, -0.2, 0.1)) == 3
    assert evidence_level(3, (0.1, 0.1), (0.0, 0.0, 0.01)) == 3
    assert evidence_level(3, (0.1, 0.1), (0.1, 0.1, 0.1)) == 4


def test_provider_name_alone_does_not_prove_campaign_authority():
    result = run_campaign(
        weakness="g0", max_generations=1,
        attempt=lambda _n, _p: {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
            "focused_green": True, "holdout_green": True, "no_material_regression": True,
            "no_unauthorized_files": True, "no_authority_change": True})
    assert verify_mutation_authority("codex_cli") is True
    assert CandidateGate().authority_ok is False


def test_malicious_self_reported_scores_are_ignored():
    evidence = CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, False, True, False, 1, 0)
    result = run_campaign(
        weakness="g0", max_generations=1,
        attempt=lambda _n, _p: {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
            "focused_green": True, "holdout_green": False, "no_material_regression": True,
            "no_unauthorized_files": True, "no_authority_change": True,
            "trusted_evidence": evidence, "score_before": 0.0, "score_after": 999999.0,
            "meta_score_before": 0.0, "meta_score_after": 999999.0})
    assert result.generations[0].score_after != 999999.0
    assert result.generations[0].meta_score_after != 999999.0


def test_rejected_self_reported_score_cannot_advance_accepted_baseline():
    evidence = CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, True, True, False, 1, 0)
    seen = []
    def attempt(number, parent):
        seen.append(parent)
        if number == 0:
            return {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
                "focused_green": False, "holdout_green": False, "no_material_regression": True,
                "no_unauthorized_files": True, "no_authority_change": True,
                "score_after": 999999.0, "meta_score_after": 999999.0}
        return {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
            "focused_green": True, "holdout_green": True, "no_material_regression": True,
            "no_unauthorized_files": True, "no_authority_change": True,
            "trusted_evidence": evidence}
    result = run_campaign(weakness="g0", max_generations=2, attempt=attempt, verifier=independent_results(reject_first=True))
    assert seen == ["g0", "g0"]
    assert result.generations[1].score_before == 0.0


def test_scoring_is_deterministic_from_trusted_evidence():
    evidence = CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, True, True, True, 2, 1)
    from sophyane.rsi.campaign import capability_score, meta_improvement_score
    assert capability_score(evidence=evidence) == capability_score(evidence=evidence)
    assert meta_improvement_score(evidence=evidence) == meta_improvement_score(evidence=evidence)



def test_omitted_and_garbage_provider_scores_do_not_change_trusted_measurement():
    evidence = CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, True, True, False, 1, 0)
    def attempt(number, _parent):
        result = {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
            "focused_green": True, "holdout_green": True, "no_material_regression": True,
            "no_unauthorized_files": True, "no_authority_change": True,
            "trusted_evidence": evidence}
        if number == 1:
            result.update(score_before=-999, score_after="garbage", meta_score_after=-999)
        return result
    result = run_campaign(weakness="g0", max_generations=2, attempt=attempt)
    assert result.generations[1].score_before == result.generations[0].score_after
    assert result.generations[1].meta_score_after == result.generations[0].meta_score_after


def test_provider_cannot_self_award_level_four():
    def attempt(n, _parent):
        return {"provider": "codex_cli", "red_status": RedStatus.RED_CONFIRMED,
            "focused_green": True, "holdout_green": True, "no_material_regression": True,
            "no_unauthorized_files": True, "no_authority_change": True,
            "diff_fingerprint": f"unique-{n}", "score_after": 999999,
            "meta_score_after": 999999}
    result = run_campaign(weakness="g0", max_generations=3, attempt=attempt)
    assert result.evidence_level < 4
