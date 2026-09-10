def test_discovery_episode_records_verified_acceptance(
    monkeypatch,
    tmp_path,
):
    import sophyane.sli_learner as learner

    from sophyane.discovery_contract import (
        Candidate,
        DiscoveryCandidateResult,
        DiscoveryEpisode,
        ExperimentPlan,
        Observation,
        ValidationResult,
    )
    from sophyane.discovery_learning import (
        record_discovery_episode,
    )

    captured = {}

    def fake_learn_execution(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "provenance": dict(
                kwargs[
                    "provenance"
                ]
            )
        }

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fake_learn_execution,
    )

    candidate = Candidate(
        candidate_id="c1",
        hypothesis_id="h1",
        description="candidate",
    )

    plan = ExperimentPlan(
        experiment_id="e1",
        candidate_id="c1",
        experiment_type="simulation",
        procedure=("run",),
        success_criteria=("pass",),
        safe_for_autonomous_execution=True,
    )

    result = DiscoveryCandidateResult(
        candidate=candidate,
        experiment=plan,
        observation=Observation(
            experiment_id="e1",
            executed=True,
            ok=True,
            output="pass",
        ),
        validations=(
            ValidationResult(
                validator="test",
                passed=True,
                score=1.0,
                summary="verified",
            ),
        ),
        reproduced=True,
        final_novelty_score=0.8,
        accepted=True,
    )

    episode = DiscoveryEpisode(
        episode_id="discovery-test",
        objective="discover something",
        knowledge=(),
        hypotheses=(),
        results=(result,),
        started_at=1.0,
        finished_at=2.0,
        accepted_candidates=("c1",),
    )

    record_discovery_episode(
        episode,
        workspace=tmp_path,
    )

    provenance = captured[
        "provenance"
    ]

    assert (
        provenance[
            "event_type"
        ]
        == "discovery_episode"
    )

    assert (
        provenance[
            "accepted"
        ]
        is True
    )

    assert (
        provenance[
            "verification_state"
        ]
        == "verified"
    )
