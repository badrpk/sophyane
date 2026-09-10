import json


def _verified_episode(
    token,
):
    return {
        "trace_id": "phase8-seed",
        "event_key": "phase8-seed",
        "original_objective": (
            "Remember the verified Phase 8 marker "
            + token
        ),
        "status": "succeeded",
        "accepted": True,
        "verification_state": "verified",
        "verification_evidence": [
            {
                "validator": "seed",
                "passed": True,
            }
        ],
        "reward": 1.0,
        "provider_identity": "nifdu_browser",
        "model_identity": "chatgpt-browser",
        "session_mode": "nifdu_llm",
        "capability_class": "phase8-test",
        "result": (
            "Verified result contains "
            + token
        ),
    }


def test_complete_verified_cycle_creates_sparse_memory(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
        recall_sparse_memories,
    )

    from sophyane.cognitive_loop import (
        ActionResult,
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        VerificationResult,
        run_cognitive_cycle,
    )

    token = "PHASE8_COGNITION_CEDAR_9401"

    assert (
        consolidate_verified_episode(
            _verified_episode(token)
        )["ok"]
        is True
    )

    observed = []
    acted = []
    measured = []
    verified = []

    def observer(
        objective,
        context,
    ):
        observed.append(objective)

        return {
            "sensor": "test_sensor",
            "value": 7,
        }

    def reasoner(
        objective,
        context,
    ):
        text = json.dumps(
            context.get(
                "thought",
                {},
            ),
            ensure_ascii=False,
        )

        assert token in text

        return {
            "task": {
                "objective": (
                    "Run bounded Phase 8 test"
                ),
                "action_kind": (
                    "bounded_test"
                ),
                "risk_class": (
                    "local_test"
                ),
                "payload": {
                    "expected": 42,
                },
                "rationale": (
                    "Deterministic test"
                ),
                "bounded": True,
            }
        }

    registry = (
        CognitiveActionRegistry()
    )

    def action_handler(
        task,
        context,
    ):
        acted.append(
            task.task_id
        )

        return ActionResult(
            ok=True,
            status="completed",
            observation={
                "answer": 42,
            },
            evidence={
                "calculation": (
                    "6 * 7"
                ),
            },
        )

    registry.register(
        "bounded_test",
        action_handler,
    )

    def measurer(
        task,
        action,
        context,
    ):
        measured.append(
            task.task_id
        )

        return {
            "answer": (
                action.observation[
                    "answer"
                ]
            )
        }

    def verifier(
        task,
        action,
        measurement,
        context,
    ):
        verified.append(
            task.task_id
        )

        passed = (
            measurement["answer"]
            == 42
        )

        return VerificationResult(
            verified=passed,
            accepted=passed,
            evidence={
                "expected": 42,
                "actual": (
                    measurement[
                        "answer"
                    ]
                ),
            },
            score=(
                1.0
                if passed
                else 0.0
            ),
            reason=(
                "deterministic_match"
                if passed
                else "mismatch"
            ),
        )

    result = run_cognitive_cycle(
        "Use remembered cedar marker to test cognition",
        cycle_number=1,
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        measurer=measurer,
        verifier=verifier,
        config=CognitiveLoopConfig(
            dream_interval=99,
        ),
    )

    assert observed
    assert acted
    assert measured
    assert verified

    assert (
        result.verification.verified
        is True
    )

    assert (
        result.verification.accepted
        is True
    )

    assert (
        result.persistence[
            "exact_recorded"
        ]
        is True
    )

    assert (
        result.persistence[
            "trusted_episode_recorded"
        ]
        is True
    )

    assert (
        result.persistence[
            "sparse_memory_created"
        ]
        is True
    )

    rows = recall_sparse_memories(
        "bounded Phase 8 deterministic test",
        limit=16,
    )

    assert rows


