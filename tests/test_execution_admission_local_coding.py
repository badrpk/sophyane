from pathlib import Path

import pytest

from sophyane.capability_chain_guard import (
    CapabilityChainGuard,
    ChainRequest,
)
from sophyane.capability_flow_graph import default_capability_graph
from sophyane.capability_flow_policy import (
    LabeledValue,
    Sensitivity,
)
from sophyane.execution_admission import (
    classify_execution_admission,
)
from sophyane.execution_admission_verifiers import (
    verify_execution_admission,
)
from sophyane.local_coding_capability import (
    recognizes_coding_request,
)


@pytest.mark.parametrize(
    ("text", "recognized"),
    (
        ("create hello.py that prints hello", True),
        ("write hello.py", True),
        ("make hello.cpp that prints hello", True),
        ("generate hello.cpp", True),
        ("repair broken.py", True),
        ("fix broken.py", True),
        ("correct broken.py", True),
        ("debug broken.py", True),
        ("update broken.py", True),
        ("explain what Python is", False),
        ("what is Python", False),
        ("how does Python work", False),
        ("why does Python work", False),
        ("tell me about Python", False),
        ("ordinary conversation", False),
        ("", False),
    ),
)
def test_pure_shared_local_coding_frontier(
    tmp_path: Path,
    text: str,
    recognized: bool,
) -> None:
    before = sorted(tmp_path.rglob("*"))

    actual = recognizes_coding_request(text)

    after = sorted(tmp_path.rglob("*"))

    assert actual is recognized
    assert before == after


@pytest.mark.parametrize(
    "text",
    (
        "create hello.py that prints hello",
        "make hello.cpp that prints hello",
        "repair broken.py",
        "debug broken.py",
    ),
)
def test_local_coding_admission_includes_process_execution(
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
    assert admission.runtime_family == "development.local_coding"
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


@pytest.mark.parametrize(
    "text",
    (
        "explain what Python is",
        "what is Python",
        "ordinary conversation",
    ),
)
def test_non_coding_text_not_claimed_by_local_coding(
    tmp_path: Path,
    text: str,
) -> None:
    assert recognizes_coding_request(text) is False

    admission = classify_execution_admission(
        text,
        workspace=tmp_path,
    )

    assert (
        admission is None
        or admission.runtime_family != "development.local_coding"
    )
