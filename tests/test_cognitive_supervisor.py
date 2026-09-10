import json


def _seed_episode(token):
    return {
        "trace_id": (
            "phase9-seed-"
            + token[-6:]
        ),
        "event_key": (
            "phase9-seed-"
            + token[-6:]
        ),
        "original_objective": (
            "Remember verified supervisor marker "
            + token
        ),
        "status": "succeeded",
        "accepted": True,
        "verification_state": "verified",
        "verification_evidence": [
            {
                "validator": "phase9-test",
                "passed": True,
            }
        ],
        "reward": 1.0,
        "provider_identity": "nifdu_browser",
        "model_identity": "chatgpt-browser",
        "session_mode": "nifdu_llm",
        "capability_class": "phase9-test",
        "result": (
            "Verified supervisor marker "
            + token
        ),
    }


def _test_components():
    from sophyane.cognitive_loop import (
        ActionResult,
        CognitiveActionRegistry,
        VerificationResult,
    )

    registry = CognitiveActionRegistry()

    registry.register(
        "phase9_test",
        lambda task, context: ActionResult(
            ok=True,
            status="completed",
            observation={
                "value": 42,
            },
            evidence={
                "deterministic": True,
            },
        ),
    )

    def observer(
        objective,
        context,
    ):
        return {
            "sensor": "phase9-test",
            "value": 21,
        }

    def reasoner(
        objective,
        context,
    ):
        return {
            "task": {
                "objective": objective,
                "action_kind": (
                    "phase9_test"
                ),
                "risk_class": (
                    "local_test"
                ),
                "payload": {},
                "bounded": True,
            }
        }

    def verifier(
        task,
        action,
        measurement,
        context,
    ):
        passed = (
            action.ok
            and measurement[
                "observation"
            ][
                "value"
            ]
            == 42
        )

        return VerificationResult(
            verified=passed,
            accepted=passed,
            evidence={
                "expected": 42,
                "actual": (
                    measurement[
                        "observation"
                    ][
                        "value"
                    ]
                ),
            },
            score=(
                1.0
                if passed
                else 0.0
            ),
            reason=(
                "pass"
                if passed
                else "fail"
            ),
        )

    return (
        observer,
        reasoner,
        registry,
        verifier,
    )


