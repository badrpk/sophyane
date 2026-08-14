from __future__ import annotations

from pathlib import Path

import pytest

import sophyane.sli_graph as graph
from sophyane.sli_graph import SLIState, classify


FAILED_REQUEST = (
    "Design a lightweight execution journaling mechanism in "
    "Python/C++ that captures non-deterministic async API "
    "responses and thread interleavings. Provide a complete "
    "code snippet showing how to replay a failed execution path "
    "with bit-for-bit precision to isolate a race condition."
)


def route(request: str) -> str:
    state = classify(
        SLIState(
            request=request,
            workspace=".",
        ),
        lambda _message: None,
    )
    return state.route


@pytest.mark.parametrize(
    "case",
    (
        FAILED_REQUEST,
        (
            "Design a deterministic replay system in Python and "
            "provide a complete code snippet."
        ),
        "Give me Python code for an execution journal.",
        "Show a C++ implementation example for a race condition.",
        "Provide source code for async API replay.",
        "Build a command line concurrency debugger.",
    ),
)
def test_constructive_code_routes_to_software_artifact(
    case: str,
) -> None:
    assert route(case) == "software_artifact"


@pytest.mark.parametrize(
    "case",
    (
        "Explain what a race condition is.",
        "What is deterministic replay?",
        "Tell me about thread interleavings.",
        "How does an async API work?",
    ),
)
def test_informational_questions_remain_informational(
    case: str,
) -> None:
    assert route(case) == "memory_then_internet"


@pytest.mark.parametrize(
    "case",
    (
        "Design a website about race conditions.",
        "Create a browser app showing thread scheduling.",
        "Build a dashboard for concurrency metrics.",
    ),
)
def test_browser_products_do_not_use_software_artifact(
    case: str,
) -> None:
    assert route(case) != "software_artifact"


def test_exact_prompt_never_calls_browser_internet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_memory(state, progress):
        calls.append("memory")
        return state

    def forbidden_internet(state, progress):
        raise AssertionError(
            "software_artifact called browser internet acquisition"
        )

    monkeypatch.setattr(
        graph,
        "try_memory_router",
        fake_memory,
    )

    monkeypatch.setattr(
        graph,
        "try_internet",
        forbidden_internet,
    )

    result = graph.run_sli_graph(
        FAILED_REQUEST,
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert result.route == "software_artifact"
    assert calls == ["memory"]
    assert result.success is False
