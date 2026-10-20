"""Persistent worker isolation state."""

from __future__ import annotations

from .ledger import ConsensusLedger


class IsolationRegistry:
    def __init__(self, ledger: ConsensusLedger) -> None:
        self.ledger = ledger

    def lock(self, worker_id: str, reason: str, failure_boundary: str) -> None:
        self.ledger.lock_worker(worker_id, reason, failure_boundary)

    def is_locked(self, worker_id: str) -> bool:
        return self.ledger.is_locked(worker_id)

    def locked_workers(self) -> list[str]:
        return self.ledger.locked_workers()

