from sophyane.connectors.runtime import (
    resolve_connector_op,
    try_connector_reply,
)


def test_unresolved_reply_analysis_is_not_outbound(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.connectors.runtime.run_connector",
        lambda *_args, **_kwargs: {
            "ok": True,
            "formatted": "ANALYSIS_OK",
        },
    )

    result = try_connector_reply(
        "Inspect my Inbox and Sent Mail for the last 90 days "
        "and determine whether I subsequently replied."
    )

    assert result == "ANALYSIS_OK"
    assert "cannot send" not in result.lower()


def test_missing_later_reply_is_read_only_analysis(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.connectors.runtime.run_connector",
        lambda *_args, **_kwargs: {
            "ok": True,
            "formatted": "READ_ONLY_ANALYSIS",
        },
    )

    result = try_connector_reply(
        "Search Inbox and Sent Mail and identify conversations "
        "where I cannot find a later sent reply from me."
    )

    assert result == "READ_ONLY_ANALYSIS"


def test_attachment_query_resolves_to_connector() -> None:
    match = resolve_connector_op(
        "Find my five most recent emails containing attachments."
    )

    assert match is not None


def test_classification_query_resolves_to_connector() -> None:
    match = resolve_connector_op(
        "Analyze my last 200 received emails and classify them."
    )

    assert match is not None


def test_cross_mailbox_query_resolves_to_connector() -> None:
    match = resolve_connector_op(
        "Search Inbox and Sent Mail for messages involving "
        "the same people."
    )

    assert match is not None


def test_explicit_send_remains_blocked() -> None:
    result = try_connector_reply(
        "Send an email to owner@example.com saying hello."
    )

    assert result is not None
    assert "read-only" in result.lower()
    assert "cannot send" in result.lower()



def test_received_messages_never_replied_is_email_analysis(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.connectors.runtime.run_connector",
        lambda *_args, **_kwargs: {
            "ok": True,
            "formatted": "READ_ONLY_ANALYSIS",
        },
    )

    result = try_connector_reply(
        "Find messages I received but never replied to."
    )

    assert result == "READ_ONLY_ANALYSIS"



def test_classify_last_200_routes_to_analyze(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(
        connector_id,
        op,
        *,
        args,
        profile=None,
    ):
        calls.append((connector_id, op))
        return {
            "ok": True,
            "formatted": "ANALYSIS_OK",
        }

    monkeypatch.setattr(
        "sophyane.connectors.runtime.run_connector",
        fake_run,
    )

    result = try_connector_reply(
        "Analyze my last 200 received emails and classify them."
    )

    assert result == "ANALYSIS_OK"
    assert calls == [
        ("email.imap", "analyze")
    ]


def test_first_received_email_uses_first_connector_operation() -> None:
    match = resolve_connector_op("what is the first email i received?")

    assert match is not None
    assert (match.connector_id, match.op) == ("email.imap", "first")
