# External RSI Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a standalone external watchdog CLI that restarts the RSI daemon after abrupt termination or stale heartbeat.

**Architecture:** Keep the existing RSI daemon unchanged. Add supervisor lifecycle primitives in `src/sophyane/rsi/supervisor.py`, with a CLI that launches the daemon, validates ownership/health, applies bounded backoff, and optionally manages a Termux wakelock.

**Tech Stack:** Python 3.13, standard library (`argparse`, `json`, `os`, `signal`, `socket`, `subprocess`, `time`, `pathlib`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-external-rsi-watchdog-design.md`

## Global Constraints

- Never kill a live unrelated PID.
- Preserve the existing RSI state directory and daemon entrypoint.
- Provider failures remain inside RSI; the watchdog handles process/lifecycle failures.
- Wakelock support is best-effort and must not prevent RSI startup.
- Restart delays are bounded.

## Review Focus

- Stale PID/socket artifacts must be recoverable without deleting another process's files.
- A live unrelated PID must fail closed.
- Corrupt or missing heartbeat data must trigger controlled recovery, not supervisor exit.
- Repeated child crashes must back off rather than spin.
- Missing `termux-wake-lock` must remain nonfatal.

## Tasks

- [ ] **Task 1: Add failing watchdog unit tests**
  - File: `tests/rsi/test_external_watchdog.py`
  - Add tests for parser defaults/required mode, stale artifact recovery, unrelated PID protection, heartbeat health, restart backoff, and missing wakelock command.
  - Run the focused test file and confirm it fails because the external CLI/API is absent.

- [ ] **Task 2: Implement lifecycle primitives**
  - File: `src/sophyane/rsi/supervisor.py`
  - Add typed configuration/status helpers, safe PID ownership checks, heartbeat/socket health checks, child launch, bounded backoff, and wakelock helpers.
  - Keep existing in-process supervisor APIs compatible.
  - Run the focused tests and confirm they pass.

- [ ] **Task 3: Implement the CLI loop**
  - File: `src/sophyane/rsi/supervisor.py`
  - Add `main(argv=None)` and `if __name__ == "__main__"` handling for the approved flags, daemonization, one-shot mode, signal shutdown, status writes, and restart loop.
  - Run parser and lifecycle tests.

- [ ] **Task 4: Add regression coverage and documentation**
  - Files: `tests/rsi/test_external_watchdog.py`, `src/sophyane.egg-info/entry_points.txt` only if an entrypoint is needed.
  - Verify `python -m sophyane.rsi.supervisor --help` and the documented command.
  - Run the focused RSI suite; separately report the pre-existing committed-baseline import failure.

- [ ] **Task 5: Final verification**
  - Run focused watchdog tests and all available RSI tests in the isolated worktree.
  - Review the diff for scope and confirm the original checkout remains unchanged.
