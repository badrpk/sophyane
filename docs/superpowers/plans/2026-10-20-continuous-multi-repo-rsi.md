# Continuous Multi-Repository RSI Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bounded continuous RSI loop that inventories configured repositories, obtains concrete Codex proposals, requires genuine RED-to-GREEN evidence, and promotes commits only within the owning repository.

**Architecture:** Add a durable repository inventory/cursor layer, extend curriculum tasks with repository and verification provenance, and route every candidate through the existing authority, candidate, isolation, review, and promotion gates. The first implementation is opt-in and round-robin; it never grants an LLM direct filesystem or cross-repository mutation authority.

**Tech Stack:** Python 3, dataclasses, atomic JSON/JSONL state, Git worktrees, pytest, existing QEMU/local-artifact RSI gates, Codex CLI provider.

**Spec:** `docs/superpowers/specs/2026-10-20-autonomous-repo-review-design.md`

## Global Constraints

- Discover repositories only from `SOPHYANE_REPOSITORY_ROOTS` and the configured owner.
- Never follow symlink escapes or accept LLM-selected repository roots.
- Every task must identify exactly one repository and one immutable base commit.
- A proposal is invalid unless its declared focused check fails on the base and passes on the candidate.
- Isolation, authority, review, rollback, and promotion gates remain mandatory.
- Existing curriculum JSON must remain readable through migration defaults.
- Queue, attempt, wall-time, file-count, and repository-count budgets remain enforced.
- No automatic remote pushes and no unrestricted host execution.

## Review Focus

- Duplicate local checkouts of one remote must produce one stable inventory record; test in Task 1.
- A symlink or `..` path must never escape the selected repository; test in Tasks 1 and 2.
- A stale task must be regenerated when the repository base commit changes; test in Task 2.
- An already-green base must be rejected without retry or promotion; test in Task 3.
- A successful promotion in repository A must not alter repository B; test in Task 4.

---

### Task 1: Durable repository inventory and round-robin cursor

**Files:**
- Create: `src/sophyane/rsi/repository_inventory.py`
- Modify: `src/sophyane/repository_discovery.py` only for shared safe Git metadata helpers if needed
- Test: `tests/rsi/test_repository_inventory.py`

**Interfaces:**
- Consumes: `discover_local_repositories(roots, owner)` and configured repository roots.
- Produces: `RepositoryInventory`, `RepositoryRecord`, and `RepositoryCursor` APIs with atomic JSON persistence.

- [ ] **Step 1: Write failing tests**

  Add tests for canonical repository IDs, duplicate checkout collapse, ignored symlink escapes, persisted cursor advancement, missing repositories, and stable ordering.

- [ ] **Step 2: Run the inventory tests and verify they fail**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_repository_inventory.py`

  Expected: import/API failures for the new inventory service.

- [ ] **Step 3: Implement the minimal inventory service**

  Define `RepositoryRecord(repo_id: str, path: str, remote: str, owner: str, name: str, commit: str, branch: str, test_commands: tuple[tuple[str, ...], ...], editable_paths: tuple[str, ...], digest: str)` and `RepositoryCursor(next_index: int, scanned_commits: dict[str, str])`. Use atomic JSON writes and round-robin selection; reject paths outside configured roots after resolution.

- [ ] **Step 4: Run focused and existing discovery tests**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_repository_inventory.py tests/test_repository_context_selection.py tests/test_repository_audit_operation_authority.py`

  Expected: all pass.

- [ ] **Step 5: Commit**

  `git add src/sophyane/rsi/repository_inventory.py tests/rsi/test_repository_inventory.py src/sophyane/repository_discovery.py && git commit -m "feat: persist multi-repository RSI inventory"`

### Task 2: Repository-bound curriculum task contract

**Files:**
- Modify: `src/sophyane/rsi/curriculum.py`
- Modify: `src/sophyane/rsi/curriculum_proposals.py`
- Modify: `src/sophyane/rsi/curriculum_source.py`
- Test: `tests/rsi/test_curriculum_repository_scope.py`

**Interfaces:**
- Consumes: `RepositoryRecord` and current repository cursor.
- Produces: `CurriculumTask.repository_id`, `base_commit`, `proposal_digest`, and structured `red_command`/`green_commands` fields with migration defaults.

- [ ] **Step 1: Write failing tests**

  Assert old JSON tasks load with empty migration defaults; new proposals require one repository ID, a 40-character-or-valid Git commit string, repository-relative editable paths, one RED command with an intended failure marker, and GREEN commands; reject cross-repository paths and duplicate task identities.

- [ ] **Step 2: Run tests and verify they fail**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_curriculum_repository_scope.py`

  Expected: missing task fields and validation failures.

- [ ] **Step 3: Implement strict task/proposal validation**

  Add backward-compatible dataclass fields and JSON parsing. Extend `ProposalContext` with repository identity/base commit and reject any path not contained by the selected repository policy. Include structured verification in the Codex prompt and provenance.

- [ ] **Step 4: Run curriculum and proposal suites**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_curriculum_repository_scope.py tests/rsi/test_curriculum_proposals.py tests/rsi/test_curriculum_source.py tests/rsi/test_curriculum_state.py`

  Expected: all pass.

- [ ] **Step 5: Commit**

  `git add src/sophyane/rsi/curriculum.py src/sophyane/rsi/curriculum_proposals.py src/sophyane/rsi/curriculum_source.py tests/rsi/test_curriculum_repository_scope.py && git commit -m "feat: bind RSI tasks to repositories and commits"`

