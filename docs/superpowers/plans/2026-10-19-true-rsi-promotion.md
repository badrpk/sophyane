# True RSI Source Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote only fully verified native source candidates into an isolated live RSI branch and automatically roll back failed live health checks.

**Architecture:** Add a small `PromotionManager` around git worktree/branch operations. Wire the native task adapter to call it only after the EvolutionEngine gate reports a committed candidate, and persist promotion evidence in the curriculum state. The user checkout remains untouched.

**Tech Stack:** Python 3.13, dataclasses, subprocess git, pytest, existing EvolutionEngine and Termux RSI daemon.

**Spec:** `docs/superpowers/specs/2026-10-19-true-rsi-promotion-design.md`

## Global Constraints

- User working tree is never modified by promotion.
- Existing native targeted/regression/held-out/security/Red Queen gates remain authoritative.
- Promotion refuses live-branch divergence and failed health checks.
- Every source promotion and rollback is durable and auditable.

## Review Focus

- Dirty user checkout: promotion must operate only in the isolated live worktree.
- Live branch divergence: refuse rather than overwrite unrelated commits.
- Health-check failure: reset only to the recorded checkpoint.
- Repeated rollback: remain idempotent and preserve the ledger.
- Candidate without a committed gate: adapter must not call promotion.

### Task 1: Promotion manager

**Files:**
- Create: `src/sophyane/rsi/promotion.py`
- Test: `tests/rsi/test_promotion.py`

**Interfaces:**
- Produces `PromotionManager(repo, state_dir, branch, health_command)` and `PromotionResult`.
- `promote(candidate_commit: str, expected_base: str) -> PromotionResult`.
- `rollback() -> PromotionResult`.

- [ ] Write failing tests for clean promotion, divergence refusal, health failure rollback, and idempotent rollback.
- [ ] Run the promotion tests and confirm they fail because the manager does not exist.
- [ ] Implement isolated branch/worktree creation, fast-forward promotion, health check, checkpoint persistence, and rollback.
- [ ] Run the promotion tests and confirm they pass.
- [ ] Commit `feat: add isolated RSI source promotion manager`.

### Task 2: Native adapter promotion contract

**Files:**
- Modify: `src/sophyane/rsi/curriculum_adapter.py`
- Test: `tests/rsi/test_curriculum_adapter.py`

**Interfaces:**
- Consumes `PromotionManager` and native gate details.
- Produces verified curriculum results only when native source promotion is accepted.

- [ ] Add a failing test proving `reinforced` without source promotion is not true RSI promotion.
- [ ] Run the test and confirm it fails under the current adapter behavior.
- [ ] Require `promotion_committed` plus `live_promoted` evidence for source-improvement status; preserve a separate task-verification status for non-source reinforcement.
- [ ] Run adapter tests and confirm they pass.
- [ ] Commit `fix: require live source promotion for true RSI abilities`.

### Task 3: Engine and runtime wiring

**Files:**
- Modify: `src/sophyane/evolution/engine.py`
- Modify: `src/sophyane/rsi/runtime_services.py`
- Modify: `src/sophyane/rsi/curriculum_runtime.py`
- Test: `tests/rsi/test_true_rsi_runtime.py`

**Interfaces:**
- Native engine exposes candidate commit and gate details to the adapter.
- Runtime constructs the manager in the external RSI state directory and records active commit in status.

- [ ] Add failing tests for candidate commit evidence, runtime status active commit, and no fallback source promotion.
- [ ] Run tests and confirm failure.
- [ ] Wire the manager after trusted gate approval, pass promotion evidence through the adapter, and make follow-up scheduling depend on true promotion.
- [ ] Run the focused runtime tests and confirm they pass.
- [ ] Commit `feat: wire native source promotion into continuous RSI`.

### Task 4: End-to-end verification

**Files:**
- Modify: `src/sophyane/rsi_terminal.py`
- Test: `tests/rsi/test_true_rsi_e2e.py`

- [ ] Add a failing temporary-repository test for promotion, health check, status evidence, and rollback.
- [ ] Implement daemon/runtime status reporting for the promotion ledger.
- [ ] Run the end-to-end test and confirm it passes.
- [ ] Run the full relevant RSI/evolution suite and record results.
- [ ] Commit `test: verify true RSI promotion and rollback flow`.
