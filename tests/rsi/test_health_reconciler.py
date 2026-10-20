import sqlite3
from pathlib import Path

from sophyane.rsi.health_reconciler import HealthReconciler


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_creates_sqlite_schema_and_persists_metrics_and_git_parity(tmp_path):
    clock = Clock()
    samples = {"node-a": {"memory_bytes": 1234, "open_fds": 7}}
    commits = {str(tmp_path / "repo-a"): "abc123"}
    reconciler = HealthReconciler(
        tmp_path / "health.sqlite3",
        clock=clock,
        sampler=lambda node_id, _repository: samples[node_id],
        git_probe=lambda repository: commits[str(repository)],
    )
    rollback_calls = []
    reconciler.register_node("node-a", tmp_path / "repo-a", "abc123", lambda: rollback_calls.append("called"))

    result = reconciler.tick()

    assert result["status"] == "healthy"
    assert result["nodes"]["node-a"]["memory_bytes"] == 1234
    assert result["nodes"]["node-a"]["open_fds"] == 7
    assert result["nodes"]["node-a"]["git_parity"] is True
    assert rollback_calls == []
    with sqlite3.connect(tmp_path / "health.sqlite3") as connection:
        assert connection.execute("select count(*) from nodes").fetchone()[0] == 1
        assert connection.execute("select count(*) from ticks").fetchone()[0] == 1
        assert connection.execute("select journal_mode from pragma_journal_mode").fetchone()[0] == "wal"
    assert reconciler.status()["nodes"]["node-a"]["failure_streak"] == 0
    reconciler.close()


def test_git_head_divergence_is_recorded_as_failed_boundary(tmp_path):
    clock = Clock()
    reconciler = HealthReconciler(
        tmp_path / "health.sqlite3",
        clock=clock,
        sampler=lambda *_args: {"memory_bytes": 1, "open_fds": 2},
        git_probe=lambda _repository: "different-commit",
    )
    reconciler.register_node("node-a", tmp_path / "repo-a", "expected-commit", lambda: None)

    result = reconciler.tick()

    assert result["status"] == "degraded"
    node = result["nodes"]["node-a"]
    assert node["git_parity"] is False
    assert node["failure_boundary"] == "git_head_parity"
    assert node["failure_streak"] == 1
    assert reconciler.status()["last_failure_boundary"] == "git_head_parity"


def test_worker_is_pruned_only_after_ttl_expires(tmp_path):
    clock = Clock()
    reconciler = HealthReconciler(
        tmp_path / "health.sqlite3", ttl_seconds=10, clock=clock,
        sampler=lambda *_args: {"memory_bytes": 1, "open_fds": 1},
        git_probe=lambda _repository: "commit",
    )
    reconciler.register_node("node-a", tmp_path / "repo-a", "commit", lambda: None)
    clock.advance(10)
    assert reconciler.tick()["pruned"] == []
    clock.advance(0.01)

    result = reconciler.tick()

    assert result["pruned"] == ["node-a"]
    assert reconciler.status()["nodes"] == {}


def test_three_consecutive_failures_trigger_one_rollback(tmp_path):
    clock = Clock()
    rollback_calls = []
    reconciler = HealthReconciler(
        tmp_path / "health.sqlite3", clock=clock,
        sampler=lambda *_args: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
        git_probe=lambda _repository: "commit",
    )
    reconciler.register_node("node-a", tmp_path / "repo-a", "commit", lambda: rollback_calls.append("rollback"))

    first = reconciler.tick()
    second = reconciler.tick()
    third = reconciler.tick()

    assert first["nodes"]["node-a"]["failure_streak"] == 1
    assert second["nodes"]["node-a"]["failure_streak"] == 2
    assert third["nodes"]["node-a"]["failure_streak"] == 3
    assert rollback_calls == ["rollback"]
    assert reconciler.status()["nodes"]["node-a"]["rollback_state"] == "rolled_back"

    fourth = reconciler.tick()
    assert fourth["nodes"]["node-a"]["failure_streak"] == 4
    assert rollback_calls == ["rollback"]


def test_rollback_failure_is_recorded_without_repeating_or_touching_other_node(tmp_path):
    clock = Clock()
    changed = tmp_path / "unrelated.txt"
    changed.write_text("preserve\n")
    rollback_calls = []
    reconciler = HealthReconciler(
        tmp_path / "health.sqlite3", clock=clock,
        sampler=lambda node_id, _repository: (
            (_ for _ in ()).throw(RuntimeError("node failed")) if node_id == "bad" else {"memory_bytes": 1, "open_fds": 1}
        ),
        git_probe=lambda _repository: "commit",
    )
    reconciler.register_node("bad", tmp_path / "repo-bad", "commit", lambda: (rollback_calls.append("bad"), (_ for _ in ()).throw(RuntimeError("rollback unavailable")))[1])
    reconciler.register_node("good", tmp_path / "repo-good", "commit", lambda: rollback_calls.append("good"))

    for _ in range(3):
        reconciler.tick()

    assert rollback_calls == ["bad"]
    assert reconciler.status()["nodes"]["bad"]["rollback_state"] == "rollback_failed"
    assert reconciler.status()["nodes"]["good"]["status"] == "healthy"
    assert changed.read_text() == "preserve\n"
