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
- The initial hard-link fixture run skipped because this Termux filesystem
  denied link creation with `EACCES`. The follow-up test now simulates
  `st_nlink > 1` when link creation is denied, and skips only when the platform
  reports hard links are unsupported (`ENOSYS` or `EOPNOTSUPP`).
- `git diff --check` completed with no whitespace errors.

## Scope and commit

Committed only the Task 1 package, focused tests, and this report. Existing
unrelated dirty repository changes were left unstaged and untouched.

## Review fix round 1

- Added fail-closed `onerror` handling to source copying and transaction
  snapshots; filesystem walk errors now propagate instead of silently
  omitting entries.
- Replacement writes now traverse from a pinned transaction directory
  descriptor, write a fresh same-directory temporary file, and atomically
  replace the target. A destination symlink swap therefore replaces the link
  itself and does not write through it; hard-link swaps likewise cannot
  redirect the write to the linked inode.
- Added tests that inject source/snapshot walk errors and swap the replacement
  target to an external symlink immediately before atomic replacement.
- RED: all three focused review cases failed against the prior implementation.
- GREEN: `env PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/mutation/test_containment.py`
  completed with **13 passed**.
- The actual hard-link creation path remains unavailable under this
  environment's filesystem permissions (`EACCES`); the test exercises the
  multiple-link metadata rejection path as a fallback.
