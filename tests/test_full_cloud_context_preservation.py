from pathlib import Path

from sophyane import adaptive_execution


def test_new_browser_prompt_preserves_complete_large_request():
    beginning = "BEGINNING_REQUIREMENT_" + ("A" * 5000)
    ending = "ENDING_REQUIREMENT_" + ("B" * 5000)
    request = beginning + ending

    prompt = adaptive_execution._raw_html_prompt(request)

    assert beginning in prompt
    assert ending in prompt


def test_existing_browser_prompt_preserves_complete_artifact():
    request = "Change only the requested behavior."
    beginning = "<!-- BEGIN_ARTIFACT -->" + ("A" * 15000)
    ending = ("B" * 15000) + "<!-- END_ARTIFACT -->"
    existing = (
        "<!doctype html><html><body>"
        + beginning
        + ending
        + "</body></html>"
    )

    prompt = adaptive_execution._raw_html_prompt(
        request,
        existing,
    )

    assert beginning in prompt
    assert ending in prompt
    assert existing in prompt


def test_structural_recovery_receives_complete_preserved_artifact():
    beginning = "<!doctype html><html><body><script>" + ("A" * 10000)
    ending = ("B" * 10000) + "function unfinished(){"
    partial = beginning + ending

    prompt = adaptive_execution._html_continuation_prompt(partial)

    assert beginning in prompt
    assert ending in prompt
    assert partial in prompt


def test_browser_recovery_has_no_fixed_artifact_character_ceiling():
    from sophyane import browser_partial_recovery

    assert browser_partial_recovery.MAX_TOTAL_CHARS == 0


def test_no_task_specific_domain_language_in_context_regression():
    sources = [
        Path("src/sophyane/adaptive_execution.py").read_text(),
        Path("src/sophyane/html_repair_policy.py").read_text(),
    ]

    joined = "\n".join(sources).lower()

    # The general context/repair transport must not specialize itself around
    # one application domain.
    assert "sophyane_snake_scalar" not in joined
