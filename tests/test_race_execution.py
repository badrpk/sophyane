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


def test_verified_success_emits_provenance_rich_learning_event(tmp_path, monkeypatch):
    import hashlib
    import sophyane.race_execution as execution
    import sophyane.sli_learner as learner

    captured = []
    monkeypatch.setattr(learner, "learn_execution", lambda **kwargs: captured.append(kwargs) or {"quality_reward": 1.0})

    result = run_race_apply_verify(
        "Create a verified artifact",
        workspace=tmp_path,
        config={},
        race_runner=lambda *args, **kwargs: race_with_action(
            {"type": "write_file", "path": "artifact.html", "content": "<h1>ok</h1>"},
            worker="api:gemini",
        ),
        verifier=lambda workspace: [
            VerificationResult(True, ("pytest",), 0, "passed structural verification")
        ],
    )

    assert result.ok
    assert len(captured) == 1
    event = captured[0]["provenance"]
    assert event["original_objective"] == "Create a verified artifact"
    assert event["objective_hash"] == hashlib.sha256(
        b"Create a verified artifact"
    ).hexdigest()
    assert event["accepted"] is True
    assert event["verification_state"] == "verified"
    assert event["changed_paths"] == ["artifact.html"]
    assert event["artifact_paths"] == ["artifact.html"]
    assert event["provider_identity"] == "api:gemini"
    assert event["capability_class"] == "external_api"
    assert event["verification_evidence"][0]["output"] == "passed structural verification"
    assert result.learning_event["objective_hash"] == event["objective_hash"]


def test_verification_failure_emits_no_positive_learning_event(tmp_path, monkeypatch):
    import sophyane.sli_learner as learner

    calls = []
    monkeypatch.setattr(learner, "learn_execution", lambda **kwargs: calls.append(kwargs))
    result = run_race_apply_verify(
        "Create an invalid artifact",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=lambda *args, **kwargs: race_with_action(
            {"type": "write_file", "path": "bad.html", "content": "bad"}
        ),
        verifier=lambda workspace: [
            VerificationResult(False, ("pytest",), 1, "validation failed")
        ],
    )
    assert not result.ok
    assert calls == []
    assert result.learning_event is None


def test_verified_learning_event_is_idempotent(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    import sophyane.sli as sqlite_sli
    import sophyane.sli_learner as learner

    database = tmp_path / "sli.db"

    @contextmanager
    def connect():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        sqlite_sli.initialize(db)
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(learner.sli, "connect", connect)
    monkeypatch.setattr(learner.sli, "selected_backend", lambda: "sqlite")
    monkeypatch.setattr(learner.sli, "atomic_learning_enabled", lambda: False)
    monkeypatch.setattr(learner.sli, "synchronize_rollback_mirror", lambda: None)

    provenance = {
        "objective_hash": "h" * 64,
        "original_objective": "same objective",
        "status": "succeeded",
        "verification_state": "verified",
        "verification_evidence": [{"ok": True}],
        "accepted": True,
        "workspace": str(tmp_path),
        "changed_paths": ["artifact.html"],
        "artifact_paths": ["artifact.html"],
        "provider_identity": "api:test",
        "capability_class": "external_api",
        "result": "verified",
    }
    kwargs = dict(
        request="same objective", workspace_before={}, workspace_after={"artifact.html": "x"},
        status="succeeded", reward=1.0, result="verified", elapsed_seconds=0.0, provenance=provenance,
    )
    first = learner.learn_execution(trace_id="first", **kwargs)
    second = learner.learn_execution(trace_id="second", **kwargs)
    assert first.get("deduplicated") is not True
    assert second["deduplicated"] is True
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT provenance_json FROM learned_execution_traces"
        ).fetchone()
    assert row is not None
    assert '"objective_hash":"' + ("h" * 64) in row[0]
    assert '"verification_state":"verified"' in row[0]


def test_terminal_apply_failure_emits_no_positive_learning_event(tmp_path, monkeypatch):
    import sophyane.sli_learner as learner

    calls = []
    monkeypatch.setattr(learner, "learn_execution", lambda **kwargs: calls.append(kwargs))
    result = run_race_apply_verify(
        "Write safely",
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=lambda *args, **kwargs: race_with_action(
            {"type": "write_file", "path": "../forbidden.txt", "content": "x"}
        ),
    )
    assert not result.ok
    assert calls == []
    assert result.learning_event is None


def test_verified_learning_triggers_explicit_promotion_without_rerouting(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    import sophyane.sli as sqlite_sli
    import sophyane.sli_learner as learner

    database = tmp_path / "sli.db"
    artifact = tmp_path / "artifact.html"
    artifact.write_text("<h1>verified</h1>", encoding="utf-8")

    @contextmanager
    def connect():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        sqlite_sli.initialize(db)
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(learner.sli, "connect", connect)
    monkeypatch.setattr(learner.sli, "selected_backend", lambda: "sqlite")
    monkeypatch.setattr(learner.sli, "atomic_learning_enabled", lambda: False)
    monkeypatch.setattr(learner.sli, "synchronize_rollback_mirror", lambda: None)
    promotions = []
    monkeypatch.setattr(
        "sophyane.code_memory.promote_success.promote_workspace",
        lambda *args, **kwargs: promotions.append((args, kwargs)) or {"ok": True, "chunks_added": 1},
    )

    provenance = {
        "objective_hash": "a" * 64,
        "original_objective": "create verified artifact",
        "status": "succeeded",
        "verification_state": "verified",
        "verification_evidence": [{"ok": True, "command": ["pytest"]}],
        "accepted": True,
        "workspace": str(tmp_path),
        "changed_paths": ["artifact.html"],
        "artifact_paths": ["artifact.html"],
        "repository_identity": "repo-a",
        "provider_identity": "api:test",
        "capability_class": "external_api",
    }
    result = learner.learn_execution(
        trace_id="verified-promotion", request="create verified artifact",
        workspace_before={}, workspace_after={"artifact.html": "hash"},
        status="succeeded", reward=1.0, result="verified", elapsed_seconds=0.0,
        provenance=provenance,
    )
    assert result["promotion"]["ok"] is True
    assert len(promotions) == 1
    assert promotions[0][1]["paths"] == ["artifact.html"]
    assert promotions[0][1]["provenance"]["repository_identity"] == "repo-a"


def test_verified_promotion_writes_retrievable_chunk_with_provenance(tmp_path, monkeypatch):
    from sophyane.code_memory.promote_success import promote_workspace
    from sophyane.code_memory.store import ChunkStore

    memory_root = tmp_path / "memory"
    monkeypatch.setenv("SOPHYANE_HOME", str(memory_root))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "artifact.py"
    source.write_text(
        "def verified_artifact(value):\n    return value * 2\n\n"
        "# deterministic verified output\n",
        encoding="utf-8",
    )
    provenance = {
        "accepted": True,
        "verification_state": "verified",
        "objective_hash": "b" * 64,
        "repository_identity": "repo-b",
    }
    report = promote_workspace(
        workspace, request="create artifact",
        report="success: true validation: passed",
        paths=["artifact.py"], provenance=provenance,
    )
    assert report["ok"] is True
    store = ChunkStore()
    chunks = [chunk for chunk in store.chunks.values() if Path(chunk.path).name == "artifact.py"]
    assert chunks
    assert chunks[0].meta["verified_provenance"]["repository_identity"] == "repo-b"
    assert chunks[0].meta["verified_provenance"]["objective_hash"] == "b" * 64
