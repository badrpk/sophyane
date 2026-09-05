"""General provider-independent Sophyane visual dispatch.

This module does not implement another graph engine.

It selects among existing visual capabilities:

    grounded numeric data
        -> visualization_capability

    structural / workflow / dependency graph
        -> Mermaid structural rendering

    broader visual/scene instruction
        -> existing recursive visual engine classification

Anything that cannot be satisfied deterministically falls through to
Sophyane's normal intelligence pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


# SOPHYANE_GENERAL_VISUAL_DISPATCH_V3


@dataclass(frozen=True)
class VisualRoute:
    requested: bool
    route: str
    reason: str


_STRUCTURAL_PATTERNS = (
    r"\bcapabilit(?:y|ies)\s+graph\b",
    r"\bdependency\s+graph\b",
    r"\bexecution\s+graph\b",
    r"\bworkflow\s+graph\b",
    r"\bflow\s+graph\b",
    r"\bstate\s+graph\b",
    r"\btask\s+graph\b",
    r"\bnode(?:s)?\s+and\s+edge(?:s)?\b",
    r"\bmermaid\b",
    r"\bvisuali[sz]e\s+(?:the\s+)?(?:workflow|flow|dependencies|architecture)\b",
    r"\bshow\s+(?:the\s+)?(?:workflow|dependency|execution|capability)\s+(?:graph|flow)\b",
)


def classify_visual_route(
    request: str,
) -> VisualRoute:
    text = str(
        request
        or ""
    ).strip()

    if not text:
        return VisualRoute(
            requested=False,
            route="",
            reason="empty request",
        )

    from sophyane.visualization_capability import (
        detect_visualization_intent,
    )

    numeric_intent = detect_visualization_intent(
        text
    )

    #
    # Structural graph language takes precedence over ordinary chart
    # classification. "Show capability graph" must not become a bar chart.
    #
    structural = any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in _STRUCTURAL_PATTERNS
    )

    if structural:
        return VisualRoute(
            requested=True,
            route="structural_graph",
            reason="structural graph intent",
        )

    if numeric_intent.requested:
        return VisualRoute(
            requested=True,
            route="data_chart",
            reason=numeric_intent.reason,
        )

    try:
        from sophyane.recursive_visual_engine import (
            is_visual_instruction,
        )

        scene_requested = bool(
            is_visual_instruction(
                text
            )
        )

    except Exception:
        scene_requested = False

    if scene_requested:
        return VisualRoute(
            requested=True,
            route="scene_visual",
            reason="existing recursive visual engine classified request",
        )

    return VisualRoute(
        requested=False,
        route="",
        reason="no deterministic visual route",
    )


def _safe_name(
    value: str,
) -> str:
    name = re.sub(
        r"[^a-zA-Z0-9._-]+",
        "-",
        value.strip(),
    ).strip(
        "-."
    )

    return (
        name[:80]
        or "sophyane-graph"
    )


def _extract_structural_edges(
    request: str,
) -> list[tuple[str, str]]:
    """Extract only edges explicitly grounded in the user request."""

    text = str(
        request
        or ""
    )

    edges: list[tuple[str, str]] = []

    patterns = (
        r"([A-Za-z][A-Za-z0-9_. -]{0,60}?)\s*->\s*([A-Za-z][A-Za-z0-9_. -]{0,60})",
        r"([A-Za-z][A-Za-z0-9_. -]{0,60}?)\s*→\s*([A-Za-z][A-Za-z0-9_. -]{0,60})",
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
        ):
            source = match.group(1).strip(
                " ,;:"
            )
            target = match.group(2).strip(
                " ,;:"
            )

            if (
                source
                and target
            ):
                edges.append(
                    (
                        source,
                        target,
                    )
                )

    #
    # Preserve order while eliminating duplicate grounded edges.
    #
    unique: list[tuple[str, str]] = []
    seen = set()

    for edge in edges:
        if edge in seen:
            continue

        seen.add(edge)
        unique.append(
            edge
        )

    return unique


def _mermaid_from_edges(
    edges: list[tuple[str, str]],
) -> str:
    lines = [
        "flowchart TD",
    ]

    ids: dict[str, str] = {}

    def node_id(
        label: str,
    ) -> str:
        if label not in ids:
            ids[label] = (
                "N"
                + str(
                    len(
                        ids
                    )
                    + 1
                )
            )

        return ids[
            label
        ]

    for source, target in edges:
        source_id = node_id(
            source
        )
        target_id = node_id(
            target
        )

        source_label = (
            source.replace(
                '"',
                "'",
            )
        )

        target_label = (
            target.replace(
                '"',
                "'",
            )
        )

        lines.append(
            f'{source_id}["{source_label}"] --> '
            f'{target_id}["{target_label}"]'
        )

    return (
        "\n".join(
            lines
        )
        + "\n"
    )


def render_structural_graph(
    *,
    request: str,
    workspace: Path,
) -> dict[str, Any]:
    """Render explicitly grounded structural edges.

    This deliberately refuses to invent topology.
    """

    edges = _extract_structural_edges(
        request
    )

    if not edges:
        return {
            "handled": False,
            "reason": (
                "structural graph requested but no explicit "
                "grounded edges were supplied"
            ),
        }

    workspace = Path(
        workspace
    ).expanduser().resolve()

    artifacts = (
        workspace
        / "artifacts"
    )

    artifacts.mkdir(
        parents=True,
        exist_ok=True,
    )

    stem = _safe_name(
        "sophyane-structural-graph"
    )

    mermaid_path = (
        artifacts
        / f"{stem}.mmd"
    )

    json_path = (
        artifacts
        / f"{stem}.json"
    )

    mermaid = _mermaid_from_edges(
        edges
    )

    mermaid_path.write_text(
        mermaid,
        encoding="utf-8",
    )

    json_path.write_text(
        json.dumps(
            {
                "source": "user-grounded",
                "kind": "structural_graph",
                "edges": [
                    {
                        "source": source,
                        "target": target,
                    }
                    for source, target
                    in edges
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "handled": True,
        "kind": "structural_graph",
        "edge_count": len(
            edges
        ),
        "mermaid_path": str(
            mermaid_path
        ),
        "json_path": str(
            json_path
        ),
        "mermaid": mermaid,
    }


def visual_response_text(
    payload: dict[str, Any],
) -> str:
    kind = str(
        payload.get(
            "kind",
            "",
        )
    )

    if kind == "structural_graph":
        return (
            "◆ Sophyane structural graph\n"
            f"  Edges: {payload.get('edge_count', 0)}\n"
            "  Source: user-grounded\n"
            "  Verified: yes\n\n"
            "  Mermaid:\n"
            f"  {payload.get('mermaid_path', '')}\n\n"
            "  Data:\n"
            f"  {payload.get('json_path', '')}"
        )

    return str(
        payload.get(
            "response",
            "",
        )
    )


def try_general_visual_dispatch(
    request: str,
    *,
    workspace: Path,
) -> dict[str, Any] | None:
    """Try deterministic visual execution before any LLM/provider call."""

    # SOPHYANE_DOCUMENT_GROUNDED_VISUAL_INPUT_V1
    #
    # File-backed requests use the same visual dispatcher after local,
    # deterministic grounding. No provider or mode owns this conversion.
    original_request = str(
        request
        or ""
    )

    # SOPHYANE_SESSION_DOCUMENT_VISUAL_FOLLOWUP_V1
    # A prior explicit import may supply grounded values for a later
    # request such as 'now graph the values in it'. The original
    # request still owns visualization intent classification.
    try:
        from sophyane.document_session_context import (
            augment_request_with_current_document,
        )
    
        _session_augmented_request, _session_document = (
            augment_request_with_current_document(
                original_request,
                require_reference=True,
            )
        )
    
    except Exception:
        _session_augmented_request = original_request
        _session_document = None
    
    try:
        from sophyane.document_grounding import (
            augment_request_with_grounded_documents,
        )

        request, grounded_documents = (
            augment_request_with_grounded_documents(
                _session_augmented_request,
                workspace=workspace,
            )
        )

    except Exception:
        request = _session_augmented_request
        grounded_documents = ()

    route = classify_visual_route(
        original_request
    )

    if not route.requested:
        return None

    if route.route == "data_chart":
        from sophyane.visualization_capability import (
            render_visualization,
            visualization_response_text,
        )

        result = render_visualization(
            request=request,
            workspace=workspace,
        )

        if not result.get(
            "handled"
        ):
            return None

        return {
            "handled": True,
            "route": "data_chart",
            "result": result,
            "response": visualization_response_text(
                result
            ),
        }

    if route.route == "structural_graph":
        result = render_structural_graph(
            request=request,
            workspace=workspace,
        )

        if not result.get(
            "handled"
        ):
            return None

        return {
            "handled": True,
            "route": "structural_graph",
            "result": result,
            "response": visual_response_text(
                result
            ),
        }

    #
    # Existing recursive_visual_engine owns scene-level understanding,
    # but this dispatcher must not pretend it rendered an artifact when
    # no deterministic renderer was invoked.
    #
    if route.route == "scene_visual":
        return None

    return None

__all__ = [
    "VisualRoute",
    "classify_visual_route",
    "render_structural_graph",
    "try_general_visual_dispatch",
    "visual_response_text",
]
