from __future__ import annotations

import sophyane.unified_execution_kernel as kernel


def _result(
    *,
    capability: str,
    ok: bool,
    output: str,
) -> kernel.ExecutionResult:
    return kernel.ExecutionResult(
        handled=True,
        ok=ok,
        capability=capability,
        output=output,
        evidence={"original": output},
        started_at=1.0,
        finished_at=2.0,
    )


def test_phase2_registry_execution_runs_inside_canonical_stategraph(
    monkeypatch,
    tmp_path,
):
    calls = []

    class Registry:
        def execute(self, request):
            calls.append(request.text)
            return _result(
                capability="test.graph",
                ok=True,
                output="GRAPH_OK",
            )

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    result = kernel.execute_request(
        "execute selected action",
        workspace=tmp_path,
        request_id="phase2-1",
        metadata={
            "intelligence_authority": {
                "session_mode": "codex_cli",
                "session_provider": "codex_cli",
            },
        },
    )

    assert result is not None
    assert result.ok is True
    assert result.output == "GRAPH_OK"
    assert calls == ["execute selected action"]

    execution = result.evidence[
        "execution_spine"
    ]["execution"]

    assert execution["engine"] == "graph_runtime.StateGraph"
    assert execution["graph_trace"] == (
        "registry_execute",
    )
    assert execution["graph_completed"] is True
    assert execution["graph_next_node"] == "END"
    assert execution["registry_semantics_preserved"] is True

    assert len(
        execution["graph_events"]
    ) == 1

    event = execution["graph_events"][0]

    assert event["sequence"] == 1
    assert event["node"] == "registry_execute"
    assert event["status"] == "completed"
    assert event["attempt"] == 1


def test_phase2_graph_preserves_none_fallthrough(
    monkeypatch,
    tmp_path,
):
    calls = []

    class Registry:
        def execute(self, request):
            calls.append(request.text)
            return None

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    result = kernel.execute_request(
        "ordinary unowned request",
        workspace=tmp_path,
    )

    assert result is None
    assert calls == ["ordinary unowned request"]


def test_phase2_graph_preserves_failed_execution(
    monkeypatch,
    tmp_path,
):
    class Registry:
        def execute(self, request):
            return _result(
                capability="reasoning.task_compiler",
                ok=False,
                output="FAILED",
            )

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    result = kernel.execute_request(
        "failing selected action",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is False
    assert result.output == "FAILED"

    execution = result.evidence[
        "execution_spine"
    ]["execution"]

    assert execution["graph_trace"] == (
        "registry_execute",
    )


def test_phase2_does_not_change_registry_fallthrough_semantics(
    tmp_path,
):
    registry = kernel.CapabilityRegistry()
    calls = []

    registry.register(
        "compiler",
        lambda request: (
            calls.append("compiler")
            or _result(
                capability="reasoning.task_compiler",
                ok=False,
                output="FIRST_FAILURE",
            )
        ),
        priority=10,
    )

    registry.register(
        "executor",
        lambda request: (
            calls.append("executor")
            or _result(
                capability="test.success",
                ok=True,
                output="SUCCESS",
            )
        ),
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="x",
            workspace=str(tmp_path),
        )
    )

    assert result is not None
    assert result.ok is True
    assert result.output == "SUCCESS"
    assert calls == [
        "compiler",
        "executor",
    ]
