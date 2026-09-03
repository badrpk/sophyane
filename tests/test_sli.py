from pathlib import Path

from sophyane import sli
from sophyane.sli_learner import calculate_quality_reward, classify_action


def test_execution_memory_outranks_scanned_logs(tmp_path: Path) -> None:
    with sli.connect(tmp_path / "sli.db") as db:
        for _ in range(20):
            sli.record(
                db,
                request="make a calculator",
                action="INSPECT_EVIDENCE",
                reward=1.0,
                source_type="scanned_log",
            )
        for _ in range(2):
            sli.record(
                db,
                request="make a calculator",
                action="GENERATE_BROWSER_ARTIFACT",
                reward=1.0,
                source_type="execution",
            )
        recommendations = sli.recommend_actions(
            db,
            request="make a simple calculator",
        )
    assert recommendations[0]["action"] == "GENERATE_BROWSER_ARTIFACT"


def test_verified_browser_success_receives_full_reward() -> None:
    reward, signals, category = calculate_quality_reward(
        status="succeeded",
        result=(
            "Browser artifact passed structural verification; "
            "opening verified browser preview. Project completed successfully."
        ),
        workspace_before={"sample": []},
        workspace_after={"sample": [{"path": "index.html", "bytes": 1458}]},
    )
    assert reward == 1.0
    assert category == ""
    assert "artifact_created:+0.20" in signals
    assert "validation_passed:+0.20" in signals


def test_read_verified_history_uses_deterministic_similarity(tmp_path, monkeypatch):
    import json
    import sqlite3

    import sophyane.sli as sqlite_sli
    from sophyane.sli_learner import read_verified_history

    database = tmp_path / "sli.db"
    monkeypatch.setattr(sqlite_sli, "DB_PATH", database)
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE learned_execution_traces ("
            "trace_id TEXT, created_at REAL, provenance_json TEXT)"
        )
        trusted = {
            "accepted": True, "verification_state": "verified",
            "status": "succeeded", "objective_hash": "objective-match",
            "original_objective": "build a verified artifact",
            "event_key": "event-match",
        }
        irrelevant = {
            "accepted": True, "verification_state": "verified",
            "status": "succeeded", "objective_hash": "objective-other",
            "original_objective": "unrelated task", "event_key": "event-other",
        }
        db.executemany(
            "INSERT INTO learned_execution_traces VALUES (?, ?, ?)",
            [("trace-match", 2, json.dumps(trusted, separators=(",", ":"))),
             ("trace-other", 1, json.dumps(irrelevant, separators=(",", ":")))],
        )
        db.commit()

    records = read_verified_history(request="build a verified artifact", limit=8)

    assert [record["event_key"] for record in records] == ["event-match"]


def test_unusable_response_is_categorized() -> None:
    reward, signals, category = calculate_quality_reward(
        status="failed",
        result=(
            "Execution stopped safely: provider could not produce a usable artifact. "
            "Previous working files were preserved."
        ),
        workspace_before={"sample": []},
        workspace_after={"sample": []},
    )
    assert category == "UNUSABLE_PROVIDER_RESPONSE"
    assert reward == -0.5
    assert "safe_failure_preservation:+0.10" in signals


def test_browser_requests_use_browser_action() -> None:
    assert classify_action("make a responsive tip calculator") == "GENERATE_BROWSER_ARTIFACT"
    assert classify_action("explain a repository") == "EXECUTE_STRUCTURED_TASK"


def test_sli_learner_paths_accepts_structured_snapshot():
    from sophyane.sli_learner import _paths

    snapshot = {
        "files": 2,
        "bytes": 1400,
        "sample": [
            {
                "path": "index.html",
                "bytes": 1200,
            },
            {
                "path": "assets/app.js",
                "bytes": 200,
            },
        ],
    }

    assert _paths(snapshot) == {
        "index.html",
        "assets/app.js",
    }


def test_sli_learner_paths_accepts_hash_snapshot():
    from sophyane.sli_learner import _paths

    snapshot = {
        "index.html": "abc123",
        "src/app.py": "def456",
    }

    assert _paths(snapshot) == {
        "index.html",
        "src/app.py",
    }


def test_sli_quality_reward_detects_html_from_hash_snapshot():
    from sophyane.sli_learner import (
        calculate_quality_reward,
    )

    reward, signals, category = (
        calculate_quality_reward(
            status="succeeded",
            result="Validation: passed",
            workspace_before={},
            workspace_after={
                "index.html": "abc123",
            },
        )
    )

    assert category == ""
    assert reward >= 0.85
    assert "artifact_created:+0.20" in signals
    assert "validation_passed:+0.20" in signals


