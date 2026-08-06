from pathlib import Path
from unittest.mock import patch

from sophyane.local_site_refinement import (
    compose_refined_local_topic_site,
)


class FakeLocalProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        del system_prompt
        self.calls += 1

        if "Return JSON only" in prompt:
            if self.calls >= 3:
                return (
                    '{"verdict":"pass",'
                    '"issues":[],'
                    '"improvements":[]}'
                )

            return (
                '{"verdict":"improve",'
                '"issues":["Improve keyboard focus"],'
                '"improvements":["Add visible focus styling"]}'
            )

        return (
            "<style>"
            "a:focus-visible,button:focus-visible{"
            "outline:3px solid currentColor;"
            "outline-offset:4px}"
            "</style>"
        )


def test_local_refinement_occurs_before_browser(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    provider = FakeLocalProvider()

    def initial_compose(
        request: str,
        workspace: Path,
        progress=None,
    ) -> str:
        del request, progress
        events.append("initial_sli")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "index.html").write_text(
            "<!doctype html><html><head>"
            "<title>Tiger</title></head>"
            "<body><main><h1>Tiger</h1>"
            + ("<p>Grounded content.</p>" * 100)
            + "</main></body></html>",
            encoding="utf-8",
        )
        return "Success: True"

    def browser(
        target: Path,
        progress,
    ) -> tuple[bool, str]:
        del progress
        events.append("browser")
        document = target.read_text(encoding="utf-8")
        assert "focus-visible" in document
        return True, target.as_uri()

    with (
        patch(
            "sophyane.local_site_refinement."
            "rich.compose_rich_topic_site",
            side_effect=initial_compose,
        ),
        patch(
            "sophyane.local_site_refinement._provider",
            return_value=provider,
        ),
        patch(
            "sophyane.local_site_refinement."
            "rich._open_generated_site",
            side_effect=browser,
        ),
    ):
        report = compose_refined_local_topic_site(
            "make tiger website",
            tmp_path,
        )

    assert events == ["initial_sli", "browser"]
    assert provider.calls >= 2
    assert "Local GGUF used: True" in report
    assert "Cloud LLM used: False" in report
    assert "Final validation: passed" in report
    assert (tmp_path / "local-gguf-critique.json").is_file()