### Task 3: Genuine RED/GREEN preverification

**Files:**
- Create: `src/sophyane/rsi/curriculum_redgreen.py`
- Modify: `src/sophyane/rsi/curriculum_adapter.py`
- Test: `tests/rsi/test_curriculum_redgreen.py`

**Interfaces:**
- Consumes: a repository-bound `CurriculumTask`, immutable base worktree, candidate worktree, and existing `run_command`/`confirm_red` verification helpers.
- Produces: `RedGreenResult(status: str, base_result, candidate_results, evidence: tuple[str, ...])`, with statuses `verified`, `already_green`, `candidate_failed`, `invalid_red`, and `infrastructure_error`.

- [ ] **Step 1: Write failing tests**

  Test a base failure with the declared marker followed by candidate success, already-green rejection with zero promotion calls, unrelated failures rejected as invalid RED, and command/path containment.

- [ ] **Step 2: Run tests and verify they fail**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_curriculum_redgreen.py`

  Expected: missing module/result API failures.

- [ ] **Step 3: Implement the bounded preverification service**

  Execute the same focused command against immutable base and candidate. Require `confirm_red` on the base and exit code zero on the candidate. Classify `RED_ALREADY_GREEN` as terminal `already_green`; never convert it into a retry task.

- [ ] **Step 4: Integrate adapter rejection/acceptance**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_curriculum_redgreen.py tests/rsi/test_curriculum_adapter.py tests/rsi/test_red_gate.py`

  Expected: all pass and old adapter gates remain enforced.

- [ ] **Step 5: Commit**

  `git add src/sophyane/rsi/curriculum_redgreen.py src/sophyane/rsi/curriculum_adapter.py tests/rsi/test_curriculum_redgreen.py && git commit -m "feat: require genuine red to green curriculum evidence"`

### Task 4: Multi-repository execution and scoped promotion evidence

**Files:**
- Modify: `src/sophyane/rsi/runtime_services.py`
- Modify: `src/sophyane/rsi/promotion.py`
- Modify: `src/sophyane/rsi/curriculum_runtime.py`
- Test: `tests/rsi/test_multi_repository_rsi.py`

**Interfaces:**
- Consumes: inventory/cursor, repository-bound tasks, and `RedGreenResult`.
- Produces: repository-scoped worktree/promotion records containing `task_id`, `repository_id`, `base_commit`, `candidate_commit`, reviewer, isolation result, and post-promotion checks.

- [ ] **Step 1: Write failing integration tests**

  Use two temporary repositories and assert round-robin selection, candidate mutation only in the owning repository, promotion evidence binding, divergence regeneration, and restart reconciliation requiring exact live HEAD/recorded commit equality.

- [ ] **Step 2: Run tests and verify they fail**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_multi_repository_rsi.py`

  Expected: missing repository binding/evidence behavior.

- [ ] **Step 3: Implement repository-aware runtime wiring**

  Build inventory at startup, select the next repository cursor, inject repository context into Codex proposals, and instantiate promotion managers with repository-specific state roots. Preserve existing QEMU/local-artifact/authority gates.

- [ ] **Step 4: Harden promotion/restart evidence**

  Persist task and repository IDs in promotion ledger records. Reconcile only when the recorded active commit equals live Git `HEAD`, the task base matches its recorded base, and proposal bytes match the live snapshot.

- [ ] **Step 5: Run focused integration tests**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_multi_repository_rsi.py tests/rsi/test_promotion.py tests/rsi/test_rsi_terminal.py tests/rsi/test_continuous_curriculum_runtime.py`

  Expected: all pass.

- [ ] **Step 6: Commit**

  `git add src/sophyane/rsi/runtime_services.py src/sophyane/rsi/promotion.py src/sophyane/rsi/curriculum_runtime.py tests/rsi/test_multi_repository_rsi.py && git commit -m "feat: run RSI with repository-scoped promotion"`

### Task 5: Continuous daemon rollout and full verification

**Files:**
- Modify: `src/sophyane/rsi_terminal.py`
- Modify: `README.md`
- Test: `tests/rsi/test_continuous_multi_repo_runtime.py`

**Interfaces:**
- Consumes: all prior services and environment-controlled budgets.
- Produces: opt-in read-only/proposal-only/execution modes, status fields for repository cursor and current repository, and documented operational commands.

- [ ] **Step 1: Write failing daemon/status tests**

  Assert mode selection, persisted cursor advancement, queue empty behavior, stop/pause durability, and status reporting of current repository/task and last review outcome.

- [ ] **Step 2: Run tests and verify they fail**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_continuous_multi_repo_runtime.py`

  Expected: missing mode/status fields.

- [ ] **Step 3: Implement bounded rollout controls and documentation**

  Add explicit `SOPHYANE_RSI_MULTI_REPO_MODE=inventory|proposal|execute`, repository and file budgets, and status output. Preserve the existing lifecycle budget environment behavior and require explicit execute mode for mutations.

- [ ] **Step 4: Run the full RSI/evolution verification**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi tests/evolution`

  Expected: all tests pass; any QEMU timeout must be reported as infrastructure failure, never bypassed.

- [ ] **Step 5: Commit**

  `git add src/sophyane/rsi_terminal.py README.md tests/rsi/test_continuous_multi_repo_runtime.py && git commit -m "feat: enable bounded continuous multi-repo RSI"`

