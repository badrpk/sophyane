from __future__ import annotations

from pathlib import Path

import sophyane.tui_v2 as tui
import sophyane.v13_cli as cli
from sophyane.race_adapters import ProgressProposal


DEPLOY_REQUEST = (
    "Deploy a data-parsing agent to ingest unstructured or "
    "semi-structured data feeds, normalize them against a strict "
    "target schema, and output clean, verified transactional records."
)

CHAT_REQUEST = (
    "Explain how a data-parsing agent should normalize messy "
    "vendor data against a strict schema."
)


def test_deploy_request_is_execution_intent():
    """
    The request that failed in the live acceptance must not be
    treated as ordinary direct-answer chat.
    """
    assert tui._execution_requested(DEPLOY_REQUEST) is True


def test_explanation_request_is_not_execution_intent():
    assert tui._execution_requested(CHAT_REQUEST) is False


def test_race_protocol_accepts_answer_kind():
    from sophyane.race_adapters import validate_progress_proposal

    proposal = ProgressProposal(
        engine="cloud",
        payload={"answer": "Direct answer"},
        kind="answer",
        confidence=0.90,
        evidence=("provider produced direct answer",),
        requires_write=False,
    )

    valid, score, evidence = validate_progress_proposal(
        "cloud",
        proposal,
    )

    assert valid is True
    assert score >= 0.55
    assert evidence


def test_nonexecution_bridge_does_not_enter_apply_verify(
    monkeypatch,
    tmp_path: Path,
):
    """
    A direct-answer request must never enter the mutation/repair loop.
    """

    import sophyane.race_execution as race_execution
    import sophyane.race_orchestrator as race_orchestrator

    def forbidden_apply_verify(*args, **kwargs):
        raise AssertionError(
            "non-execution request entered apply/verify"
        )

    class FakeRaceResult:
        def __init__(self):
            self.winner = type(
                "Winner",
                (),
                {
                    "worker": "cloud",
                    "value": ProgressProposal(
                        engine="cloud",
                        payload={
                            "answer": (
                                "Normalize each input into the "
                                "target transactional schema."
                            )
                        },
                        kind="answer",
                        confidence=0.90,
                        evidence=("direct answer",),
                        requires_write=False,
                    ),
                },
            )()

    class FakeRealRaceResult:
        ok = True

        def __init__(self):
            self.race_result = FakeRaceResult()

        @property
        def winner(self):
            return self.race_result.winner

    def fake_race(*args, **kwargs):
        return FakeRealRaceResult()

    monkeypatch.setattr(
        race_execution,
        "run_race_apply_verify",
        forbidden_apply_verify,
    )
    monkeypatch.setattr(
        race_orchestrator,
        "run_adaptive_race",
        fake_race,
    )

    result = cli._run_adaptive_race_request(
        CHAT_REQUEST,
        workspace=tmp_path,
        config={},
    )

    assert result["ok"] is True

    answer = (
        result.get("answer")
        or result.get("message")
        or result.get("response")
    )

    assert answer
    assert "Normalize" in answer


def test_execution_bridge_still_enters_apply_verify(
    monkeypatch,
    tmp_path: Path,
):
    """
    Fixing direct answers must not weaken execution authority.
    """

    import sophyane.race_execution as race_execution

    calls = []

    class FakeExecutionResult:
        ok = True
        winner = "local"
        attempts = 1
        applied = ["write_file"]
        verifications = ["pytest: pass"]
        error = None

    def fake_apply_verify(request, **kwargs):
        calls.append((request, kwargs))
        return FakeExecutionResult()

    monkeypatch.setattr(
        race_execution,
        "run_race_apply_verify",
        fake_apply_verify,
    )

    result = cli._run_adaptive_race_request(
        DEPLOY_REQUEST,
        workspace=tmp_path,
        config={},
    )

    assert result["ok"] is True
    assert calls
    assert calls[0][0] == DEPLOY_REQUEST
    assert result["applied"] == ["write_file"]


def test_plain_provider_text_can_be_represented_as_answer():
    """
    Desired V3 contract:
    direct user-facing provider output is an answer, not an
    executable repair plan.

    This test intentionally describes the target behavior and may
    be RED until the producer gains explicit answer mode.
    """
    from sophyane.race_orchestrator import _llm_proposal

    proposal = _llm_proposal(
        engine="cloud",
        text="CSV is row-oriented while JSON is hierarchical.",
        mode="answer",
    )

    assert proposal.kind == "answer"
    assert isinstance(proposal.payload, dict)
    assert (
        proposal.payload.get("answer")
        or proposal.payload.get("message")
    )


def test_execution_json_remains_action():
    from sophyane.race_orchestrator import _llm_proposal

    proposal = _llm_proposal(
        engine="local",
        text=(
            '{"action":{"type":"run",'
            '"command":"pytest -q"}}'
        ),
    )

    assert proposal.kind == "action"
    assert proposal.payload["action"]["type"] == "run"


# SOPHYANE_TEST_AUTO_RESPONSE_CODE_BOUNDARY_V1
def test_python_cpp_code_snippet_request_is_answer_mode():
    request = (
        "Design a lightweight execution journaling mechanism "
        "in Python/C++ that captures non-deterministic async API "
        "responses and thread interleavings. Provide complete code "
        "showing how to replay a failed execution path with "
        "bit-for-bit precision to isolate a race condition."
    )

    assert cli._auto_request_requires_execution(request) is False


def test_show_code_request_is_answer_mode():
    assert (
        cli._auto_request_requires_execution(
            "Show me code in Python for deterministic replay."
        )
        is False
    )


def test_write_file_request_remains_execution_mode():
    assert (
        cli._auto_request_requires_execution(
            "Write a file replay.py containing deterministic replay code."
        )
        is True
    )


def test_build_website_request_remains_execution_mode():
    assert (
        cli._auto_request_requires_execution(
            "Build a website about dogs."
        )
        is True
    )


def test_deploy_request_still_remains_execution_mode():
    assert (
        cli._auto_request_requires_execution(
            DEPLOY_REQUEST
        )
        is True
    )
