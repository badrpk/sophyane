from types import SimpleNamespace


def test_session_authority_reads_selected_mode(
    monkeypatch,
):
    from sophyane.execution_experience import (
        session_authority,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "codex_cli",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "codex-default",
    )

    authority = (
        session_authority()
    )

    assert (
        authority[
            "session_mode"
        ]
        == "codex_cli"
    )

    assert (
        authority[
            "session_provider"
        ]
        == "codex_cli"
    )


def test_unverified_success_is_not_trusted_memory(
    monkeypatch,
    tmp_path,
):
    import sophyane.sli_learner as learner

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

    from sophyane.execution_experience import (
        record_execution_experience,
    )

    result = SimpleNamespace(
        handled=True,
        ok=True,
        capability="reasoning.test",
        output="answer",
        evidence={},
        started_at=1.0,
        finished_at=2.0,
    )

    event = (
        record_execution_experience(
            request_text="test request",
            workspace=tmp_path,
            result=result,
            metadata={},
            workspace_before={},
        )
    )

    assert event is not None

    provenance = (
        captured[
            "provenance"
        ]
    )

    assert (
        provenance[
            "accepted"
        ]
        is False
    )

    assert (
        provenance[
            "verification_state"
        ]
        == "unverified"
    )

    assert (
        captured[
            "status"
        ]
        == "succeeded"
    )


def test_verified_success_becomes_accepted_experience(
    monkeypatch,
    tmp_path,
):
    import sophyane.sli_learner as learner

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

    from sophyane.execution_experience import (
        record_execution_experience,
    )

    result = SimpleNamespace(
        handled=True,
        ok=True,
        capability="verification.test",
        output="verified",
        evidence={
            "data": {
                "byte_for_byte_verified": True,
            },
            "executed_repository": "veyron",
        },
        started_at=1.0,
        finished_at=2.0,
    )

    event = (
        record_execution_experience(
            request_text="verified test",
            workspace=tmp_path,
            result=result,
            metadata={
                "badrpk_capability_plan": {
                    "repositories": [
                        {
                            "repository": "veyron",
                            "available": True,
                            "score": 1.0,
                        }
                    ]
                }
            },
            workspace_before={},
        )
    )

    assert event is not None

    provenance = (
        captured[
            "provenance"
        ]
    )

    assert (
        provenance[
            "accepted"
        ]
        is True
    )

    assert (
        provenance[
            "repository_identity"
        ]
        == "badrpk/veyron"
    )


def test_ranked_candidate_does_not_receive_false_execution_credit(
    monkeypatch,
    tmp_path,
):
    import sophyane.sli_learner as learner

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

    from sophyane.execution_experience import (
        record_execution_experience,
    )

    result = SimpleNamespace(
        handled=True,
        ok=True,
        capability="reasoning.test",
        output="answer",
        evidence={},
        started_at=1.0,
        finished_at=2.0,
    )

    record_execution_experience(
        request_text="test",
        workspace=tmp_path,
        result=result,
        metadata={
            "badrpk_capability_plan": {
                "repositories": [
                    {
                        "repository": "neuron",
                        "available": True,
                        "score": 1.0,
                    }
                ]
            }
        },
        workspace_before={},
    )

    assert (
        captured[
            "provenance"
        ][
            "repository_identity"
        ]
        is None
    )


def test_execution_evidence_can_credit_repository(
    monkeypatch,
    tmp_path,
):
    import sophyane.sli_learner as learner

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

    from sophyane.execution_experience import (
        record_execution_experience,
    )

    result = SimpleNamespace(
        handled=True,
        ok=True,
        capability="memory.peer",
        output="recalled",
        evidence={
            "executed_repository": "xerus",
        },
        started_at=1.0,
        finished_at=2.0,
    )

    record_execution_experience(
        request_text="recall memory",
        workspace=tmp_path,
        result=result,
        metadata={},
        workspace_before={},
    )

    assert (
        captured[
            "provenance"
        ][
            "repository_identity"
        ]
        == "badrpk/xerus"
    )
