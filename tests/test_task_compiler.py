from sophyane.task_compiler import (
    compile_task,
    should_compile_task,
)
from sophyane.task_execution import (
    validate_generated_source,
)


def test_simple_latest_email_does_not_compile() -> None:
    assert (
        should_compile_task(
            "show my latest email"
        )
        is False
    )

    assert (
        compile_task(
            "show my latest email"
        )
        is None
    )


def test_complex_correspondent_task_compiles() -> None:
    task = compile_task(
        "Determine the five people I communicate with "
        "most frequently by email over the last 90 days. "
        "Show received count, sent count and total messages."
    )

    assert task is not None
    assert (
        task.task_id
        == "gmail-top-correspondents"
    )

    assert task.source_kind == "gmail_imap"
    assert task.privileges == ("read",)
    assert task.ephemeral is True


def test_generated_email_task_has_no_embedded_secret() -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "and show received count and sent count."
    )

    assert task is not None

    source = task.source_code.lower()

    assert "app_password =" not in source
    assert "sophyane_imap_app_password" in source


def test_generated_email_task_passes_static_gate() -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "and show received count and sent count."
    )

    assert task is not None

    assert (
        validate_generated_source(
            task
        )
        == []
    )


def test_mutating_email_request_is_not_compiled() -> None:
    assert (
        compile_task(
            "send an email to Alice"
        )
        is None
    )
