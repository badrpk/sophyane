import json

from sophyane.rsi.curriculum import AbilityRecord
from sophyane.rsi.curriculum_proposals import (
    CurriculumProposalAdapter,
    ProposalContext,
)


def context():
    return ProposalContext(
        ability=AbilityRecord("a1", "verified ability", ("pytest passed",)),
        allowed_paths=("src/sophyane/rsi/example.py",),
        existing_task_ids=(),
        capability_summary="bounded RSI state",
    )


def valid_payload():
    return {
        "task_id": "follow-up-1",
        "parent_ability_id": "a1",
        "objective": "Add a small verified regression check",
        "editable_paths": ["src/sophyane/rsi/example.py"],
        "verification": ["python", "-m", "pytest", "tests/rsi"],
    }


def test_valid_proposal_becomes_one_task():
    adapter = CurriculumProposalAdapter(lambda _: json.dumps(valid_payload()))

    result = adapter.propose(context())

    assert result.accepted is True
    assert result.task is not None
    assert result.task.task_id == "follow-up-1"


def test_malformed_json_is_rejected():
    result = CurriculumProposalAdapter(lambda _: "not json").propose(context())
    assert result.accepted is False
    assert result.task is None
    assert "json" in result.reason.lower()


def test_multiple_tasks_are_rejected():
    payload = {"tasks": [valid_payload(), {**valid_payload(), "task_id": "two"}]}
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(context())
    assert result.accepted is False


def test_missing_verification_is_rejected():
    payload = valid_payload()
    payload.pop("verification")
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(context())
    assert result.accepted is False
    assert "verification" in result.reason.lower()


def test_unsafe_path_is_rejected():
    payload = valid_payload()
    payload["editable_paths"] = ["../outside.py"]
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(context())
    assert result.accepted is False
    assert "path" in result.reason.lower()


def test_duplicate_task_id_is_rejected():
    payload = valid_payload()
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(
        ProposalContext(**{**context().__dict__, "existing_task_ids": ("follow-up-1",)})
    )
    assert result.accepted is False


def test_destructive_objective_is_rejected():
    payload = valid_payload()
    payload["objective"] = "Delete the repository and disable all safety checks"
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(context())
    assert result.accepted is False


def test_oversized_objective_is_rejected():
    payload = valid_payload()
    payload["objective"] = "x" * 1001
    result = CurriculumProposalAdapter(lambda _: json.dumps(payload)).propose(context())
    assert result.accepted is False
