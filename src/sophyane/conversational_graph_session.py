"""Session-local conversational process retention.

This is deliberately separate from graph rendering.

Responsibilities:

assistant response
    ->
grounded sequential process detection
    ->
retain exact grounded description on the active conversation owner

later user graph follow-up
    ->
reuse retained description
    ->
existing conversational_graph adapter
    ->
existing StateGraph + Mermaid renderer

No provider, mode, document type, domain, or named service is special-cased.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sophyane.conversational_graph import (
    extract_grounded_process_steps,
    graph_response_text,
    is_conversational_graph_followup,
    save_process_graph_artifacts,
)


# SOPHYANE_CONVERSATIONAL_GRAPH_SESSION_V5


_CONTEXT_ATTR = (
    "_sophyane_grounded_process_description"
)

_CONTEXT_STEPS_ATTR = (
    "_sophyane_grounded_process_step_count"
)


def _workspace_for_owner(
    owner: Any,
) -> Path:
    """Resolve a local workspace without introducing routing authority."""

    for name in (
        "workspace",
        "workspace_path",
        "workdir",
        "cwd",
        "root",
        "project_root",
    ):
        value = getattr(
            owner,
            name,
            None,
        )

        if value:
            try:
                return Path(
                    value
                ).expanduser().resolve()
            except Exception:
                pass

    return Path.cwd().resolve()


def remember_grounded_process_context(
    owner: Any,
    assistant_text: str,
) -> bool:
    """Retain only an explicitly grounded sequential process.

    Authority order:

    1. Explicit ``PROCESS_FLOW:`` machine-retainable line.
    2. Best explicit inline arrow chain present in the assistant response.
    3. A response that is itself essentially one arrow process.

    Ordinary multiline prose must never become graph topology merely because
    the generic extractor can split on newlines.
    """

    text = str(
        assistant_text
        or ""
    ).strip()

    if not text:
        return False

    # SOPHYANE_PROCESS_FLOW_RETENTION_AUTHORITY_V10
    #
    # First authority: explicit machine-retainable process flow.
    process_description = ""

    for raw_line in text.splitlines():
        line = str(
            raw_line
            or ""
        ).strip()

        if not line:
            continue

        prefix = "PROCESS_FLOW:"

        if line.upper().startswith(
            prefix
        ):
            candidate = line[
                len(
                    prefix
                ):
            ].strip()

            if candidate:
                process_description = candidate

            break

    def _retain(
        description: str,
    ) -> bool:
        steps = extract_grounded_process_steps(
            description
        )

        if len(
            steps
        ) < 2:
            return False

        setattr(
            owner,
            _CONTEXT_ATTR,
            description,
        )

        setattr(
            owner,
            _CONTEXT_STEPS_ATTR,
            len(
                steps
            ),
        )

        return True

    if (
        process_description
        and _retain(
            process_description
        )
    ):
        return True

    # SOPHYANE_EXPLICIT_ARROW_CHAIN_FALLBACK_V10
    #
    # Providers do not always obey the PROCESS_FLOW suffix contract,
    # especially when a long answer is truncated. In that case use only
    # explicit process topology actually authored in the response.
    #
    # Do NOT use the entire multiline response as fallback: doing so turns
    # headings, bullets and prose paragraphs into fabricated graph nodes.
    import re

    arrow = r"(?:->|→|=>|➜)"

    candidates: list[
        tuple[
            int,
            int,
            str,
        ]
    ] = []

    for index, raw_line in enumerate(
        text.splitlines()
    ):
        line = " ".join(
            str(
                raw_line
                or ""
            ).strip().split()
        )

        if not line:
            continue

        arrow_count = len(
            re.findall(
                arrow,
                line,
            )
        )

        if arrow_count < 1:
            continue

        steps = extract_grounded_process_steps(
            line
        )

        if len(
            steps
        ) < 2:
            continue

        # Prefer the richest explicit chain. Earlier occurrence breaks ties
        # because high-level architecture normally precedes examples/details.
        candidates.append(
            (
                len(
                    steps
                ),
                -index,
                line,
            )
        )

    if candidates:
        candidates.sort(
            reverse=True
        )

        best = candidates[
            0
        ][
            2
        ]

        if _retain(
            best
        ):
            return True

    # Final bounded fallback:
    #
    # Preserve legacy behavior only when the whole assistant response is
    # essentially a compact arrow process rather than ordinary prose.
    compact = " ".join(
        text.split()
    )

    if (
        len(
            text.splitlines()
        )
        <= 3
        and len(
            re.findall(
                arrow,
                compact,
            )
        )
        >= 1
    ):
        if _retain(
            compact
        ):
            return True

    return False


def retained_grounded_process_context(
    owner: Any,
) -> str:
    return str(
        getattr(
            owner,
            _CONTEXT_ATTR,
            "",
        )
        or ""
    ).strip()


def retained_grounded_process_step_count(
    owner: Any,
) -> int:
    try:
        return int(
            getattr(
                owner,
                _CONTEXT_STEPS_ATTR,
                0,
            )
            or 0
        )
    except Exception:
        return 0


def try_conversational_graph_followup(
    owner: Any,
    request: str,
) -> str | None:
    """Render retained process context before any LLM/provider routing."""

    if not is_conversational_graph_followup(
        request
    ):
        return None

    description = (
        retained_grounded_process_context(
            owner
        )
    )

    if not description:
        #
        # A graph request without grounded conversation state must
        # continue through normal Sophyane routing.
        #
        return None

    result = save_process_graph_artifacts(
        description=description,
        workspace=_workspace_for_owner(
            owner
        ),
    )

    if not result.get(
        "handled"
    ):
        return None

    response = graph_response_text(
        result
    ).strip()

    if not response:
        return None

    return response


__all__ = [
    "remember_grounded_process_context",
    "retained_grounded_process_context",
    "retained_grounded_process_step_count",
    "try_conversational_graph_followup",
]
