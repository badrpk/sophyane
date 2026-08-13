from __future__ import annotations

from pathlib import Path

import pytest

import sophyane.sli_graph as sli_graph
from sophyane.sli_graph import (
    SLIState,
    classify,
)


def route(text: str) -> str:
    state = classify(
        SLIState(
            request=text,
            workspace=".",
        ),
        lambda _message: None,
    )
    return state.route


@pytest.mark.parametrize(
    "case",
    (
        "Build a REST API and client SDK.",
        "Create a Python CLI.",
        "Implement a Python library.",
        "Create a FastAPI backend.",
        (
            "Generate an OpenAPI specification and backend "
            "stubs plus a test client."
        ),
        (
            "Instruct an AI harness to parse incoming raw payload "
            "examples or rough functional descriptions, autonomously "
            "derive strict JSON schemas or OpenAPI specifications, "
            "and generate functional backend mocking stubs or test "
            "client scripts."
        ),
    ),
)
def test_constructive_non_browser_software_uses_software_artifact(
    case: str,
) -> None:
    assert route(case) == "software_artifact"


@pytest.mark.parametrize(
    "case",
    (
        "Explain how REST APIs work.",
        "What is OpenAPI?",
        "Explain JSON Schema validation.",
    ),
)
def test_informational_software_topics_remain_informational(
    case: str,
) -> None:
    assert route(case) == "memory_then_internet"


@pytest.mark.parametrize(
    "case",
    (
        "Create an interactive browser application.",
        "Create a web app dashboard.",
    ),
)
def test_browser_products_remain_product_app(
    case: str,
) -> None:
    assert route(case) == "product_app"


def test_known_grounded_harness_contract_remains_python_harness() -> None:
    assert route(
        "Create policy_engine.py implementing decide_route."
    ) == "python_harness"


def test_existing_repair_route_remains_harness_execution() -> None:
    assert route(
        "Repair the existing production code after a pytest "
        "test failure and re-run verification."
    ) == "harness_execution"


def test_software_artifact_pipeline_never_calls_browser_internet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def fake_memory(state, progress):
        calls.append("memory")
        return state

    def forbidden_internet(state, progress):
        raise AssertionError(
            "software_artifact must not call browser internet acquisition"
        )

    monkeypatch.setattr(
        sli_graph,
        "try_memory_router",
        fake_memory,
    )
    monkeypatch.setattr(
        sli_graph,
        "try_internet",
        forbidden_internet,
    )

    state = sli_graph.run_sli_graph(
        "Generate an OpenAPI specification and backend stubs.",
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert state.route == "software_artifact"
    assert calls == ["memory"]
    assert state.success is False
