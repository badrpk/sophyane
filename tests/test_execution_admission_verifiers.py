from dataclasses import replace

from sophyane.capability_chain_guard import (
    CapabilityChainGuard,
    ChainRequest,
)
from sophyane.capability_flow_graph import default_capability_graph
from sophyane.capability_flow_policy import LabeledValue
from sophyane.execution_admission import (
    ExecutionAdmission,
    classify_execution_admission,
)
from sophyane.execution_admission_verifiers import (
    verify_execution_admission,
)


def _classify(text: str):
    result = classify_execution_admission(text)
    assert result is not None
    return result


def test_read_admission_receives_real_required_evidence(tmp_path):
    admission = _classify("list files")

    result = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert result.allowed is True
    assert result.verifier_evidence == frozenset(
        {
            "schema",
            "workspace_boundary",
        }
    )
    assert result.workspace == tmp_path.resolve()


def test_write_admission_receives_real_required_evidence(tmp_path):
    admission = _classify(
        "Create a file named artifact.txt. "
        "The line must begin X and contain the uppercase words "
        "ONE and TWO joined by underscores. "
        "End the file with exactly one newline."
    )

    result = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert result.allowed is True
    assert result.verifier_evidence == frozenset(
        {
            "schema",
            "workspace_boundary",
        }
    )


def test_workspace_evidence_is_not_minted_without_workspace():
    admission = _classify("list files")

    result = verify_execution_admission(
        admission,
        workspace=None,
    )

    assert result.allowed is False
    assert result.verifier_evidence == frozenset(
        {"schema"}
    )
    assert result.reason == (
        "workspace boundary requires a valid workspace"
    )


def test_unknown_capability_is_rejected(tmp_path):
    admission = ExecutionAdmission(
        runtime_family="test",
        policy_capabilities=(
            "local_reasoning",
            "not_a_real_capability",
        ),
        read_only=True,
        side_effects=frozenset(),
    )

    result = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert result.allowed is False
    assert result.verifier_evidence == frozenset()


def test_read_only_claim_cannot_hide_side_effects(tmp_path):
    admission = ExecutionAdmission(
        runtime_family="test",
        policy_capabilities=(
            "local_reasoning",
            "local_filesystem",
        ),
        read_only=True,
        side_effects=frozenset(),
    )

    result = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert result.allowed is False
    assert result.reason == "admission omits policy side effect"


def test_read_only_admission_cannot_declare_side_effects(tmp_path):
    admission = _classify("list files")

    admission = replace(
        admission,
        side_effects=frozenset(
            {"filesystem_write"}
        ),
    )

    result = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    assert result.allowed is False
    assert result.reason == (
        "read-only admission declares side effects"
    )


def test_verified_read_admission_satisfies_guard(tmp_path):
    admission = _classify("list files")

    verification = verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    request = ChainRequest(
        capabilities=admission.policy_capabilities,
        scope=str(tmp_path.resolve()),
        verifier_evidence=verification.verifier_evidence,
    )

    value = LabeledValue.create(
        {
            "request": "list files",
            "workspace": str(tmp_path.resolve()),
        },
        origin="unified_execution_kernel",
    )

    result = guard.evaluate(
        request=request,
        value=value,
    )

    assert result.allowed is True


def test_missing_workspace_still_fails_guard(tmp_path):
    admission = _classify("list files")

    verification = verify_execution_admission(
        admission,
        workspace=None,
    )

    guard = CapabilityChainGuard(
        graph=default_capability_graph()
    )

    request = ChainRequest(
        capabilities=admission.policy_capabilities,
        scope=str(tmp_path.resolve()),
        verifier_evidence=verification.verifier_evidence,
    )

    value = LabeledValue.create(
        {"request": "list files"},
        origin="unified_execution_kernel",
    )

    result = guard.evaluate(
        request=request,
        value=value,
    )

    assert verification.allowed is False
    assert result.allowed is False
    assert "workspace_boundary" in result.missing_verifiers


def test_verifier_is_workspace_mutation_free(tmp_path):
    admission = _classify("list files")

    before = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
    )

    verify_execution_admission(
        admission,
        workspace=tmp_path,
    )

    after = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
    )

    assert after == before
