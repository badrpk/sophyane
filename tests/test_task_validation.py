from sophyane.task_compiler import (
    compile_task,
)
from sophyane.task_validation import (
    validate_task_result,
)


def test_valid_compiled_payload() -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "with received count and sent count."
    )

    assert task is not None

    payload = {
        "ok": True,
        "source": "gmail_imap_all_mail",
        "window_days": 90,
        "messages_scanned": 123,
        "contacts": [],
    }

    assert (
        validate_task_result(
            task,
            payload,
        )
        == []
    )


def test_invalid_payload_is_rejected() -> None:
    task = compile_task(
        "Determine my top five email correspondents "
        "with received count and sent count."
    )

    assert task is not None

    errors = validate_task_result(
        task,
        {
            "ok": True,
        },
    )

    assert errors
