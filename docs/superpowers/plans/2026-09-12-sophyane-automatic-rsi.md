# Sophyane automatic RSI implementation plan

**Goal:** A bounded automatic, evidence-driven RSI iteration with persistent coding-provider availability.
**Architecture:** Host-owned authority, evidence and transaction logic; isolated candidate Git worktree and qualified text-proposal providers. JSON records and deterministic gates, external quota state.
**Tech Stack:** Python 3.10+, dataclasses, pathlib, subprocess, Git plumbing, pytest.
**Spec:** `docs/superpowers/specs/2026-09-12-sophyane-automatic-rsi-design.md`

## Global constraints

Preserve existing work; no developer-tree commits, push, reset, restore, clean, stash, revert, secrets or persistent provider-config edits. Runtime fixture commits are confined to temporary repositories. Mutation order exactly `("codex_cli", "nifdu_browser")`; general Mode-6 keeps Local. All tests use `PYTHONPATH="$PWD/src" .venv-full/bin/python -m pytest -q`. Architecture/promotion already approved: execute inline without another approval gate.

Every task follows: write the named focused tests; run the exact test-file command with the prefix above; record RED_COMMAND, RED_EXIT_CODE, RED_EXPECTED_FAILURE in the audit transcript; implement only the missing tested behavior; repeat the exact command to GREEN. Import checks happen inside tests so missing new modules produce focused failures, not collection errors. Additional edge behaviors receive their own failing test before fixes.

## 1. Canonical executable authority

Files: create `src/sophyane/rsi/{__init__,authority}.py`, `tests/rsi/test_authority.py`.
Interface: `Operation`, `require(provider: str, operation: Operation) -> None`, `CODING_PROVIDER_ORDER`.
- [ ] Test canonical coding providers permit source/test/promotion/rollback, Local permits read-only, Local aliases/casing and unknown/Gemini identities deny every mutation before side effects.
- [ ] RED: `tests/rsi/test_authority.py`; missing authority implementation.
- [ ] Implement enum and exact allowlist with `PermissionError` subclass; no inferred alias authority.
- [ ] GREEN same file.

```python
with pytest.raises(PermissionError):
    require('LOCAL_GGUF', Operation.SOPHYANE_SOURCE_MUTATION)
require('local_gguf', Operation.READ_ONLY_OPERATION)
```

## 2. Persistent availability and coding routing

Files: create `rsi/availability.py`, `rsi/coding_provider.py`; tests `test_provider_failover.py`, `test_provider_availability.py`.
Interfaces: `AvailabilityStore(path=None, clock=local_now)`, `blocked(provider)`, `failure(provider, error)`, `success(provider)`, `probe(provider)`; `CodingRouter(store, factory).request(prompt, workspace, cancelled) -> CodingResult`. Result carries provider, file replacements, failovers and status; factories instantiate only Codex/NIFDU read-only proposal adapters.
- [ ] Fake-clock tests for before/exact/after retry, short/weekly independent expiry, restart, unknown reset probing, tomorrow/local clocks, external path pinning, sanitized persistence, zero-exit semantic quota, independent NIFDU, malformed state fail-closed.
- [ ] Route tests A-J from spec: success, quota, timeout, unavailable, terminal bugs/cancel/causes/context, both deferred, no Local/Gemini construction, each new request restarts priority.
- [ ] RED both named files; implement atomic locked state and recognized classifier, strict response schema; GREEN both.

```python
clock.value = retry_at
assert router.request(prompt, workspace).provider == 'codex_cli'
assert calls == ['nifdu_browser', 'codex_cli']
```

## 3. Records, weaknesses and metric decisions

Files: `rsi/models.py`, `weakness.py`, `benchmark.py`; `tests/rsi/test_benchmark_comparison.py`.
Interfaces: typed state/weakness/baseline/candidate/command/verification/decision records; `detect(WeaknessRecord | None)`, `compare(weakness, baseline_metrics, candidate_metrics)`.
- [ ] Test invalid/no measurable evidence returns NO_ACTION; finite/directional target threshold and protected tolerance cases including improved/stable, regressed protection, equal and worsened target, missing/NaN.
- [ ] RED named file; implement frozen records and pure decision; GREEN.

```python
assert not compare(weakness, {'quality': 1}, {'quality': 1}).promote
```

## 4. Baseline and worktree isolation

Files: `rsi/baseline.py`, `candidate.py`; `tests/rsi/test_candidate_isolation.py` and fixture `conftest.py`.
Interfaces: `capture(path, weakness, metrics, tests) -> BaselineRecord`; `Candidate.create(baseline, root)`, `.apply(provider, files, allowed_paths)`, `.seal()`, `.cleanup()`.
- [ ] Temporary Git A fixture with committed flawed function and assertion script. Test dirty refusal, commit identity, separate path/HEAD, only candidate changes, rejection byte preservation and safe cleanup. Test all-or-none validation of traversal/Git metadata/symlink/hardlink/unauthorized paths and Local attack.
- [ ] RED named file; implement subprocess Git helper, detached worktree ownership checks and constrained replacement; GREEN.

```python
candidate.apply('codex_cli', {'value.py': 'VALUE = 2\n'}, {'value.py'})
assert (baseline_path / 'value.py').read_text() == 'VALUE = 1\n'
```

## 5. Real RED and mandatory verification

