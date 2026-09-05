"""Grounded conversational process-graph adapter.

This module does not replace Sophyane's graph engine.

It owns only:

    prior grounded process description
        ->
    bounded process-step extraction
        ->
    existing StateGraph
        ->
    existing Mermaid exporter

It must never invent process steps when none are grounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Iterable

from sophyane.graph_runtime import StateGraph
from sophyane.lc_compat.graph_viz import to_mermaid


# SOPHYANE_CONVERSATIONAL_GRAPH_CONTEXT_V4


@dataclass(frozen=True)
class ProcessStep:
    label: str
    node_id: str


_GRAPH_FOLLOWUP_PATTERNS = (
    r"\bshow\s+(?:me\s+)?(?:the\s+)?graph\b",
    r"\bshow\s+(?:me\s+)?(?:the\s+)?flow\b",
    r"\bshow\s+(?:me\s+)?(?:the\s+)?process\b",
    r"\bshow\s+(?:me\s+)?(?:the\s+)?architecture\b",
    r"\bvisuali[sz]e\s+(?:this|it|the\s+flow|the\s+process|the\s+architecture)\b",
    r"\bmake\s+(?:a\s+)?(?:process|architecture|flow)\s+graph\b",
    r"\bshow\s+how\s+(?:this|it)\s+works\s+visually\b",
    r"\bshow\s+(?:this|it)\s+visually\b",
    r"\bdraw\s+(?:the\s+)?flow\b",
)


_PROCESS_SEPARATORS = re.compile(
    r"""
    \s*
    (?:
        ->|
        →|
        =>|
        ➜|
        \n+
    )
    \s*
    """,
    flags=re.VERBOSE,
)


def is_conversational_graph_followup(
    request: str,
) -> bool:
    text = " ".join(
        str(
            request
            or ""
        ).strip().lower().split()
    )

    if not text:
        return False

    return any(
        re.search(
            pattern,
            text,
        )
        for pattern in _GRAPH_FOLLOWUP_PATTERNS
    )


def _clean_step(
    value: str,
) -> str:
    text = " ".join(
        str(
            value
            or ""
        ).strip().split()
    )

    text = text.strip(
        " \t\r\n,.;:-"
    )

    return text


def _node_id(
    label: str,
    index: int,
) -> str:
    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        label.lower(),
    ).strip(
        "_"
    )

    if not value:
        value = (
            "step_"
            + str(
                index
            )
        )

    return (
        value[:60]
        or (
            "step_"
            + str(
                index
            )
        )
    )


def extract_grounded_process_steps(
    description: str,
) -> list[ProcessStep]:
    """Extract only explicitly grounded sequential process steps."""

    raw = str(
        description
        or ""
    ).strip()

    if not raw:
        return []

    parts = [
        _clean_step(
            item
        )
        for item in _PROCESS_SEPARATORS.split(
            raw
        )
    ]

    parts = [
        item
        for item in parts
        if item
    ]

    #
    # Arrow/newline structure is authoritative.
    #
    if len(
        parts
    ) < 2:
        return []

    unique_ids: set[str] = set()
    steps: list[ProcessStep] = []

    for index, label in enumerate(
        parts,
        start=1,
    ):
        node = _node_id(
            label,
            index,
        )

        base = node
        suffix = 2

        while node in unique_ids:
            node = (
                base
                + "_"
                + str(
                    suffix
                )
            )
            suffix += 1

        unique_ids.add(
            node
        )

        steps.append(
            ProcessStep(
                label=label,
                node_id=node,
            )
        )

    return steps


def build_process_graph(
    steps: Iterable[ProcessStep],
) -> StateGraph | None:
    items = list(
        steps
    )

    if len(
        items
    ) < 2:
        return None

    graph = StateGraph()

    for item in items:
        graph.add_node(
            item.node_id,
            lambda state: state,
        )

    graph.add_edge(
        StateGraph.START,
        items[
            0
        ].node_id,
    )

    for left, right in zip(
        items,
        items[
            1:
        ],
    ):
        graph.add_edge(
            left.node_id,
            right.node_id,
        )

    graph.add_edge(
        items[
            -1
        ].node_id,
        StateGraph.END,
    )

    graph.compile()

    return graph


def render_process_mermaid(
    description: str,
) -> dict[str, object]:
    steps = extract_grounded_process_steps(
        description
    )

    graph = build_process_graph(
        steps
    )

    if graph is None:
        return {
            "handled": False,
            "reason": (
                "no grounded sequential process "
                "was available"
            ),
        }

    mermaid = to_mermaid(
        graph
    )

    #
    # Replace internal IDs with human-readable labels while retaining
    # valid Mermaid topology.
    #
    for step in steps:
        mermaid = mermaid.replace(
            f"{step.node_id}[{step.node_id}]",
            (
                step.node_id
                + "["
                + step.label.replace(
                    "]",
                    ""
                )
                + "]"
            ),
        )

    return {
        "handled": True,
        "mermaid": mermaid,
        "steps": [
            {
                "label": step.label,
                "node_id": step.node_id,
            }
            for step in steps
        ],
    }


def save_process_graph_artifacts(
    *,
    description: str,
    workspace: Path,
) -> dict[str, object]:
    result = render_process_mermaid(
        description
    )

    if not result.get(
        "handled"
    ):
        return result

    artifact_dir = (
        Path(
            workspace
        )
        / "artifacts"
    )

    artifact_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    mermaid_path = (
        artifact_dir
        / "sophyane-process-graph.mmd"
    )

    json_path = (
        artifact_dir
        / "sophyane-process-graph.json"
    )

    mermaid_path.write_text(
        str(
            result[
                "mermaid"
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    json_path.write_text(
        json.dumps(
            {
                "source": (
                    "conversation-grounded"
                ),
                "description": (
                    description
                ),
                "steps": result[
                    "steps"
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        **result,
        "mermaid_path": str(
            mermaid_path
        ),
        "json_path": str(
            json_path
        ),
    }


def graph_response_text(
    result: dict[str, object],
) -> str:
    if not result.get(
        "handled"
    ):
        return ""

    return "\n".join(
        (
            "◆ Sophyane process graph",
            "",
            str(
                result[
                    "mermaid"
                ]
            ),
            "",
            (
                "Graph: "
                + str(
                    result.get(
                        "mermaid_path",
                        "",
                    )
                )
            ),
            (
                "Data: "
                + str(
                    result.get(
                        "json_path",
                        "",
                    )
                )
            ),
        )
    )


__all__ = [
    "ProcessStep",
    "build_process_graph",
    "extract_grounded_process_steps",
    "graph_response_text",
    "is_conversational_graph_followup",
    "render_process_mermaid",
    "save_process_graph_artifacts",
]
