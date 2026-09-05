from __future__ import annotations

import time
from pathlib import Path

from sophyane.race_adapters import (
    ProgressProposal,
    proposal_worker,
)
from sophyane.race_orchestrator import (
    _extract_json_object,
    _llm_proposal,
    run_adaptive_race,
)


def test_extract_json_object():
    assert (
        _extract_json_object(
            '{"action":{"type":"respond","message":"ok"}}'
        )
        == {
            "action": {
                "type": "respond",
                "message": "ok",
            }
        }
    )

    assert (
        _extract_json_object(
            'prefix {"action":{"type":"respond","message":"ok"}} suffix'
        )
        is not None
    )


def test_llm_valid_action_scores_above_threshold():
    proposal = _llm_proposal(
        engine="local",
        text=(
            '{"action":{"type":"respond",'
            '"message":"done"}}'
        ),
    )

    assert proposal.kind == "action"
    assert proposal.confidence >= 0.80
    assert proposal.requires_write is False

    assert (
        proposal.payload[
            "action"
        ][
            "type"
        ]
        == "respond"
    )


def test_llm_text_falls_back_to_plan():
    proposal = _llm_proposal(
        engine="cloud",
        text="Inspect the failing test first.",
    )

    assert proposal.kind == "plan"
    assert proposal.confidence >= 0.55
    assert proposal.requires_write is False


def test_real_orchestrator_races_injected_workers(
    tmp_path: Path,
):
    request = "repair the failing tests"

    def sli():
        time.sleep(0.02)

        return ProgressProposal(
            engine="sli",
            payload={
                "route": "harness_execution",
            },
            kind="acquisition",
            confidence=0.82,
            evidence=(
                "SLI route selected",
            ),
            requires_write=False,
        )

    def local():
        time.sleep(0.20)

        return ProgressProposal(
            engine="local",
            payload={
                "action": {
                    "type": "run",
                    "command": "pytest -q",
                }
            },
            kind="action",
            confidence=0.90,
            evidence=(
                "normalized local action",
            ),
            requires_write=False,
        )

    def cloud():
        time.sleep(0.30)

        return ProgressProposal(
            engine="cloud",
            payload={
                "action": {
                    "type": "run",
                    "command": "pytest -q",
                }
            },
            kind="action",
            confidence=0.95,
            evidence=(
                "normalized cloud action",
            ),
            requires_write=False,
        )

    result = run_adaptive_race(
        request,
        workspace=tmp_path,
        config={},
        timeout=1.0,
        winner_grace_seconds=0.01,
        workers={
            "sli": proposal_worker(
                "sli",
                sli,
            ),
            "local": proposal_worker(
                "local",
                local,
            ),
            "cloud": proposal_worker(
                "cloud",
                cloud,
            ),
        },
    )

    assert result.ok
    assert result.winner is not None

    assert (
        result.winner.worker
        == "sli"
    )


def test_invalid_fast_worker_cannot_beat_valid_worker(
    tmp_path: Path,
):
    def bad():
        return ProgressProposal(
            engine="local",
            payload=None,
            kind="action",
            confidence=1.0,
            evidence=(),
            requires_write=False,
        )

    def good():
        time.sleep(0.02)

        return ProgressProposal(
            engine="cloud",
            payload={
                "plan": "inspect traceback",
            },
            kind="plan",
            confidence=0.80,
            evidence=(
                "valid plan",
            ),
            requires_write=False,
        )

    result = run_adaptive_race(
        "repair",
        workspace=tmp_path,
        config={},
        timeout=1.0,
        workers={
            "local": proposal_worker(
                "local",
                bad,
            ),
            "cloud": proposal_worker(
                "cloud",
                good,
            ),
        },
    )

    assert result.winner is not None
    assert result.winner.worker == "cloud"


