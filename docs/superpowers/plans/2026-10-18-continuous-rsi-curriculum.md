# Continuous RSI Curriculum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable hybrid curriculum scheduler that continually selects bounded, verifiable RSI tasks and chains one verified ability into the next without unsafe live self-modification.

**Architecture:** Add a focused curriculum package containing typed task/ability records, atomic durable state, deterministic prioritization, and bounded LLM proposal validation. Integrate one scheduler tick into the existing RSI supervisor and expose explicit start/pause/stop/status controls through a small CLI surface. Existing candidate, verification, promotion, rollback, and journal components remain authoritative.

**Tech Stack:** Python 3.10+, dataclasses, JSON/atomic filesystem persistence, existing `sophyane.rsi` controller/supervisor, pytest, existing CLI entry points.

**Spec:** `docs/superpowers/specs/2026-10-18-continuous-rsi-curriculum-design.md`

## Global Constraints

- Continuous mode is opt-in; existing foreground/runtime behavior remains unchanged by default.
- Every task requires bounded scope, an editable-path allowlist, and measurable verification evidence.
- The LLM may propose tasks but cannot write files, promote candidates, or bypass authority checks.
- State corruption fails closed and must not mutate the live checkout.
- At most one follow-up task is enqueued after a verified ability.
- Stop, pause, cooldown, wall-clock, iteration, and resource-budget controls are mandatory.
- Existing RSI controller, candidate isolation, verification, promotion, rollback, and journal APIs remain compatible.

## Review Focus

- Restart during a running task: recovery must not duplicate or silently promote work; test in Task 2.
- Malformed or over-broad LLM proposal: reject it without filesystem mutation; test in Task 3.
- Empty queue after success: enqueue exactly one bounded next task; test in Task 2 and Task 4.
- Budget/cooldown exhaustion: pause or defer without claiming progress; test in Task 2 and Task 4.
- Provider, verification, or promotion failure: preserve evidence and rollback state; test in Task 4.

### Task 1: Define curriculum records and durable state

**Files:**
- Create: `src/sophyane/rsi/curriculum.py`
- Test: `tests/rsi/test_curriculum_state.py`

**Interfaces:**
- Produces `TaskSource`, `TaskStatus`, `ResourceClass`, `CurriculumTask`, `AbilityRecord`, `CurriculumState`, and `CurriculumStore`.
- `CurriculumStore(path: Path)`, `load() -> CurriculumState`, `save(state: CurriculumState) -> None`, and `append_event(event: dict[str, object]) -> None`.
- Consumes only standard-library types; later tasks consume these records without importing controller internals.

- [ ] **Step 1: Write failing tests** for JSON round-trip, atomic save, corrupt-state fail-closed behavior, and recovery of `running` tasks as `paused`.
- [ ] **Step 2: Run** `./.venv/bin/python -m pytest -q tests/rsi/test_curriculum_state.py`; confirm collection or assertion failures identify missing interfaces.
- [ ] **Step 3: Implement** typed records, schema versioning, restrictive path handling, atomic temp-file replacement, and recovery normalization.
- [ ] **Step 4: Re-run** the focused tests and confirm all pass.
- [ ] **Step 5: Commit** `feat: add durable RSI curriculum state`.

### Task 2: Implement deterministic scheduling and lifecycle controls

**Files:**
- Modify: `src/sophyane/rsi/curriculum.py`
- Test: `tests/rsi/test_curriculum_scheduler.py`

**Interfaces:**
- Produces `CurriculumScheduler(store, policy, clock=...)`.
- `enqueue(task: CurriculumTask) -> bool`, `next_task() -> CurriculumTask | None`, `mark_running(task_id)`, `record_verified(task_id, evidence)`, `record_failure(task_id, status, reason)`, `pause(reason)`, `resume()`, `stop(reason)`, `status() -> dict[str, object]`, and `choose_next(candidates) -> CurriculumTask | None`.
- `CurriculumPolicy` carries max iterations, wall-clock budget, cooldown, max queue length, and one-follow-up limit.

