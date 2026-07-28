"""Canonical graph-backed orchestration boundary for Sophyane 21."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import time
import uuid

from sophyane.graph_runtime import DurableStore, GraphResult, StateGraph

Progress = Callable[[str], None]
StructuredRunner = Callable[..., str]


@dataclass(slots=True)
class ExecutionRequest:
    """Normalized request accepted by :class:`ExecutionKernel`."""

    initial_text: str
    original_request: str
    ask: Callable[[str], Any]
    workspace: Path
    max_steps: int = 12
    progress: Progress = field(default=lambda _message: None, repr=False)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass(slots=True)
class ExecutionResult:
    """Observable outcome of one graph-backed kernel run."""

    task_id: str
    text: str
    workspace: Path
    elapsed_seconds: float
    graph_trace: tuple[str, ...] = ()
    checkpoint_id: str | None = None


class ExecutionKernel:
    """Stable orchestration entry point backed by the Sophyane state graph.

    The existing adaptive runner remains the concrete coding engine. Sophyane 21
    wraps it in explicit prepare, execute and finalize nodes, checkpoints every
    transition, and exposes graph telemetry without changing the TUI contract.
    """

    def __init__(self, runner: StructuredRunner, store: DurableStore | None = None) -> None:
        self._runner = runner
        self._store = store
        self.last_result: ExecutionResult | None = None
        self.last_graph_result: GraphResult | None = None

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        workspace = request.workspace.expanduser().resolve()
        started = time.monotonic()
        checkpoint_id = f"kernel-{request.task_id}"
        store = self._store or DurableStore(workspace / ".sophyane" / "graph_state.db")

        def prepare(state: dict[str, Any]) -> dict[str, Any]:
            workspace.mkdir(parents=True, exist_ok=True)
            request.progress(f"Kernel task {request.task_id}: workspace {workspace}")
            return {"workspace": str(workspace), "phase": "prepared"}

        def execute(state: dict[str, Any]) -> dict[str, Any]:
            text = self._runner(
                initial_text=request.initial_text,
                original_request=request.original_request,
                ask=request.ask,
                workspace=workspace,
                max_steps=request.max_steps,
                progress=request.progress,
            )
            return {"text": str(text), "phase": "executed"}

        def finalize(state: dict[str, Any]) -> dict[str, Any]:
            return {"phase": "completed", "completed": True}

        graph = StateGraph(store)
        graph.add_node("prepare", prepare)
        graph.add_node("execute", execute)
        graph.add_node("finalize", finalize)
        graph.add_edge(StateGraph.START, "prepare")
        graph.add_edge("prepare", "execute")
        graph.add_edge("execute", "finalize")
        graph.add_edge("finalize", StateGraph.END)

        graph_result = graph.invoke(
            {"task_id": request.task_id},
            checkpoint_id=checkpoint_id,
            recursion_limit=max(8, request.max_steps + 4),
            progress=request.progress,
            return_result=True,
        )
        assert isinstance(graph_result, GraphResult)
        self.last_graph_result = graph_result

        result = ExecutionResult(
            task_id=request.task_id,
            text=str(graph_result.state.get("text", "")),
            workspace=workspace,
            elapsed_seconds=time.monotonic() - started,
            graph_trace=tuple(graph_result.trace),
            checkpoint_id=checkpoint_id,
        )
        self.last_result = result
        request.progress(
            f"Kernel task {request.task_id}: finished in {result.elapsed_seconds:.2f}s "
            f"via {' -> '.join(result.graph_trace)}"
        )
        return result

    def run_structured_loop(
        self,
        *,
        initial_text: str,
        original_request: str,
        ask: Callable[[str], Any],
        workspace: Path | None = None,
        max_steps: int = 12,
        progress: Progress | None = None,
    ) -> str:
        """Drop-in replacement for the legacy ``run_structured_loop`` callable."""

        request = ExecutionRequest(
            initial_text=initial_text,
            original_request=original_request,
            ask=ask,
            workspace=(workspace or Path.cwd()),
            max_steps=max_steps,
            progress=progress or (lambda _message: None),
        )
        return self.run(request).text