def test_worker_failure_does_not_stop_race(
    tmp_path: Path,
):
    def cloud():
        raise RuntimeError(
            "429 quota exceeded"
        )

    def local():
        time.sleep(0.02)

        return ProgressProposal(
            engine="local",
            payload={
                "plan": "run tests",
            },
            kind="plan",
            confidence=0.80,
            evidence=(
                "local survived",
            ),
            requires_write=False,
        )

    result = run_adaptive_race(
        "repair",
        workspace=tmp_path,
        config={},
        timeout=1.0,
        workers={
            "cloud": proposal_worker(
                "cloud",
                cloud,
            ),
            "local": proposal_worker(
                "local",
                local,
            ),
        },
    )

    assert result.winner is not None
    assert result.winner.worker == "local"

    assert (
        "cloud"
        in result.race_result.errors
    )


def test_authoritative_workspace_not_mutated_by_race(
    tmp_path: Path,
):
    source = (
        tmp_path
        / "production.py"
    )

    source.write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    def worker():
        return ProgressProposal(
            engine="local",
            payload={
                "action": {
                    "type": "write_file",
                    "path": "production.py",
                    "content": "VALUE = 2\n",
                }
            },
            kind="action",
            confidence=0.90,
            evidence=(
                "valid write proposal",
            ),
            requires_write=False,
        )

    result = run_adaptive_race(
        "change VALUE",
        workspace=tmp_path,
        config={},
        timeout=1.0,
        workers={
            "local": proposal_worker(
                "local",
                worker,
            ),
        },
    )

    assert result.ok

    assert (
        source.read_text(
            encoding="utf-8"
        )
        == "VALUE = 1\n"
    )


# SOPHYANE_TEST_DIRECT_ANSWER_COMPLETION_V1
def test_answer_completion_accepts_generic_nonempty_answer():
    import sophyane.race_orchestrator as orchestrator

    judgement = orchestrator._answer_completion_judgement(
        request=(
            "Explain why cooperative speculative races "
            "can improve execution."
        ),
        answer=(
            "They allow independent workers to explore candidate "
            "actions concurrently and promote the strongest result."
        ),
    )

    assert judgement["complete"] is True
    assert judgement["score"] == 0.72
    assert judgement["missing"] == ()


def test_answer_completion_rejects_requested_code_without_fence():
    import sophyane.race_orchestrator as orchestrator

    judgement = orchestrator._answer_completion_judgement(
        request=(
            "Provide a code example in Python for "
            "deterministic replay."
        ),
        answer=(
            "Python can implement deterministic replay by recording "
            "events and replaying them in the same order."
        ),
    )

    assert judgement["complete"] is False
    assert judgement["score"] == 0.54
    assert "requested code artifact" in judgement["missing"]

    assert (
        "requested language: python"
        not in judgement["missing"]
    )

    assert (
        "requested capability: deterministic replay"
        not in judgement["missing"]
    )


def test_answer_completion_requires_each_requested_language():
    import sophyane.race_orchestrator as orchestrator

    judgement = orchestrator._answer_completion_judgement(
        request=(
            "Provide a code example in Python and C++."
        ),
        answer=(
            "Python implementation:\n"
            "```python\n"
            "print('ok')\n"
            "```"
        ),
    )

    assert judgement["complete"] is False
    assert judgement["score"] == 0.54

    assert (
        "requested language: c++"
        in judgement["missing"]
    )

    assert (
        "requested language: python"
        not in judgement["missing"]
    )

    assert (
        "requested code artifact"
        not in judgement["missing"]
    )


def test_answer_completion_requires_replay_demonstration():
    import sophyane.race_orchestrator as orchestrator

    judgement = orchestrator._answer_completion_judgement(
        request=(
            "Show how to replay a failed execution path."
        ),
        answer=(
            "Record execution events in an append-only journal "
            "so the history can be inspected later."
        ),
    )

    assert judgement["complete"] is False
    assert judgement["score"] == 0.54

    assert (
        "requested replay demonstration"
        in judgement["missing"]
    )


def test_answer_completion_accepts_requested_replay_demonstration():
    import sophyane.race_orchestrator as orchestrator

    judgement = orchestrator._answer_completion_judgement(
        request=(
            "Show how to replay a failed execution path."
        ),
        answer=(
            "Replay the failed execution by loading its journal "
            "and applying the recorded schedule in order."
        ),
    )

    assert judgement["complete"] is True
    assert judgement["score"] == 0.72
    assert judgement["missing"] == ()

    assert (
        "requested replay demonstration addressed"
        in judgement["evidence"]
    )


