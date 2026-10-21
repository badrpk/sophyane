import pytest

from sophyane.core_controller.models import ControllerContext, ControllerRequest, ModeName
from sophyane.core_controller.selection import ModeSelection, select_mode


ALL_MODES = tuple(ModeName)


def test_explicit_mode_has_highest_precedence():
    result = select_mode(
        ControllerRequest(text="inspect", requested_mode=ModeName.LOCAL_LLM),
        ControllerContext(available_modes=ALL_MODES, session_mode=ModeName.RACE),
        classifier=lambda _request: ModeName.EXTERNAL_LLM,
    )
    assert result == ModeSelection(ModeName.LOCAL_LLM, "explicit")


def test_bound_session_mode_beats_classifier():
    result = select_mode(
        ControllerRequest(text="continue"),
        ControllerContext(available_modes=ALL_MODES, session_mode=ModeName.SLI_GRAPH),
        classifier=lambda _request: ModeName.RACE,
    )
    assert result == ModeSelection(ModeName.SLI_GRAPH, "session")


def test_classifier_is_used_when_no_explicit_or_session_mode_exists():
    result = select_mode(
        ControllerRequest(text="compare solutions"),
        ControllerContext(available_modes=ALL_MODES),
        classifier=lambda _request: ModeName.RACE,
    )
    assert result == ModeSelection(ModeName.RACE, "classifier")


def test_ordinary_chat_defaults_to_human_conversation():
    result = select_mode(
        ControllerRequest(text="hello"),
        ControllerContext(available_modes=ALL_MODES),
        classifier=lambda _request: None,
    )
    assert result == ModeSelection(ModeName.HUMAN_CONVERSATION, "default")


def test_unavailable_explicit_mode_fails_closed():
    with pytest.raises(ValueError, match="mode unavailable"):
        select_mode(
            ControllerRequest(text="run locally", requested_mode=ModeName.LOCAL_LLM),
            ControllerContext(available_modes=(ModeName.EXTERNAL_LLM,)),
        )


def test_invalid_classifier_result_fails_closed():
    with pytest.raises(ValueError, match="mode unavailable"):
        select_mode(
            ControllerRequest(text="unknown"),
            ControllerContext(available_modes=(ModeName.HUMAN_CONVERSATION,)),
            classifier=lambda _request: ModeName.RACE,
        )


def test_selection_is_deterministic_for_identical_input():
    request = ControllerRequest(text="same")
    context = ControllerContext(available_modes=ALL_MODES)
    assert select_mode(request, context) == select_mode(request, context)
