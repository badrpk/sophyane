"""General deterministic document import dispatch.

Plain document import is a document-grounding capability, not a graph command.

Routes:
    import/read/load <file>
        -> ground the real document locally
        -> expose bounded grounded content to the session

Graph/chart requests remain owned by visual_dispatch.py, which consumes
the same document_grounding.py authority.

No provider, model or Sophyane mode is hard-coded here.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from sophyane.document_grounding import (
    GroundedDocument,
    ground_request_documents,
)


# SOPHYANE_GENERAL_DOCUMENT_IMPORT_V2


_IMPORT_PATTERNS = (
    r"\bimport\b",
    r"\bload\b",
    r"\bread\b",
    r"\bopen\b",
    r"\bingest\b",
    r"\buse\b.*\b(?:pdf|csv|json|document|file)\b",
)


_VISUAL_WORDS = (
    "graph",
    "chart",
    "plot",
    "visualize",
    "visualise",
    "pie chart",
    "bar chart",
    "line chart",
    "scatter",
)


def detect_document_import_intent(
    request: str,
) -> bool:
    text = str(
        request
        or ""
    ).strip()

    if not text:
        return False

    lowered = text.casefold()

    #
    # Visualization keeps its own authority and consumes the same grounding
    # layer. Plain import must never steal an explicit graph request.
    #
    if any(
        word in lowered
        for word in _VISUAL_WORDS
    ):
        return False

    return any(
        re.search(
            pattern,
            lowered,
        )
        for pattern in _IMPORT_PATTERNS
    )


def _document_response(
    documents: tuple[GroundedDocument, ...],
) -> str:
    lines = [
        "◆ Sophyane document import",
        f"  Documents: {len(documents)}",
        "  Grounded locally: yes",
        "  Provider required: no",
        "",
    ]

    for index, document in enumerate(
        documents,
        start=1,
    ):
        lines.extend(
            (
                (
                    f"  [{index}] "
                    f"{Path(document.path).name}"
                ),
                (
                    f"      Type: "
                    f"{document.kind}"
                ),
                (
                    f"      Source: "
                    f"{document.source}"
                ),
                (
                    f"      Text chars: "
                    f"{len(document.text)}"
                ),
            )
        )

    lines.extend(
        (
            "",
            (
                "  The grounded document is available for "
                "subsequent summarization, analysis or visualization."
            ),
        )
    )

    return "\n".join(
        lines
    )


def try_general_document_dispatch(
    request: str,
    *,
    workspace: Path,
) -> dict[str, Any] | None:
    if not detect_document_import_intent(
        request
    ):
        return None

    documents = ground_request_documents(
        request,
        workspace=workspace,
    )

    if not documents:
        return None

    # SOPHYANE_DOCUMENT_IMPORT_SESSION_CONTEXT_V1
    try:
        from sophyane.document_session_context import (
            remember_grounded_documents,
        )
    
        remember_grounded_documents(
            documents
        )
    
    except Exception:
        pass
    
    return {
        "handled": True,
        "route": "document_import",
        "documents": documents,
        "response": _document_response(
            documents
        ),
    }


__all__ = [
    "detect_document_import_intent",
    "try_general_document_dispatch",
]
