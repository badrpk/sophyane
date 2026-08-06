from pathlib import Path

from sophyane.goal_completion_dialogue import (
    continue_private_goal,
)


def _payload() -> dict:
    return {
        "ok": True,
        "from": "GitHub <notifications@github.com>",
        "to": "owner@gmail.com",
        "subject": "[repo] Run failed: CI",
        "body": (
            "The CI run failed.\n"
            "View results: "
            "https://github.com/example/repo/actions/runs/123"
        ),
        "preview": "The CI run failed.",
    }


def test_noninteractive_result_completes_without_blocking(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: False,
    )

    result = continue_private_goal(
        _payload()
    )

    assert result["asked"] is False
    assert result["resolved"] is True
    assert result["action"] == "message_displayed"


def test_user_can_confirm_goal_complete(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": "1",
    )

    result = continue_private_goal(
        _payload()
    )

    assert result["asked"] is True
    assert result["resolved"] is True
    assert result["action"] == "confirmed_complete"


def test_user_can_request_complete_message(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": "2",
    )

    result = continue_private_goal(
        _payload()
    )

    assert result["resolved"] is True
    assert result["action"] == "full_message_shown"
    assert "CI run failed" in result["body"]


def test_user_can_search_related_emails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )

    # Options are:
    # 1 done, 2 full message, 3 open URL, 4 related emails.
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": "4",
    )

    queries: list[str] = []

    def search(query: str) -> dict:
        queries.append(query)

        return {
            "ok": True,
            "matches": 2,
            "formatted": "Two related CI emails found.",
        }

    result = continue_private_goal(
        _payload(),
        search_callback=search,
    )

    assert result["resolved"] is True
    assert result["action"] == "related_emails_searched"
    assert queries


def test_user_can_defer_resolution(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )

    # With URL and search callback, defer is option 5.
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": "5",
    )

    result = continue_private_goal(
        _payload(),
        search_callback=lambda _query: {
            "ok": True,
        },
    )

    assert result["resolved"] is False
    assert result["action"] == "deferred"
