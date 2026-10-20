from pathlib import Path
from types import SimpleNamespace

from sophyane.rsi.curriculum import CurriculumTask, CurriculumStore, ResourceClass, TaskSource
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


def test_worker_records_proposal_provenance_after_enqueue(tmp_path: Path):
    store = heartbeat(tmp_path)
    runtime = FakeRuntime()
    runtime.scheduler.store = CurriculumStore(tmp_path / "curriculum.json")
    worker = ContinuousRSIWorker(runtime, store, FakeSource(), context_factory=lambda: "context")

    worker.run_once()

    events = (tmp_path / "curriculum.events.jsonl").read_text(encoding="utf-8")
    assert '"event": "proposal_provenance"' in events
    assert '"task_id": "task-2"' in events


def test_worker_reports_rejected_proposal_in_heartbeat(tmp_path: Path):
    store = heartbeat(tmp_path)
    runtime = FakeRuntime()
    source = SimpleNamespace(propose=lambda _context: ProposalResult(False, reason="no frozen experiment plan"))
    worker = ContinuousRSIWorker(runtime, store, source, context_factory=lambda: "context")

    worker.run_once()

    assert "no frozen experiment plan" in store.load().last_error


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
    assert runtime.task_source.proposal_adapter.generator == "codex_cli"


def test_runtime_services_describes_demo_score_contract_to_proposal_llm(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SOPHYANE_CONTINUOUS_RSI", raising=False)
    controller = SimpleNamespace(
        ledger=WeaknessLedger(),
        plans={"demo_score": SimpleNamespace(allowed_paths=("src/sophyane/rsi_demo_target.py",))},
    )

    runtime = build_curriculum_runtime(tmp_path, controller)

    summary = runtime.context_factory().capability_summary
    assert "score() -> int" in summary
    assert "score() == 3" in summary
    assert "return 3" in summary


def test_runtime_services_falls_back_to_bounded_task_when_local_llm_times_out(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("SOPHYANE_CONTINUOUS_RSI", raising=False)
    monkeypatch.setenv("SOPHYANE_RSI_PROPOSAL_PROVIDER", "local_gguf")
    controller = SimpleNamespace(
        ledger=WeaknessLedger(),
        plans={
            "demo_score": SimpleNamespace(
                allowed_paths=("src/sophyane/rsi_demo_target.py",),
            ),
        },
    )

    def timeout(*_args, **_kwargs):
        raise TimeoutError("local proposal provider timed out")

    monkeypatch.setattr("sophyane.rsi.runtime_services.local_request", timeout)
    runtime = build_curriculum_runtime(tmp_path, controller)
    proposal = runtime.task_source.propose(runtime.context_factory())

    assert proposal.accepted is True
    assert proposal.task is not None
    assert proposal.task.editable_paths == ("src/sophyane/rsi_demo_target.py",)
    assert proposal.task.component == "filesystem"


def test_runtime_services_falls_back_when_local_llm_returns_malformed_json(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("SOPHYANE_CONTINUOUS_RSI", raising=False)
    monkeypatch.setenv("SOPHYANE_RSI_PROPOSAL_PROVIDER", "local_gguf")
    controller = SimpleNamespace(
        ledger=WeaknessLedger(),
        plans={"demo_score": SimpleNamespace(allowed_paths=("src/sophyane/rsi_demo_target.py",))},
    )
    monkeypatch.setattr(
        "sophyane.rsi.runtime_services.local_request",
        lambda *_args, **_kwargs: "not-json",
    )

    runtime = build_curriculum_runtime(tmp_path, controller)
    proposal = runtime.task_source.propose(runtime.context_factory())

    assert proposal.accepted is True
    assert proposal.task is not None


def test_runtime_services_accepts_proposal_only_adapter(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SOPHYANE_CONTINUOUS_RSI", raising=False)
    controller = SimpleNamespace(ledger=WeaknessLedger(), plans={})
    adapter = SimpleNamespace(propose=lambda _context: ProposalResult(False, reason="deferred"))

    runtime = build_curriculum_runtime(tmp_path, controller, proposal_adapter=adapter)

    assert runtime.task_source is None


def test_worker_does_not_overwrite_corrupt_heartbeat(tmp_path: Path):
    path = tmp_path / "heartbeat.json"
    path.write_text("corrupt", encoding="utf-8")
    store = HeartbeatStore(path)
    runtime = FakeRuntime(queue_length=1)

    result = ContinuousRSIWorker(runtime, store).run_once()

    assert result["status"] == "paused"
    assert path.read_text(encoding="utf-8") == "corrupt"


def test_watchdog_records_restart_failure(tmp_path: Path):
    store = heartbeat(tmp_path, last_tick_at=10.0)
    scheduler = SimpleNamespace(status=lambda: {"paused": False, "stopped": False})

    def fail_start():
        raise RuntimeError("worker unavailable")

    result = RSIWatchdog(store, fail_start, scheduler, stale_seconds=5.0, clock=lambda: 20.0).check()

    assert result["status"] == "error"
    assert "worker unavailable" in result["reason"]
    assert "worker unavailable" in store.load().last_error
