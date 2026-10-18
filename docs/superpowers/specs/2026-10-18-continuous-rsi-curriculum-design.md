# Continuous RSI Curriculum Design

## Status

Approved direction: a hybrid continuous recursive self-improvement loop for Sophyane.

## Goal

Allow Sophyane to continue improving after one verified ability by selecting, executing, and verifying the next bounded improvement task, while preserving isolation, rollback, resource limits, and an explicit stop control.

## Non-goals

- Unattended arbitrary self-modification of the live checkout.
- Removing human or policy approval gates for promotion.
- Treating an LLM claim as evidence of a completed ability.
- Infinite execution without a configurable budget, pause, or stop mechanism.
- Replacing the existing RSI controller, candidate isolation, verification, promotion, rollback, or journal layers.

## Architecture

The existing RSI supervisor remains the lifecycle owner. A new durable curriculum scheduler supplies the controller with the next task when the observation queue is empty or a prior iteration completes.

The loop is:

```text
observe → prioritize gap → create bounded task → propose change → isolate candidate
       → run fresh verification → promote or rollback → record ability
       → generate next bounded task
```

The deterministic scheduler is authoritative for priority. It consumes recorded weaknesses, failed verifications, regression history, and declared capability gaps. An optional LLM curriculum adapter may propose a task, but the proposal is accepted only after deterministic validation: bounded scope, allowed paths, measurable acceptance criteria, no destructive operation, and resource limits.

## Durable state

The continuous RSI state directory stores:

- task queue and task lifecycle (`queued`, `running`, `verified`, `rejected`, `rolled_back`, `paused`);
- current task and parent ability identifier;
- generated task rationale and source (`weakness`, `regression`, `capability_gap`, `llm_follow_up`);
- iteration counters, timestamps, token/time budgets, and cooldowns;
- ability records with verification evidence and promoted commit/checkpoint;
- failure and rollback history;
- scheduler status and a stop/pause request.

Writes are atomic and append-only where audit history matters. Corrupt or invalid state fails closed and leaves the live checkout unchanged.

## Task contract

Each task must define:

- a stable task ID and parent ability ID;
- one bounded objective;
- explicit editable-path allowlist;
- verification commands and expected evidence;
- maximum lifecycle duration and retry count;
- a resource class (`light`, `normal`, or `paused`);
- provenance and rationale.

The scheduler rejects tasks without measurable verification or with paths outside the RSI authority policy. A completed task is not an ability until fresh verification passes and promotion succeeds.

## Scheduling policy

Priority order:

1. regressions and confirmed weaknesses;
2. failed or incomplete verification obligations;
3. declared capability gaps;
4. deterministic curriculum progression;
5. bounded LLM follow-up proposals.

The LLM proposal adapter receives only a summarized state and the allowed capability catalog. It must return structured JSON, and malformed, over-broad, duplicate, or untestable proposals are rejected. The adapter cannot directly write files or promote candidates.

After a verified ability, the scheduler records the result and immediately enqueues at most one next task. This prevents an LLM from recursively exploding the queue.

## Continuous operation

Continuous mode is opt-in and explicit:

- `start` begins or resumes the scheduler;
- `pause` finishes no new task and preserves state;
- `stop` requests a bounded shutdown and records the reason;
- `status` reports the current task, queue, last result, next task, budgets, and health.

Configuration controls maximum iterations, wall-clock duration, daily/model budget, cooldown between tasks, and whether LLM follow-up generation is enabled. Defaults are conservative and finite; a caller must explicitly select an unbounded-running daemon mode, which still retains stop and safety gates.

## Failure handling

- Provider failure: record the failure, apply existing availability/cooldown logic, and defer the task.
- Candidate verification failure: reject or rollback through the existing RSI transaction boundary.
- Promotion failure: restore the checkpoint and mark the task incomplete.
- Scheduler or LLM failure: keep the current state durable, pause new work, and expose diagnostics.
- Process restart: recover the last durable task state and any unfinished promotion before scheduling new work.

No failure path may claim an ability or advance the curriculum without evidence.

## Interfaces

The implementation will add a focused curriculum/scheduler module and integrate it with `sophyane.rsi.supervisor` and existing controller/runtime services. Existing controller APIs remain compatible. CLI/status surfaces expose the continuous RSI lifecycle without requiring users to inspect JSON files manually.

## Verification strategy

Tests must cover:

- deterministic next-task selection and priority ordering;
- durable queue/state recovery after restart;
- LLM proposal schema rejection and bounded-task validation;
- one-task-at-a-time chaining after a verified ability;
- pause, stop, cooldown, and budget enforcement;
- promotion, rollback, and provider-failure handoff;
- end-to-end two-ability progression using a deterministic fixture;
- live smoke execution proving a task creates evidence, advances state, and produces the next queued task.

