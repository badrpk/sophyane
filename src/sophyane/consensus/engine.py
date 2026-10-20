"""Deadline-bounded BFT quorum coordination."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from .isolation import IsolationRegistry
from .ledger import ConsensusLedger
from .models import ConsensusDecision, InvalidVote, ValidatedVote
from .validation import validate_worker_response


class BFTConsensusEngine:
    def __init__(
        self,
        ledger_path,
        workers: Sequence[str],
        *,
        quorum: int = 3,
        deadline_seconds: float = 1.5,
    ) -> None:
        self.workers = tuple(workers)
        if len(self.workers) != 5 or len(set(self.workers)) != 5:
            raise ValueError("BFT consensus requires exactly five unique workers")
        if quorum != 3:
            raise ValueError("five-worker BFT consensus requires quorum 3")
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        self.deadline_seconds = float(deadline_seconds)
        self.ledger = ConsensusLedger(ledger_path)
        self.isolation = IsolationRegistry(self.ledger)

    def decide(
        self,
        request: Mapping[str, object],
        *,
        base_commit: str,
        worker_calls: Mapping[str, Callable[[Mapping[str, object]], object]],
    ) -> ConsensusDecision:
        round_id = uuid.uuid4().hex
        started = time.monotonic()
        self.ledger.record_round(round_id, workers=list(self.workers), quorum=3, base_commit=base_commit)
        isolated = set(self.isolation.locked_workers())
        active = [worker for worker in self.workers if worker not in isolated and worker in worker_calls]
        votes: list[ValidatedVote | InvalidVote] = []
        futures = {}
        executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="sophyane-bft")
        try:
            futures = {executor.submit(worker_calls[worker], request): worker for worker in active}
            pending = set(futures)
            counts: Counter[str] = Counter()
            decisions: dict[str, dict[str, Any]] = {}
            quorum_digest: str | None = None
            while pending:
                remaining = self.deadline_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                if not done:
                    break
                for future in done:
                    worker = futures[future]
                    try:
                        raw = future.result()
                        vote = validate_worker_response(raw, base_commit=base_commit)
                        if isinstance(vote, ValidatedVote) and vote.worker_id != worker:
                            vote = InvalidVote(worker, None, None, vote.git_head, "json_schema", "worker identity mismatch")
                    except Exception as exc:  # worker failure is an invalid vote, never a process failure
                        vote = InvalidVote(worker, None, None, None, "worker_exception", str(exc))
                    votes.append(vote)
                    valid = isinstance(vote, ValidatedVote)
                    self.ledger.record_vote(round_id, vote, status="valid" if valid else "invalid")
                    if not valid:
                        self.isolation.lock(worker, vote.error, vote.failure_boundary)
                        isolated.add(worker)
                        continue
                    counts[vote.digest] += 1
                    decisions[vote.digest] = vote.decision
                    if counts[vote.digest] >= 3:
                        quorum_digest = vote.digest
                if quorum_digest is not None:
                    # Give already-running fast workers a tiny non-blocking
                    # drain window so adversarial responses are still audited;
                    # slow workers never extend the decision deadline.
                    extra_done, pending = wait(
                        pending,
                        timeout=min(0.10, max(0.0, self.deadline_seconds - (time.monotonic() - started))),
                        return_when=FIRST_COMPLETED,
                    )
                    for future in extra_done:
                        worker = futures[future]
                        try:
                            raw = future.result()
                            extra_vote = validate_worker_response(raw, base_commit=base_commit)
                            if isinstance(extra_vote, ValidatedVote) and extra_vote.worker_id != worker:
                                extra_vote = InvalidVote(worker, None, None, extra_vote.git_head, "json_schema", "worker identity mismatch")
                        except Exception as exc:
                            extra_vote = InvalidVote(worker, None, None, None, "worker_exception", str(exc))
                        votes.append(extra_vote)
                        valid = isinstance(extra_vote, ValidatedVote)
                        self.ledger.record_vote(round_id, extra_vote, status="valid" if valid else "invalid")
                        if not valid:
                            self.isolation.lock(worker, extra_vote.error, extra_vote.failure_boundary)
                            isolated.add(worker)
                    break
            if quorum_digest is not None:
                self.ledger.record_event(round_id, "quorum_reached", {"count": counts[quorum_digest], "digest": quorum_digest})
                return self._result(round_id, "finalized", decisions[quorum_digest], counts[quorum_digest], started, votes, isolated, executor)
            self.ledger.record_event(round_id, "no_quorum", {"max_count": max(counts.values(), default=0)})
            return self._result(round_id, "no_quorum", None, max(counts.values(), default=0), started, votes, isolated, executor)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _result(round_id, status, decision, quorum, started, votes, isolated, executor) -> ConsensusDecision:
        executor.shutdown(wait=False, cancel_futures=True)
        return ConsensusDecision(
            round_id=round_id,
            status=status,
            decision=decision,
            quorum=quorum,
            elapsed_ms=(time.monotonic() - started) * 1000,
            votes=tuple(votes),
            isolated_workers=tuple(sorted(isolated)),
        )

