from __future__ import annotations

import pytest

from sophyane.runtime_capability_acquisition_patch import (
    _is_editable_session_request,
    _is_repository_coding_request,
)


@pytest.mark.parametrize(
    "user_text",
    [
        (
            "Modify the Python source code and tests in the currently "
            "attached ~/sophyane repository. Fix visual capability routing."
        ),
        (
            "Inspect src/sophyane/runtime_capability_acquisition_patch.py "
            "and add pytest regression tests for editable canvas routing."
        ),
        (
            "Improve this software project so a repository request mentioning "
            "visual, image, canvas, website and editable does not open a scene."
        ),
        (
            "Refactor the codebase and run the test suite. Do not create an "
            "HTML preview or editable visual session."
        ),
        (
            "Patch the Python code in src/ and tests/ for production use."
        ),
    ],
)
def test_repository_requests_override_visual_keywords(user_text: str) -> None:
    assert _is_repository_coding_request(user_text) is True
    assert _is_editable_session_request(user_text) is False


@pytest.mark.parametrize(
    "user_text",
    [
        "Create an editable portrait with undo and redo",
        "Make a logo with layers and a live preview",
        "Design a visual poster that I can continue editing",
        "Generate an editable canvas illustration",
    ],
)
def test_genuine_editable_visual_requests_still_activate(
    user_text: str,
) -> None:
    assert _is_repository_coding_request(user_text) is False
    assert _is_editable_session_request(user_text) is True


@pytest.mark.parametrize(
    "user_text",
    [
        "Explain visual design principles",
        "What is a canvas?",
        "Describe an editable document",
        "How does pytest work?",
    ],
)
def test_non_execution_conversation_does_not_activate_canvas(
    user_text: str,
) -> None:
    assert _is_editable_session_request(user_text) is False


def test_building_canvas_software_is_a_coding_request() -> None:
    request = (
        "Build a Python project in this repository implementing an editable "
        "canvas application and add tests under tests/."
    )

    assert _is_repository_coding_request(request) is True
    assert _is_editable_session_request(request) is False


@pytest.mark.parametrize(
    "user_text",
    [
        "Explain Canva and canvas differences",
        "What does editable canvas mean?",
        "Describe poster design principles",
        "How do visual layers work?",
        "Can you explain how to make a logo?",
        "What is portrait design?",
    ],
)
def test_explanatory_visual_language_never_starts_session(
    user_text: str,
) -> None:
    assert _is_editable_session_request(user_text) is False


@pytest.mark.parametrize(
    "user_text",
    [
        "Please design a poster",
        "Create a visual logo",
        "Make an editable canvas",
        "Generate a portrait with live preview",
        "Draw an illustration that I can continue editing",
    ],
)
def test_explicit_visual_creation_still_starts_session(
    user_text: str,
) -> None:
    assert _is_editable_session_request(user_text) is True