def test_learn_execution_requests_rollback_mirror_after_writes(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        "0",
    )
    from contextlib import contextmanager

    import sophyane.sli_learner as learner

    events = []

    class FakeDB:
        pass

    @contextmanager
    def fake_connect():
        events.append("connect")
        yield FakeDB()
        events.append("close")

    def fake_record(
        db,
        **kwargs,
    ):
        assert isinstance(db, FakeDB)
        events.append("record")
        return 121

    def fake_store_trace(
        db,
        payload,
    ):
        assert isinstance(db, FakeDB)
        assert payload["trace_id"] == "phase3a-test"
        events.append("trace")

    def fake_mirror():
        events.append("mirror")
        return {
            "state": "synchronized",
            "memories_added": 1,
            "traces_added": 1,
            "memories": 121,
            "traces": 121,
        }

    monkeypatch.setattr(
        learner.sli,
        "connect",
        fake_connect,
    )

    monkeypatch.setattr(
        learner.sli,
        "record",
        fake_record,
    )

    monkeypatch.setattr(
        learner.sli,
        "store_trace",
        fake_store_trace,
    )

    monkeypatch.setattr(
        learner.sli,
        "synchronize_rollback_mirror",
        fake_mirror,
    )

    result = learner.learn_execution(
        trace_id="phase3a-test",
        request="inspect existing project safely",
        workspace_before={},
        workspace_after={},
        status="succeeded",
        reward=1.0,
        result="completed successfully",
        elapsed_seconds=0.001,
    )

    assert result["memory_id"] == 121

    assert result["rollback_mirror"] == {
        "state": "synchronized",
        "memories_added": 1,
        "traces_added": 1,
        "memories": 121,
        "traces": 121,
    }

    assert events == [
        "connect",
        "record",
        "trace",
        "close",
        "mirror",
    ]


def test_learn_execution_surfaces_mirror_failure(
    monkeypatch,
):
    monkeypatch.setenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        "0",
    )
    from contextlib import contextmanager

    import pytest
    import sophyane.sli_learner as learner

    @contextmanager
    def fake_connect():
        yield object()

    monkeypatch.setattr(
        learner.sli,
        "connect",
        fake_connect,
    )

    monkeypatch.setattr(
        learner.sli,
        "record",
        lambda db, **kwargs: 121,
    )

    monkeypatch.setattr(
        learner.sli,
        "store_trace",
        lambda db, payload: None,
    )

    def fail_mirror():
        raise RuntimeError(
            "simulated rollback mirror failure"
        )

    monkeypatch.setattr(
        learner.sli,
        "synchronize_rollback_mirror",
        fail_mirror,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated rollback mirror failure",
    ):
        learner.learn_execution(
            trace_id="phase3a-mirror-failure",
            request="inspect existing project safely",
            workspace_before={},
            workspace_after={},
            status="succeeded",
            reward=1.0,
            result="completed successfully",
            elapsed_seconds=0.001,
        )


def test_backend_sqlite_requires_no_rollback_mirror(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "sqlite",
    )

    assert (
        sli_backend.synchronize_rollback_mirror()
        is None
    )


def test_backend_postgres_delegates_to_cutover_synchronizer(
    monkeypatch,
):
    import sophyane.sli_backend as sli_backend
    import sophyane.sli_cutover as cutover

    sentinel_store = object()
    captured = {}

    monkeypatch.setenv(
        "SOPHYANE_SLI_BACKEND",
        "postgres",
    )

    monkeypatch.setattr(
        sli_backend,
        "postgres_store",
        lambda: sentinel_store,
    )

    def fake_sync(
        *,
        sqlite_path,
        store,
    ):
        captured["sqlite_path"] = sqlite_path
        captured["store"] = store

        return {
            "state": "synchronized",
            "memories_added": 1,
            "traces_added": 1,
        }

    monkeypatch.setattr(
        cutover,
        "synchronize_postgres_to_sqlite",
        fake_sync,
    )

    result = (
        sli_backend.synchronize_rollback_mirror()
    )

    assert result == {
        "state": "synchronized",
        "memories_added": 1,
        "traces_added": 1,
    }

    assert captured["sqlite_path"] == (
        sli_backend.sli.DB_PATH
    )

    assert captured["store"] is sentinel_store


