"""Compile, execute and validate complex Sophyane tasks."""

from __future__ import annotations

import json
import re
from typing import Any

from sophyane.task_compiler import (
    compile_task,
)
from sophyane.task_execution import (
    execute_compiled_task,
)
from sophyane.task_validation import (
    validate_task_result,
)


def _window_days(
    request: str,
) -> int:
    text = request.lower()

    match = re.search(
        r"(?:last|past)\s+"
        r"(\d+)\s+days?",
        text,
    )

    if match:
        return max(
            1,
            min(
                int(match.group(1)),
                3650,
            ),
        )

    match = re.search(
        r"(?:last|past)\s+"
        r"(\d+)\s+months?",
        text,
    )

    if match:
        return max(
            1,
            min(
                int(match.group(1))
                * 30,
                3650,
            ),
        )

    return 90


def _result_limit(
    request: str,
) -> int:
    text = request.lower()

    if (
        "five people" in text
        or "top five" in text
        or "top 5" in text
    ):
        return 5

    match = re.search(
        r"\btop\s+(\d+)\b",
        text,
    )

    if match:
        return max(
            1,
            min(
                int(match.group(1)),
                100,
            ),
        )

    return 10


def _format_contacts(
    payload: dict[str, Any],
) -> str:
    contacts = payload.get(
        "contacts",
        [],
    )

    lines = [
        "┌─ Compiled Gmail analysis",
        (
            "│ Source: "
            + str(
                payload.get(
                    "source",
                    "unknown",
                )
            )
        ),
        (
            "│ Window: "
            + str(
                payload.get(
                    "window_days",
                    "?",
                )
            )
            + " days"
        ),
        (
            "│ Messages scanned: "
            + str(
                payload.get(
                    "messages_scanned",
                    0,
                )
            )
        ),
    ]

    for index, contact in enumerate(
        contacts,
        start=1,
    ):
        lines.append(
            "│ "
            f"{index}. "
            f"{contact.get('email', '')} | "
            f"received={contact.get('received', 0)} | "
            f"sent={contact.get('sent', 0)} | "
            f"total={contact.get('total', 0)}"
        )

    lines.append("└─")

    return "\n".join(lines)


def _compiled_task_runtime_env(
    task,
    *,
    profile: str | None = None,
) -> dict[str, str]:
    """Resolve runtime-only secrets required by a compiled task.

    Secret values are never added to generated source or result
    payloads. They exist only in the environment of the temporary
    child process.
    """
    env: dict[str, str] = {}

    if task.source_kind != "gmail_imap":
        return env

    resolved_profile = profile

    if not resolved_profile or resolved_profile == "default":
        try:
            from sophyane.email_account_registry import (
                active_profile,
            )

            resolved_profile = active_profile()

        except Exception:
            resolved_profile = (
                profile
                or "default"
            )

    # Reuse the authoritative connector credential resolution:
    # shell environment first, then Sophyane local vault.
    from sophyane.connectors.email_imap.handler import (
        _creds,
    )

    user, password, host, port = _creds(
        str(
            resolved_profile
            or "default"
        )
    )

    if not user or not password:
        return env

    env.update(
        {
            "SOPHYANE_IMAP_USER":
                str(user),

            "SOPHYANE_IMAP_APP_PASSWORD":
                str(password),

            "SOPHYANE_IMAP_HOST":
                str(host),

            "SOPHYANE_IMAP_PORT":
                str(port),
        }
    )

    return env


def try_compiled_task_reply(
    request: str,
    *,
    profile: str | None = None,
) -> str | None:
    task = compile_task(
        request
    )

    if task is None:
        return None

    env = {
        "SOPHYANE_TASK_WINDOW_DAYS":
            str(
                _window_days(
                    request
                )
            ),
        "SOPHYANE_TASK_RESULT_LIMIT":
            str(
                _result_limit(
                    request
                )
            ),
    }

    # Inject credentials only into the temporary subprocess
    # environment. Nothing is added to generated source or its
    # persistent workspace files.
    env.update(
        _compiled_task_runtime_env(
            task,
            profile=profile,
        )
    )

    result = execute_compiled_task(
        task,
        env=env,
    )

    if not result.get("ok"):
        error = str(
            result.get(
                "error",
                "compiled_task_failed",
            )
        )

        # Allow existing deterministic Sophyane paths to
        # handle missing credentials/configuration rather
        # than hiding them behind compiler machinery.
        if error in {
            "task_failed",
            "source_validation_failed",
        }:
            return None

        return (
            "Compiled task failed: "
            + error
        )

    payload = result.get(
        "payload"
    )

    validation_errors = (
        validate_task_result(
            task,
            payload,
        )
    )

    if validation_errors:
        return (
            "Compiled task result validation failed: "
            + ", ".join(
                validation_errors
            )
        )

    if task.task_id == (
        "gmail-top-correspondents"
    ):
        return _format_contacts(
            payload
        )

    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )


__all__ = [
    "try_compiled_task_reply",
]
