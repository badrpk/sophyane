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


def test_failed_sli_report_cannot_win_adaptive_race(
    monkeypatch,
    tmp_path,
):
    """
    A failed SLI graph may provide diagnostics, route metadata, and a
    report, but it must remain below the race winner threshold.
    """
    import sophyane.race_orchestrator as orchestrator

    class FailedState:
        route = "software_artifact"
        success = False
        promoted = False
        report = (
            "SLI-only mode: code-memory assembly did not meet "
            "the artifact quality threshold."
        )

    monkeypatch.setattr(
        orchestrator,
        "_copy_shadow_workspace",
        lambda workspace, *, engine: tmp_path,
    )

    monkeypatch.setattr(
        orchestrator,
        "_file_manifest",
        lambda root: {},
    )

    monkeypatch.setattr(
        orchestrator,
        "_shadow_changes",
        lambda before, shadow: (),
    )

    import sophyane.sli_graph as sli_graph

    monkeypatch.setattr(
        sli_graph,
        "run_sli_graph",
        lambda *args, **kwargs: FailedState(),
    )

    import sophyane.unified_execution_kernel as kernel

    class NotHandled:
        handled = False

    monkeypatch.setattr(
        kernel,
        "execute_request",
        lambda *args, **kwargs: NotHandled(),
    )

    producer = orchestrator.make_sli_producer(
        request="build deterministic replay support",
        workspace=tmp_path,
    )

    proposal = producer()

    assert proposal.engine == "sli"
    assert proposal.payload["success"] is False
    assert proposal.payload["promoted"] is False
    assert proposal.confidence < 0.55


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
