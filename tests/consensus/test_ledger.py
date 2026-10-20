import sqlite3

import pytest

from sophyane.consensus.isolation import IsolationRegistry
from sophyane.consensus.ledger import ConsensusLedger
from sophyane.consensus.models import InvalidVote, ValidatedVote


BASE_COMMIT = "a" * 40


def test_ledger_persists_round_votes_and_events(tmp_path):
    path = tmp_path / "consensus_ledger.sqlite3"
    ledger = ConsensusLedger(path)
    vote = ValidatedVote("worker-1", {"action": "keep"}, "d" * 64, BASE_COMMIT)

    ledger.record_round("round-1", workers=["worker-1", "worker-2"], quorum=2, base_commit=BASE_COMMIT)
    ledger.record_vote("round-1", vote, status="valid")
    ledger.record_event("round-1", "quorum_reached", {"count": 2})

    reopened = ConsensusLedger(path)
    assert reopened.rounds() == [{"round_id": "round-1", "quorum": 2, "base_commit": BASE_COMMIT}]
    assert reopened.votes("round-1")[0]["worker_id"] == "worker-1"
    assert reopened.events("round-1")[0]["event_type"] == "quorum_reached"


def test_isolation_lock_survives_engine_restart(tmp_path):
    path = tmp_path / "consensus_ledger.sqlite3"
    registry = IsolationRegistry(ConsensusLedger(path))

    registry.lock("worker-evil", "invalid response", "ast_contract")

    reopened = IsolationRegistry(ConsensusLedger(path))
    assert reopened.is_locked("worker-evil")
    assert reopened.locked_workers() == ["worker-evil"]


def test_invalid_vote_records_exact_boundary(tmp_path):
    ledger = ConsensusLedger(tmp_path / "consensus_ledger.sqlite3")
    vote = InvalidVote("worker-evil", None, None, "b" * 40, "git_head", "diverged")

    ledger.record_round("round-1", workers=["worker-evil"], quorum=1, base_commit=BASE_COMMIT)
    ledger.record_vote("round-1", vote, status="invalid")

    assert ledger.votes("round-1")[0]["failure_boundary"] == "git_head"
    assert ledger.votes("round-1")[0]["status"] == "invalid"


def test_ledger_rejects_unusable_database_path(tmp_path):
    with pytest.raises((sqlite3.Error, OSError)):
        ConsensusLedger(tmp_path / "missing" / "ledger.sqlite3")
