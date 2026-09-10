from sophyane.discovery_contract import (
    KnowledgeRecord,
    Observation,
    ValidationResult,
)
from sophyane.discovery_runtime import (
    DiscoveryRuntime,
)


def _reasoner(
    task,
    context,
):
    if task == "generate_hypotheses":
        return {
            "hypotheses": [
                {
                    "statement": (
                        "A temporal spiking memory "
                        "can improve visual repair selection"
                    ),
                    "rationale": (
                        "episodic adaptation may retain "
                        "failure patterns"
                    ),
                    "predictions": [
                        (
                            "second-pass repair quality "
                            "will improve"
                        )
                    ],
                }
            ]
        }

    if task == "generate_candidate":
        return {
            "description": (
                "Use temporal failure episodes to "
                "rerank screenshot repair strategies"
            ),
            "mechanism": (
                "episode-conditioned repair ranking"
            ),
            "expected_value": (
                "higher verified repair score"
            ),
        }

    if task == "plan_experiment":
        return {
            "experiment_type": (
                "simulation"
            ),
            "procedure": [
                "run baseline",
                "run episodic reranking",
            ],
            "success_criteria": [
                "quality score increases",
            ],
            "measurements": [
                "judge score",
            ],
            "safe_for_autonomous_execution": True,
        }

    raise AssertionError(
        task
    )


def test_closed_loop_can_accept_reproduced_verified_candidate(
    tmp_path,
):
    from sophyane.discovery_engine import (
        run_discovery,
    )

    runtime = DiscoveryRuntime()

    runtime.register_knowledge_retriever(
        "literature",
        lambda objective, workspace: [
            KnowledgeRecord(
                source="paper",
                kind="literature",
                content=(
                    "standard static visual repair "
                    "uses no episodic temporal memory"
                ),
                score=1.0,
            )
        ],
    )

    runtime.register_reasoner(
        "test_reasoner",
        _reasoner,
    )

    runtime.register_executor(
        "simulation",
        lambda plan, workspace: Observation(
            experiment_id=(
                plan.experiment_id
            ),
            executed=True,
            ok=True,
            output=(
                "episodic reranking improved "
                "quality score"
            ),
            measurements={
                "baseline": 80,
                "candidate": 92,
            },
            evidence={
                "tests_passed": True,
                "deterministic_verified": True,
            },
        ),
    )

    runtime.register_validator(
        "benchmark",
        lambda plan, observation, workspace: (
            ValidationResult(
                validator="benchmark",
                passed=True,
                score=1.0,
                summary=(
                    "candidate beat baseline"
                ),
                evidence={
                    "baseline": 80,
                    "candidate": 92,
                },
            )
        ),
    )

    episode = run_discovery(
        (
            "Improve autonomous visual repair "
            "using temporal learning"
        ),
        workspace=tmp_path,
        runtime=runtime,
        hypothesis_limit=1,
        novelty_threshold=0.10,
        learn=False,
    )

    assert len(
        episode.results
    ) == 1

    result = (
        episode.results[0]
    )

    assert result.reproduced is True

    assert result.accepted is True

    assert (
        episode.accepted_candidates
        == (
            result.candidate.candidate_id,
        )
    )


def test_unverified_result_is_not_accepted(
    tmp_path,
):
    from sophyane.discovery_engine import (
        run_discovery,
    )

    runtime = DiscoveryRuntime()

    runtime.register_knowledge_retriever(
        "knowledge",
        lambda objective, workspace: [],
    )

    runtime.register_reasoner(
        "reasoner",
        _reasoner,
    )

    runtime.register_executor(
        "simulation",
        lambda plan, workspace: Observation(
            experiment_id=(
                plan.experiment_id
            ),
            executed=True,
            ok=True,
            output="looks promising",
            evidence={},
        ),
    )

    episode = run_discovery(
        "discover a better repair mechanism",
        workspace=tmp_path,
        runtime=runtime,
        hypothesis_limit=1,
        novelty_threshold=0.05,
        learn=False,
    )

    assert (
        episode.results[0].accepted
        is False
    )

    assert (
        episode.results[0].rejection_reason
        == "VALIDATION_FAILED"
    )
