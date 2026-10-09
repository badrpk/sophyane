from __future__ import annotations

import sophyane.unified_execution_kernel as kernel


def _result(
    *,
    capability: str,
    ok: bool,
    marker: str,
) -> kernel.ExecutionResult:
    return kernel.ExecutionResult(
        handled=True,
        ok=ok,
        capability=capability,
        output=marker,
        evidence={"original_evidence": marker},
        started_at=1.0,
        finished_at=2.0,
    )


def test_phase1_spine_is_observable_without_replacing_existing_evidence(
    monkeypatch,
    tmp_path,
):
    original = _result(
        capability="test.success",
        ok=True,
        marker="SUCCESS",
    )

    class Registry:
        def execute(self, request):
            assert request.text == "perform selected action"
            return original

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    result = kernel.execute_request(
        "perform selected action",
        workspace=tmp_path,
        request_id="req-1",
        metadata={
            "intelligence_authority": {
                "session_mode": "codex_cli",
                "session_provider": "codex_cli",
            },
        },
    )

    assert result is not None
    assert result.ok is True
    assert result.capability == "test.success"
    assert result.output == "SUCCESS"
    assert result.started_at == 1.0
    assert result.finished_at == 2.0
    assert result.evidence["original_evidence"] == "SUCCESS"

    spine = result.evidence["execution_spine"]

    assert spine["version"] == 1
    assert spine["trace"] == (
        "authority",
        "goal_plan",
        "capability_policy",
        "execution_kernel",
        "evidence",
        "validation",
        "result",
    )
    assert spine["authority"]["session_mode"] == "codex_cli"
    assert spine["authority"]["session_provider"] == "codex_cli"
    assert spine["goal"] == {
        "objective": "perform selected action",
        "request_id": "req-1",
    }
    assert spine["policy"] == {
        "status": "pending",
        "enforced": False,
    }
    # Phase 1 owns these baseline execution invariants. Later spine
    # phases may add execution evidence without invalidating this contract.
    assert spine["execution"]["status"] == "completed"
    assert spine["execution"]["capability"] == "test.success"
    assert spine["execution"]["registry_semantics_preserved"] is True
    # Phase 1 owns the baseline validation invariants. Later phases may
    # add validation evidence without invalidating this contract.
    assert spine["validation"]["status"] == "passed"
    assert spine["validation"]["structural_only"] is True


def test_phase1_spine_does_not_turn_failed_execution_into_success(
    monkeypatch,
    tmp_path,
):
    original = _result(
        capability="test.failure",
        ok=False,
        marker="FAILED",
    )

    class Registry:
        def execute(self, request):
            return original

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    result = kernel.execute_request(
        "perform failing action",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is False
    assert result.output == "FAILED"
    assert (
        result.evidence["execution_spine"]["validation"]["status"]
        == "failed"
    )


def test_registry_nonterminal_failure_fallthrough_is_unchanged(
    tmp_path,
):
    registry = kernel.CapabilityRegistry()
    calls = []

    def first(request):
        calls.append("first")
        return _result(
            capability="reasoning.task_compiler",
            ok=False,
            marker="FIRST_FAILURE",
        )

    def second(request):
        calls.append("second")
        return _result(
            capability="test.success",
            ok=True,
            marker="SECOND_SUCCESS",
        )

    registry.register(
        "first",
        first,
        priority=10,
    )
    registry.register(
        "second",
        second,
        priority=20,
    )

    request = kernel.ExecutionRequest(
        text="x",
        workspace=str(tmp_path),
    )

    result = registry.execute(request)

    assert result is not None
    assert result.ok is True
    assert result.output == "SECOND_SUCCESS"
    assert calls == ["first", "second"]


def test_registry_returns_first_nonterminal_failure_when_nothing_succeeds(
    tmp_path,
):
    registry = kernel.CapabilityRegistry()

    registry.register(
        "compiler",
        lambda request: _result(
            capability="reasoning.task_compiler",
            ok=False,
            marker="COMPILER_FAILURE",
        ),
        priority=10,
    )

    registry.register(
        "unhandled",
        lambda request: None,
        priority=20,
    )

    request = kernel.ExecutionRequest(
        text="x",
        workspace=str(tmp_path),
    )

    result = registry.execute(request)

    assert result is not None
    assert result.ok is False
    assert result.output == "COMPILER_FAILURE"
