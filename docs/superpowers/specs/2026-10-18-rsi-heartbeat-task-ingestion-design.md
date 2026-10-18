# RSI Heartbeat and LLM Task Ingestion

## Goal

Keep Sophyane's bounded RSI curriculum worker observable and restartable while
allowing an LLM to propose the next bounded task when deterministic state says
new work is needed.

## Safety boundary

The heartbeat and watchdog control liveness only. They cannot approve code,
change experiment policy, bypass candidate isolation, or promote a candidate.
LLM output remains an untrusted task proposal and passes the existing strict
curriculum validator before entering the durable queue.

## Components

1. `HeartbeatStore` atomically writes a small JSON record containing worker
   identity, process information, timestamps, lifecycle state, current task,
   and last error.
2. `CurriculumTaskSource` asks a configured proposal function for one task at
   a time, using the existing `ProposalContext` and `CurriculumProposalAdapter`.
   It never receives filesystem mutation or promotion capabilities.
3. `ContinuousRSIWorker` runs one bounded curriculum tick, refreshes the
   heartbeat before and after work, requests a proposal when the queue is
   empty, and exits on durable pause/stop or budget exhaustion.
4. `RSIWatchdog` checks heartbeat age and worker liveness. It may restart a
   stale worker only when the durable state is not stopped or paused. Restart
   attempts are bounded and audited.

## Lifecycle

```text
start → heartbeat → request one proposal → validate → enqueue
      → execute through RSI gates → record verified ability
      → heartbeat → request next bounded task
pause/stop ───────────────────────────────────────────────→ no restart
stale heartbeat → bounded restart → recover running task as paused
```

The process cannot be guaranteed to survive power loss or OS termination. The
watchdog provides restart-on-stale behavior when its host remains available;
all state transitions are durable and fail closed.

## Configuration

- `SOPHYANE_RSI_HEARTBEAT_SECONDS`: heartbeat interval, bounded to safe limits.
- `SOPHYANE_RSI_STALE_SECONDS`: stale threshold, greater than the interval.
- `SOPHYANE_RSI_WATCHDOG=1`: enable watchdog supervision.
- `SOPHYANE_RSI_TASK_SOURCE`: configured host source/provider name; no arbitrary
  network or shell capability is inferred from this value.

Existing iteration, wall-time, queue, cooldown, follow-up, pause, and stop
limits remain authoritative.

## Failure handling

- Invalid or over-broad LLM output is rejected and audited.
- Provider errors update heartbeat diagnostics and defer new proposals.
- Worker crashes recover running tasks as paused; no ability is claimed.
- Stale-worker restart is suppressed after durable stop or pause.
- Corrupt heartbeat/state fails closed without touching the live checkout.

## Verification

Tests will cover atomic heartbeat recovery, heartbeat refresh, proposal
polling, malformed proposal rejection, stale restart, crash recovery, and
durable pause/stop behavior.
