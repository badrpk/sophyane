from pathlib import Path

from sophyane.adaptive_execution import _browser_request


SOURCE = Path(
    "src/sophyane/runtime_intent_refinement_patch.py"
)


def _source():
    return SOURCE.read_text(encoding="utf-8")


def test_explicit_browser_game_direct_dispatch_precedes_refinement():
    source = _source()

    direct = source.index(
        "SOPHYANE_EXPLICIT_BROWSER_GAME_DIRECT_CAPABILITY_V1"
    )
    refinement = source.index(
        "refined_result = _confirm_refinement"
    )

    assert direct < refinement


def test_direct_dispatch_starts_without_planning_output():
    source = _source()
    start = source.index(
        "SOPHYANE_EXPLICIT_BROWSER_GAME_DIRECT_CAPABILITY_V1"
    )
    end = source.index(
        "SOPHYANE_DIRECT_CHAT_REFINEMENT_BYPASS_V1",
        start,
    )
    section = source[start:end]

    assert 'initial_text=""' in section
    assert "tui_v2.run_structured_loop(" in section
    assert "refinement calls: 0" in section
    assert "planning calls: 0" in section


def test_browser_game_classifier_accepts_snake_request():
    assert _browser_request(
        "make a snake game and let me play it in browser"
    )


def test_direct_dispatch_has_full_stack_exclusions():
    source = _source()
    start = source.index(
        "SOPHYANE_EXPLICIT_BROWSER_GAME_DIRECT_CAPABILITY_V1"
    )
    end = source.index(
        "SOPHYANE_DIRECT_CHAT_REFINEMENT_BYPASS_V1",
        start,
    )
    section = source[start:end]

    for marker in (
        '" full-stack "',
        '" full stack "',
        '" fastapi "',
        '" backend "',
        '" database "',
        '" sqlite "',
        '" api "',
    ):
        assert marker in section

def test_existing_project_does_not_disable_browser_game_shortcut():
    source = _source()
    start = source.index(
        "SOPHYANE_EXPLICIT_BROWSER_GAME_DIRECT_CAPABILITY_V1"
    )
    end = source.index(
        "SOPHYANE_DIRECT_CHAT_REFINEMENT_BYPASS_V1",
        start,
    )
    section = source[start:end]

    assert "_project_continuation" not in section
    assert "_direct_browser_game" in section
    assert "tui_v2.run_structured_loop(" in section

