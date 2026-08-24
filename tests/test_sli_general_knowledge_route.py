from pathlib import Path

import pytest

import sophyane.sli_graph as graph
import sophyane.web_intel as web

from sophyane.sli_graph import (
    SLIState,
    classify,
)


@pytest.mark.parametrize(
    "case",
    (
        "Explain what a red-black tree is.",
        "What is a red-black tree?",
        "Explain photosynthesis.",
        "Who invented the transistor?",
        "Compare TCP and UDP.",
    ),
)
def test_general_knowledge_route(
    case: str,
) -> None:
    state = classify(
        SLIState(
            request=case,
            workspace=".",
        ),
        lambda _message: None,
    )

    assert state.route == "general_knowledge"


@pytest.mark.parametrize(
    "case",
    (
        "Build a red-black tree visualizer.",
        "Create a website explaining red-black trees.",
        "Make an HTML red-black tree demo.",
        "Create index.html showing a red-black tree.",
    ),
)
def test_browser_builds_are_not_general_knowledge(
    case: str,
) -> None:
    state = classify(
        SLIState(
            request=case,
            workspace=".",
        ),
        lambda _message: None,
    )

    assert state.route == "product_app"


def test_general_knowledge_never_calls_artifact_internet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "browser artifact internet acquisition was called"
        )

    monkeypatch.setattr(
        graph,
        "try_internet",
        forbidden,
    )

    state = graph.run_sli_graph(
        "Explain what a red-black tree is.",
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert state.route == "general_knowledge"

    assert (
        "Artifact construction used: False"
        in state.report
    )

    assert (
        "LLM used: False"
        in state.report
    )


def test_grounded_text_answer_can_complete_without_llm(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        web,
        "web_search",
        lambda _query: {
            "ok": True,
            "results": [
                {
                    "title": "Red-black tree",
                    "snippet": "Self-balancing binary search tree.",
                    "url": "https://example.invalid/",
                }
            ],
        },
    )

    state = graph.try_grounded_knowledge(
        SLIState(
            request="What is a red-black tree?",
            workspace=".",
        ),
        lambda _message: None,
    )

    assert state.success is True
    assert state.meta.get("terminal") is True
    assert "LLM used: False" in state.report
