import json
import pytest
from sophyane.evolution.continuous_supervisor import run_bounded_continuous_rsi

class FakeEngine:
    calls = 0
    def __init__(self, cfg): self.cfg = cfg
    def run(self): FakeEngine.calls += 1; return [{"status": "reinforced"}]

def test_default_is_finite_and_checkpointed(tmp_path):
    FakeEngine.calls = 0
    state = run_bounded_continuous_rsi(tmp_path, state_dir=tmp_path / "state", engine_factory=FakeEngine)
    assert FakeEngine.calls == 1 and state["completed_cycles"] == 1
    saved = json.loads((tmp_path / "state" / "run.json").read_text())
    assert saved["last_cycle_status"] == "completed" and saved["cycle_index"] == 2

def test_max_cycles_and_resume(tmp_path):
    class Flaky:
        calls = 0
        def __init__(self, cfg): pass
        def run(self):
            Flaky.calls += 1
            if Flaky.calls == 1: raise RuntimeError("interrupted")
            return []
    sleeps=[]
    state = run_bounded_continuous_rsi(tmp_path, max_cycles=2, max_failures=0, state_dir=tmp_path / "s", engine_factory=Flaky, sleep_fn=sleeps.append)
    assert state["completed_cycles"] == 0
    state = run_bounded_continuous_rsi(tmp_path, max_cycles=2, resume=True, state_dir=tmp_path / "s", engine_factory=Flaky)
    assert state["completed_cycles"] == 2

def test_invalid_bound_fails_safe(tmp_path):
    with pytest.raises(ValueError): run_bounded_continuous_rsi(tmp_path, max_cycles=0, state_dir=tmp_path / "s", engine_factory=FakeEngine)

def test_failure_backoff_and_budget(tmp_path):
    class Failing:
        def __init__(self, cfg): pass
        def run(self): raise RuntimeError("boom")
    sleeps=[]
    state=run_bounded_continuous_rsi(tmp_path, max_cycles=2, max_failures=2, backoff_seconds=1, maximum_backoff_seconds=2, state_dir=tmp_path / "s", engine_factory=Failing, sleep_fn=sleeps.append)
    assert state["completed_cycles"] == 0 and state["consecutive_failures"] == 3 and sleeps == [1,2]

def test_stop_condition(tmp_path):
    state=run_bounded_continuous_rsi(tmp_path, stop=lambda: True, state_dir=tmp_path / "s", engine_factory=FakeEngine)
    assert state["last_cycle_status"] == "stopped" and state["completed_cycles"] == 0

def test_corrupt_checkpoint_recovers(tmp_path):
    d=tmp_path/"s"; d.mkdir(); (d/"run.json").write_text("not json")
    state=run_bounded_continuous_rsi(tmp_path, state_dir=d, engine_factory=FakeEngine)
    assert state["completed_cycles"] == 1

def test_engine_receives_analysis_only_authority(tmp_path):
    seen=[]
    class Inspect:
        def __init__(self,cfg): seen.append(cfg)
        def run(self): return []
    run_bounded_continuous_rsi(tmp_path, state_dir=tmp_path/"s", engine_factory=Inspect)
    cfg=seen[0]; assert cfg.allow_candidate_patches is False and cfg.allow_promotion is False and cfg.allow_cloud_analysis is False

def test_lock_blocks_duplicate_supervisor(tmp_path):
    import fcntl
    d=tmp_path/"s"; d.mkdir(); h=(d/"run.lock").open("a+"); fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RuntimeError): run_bounded_continuous_rsi(tmp_path, state_dir=d, engine_factory=FakeEngine)
    finally: fcntl.flock(h.fileno(), fcntl.LOCK_UN); h.close()


def test_interrupted_cycle_remains_in_progress(tmp_path):
    class Interrupted:
        def __init__(self, cfg): pass
        def run(self): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_bounded_continuous_rsi(tmp_path, state_dir=tmp_path / "s", engine_factory=Interrupted)
    saved = json.loads((tmp_path / "s" / "run.json").read_text())
    assert saved["last_cycle_status"] == "in_progress" and saved["completed_cycles"] == 0
