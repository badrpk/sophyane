"""Streaming event types (values / updates / debug)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

EventMode = Literal["values", "updates", "debug"]

@dataclass
class StreamEvent:
    mode: EventMode
    data: dict[str, Any]
    node: str | None = None
    ts: float = 0.0

def wrap_graph_stream(graph: Any, initial: dict[str, Any], modes: list[EventMode] | None = None) -> Iterator[StreamEvent]:
    import time
    modes = modes or ["updates"]
    if hasattr(graph, "stream"):
        for item in graph.stream(initial):
            node = item.get("node") if isinstance(item, dict) else None
            state = item.get("state", item) if isinstance(item, dict) else item
            if "updates" in modes:
                yield StreamEvent("updates", {"state": state}, node=node, ts=time.time())
            if "values" in modes:
                yield StreamEvent("values", dict(state) if isinstance(state, dict) else {"value": state}, node=node, ts=time.time())
            if "debug" in modes:
                yield StreamEvent("debug", dict(item) if isinstance(item, dict) else {"item": item}, node=node, ts=time.time())
    else:
        final = graph.invoke(initial)
        yield StreamEvent("values", dict(final), ts=time.time())
