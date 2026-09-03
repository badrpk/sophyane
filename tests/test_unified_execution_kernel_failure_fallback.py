from __future__ import annotations

from pathlib import Path

import sophyane.unified_execution_kernel as kernel


def _result(
    *,
    handled: bool,
    ok: bool,
    capability: str,
    output: str,
) -> kernel.ExecutionResult:
    return kernel.ExecutionResult(
        handled=handled,
        ok=ok,
        capability=capability,
        output=output,
        evidence={},
        started_at=1.0,
        finished_at=2.0,
    )


def test_failed_coding_result_falls_through_to_later_success():
    registry = kernel.CapabilityRegistry()

    calls: list[str] = []

    def coding(_request):
        calls.append("coding")

        return _result(
            handled=True,
            ok=False,
            capability="development.python_existing_pytest_repair",
            output="RED repair failed",
        )

    def later(_request):
        calls.append("later")

        return _result(
            handled=True,
            ok=True,
            capability="test.successful_fallback",
            output="GREEN",
        )

    registry.register(
        "development.local_coding",
        coding,
        priority=10,
    )

    registry.register(
        "test.successful_fallback",
        later,
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="repair target.py",
            workspace=str(Path.cwd()),
        )
    )

    assert result is not None
    assert result.ok is True
    assert result.output == "GREEN"
    assert calls == [
        "coding",
        "later",
    ]


def test_failed_compiler_result_falls_through_to_later_success():
    registry = kernel.CapabilityRegistry()

    def compiler(_request):
        return _result(
            handled=True,
            ok=False,
            capability="reasoning.task_compiler",
            output="# Sophyane compiled work packet\nStatus: unresolved",
        )

    def later(_request):
        return _result(
            handled=True,
            ok=True,
            capability="test.executor",
            output="executed",
        )

    registry.register(
        "reasoning.task_compiler",
        compiler,
        priority=10,
    )

    registry.register(
        "test.executor",
        later,
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="repair target.py",
            workspace=str(Path.cwd()),
        )
    )

    assert result is not None
    assert result.ok is True
    assert result.output == "executed"


def test_first_failed_execution_result_is_preserved_if_nothing_succeeds():
    registry = kernel.CapabilityRegistry()

    first = _result(
        handled=True,
        ok=False,
        capability="development.python_existing_pytest_repair",
        output="original coding failure",
    )

    second = _result(
        handled=True,
        ok=False,
        capability="reasoning.task_compiler",
        output="unresolved compiler packet",
    )

    registry.register(
        "development.local_coding",
        lambda _request: first,
        priority=10,
    )

    registry.register(
        "reasoning.task_compiler",
        lambda _request: second,
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="repair target.py",
            workspace=str(Path.cwd()),
        )
    )

    assert result is first


def test_failed_coding_result_is_not_rendered_as_terminal_text(monkeypatch):
    failure = _result(
        handled=True,
        ok=False,
        capability="development.python_existing_pytest_repair",
        output='{"handled": true, "ok": false}',
    )

    monkeypatch.setattr(
        kernel,
        "execute_request",
        lambda *args, **kwargs: failure,
    )

    assert kernel.execute_text(
        "repair target.py"
    ) is None


def test_failed_task_compiler_result_is_not_terminal_text(monkeypatch):
    failure = _result(
        handled=True,
        ok=False,
        capability="reasoning.task_compiler",
        output="# Sophyane compiled work packet\nStatus: unresolved",
    )

    monkeypatch.setattr(
        kernel,
        "execute_request",
        lambda *args, **kwargs: failure,
    )

    assert kernel.execute_text(
        "repair target.py"
    ) is None


def test_successful_kernel_result_remains_terminal_text(monkeypatch):
    success = _result(
        handled=True,
        ok=True,
        capability="development.python",
        output="verified success",
    )

    monkeypatch.setattr(
        kernel,
        "execute_request",
        lambda *args, **kwargs: success,
    )

    assert kernel.execute_text(
        "create target.py"
    ) == "verified success"


def test_non_coding_failed_capability_remains_fail_closed():
    registry = kernel.CapabilityRegistry()

    calls: list[str] = []

    denial = _result(
        handled=True,
        ok=False,
        capability="security.denied",
        output="denied",
    )

    registry.register(
        "security.denied",
        lambda _request: (
            calls.append("denied")
            or denial
        ),
        priority=10,
    )

    registry.register(
        "test.must_not_run",
        lambda _request: (
            calls.append("later")
            or _result(
                handled=True,
                ok=True,
                capability="test.must_not_run",
                output="unsafe fallback",
            )
        ),
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="denied operation",
            workspace=str(Path.cwd()),
        )
    )

    assert result is denial
    assert calls == ["denied"]


def test_unrelated_development_failure_remains_terminal():
    registry = kernel.CapabilityRegistry()

    calls: list[str] = []

    failure = _result(
        handled=True,
        ok=False,
        capability="development.cpp_explanation_guard",
        output="not an execution request",
    )

    registry.register(
        "development.guard",
        lambda _request: (
            calls.append("development")
            or failure
        ),
        priority=10,
    )

    registry.register(
        "reasoning.later",
        lambda _request: (
            calls.append("reasoning")
            or _result(
                handled=True,
                ok=True,
                capability="reasoning.later",
                output="must not run",
            )
        ),
        priority=20,
    )

    result = registry.execute(
        kernel.ExecutionRequest(
            text="what is hello.cpp",
            workspace=str(Path.cwd()),
        )
    )

    assert result is failure
    assert calls == ["development"]


def test_unrelated_failed_development_result_remains_terminal_text(
    monkeypatch,
):
    failure = _result(
        handled=True,
        ok=False,
        capability="development.cpp_explanation_guard",
        output="not an execution request",
    )

    monkeypatch.setattr(
        kernel,
        "execute_request",
        lambda *args, **kwargs: failure,
    )

    assert (
        kernel.execute_text(
            "what is hello.cpp"
        )
        == "not an execution request"
    )