def test_atomic_learning_gate_defaults_off(
    monkeypatch,
) -> None:
    import sophyane.sli_backend as backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        raising=False,
    )

    monkeypatch.setattr(
        backend,
        "load_config",
        lambda: {},
    )

    assert (
        backend.atomic_learning_enabled()
        is False
    )


def test_atomic_learning_gate_accepts_explicit_true(
    monkeypatch,
) -> None:
    import sophyane.sli_backend as backend

    for value in (
        "1",
        "true",
        "TRUE",
        "yes",
        "on",
    ):
        monkeypatch.setenv(
            "SOPHYANE_SLI_ATOMIC_LEARNING",
            value,
        )

        assert (
            backend.atomic_learning_enabled()
            is True
        )


def test_learner_event_digest_is_canonical() -> None:
    import sophyane.sli_learner as learner

    first = {
        "b":
            {
                "z": 2,
                "a": 1,
            },

        "a":
            [
                3,
                2,
                1,
            ],
    }

    second = {
        "a":
            [
                3,
                2,
                1,
            ],

        "b":
            {
                "a": 1,
                "z": 2,
            },
    }

    assert (
        learner._learner_event_digest(
            first
        )
        ==
        learner._learner_event_digest(
            second
        )
    )

    assert len(
        learner._learner_event_digest(
            first
        )
    ) == 64


def test_learn_execution_preserves_legacy_path_when_atomic_disabled(
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    import sophyane.sli_learner as learner

    events = []

    class FakeDB:
        pass

    @contextmanager
    def fake_connect():
        events.append(
            "connect"
        )

        yield FakeDB()

        events.append(
            "close"
        )

    monkeypatch.setattr(
        learner.sli,
        "connect",
        fake_connect,
    )

    monkeypatch.setattr(
        learner.sli,
        "selected_backend",
        lambda: "postgres",
    )

    monkeypatch.setattr(
        learner.sli,
        "atomic_learning_enabled",
        lambda: False,
    )

    def fake_record(
        db,
        **kwargs,
    ):
        assert isinstance(
            db,
            FakeDB,
        )

        events.append(
            "record"
        )

        return 121

    def fake_trace(
        db,
        payload,
    ):
        assert isinstance(
            db,
            FakeDB,
        )

        assert payload[
            "trace_id"
        ] == "legacy-disabled"

        events.append(
            "trace"
        )

    monkeypatch.setattr(
        learner.sli,
        "record",
        fake_record,
    )

    monkeypatch.setattr(
        learner.sli,
        "store_trace",
        fake_trace,
    )

    monkeypatch.setattr(
        learner.sli,
        "atomic_learn_execution",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "atomic path must not run"
                )
            )
        ),
    )

    monkeypatch.setattr(
        learner.sli,
        "synchronize_rollback_mirror",
        lambda: (
            events.append(
                "mirror"
            )
            or {
                "state":
                    "synchronized",
            }
        ),
    )

    result = learner.learn_execution(
        trace_id=
            "legacy-disabled",

        request=
            "inspect existing project safely",

        workspace_before=
            {},

        workspace_after=
            {},

        status=
            "succeeded",

        reward=
            1.0,

        result=
            "completed successfully",

        elapsed_seconds=
            0.001,
    )

    assert result[
        "memory_id"
    ] == 121

    assert (
        "atomic_learning"
        not in result
    )

    assert events == [
        "connect",
        "record",
        "trace",
        "close",
        "mirror",
    ]


def test_atomic_learning_gate_accepts_persistent_true(
    monkeypatch,
) -> None:
    from sophyane import sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend": "postgres",
            "sli_atomic_learning": True,
        },
    )

    assert (
        sli_backend.atomic_learning_enabled()
        is True
    )


def test_atomic_learning_environment_false_overrides_persistent_true(
    monkeypatch,
) -> None:
    from sophyane import sli_backend

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend": "postgres",
            "sli_atomic_learning": True,
        },
    )

    monkeypatch.setenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        "0",
    )

    assert (
        sli_backend.atomic_learning_enabled()
        is False
    )


