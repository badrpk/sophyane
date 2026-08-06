from pathlib import Path

from sophyane.sli_personal_connector import (
    run_personal_connector,
)


def test_private_connector_records_goal_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler.execute",
        lambda **_kwargs: {
            "ok": True,
            "from": "Sender <sender@example.com>",
            "to": "Owner <owner@gmail.com>",
            "subject": "Action required",
            "word_count": 4,
            "body": "Please review the attached result.",
            "formatted": (
                "┌─ Latest email\n"
                "├─ Preview\n"
                "│ Please review the attached result.\n"
                "└─"
            ),
        },
    )
    monkeypatch.setattr(
        "sophyane.sli_personal_connector."
        "_open_dashboard",
        lambda _workspace, _payload: "",
    )
    monkeypatch.setattr(
        "sophyane.goal_completion_dialogue."
        "continue_private_goal",
        lambda _payload, search_callback=None: {
            "asked": True,
            "resolved": True,
            "action": "confirmed_complete",
            "summary": "The user confirmed completion.",
        },
    )

    report = run_personal_connector(
        "what was my last email?",
        tmp_path,
    )

    assert "Goal completion:" in report
    assert "Resolved" in report
    assert "Action: confirmed_complete" in report
    assert "The user confirmed completion." in report
