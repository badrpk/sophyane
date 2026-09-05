"""Session-local grounded document context.

This module remembers document identity and already-grounded text for the
current Sophyane process/session.

It deliberately does not:
- call an LLM;
- select a Sophyane mode;
- create charts;
- invent document content;
- persist secrets to global memory automatically.

The context is an execution convenience layer only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Iterable

from sophyane.document_grounding import (
    GroundedDocument,
)


# SOPHYANE_DOCUMENT_SESSION_CONTEXT_V1


@dataclass(frozen=True)
class SessionDocumentReference:
    path: str
    kind: str
    source: str
    text: str


_LOCK = threading.RLock()

_CURRENT_DOCUMENT: (
    SessionDocumentReference
    | None
) = None


def remember_grounded_document(
    document: GroundedDocument,
) -> SessionDocumentReference:
    """Remember one already-grounded document for follow-up turns."""

    global _CURRENT_DOCUMENT

    reference = SessionDocumentReference(
        path=str(
            Path(
                document.path
            ).expanduser().resolve()
        ),
        kind=str(
            document.kind
            or ""
        ),
        source=str(
            document.source
            or ""
        ),
        text=str(
            document.text
            or ""
        ),
    )

    with _LOCK:
        _CURRENT_DOCUMENT = (
            reference
        )

    return reference


def remember_grounded_documents(
    documents: Iterable[
        GroundedDocument
    ],
) -> SessionDocumentReference | None:
    """Remember the last grounded document from an import operation."""

    latest = None

    for document in documents:
        latest = (
            remember_grounded_document(
                document
            )
        )

    return latest


def current_document() -> SessionDocumentReference | None:
    with _LOCK:
        return (
            _CURRENT_DOCUMENT
        )


def clear_current_document() -> None:
    global _CURRENT_DOCUMENT

    with _LOCK:
        _CURRENT_DOCUMENT = None


def has_current_document() -> bool:
    return (
        current_document()
        is not None
    )


_REFERENCE_PATTERNS = (
    " it",
    " it?",
    " this document",
    " the document",
    " this pdf",
    " the pdf",
    " this file",
    " the file",
    " imported document",
    " imported file",
    " that document",
    " that pdf",
)


def request_refers_to_current_document(
    request: str,
) -> bool:
    """Conservatively detect follow-up references to imported content."""

    text = (
        " "
        + str(
            request
            or ""
        ).strip().casefold()
        + " "
    )

    if not text.strip():
        return False

    return any(
        pattern in text
        for pattern in _REFERENCE_PATTERNS
    )


def augment_request_with_current_document(
    request: str,
    *,
    require_reference: bool = True,
    max_chars: int = 24000,
) -> tuple[
    str,
    SessionDocumentReference | None,
]:
    """Append grounded session document text to a follow-up request."""

    original = str(
        request
        or ""
    )

    document = (
        current_document()
    )

    if document is None:
        return (
            original,
            None,
        )

    if (
        require_reference
        and not request_refers_to_current_document(
            original
        )
    ):
        return (
            original,
            None,
        )

    text = str(
        document.text
        or ""
    ).strip()

    if not text:
        return (
            original,
            None,
        )

    bounded = text[
        :max(
            1,
            int(
                max_chars
            ),
        )
    ]

    augmented = (
        original
        + "\n\n"
        + "SOPHYANE_CURRENT_GROUNDED_DOCUMENT\n"
        + "PATH="
        + document.path
        + "\n"
        + "KIND="
        + document.kind
        + "\n"
        + "SOURCE="
        + document.source
        + "\n"
        + "CONTENT_BEGIN\n"
        + bounded
        + "\n"
        + "CONTENT_END"
    )

    return (
        augmented,
        document,
    )


__all__ = [
    "SessionDocumentReference",
    "augment_request_with_current_document",
    "clear_current_document",
    "current_document",
    "has_current_document",
    "remember_grounded_document",
    "remember_grounded_documents",
    "request_refers_to_current_document",
]
