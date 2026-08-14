from __future__ import annotations

from sophyane.adaptive_execution import (
    _full_stack_initial_bundle_prompt,
    _full_stack_next_increment_prompt,
)


def test_initial_full_stack_prompt_requests_only_backend() -> None:
    prompt = _full_stack_initial_bundle_prompt(
        "Build a full-stack task application."
    )

    assert "backend/app.py" in prompt

    assert "static/index.html only" not in prompt
    assert '"files"' not in prompt

    assert (
        "No multiple files"
        in prompt
    )

    assert (
        "Do not generate frontend files"
        in prompt
    )


def test_initial_prompt_is_materially_smaller_than_old_bundle() -> None:
    prompt = _full_stack_initial_bundle_prompt(
        "Build a responsive full-stack task management "
        "web application with REST API, SQLite persistence, "
        "CRUD, validation, dashboard statistics, "
        "search/filtering and automated tests."
    )

    print(
        "INITIAL_PROMPT_CHARS:",
        len(prompt),
    )

    assert len(prompt) < 1800


def test_next_increment_sequence_is_deterministic() -> None:
    request = "Build a task app."

    prompt = _full_stack_next_increment_prompt(
        request,
        ["backend/app.py"],
    )

    assert prompt is not None
    assert "static/index.html only" in prompt

    prompt = _full_stack_next_increment_prompt(
        request,
        [
            "backend/app.py",
            "static/index.html",
        ],
    )

    assert prompt is not None
    assert "static/app.js only" in prompt

    prompt = _full_stack_next_increment_prompt(
        request,
        [
            "backend/app.py",
            "static/index.html",
            "static/app.js",
        ],
    )

    assert prompt is not None
    assert "static/style.css only" in prompt


def test_tests_follow_runtime_artifacts() -> None:
    prompt = _full_stack_next_increment_prompt(
        "Build app",
        [
            "backend/app.py",
            "static/index.html",
            "static/app.js",
            "static/style.css",
        ],
    )

    assert prompt is not None
    assert "tests/test_app.py only" in prompt


def test_manifest_completion_returns_none() -> None:
    prompt = _full_stack_next_increment_prompt(
        "Build app",
        [
            "backend/app.py",
            "static/index.html",
            "static/app.js",
            "static/style.css",
            "tests/test_app.py",
            "README.md",
        ],
    )

    assert prompt is None
