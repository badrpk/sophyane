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


def test_browser_delivery_requires_open_step_before_success(tmp_path: Path, monkeypatch):
    import sophyane.race_execution as execution

    calls = []

    def runner(request, **kwargs):
        index = len(calls)
        calls.append(request)
        action = (
            {"type": "write_file", "path": "snake.html", "content": "<canvas/>"}
            if index == 0
            else {"type": "open_browser", "url": "file://snake.html"}
        )
        return race_with_action(action)

    def apply(*, engine, action, workspace, lease):
        return execution.AppliedAction(engine, action, ("snake.html",) if action["type"] == "write_file" else ())

    monkeypatch.setattr(execution, "_apply_action", apply)
    result = execution.run_race_apply_verify(
        "Create a Snake game and open it in the browser",
        workspace=tmp_path, config={}, race_runner=runner,
        verifier=lambda workspace: [], max_rounds=2,
    )
    assert result.ok
    assert [item.action["type"] for item in result.applied] == ["write_file", "open_browser"]
    assert len(calls) == 2


def test_non_browser_write_still_completes_without_delivery_step(tmp_path: Path):
    result = run_race_apply_verify(
        "Write a value file", workspace=tmp_path, config={},
        race_runner=lambda *args, **kwargs: race_with_action(
            {"type": "write_file", "path": "value.txt", "content": "ok"}
        ), verifier=lambda workspace: [],
    )
    assert result.ok



def _trusted_exact_race(action):
    return FakeRace(
        winner=Winner(
            worker="sli",
            value=ProgressProposal(
                engine="sli",
                payload={
                    "route": "deterministic_capability",
                    "success": True,
                    "capability": "filesystem.write_exact_verified",
                    "action": action,
                },
                kind="action",
                confidence=0.9,
                evidence=(
                    "verified exact write",
                ),
                requires_write=False,
            ),
        )
    )


def test_trusted_exact_write_non_browser_keeps_immediate_success(
    tmp_path: Path,
    monkeypatch,
):
    import sophyane.race_execution as execution

    calls = []

    def runner(request, **kwargs):
        calls.append(request)
        return _trusted_exact_race(
            {
                "type": "write_file",
                "path": "artifact.txt",
                "content": "verified",
            }
        )

    monkeypatch.setattr(
        execution,
        "_apply_action",
        lambda *, engine, action, workspace, lease: execution.AppliedAction(
            engine,
            action,
            ("artifact.txt",),
        ),
    )

    def verifier(_workspace):
        raise AssertionError(
            "trusted exact write must retain its verification isolation"
        )

    result = execution.run_race_apply_verify(
        "Write an exact artifact file",
        workspace=tmp_path,
        config={},
        race_runner=runner,
        verifier=verifier,
        max_rounds=2,
    )

    assert result.ok
    assert len(calls) == 1
    assert [
        item.action["type"]
        for item in result.applied
    ] == ["write_file"]


def test_trusted_exact_write_browser_request_continues_after_write(
    tmp_path: Path,
    monkeypatch,
):
    import sophyane.race_execution as execution

    calls = []

    def runner(request, **kwargs):
        calls.append(request)

        if len(calls) == 1:
            return _trusted_exact_race(
                {
                    "type": "write_file",
                    "path": "index.html",
                    "content": "<html><body>artifact</body></html>",
                }
            )

        return race_with_action(
            {
                "type": "open_browser",
                "url": "file://index.html",
            }
        )

    def apply(*, engine, action, workspace, lease):
        changed = (
            ("index.html",)
            if action["type"] == "write_file"
            else ()
        )
        return execution.AppliedAction(
            engine,
            action,
            changed,
        )

    monkeypatch.setattr(
        execution,
        "_apply_action",
        apply,
    )

    verifier_calls = 0

    def verifier(_workspace):
        nonlocal verifier_calls
        verifier_calls += 1
        return []

    result = execution.run_race_apply_verify(
        "Create an artifact and open it in the browser",
        workspace=tmp_path,
        config={},
        race_runner=runner,
        verifier=verifier,
        max_rounds=2,
    )

    assert result.ok
    assert len(calls) == 2
    assert verifier_calls == 1
    assert "browser delivery has not" in calls[1].lower()
    assert [
        item.action["type"]
        for item in result.applied
    ] == [
        "write_file",
        "open_browser",
    ]


