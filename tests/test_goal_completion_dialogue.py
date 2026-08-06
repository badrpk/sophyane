from sophyane.goal_completion_dialogue import (
    continue_private_goal,
    redact_sensitive_text,
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


def test_noninteractive_result_does_not_block(
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


def test_show_full_then_finish_stays_in_same_session(
    monkeypatch,
) -> None:
    answers = iter([
        "1",  # show full
        "3",  # finish: full, open, finish, defer
    ])

    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )

    result = continue_private_goal(
        _payload()
    )

    assert result["resolved"] is True
    assert result["action"] == "confirmed_complete"
    assert result["actions"] == [
        {
            "action": "full_message_shown",
            "success": True,
        }
    ]


def test_open_link_then_finish_stays_in_same_session(
    monkeypatch,
) -> None:
    answers = iter([
        "2",  # open link
        "3",  # finish
    ])

    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue._open_url",
        lambda _url: True,
    )

    result = continue_private_goal(
        _payload()
    )

    assert result["resolved"] is True
    assert result["action"] == "confirmed_complete"
    assert result["actions"][0]["action"] == "link_opened"


def test_related_search_then_finish(
    monkeypatch,
) -> None:
    answers = iter([
        "3",  # related: full, open, related, finish, defer
        "4",  # finish
    ])

    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": next(answers),
    )

    queries: list[str] = []

    def search(query: str) -> dict:
        queries.append(query)

        return {
            "ok": True,
            "matches": 2,
            "formatted": "Two related messages found.",
        }

    result = continue_private_goal(
        _payload(),
        search_callback=search,
    )

    assert result["resolved"] is True
    assert queries
    assert (
        result["actions"][0]["action"]
        == "related_emails_searched"
    )


def test_defer_leaves_goal_unresolved(
    monkeypatch,
) -> None:
    # With full, open, related, finish and defer: defer is 5.
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "sys.stdin.isatty",
        lambda: True,
    )
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


def test_secret_like_tokens_are_masked() -> None:
    token = (
        "AQ.Ab8RN6Jl75fbM1VpPdMV3Rj"
        "-zZxbVwezhOokIbTFs1V-Qik0dQ"
    )

    redacted = redact_sensitive_text(token)

    assert token not in redacted
    assert "[REDACTED]" in redacted


def test_notification_email_token_is_removed() -> None:
    value = (
        "https://github.com/settings/notifications"
        "?email_token=THISISALONGPRIVATEEMAILTOKEN123456"
    )

    redacted = redact_sensitive_text(value)

    assert "THISISALONGPRIVATEEMAILTOKEN123456" not in redacted
    assert "email_token=[REDACTED]" in redacted
