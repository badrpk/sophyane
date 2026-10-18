# Mode 6 Persistent Capability Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist only verified Mode-6 capability artifacts so developed abilities survive restart and remain workspace-bound.

**Architecture:** Add a bounded JSON-backed implementation of the existing `CapabilityStore` protocol. The Mode-6 controller supplies the canonical workspace identity and keeps the existing verifier, promoter, retry, and authority gates unchanged; persistence happens only after trusted promotion.

**Tech Stack:** Python 3, dataclasses, JSON, atomic `os.replace`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-mode6-persistent-capability-reuse-design.md`

## Global Constraints

- Provider proposals remain untrusted bytes; only the existing verifier and promoter may grant trust.
- Capability records are scoped to the canonical workspace path and capability class.
- A persisted record is usable only when its exact promoted file bytes still match the workspace.
- Security, authorization, provider-availability, and sandbox failures must not enter capability development.
- Persistence must be atomic, bounded, and free of prompts, credentials, or provider responses.

## Review Focus

- Corrupt or oversized state must fail closed — test malformed JSON and size limits.
- Workspace identity must not bleed across projects — test a second workspace cannot load the record.
- Untrusted candidates must not be persisted — test `put` rejects non-trusted records.
- Restart reuse must not call a provider — test a fresh store/controller reuses the persisted candidate.
- Atomic writes must not leave partial JSON — test the final state parses after repeated writes.

---

### Task 1: Durable bounded capability store

**Files:**
- Modify: `src/sophyane/failure_driven_capability.py`
- Test: `tests/test_failure_driven_capability_development.py`

**Interfaces:**
- Consumes: existing `CapabilityStore` protocol and trusted candidates returned by the promoter.
- Produces: `PersistentCapabilityStore(path, workspace=...)` with `get(capability_class)` and `put(capability_class, candidate)`.

- [ ] **Step 1: Write failing tests** for verified persistence across store instances, workspace isolation, malformed-state fail-closed behavior, and rejection of non-trusted candidates.
- [ ] **Step 2: Run the focused tests** and confirm they fail because the durable store is absent.
- [ ] **Step 3: Implement `PersistentCapabilityStore`** with bounded JSON state, canonical workspace matching, trusted-status filtering, atomic replacement, and restrictive file mode.
- [ ] **Step 4: Run the focused tests** and confirm they pass.
- [ ] **Step 5: Commit** as `feat: persist verified mode6 capabilities`.

### Task 2: Wire Mode 6 to durable reuse

**Files:**
- Modify: `src/sophyane/human_conversation_cli.py`
- Test: `tests/test_human_conversation_execution_routing.py`

**Interfaces:**
- Consumes: `PersistentCapabilityStore` from Task 1 and existing Mode-6 workspace binding.
- Produces: fresh Mode-6 controller instances that load verified capabilities for the current workspace.

- [ ] **Step 1: Write a failing integration test** that promotes a capability, clears the process controller, creates a fresh controller for the same workspace, and verifies reuse without development/provider calls.
- [ ] **Step 2: Run the test** and confirm the fresh controller has no persisted capability.
- [ ] **Step 3: Wire the Mode-6 controller** to construct the persistent store using the configured state path and resolved workspace; preserve injectable stores in tests.
- [ ] **Step 4: Run the integration test** and the focused Mode-6/RSI suites.
- [ ] **Step 5: Commit** as `feat: reuse mode6 capabilities after restart`.

### Task 3: Full verification and review

- [ ] **Step 1:** Run `git diff --check` and inspect the complete diff.
- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_failure_driven_capability_development.py tests/test_human_conversation_execution_routing.py`.
- [ ] **Step 3:** Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/rsi tests/evolution`.
- [ ] **Step 4:** Run the full test suite and report any pre-existing failures separately.