def test_provider_answer_missing_deliverable_stays_below_race_threshold(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as orchestrator

    class Provider:
        def generate(
            self,
            user_prompt,
            system_prompt,
        ):
            return (
                "Python can provide deterministic replay by "
                "recording execution events and replaying them."
            )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda **kwargs: Provider(),
    )

    producer = orchestrator.make_provider_producer(
        engine="local",
        provider_id="test-provider",
        request=(
            "Provide a complete implementation in Python "
            "with deterministic replay."
        ),
        workspace=tmp_path,
        config={},
        mode="answer",
    )

    proposal = producer()

    assert proposal.engine == "local"
    assert proposal.kind == "answer"
    assert proposal.payload["answer"]

    # _llm_proposal() initially gives a non-empty answer 0.60.
    # The completion gate must replace it with the losing ceiling.
    assert proposal.confidence == 0.54
    assert proposal.confidence < 0.55

    assert any(
        evidence.startswith(
            "missing answer requirements:"
        )
        for evidence in proposal.evidence
    )

    assert any(
        "requested code artifact" in evidence
        for evidence in proposal.evidence
    )


def test_provider_complete_answer_receives_completion_score(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as orchestrator

    class Provider:
        def generate(
            self,
            user_prompt,
            system_prompt,
        ):
            return (
                "Python deterministic replay implementation:\n"
                "```python\n"
                "def replay(journal):\n"
                "    for event in journal:\n"
                "        apply(event)\n"
                "```\n"
                "The journal is replayed deterministically."
            )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda **kwargs: Provider(),
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="test-provider",
        request=(
            "Provide a complete implementation in Python "
            "with deterministic replay."
        ),
        workspace=tmp_path,
        config={},
        mode="answer",
    )

    proposal = producer()

    assert proposal.engine == "cloud"
    assert proposal.kind == "answer"
    assert proposal.confidence == 0.72
    assert proposal.confidence >= 0.55

    assert (
        "requested code artifact present"
        in proposal.evidence
    )

    assert (
        "requested language present: python"
        in proposal.evidence
    )

    assert (
        "requested capability addressed: deterministic replay"
        in proposal.evidence
    )


