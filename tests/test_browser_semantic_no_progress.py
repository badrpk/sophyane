from types import SimpleNamespace

from sophyane import adaptive_execution as adaptive
from sophyane.browser_partial_recovery import (
    MAX_CONTINUATIONS,
    _semantic_repair_state,
    install_browser_partial_recovery,
)


HTML_A = (
    "<!doctype html><html><body>"
    + ("A" * 400)
    + "<script>let direction={x:1,y:0};</script>"
    + "</body></html>"
)

HTML_B = HTML_A.replace(
    "let direction",
    "const direction",
)


def _installed_recovery(monkeypatch):
    original = adaptive._one_shot_browser_artifact
    monkeypatch.setattr(
        adaptive,
        "_one_shot_browser_artifact",
        original,
    )
    install_browser_partial_recovery()
    return adaptive._one_shot_browser_artifact


def _patch_complete_rewrites(monkeypatch, problem_for):
    monkeypatch.setattr(
        adaptive,
        "_extract_html",
        lambda value: value,
    )
    monkeypatch.setattr(
        adaptive,
        "_extract_partial_html",
        lambda value: value,
    )
    monkeypatch.setattr(
        adaptive,
        "_prepare_for_continuation",
        lambda value: value,
    )
    monkeypatch.setattr(
        adaptive,
        "_join_html_continuation",
        lambda base, continuation: continuation,
    )
    monkeypatch.setattr(
        adaptive,
        "_validate_html",
        lambda html, request: problem_for(html),
    )


def test_identical_html_and_problem_stop_before_third_call(
    tmp_path,
    monkeypatch,
):
    recovered = _installed_recovery(monkeypatch)
    problem = "snake controls allow unstable 180-degree reversal"
    _patch_complete_rewrites(
        monkeypatch,
        lambda html: problem,
    )

    calls = []
    messages = []

    def ask(prompt):
        calls.append(prompt)
        return SimpleNamespace(text=HTML_A)

    result = recovered(
        ask=ask,
        original_request="make a snake game",
        workspace=tmp_path,
        progress=messages.append,
    )

    assert result is None
    assert len(calls) == 2
    assert any(
        "before another provider call" in message
        and "1 completed attempt(s)" in message
        and problem in message
        for message in messages
    )


def test_changed_html_allows_another_provider_call(
    tmp_path,
    monkeypatch,
):
    recovered = _installed_recovery(monkeypatch)
    problem = "same validation problem"
    _patch_complete_rewrites(
        monkeypatch,
        lambda html: problem,
    )

    responses = iter([HTML_A, HTML_B, HTML_B])
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return SimpleNamespace(text=next(responses))

    recovered(
        ask=ask,
        original_request="make a browser game",
        workspace=tmp_path,
        progress=lambda message: None,
    )

    assert len(calls) == 3


def test_changed_problem_changes_semantic_state():
    first = _semantic_repair_state(
        HTML_A,
        "first problem",
    )
    second = _semantic_repair_state(
        HTML_A,
        "second problem",
    )

    assert first != second


def test_whitespace_only_document_change_is_not_progress():
    first = _semantic_repair_state(
        HTML_A,
        "same problem",
    )
    second = _semantic_repair_state(
        "  " + HTML_A.replace("><", ">   <") + "  ",
        "  SAME   PROBLEM ",
    )

    assert first == second


def test_maximum_continuation_limit_is_preserved():
    assert MAX_CONTINUATIONS == 6
