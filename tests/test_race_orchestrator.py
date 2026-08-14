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
