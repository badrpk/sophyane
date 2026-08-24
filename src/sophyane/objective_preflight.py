"""Deterministic preflight for original Sophyane user objectives.

This layer runs before provider/LLM consultation.

Contract:
- consume the original user request, not an LLM rewrite;
- preserve existing deterministic connector routing;
- allow the bounded task compiler to solve supported workloads;
- refuse mixed read+mutation email objectives before provider routing;
- return None when Sophyane should continue to its normal reasoning path.
"""

from __future__ import annotations

import re

from sophyane.connectors.runtime import (
    try_connector_reply,
)


_EMAIL_CONTEXT = re.compile(
    r"\b(?:email|emails|mail|gmail|inbox|"
    r"correspondent|correspondents)\b",
    re.I,
)

_MUTATION = re.compile(
    r"\b(?:delete|remove|erase|move|rename|"
    r"send|forward|reply\s+to|reply\s+automatically|"
    r"mark\s+as|archive|trash|expunge)\b",
    re.I,
)


def preflight_original_request(
    request: str,
    *,
    profile: str | None = None,
) -> str | None:
    raw = str(
        request
        or ""
    ).strip()

    if not raw:
        return None

    # Mixed analytical + mutating email requests must never be
    # softened into a read request by an LLM or semantic rewrite.
    if (
        _EMAIL_CONTEXT.search(raw)
        and _MUTATION.search(raw)
    ):
        return (
            "This request includes an email mutation action, "
            "but the configured Gmail capability is read-only. "
            "No messages were changed."
        )

    # Existing connector runtime now includes:
    # - simple deterministic IMAP operations;
    # - advanced email analyzer;
    # - compiled task routing.
    #
    # Therefore this is the single deterministic front door.
    return try_connector_reply(
        raw,
        profile=profile,
    )


__all__ = [
    "preflight_original_request",
]
