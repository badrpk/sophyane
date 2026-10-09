from pathlib import Path

import pytest

from sophyane.capability_chain_guard import (
    CapabilityChainGuard,
    ChainRequest,
)
from sophyane.capability_executors import (
    _is_judge_validation_request,
    _is_shell_exit_probe_request,
)
from sophyane.capability_flow_graph import default_capability_graph
from sophyane.capability_flow_policy import (
    LabeledValue,
    Sensitivity,
)
from sophyane.execution_admission import classify_execution_admission
from sophyane.execution_admission_verifiers import (
    verify_execution_admission,
)


@pytest.mark.parametrize(
    ("text", "shell", "judge"),
    (
        ("exit_probe STDOUT_OK STDERR_OK exit code 7", True, False),
        ("stdout_ok stderr_ok exit with code 7", True, False),
        (
            "create judge.sh and verify required_section judge_validated",
            False,
            True,
        ),
        ("judge.sh required_section judge_validated", False, True),
    ),
)
def test_shared_recognition_frontier(
    text: str,
    shell: bool,
    judge: bool,
) -> None:
    assert _is_shell_exit_probe_request(text) is shell
    assert _is_judge_validation_request(text) is judge


@pytest.mark.parametrize(
    "text",
    (
        "exit_probe STDOUT_OK STDERR_OK exit code 7",
        "stdout_ok stderr_ok exit with code 7",
        "create judge.sh and verify required_section judge_validated",
        "judge.sh required_section judge_validated",
    ),
)
def test_process_execution_admission(
    tmp_path: Path,
    text: str,
) -> None:
    before = sorted(tmp_path.rglob("*"))

    admission = classify_execution_admission(
        text,
        workspace=tmp_path,
    )

    after = sorted(tmp_path.rglob("*"))

    assert before == after
    assert admission is not None
    assert admission.runtime_family == "legacy.deterministic_capabilities"
    assert admission.policy_capabilities == (
        "local_reasoning",
        "local_filesystem",
        "local_process_execution",
    )
    assert admission.read_only is False
    assert admission.side_effects == frozenset(
        {
            "filesystem_write",
            "process_execution",
        }
    )

    verification = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert verification.allowed is True
    assert verification.verifier_evidence == frozenset(
        {
            "schema",
            "workspace_boundary",
        }
    )

    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    decision = guard.evaluate(
        request=ChainRequest(
            capabilities=admission.policy_capabilities,
            scope=str(tmp_path.resolve()),
            verifier_evidence=verification.verifier_evidence,
        ),
        value=LabeledValue.create(
            text,
            sensitivity=Sensitivity.USER_PRIVATE,
            origin="user_request",
        ),
    )

    assert decision.allowed is True
    assert not decision.missing_verifiers


def test_process_descriptor_is_explicit_executable_sink() -> None:
    graph = default_capability_graph()
    descriptor = graph.descriptor("local_process_execution")

    assert descriptor.executable_sink is True
    assert descriptor.persistent_sink is False
    assert descriptor.external_sink is False
    assert descriptor.side_effects == frozenset(
        {
            "process_execution",
        }
    )
    assert descriptor.required_verifiers == frozenset(
        {
            "workspace_boundary",
        }
    )


def test_process_transition_requires_filesystem_stage() -> None:
    graph = default_capability_graph()
    value = LabeledValue.create(
        "probe",
        sensitivity=Sensitivity.USER_PRIVATE,
        origin="test",
    )

    valid = graph.validate_chain(
        (
            "local_reasoning",
            "local_filesystem",
            "local_process_execution",
        ),
        value,
    )
    assert valid.allowed is True

    undeclared = graph.validate_chain(
        (
            "local_reasoning",
            "local_process_execution",
        ),
        value,
    )
    assert undeclared.allowed is False
    assert "undeclared capability transition" in undeclared.reason
