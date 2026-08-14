from __future__ import annotations

from dataclasses import dataclass

import sophyane.v13_cli as cli
import sophyane.race_execution as execution


@dataclass
class FakeResult:
    ok: bool = True
    winner: str | None = "local"
    attempts: int = 2
    applied: list = None
    verifications: list = None
    error: str = ""

    def __post_init__(self):
        if self.applied is None:
            self.applied = [
                "write_file"
            ]

        if self.verifications is None:
            self.verifications = [
                "pytest"
            ]


def test_default_bridge_calls_apply_verify_loop(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_run(
        request,
        **kwargs,
    ):
        calls.append(
            (
                request,
                kwargs,
            )
        )

        return FakeResult()

    monkeypatch.setattr(
        execution,
        "run_race_apply_verify",
        fake_run,
    )

    result = (
        cli._run_adaptive_race_request(
            "repair tests",
            workspace=tmp_path,
            config={
                "provider": "gemini"
            },
            timeout=42,
        )
    )

    assert len(calls) == 1

    request, kwargs = (
        calls[0]
    )

    assert request == "repair tests"

    assert (
        kwargs["workspace"]
        == tmp_path
    )

    assert (
        kwargs["race_timeout"]
        == 42
    )

    assert (
        kwargs["max_rounds"]
        == 3
    )

    assert result["ok"] is True
    assert result["winner"] == "local"
    assert result["attempts"] == 2


def test_failed_execution_bridge_is_truthful(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        execution,
        "run_race_apply_verify",
        lambda *args, **kwargs:
            FakeResult(
                ok=False,
                winner="sli",
                attempts=3,
                applied=[],
                verifications=[],
                error="maximum rounds exhausted",
            ),
    )

    result = (
        cli._run_adaptive_race_request(
            "repair",
            workspace=tmp_path,
            config={},
        )
    )

    assert result["ok"] is False

    assert (
        result["error"]
        == "maximum rounds exhausted"
    )


def test_default_session_remains_race(
    monkeypatch,
):
    monkeypatch.delenv(
        "SOPHYANE_SESSION_MODE",
        raising=False,
    )

    assert (
        cli._execution_session_mode()
        == "race"
    )

    assert (
        cli._should_use_adaptive_race()
        is True
    )