def test_atomic_learning_invalid_persistent_value_fails_closed(
    monkeypatch,
) -> None:
    import pytest

    from sophyane import sli_backend

    monkeypatch.delenv(
        "SOPHYANE_SLI_ATOMIC_LEARNING",
        raising=False,
    )

    monkeypatch.setattr(
        sli_backend,
        "load_config",
        lambda: {
            "sli_backend": "postgres",
            "sli_atomic_learning": "maybe",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported atomic-learning value",
    ):
        sli_backend.atomic_learning_enabled()


def test_repository_memory_hit_is_disk_first_and_target_bound(tmp_path, monkeypatch):
    import json
    import sophyane.sli_graph as graph
    monkeypatch.setenv("HOME", str(tmp_path))
    evidence = tmp_path / "1-xerus.json"
    evidence.write_text(json.dumps({"target_name": "xerus", "status": "ready"}), encoding="utf-8")
    monkeypatch.setattr(graph, "_local_repository_evidence", lambda target: (str(evidence),))
    progress = []
    state = graph.run_sli_graph(
        "What existing local memory do you have about the Xerus repository? Search local stored memory first.",
        workspace=tmp_path / "workspace", progress=progress,
    )
    assert state.success
    assert state.route == "repository_memory"
    assert "1-xerus.json" in state.report
    assert "LOCAL_MEMORY_HIT=YES" in state.report
    assert "internet acquire" not in " ".join(progress).lower()


def test_repository_memory_miss_preserves_target_on_fallback(tmp_path, monkeypatch):
    import sophyane.sli_graph as graph
    monkeypatch.setenv("HOME", str(tmp_path))
    captured = []
    module = __import__("sophyane.code_memory.internet_acquire", fromlist=["acquire_and_build"])
    monkeypatch.setattr(module, "acquire_and_build", lambda request, **kwargs: captured.append(request) or "fallback")
    state = graph.SLIState("Tell me about the Droidra repository from stored memory", str(tmp_path / "workspace"))
    progress = []
    graph.try_memory_router(state, progress.append)
    assert state.meta["local_memory_checked"] is True
    assert state.meta["local_memory_hit"] is False
    graph.try_internet(state, progress.append)
    assert captured and "droidra" in captured[0].lower()
    assert "what existing local memory" not in captured[0].lower()


def test_request_authority_context_is_immutable_and_preserves_multiline_objective(tmp_path):
    from dataclasses import FrozenInstanceError
    import sophyane.sli_graph as graph
    objective = "What local memory exists about Xerus?\nSearch local stored memory first.\nDo not use internet.\nReport route."
    state = graph.run_sli_graph(objective, workspace=tmp_path / "workspace")
    assert state.context is not None
    assert state.context.original_objective == objective
    import hashlib
    assert state.context.original_objective_hash == hashlib.sha256(objective.encode()).hexdigest()
    try:
        state.context.original_objective = "fragment"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("authority context must be frozen")
    assert "LOGICAL_OBJECTIVES=1" in state.report


def test_authority_diagnostics_record_txq_and_rsi(tmp_path):
    import sophyane.sli_graph as graph
    state = graph.run_sli_graph("What existing local memory do you have about Xerus?", workspace=tmp_path / "workspace")
    assert "TXQ_CAPABILITY=repository_memory" in state.report
    assert "RSI_OUTCOME_RECORDED=YES" in state.report


def test_sli_context_supplied_to_graph_cannot_change_objective(tmp_path):
    import hashlib
    import sophyane.sli_graph as graph
    objective = "Xerus repository memory\nlocal first"
    context = graph.RequestAuthorityContext(objective, hashlib.sha256(objective.encode()).hexdigest(), txq_capability="repository_memory")
    state = graph.run_sli_graph("fragment", workspace=tmp_path / "workspace", context=context)
    assert state.request == objective
    assert state.context.original_objective_hash == context.original_objective_hash


def test_fallback_identity_authority_diagnostics_use_execution_truth():
    import sophyane.sli_graph as graph
    context = graph.RequestAuthorityContext("repo memory", "h", target_identity="xerus", fallback_identity_preserved=True)
    state = graph.SLIState("repo memory", ".", context=context)
    state.meta["repository_target"] = "xerus"
    assert "FALLBACK_IDENTITY_PRESERVED=YES" in graph._authority_diagnostics(state)
    state.context = context.evolve(fallback_identity_preserved=False)
    assert "FALLBACK_IDENTITY_PRESERVED=NO" in graph._authority_diagnostics(state)


def test_non_repository_fallback_identity_is_neutral():
    import sophyane.sli_graph as graph
    context = graph.RequestAuthorityContext("general question", "h")
    state = graph.SLIState("general question", ".", context=context)
    assert "FALLBACK_IDENTITY_PRESERVED=N/A" in graph._authority_diagnostics(state)
