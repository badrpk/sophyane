# True RSI Source Promotion Design

## Goal

Make continuous RSI produce genuine, measurable self-improvement by allowing only fully verified source patches to become the next live Sophyane baseline, with automatic health-check rollback.

## Current gap

The native evolution engine can create a candidate commit in an isolated worktree, but the continuous curriculum currently treats temporary task reinforcement as an ability and never activates a source commit. A successful task therefore does not improve the running system.

## Design

The native evolution engine remains the sole source-change authority. A candidate must pass its existing targeted, full-regression, held-out, security, and Red Queen gates. After those gates, a promotion manager records the previous live commit, fast-forwards a dedicated RSI live branch to the candidate commit, runs a bounded health check, and either keeps the new commit active or resets the live branch to the checkpoint.

The user’s working branch is never modified. The live branch is isolated under the RSI state directory and is represented by a dedicated worktree. The daemon records the active commit, candidate commit, health-check output, and rollback reason in a durable promotion ledger. Stop, pause, heartbeat, and watchdog behavior remain authoritative.

Curriculum tasks that only reinforce an existing capability remain valid evidence, but they do not count as source promotion. A curriculum ability is marked as a true improvement only when its native record contains a committed source patch and an accepted live promotion. If the LLM cannot propose a safe patch, the system records the failure and requests a later task; it does not invent source changes.

## Promotion contract

`PromotionManager.promote(candidate_commit, expected_base)` returns a durable result with `promoted`, `active_commit`, `checkpoint_commit`, and evidence. It refuses promotion when the live branch has diverged from the expected base, the candidate is not an ancestor of the candidate branch, or the health check fails. `rollback()` is idempotent and only targets commits recorded in the ledger.

The health check runs the configured test command in the live worktree and verifies that the daemon can import Sophyane. A failed check resets the live branch to the checkpoint and records the failure.

## Safety boundaries

- No reset, merge, or checkout targets the user’s current working tree.
- Candidate patches remain path- and line-bounded by the existing engine.
- Promotion is allowed only after the existing trusted gates return promotable.
- The live branch has a configurable iteration and wall-clock budget.
- Every promotion and rollback is append-only logged.
- Termux stop and pause prevent new promotions; an in-flight promotion finishes atomically or rolls back.

## Verification

- Unit tests cover clean promotion, base divergence, failed health check, rollback, and idempotent rollback.
- Adapter tests require source promotion evidence for a true RSI ability.
- An end-to-end test uses a temporary git repository and a deterministic candidate patch, then verifies the live branch changes and rolls back on a failing health check.
- The Termux daemon is started against the isolated live worktree and status reports the active commit and last promotion result.
