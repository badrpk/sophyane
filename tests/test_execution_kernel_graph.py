from __future__ import annotations

from pathlib import Path

from sophyane.execution_kernel import ExecutionKernel, ExecutionRequest
from sophyane.graph_runtime import DurableStore


def test_execution_kernel_runs_through_durable_graph(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    progress: list[str] = []

    def runner(**kwargs):
        calls.append(kwargs)
        return "verified result"

    kernel = ExecutionKernel(runner, DurableStore(tmp_path / "kernel.db"))
    request = ExecutionRequest(
        initial_text="approved",
        original_request="build project",
        ask=lambda prompt: prompt,
        workspace=tmp_path / "workspace",
        max_steps=9,
        progress=progress.append,
        task_id="task-21",
    )

    result = kernel.run(request)

    assert result.text == "verified result"
    assert result.workspace == (tmp_path / "workspace").resolve()
    assert result.graph_trace == ("prepare", "execute", "finalize")
    assert result.checkpoint_id == "kernel-task-21"
    assert kernel.last_graph_result is not None
    assert kernel.last_graph_result.completed is True
    assert calls[0]["workspace"] == result.workspace
    assert any("Graph node execute" in message for message in progress)


def test_structured_loop_contract_is_preserved(tmp_path: Path) -> None:
    kernel = ExecutionKernel(lambda **kwargs: kwargs["original_request"])
    text = kernel.run_structured_loop(
        initial_text="initial",
        original_request="original",
        ask=lambda prompt: prompt,
        workspace=tmp_path,
    )
    assert text == "original"
