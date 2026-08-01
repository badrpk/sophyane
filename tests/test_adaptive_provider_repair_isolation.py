from __future__ import annotations

from sophyane.adaptive_execution import _compact_repair_prompt


def test_repair_prompt_does_not_trigger_message_connectors() -> None:
    prompt = _compact_repair_prompt(
        "Create a FastAPI application and run tests.",
        [],
        "Provider returned a Markdown plan.",
    )

    lowered = prompt.casefold()

    # These words previously activated an unrelated connector route.
    assert "gmail" not in lowered
    assert "imap" not in lowered
    assert "draft an email" not in lowered

    assert "return exactly one valid json object" in lowered
    assert "original task" in lowered
    assert "execution contract" in lowered


def test_repair_prompt_preserves_original_task() -> None:
    task = (
        "Create a complete FastAPI TODO application with authentication, "
        "SQLite, tests, Dockerfile, GitHub Actions, and README."
    )

    prompt = _compact_repair_prompt(
        task,
        ["app/database.py"],
        "Non-executable response.",
    )

    assert task in prompt
    assert "app/database.py" in prompt
    assert "single next unfinished action" in prompt
