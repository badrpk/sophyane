from pathlib import Path
from unittest.mock import patch

import pytest

from sophyane.sli_chunk_router import resolve_tier


@pytest.mark.parametrize(
    "mode",
    [
        "local_llm",
        "cloud_llm",
    ],
)
def test_website_build_uses_sli_before_provider(
    tmp_path: Path,
    mode: str,
) -> None:
    report = (
        "Sophyane rich SLI website orchestrator\n"
        "Files: index.html\n"
        "Success: True"
    )

    def compose(message, workspace=None, progress=None):
        del message, progress
        target = Path(workspace)
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.html").write_text(
            "<!doctype html><title>Dogs</title>",
            encoding="utf-8",
        )
        return report

    with patch(
        "sophyane.sli_chunk_router.try_sli_chunks",
        side_effect=compose,
    ) as mocked:
        tier, result = resolve_tier(
            "make website on dogs",
            selected_mode=mode,
            workspace=tmp_path,
        )

    assert tier == "sli_topic_site"
    assert result == report
    mocked.assert_called_once()


@pytest.mark.parametrize(
    "mode",
    [
        "local_llm",
        "cloud_llm",
    ],
)
def test_non_website_request_keeps_provider(
    tmp_path: Path,
    mode: str,
) -> None:
    tier, result = resolve_tier(
        "Explain Python decorators",
        selected_mode=mode,
        workspace=tmp_path,
    )

    assert tier == mode
    assert result is None
