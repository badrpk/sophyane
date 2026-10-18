# RSI Heartbeat and LLM Task Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a durable heartbeat, bounded LLM task source, and restartable watchdog around continuous RSI.

**Architecture:** A small heartbeat store records worker liveness atomically. A proposal source asks the configured LLM for one task and sends it through the existing strict validator. A worker tick coordinates proposal, execution, and heartbeat updates; a watchdog restarts stale workers unless durable pause/stop state forbids it.

**Tech Stack:** Python 3.10+, dataclasses, atomic JSON persistence, existing curriculum scheduler/proposal adapter/supervisor, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-rsi-heartbeat-task-ingestion-design.md`

## Global Constraints

- Heartbeat and watchdog control liveness only; they cannot approve, mutate, verify, or promote code.
- LLM output is one untrusted proposal and must pass `CurriculumProposalAdapter` before queue insertion.
- Existing iteration, wall-time, queue, cooldown, follow-up, pause, and stop limits remain authoritative.
- Power loss and OS termination are not claimed to be impossible; recovery is durable and fail closed.

## Review Focus

- Corrupt heartbeat JSON: fail closed without touching curriculum or checkout; test in Task 1.
- Stale heartbeat with durable stop/pause: never restart; test in Task 3.
- LLM returns malformed or multiple tasks: reject and audit; test in Task 2.
- Proposal provider hangs or raises: heartbeat records the error and worker remains bounded; test in Task 2.
- Worker crashes after marking a task running: restart recovers it as paused with no ability claim; test in Task 3.

### Task 1: Add durable heartbeat state

**Files:**
- Create: `src/sophyane/rsi/heartbeat.py`
- Test: `tests/rsi/test_heartbeat.py`

**Interfaces:**
- Produces `HeartbeatRecord`, `HeartbeatStore(path)`, `HeartbeatStore.load()`, `HeartbeatStore.save(record)`, and `HeartbeatStore.touch(**updates)`.
- `HeartbeatRecord` includes `worker_id`, `pid`, `state`, `started_at`, `last_tick_at`, `current_task_id`, `last_error`, and `restart_count`.

- [ ] Write failing tests for JSON round-trip, atomic touch, corrupt-state failure, and stale-age calculation.
- [ ] Run `./.venv/bin/pytest -q tests/rsi/test_heartbeat.py`; confirm the missing module/interface failure.
- [ ] Implement schema-versioned atomic JSON storage and `is_stale(now, threshold)` without filesystem deletion or checkout access.
- [ ] Re-run the heartbeat tests; expect all pass.
- [ ] Commit `feat: add durable RSI heartbeat state`.

### Task 2: Add bounded LLM curriculum task source

**Files:**
- Create: `src/sophyane/rsi/curriculum_source.py`
- Modify: `src/sophyane/rsi/curriculum_proposals.py` only if context needs bounded source metadata
- Test: `tests/rsi/test_curriculum_source.py`

**Interfaces:**
- Produces `CurriculumTaskSource(generate, proposal_adapter).propose(context) -> ProposalResult`.
- The source invokes `generate(prompt)` exactly once per request, passes the result to `CurriculumProposalAdapter`, and never writes files or enqueues directly.

- [ ] Write failing tests for one accepted proposal, malformed output rejection, provider exception, and exactly-one-generator-call behavior.
- [ ] Run the focused source tests and confirm failure.
- [ ] Implement bounded proposal invocation with truncated context, exception-to-rejection mapping, and no retry loop.
- [ ] Run source tests; expect all pass.
- [ ] Commit `feat: add bounded RSI LLM task source`.

### Task 3: Add heartbeat worker and watchdog lifecycle

**Files:**
- Create: `src/sophyane/rsi/heartbeat_runtime.py`
- Modify: `src/sophyane/rsi/supervisor.py`
- Modify: `src/sophyane/rsi/runtime_services.py`
- Test: `tests/rsi/test_heartbeat_runtime.py`

**Interfaces:**
- Produces `ContinuousRSIWorker(runtime, heartbeat, source=None).run_once() -> dict[str, object]` and `RSIWatchdog(heartbeat, start_worker, scheduler, stale_seconds).check() -> dict[str, object]`.
- Worker refreshes before/after each bounded operation, requests a proposal only when the queue is empty, and respects durable pause/stop.
- Watchdog restarts only for stale, non-paused, non-stopped state and increments durable restart count.

- [ ] Write failing tests for heartbeat refresh, empty-queue proposal enqueue, stale restart, pause/stop suppression, and crash recovery.
- [ ] Run focused runtime tests and confirm failure.
- [ ] Implement worker/watchdog with bounded intervals and durable state transitions; reuse existing supervisor ownership locks.
- [ ] Wire `build_curriculum_runtime` and supervisor startup to construct the worker heartbeat and optional task source from host configuration.
- [ ] Run focused runtime tests; expect all pass.
- [ ] Commit `feat: add restartable RSI heartbeat worker`.

### Task 4: Expose status/configuration and verify end-to-end

**Files:**
- Modify: `src/sophyane/v13_cli.py`
- Modify: `README.md`
- Test: `tests/rsi/test_heartbeat_cli.py`

**Interfaces:**
- Extend curriculum status JSON with heartbeat state, age, and restart count.
- Add bounded environment parsing for heartbeat interval, stale threshold, watchdog enablement, and task source selection.

- [ ] Write failing CLI tests for heartbeat status, safe invalid configuration, and durable stop preventing restart.
- [ ] Run focused CLI tests and confirm failure.
- [ ] Implement status/configuration surfaces without exposing provider secrets or arbitrary commands.
- [ ] Run all RSI tests plus compile and diff checks.
- [ ] Run a local smoke test showing two heartbeat ticks and one validated task proposal.
- [ ] Commit `feat: expose RSI heartbeat controls and status`.
