# Repository capability classification design

Approved 2026-09-13. Implementation blocked by the action-boundary finding below.

## Problem and authority

`_execute_repository_request()` hard-codes source-mutation authority for all repository requests. Existing filesystem/UI classifiers are unsuitable for authority decisions.

- Read-only generation: `codex_cli -> nifdu_browser -> local_gguf`.
- Mutation generation: `codex_cli -> nifdu_browser -> DEFERRED_NO_CODING_PROVIDER`.
- Local GGUF receives only `READ_ONLY_OPERATION`, never coding authority.

## Canonical classifier

Add `RepositoryCapability(str, Enum)` with exactly `READ_ONLY = "read_only"`, `MUTATION = "mutation"`, and `AMBIGUOUS = "ambiguous"`, plus `classify_repository_capability(request: str) -> RepositoryCapability` in `request_classification.py`.

Normalize text. Detect affirmative mutation first: fix, patch, modify, edit, update, implement, rewrite, refactor, replace, change, create/write source, add/remove code or features. Account for negated verbs and explanatory uses where practical. Explicit mutation always overrides inspection and non-mutation wording. Next recognize explicit non-mutation language, then clear inspection/read/show/explain/list intent; otherwise AMBIGUOUS. Keep it deterministic and small.

Classify the original request once. Map READ_ONLY to `Operation.READ_ONLY_OPERATION`; MUTATION and AMBIGUOUS both map to `Operation.SOPHYANE_SOURCE_MUTATION`. Capture this operation for every HumanConversationProvider ask, including repairs; preserve other provider behavior. Ambiguity fails closed.

## Action boundary and blocking evidence

The classifier controls generation only. Preserve adaptive action guards and the distinction between read-only and source-changing commands. Do not classify every run_command as mutation.

`adaptive_execution.py:2219` enables `_no_edit_action_problem()` only when `_explicit_no_edit_request(original_request)` matches. That helper (line 87) does not match ordinary inspection or `without changing it`. The loop calls `_execute()` at line 2241, which forwards valid writes to the runtime. `execution_runtime.py:976` writes files without original-request authority.

A real adaptive-loop probe using a temporary workspace and intercepted final executor confirmed that write_file reaches execution for `Inspect src/example.py` and `Analyze src/example.py without changing it`. The control `Inspect src/example.py; do not edit` blocks it. No source write occurred. The user's stop condition blocks implementation until separately authorized work resolves this gap.

## Test matrix

| Outcome | Requests |
| --- | --- |
| READ_ONLY | `Inspect src/example.py`; `Read src/example.py`; `Explain src/example.py`; `Show me src/example.py`; `List files in this repository`; `Analyze src/example.py without changing it` |
| MUTATION | `Inspect src/example.py and fix the failing function`; `List files and fix src/example.py`; `Read src/example.py then patch the bug`; `Analyze src/example.py and implement the fix`; `Modify src/example.py`; `Patch src/example.py`; `Implement the missing function` |
| AMBIGUOUS | `Work on src/example.py`; `Handle src/example.py` |

Also test `without modifying`, `do not edit`, and `read-only analysis`, including affirmative mutation combined with non-mutation language. Integration tests prove inspection reaches Local GGUF after Codex/NIFDU availability failures, while mixed and ambiguous requests defer without constructing or calling Local GGUF. Repair prompts retain original authority.

## Exclusions

Preserve current Mode-6, RSI, provider-deactivation and NIFDU work. No credentials/configuration changes, provider deletion, startup/catalog/hardware cleanup, generic fallback redesign, SLI changes, full suite, commit, push, reset, restore, stash, clean, or revert. Leave the known saved-Gemini PROVIDER_DISABLED timeout-test failure separate.
