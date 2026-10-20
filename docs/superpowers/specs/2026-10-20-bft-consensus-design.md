# BFT Consensus for Sophyane Worker Decisions

## Goal

Coordinate five isolated worker subagents, tolerate two Byzantine responses, and
finalize a validated decision or fail closed within 1.5 seconds.

## Scope and invariants

- The engine is a decision coordinator; it does not edit files, create commits,
  or grant mutation authority.
- Each round has exactly five configured worker identities and a quorum of three
  matching valid votes (`2f + 1`, with `f = 2`).
- A vote is valid only when its JSON payload is strict and canonical, its AST
  artifact parses and satisfies the expected artifact contract, and its Git
  commit hash equals the round base commit.
- Invalid JSON, malformed/corrupt AST, exceptions, timeouts, and divergent Git
  hashes are recorded with an exact failure boundary and isolate the worker for
  subsequent rounds.
- The monotonic wall-clock deadline is 1.5 seconds by default. Reaching quorum
  returns immediately; failure to reach quorum returns `no_quorum` and never
  returns a decision for mutation.
- SQLite writes are transactional and durable in `consensus_ledger.sqlite3`.
- Ledger state is auditable: rounds, votes, isolation locks, and events retain
  worker identity, status, digest, failure boundary, and timestamps.

## Interfaces

`src/sophyane/consensus/engine.py` exposes:

```python
class BFTConsensusEngine:
    def __init__(self, ledger_path: Path, workers: Sequence[str], *,
                 quorum: int = 3, deadline_seconds: float = 1.5): ...
    def decide(self, request: Mapping[str, object], *,
               base_commit: str,
               worker_calls: Mapping[str, Callable[[Mapping[str, object]], object]])
               -> ConsensusDecision: ...
```

`ConsensusDecision` contains `round_id`, `status` (`finalized` or
`no_quorum`), the canonical decision when finalized, quorum count, elapsed
milliseconds, vote records, and isolated worker IDs.

Worker responses accept a JSON string/bytes or mapping with the required
decision, AST artifact, and `git_head` fields. Validation is deterministic and
does not execute submitted code.

## Persistence

The ledger creates `rounds`, `votes`, `worker_locks`, and `events` tables. A
worker lock is keyed by worker ID and remains active across engine restarts.
SQLite uses short transactions and WAL mode where supported; the engine fails
closed if the ledger cannot be written.

## Adversarial simulation

Tests provide two adversarial workers: one emits malformed JSON/corrupted AST,
and another emits a valid-looking response with a divergent Git hash. Three
honest workers emit the same canonical decision. The expected outcome is a
finalized decision with exactly three valid votes and two persisted isolation
locks.

## Non-goals

- No claim of cryptographic Byzantine identity or network security.
- No automatic source mutation or commit promotion.
- No unbounded retries after the deadline.
