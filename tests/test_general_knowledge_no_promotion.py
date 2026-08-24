from pathlib import Path

import sophyane.sli_graph as graph
import sophyane.web_intel as web


def test_terminal_grounded_text_skips_artifact_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        web,
        "web_search",
        lambda _query, **_kwargs: {
            "ok": True,
            "count": 1,
            "results": [
                {
                    "title": "Red-black tree",
                    "snippet": (
                        "A red-black tree is a self-balancing "
                        "binary search tree."
                    ),
                    "url": "https://example.invalid/",
                },
            ],
            "errors": [],
        },
    )

    def forbidden(
        *_args,
        **_kwargs,
    ):
        raise AssertionError(
            "artifact promotion invoked"
        )

    monkeypatch.setattr(
        graph,
        "validate_and_promote",
        forbidden,
    )

    state = graph.run_sli_graph(
        "Explain what a red-black tree is.",
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert state.route == "general_knowledge"
    assert state.success is True
    assert state.meta.get("terminal") is True
    assert state.meta.get(
        "grounded_text_answer"
    ) is True


def test_product_route_keeps_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def classify_product(state, progress):
        state.route = "product_app"
        return state

    monkeypatch.setattr(
        graph,
        "classify",
        classify_product,
    )

    monkeypatch.setattr(
        graph,
        "try_product_reuse",
        lambda state, progress: state,
    )

    monkeypatch.setattr(
        graph,
        "try_product_app",
        lambda state, progress: state,
    )

    monkeypatch.setattr(
        graph,
        "validate_and_promote",
        lambda state, progress: (
            calls.append(state.route)
            or state
        ),
    )

    graph.run_sli_graph(
        "Create a website.",
        workspace=tmp_path,
        progress=lambda _message: None,
        max_retries=1,
    )

    assert calls == ["product_app"]
