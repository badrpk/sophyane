from sophyane.rsi.campaign import CampaignEvidence, CandidateGate, RedStatus, capability_score, run_campaign


def forged(n, parent):
    return dict(provider='codex_cli', candidate=n, next_state=n,
                diff_fingerprint=str(n), weakness_grounded=True,
                red_status=RedStatus.RED_CONFIRMED, focused_green=True,
                holdout_green=True, no_material_regression=True,
                no_unauthorized_files=True, no_authority_change=True,
                authorized=True, verified=True, tests_passed=True,
                trusted_evidence=CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, True, True, True),
                score_after=999, meta_score_after=999)


def test_forged_perfect_evidence_cannot_accept_without_independent_verifier():
    result = run_campaign(weakness='real failure', attempt=forged, max_generations=3)
    assert result.accepted_generations == 0
    assert result.evidence_level == 0
    assert all(g.score_after == 0 and g.meta_score_after == 0 for g in result.generations)


def test_unavailable_red_gets_no_scientific_credit():
    assert capability_score(red=RedStatus.RED_UNAVAILABLE) == 0
    assert not CandidateGate(True, True, RedStatus.RED_UNAVAILABLE, True, True, True, True, True).accepted


def test_generic_error_is_not_genuine_red_and_unproven_rejection_is_not_good_diagnosis():
    from sophyane.rsi.campaign import classify_red
    assert classify_red(exit_code=2, output='usage error') != RedStatus.RED_CONFIRMED
    assert classify_red(exit_code=1, output='arbitrary failure') != RedStatus.RED_CONFIRMED
    result = run_campaign(weakness='failure', attempt=lambda n, p: {'provider': 'codex_cli'})
    assert result.generations[0].meta_score_after == 0


def test_repeated_verifier_gates_without_measured_gain_do_not_advance_state():
    from dataclasses import replace
    evidence = CampaignEvidence(True, RedStatus.RED_CONFIRMED, True, True, True,
                                False, 1, 0, True, True, False, 'codex_cli')
    result = run_campaign(weakness='initial', attempt=forged, max_generations=2,
                          verifier=lambda raw, manifest: evidence)
    assert result.accepted_generations == 0
