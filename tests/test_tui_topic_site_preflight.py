from pathlib import Path
from unittest.mock import patch

import pytest

from sophyane.tui_v2 import _simple_chat_reply


def _write_fake_site(
    workspace: Path,
    title: str = "Tigers",
) -> None:
    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )
    (workspace / "index.html").write_text(
        (
            "<!doctype html>"
            "<html><head>"
            f"<title>{title}</title>"
            "</head><body>"
            f"<main><h1>{title}</h1></main>"
            "</body></html>"
        ),
        encoding="utf-8",
    )


def test_local_mode_uses_hybrid_sli_gguf_pipeline_before_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )
    monkeypatch.setenv(
        "SOPHYANE_LOCAL_ONLY",
        "1",
    )
    monkeypatch.setenv(
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
        "1",
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_ONLY",
        raising=False,
    )

    report = (
        "Sophyane hybrid SLI + local GGUF website pipeline\n"
        "Initial artifact: deterministic SLI\n"
        "Local GGUF critique: completed\n"
        "Final validation: passed\n"
        "Browser opened: True\n"
        "Cloud LLM used: False\n"
        "Local GGUF used: True\n"
        "Success: True"
    )

    def compose(
        request: str,
        workspace: Path,
        *,
        progress=None,
    ) -> str:
        del request, progress
        _write_fake_site(workspace)
        return report

    with (
        patch(
            "sophyane.local_site_refinement."
            "compose_refined_local_topic_site",
            side_effect=compose,
        ) as hybrid,
        patch(
            "sophyane.code_memory.sli_rich_site_compose."
            "compose_rich_topic_site",
        ) as deterministic_only,
    ):
        result = _simple_chat_reply(
            "make tigers website"
        )

    assert result == report
    hybrid.assert_called_once()
    deterministic_only.assert_not_called()

    assert (
        tmp_path
        / ".sophyane-workspace"
        / "index.html"
    ).is_file()


def test_cloud_mode_uses_deterministic_site_composer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_ONLY",
        raising=False,
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_GRAPH",
        raising=False,
    )

    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Files: index.html\n"
        "Browser opened: True\n"
        "LLM used: False\n"
        "Success: True"
    )

    def compose(
        request: str,
        workspace: Path,
        progress=None,
    ) -> str:
        del request, progress
        _write_fake_site(workspace)
        return report

    with (
        patch(
            "sophyane.code_memory.sli_rich_site_compose."
            "compose_rich_topic_site",
            side_effect=compose,
        ) as deterministic,
        patch(
            "sophyane.local_site_refinement."
            "compose_refined_local_topic_site",
        ) as hybrid,
        patch(
            "sophyane.sli_graph.run_sli_graph",
        ) as graph,
    ):
        result = _simple_chat_reply(
            "make tigers website"
        )

    assert result == report
    deterministic.assert_called_once()
    hybrid.assert_not_called()
    graph.assert_not_called()

    assert (
        tmp_path
        / ".sophyane-workspace"
        / "index.html"
    ).is_file()


def test_ordinary_local_prompt_does_not_use_site_pipeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_ONLY",
        raising=False,
    )

    with (
        patch(
            "sophyane.local_site_refinement."
            "compose_refined_local_topic_site",
        ) as hybrid,
        patch(
            "sophyane.code_memory.sli_rich_site_compose."
            "compose_rich_topic_site",
        ) as deterministic,
    ):
        result = _simple_chat_reply(
            "Explain Python decorators"
        )

    hybrid.assert_not_called()
    deterministic.assert_not_called()

    # None means the ordinary request continues to strict local GGUF.
    assert result is None


def test_sli_graph_topic_site_uses_graph_lifecycle_before_direct_composer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )
    monkeypatch.setenv(
        "SOPHYANE_SLI_ONLY",
        "1",
    )
    monkeypatch.setenv(
        "SOPHYANE_SLI_GRAPH",
        "1",
    )

    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Validation: passed\n"
        "Success: True\n"
        "SLI-graph route: topic_site; "
        "seconds: 0.01; promoted: True; chunks_added: 3"
    )

    class FakeState:
        def __init__(self) -> None:
            self.report = report

    with (
        patch(
            "sophyane.sli_graph.run_sli_graph",
            return_value=FakeState(),
        ) as graph,
        patch(
            "sophyane.code_memory.sli_rich_site_compose."
            "compose_rich_topic_site",
        ) as direct,
    ):
        result = _simple_chat_reply(
            "make website on demis hassabis"
        )

    assert result == report

    graph.assert_called_once_with(
        "make website on demis hassabis",
        workspace=(
            tmp_path
            / ".sophyane-workspace"
        ),
    )

    direct.assert_not_called()
