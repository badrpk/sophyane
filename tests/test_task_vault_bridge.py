import sophyane.task_orchestrator as orch

from sophyane.task_compiler import (
    compile_task,
)


def test_gmail_compiled_task_resolves_runtime_credentials(
    monkeypatch,
) -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "with received count and sent count."
    )

    assert task is not None

    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler._creds",
        lambda _profile: (
            "owner@gmail.com",
            "abcdefghijklmnop",
            "imap.gmail.com",
            993,
        ),
    )

    env = orch._compiled_task_runtime_env(
        task,
        profile="owner@gmail.com",
    )

    assert (
        env["SOPHYANE_IMAP_USER"]
        == "owner@gmail.com"
    )

    assert (
        env[
            "SOPHYANE_IMAP_APP_PASSWORD"
        ]
        == "abcdefghijklmnop"
    )

    assert (
        env["SOPHYANE_IMAP_HOST"]
        == "imap.gmail.com"
    )

    assert (
        env["SOPHYANE_IMAP_PORT"]
        == "993"
    )


def test_runtime_secret_is_not_in_generated_source(
    monkeypatch,
) -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "with received count and sent count."
    )

    assert task is not None

    secret = "abcdefghijklmnop"

    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler._creds",
        lambda _profile: (
            "owner@gmail.com",
            secret,
            "imap.gmail.com",
            993,
        ),
    )

    env = orch._compiled_task_runtime_env(
        task,
        profile="owner@gmail.com",
    )

    assert env[
        "SOPHYANE_IMAP_APP_PASSWORD"
    ] == secret

    assert secret not in task.source_code


def test_non_gmail_task_gets_no_email_secret_env() -> None:
    class DummyTask:
        source_kind = "filesystem"

    assert (
        orch._compiled_task_runtime_env(
            DummyTask(),
            profile="default",
        )
        == {}
    )


def test_orchestrator_passes_vault_env_to_executor(
    monkeypatch,
) -> None:
    captured = {}

    monkeypatch.setattr(
        orch,
        "_compiled_task_runtime_env",
        lambda _task, profile=None: {
            "SOPHYANE_IMAP_USER":
                "owner@gmail.com",

            "SOPHYANE_IMAP_APP_PASSWORD":
                "abcdefghijklmnop",

            "SOPHYANE_IMAP_HOST":
                "imap.gmail.com",

            "SOPHYANE_IMAP_PORT":
                "993",
        },
    )

    def fake_execute(
        task,
        *,
        env=None,
    ):
        captured.update(
            env or {}
        )

        return {
            "ok": True,
            "payload": {
                "ok": True,
                "source":
                    "gmail_imap_all_mail",
                "window_days": 90,
                "messages_scanned": 10,
                "contacts": [],
            },
        }

    monkeypatch.setattr(
        orch,
        "execute_compiled_task",
        fake_execute,
    )

    result = (
        orch.try_compiled_task_reply(
            "Determine my top five email correspondents "
            "with received count and sent count.",
            profile="owner@gmail.com",
        )
    )

    assert result is not None

    assert captured[
        "SOPHYANE_IMAP_USER"
    ] == "owner@gmail.com"

    assert captured[
        "SOPHYANE_IMAP_APP_PASSWORD"
    ] == "abcdefghijklmnop"
