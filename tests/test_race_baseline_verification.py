from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.race_execution as race_execution

from sophyane.race_execution import (
    VerificationResult,
    run_race_apply_verify,
)


class _Winner:
    worker = "test-worker"

    def __init__(self) -> None:
        self.value = SimpleNamespace(
            payload={
                "action": {
                    "type": "write_file",
                    "path": "generated.py",
                    "content": "VALUE = 1\n",
                }
            }
        )


def _race_runner(*args, **kwargs):
    return SimpleNamespace(
        winner=_Winner(),
    )


def _failure(output: str) -> list[VerificationResult]:
    return [
        VerificationResult(
            ok=False,
            command=("pytest", "-q"),
            returncode=1,
            output=output,
        )
    ]


def _success() -> list[VerificationResult]:
    return [
        VerificationResult(
            ok=True,
            command=("pytest", "-q"),
            returncode=0,
            output="passed",
        )
    ]


def test_custom_verifier_remains_post_action_only(
    tmp_path: Path,
) -> None:
    calls = 0

    def verifier(workspace):
        nonlocal calls
        calls += 1

        assert (
            Path(workspace) / "generated.py"
        ).exists()

        return _success()

    result = run_race_apply_verify(
        "Generate an OpenAPI backend stub.",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_race_runner,
        verifier=verifier,
    )

    assert calls == 1
    assert result.ok is True
    assert result.error == ""


def test_production_verifier_ignores_identical_baseline_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0
    failure = _failure(
        "ERROR collecting tests/test_native_imap_engine.py\n"
        "ModuleNotFoundError: No module named 'psycopg'"
    )

    def fake_verify_workspace(workspace):
        nonlocal calls
        calls += 1
        return failure

    # Patch the module-level production verifier before passing it.
    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        fake_verify_workspace,
    )

    result = run_race_apply_verify(
        "Generate an OpenAPI backend stub.",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_race_runner,
        verifier=fake_verify_workspace,
    )

    assert calls == 2
    assert result.ok is True
    assert result.error == ""


def test_production_verifier_rejects_new_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    def fake_verify_workspace(workspace):
        nonlocal calls
        calls += 1

        if calls == 1:
            return _success()

        return _failure(
            "FAILED tests/test_generated.py::test_contract\n"
            "AssertionError"
        )

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        fake_verify_workspace,
    )

    result = run_race_apply_verify(
        "Generate an OpenAPI backend stub.",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_race_runner,
        verifier=fake_verify_workspace,
    )

    assert calls == 2
    assert result.ok is False
    assert (
        result.error
        == "maximum adaptive repair rounds exhausted"
    )


def test_production_verifier_ignores_only_pytest_elapsed_time_difference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    baseline = _failure(
        "ERROR collecting tests/test_native_imap_engine.py\n"
        "ModuleNotFoundError: No module named 'psycopg'\n"
        "1 error in 0.45s"
    )

    post = _failure(
        "ERROR collecting tests/test_native_imap_engine.py\n"
        "ModuleNotFoundError: No module named 'psycopg'\n"
        "1 error in 0.46s"
    )

    def fake_verify_workspace(workspace):
        nonlocal calls
        calls += 1
        return baseline if calls == 1 else post

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        fake_verify_workspace,
    )

    result = run_race_apply_verify(
        "Generate an OpenAPI backend stub.",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_race_runner,
        verifier=fake_verify_workspace,
    )

    assert calls == 2
    assert result.ok is True
    assert result.error == ""


def test_production_verifier_does_not_hide_changed_exception(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    baseline = _failure(
        "ERROR collecting tests/test_native_imap_engine.py\n"
        "ModuleNotFoundError: No module named 'psycopg'\n"
        "1 error in 0.45s"
    )

    post = _failure(
        "ERROR collecting tests/test_native_imap_engine.py\n"
        "RuntimeError: database configuration corrupted\n"
        "1 error in 0.46s"
    )

    def fake_verify_workspace(workspace):
        nonlocal calls
        calls += 1
        return baseline if calls == 1 else post

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        fake_verify_workspace,
    )

    result = run_race_apply_verify(
        "Generate an OpenAPI backend stub.",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_race_runner,
        verifier=fake_verify_workspace,
    )

    assert calls == 2
    assert result.ok is False
    assert (
        result.error
        == "maximum adaptive repair rounds exhausted"
    )
