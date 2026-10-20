import json
import time

from sophyane.consensus.engine import BFTConsensusEngine


BASE_COMMIT = "a" * 40
REQUEST = {"task": "review candidate"}


def response(worker_id: str, *, decision=None, ast_source="def score():\n    return 3\n", git_head=BASE_COMMIT):
    return json.dumps(
        {
            "worker_id": worker_id,
            "decision": decision or {"action": "keep", "score": 3},
            "ast": ast_source,
            "git_head": git_head,
        }
    )


def test_three_matching_workers_finalize_and_two_adversaries_are_locked(tmp_path):
    workers = ["honest-1", "honest-2", "honest-3", "bad-json", "bad-git"]
    calls = {
        "honest-1": lambda _: response("honest-1"),
        "honest-2": lambda _: response("honest-2"),
        "honest-3": lambda _: response("honest-3"),
        "bad-json": lambda _: "{not-json",
        "bad-git": lambda _: response("bad-git", git_head="b" * 40),
    }
    engine = BFTConsensusEngine(tmp_path / "consensus_ledger.sqlite3", workers)

    result = engine.decide(REQUEST, base_commit=BASE_COMMIT, worker_calls=calls)

    assert result.status == "finalized"
    assert result.decision == {"action": "keep", "score": 3}
    assert result.quorum == 3
    assert set(result.isolated_workers) == {"bad-json", "bad-git"}
    assert result.elapsed_ms < 1500


def test_disagreement_without_quorum_fails_closed(tmp_path):
    workers = [f"worker-{index}" for index in range(5)]
    calls = {
        worker: (lambda worker_id: lambda _: response(worker_id, decision={"score": int(worker_id[-1])}))(worker)
        for worker in workers
    }
    engine = BFTConsensusEngine(tmp_path / "consensus_ledger.sqlite3", workers)

    result = engine.decide(REQUEST, base_commit=BASE_COMMIT, worker_calls=calls)

    assert result.status == "no_quorum"
    assert result.decision is None
    assert result.quorum == 1


def test_reaching_quorum_does_not_wait_for_slow_worker(tmp_path):
    workers = ["honest-1", "honest-2", "honest-3", "slow-1", "slow-2"]

    def slow(_):
        time.sleep(1.0)
        return response("slow-1")

    calls = {
        "honest-1": lambda _: response("honest-1"),
        "honest-2": lambda _: response("honest-2"),
        "honest-3": lambda _: response("honest-3"),
        "slow-1": slow,
        "slow-2": slow,
    }
    engine = BFTConsensusEngine(tmp_path / "consensus_ledger.sqlite3", workers, deadline_seconds=0.4)

    started = time.monotonic()
    result = engine.decide(REQUEST, base_commit=BASE_COMMIT, worker_calls=calls)
    elapsed = time.monotonic() - started

    assert result.status == "finalized"
    assert elapsed < 0.4


def test_persisted_lock_excludes_worker_from_later_round(tmp_path):
    path = tmp_path / "consensus_ledger.sqlite3"
    workers = ["worker-1", "worker-2", "worker-3", "worker-4", "worker-5"]
    first_calls = {worker: (lambda _: "{bad") for worker in workers}
    engine = BFTConsensusEngine(path, workers)
    engine.decide(REQUEST, base_commit=BASE_COMMIT, worker_calls=first_calls)
    called = False

    def should_not_run(_):
        nonlocal called
        called = True
        return response("worker-1")

    second_calls = {worker: (should_not_run if worker == "worker-1" else lambda _: response(worker)) for worker in workers}
    result = engine.decide(REQUEST, base_commit=BASE_COMMIT, worker_calls=second_calls)

    assert not called
    assert "worker-1" in result.isolated_workers
