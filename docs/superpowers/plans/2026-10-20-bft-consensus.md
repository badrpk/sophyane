# BFT Consensus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add a fail-closed, SQLite-audited BFT decision engine for five isolated Sophyane workers that tolerates two invalid workers and reaches quorum within 1.5 seconds.

**Architecture:** A small consensus package separates response validation, durable ledger writes, isolation locks, and deadline-bounded orchestration. The engine returns a decision record only; existing authority and promotion code remain the sole mutation gates.

**Tech Stack:** Python 3.10+, standard-library `json`, `ast`, `sqlite3`, `concurrent.futures`, `hashlib`, `time`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-bft-consensus-design.md`

## Global Constraints

- Exactly five configured workers; default quorum is 3.
- Default decision deadline is 1.5 seconds, measured with `time.monotonic()`.
- Invalid JSON, corrupted AST, exceptions, timeouts, and divergent Git heads isolate the worker.
- No consensus code may perform source mutation, commit, or authority escalation.
- Ledger writes must be durable and auditable in SQLite.

## Review Focus

- Duplicate/unknown JSON fields: reject deterministically and record `json_schema`.
- AST payload that parses but violates the artifact contract: reject as `ast_contract`.
- Divergent or malformed Git hashes: reject as `git_head`.
- Slow workers after quorum/deadline: return without waiting indefinitely and record `timeout`.
- SQLite failure or restart: fail closed and preserve existing working-tree state; test ledger reopen and lock persistence.

### Task 1: Validation contract

**Files:**
- Create: `src/sophyane/consensus/validation.py`
- Create: `src/sophyane/consensus/models.py`
- Create: `tests/consensus/test_validation.py`

**Interfaces:**
- `validate_worker_response(raw: object, *, base_commit: str) -> ValidatedVote | InvalidVote`
- `canonical_decision(value: Mapping[str, object]) -> tuple[str, str]`
- `ValidatedVote` and `InvalidVote` are immutable records carrying worker ID, digest, decision, git head, and failure boundary.

- [ ] Write tests for valid canonical responses, malformed/duplicate JSON, AST contract failure, and divergent Git head.
- [ ] Run `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/consensus/test_validation.py`; expect RED because the package does not exist.
- [ ] Implement only the validation models and deterministic checks needed by those tests.
- [ ] Re-run the focused tests and confirm GREEN.
- [ ] Commit with `test/feat: add BFT response validation`.

### Task 2: Durable ledger and isolation locks

**Files:**
- Create: `src/sophyane/consensus/ledger.py`
- Create: `src/sophyane/consensus/isolation.py`
- Create: `tests/consensus/test_ledger.py`

**Interfaces:**
- `ConsensusLedger(path: Path)` with `record_round`, `record_vote`, `lock_worker`, `is_locked`, and `events` methods.
- `IsolationRegistry(ledger: ConsensusLedger)` with `lock(worker_id, reason, boundary)` and `locked_workers()`.

- [ ] Write tests for schema creation, round/vote/event persistence, lock persistence after reopening, and transactional failure behavior.
- [ ] Run the focused ledger tests and confirm RED.
- [ ] Implement WAL setup where available, parameterized SQL, and short transactions; never delete or rewrite unrelated files.
- [ ] Re-run the focused tests and confirm GREEN.
- [ ] Commit with `feat: add auditable consensus ledger`.

### Task 3: Deadline-bounded BFT engine

**Files:**
- Create: `src/sophyane/consensus/engine.py`
- Create: `src/sophyane/consensus/__init__.py`
- Create: `tests/consensus/test_engine.py`

**Interfaces:**
- `BFTConsensusEngine(ledger_path, workers, *, quorum=3, deadline_seconds=1.5)`.
- `decide(request, *, base_commit, worker_calls) -> ConsensusDecision`.

- [ ] Write tests for three honest votes plus two adversaries, no quorum, persistent lock exclusion, early quorum return, and slow-worker deadline handling.
- [ ] Run the focused engine tests and confirm RED.
- [ ] Implement bounded `ThreadPoolExecutor(max_workers=5)` collection, canonical digest counting, lock filtering, cancellation at deadline, and fail-closed statuses.
- [ ] Re-run all `tests/consensus` and confirm GREEN, including elapsed-time assertions with a reduced test deadline where needed.
- [ ] Commit with `feat: add BFT consensus engine`.

### Task 4: Integration and verification

**Files:**
- Modify: `src/sophyane/consensus/__init__.py` only if exports need adjustment.
- Create: `tests/consensus/test_integration.py`

- [ ] Add an end-to-end test using five worker callables, two adversarial responses, a temporary ledger, and an untouched sentinel file.
- [ ] Verify three valid votes finalize, two workers are locked, and no source or sentinel mutation occurs.
- [ ] Run `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/consensus`.
- [ ] Run the complete project suite and report any pre-existing failures by name.
- [ ] Review the diff for unrelated-file changes and commit only consensus files and tests.

## Self-review

Every spec requirement maps to Tasks 1–4: validation and failure boundaries in
Task 1, durable state and locks in Task 2, quorum/deadline behavior in Task 3,
and adversarial end-to-end/no-mutation behavior in Task 4. The API names and
types are consistent across tasks, and the five review-focus failure classes
each have an assigned test.
