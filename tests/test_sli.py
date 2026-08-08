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
