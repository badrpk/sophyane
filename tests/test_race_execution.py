from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sophyane.race_adapters import (
    ProgressProposal,
)
from sophyane.race_execution import (
    VerificationResult,
    run_race_apply_verify,
)


@dataclass
class Winner:
    worker: str
    value: ProgressProposal


@dataclass
class FakeRace:
    winner: Winner | None


def race_with_action(
    action,
    *,
    worker="local",
):
    return FakeRace(
        winner=Winner(
            worker=worker,
            value=ProgressProposal(
                engine=worker,
                payload={
                    "action": action
                },
                kind="action",
                confidence=0.9,
                evidence=(
                    "valid action",
                ),
                requires_write=False,
            ),
        )
    )


def test_write_then_green(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "value.txt"
    )

    def runner(
        *args,
        **kwargs,
    ):
        return race_with_action(
            {
                "type": "write_file",
                "path": "value.txt",
                "content": "42\n",
            }
        )

    def verifier(
        workspace,
    ):
        assert (
            target.read_text(
                encoding="utf-8"
            )
            == "42\n"
        )

        return [
            VerificationResult(
                ok=True,
                command=(
                    "fake-test",
                ),
                returncode=0,
                output="green",
            )
        ]

    result = run_race_apply_verify(
        "write value",
        workspace=tmp_path,
        config={},
        race_runner=runner,
        verifier=verifier,
    )

    assert result.ok
    assert len(result.applied) == 1


def test_failed_verification_triggers_new_race(
    tmp_path: Path,
):
    calls = []

    def runner(
        request,
        **kwargs,
    ):
        calls.append(
            request
        )

        if len(calls) == 1:
            return race_with_action(
                {
                    "type": "write_file",
                    "path": "value.txt",
                    "content": "bad\n",
                },
                worker="cloud",
            )

        return race_with_action(
            {
                "type": "write_file",
                "path": "value.txt",
                "content": "good\n",
            },
            worker="local",
        )

    verify_count = 0

    def verifier(
        workspace,
    ):
        nonlocal verify_count

        verify_count += 1

        value = (
            Path(workspace)
            / "value.txt"
        ).read_text(
            encoding="utf-8"
        )

        if value == "good\n":
            return [
                VerificationResult(
                    ok=True,
                    command=(
                        "pytest",
                    ),
                    returncode=0,
                    output="passed",
                )
            ]

        return [
            VerificationResult(
                ok=False,
                command=(
                    "pytest",
                ),
                returncode=1,
                output="expected good",
            )
        ]

    result = run_race_apply_verify(
        "repair value",
        workspace=tmp_path,
        config={},
        max_rounds=3,
        race_runner=runner,
        verifier=verifier,
    )

    assert result.ok
    assert len(calls) == 2
    assert verify_count == 2

    assert (
        "DETERMINISTIC VERIFICATION FAILED"
        in calls[1]
    )


def test_plan_winner_causes_another_race(
    tmp_path: Path,
):
    calls = []

    def runner(
        request,
        **kwargs,
    ):
        calls.append(
            request
        )

        if len(calls) == 1:
            return FakeRace(
                winner=Winner(
                    worker="sli",
                    value=ProgressProposal(
                        engine="sli",
                        payload={
                            "route": "harness_execution"
                        },
                        kind="acquisition",
                        confidence=0.9,
                        evidence=(
                            "valid acquisition",
                        ),
                        requires_write=False,
                    ),
                )
            )

        return race_with_action(
            {
                "type": "write_file",
                "path": "done.txt",
                "content": "done",
            }
        )

    result = run_race_apply_verify(
        "complete task",
        workspace=tmp_path,
        config={},
        max_rounds=2,
        race_runner=runner,
        verifier=lambda workspace: [],
    )

    assert result.ok
    assert len(calls) == 2

    assert (
        "RACE CONTEXT"
        in calls[1]
    )


def test_path_escape_rejected_and_reraced(
    tmp_path: Path,
):
    calls = 0

    def runner(
        request,
        **kwargs,
    ):
        nonlocal calls
        calls += 1

        if calls == 1:
            return race_with_action(
                {
                    "type": "write_file",
                    "path": "../escape.txt",
                    "content": "bad",
                }
            )

        return race_with_action(
            {
                "type": "write_file",
                "path": "safe.txt",
                "content": "good",
            }
        )

    result = run_race_apply_verify(
        "write safely",
        workspace=tmp_path,
        config={},
        max_rounds=2,
        race_runner=runner,
        verifier=lambda workspace: [],
    )

    assert result.ok

    assert not (
        tmp_path.parent
        / "escape.txt"
    ).exists()

    assert (
        tmp_path
        / "safe.txt"
    ).exists()


def test_no_valid_winner_fails_cleanly(
    tmp_path: Path,
):
    def runner(
        *args,
        **kwargs,
    ):
        return FakeRace(
            winner=None
        )

    result = run_race_apply_verify(
        "task",
        workspace=tmp_path,
        config={},
        race_runner=runner,
    )

    assert not result.ok

    assert (
        "no valid winner"
        in result.error
    )
