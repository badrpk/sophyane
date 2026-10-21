# Sophyane Core Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native execution) to implement this plan task-by-task.

**Goal:** Build one tested Core Controller entry point that routes Sophyane requests through six explicit modes while preserving provider, execution, verification, and promotion authority boundaries.

**Architecture:** Add a small controller package with typed request/plan/result/audit models, mode adapters, deterministic mode selection, and an append-only trace store. Existing mode implementations remain behind adapters; provider and execution components are injected interfaces so the controller cannot perform privileged work itself.

**Tech Stack:** Python 3.13, dataclasses/enums, JSONL audit persistence, pytest, existing Sophyane provider and execution abstractions.

**Spec:** `docs/superpowers/specs/2026-10-21-core-controller-design.md`

## Global Constraints

- Models may propose actions but cannot grant themselves execution or promotion authority.
- Explicit unauthorized or unavailable modes fail closed; they never silently broaden authority.
- Provider fallback is limited to the selected mode's declared policy.
- Unknown in-flight work recovers as failed/needs-review, never as promoted.
- Existing mode implementations are adapted, not wholesale-rewritten.
- No new runtime dependency is required.
- Existing dirty worktree changes must remain untouched.

## Review Focus

- Explicit mode request that is unavailable or unauthorized: must return `mode_unavailable` without fallback.
- Provider failure in one route: may use only the selected mode's fallback chain and must audit the decision.
- Model proposal requesting a forbidden capability: execution must be denied before any tool call.
- Process restart during an in-flight request: trace must recover as `unknown`/needs-review.
- Malformed or secret-bearing provider output: result must be bounded and audit storage must omit credentials.

---

### Task 1: Define controller contracts

**Files:**
- Create: `src/sophyane/core_controller/__init__.py`
- Create: `src/sophyane/core_controller/models.py`
- Test: `tests/test_core_controller_models.py`

**Interfaces:**
- Produce `ModeName`, `ControllerRequest`, `ControllerContext`, `ModePlan`, `ProviderDecision`, `ExecutionResult`, `ModeResult`, and `AuditEvent`.
- All public models must be JSON-serializable through a deterministic `to_dict()` representation.

- [ ] Write tests for all six mode enum values, bounded request fields, stable serialization, and structured failure results.
- [ ] Run `PYTHONPATH=src .venv/bin/pytest -q tests/test_core_controller_models.py`; confirm RED before implementation.
- [ ] Implement frozen dataclasses/enums with bounded text and explicit dispositions.
- [ ] Rerun the focused test; confirm GREEN.
- [ ] Commit: `feat: add core controller contracts`.

### Task 2: Add deterministic mode selection

**Files:**
- Create: `src/sophyane/core_controller/selection.py`
- Test: `tests/test_core_controller_selection.py`

**Interfaces:**
- `select_mode(request: ControllerRequest, context: ControllerContext) -> ModeSelection`.
- Selection precedence follows the spec: explicit request, bound session, deterministic classifier, safe default.

- [ ] Write tests for each precedence level, invalid explicit mode, unavailable mode, and ordinary-chat default.
- [ ] Run the focused test and verify the expected failures.
- [ ] Implement selection without provider calls or side effects.
- [ ] Verify focused tests pass and add a property test that selection is deterministic for identical input.
- [ ] Commit: `feat: add deterministic mode selection`.

### Task 3: Add adapter and authority protocols

**Files:**
- Create: `src/sophyane/core_controller/protocols.py`
- Create: `src/sophyane/core_controller/adapters.py`
- Test: `tests/test_core_controller_adapters.py`

**Interfaces:**
- `ModeAdapter.prepare()` and `ModeAdapter.interpret()` protocols.
- `ProviderGateway.admit()` and `ExecutionBoundary.execute()` protocols.
- `AdapterRegistry.register(mode, adapter)` and `AdapterRegistry.get(mode)`.
- Default adapters wrap existing race, SLI, local, external, learning, and conversation entry points without executing during `prepare()`.

- [ ] Write tests proving all six modes have registered adapters and that preparation only creates a plan.
- [ ] Write tests proving execution requires an explicit provider decision and execution-boundary approval.
- [ ] Run focused tests and verify RED.
- [ ] Implement protocols, registry, and minimal adapters using dependency injection.
- [ ] Verify focused tests pass and confirm no adapter imports credentials or starts a process during preparation.
- [ ] Commit: `feat: add six-mode adapter registry`.

### Task 4: Implement controller lifecycle and failure boundaries

**Files:**
- Create: `src/sophyane/core_controller/controller.py`
- Create: `src/sophyane/core_controller/failures.py`
- Test: `tests/test_core_controller_lifecycle.py`

**Interfaces:**
- `CoreController.handle(request: ControllerRequest) -> ModeResult`.
- Inject `ModeSelector`, `AdapterRegistry`, `ProviderGateway`, `ExecutionBoundary`, and `AuditStore`.
- Map failures to the nine stable failure boundaries in the specification.

- [ ] Write tests for successful dry-run lifecycle, provider denial, execution denial, verification failure, and promotion denial.
- [ ] Write tests proving provider fallback cannot cross mode policy and model output cannot self-promote.
- [ ] Run focused tests and verify RED.
- [ ] Implement the minimal orchestration sequence: select, prepare, admit, execute, interpret, audit.
- [ ] Verify focused tests pass, including exception-to-boundary mapping.
- [ ] Commit: `feat: implement core controller lifecycle`.

### Task 5: Add durable audit and restart recovery

**Files:**
- Create: `src/sophyane/core_controller/audit.py`
- Modify: `src/sophyane/core_controller/controller.py`
- Test: `tests/test_core_controller_audit.py`

**Interfaces:**
- `AuditStore.append(event: AuditEvent) -> None`.
- `AuditStore.read(trace_id: str) -> tuple[AuditEvent, ...]`.
- `AuditStore.recover_inflight() -> tuple[str, ...]`.

- [ ] Write tests for append-only JSONL records, bounded error text, secret redaction, trace filtering, and restart recovery.
- [ ] Run focused tests and verify RED.
- [ ] Implement atomic append, tolerant read, and unknown-in-flight recovery without marking promotion successful.
- [ ] Verify tests pass with truncated and malformed trailing records.
- [ ] Commit: `feat: add durable core controller audit`.

### Task 6: Integrate existing entry points and verify the milestone

**Files:**
- Modify: `src/sophyane/cli_entry.py` or the existing top-level dispatch entry point identified during implementation.
- Modify: `src/sophyane/agent.py` only where the controller boundary is required.
- Create: `tests/test_core_controller_integration.py`
- Create: `docs/superpowers/reports/2026-10-21-core-controller-verification.md`

**Interfaces:**
- Expose one explicit controller construction path for CLI/API callers.
- Preserve current behavior for existing callers by adapting them into `ControllerRequest`.

- [ ] Write integration tests for all six mode entry points using deterministic fake gateways and boundaries.
- [ ] Write a dry-run test that proves no filesystem, browser, subprocess, or provider mutation occurs.
- [ ] Run the integration tests and verify RED before wiring the entry point.
- [ ] Implement the narrowest dispatch integration and preserve existing public commands.
- [ ] Run focused controller tests, relevant existing mode tests, `git diff --check`, and the repository test command.
- [ ] Record unrelated baseline failures with exact command/output; do not hide them.
- [ ] Commit: `feat: integrate core controller entry point`.

## Completion Gate

The milestone is complete only after Tasks 1–6 pass their focused tests, the integration verification report is written, and the final test results distinguish verified behavior from unavailable live-provider checks.
