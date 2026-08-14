from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.race_execution as race_execution

from sophyane.race_adapters import ProgressProposal


ARTIFACT_REQUEST = (
    "Generate an OpenAPI specification and functional backend "
    "mocking stub for the supplied API description."
)


def _race_with_action(
    action: dict,
    *,
    worker: str = "cloud",
):
    proposal = ProgressProposal(
        engine=worker,
        payload={
            "action": action,
        },
        kind="execution",
        confidence=0.95,
        evidence=(
            "synthetic deterministic race fixture",
        ),
        requires_write=True,
    )

    winner = SimpleNamespace(
        worker=worker,
        value=proposal,
    )

    return SimpleNamespace(
        winner=winner,
    )


def _respond_only_race(
    *args,
    **kwargs,
):
    """
    Valid executable action, but no material workspace output.
    """
    return _race_with_action(
        {
            "type": "respond",
            "content": (
                "I would generate an OpenAPI specification "
                "and backend mocking stub."
            ),
        }
    )


def _write_artifact_race(
    *args,
    **kwargs,
):
    return _race_with_action(
        {
            "type": "write_file",
            "path": "openapi.yaml",
            "content": (
                "openapi: 3.1.0\n"
                "info:\n"
                "  title: Generated API\n"
                "  version: 1.0.0\n"
                "paths: {}\n"
            ),
        }
    )


def _green_verifier(
    workspace,
):
    """
    Deliberately no deterministic verifier.

    This isolates finalization semantics from pytest behavior.
    """
    return []


def test_artifact_request_rejects_respond_only_false_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    An artifact-construction objective cannot be satisfied merely by
    executing a respond action.

    This is the live false-success shape we need to prevent:
    Attempts: 1, Applied: 1, but no requested artifact exists.
    """

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        _green_verifier,
    )

    result = race_execution.run_race_apply_verify(
        ARTIFACT_REQUEST,
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_respond_only_race,
        verifier=_green_verifier,
    )

    files = [
        path
        for path in tmp_path.rglob("*")
        if path.is_file()
    ]

    assert files == []

    assert len(result.applied) == 1
    assert result.applied[0].changed_paths == ()

    # TARGET CONTRACT:
    #
    # A construction request with no material filesystem output must
    # not be finalized as successful.
    assert result.ok is False


def test_artifact_request_accepts_real_file_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    The new contract must not block genuine material construction.
    """

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        _green_verifier,
    )

    result = race_execution.run_race_apply_verify(
        ARTIFACT_REQUEST,
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=_write_artifact_race,
        verifier=_green_verifier,
    )

    artifact = (
        tmp_path
        / "openapi.yaml"
    )

    assert artifact.is_file()
    assert "openapi: 3.1.0" in artifact.read_text(
        encoding="utf-8"
    )

    assert len(result.applied) == 1
    assert result.applied[0].changed_paths == (
        "openapi.yaml",
    )

    assert result.ok is True
