import pytest

from sophyane.human_conversation_cli import (
    _repository_operation_for_request,
)
from sophyane.rsi.authority import Operation


@pytest.mark.parametrize(
    "task_text",
    [
        "Audit whether Sophyane enforces its eight agent execution guardrails deterministically.",
        "Check whether Sophyane should implement SSRF protection.",
        "Assess whether Sophyane should implement additional safeguards.",
        "Check if Sophyane implements tenant isolation, SSRF protection, idempotency, and verification.",
        "Review Sophyane's current source and report which controls are implemented.",
        "Assess whether Sophyane currently implements the required guardrails.",
        "Audit Sophyane and report findings. Do not make changes.",
    ],
)
def test_repository_audit_is_read_only(task_text):
    assert (
        _repository_operation_for_request(task_text)
        is Operation.READ_ONLY_OPERATION
    )


@pytest.mark.parametrize(
    "task_text, expected",
    [
        (
            "Implement a guardrail fix in Sophyane source. Source edits are explicitly authorized.",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "Fix the SSRF guardrail in Sophyane.",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "Audit whether Sophyane should implement safeguards. Fix any missing safeguards.",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "Check whether Sophyane should implement X and create a test file.",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "Create a new Python file in the ordinary workspace.",
            Operation.ORDINARY_WORKSPACE_MUTATION,
        ),
    ],
)
def test_affirmative_mutations_retain_authority(task_text, expected):
    assert _repository_operation_for_request(task_text) is expected
