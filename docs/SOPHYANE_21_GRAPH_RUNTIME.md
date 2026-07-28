# Sophyane 21 Graph Runtime

Sophyane 21 makes the execution kernel graph-native while preserving the existing adaptive coding runner and TUI contract.

## Runtime primitives

- Explicit `START` and `END` boundaries
- Named state-transforming nodes
- Static and conditional edges
- Cyclic execution with recursion limits
- Dynamic `Command(update=..., goto=...)` routing
- Per-node retry and exponential backoff
- SQLite/WAL durable checkpoints
- Interrupt-before boundaries for human approval
- Resume from the exact pending node
- Structured node telemetry and streaming
- Deterministic bounded parallel fan-out

## Kernel lifecycle

Every coding request now follows this durable lifecycle:

```text
START -> prepare -> execute -> finalize -> END
```

The `execute` node invokes the existing adaptive runtime. This keeps proven provider interaction, tool execution, validation and repair behavior intact while making orchestration observable and checkpointed.

Each kernel task stores its checkpoint under `kernel-<task-id>` in:

```text
<workspace>/.sophyane/graph_state.db
```

## Example

```python
from sophyane.graph_runtime import DurableStore, StateGraph

store = DurableStore(path)
graph = StateGraph(store)
graph.add_node("increment", lambda state: {"count": state["count"] + 1})
graph.add_edge(StateGraph.START, "increment")
graph.add_conditional_edges(
    "increment",
    lambda state: "again" if state["count"] < 3 else "done",
    {"again": "increment", "done": StateGraph.END},
)
result = graph.invoke({"count": 0}, checkpoint_id="example")
assert result["count"] == 3
```

## Human-in-the-loop resume

```python
graph.set_interrupt_before("deploy")

try:
    graph.invoke(initial_state, checkpoint_id="release-42")
except GraphInterrupt:
    # Obtain approval, then continue from deploy.
    result = graph.resume("release-42")
```

## Compatibility

The existing `StateGraph.invoke()` state-dictionary return contract remains the default. Set `return_result=True` to obtain `GraphResult` with trace, events, completion status and checkpoint identity.
