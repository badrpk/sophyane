# Adaptive Repair Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make failed deterministic project tests invoke the selected provider for one targeted repair, preserve the failed verification stage, rerun the exact original verification command after repair, and require a verified pass before completion.

**Architecture:** Keep RSI experiment containment and provider routing unchanged. Extend the existing `run_adaptive_loop` state machine with an explicit pending-repair verification state and a separate bounded repair counter; the repair prompt is sent through `ask()`, the resulting action is applied through the existing admission/runtime path, and the preserved command is rerun deterministically.

**Tech Stack:** Python, pytest, existing `adaptive_execution.py` runtime and provider callback interface.

**Spec:** User-provided adaptive execution repair-state-machine requirements in the current task.

## Global Constraints

- Do not modify RSI repository-scope authorization or experiment workspace construction.
- Do not weaken action admission, provider routing, or verification requirements.
- Preserve the exact failed verification command and rerun it after each authorized repair.
- Keep repair attempts bounded independently from the general execution step budget.
- Do not modify tests or production files merely to suppress a failure.

## Review Focus

- Failed verification must call `ask()` with repair context instead of parsing repair prose as an action.
- A successful repair must automatically rerun the original failing command.
- A second failed repair must remain bounded and report unresolved failure.
- Repair state must survive ordinary provider continuation without resetting the verification command.
- Zero-battery and solar-capacity mismatch failures must exercise the same repair path without test mutation.

### Task 1: Characterize the failed-test repair transition

**Files:**
- Modify: `tests/test_adaptive_unresolved_failure_completion.py`
- Test: same file

- [x] Add regression tests with a deterministic `run_command` verification failure followed by a provider repair action and a passing rerun. Assert the repair prompt is delivered through `ask()`, the original command executes again, and completion is returned only after its pass.
- [x] Add bounded-failure coverage asserting repeated failed repairs return unresolved evidence and do not reset the repair budget.
- [x] Run the focused tests and confirm they fail against the current direct-assignment/reset behavior.

### Task 2: Implement explicit pending repair verification

**Files:**
- Modify: `src/sophyane/adaptive_execution.py`

- [x] Add state for the exact failed command and its verification phase/result.
- [x] On failed test verification, call `ask(_compact_repair_prompt(...))`, store the provider response as the next action candidate, preserve the verification stage, and increment the task-level repair counter without resetting it.
- [x] After an authorized repair succeeds, schedule the preserved command as the next deterministic action.
- [x] Return unresolved failure when the bounded repair budget is exhausted; never report success without a fresh passing verification result.

### Task 3: Verify focused and regression suites

**Files:**
- No additional production files.

- [x] Run the new adaptive repair tests.
- [x] Run the existing adaptive execution, Python repair-loop, and full-stack verification tests.
- [x] Run formatting/static checks available in the repository and inspect the diff for unrelated files.

### Task 4: Review and integration

- [x] Review the final diff against this plan and preserve unrelated Sophyane worktree changes.
- [x] Commit only the targeted adaptive execution and regression-test changes.
