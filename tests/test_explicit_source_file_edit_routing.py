from sophyane.tui_v2 import (
    _execution_requested,
)


def test_exact_jsx_asset_edit_is_execution():
    request = (
        "Update dead image URLs in Footer.jsx and "
        "HeroBanner.jsx with active CDN assets, and "
        "add fallback alt tags to prevent layout shifts."
    )

    assert (
        _execution_requested(
            request
        )
        is True
    )


def test_edit_named_jsx_is_execution():
    assert (
        _execution_requested(
            "Edit Footer.jsx."
        )
        is True
    )


def test_named_tsx_edit_is_execution():
    assert (
        _execution_requested(
            "Edit HeroBanner.tsx and replace its broken asset URL."
        )
        is True
    )


def test_named_css_edit_is_execution():
    assert (
        _execution_requested(
            "Fix styles.css so the banner does not shift."
        )
        is True
    )


def test_named_python_edit_is_execution():
    assert (
        _execution_requested(
            "Edit test.py so that it prints hello."
        )
        is True
    )


def test_question_about_named_source_file_remains_chat():
    assert (
        _execution_requested(
            "What is Footer.jsx?"
        )
        is False
    )


def test_explanation_about_named_source_file_remains_chat():
    assert (
        _execution_requested(
            "Explain HeroBanner.jsx."
        )
        is False
    )


def test_generic_media_request_is_not_promoted():
    assert (
        _execution_requested(
            "Show me an image of a snake."
        )
        is False
    )
