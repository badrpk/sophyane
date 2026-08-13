from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sophyane.race_execution import (
    VerificationResult,
    run_race_apply_verify,
)


REQUEST = (
    "Create a file named event18.txt containing exactly: "
    "Sophyane event 18 learning verification"
)

EXPECTED = "Sophyane event 18 learning verification"


class FakeRace:
    def __init__(self, winner):
        self.winner = winner


def _winner(
    content: str,
    *,
    worker: str = "sli",
    route: str = "deterministic_capability",
    capability: str = "filesystem.write_exact_verified",
    success: bool = True,
):
    proposal = SimpleNamespace(
        payload={
            "route": route,
            "success": success,
            "capability": capability,
            "action": {
                "type": "write_file",
                "path": "event18.txt",
                "content": content,
            },
        }
    )

    return SimpleNamespace(
        worker=worker,
        value=proposal,
    )


def _failing_verifier(calls):
    def verifier(_workspace):
        calls.append("verify")

        return [
            VerificationResult(
                ok=False,
                command=(
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    "--maxfail=1",
                ),
                returncode=1,
                output=(
                    "FAILED "
                    "tests/test_platform_kernel.py::"
                    "test_eval_and_prompt_advice"
                ),
            )
        ]

    return verifier


def test_verified_sli_exact_write_isolated_from_unrelated_workspace_failure(
    tmp_path: Path,
):
    race_calls = []
    verify_calls = []

    def race_runner(
        request,
        *,
        workspace,
        config,
        progress,
        timeout,
    ):
        race_calls.append(request)

        if len(race_calls) > 1:
            raise AssertionError(
                "trusted exact write must not enter repair race"
            )

        return FakeRace(
            _winner(EXPECTED)
        )

    result = run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        race_runner=race_runner,
        verifier=_failing_verifier(verify_calls),
        max_rounds=3,
    )

    target = tmp_path / "event18.txt"

    assert result.ok is True
    assert race_calls == [REQUEST]

    # The capability already performed deterministic byte verification.
    # Repository-wide verification must not be invoked for this trusted path.
    assert verify_calls == []

    assert target.exists()
    assert target.read_bytes() == EXPECTED.encode("utf-8")


def test_provider_write_does_not_receive_exact_write_bypass(
    tmp_path: Path,
):
    race_calls = []
    verify_calls = []

    def race_runner(
        request,
        *,
        workspace,
        config,
        progress,
        timeout,
    ):
        race_calls.append(request)

        if len(race_calls) == 1:
            return FakeRace(
                _winner(
                    EXPECTED,
                    worker="cloud",
                    route="provider",
                    capability="",
                )
            )

        return FakeRace(
            _winner(
                "repair",
                worker="cloud",
                route="provider",
                capability="",
            )
        )

    result = run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        race_runner=race_runner,
        verifier=_failing_verifier(verify_calls),
        max_rounds=2,
    )

    assert len(race_calls) == 2
    assert len(verify_calls) == 2
    assert result.ok is False


def test_failed_deterministic_capability_does_not_receive_bypass(
    tmp_path: Path,
):
    race_calls = []
    verify_calls = []

    def race_runner(
        request,
        *,
        workspace,
        config,
        progress,
        timeout,
    ):
        race_calls.append(request)

        return FakeRace(
            _winner(
                EXPECTED,
                success=False,
            )
        )

    result = run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        race_runner=race_runner,
        verifier=_failing_verifier(verify_calls),
        max_rounds=1,
    )

    assert len(race_calls) == 1
    assert len(verify_calls) == 1
    assert result.ok is False


def test_other_deterministic_capability_does_not_receive_bypass(
    tmp_path: Path,
):
    race_calls = []
    verify_calls = []

    def race_runner(
        request,
        *,
        workspace,
        config,
        progress,
        timeout,
    ):
        race_calls.append(request)

        return FakeRace(
            _winner(
                EXPECTED,
                capability="filesystem.some_other_capability",
            )
        )

    result = run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        race_runner=race_runner,
        verifier=_failing_verifier(verify_calls),
        max_rounds=1,
    )

    assert len(race_calls) == 1
    assert len(verify_calls) == 1
    assert result.ok is False
