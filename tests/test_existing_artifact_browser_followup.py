from __future__ import annotations

from sophyane.runtime_sli_brain import _route
from sophyane.sli_intent_router import classify_intent


def test_open_this_in_browser_is_project_continuation():
    decision = classify_intent(
        "open this in browser",
        has_project=True,
    )

    assert decision.route == "continue_project"


def test_open_it_is_project_continuation():
    decision = classify_intent(
        "open it",
        has_project=True,
    )

    assert decision.route == "continue_project"


def test_preview_this_is_project_continuation():
    decision = classify_intent(
        "preview this",
        has_project=True,
    )

    assert decision.route == "continue_project"


def test_show_this_in_browser_is_project_continuation():
    decision = classify_intent(
        "show this in browser",
        has_project=True,
    )

    assert decision.route == "continue_project"


def test_sli_brain_browser_followup_precedes_generic_execution():
    assert (
        _route(
            "open this in browser",
            has_project=True,
        )
        == "continue_project"
    )


def test_sli_brain_preview_followup_precedes_generic_execution():
    assert (
        _route(
            "preview it in browser",
            has_project=True,
        )
        == "continue_project"
    )


def test_new_browser_request_without_project_is_not_continuation():
    assert (
        _route(
            "open browser",
            has_project=False,
        )
        != "continue_project"
    )
