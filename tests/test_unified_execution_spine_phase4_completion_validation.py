from pathlib import Path

import sophyane.unified_execution_kernel as kernel


def _success_result() -> kernel.ExecutionResult:
    return kernel.ExecutionResult(
        handled=True,
        ok=True,
        capability="test.project",
        output="executed",
        evidence={},
        started_at=1.0,
        finished_at=2.0,
    )


def _install_single_success_registry(monkeypatch) -> None:
    class Registry:
        def execute(self, request):
            del request
            return _success_result()

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )


def test_completion_validation_is_opt_in(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_single_success_registry(monkeypatch)

    result = kernel.execute_request(
        "ordinary successful operation",
        workspace=tmp_path,
    )

    assert result is not None
    assert result.ok is True

    validation = result.evidence[
        "execution_spine"
    ]["validation"]

    assert validation["status"] == "passed"
    assert validation["structural_only"] is True
    assert validation["completion"] == {
        "required": False,
    }


def test_required_completion_fails_without_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_single_success_registry(monkeypatch)

    result = kernel.execute_request(
        "build project",
        workspace=tmp_path,
        metadata={
            "require_project_completion": True,
        },
    )

    assert result is not None
    assert result.ok is False

    validation = result.evidence[
        "execution_spine"
    ]["validation"]

    assert validation["status"] == "failed"
    assert validation["structural_only"] is False

    completion = validation["completion"]

    assert completion["required"] is True
    assert completion["complete"] is False
    assert completion["entry"] is None
    assert completion["project_type"] == "unknown"
    assert completion["errors"]


def test_required_completion_passes_with_verified_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_single_success_registry(monkeypatch)

    (tmp_path / "index.html").write_text(
        (
            "<!doctype html>"
            "<html><body>Ready</body></html>"
        ),
        encoding="utf-8",
    )

    result = kernel.execute_request(
        "build project",
        workspace=tmp_path,
        metadata={
            "require_project_completion": True,
        },
    )

    assert result is not None
    assert result.ok is True

    validation = result.evidence[
        "execution_spine"
    ]["validation"]

    assert validation["status"] == "passed"
    assert validation["structural_only"] is False

    completion = validation["completion"]

    assert completion["required"] is True
    assert completion["complete"] is True
    assert completion["project_type"] == "browser"
    assert completion["errors"] == ()
    assert Path(completion["entry"]).name == "index.html"


def test_completion_verifier_does_not_replace_execution_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Registry:
        def execute(self, request):
            del request
            return kernel.ExecutionResult(
                handled=True,
                ok=False,
                capability="test.project",
                output="execution failed",
                evidence={},
                started_at=1.0,
                finished_at=2.0,
            )

    monkeypatch.setattr(
        kernel,
        "initialize_registry",
        lambda: Registry(),
    )

    (tmp_path / "index.html").write_text(
        "<html><body>Ready</body></html>",
        encoding="utf-8",
    )

    result = kernel.execute_request(
        "build project",
        workspace=tmp_path,
        metadata={
            "require_project_completion": True,
        },
    )

    assert result is not None
    assert result.ok is False

    validation = result.evidence[
        "execution_spine"
    ]["validation"]

    assert validation["status"] == "failed"
    assert validation["completion"]["complete"] is True