def test_trusted_exact_write_browser_request_needs_second_round(
    tmp_path: Path,
    monkeypatch,
):
    import sophyane.race_execution as execution

    calls = []

    def runner(request, **kwargs):
        calls.append(request)
        return _trusted_exact_race(
            {
                "type": "write_file",
                "path": "index.html",
                "content": "<html><body>artifact</body></html>",
            }
        )

    monkeypatch.setattr(
        execution,
        "_apply_action",
        lambda *, engine, action, workspace, lease: execution.AppliedAction(
            engine,
            action,
            ("index.html",),
        ),
    )

    result = execution.run_race_apply_verify(
        "Create an artifact and open it in the browser",
        workspace=tmp_path,
        config={},
        race_runner=runner,
        verifier=lambda _workspace: [],
        max_rounds=1,
    )

    assert not result.ok
    assert len(calls) == 1
    assert [
        item.action["type"]
        for item in result.applied
    ] == ["write_file"]



def test_race_apply_action_executes_real_browser_action(
    tmp_path: Path,
    monkeypatch,
):
    import sophyane.execution_runtime as runtime
    import sophyane.race_execution as execution

    calls = []

    def fake_execute_action(action, workspace, progress):
        calls.append(
            (
                action,
                Path(workspace),
            )
        )
        return (
            True,
            "Browser command: termux-open-url http://127.0.0.1/example\n"
            "Exit code: 0\n",
        )

    monkeypatch.setattr(
        runtime,
        "execute_action",
        fake_execute_action,
    )

    lease = execution.WorkspaceWriteLease(
        tmp_path
    )
    assert lease.acquire(
        "local"
    )

    try:
        applied = execution._apply_action(
            engine="local",
            action={
                "type": "open_browser",
                "url": "file://index.html",
            },
            workspace=tmp_path,
            lease=lease,
        )
    finally:
        lease.release(
            "local"
        )

    assert applied.action["type"] == "open_browser"
    assert applied.changed_paths == ()
    assert len(calls) == 1
    assert calls[0][0]["type"] == "open_browser"
    assert calls[0][1] == tmp_path


def test_race_apply_action_rejects_failed_browser_action(
    tmp_path: Path,
    monkeypatch,
):
    import sophyane.execution_runtime as runtime
    import sophyane.race_execution as execution

    monkeypatch.setattr(
        runtime,
        "execute_action",
        lambda action, workspace, progress: (
            False,
            "Browser launch blocked: test failure",
        ),
    )

    lease = execution.WorkspaceWriteLease(
        tmp_path
    )
    assert lease.acquire(
        "local"
    )

    try:
        try:
            execution._apply_action(
                engine="local",
                action={
                    "type": "open_browser",
                    "url": "file://index.html",
                },
                workspace=tmp_path,
                lease=lease,
            )
        except RuntimeError as exc:
            assert "browser action failed" in str(exc)
        else:
            raise AssertionError(
                "failed browser runtime result must fail race action application"
            )
    finally:
        lease.release(
            "local"
        )


def test_usable_textual_winner_with_browser_presentation_does_not_rerace(tmp_path, monkeypatch):
    import sophyane.race_execution as execution
    calls = []

    def runner(request, **kwargs):
        calls.append(request)
        return race_with_action({"type": "respond", "message": "complete result"}, worker="external")

    monkeypatch.setattr(
        execution,
        "_apply_action",
        lambda *, engine, action, workspace, lease: execution.AppliedAction(engine, action, ()),
    )
    result = execution.run_race_apply_verify(
        "Provide the result and open it in the browser",
        workspace=tmp_path,
        config={},
        race_runner=runner,
        verifier=lambda workspace: [],
        max_rounds=3,
    )
    assert result.ok
    assert len(calls) == 1
