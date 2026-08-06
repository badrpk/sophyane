from pathlib import Path
from unittest.mock import patch

import pytest

from sophyane.tui_v2 import _simple_chat_reply


@pytest.mark.parametrize(
    "mode",
    [
        "local_llm",
        "cloud_llm",
        "sli_graph",
    ],
)
def test_topic_site_runs_before_provider_in_every_mode(
    tmp_path: Path,
    monkeypatch,
    mode: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        mode,
    )
    monkeypatch.delenv(
        "SOPHYANE_SLI_ONLY",
        raising=False,
    )

    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Files: index.html\n"
        "Browser opened: True\n"
        "Success: True"
    )

    def compose(
        message: str,
        workspace: Path,
        progress=None,
    ) -> str:
        del message, progress

        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )
        (workspace / "index.html").write_text(
            "<!doctype html><title>Tigers</title>",
            encoding="utf-8",
        )
        return report

    with patch(
        "sophyane.code_memory.sli_rich_site_compose."
        "compose_rich_topic_site",
        side_effect=compose,
    ) as mocked:
        result = _simple_chat_reply(
            "make tigers website"
        )

    assert result == report
    assert mocked.call_count == 1
    assert (
        tmp_path
        / ".sophyane-workspace"
        / "index.html"
    ).is_file()


def test_ordinary_local_prompt_does_not_use_topic_composer(
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

    with patch(
        "sophyane.code_memory.sli_rich_site_compose."
        "compose_rich_topic_site",
    ) as mocked:
        result = _simple_chat_reply(
            "Explain Python decorators"
        )

    mocked.assert_not_called()
    # None means the ordinary request continues to the selected local model.
    assert result is None
