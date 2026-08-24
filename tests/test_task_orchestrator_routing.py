import sophyane.task_orchestrator as orch


def test_compiled_task_formats_valid_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        orch,
        "execute_compiled_task",
        lambda *_args, **_kwargs: {
            "ok": True,
            "payload": {
                "ok": True,
                "source": "gmail_imap_all_mail",
                "window_days": 90,
                "messages_scanned": 1000,
                "contacts": [
                    {
                        "email": "a@example.com",
                        "received": 8,
                        "sent": 2,
                        "total": 10,
                    }
                ],
            },
        },
    )

    result = orch.try_compiled_task_reply(
        "Determine the five people I communicate with "
        "most frequently by email over the last 90 days. "
        "Show received count, sent count and total messages."
    )

    assert result is not None
    assert "Compiled Gmail analysis" in result
    assert "a@example.com" in result
    assert "Messages scanned: 1000" in result


def test_simple_task_declines_compiler() -> None:
    assert (
        orch.try_compiled_task_reply(
            "show my latest email"
        )
        is None
    )
