# Repository Capability Classification Implementation Plan

**Goal:** Derive repository generation authority from one conservative classifier.

**Architecture:** Three-state enum and deterministic classifier in request_classification.py; one captured operation per CLI repository session. Keep action guards separate.

**Tech stack:** Python enum, deterministic text matching, pytest.

**Spec:** docs/superpowers/specs/2026-09-13-repository-capability-classification-design.md.

**Status: BLOCKED before implementation.** Ordinary inspection can pass write actions to the executor. The user explicitly requires stopping on this gap. Pending steps do not authorize adaptive-policy changes.

## Constraints

Preserve the exact current working tree. Use `PYTHONPATH="$PWD/src" .venv-full/bin/python`. No commit/push or full suite. No Local GGUF mutation authority, provider authority changes, NIFDU weakening, persistent configuration changes, provider cleanup, fallback redesign, or SLI changes.

## 0. Action guard prerequisite

- [x] Inspect the no-edit helper, adaptive call site, and runtime write branch.
- [x] Probe the real loop with an intercepted executor: ordinary inspection and without-changing wording pass write_file; do-not-edit blocks it. No source write performed.
- [x] Stop without changing production or tests; document the gap.
- [ ] Resume only after separately authorized work resolves this boundary.

## 1. Classifier RED then GREEN

Files: tests/test_mode6_provider_cascade.py, src/sophyane/request_classification.py.

- [ ] Add parameterized `test_repository_capability` with the spec's exact 15 request/outcome pairs. Import inside the test to isolate missing-API failures:

```python
def test_repository_capability(request_text, expected):
    from sophyane.request_classification import (
        RepositoryCapability, classify_repository_capability,
    )
    assert classify_repository_capability(request_text) is RepositoryCapability(expected)
```

- [ ] Run only `PYTHONPATH="$PWD/src" .venv-full/bin/python -m pytest -q tests/test_mode6_provider_cascade.py -k repository_capability`. Record missing-classifier RED before any production code.
- [ ] Implement the three-member enum and classifier: normalize, affirmative mutation first, explicit non-mutation second, inspection third, otherwise AMBIGUOUS. Exclude negated mutation verbs. Do not use the filesystem UI helper as authority.
- [ ] Run classifier tests to GREEN. Add RED/GREEN cases for explicit prohibition variants and mutation precedence over those variants.

## 2. CLI authority RED then GREEN

Files: tests/test_mode6_provider_cascade.py, src/sophyane/human_conversation_cli.py.

- [ ] Reuse the cascade fixture with Codex/NIFDU availability failures. Extend `test_repository_uses_same_cascade` for Inspect src/example.py; add `test_repository_mixed_mutation_defers` for Inspect src/example.py and fix the failing function, and `test_repository_ambiguous_defers` for Work on src/example.py.
- [ ] Assert DEFERRED_NO_CODING_PROVIDER for mixed/ambiguous requests, with Local GGUF absent from both constructions and calls. Exercise another ask via the adaptive-loop stub to prove repair text cannot change original authority.
- [ ] Run these tests before wiring. Record inspection RED from hard-coded mutation authority; report deferred cases as existing GREEN if they already pass.
- [ ] Classify the original nonempty request once and capture:

```python
capability = classify_repository_capability(request)
operation = (
    Operation.READ_ONLY_OPERATION
    if capability is RepositoryCapability.READ_ONLY
    else Operation.SOPHYANE_SOURCE_MUTATION
)
```

- [ ] Pass captured operation to every HumanConversationProvider generation in ask; preserve other provider behavior. Never classify repairs or change provider authority implementation.

## 3. Ordered targeted verification

Prefix every pytest invocation with `PYTHONPATH="$PWD/src" .venv-full/bin/python -m pytest -q`. Stop on unrelated failures.

- [ ] Classifier: `tests/test_mode6_provider_cascade.py -k repository_capability`.
- [ ] Original: `tests/test_mode6_provider_cascade.py::test_repository_uses_same_cascade`.
- [ ] Mixed: `tests/test_mode6_provider_cascade.py::test_repository_mixed_mutation_defers`.
- [ ] Ambiguous: `tests/test_mode6_provider_cascade.py::test_repository_ambiguous_defers`.
- [ ] Routing/authority: `tests/test_human_conversation_execution_routing.py tests/rsi/test_authority.py tests/test_mode6_provider_cascade.py`.
- [ ] Mode-6: `tests/test_human_conversation_provider_authority.py tests/test_human_conversation_runtime_compatibility.py tests/test_human_conversation_session_identity.py tests/test_human_conversation_startup_mode.py tests/test_mode6_failure_boundaries.py tests/test_mode6_provider_availability.py`.
- [ ] Provider policy: `tests/test_provider_deactivation_policy.py`.
- [ ] Fallback: `tests/test_fallback_and_daemon.py tests/test_fallback_context_rendering.py tests/test_fallback_generation_budget.py tests/test_fallback_provider_capabilities.py`.
- [ ] Run git diff --check, print git status --short --branch, and run the user's authority proof: coding order exactly Codex/NIFDU, Local GGUF read-only allowed and source mutation denied.
- [ ] Report files, RED/GREEN evidence and totals, routing proofs, guard findings, separate failure, Git checks, LOCAL_MUTATION_AUTHORITY=DENIED, no commit, and no push. No full suite.
