from pathlib import Path

import sophyane.sli_graph as graph

from sophyane.web_intel import (
    normalize_knowledge_query,
)


def test_explanation_query_is_reduced_to_topic() -> None:
    assert (
        normalize_knowledge_query(
            "Explain what a red-black tree is."
        )
        == "red-black tree"
    )


def test_question_article_is_removed() -> None:
    assert (
        normalize_knowledge_query(
            "What is a red-black tree?"
        )
        == "red-black tree"
    )


def test_definite_article_is_removed_after_wrapper() -> None:
    assert (
        normalize_knowledge_query(
            "What is the TCP congestion window?"
        )
        == "tcp congestion window"
    )


def test_bare_query_is_not_broadened_or_rewritten() -> None:
    assert (
        normalize_knowledge_query(
            "red-black tree"
        )
        == "red-black tree"
    )


def test_bare_leading_article_is_preserved() -> None:
    assert (
        normalize_knowledge_query(
            "a red-black tree"
        )
        == "a red-black tree"
    )


def test_general_knowledge_pipeline_never_uses_artifact_internet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def forbidden(
        *_args,
        **_kwargs,
    ):
        raise AssertionError(
            "browser acquisition invoked"
        )

    monkeypatch.setattr(
        graph,
        "try_internet",
        forbidden,
    )

    result = graph.run_sli_graph(
        "Explain what a red-black tree is.",
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert (
        result.route
        == "general_knowledge"
    )

    assert (
        "Artifact construction used: False"
        in result.report
    )

    assert (
        "LLM used: False"
        in result.report
    )
