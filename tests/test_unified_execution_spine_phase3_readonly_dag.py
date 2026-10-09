from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.readonly_task_graph import ReadonlyGraphNode
from sophyane.unified_execution_kernel import execute_request


def test_explicit_validated_readonly_graph_uses_parallel_dag(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def first():
        calls.append("a")
        return {"ok": True, "value": 1}

    def second():
        calls.append("b")
        return {"ok": True, "value": 2}

    result = execute_request(
        "execute validated read-only plan",
        workspace=tmp_path,
        metadata={
            "validated_readonly_graph_nodes": [
                ReadonlyGraphNode("a", first),
                ReadonlyGraphNode("b", second),
            ],
            "validated_readonly_graph_max_workers": 2,
        },
    )

    assert result is not None
    assert result.handled is True
    assert result.ok is True
    assert result.capability == "execution.readonly_task_graph"
    assert set(calls) == {"a", "b"}

    dag = result.evidence["readonly_task_graph"]
    assert dag["ok"] is True
    assert dag["completed"] == 2
    assert dag["total"] == 2

    execution = result.evidence["execution_spine"]["execution"]
    assert execution["engine"] == "graph_runtime.StateGraph"
    assert execution["readonly_parallel_graph"] == {
        "selected": True,
        "engine": "readonly_task_graph",
        "ok": True,
        "completed": 2,
        "total": 2,
    }
    assert execution["graph_trace"] == ("registry_execute",)


def test_ordinary_request_does_not_select_readonly_dag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sophyane.unified_execution_kernel as kernel

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: _RegistryStub(),
    )

    result = execute_request(
        "ordinary sequential request",
        workspace=tmp_path,
    )

    assert result is not None
    execution = result.evidence["execution_spine"]["execution"]
    assert execution["readonly_parallel_graph"] == {
        "selected": False,
    }
    assert execution["engine"] == "graph_runtime.StateGraph"


def test_mutating_node_is_rejected_before_worker_execution(
    tmp_path: Path,
) -> None:
    called = False

    def mutation():
        nonlocal called
        called = True
        return {"ok": True}

    with pytest.raises(ValueError):
        execute_request(
            "invalid parallel mutation",
            workspace=tmp_path,
            metadata={
                "validated_readonly_graph_nodes": [
                    ReadonlyGraphNode(
                        "write",
                        mutation,
                        read_only=False,
                    ),
                ],
            },
        )

    assert called is False


def test_unstructured_metadata_cannot_enter_parallel_dag(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        execute_request(
            "invalid graph metadata",
            workspace=tmp_path,
            metadata={
                "validated_readonly_graph_nodes": [
                    {
                        "node_id": "fake",
                        "read_only": True,
                    }
                ],
            },
        )


def test_failed_readonly_graph_is_structured_failure(
    tmp_path: Path,
) -> None:
    def failed():
        return {"ok": False, "error": "inspection failed"}

    result = execute_request(
        "execute failing validated read-only plan",
        workspace=tmp_path,
        metadata={
            "validated_readonly_graph_nodes": [
                ReadonlyGraphNode("inspect", failed),
            ],
        },
    )

    assert result is not None
    assert result.handled is True
    assert result.ok is False
    assert result.capability == "execution.readonly_task_graph"

    dag = result.evidence["readonly_task_graph"]
    assert dag["ok"] is False
    assert dag["total"] == 1

    execution = result.evidence["execution_spine"]["execution"]
    assert execution["readonly_parallel_graph"]["selected"] is True
    assert execution["readonly_parallel_graph"]["ok"] is False


class _RegistryStub:
    def execute(self, request):
        from sophyane.unified_execution_kernel import ExecutionResult
        import time

        now = time.time()
        return ExecutionResult(
            handled=True,
            ok=True,
            capability="test.sequential",
            output="ok",
            evidence={},
            started_at=now,
            finished_at=now,
        )
