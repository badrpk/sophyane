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


class FailingLocalProvider:
    def generate(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        del prompt, system_prompt
        raise RuntimeError(
            "llama-server is not running on 8766"
        )


def test_local_runtime_failure_stops_without_browser_or_provider_fallback(
    tmp_path: Path,
) -> None:
    browser_calls: list[Path] = []

    def initial_compose(
        request: str,
        workspace: Path,
        progress=None,
    ) -> str:
        del request, progress

        workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        (workspace / "index.html").write_text(
            "<!doctype html><html><head>"
            "<title>Fruit</title></head><body>"
            "<main><h1>Fruit</h1>"
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
        browser_calls.append(target)
        return True, target.as_uri()

    with (
        patch(
            "sophyane.local_site_refinement."
            "rich.compose_rich_topic_site",
            side_effect=initial_compose,
        ),
        patch(
            "sophyane.local_site_refinement._provider",
            return_value=FailingLocalProvider(),
        ),
        patch(
            "sophyane.local_site_refinement."
            "rich._open_generated_site",
            side_effect=browser,
        ),
    ):
        report = compose_refined_local_topic_site(
            "make fruits website",
            tmp_path,
        )

    assert (tmp_path / "index.html").is_file()
    assert browser_calls == []

    assert "Initial artifact: deterministic SLI completed" in report
    assert "Local GGUF critique attempted: True" in report
    assert "Local GGUF critique completed: False" in report
    assert "Browser opened: False" in report
    assert "Cloud LLM used: False" in report
    assert "Provider fallback used: False" in report
    assert "Success: False" in report


def test_pass_with_issues_is_treated_as_improve() -> None:
    from sophyane.local_site_refinement import (
        _effective_verdict,
    )

    critique = {
        "verdict": "pass",
        "issues": [
            "Navigation could be improved",
        ],
        "improvements": [
            "Add visible focus styles",
        ],
    }

    assert _effective_verdict(critique) == "improve"


def test_clean_pass_remains_pass() -> None:
    from sophyane.local_site_refinement import (
        _effective_verdict,
    )

    critique = {
        "verdict": "pass",
        "issues": [],
        "improvements": [],
    }

    assert _effective_verdict(critique) == "pass"


def test_unknown_verdict_defaults_to_improve() -> None:
    from sophyane.local_site_refinement import (
        _effective_verdict,
    )

    critique = {
        "verdict": "maybe",
        "issues": [],
        "improvements": [],
    }

    assert _effective_verdict(critique) == "improve"
