"""Export StateGraph to Mermaid for visual debugging."""
from __future__ import annotations
from typing import Any

def to_mermaid(graph: Any) -> str:
    lines = ["flowchart TD", "  START([START])", "  END([END])"]
    nodes = getattr(graph, "nodes", {})
    edges = getattr(graph, "edges", {})
    conditions = getattr(graph, "conditions", {})
    for name in nodes:
        lines.append(f"  {name}[{name}]")
    for src, dst in edges.items():
        a = "START" if src == getattr(graph, "START", "START") else src
        b = "END" if dst == getattr(graph, "END", "END") else dst
        lines.append(f"  {a} --> {b}")
    for src, (_sel, routes) in conditions.items():
        if routes:
            for label, dst in routes.items():
                b = "END" if dst == getattr(graph, "END", "END") else dst
                lines.append(f"  {src} -->|{label}| {b}")
        else:
            lines.append(f"  {src} --> COND_{src}{{condition}}")
    return "\n".join(lines)