def test_unverified_cycle_is_exactly_recorded_but_not_consolidated(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_loop import (
        ActionResult,
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        run_cognitive_cycle,
    )

    registry = (
        CognitiveActionRegistry()
    )

    registry.register(
        "bounded_test",
        lambda task, context: ActionResult(
            ok=True,
            status="completed",
            observation={
                "value": 123,
            },
        ),
    )

    def reasoner(
        objective,
        context,
    ):
        return {
            "task": {
                "objective": objective,
                "action_kind": (
                    "bounded_test"
                ),
                "risk_class": (
                    "local_test"
                ),
                "bounded": True,
            }
        }

    result = run_cognitive_cycle(
        "Unverified cycle",
        reasoner=reasoner,
        registry=registry,
        verifier=None,
        config=CognitiveLoopConfig(
            dream_interval=99,
        ),
    )

    assert (
        result.persistence[
            "exact_recorded"
        ]
        is True
    )

    assert (
        result.persistence[
            "trusted_episode_recorded"
        ]
        is False
    )

    assert (
        result.persistence[
            "sparse_memory_created"
        ]
        is False
    )

    assert (
        result.episode[
            "verification_state"
        ]
        == "unverified"
    )


def test_unregistered_action_cannot_execute(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_loop import (
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        run_cognitive_cycle,
    )

    def reasoner(
        objective,
        context,
    ):
        return {
            "task": {
                "objective": objective,
                "action_kind": (
                    "invented_power"
                ),
                "risk_class": (
                    "local_test"
                ),
                "bounded": True,
            }
        }

    result = run_cognitive_cycle(
        "Try invented capability",
        reasoner=reasoner,
        registry=CognitiveActionRegistry(),
        config=CognitiveLoopConfig(
            dream_interval=99,
        ),
    )

    assert result.action is not None

    assert (
        result.action.ok
        is False
    )

    assert (
        result.action.status
        == "capability_unavailable"
    )


def test_blocked_risk_class_never_reaches_handler(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_loop import (
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        run_cognitive_cycle,
    )

    called = []

    registry = (
        CognitiveActionRegistry()
    )

    registry.register(
        "machine_control",
        lambda task, context: (
            called.append(True)
        ),
    )

    def reasoner(
        objective,
        context,
    ):
        return {
            "task": {
                "objective": objective,
                "action_kind": (
                    "machine_control"
                ),
                "risk_class": (
                    "physical"
                ),
                "bounded": True,
            }
        }

    result = run_cognitive_cycle(
        "Move physical machine",
        reasoner=reasoner,
        registry=registry,
        config=CognitiveLoopConfig(
            dream_interval=99,
        ),
    )

    assert not called

    assert (
        result.action.status
        == "policy_blocked"
    )


def test_dream_becomes_unverified_future_hypothesis(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    from sophyane.cognitive_loop import (
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        run_cognitive_cycle,
    )

    consolidate_verified_episode(
        _verified_episode(
            "PHASE8_DREAM_MEMORY_ALPHA_1191"
        )
    )

    second = _verified_episode(
        "PHASE8_DREAM_MEMORY_BETA_1192"
    )

    second[
        "trace_id"
    ] = "phase8-seed-two"

    second[
        "event_key"
    ] = "phase8-seed-two"

    second[
        "original_objective"
    ] = (
        "A second verified Phase 8 memory "
        "shares dream memory testing."
    )

    consolidate_verified_episode(
        second
    )

    registry = (
        CognitiveActionRegistry()
    )

    registry.register(
        "hypothesis_only",
        lambda task, context: {
            "ok": True,
            "status": (
                "hypothesis_formed"
            ),
            "observation": {
                "executed": False,
            },
        },
    )

    result = run_cognitive_cycle(
        "dream memory testing",
        cycle_number=1,
        reasoner=lambda objective, context: {
            "hypotheses": [
                {
                    "statement": (
                        "Current test hypothesis"
                    ),
                    "rationale": (
                        "test"
                    ),
                    "predictions": [],
                    "assumptions": [],
                }
            ]
        },
        registry=registry,
        config=CognitiveLoopConfig(
            dream_interval=1,
        ),
    )

    assert result.dream is not None

    assert (
        result.dream["ok"]
        is True
    )

    hypothesis = (
        result.next_hypothesis
    )

    assert hypothesis is not None

    assert (
        hypothesis[
            "verified"
        ]
        is False
    )

    assert (
        hypothesis[
            "trusted"
        ]
        is False
    )

    assert (
        hypothesis[
            "accepted"
        ]
        is False
    )

    assert (
        hypothesis[
            "requires_external_verification"
        ]
        is True
    )


def test_bounded_loop_retests_dream_hypothesis(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    from sophyane.cognitive_loop import (
        CognitiveActionRegistry,
        CognitiveLoopConfig,
        run_cognitive_loop,
    )

    consolidate_verified_episode(
        _verified_episode(
            "PHASE8_LOOP_DREAM_7701"
        )
    )

    seen_objectives = []

    def reasoner(
        objective,
        context,
    ):
        seen_objectives.append(
            objective
        )

        return {
            "hypotheses": [
                {
                    "statement": (
                        "Memory association may "
                        "predict a reusable pattern."
                    ),
                    "rationale": (
                        "bounded reasoning"
                    ),
                    "predictions": [],
                    "assumptions": [],
                }
            ]
        }

    registry = (
        CognitiveActionRegistry()
    )

    registry.register(
        "hypothesis_only",
        lambda task, context: {
            "ok": True,
            "status": (
                "hypothesis_formed"
            ),
            "observation": {
                "executed": False,
            },
        },
    )

    results = run_cognitive_loop(
        "memory association dream test",
        reasoner=reasoner,
        registry=registry,
        config=CognitiveLoopConfig(
            max_cycles=2,
            max_runtime_seconds=30,
            dream_interval=1,
        ),
    )

    assert len(results) == 2

    assert (
        results[0].next_hypothesis
        is not None
    )

    assert len(
        seen_objectives
    ) == 2

    assert (
        "Test this unverified dream hypothesis"
        in seen_objectives[1]
    )