Files: `rsi/verification.py`; `tests/rsi/test_red_gate.py`, `test_verification_gate.py`.
Interfaces: `run_command(argv, cwd, timeout, cancelled) -> CommandResult`; `confirm_red(result, expected_failure)`; `gates(VerificationResult) -> dict[str,bool]`.
- [ ] Real failed assertion accepted, passing RED rejected, syntax/import errors and unrelated noise rejected; fresh Python imports candidate src; timeout/cancel stop; each mandatory failed gate vetoes promotion including absent evidence and LLM override text.
- [ ] RED both named files; implement argv execution with bounded process lifecycle and output digest, exact RED/GREEN pairing and complete gate set; GREEN.

```python
assert not confirm_red(CommandResult(command, 0, 'expected weakness'), 'expected weakness')
```

## 6. Durable transaction and rollback

Files: `rsi/journal.py`, `promotion.py`, `rollback.py`; tests `test_iteration_journal.py`, `test_automatic_promotion.py`, `test_automatic_rollback.py`.
Interfaces: `Journal.append(provider, iteration_id, state, evidence)`, `.checkpoint(provider, iteration_id, evidence)`; `promote(baseline, candidate, decision, checkpoint)`; `rollback(checkpoint)`.
- [ ] Test audit reload, stable ids/timestamps, immutable checkpoint, Local denial; eligible A->B automatic tree/HEAD transition; mandatory veto, stale/dirty A refusal; failed smoke exact A restoration; recovery from recorded checkpoint and retained diagnostics.
- [ ] RED named files; implement exclusive lock, fsynced evidence, local object capture and safe two-tree/index/ref transaction; GREEN.

```python
rollback(checkpoint)
assert git(repo, 'rev-parse', 'HEAD') == old_commit
assert (repo / 'value.py').read_bytes() == original_bytes
```

## 7. Bounded controller and E2E

Files: `rsi/controller.py`; `tests/rsi/test_end_to_end_rsi_cycle.py`.
Interface: `Controller(...).run_once(weakness, parent_iteration=None) -> IterationResult` with trusted command/benchmark policy, editable paths, repair-round limit, lifecycle seconds and cancellation callback. Controller captures A, creates B, runs real RED, routes proposal, applies restricted edits, requires matching GREEN and regressions, measures A/B, seals B, checkpoints and auto-promotes, smoke/rollback, journals final state, safely cleans candidate.
- [ ] E2E success including fresh smoke process and next verified baseline; rollback exact A; quota NIFDU; both unavailable despite available Local; Local attack. Test NO_ACTION, cancelled before promotion, lifecycle/round exhaustion, failed RED and rejected benchmark retain A.
- [ ] RED named file; implement state transitions with terminal exceptions and cleanup in finally; GREEN.

## 8. Mode-6 capability integration and audit

Files: preserve/add minimal capability argument in `src/sophyane/providers/human_conversation.py`; test `tests/rsi/test_authority.py` for read-only Local and mutation stop with existing fake provider chain.
- [ ] RED proves explicit mutation capability cannot reach Local; add router capability check before construction, leave vision/semantic repair and Mode-4 routing unchanged; GREEN.
- [ ] Run `tests/rsi` then requested Mode-6 eleven-file command, provider suite file list determined from repository, then one full suite. Capture exact commands/exits/counts to audit report.
- [ ] Execute `git diff --check`, `git status --short --branch`, `git diff --stat`, `git diff --name-only`; inspect new untracked files too. Compare original hashes, review only intentional additive Mode-6 change. Verify literal RSI order and Local read-only executable test.
- [ ] Self-review spec coverage; report all nineteen exact requested sections, remaining issues and fresh results. No commit/push.

## Review-driven TDD additions executed before broad regression

- [x] RED tests in `test_red_gate.py`: unrelated multi-failure output and marker only in displayed source must reject. Implement assertion-line matching and suite-failure-count check; GREEN.
- [x] RED tests in `test_end_to_end_rsi_cycle.py`: benchmark cannot modify candidate after GREEN; verification script cannot be editable. Implement exact candidate-byte fingerprint and policy-path guard; GREEN.
- [x] RED tests in `test_provider_availability.py`: multiple limit windows in one response, explicit UTC clock, future legacy probe_after, unsupported version and incomplete v2 record. Implement window splitting, fixed-offset timezone parsing, conservative migration/schema rejection; GREEN.
- [x] RED tests in `test_execution_sandbox.py`: no OS sandbox must hard-fail before execution; constructed command mounts host read-only. Add `rsi/sandbox.py`; no runtime bypass. Real sandbox test skips only when executable absent. Trusted fixture runner is patched solely under `tests/rsi/conftest.py`.
- [x] RED tests in `test_automatic_rollback.py`: unrelated untracked data cannot yield false clean-rollback claim; unfinished journal promotion recovers A. Implement clean restoration assertion and checkpoint recovery; GREEN.
- [x] RED tests in `test_authority.py` and `test_provider_failover.py`: Mode-6 source requests persist semantic quota even when bridge response is plain text, without accidental JSON parsing cause reclassification. Implement mutation-only strict state routing and parse outside exception context; GREEN.
- [x] RED tests in `test_end_to_end_rsi_cycle.py`: concurrent invocation refused and unfinished promotion recovered before next iteration. Implement lifecycle lock around one complete iteration; GREEN.
