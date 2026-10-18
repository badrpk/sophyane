from pathlib import Path
from types import SimpleNamespace

from sophyane.rsi.curriculum import CurriculumTask, ResourceClass, TaskSource
from sophyane.rsi.curriculum_proposals import ProposalResult
from sophyane.rsi.heartbeat import HeartbeatRecord, HeartbeatStore
from sophyane.rsi.heartbeat_runtime import ContinuousRSIWorker, RSIWatchdog
from sophyane.rsi.runtime_services import build_curriculum_runtime
from sophyane.rsi.weakness_ledger import WeaknessLedger


def task():
    return CurriculumTask("task-2", "a1", "next ability", ("src/x.py",), ("pytest",), TaskSource.LLM_FOLLOW_UP, ResourceClass.LIGHT)


class FakeRuntime:
    def __init__(self, state="running", queue_length=0):
        self.state = state
        self.queue_length = queue_length
        self.enqueued = []
        self.ticks = 0
        self.scheduler = SimpleNamespace(
            status=lambda: {"stopped": state == "stopped", "paused": state == "paused"},
            enqueue=self.enqueue,
        )

    def status(self):
        return {"paused": self.state == "paused", "stopped": self.state == "stopped", "queue_length": self.queue_length}

    def enqueue(self, value):
        self.enqueued.append(value)
        self.queue_length += 1
        return True

    def tick(self):
        self.ticks += 1
        return {"status": "idle"}


class FakeSource:
    def __init__(self):
        self.calls = 0

    def propose(self, _context):
        self.calls += 1
        return ProposalResult(True, task(), "accepted")


def heartbeat(tmp_path: Path, **updates):
    store = HeartbeatStore(tmp_path / "heartbeat.json")
    values = {"state": "running", "last_tick_at": 10.0, **updates}
    store.save(HeartbeatRecord("worker", 1, values["state"], 10.0, values["last_tick_at"]))
    return store


def test_worker_refreshes_heartbeat_and_ticks(tmp_path: Path):
    store = heartbeat(tmp_path)
    runtime = FakeRuntime(queue_length=1)
    worker = ContinuousRSIWorker(runtime, store, clock=lambda: 20.0)

    result = worker.run_once()

    assert result["status"] == "idle"
    assert runtime.ticks == 1
    assert store.load().last_tick_at == 20.0


def test_worker_requests_one_task_when_queue_is_empty(tmp_path: Path):
    store = heartbeat(tmp_path)
    runtime = FakeRuntime()
    source = FakeSource()
    worker = ContinuousRSIWorker(runtime, store, source, context_factory=lambda: "context")

    worker.run_once()

    assert source.calls == 1
    assert [item.task_id for item in runtime.enqueued] == ["task-2"]


def test_watchdog_restarts_stale_worker_but_not_paused_or_stopped(tmp_path: Path):
    store = heartbeat(tmp_path, last_tick_at=10.0)
    starts = []
    scheduler = SimpleNamespace(status=lambda: {"paused": False, "stopped": False})
    watchdog = RSIWatchdog(store, lambda: starts.append(True), scheduler, stale_seconds=5.0, clock=lambda: 20.0)

    assert watchdog.check()["status"] == "restarted"
    assert len(starts) == 1
    assert store.load().restart_count == 1

    for state in ("paused", "stopped"):
        store.touch(state=state)
        scheduler.status = lambda state=state: {"paused": state == "paused", "stopped": state == "stopped"}
        assert watchdog.check()["status"] == "suppressed"
        assert len(starts) == 1


def test_runtime_services_wires_heartbeat_and_llm_source(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SOPHYANE_CONTINUOUS_RSI", raising=False)
    controller = SimpleNamespace(ledger=WeaknessLedger(), plans={})

    runtime = build_curriculum_runtime(tmp_path, controller)

    assert runtime.enabled is True
    assert runtime.heartbeat.path == tmp_path / "heartbeat.json"
    assert runtime.task_source is not None
