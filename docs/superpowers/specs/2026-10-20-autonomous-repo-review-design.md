# Continuous Multi-Repository RSI Review Design

## Goal

Enable Sophyane to continuously inspect its configured repositories, ask Codex CLI for concrete bounded improvement proposals, and promote only changes that demonstrate genuine RED-to-GREEN progress through repository tests, isolation, review, and rollback gates.

## Scope

This design covers the first end-to-end control loop for all configured repository roots. It does not attempt to review or rewrite every line in one pass, alter model weights, or claim AGI. It creates a durable, auditable stream of small improvements; later work can add specialized analyzers and repository-specific policies.

## Requirements

1. Discover repositories only from explicitly configured roots and record repository identity, branch, commit, language, tests, and editable boundaries.
2. Maintain a per-repository review cursor so scans resume after restart without duplicating work.
3. Ask Codex CLI for one concrete proposal at a time, including target repository, files, expected failing check, replacement or patch, and verification commands.
4. Reject proposals that have no reproducible RED baseline, mutate files outside the repository policy, or mix repositories.
5. Execute candidate verification in the configured isolation backend, then run focused, regression, holdout, and repository-level checks.
6. Require explicit local-artifact review when configured; no cloud availability may silently weaken the gate.
7. Promote and commit only the repository that owns the task, using a repository-scoped branch and durable evidence.
8. Record accepted, rejected, rolled-back, and skipped tasks with reasons, provider identity, commit IDs, and test evidence.
9. Bound work by repository count, files per scan, task attempts, wall time, queue length, and iteration count.
10. Continue scanning after a rejected task without re-queueing an already-green candidate.

## Proposed architecture

```text
configured repository roots
        ↓
repository inventory + review cursor
        ↓
Codex review provider → durable curriculum task
        ↓
policy / authority / genuine-RED precheck
        ↓
candidate workspace → focused + regression + holdout tests
        ↓
QEMU or configured isolation gate
        ↓
local-artifact review → repository-scoped promotion
        ↓
commit ledger + inventory refresh + next repository
```

### Repository inventory

Add a durable inventory service beside the existing repository discovery code. The inventory records a stable repository ID, canonical path, remote identity when available, current commit, default branch, detected test commands, editable policy, and a scan digest. It must ignore symlink escapes and never treat an arbitrary path supplied by an LLM as a repository root.

### Review task contract

Extend the existing curriculum task provenance with repository ID, base commit, proposal digest, and a structured RED/GREEN verification plan. Existing tasks remain readable through migration defaults. A task is eligible only when its repository is still at the recorded base commit or the task is regenerated against the new base.

### Codex review

Codex CLI remains a proposal and review provider, not an unbounded mutator. Prompts receive the inventory summary, bounded file excerpts or digests, known tests, and current weaknesses. The response is parsed as strict JSON. The provider may suggest a patch or complete replacement text, but the host enforces paths, repository ownership, authority, and verification commands.

### Genuine RED gate

Before candidate execution, run the declared focused check against the immutable base snapshot. It must fail for the declared weakness. Run it again against the candidate and require success. If the base already passes, classify the task as `already_green` and do not promote or retry it under a new ID.

### Promotion and commits

Each repository gets an isolated promotion branch/worktree. Promotion evidence must bind task ID, repository ID, base commit, candidate commit, reviewer outcome, isolation result, and post-promotion checks. A restart reconciliation may complete a task only when the recorded promotion commit exactly matches the live worktree HEAD and the proposal files match; stale markers are not sufficient.

## Failure handling

- Invalid or ambiguous Codex output: reject with a structured provider error.
- Base check already green: reject as `already_green` and advance the cursor.
- Base check fails but candidate check fails: reject and retain evidence for a bounded retry.
- Isolation timeout or unavailable backend: pause infrastructure work; never bypass isolation.
- Review timeout: retry only within the task budget; do not promote.
- Repository divergence: regenerate the task against the current commit.
- Promotion health failure: rollback the isolated branch and record the failure.

## Testing strategy

- Unit tests for inventory normalization, symlink/path containment, cursor persistence, strict proposal parsing, and task migration.
- Integration tests for genuine RED/GREEN, already-green rejection, repository divergence, QEMU/local-artifact gate ordering, promotion evidence, restart reconciliation, and repository-scoped commits.
- A fixture with two repositories proves that a task cannot edit or commit the other repository.
- End-to-end tests use a deterministic local Codex-provider fixture; live Codex and QEMU remain opt-in acceptance tests.

## Rollout

1. Read-only inventory and cursor generation.
2. Codex proposals stored but not executed.
3. One-repository execution behind an explicit opt-in flag.
4. Multi-repository round-robin scheduling with bounded queue and commits.
5. Continuous operation with monitoring, pause, rollback, and audit review.

## Non-goals

- Unrestricted host execution.
- Silent QEMU bypasses.
- Automatic pushes to remote repositories.
- Automatic model-weight modification.
- Treating code volume or line coverage as intelligence.
