from __future__ import annotations

from types import SimpleNamespace


def test_execution_experience_persists_to_xerus(
    monkeypatch,
    tmp_path,
):
    import sophyane.durable_memory as durable
    import sophyane.episodic_memory as episodic
    import sophyane.sli_learner as learner

    from sophyane.execution_experience import (
        record_execution_experience,
    )

    captured = []

    def fake_learn_execution(
        **kwargs,
    ):
        return {
            "provenance": dict(
                kwargs["provenance"]
            )
        }

    monkeypatch.setattr(
        learner,
        "learn_execution",
        fake_learn_execution,
    )

    monkeypatch.setattr(
        episodic,
        "persist_execution_episode",
        lambda event: (
            captured.append(
                dict(event)
            )
            or {
                "ok": True,
            }
        ),
    )

    monkeypatch.setattr(
        durable,
        "remember_verified_execution",
        lambda event: None,
    )

    result = SimpleNamespace(
        handled=True,
        ok=True,
        capability="coding",
        output="completed",
        evidence={
            "verification_state": "verified",
            "verification_evidence": [
                {
                    "validator": "test",
                    "passed": True,
                }
            ],
        },
        started_at=1.0,
        finished_at=2.0,
    )

    event = record_execution_experience(
        request_text=(
            "build verified memory"
        ),
        workspace=tmp_path,
        result=result,
        metadata={},
        workspace_before={},
    )

    assert event is not None
    assert len(captured) == 1

    stored = captured[0]

    assert stored["accepted"] is True
    assert (
        stored["verification_state"]
        == "verified"
    )
