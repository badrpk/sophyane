# Task 1 implementation report

## Outcome

Implemented the immutable mutation data contracts and lab-only transaction
containment boundary.

## Public contracts

- Added frozen `MutationIntent`, `MutationProposal`, and `MutationResult`
  records. Proposal replacement mappings are copied into a read-only mapping.
- Added `MutationLab` with the production default
  `/home/badrpk/shmry_mutation_lab`; callers can inject a temporary root.
- Added `LabTransaction` with a unique directory, immutable baseline file
  mapping, deterministic baseline hash, read-only snapshots, allowlisted text
  replacement, reversal patch generation, baseline restoration, and close.

## Containment behavior

- Source roots and lab roots may not contain one another. A source root that is
  itself a symlink is rejected.
- Snapshot traversal never follows symlinks. Symlink entries, non-regular
  files, and regular files with multiple hard links are rejected.
- Replacements reject absolute paths, traversal components, backslashes,
  paths outside the allowlist, non-text values, and targets outside the copied
  baseline. Existing transaction symlinks and multiply linked targets are also
  rejected.
- Only the lab transaction copy is changed; source files remain read-only.

## TDD and verification

- Wrote `tests/mutation/test_containment.py` before implementation.
- RED: `env PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/mutation/test_containment.py`
  failed during collection with `ModuleNotFoundError: No module named
  'sophyane.mutation'`, as expected before package creation.
- GREEN: the same command completed with **9 passed, 1 skipped**.
- The hard-link fixture is skipped because the Termux filesystem rejects
  creating hard links with `EACCES`. The production snapshot check rejects
  source files where `st_nlink != 1`; that behavior could not be exercised in
  this environment.
- `git diff --check` completed with no whitespace errors.

## Scope and commit

Committed only the Task 1 package, focused tests, and this report. Existing
unrelated dirty repository changes were left unstaged and untouched.