- [ ] **Step 1: Write failing tests** for priority ordering (`regression` before `capability_gap` before `llm_follow_up`), deduplication, one-task chaining, pause/stop, cooldown, and iteration/time budget enforcement.
- [ ] **Step 2: Run** the focused scheduler tests and confirm they fail for the missing scheduler behavior.
- [ ] **Step 3: Implement** deterministic ordering, bounded queue transitions, and budget checks using the durable store from Task 1.
- [ ] **Step 4: Re-run** focused tests and verify no task is advanced without a durable state transition.
- [ ] **Step 5: Commit** `feat: add bounded RSI curriculum scheduler`.

### Task 3: Add bounded LLM follow-up proposals

**Files:**
- Create: `src/sophyane/rsi/curriculum_proposals.py`
- Test: `tests/rsi/test_curriculum_proposals.py`

**Interfaces:**
- Produces `ProposalContext`, `ProposalResult`, and `CurriculumProposalAdapter(generate, authority)`, where `generate(prompt: str) -> str` is injected.
- `propose(context: ProposalContext) -> ProposalResult` accepts exactly one structured JSON proposal or a rejection reason.
- Consumes `CurriculumTask`, `AbilityRecord`, capability metadata, and the existing RSI authority/path policy.

- [ ] **Step 1: Write failing tests** for valid proposals, malformed JSON, multiple tasks, missing verification, unsafe paths, duplicate task IDs, destructive wording, and oversized objectives.
- [ ] **Step 2: Run** the focused tests and confirm invalid proposals are not silently accepted.
- [ ] **Step 3: Implement** strict JSON parsing, field bounds, path normalization, authority validation, and deterministic rejection reasons; do not add filesystem or promotion capabilities.
- [ ] **Step 4: Re-run** focused tests and verify only one bounded proposal can be returned.
- [ ] **Step 5: Commit** `feat: validate RSI curriculum proposals`.

### Task 4: Integrate the scheduler with RSI supervision and lifecycle controls

**Files:**
- Modify: `src/sophyane/rsi/supervisor.py`
- Modify: `src/sophyane/rsi/runtime_services.py`
- Create: `src/sophyane/rsi/curriculum_runtime.py`
- Test: `tests/rsi/test_continuous_curriculum_runtime.py`

**Interfaces:**
- Produces `ContinuousCurriculumRuntime(state_dir, controller, scheduler, proposal_adapter=None)` with `tick() -> dict[str, object]`, `start()`, `pause()`, `stop()`, and `status()`.
- Consumes the existing controller’s verified/rejected result shape and routes candidate work through its existing isolation and transaction boundaries.
- Existing `start_supervisor`, `stop_supervisor`, and `runtime_session` remain backward compatible; continuous curriculum is enabled only by explicit configuration.

- [ ] **Step 1: Write failing integration tests** for opt-in gating, two-task progression, promotion evidence, rollback on failure, provider deferral, restart recovery, and stop behavior.
- [ ] **Step 2: Run** the focused integration tests and confirm the runtime does not yet chain tasks.
- [ ] **Step 3: Implement** the runtime adapter, one-tick bounded orchestration, supervisor wake/cooldown handling, and durable status transitions.
- [ ] **Step 4: Re-run** integration tests and inspect persisted events for the complete two-ability sequence.
- [ ] **Step 5: Commit** `feat: run continuous RSI curriculum through supervisor`.

### Task 5: Expose explicit CLI controls and complete verification

**Files:**
- Modify: `src/sophyane/v13_cli.py`
- Create: `tests/rsi/test_curriculum_cli.py`
- Modify: `README.md`

**Interfaces:**
- Adds explicit `start`, `pause`, `stop`, and `status` operations with state-directory and policy options.
- CLI output is machine-readable JSON when requested and includes current task, queue length, last result, next task, budgets, and stop/pause state.

- [ ] **Step 1: Write failing CLI tests** for start/status/pause/stop and invalid policy values.
- [ ] **Step 2: Run** focused CLI tests and confirm the commands are absent or fail.
- [ ] **Step 3: Implement** CLI routing without changing ordinary conversational or coding task behavior.
- [ ] **Step 4: Add** an end-to-end deterministic fixture that completes ability A, enqueues ability B, completes B, and verifies no third task is automatically enqueued.
- [ ] **Step 5: Run** all RSI tests plus the complete project test command; record pass/skip/failure counts.
- [ ] **Step 6: Run** `git diff --check` and inspect persisted live-smoke evidence.
- [ ] **Step 7: Commit** `feat: expose continuous RSI controls and verification`.