def test_mode1_provider_quota_fails_over_without_changing_request(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator
    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name
        def generate(self, prompt, system):
            calls.append((self.name, prompt, system))
            if self.name == "agy":
                raise RuntimeError("AGY quota exhausted")
            return "answer: preserved objective"

    monkeypatch.setattr(orchestrator, "_single_provider", lambda *, provider_id, config: Provider(provider_id))
    producer = orchestrator.make_provider_producer(
        engine="cloud", provider_id="agy", request="answer preserved objective",
        workspace=tmp_path, config={"provider_fallback_order": ["gemini"]}, mode="answer",
    )
    result = producer()
    assert result.payload["answer"] == "answer: preserved objective"
    assert [item[0] for item in calls] == ["agy", "gemini"]
    assert calls[0][1] == calls[1][1]
    assert calls[0][2] == calls[1][2]


def test_mode1_successful_provider_does_not_fallback(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator
    calls = []

    class Provider:
        def generate(self, prompt, system):
            calls.append(prompt)
            return "answer: first choice"

    monkeypatch.setattr(orchestrator, "_single_provider", lambda **kwargs: Provider())
    producer = orchestrator.make_provider_producer(
        engine="cloud", provider_id="agy", request="answer first choice",
        workspace=tmp_path, config={"provider_fallback_order": ["gemini"]}, mode="answer",
    )
    assert producer().payload["answer"] == "answer: first choice"
    assert len(calls) == 1


def test_mode1_nonrecoverable_safety_failure_is_not_bypassed(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator
    calls = []

    class Provider:
        def generate(self, prompt, system):
            calls.append(prompt)
            raise RuntimeError("safety approval required")

    monkeypatch.setattr(orchestrator, "_single_provider", lambda **kwargs: Provider())
    producer = orchestrator.make_provider_producer(
        engine="cloud", provider_id="agy", request="answer gated",
        workspace=tmp_path, config={"provider_fallback_order": ["gemini"]}, mode="answer",
    )
    import pytest
    with pytest.raises(RuntimeError, match="safety"):
        producer()
    assert len(calls) == 1

def test_mode1_unusable_execution_proposal_fails_over_without_changing_objective(
    monkeypatch,
    tmp_path,
):
    import json
    import sophyane.race_orchestrator as orchestrator

    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def generate(self, prompt, system):
            calls.append(
                (self.name, prompt, system)
            )

            if self.name == "gemini":
                # Transport succeeded, but plain prose is only a plan in
                # execution mode and therefore cannot satisfy the request.
                return "I would create the Snake game."

            return json.dumps({
                "action": "write_file",
                "path": "snake.html",
                "content": "<!doctype html><title>Snake</title>",
            })

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda *,
        provider_id,
        config: Provider(provider_id),
    )

    monkeypatch.setattr(
        orchestrator,
        "_semantic_proposal_relevance",
        lambda **kwargs: {
            "available": True,
            "relevant": True,
            "score": 0.82,
            "reason": "matches requested Snake artifact",
        },
    )

    request = (
        "Create a playable Snake game and save it as HTML."
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request=request,
        workspace=tmp_path,
        config={
            "provider_fallback_order": [
                "codex_cli",
            ],
        },
        mode="execution",
    )

    result = producer()

    assert result.kind == "action"
    assert result.payload["action"]["type"] == "write_file"
    assert [
        item[0]
        for item in calls
    ] == [
        "gemini",
        "codex_cli",
    ]

    # The exact same objective-derived prompts cross the fallback boundary.
    assert calls[0][1] == calls[1][1]
    assert calls[0][2] == calls[1][2]


def test_mode1_valid_execution_first_choice_does_not_fallback(
    monkeypatch,
    tmp_path,
):
    import json
    import sophyane.race_orchestrator as orchestrator

    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def generate(self, prompt, system):
            calls.append(self.name)
            return json.dumps({
                "action": "write_file",
                "path": "game.html",
                "content": "<!doctype html><title>Game</title>",
            })

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda *,
        provider_id,
        config: Provider(provider_id),
    )

    monkeypatch.setattr(
        orchestrator,
        "_semantic_proposal_relevance",
        lambda **kwargs: {
            "available": True,
            "relevant": True,
            "score": 0.82,
            "reason": "relevant",
        },
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request="Create game.html",
        workspace=tmp_path,
        config={
            "provider_fallback_order": [
                "codex_cli",
            ],
        },
        mode="execution",
    )

    assert producer().kind == "action"
    assert calls == ["gemini"]


def test_mode1_incomplete_answer_fails_over_to_complete_answer(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as orchestrator

    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def generate(self, prompt, system):
            calls.append(
                (self.name, prompt, system)
            )

            if self.name == "agy":
                return "Here is an idea."

            return (
                "```python\n"
                "print('deterministic replay')\n"
                "```\n"
                "deterministic replay"
            )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda *,
        provider_id,
        config: Provider(provider_id),
    )

    request = (
        "Give Python code and demonstrate deterministic replay."
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="agy",
        request=request,
        workspace=tmp_path,
        config={
            "provider_fallback_order": [
                "gemini",
            ],
        },
        mode="answer",
    )

    result = producer()

    assert result.kind == "answer"
    assert result.confidence >= 0.55
    assert [
        item[0]
        for item in calls
    ] == [
        "agy",
        "gemini",
    ]
    assert calls[0][1] == calls[1][1]
    assert calls[0][2] == calls[1][2]


def test_mode1_unusable_proposal_does_not_relax_safety_on_next_route(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as orchestrator
    import pytest

    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        def generate(self, prompt, system):
            calls.append(self.name)

            if self.name == "gemini":
                return "plain unusable execution plan"

            raise RuntimeError(
                "safety approval required"
            )

    monkeypatch.setattr(
        orchestrator,
        "_single_provider",
        lambda *,
        provider_id,
        config: Provider(provider_id),
    )

    producer = orchestrator.make_provider_producer(
        engine="cloud",
        provider_id="gemini",
        request="perform gated action",
        workspace=tmp_path,
        config={
            "provider_fallback_order": [
                "codex_cli",
                "agy",
            ],
        },
        mode="execution",
    )

    with pytest.raises(
        RuntimeError,
        match="safety",
    ):
        producer()

    # Safety remains terminal; AGY is never tried.
    assert calls == [
        "gemini",
        "codex_cli",
    ]


def test_mode1_does_not_register_sli_for_grounding_requests(tmp_path):
    import sophyane.race_orchestrator as orchestrator
    assert "sli" not in orchestrator.build_real_workers(
        request="research this topic using memory and internet",
        workspace=tmp_path, config={}, progress=lambda _: None,
    )
    assert "sli" not in orchestrator.build_real_workers(
        request="answer hello",
        workspace=tmp_path, config={}, progress=lambda _: None,
    )


def test_mode1_emits_objective_and_source_diagnostics(tmp_path):
    import hashlib
    import sophyane.race_orchestrator as orchestrator
    events = []
    orchestrator.run_adaptive_race(
        "answer a complete response",
        workspace=tmp_path, config={}, workers={},
        progress=events.append, timeout=0.1,
    )
    assert any(event.startswith("ORIGINAL_OBJECTIVE_HASH=") for event in events)
    assert any(event.startswith("ELIGIBLE_SOURCES=") for event in events)
    assert any(event.startswith("STARTED_SOURCES=") for event in events)
    expected = hashlib.sha256(b"answer a complete response").hexdigest()
    assert f"ORIGINAL_OBJECTIVE_HASH={expected}" in events


def test_mode1_builds_independent_capability_workers(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator
    monkeypatch.setattr(orchestrator, "_mode1_provider_available", lambda provider, config: provider in {"gemini", "codex_cli", "agy", "nifdu_browser"})
    workers = orchestrator.build_real_workers(
        request="research with memory and internet",
        workspace=tmp_path,
        config={"provider": "gemini", "provider_workers": ["codex_cli", "agy", "nifdu_browser"]},
        progress=lambda _: None,
    )
    assert {"local", "api:gemini", "harness:codex_cli", "harness:agy", "browser:nifdu_browser"}.issubset(workers)
    assert "sli" not in workers
    assert "cloud" not in workers


def test_mode1_uses_startup_readiness_inventory(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator
    inventory = {
        "gemini": ("Google Gemini", "external_api", "ready"),
        "codex_cli": ("Codex CLI", "external_harness", "ready"),
        "agy": ("Antigravity (AGY)", "external_harness", "ready"),
        "nifdu_browser": ("ChatGPT Browser", "external_browser", "ready"),
    }
    monkeypatch.setattr(orchestrator, "_mode1_sli_applies", lambda request: True)
    monkeypatch.setattr("sophyane.startup_policy.intelligence_provider_inventory", lambda config=None: inventory)
    workers = orchestrator.build_real_workers(
        request="implement a grounded repository change",
        workspace=tmp_path,
        config={"provider": "gemini"},
        progress=lambda _: None,
    )
    assert {"local", "api:gemini", "harness:codex_cli", "harness:agy", "browser:nifdu_browser"} <= set(workers)
    assert "sli" not in workers


def test_mode1_verified_history_prefers_eligible_provider(monkeypatch, tmp_path):
    import sophyane.race_orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "_mode1_sli_applies", lambda request: False)
    monkeypatch.setattr(orchestrator, "_mode1_provider_available", lambda provider, config: provider == "gemini")
    monkeypatch.setattr(
        "sophyane.sli_learner.read_verified_history",
        lambda **kwargs: [{
            "event_key": "event-1",
            "trace_id": "trace-1",
            "accepted": True,
            "status": "succeeded",
            "verification_state": "verified",
            "capability_class": "external_api",
            "provider_identity": "gemini",
            "repository_identity": None,
        }],
    )

    def producer(**kwargs):
        return lambda: ProgressProposal(
            engine=kwargs["engine"],
            payload={"action": {"type": "respond", "message": kwargs["engine"]}},
            kind="action",
            confidence=0.70,
            evidence=("current objective fit",),
        )

    monkeypatch.setattr(orchestrator, "make_provider_producer", producer)
    result = orchestrator.run_adaptive_race(
        "implement a bounded repository change",
        workspace=tmp_path,
        config={"provider": "gemini"},
        timeout=1.0,
    )
    assert result.winner.worker == "api:gemini"
    assert result.winner.score > 0.70


def test_mode1_history_cannot_revive_ineligible_proposal(monkeypatch):
    import sophyane.race_orchestrator as orchestrator
    proposal = ProgressProposal(
        engine="local", payload={"action": {"type": "respond"}},
        kind="action", confidence=0.54, evidence=("weak",),
    )
    monkeypatch.setattr(
        orchestrator, "_mode1_verified_history_bonus",
        lambda **kwargs: orchestrator._MODE1_HISTORY_BONUS_CAP,
    )
    unchanged = orchestrator._mode1_apply_history_preference(
        proposal, request="same capability", worker_id="local", provider_id="local_gguf",
    )
    assert unchanged.confidence == 0.54


def test_mode1_history_bonus_is_bounded_and_deduplicated(monkeypatch):
    import sophyane.race_orchestrator as orchestrator
    rows = [
        {"event_key": "same", "accepted": True, "verification_state": "verified", "status": "succeeded", "provider_identity": "gemini"},
    ] * 100
    monkeypatch.setattr("sophyane.sli_learner.read_verified_history", lambda **kwargs: rows)
    bonus = orchestrator._mode1_verified_history_bonus(
        request="same capability", worker_id="api:gemini", provider_id="gemini",
    )
    assert bonus == 0.04
    assert bonus <= orchestrator._MODE1_HISTORY_BONUS_CAP


def test_mode1_scoped_recurrent_principle_prefers_matching_worker(monkeypatch, tmp_path):
    import json
    import sophyane.race_orchestrator as orchestrator
    principle_path = tmp_path / ".sophyane-evolution" / "principles.json"
    principle_path.parent.mkdir(parents=True)
    principle_path.write_text(json.dumps({"principles": {"p": {
        "id": "p", "status": "recurrent", "origin": "verified_execution",
        "component": "external_api", "capabilities": ["external_api"],
        "repository_identity": None,
    }}}))
    monkeypatch.setattr(orchestrator, "_mode1_verified_history_bonus", lambda **kwargs: 0.0)
    proposal = ProgressProposal(engine="api:gemini", payload={"action": {"type": "respond"}}, kind="action", confidence=0.70, evidence=("fit",))
    adjusted = orchestrator._mode1_apply_history_preference(proposal, request="task", worker_id="api:gemini", provider_id="gemini", principles_root=tmp_path)
    assert adjusted.confidence == 0.72


def test_mode1_principle_and_history_share_total_advisory_cap(monkeypatch, tmp_path):
    import json
    import sophyane.race_orchestrator as orchestrator
    principle_path = tmp_path / ".sophyane-evolution" / "principles.json"
    principle_path.parent.mkdir(parents=True)
    principle_path.write_text(json.dumps({"principles": {str(i): {
        "id": str(i), "status": "recurrent", "origin": "verified_execution",
        "component": "external_api", "capabilities": ["external_api"],
    } for i in range(10)}}))
    monkeypatch.setattr(orchestrator, "_mode1_verified_history_bonus", lambda **kwargs: 0.10)
    proposal = ProgressProposal(engine="api:gemini", payload={"action": {"type": "respond"}}, kind="action", confidence=0.70, evidence=("fit",))
    adjusted = orchestrator._mode1_apply_history_preference(proposal, request="task", worker_id="api:gemini", provider_id="gemini", principles_root=tmp_path)
    assert abs(adjusted.confidence - 0.80) < 1e-9
