# Sophyane Concrete Mode Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native execution) to implement this plan task-by-task.

**Goal:** Replace contract-only Core Controller adapters with concrete, authority-preserving integrations for Sophyane's six modes and shared provider infrastructure.

**Architecture:** Add injected handler and gateway interfaces around the existing Race, SLI, Local, External, Learning, and Conversation entry points. Each handler produces bounded execution evidence; the existing Core Controller remains the sole lifecycle coordinator, while execution and promotion stay injected authorities.

**Tech Stack:** Python 3.13, existing Sophyane provider/runtime modules, dataclasses/protocols, pytest, JSONL audit.

**Spec:** `docs/superpowers/specs/2026-10-21-concrete-mode-provider-integration-design.md`

## Global Constraints

- Existing mode implementations remain intact behind adapters.
- Local mode never calls an external provider.
- External provider fallback follows explicit mode policy only.
- Mode 6 observations remain untrusted and non-executing.
- Race and RSI candidates cannot promote themselves.
- Missing readiness or credentials produces structured failure.
- No new dependency is required.
- Preserve unrelated dirty worktree changes.

## Review Focus

- Local mode with an external-looking provider intent: must reject before provider invocation.
- External mode with a sticky selected provider: must not silently switch outside its declared fallback chain.
- Mode 6 observation containing authority flags: must remain rejected/non-executing.
- Race result containing a winning candidate: must remain unpromoted until independent approval.
- Missing local server/browser/repository readiness: must return structured unavailable status rather than crash or broaden authority.

---

### Task 1: Define concrete handler and readiness contracts

**Files:**
- Modify: `src/sophyane/core_controller/protocols.py`
- Modify: `src/sophyane/core_controller/models.py`
- Modify: `src/sophyane/core_controller/adapters.py`
- Test: `tests/test_core_controller_concrete_contracts.py`

**Interfaces:**
- Add `ModeHandler.execute(plan, capability) -> ExecutionResult`.
- Add `ReadinessProbe.check(plan) -> ReadinessResult`.
- Add `ProviderPolicy` with mode, primary provider, and permitted fallbacks.
- Keep `DefaultModeAdapter` available only as an explicit dry-run adapter.

- [ ] Write failing tests for handler invocation, readiness failure, bounded output, and mode-specific provider policy.
- [ ] Run focused tests and confirm RED.
- [ ] Implement typed contracts and adapter handler injection without live side effects.
- [ ] Verify focused tests pass.
- [ ] Commit: `feat: add concrete mode handler contracts`.

### Task 2: Implement shared provider gateway policies

**Files:**
- Create: `src/sophyane/core_controller/provider_gateway.py`
- Modify: `src/sophyane/cli_entry.py`
- Test: `tests/test_core_controller_provider_gateway.py`

**Interfaces:**
- `ConfiguredProviderGateway.admit(plan) -> ProviderDecision`.
- Policies: `local_only`, `external_sticky`, `mode6_codex_nifdu`, and `offline_unavailable`.
- Readiness is injected so tests do not require credentials, browser sessions, or local servers.

- [ ] Write failing tests for local-only rejection, sticky external selection, Mode 6 cascade, and unavailable provider reporting.
- [ ] Run focused tests and confirm RED.
- [ ] Implement policy admission and bounded provider-state diagnostics.
- [ ] Verify focused tests pass and ensure no provider call occurs during admission.
- [ ] Commit: `feat: add policy-aware provider gateway`.

### Task 3: Wire Race, SLI, Local, and External handlers

**Files:**
- Create: `src/sophyane/core_controller/mode_handlers.py`
- Modify: `src/sophyane/core_controller/adapters.py`
- Test: `tests/test_core_controller_mode_handlers.py`

**Interfaces:**
- `RaceModeHandler` delegates to `run_adaptive_race` through an injected callable.
- `SliGraphModeHandler` delegates to an injected SLI planning/controller callable.
- `LocalLlmModeHandler` delegates to an injected local runtime callable and rejects external provider decisions.
- `ExternalLlmModeHandler` delegates to the injected provider gateway result without self-promoting artifacts.

- [ ] Write failing tests proving each intended callable is invoked only after admission and that results become `ExecutionResult`.
- [ ] Write tests for race candidate non-promotion and local external-provider rejection.
- [ ] Run focused tests and confirm RED.
- [ ] Implement adapters with bounded result normalization and readiness checks.
- [ ] Verify focused tests pass plus existing mode 1–4 suites.
- [ ] Commit: `feat: wire race sli local and external handlers`.

### Task 4: Wire Learning and Human Conversation handlers

**Files:**
- Modify: `src/sophyane/core_controller/mode_handlers.py`
- Modify: `src/sophyane/core_controller/adapters.py`
- Test: `tests/test_core_controller_learning_conversation.py`

**Interfaces:**
- `LearningModeHandler` delegates to injected evidence/observation sinks only.
- `HumanConversationModeHandler` delegates to `conversation_turn` and optional Mode 6 observation handoff.
- Observation handoff must reject trusted/instruction/mutation authority flags.

- [ ] Write failing tests for learning evidence-only behavior and Mode 6 untrusted observation behavior.
- [ ] Run focused tests and confirm RED.
- [ ] Implement handlers with no direct trusted-tree mutation or promotion calls.
- [ ] Verify focused tests plus existing Mode 6 suites.
- [ ] Commit: `feat: wire learning and conversation handlers`.

### Task 5: Integrate live handler registry and readiness reporting

**Files:**
- Modify: `src/sophyane/cli_entry.py`
- Modify: `src/sophyane/core_controller/controller.py`
- Create: `src/sophyane/core_controller/live_registry.py`
- Test: `tests/test_core_controller_live_registry.py`
- Create: `docs/superpowers/reports/2026-10-21-concrete-mode-provider-verification.md`

**Interfaces:**
- `build_live_core_controller()` constructs the registry from existing runtime/provider dependencies.
- `controller.readiness()` returns mode/provider readiness without executing work.
- The existing safe `build_core_controller()` remains available for injected tests and offline use.

- [ ] Write failing tests for readiness reporting, missing dependency handling, and dry-run no-mutation behavior.
- [ ] Run focused tests and confirm RED.
- [ ] Implement live registry construction with explicit unavailable states.
- [ ] Verify all concrete integration tests, existing mode 1–6 suites, and `git diff --check`.
- [ ] Run the repository suite with a bounded timeout; document any hang/failure precisely.
- [ ] Write the verification report distinguishing deterministic tests from live provider checks.
- [ ] Commit: `feat: integrate concrete mode registry`.

## Completion Gate

Complete only when all five tasks pass their focused tests, existing mode suites remain green, readiness is observable without executing work, and the verification report explicitly lists unavailable live dependencies and any full-suite limitations.