def test_wake_rest_dream_wake_lifecycle(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    from sophyane.cognitive_supervisor import (
        PHASE_WAKE,
        SupervisorConfig,
        run_supervisor,
    )

    consolidate_verified_episode(
        _seed_episode(
            "PHASE9_DREAM_CEDAR_8811"
        )
    )

    second = _seed_episode(
        "PHASE9_DREAM_CEDAR_8812"
    )

    second[
        "trace_id"
    ] = "phase9-seed-two"

    second[
        "event_key"
    ] = "phase9-seed-two"

    second[
        "original_objective"
    ] = (
        "Another verified cedar supervisor "
        "memory shares cognition."
    )

    consolidate_verified_episode(
        second
    )

    (
        observer,
        reasoner,
        registry,
        verifier,
    ) = _test_components()

    result = run_supervisor(
        "Test persistent cognitive supervisor",
        config=SupervisorConfig(
            wake_cycles_before_rest=2,
            rest_steps=1,
            dream_steps=1,
            wake_energy_cost=0.25,
            rest_energy_recovery=0.5,
            max_supervisor_steps=5,
            max_runtime_seconds=30,
        ),
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        verifier=verifier,
    )

    events = result[
        "events"
    ]

    kinds = [
        event.get(
            "event",
            {},
        ).get(
            "kind"
        )
        for event in events
        if event.get(
            "ok"
        )
    ]

    assert kinds[:4] == [
        "wake",
        "wake",
        "rest",
        "dream",
    ]

    assert (
        result[
            "state"
        ][
            "phase"
        ]
        == PHASE_WAKE
        or kinds[-1]
        == "wake"
    )

    dream_event = next(
        event[
            "event"
        ]
        for event in events
        if event.get(
            "event",
            {}
        ).get(
            "kind"
        )
        == "dream"
    )

    assert (
        dream_event[
            "external_action"
        ]
        is False
    )


def test_supervisor_state_survives_restart(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_supervisor import (
        SupervisorConfig,
        load_supervisor_state,
        run_supervisor,
    )

    (
        observer,
        reasoner,
        registry,
        verifier,
    ) = _test_components()

    config = SupervisorConfig(
        wake_cycles_before_rest=2,
        max_supervisor_steps=1,
        max_runtime_seconds=30,
    )

    first = run_supervisor(
        "Persistent restart objective",
        config=config,
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        verifier=verifier,
    )

    first_id = first[
        "state"
    ][
        "supervisor_id"
    ]

    first_step = first[
        "state"
    ][
        "supervisor_step"
    ]

    second = run_supervisor(
        "Persistent restart objective",
        config=config,
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        verifier=verifier,
    )

    assert (
        second[
            "state"
        ][
            "supervisor_id"
        ]
        == first_id
    )

    assert (
        second[
            "state"
        ][
            "supervisor_step"
        ]
        > first_step
    )

    loaded = load_supervisor_state(
        "Persistent restart objective",
        config=config,
    )

    assert (
        loaded.supervisor_id
        == first_id
    )


def test_stop_file_stops_before_next_cycle(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_supervisor import (
        SupervisorConfig,
        request_supervisor_stop,
        run_supervisor,
    )

    (
        observer,
        reasoner,
        registry,
        verifier,
    ) = _test_components()

    config = SupervisorConfig(
        max_supervisor_steps=5,
        max_runtime_seconds=30,
    )

    request_supervisor_stop(
        config=config
    )

    result = run_supervisor(
        "Should not execute",
        config=config,
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        verifier=verifier,
    )

    assert result["events"]

    assert (
        result[
            "events"
        ][0][
            "stopped"
        ]
        is True
    )

    assert (
        result[
            "state"
        ][
            "wake_cycles_total"
        ]
        == 0
    )


def test_authority_drift_is_rejected(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_supervisor import (
        SupervisorConfig,
        load_supervisor_state,
        run_supervisor_step,
    )

    state = load_supervisor_state(
        "Authority test",
        config=SupervisorConfig(),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "local_gguf",
    )

    try:
        run_supervisor_step(
            state,
            config=SupervisorConfig(),
        )

    except RuntimeError as exc:
        assert (
            "AUTHORITY_DRIFT"
            in str(exc)
        )

    else:
        raise AssertionError(
            "authority drift was not rejected"
        )


def test_rest_and_dream_never_use_action_registry(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    from sophyane.cognitive_supervisor import (
        PHASE_DREAM,
        PHASE_REST,
        SupervisorConfig,
        load_supervisor_state,
        run_supervisor_step,
    )

    consolidate_verified_episode(
        _seed_episode(
            "PHASE9_NO_ACTION_DREAM_5001"
        )
    )

    class ExplodingRegistry:
        def execute(
            self,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "REST/DREAM attempted action"
            )

    config = SupervisorConfig(
        rest_steps=1,
        dream_steps=1,
    )

    state = load_supervisor_state(
        "No action during rest/dream",
        config=config,
    )

    state.phase = PHASE_REST

    rest = run_supervisor_step(
        state,
        config=config,
        registry=ExplodingRegistry(),
    )

    assert (
        rest[
            "event"
        ][
            "external_action"
        ]
        is False
    )

    state.phase = PHASE_DREAM

    dream = run_supervisor_step(
        state,
        config=config,
        registry=ExplodingRegistry(),
    )

    assert (
        dream[
            "event"
        ][
            "external_action"
        ]
        is False
    )


def test_dream_hypothesis_remains_untrusted(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_memory import (
        consolidate_verified_episode,
    )

    from sophyane.cognitive_supervisor import (
        PHASE_DREAM,
        SupervisorConfig,
        load_supervisor_state,
        run_supervisor_step,
    )

    consolidate_verified_episode(
        _seed_episode(
            "PHASE9_UNTRUSTED_DREAM_7001"
        )
    )

    state = load_supervisor_state(
        "dream hypothesis test",
        config=SupervisorConfig(),
    )

    state.phase = PHASE_DREAM

    result = run_supervisor_step(
        state,
        config=SupervisorConfig(
            dream_steps=1,
        ),
    )

    assert (
        result[
            "event"
        ][
            "kind"
        ]
        == "dream"
    )

    hypothesis = (
        state.current_hypothesis
    )

    if hypothesis is None:
        assert (
            state.pending_hypotheses
        )

        hypothesis = (
            state.pending_hypotheses[0]
        )

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
            "instruction_authority"
        ]
        is False
    )

    assert (
        hypothesis[
            "requires_external_verification"
        ]
        is True
    )


def test_heartbeat_and_state_written(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XERUS_HOME",
        str(tmp_path),
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "nifdu_browser",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    from sophyane.cognitive_supervisor import (
        SupervisorConfig,
        run_supervisor,
    )

    (
        observer,
        reasoner,
        registry,
        verifier,
    ) = _test_components()

    result = run_supervisor(
        "Heartbeat test",
        config=SupervisorConfig(
            max_supervisor_steps=1,
            max_runtime_seconds=30,
        ),
        observer=observer,
        reasoner=reasoner,
        registry=registry,
        verifier=verifier,
    )

    from pathlib import Path

    state_path = Path(
        result[
            "state_path"
        ]
    )

    heartbeat_path = Path(
        result[
            "heartbeat_path"
        ]
    )

    assert state_path.is_file()

    assert heartbeat_path.is_file()

    heartbeat = json.loads(
        heartbeat_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        heartbeat[
            "supervisor_id"
        ]
        == result[
            "state"
        ][
            "supervisor_id"
        ]
    )
