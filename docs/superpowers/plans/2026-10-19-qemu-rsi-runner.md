# QEMU RSI Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in QEMU/TCG runner that executes RSI candidate verification in a dedicated Linux guest without host fallback.

**Architecture:** A focused runner validates a configured aarch64 guest image, creates bounded read-only input and separate output exchange directories, constructs a deterministic QEMU command using 9P shares and TCG, and parses a signed-by-protocol result bundle. The existing source-promotion controller remains authoritative for all promotion gates; QEMU only supplies candidate execution evidence.

**Tech Stack:** Python 3.13, `subprocess`, `pathlib`, QEMU `qemu-system-aarch64`, pytest, existing RSI controller and verification models.

**Spec:** `docs/superpowers/specs/2026-10-19-qemu-rsi-runner-design.md`

## Global Constraints

- QEMU execution is opt-in and must never become an implicit host fallback.
- Candidate input is read-only; the live checkout is never mounted writable.
- Guest image and exchange paths must be validated before launch.
- Every execution has bounded timeout and output limits.
- Malformed results, boot failures, and non-zero guest status reject the run.
- Existing red/green, holdout, regression, benchmark, smoke, and health gates remain authoritative.
- Default tests must not require QEMU or a guest image.

## Review Focus

- Missing or non-regular guest image: reject before spawning QEMU.
- Scratch path traversal or symlink escape: reject before creating shares.
- Guest timeout/boot failure: terminate, collect diagnostics, and preserve the active commit.
- Malformed or oversized result bundle: reject without promotion.
- QEMU unavailable or TCG-only execution: use explicit opt-in and report the exact reason.

### Task 1: Define QEMU runner configuration and deterministic command construction

**Files:**
- Create: `src/sophyane/rsi/qemu_runner.py`
- Test: `tests/rsi/test_qemu_runner.py`

**Interfaces:**
- Produces `QemuRunnerConfig`, `QemuRunResult`, `QemuRsiRunner`, and `build_qemu_command(...)`.
- `QemuRunnerConfig` contains executable, guest image, architecture, scratch root, timeout, output limit, and opt-in state.
- `QemuRsiRunner.validate()` raises a dedicated fail-closed error for invalid configuration.
- `build_qemu_command(config, input_dir, output_dir, manifest)` returns a tuple of argv tokens and includes TCG mode, the guest image, read-only input 9P share, separate output 9P share, and the guest bootstrap arguments.

- [ ] **Step 1: Write failing tests** for deterministic TCG command construction, explicit opt-in, missing image, non-regular image, and path containment.
- [ ] **Step 2: Run** `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_qemu_runner.py`; expect failures because the module and interfaces do not exist.
- [ ] **Step 3: Implement** configuration validation and pure command construction only.
- [ ] **Step 4: Run** the focused test file and require all tests to pass.
- [ ] **Step 5: Commit** `feat: define qemu rsi runner boundary`.

### Task 2: Add bounded guest exchange and result parsing

**Files:**
- Modify: `src/sophyane/rsi/qemu_runner.py`
- Test: `tests/rsi/test_qemu_runner.py`

**Interfaces:**
- `QemuRsiRunner.prepare_exchange(candidate_dir, manifest) -> ExchangePaths` creates a temporary input bundle and separate output directory under the configured scratch root.
- `QemuRsiRunner.parse_result(exchange, stdout, stderr, exit_code, timed_out) -> QemuRunResult` validates the result schema and output limit.

- [ ] **Step 1: Write failing tests** for read-only input preparation, output separation, traversal rejection, valid result parsing, malformed JSON, oversized output, non-zero status, and timeout.
- [ ] **Step 2: Run** the focused tests and verify the new cases fail for the missing behavior.
- [ ] **Step 3: Implement** bounded exchange creation and strict result parsing; never expose the repository directly.
- [ ] **Step 4: Run** the focused tests and require all tests to pass.
- [ ] **Step 5: Commit** `feat: add bounded qemu exchange protocol`.

### Task 3: Execute QEMU with timeout and diagnostics

**Files:**
- Modify: `src/sophyane/rsi/qemu_runner.py`
- Test: `tests/rsi/test_qemu_runner.py`

**Interfaces:**
- `QemuRsiRunner.run(candidate_dir, manifest) -> QemuRunResult` validates, prepares the exchange, launches only the constructed argv list, enforces timeout, captures bounded diagnostics, and cleans temporary state.
- The subprocess layer is injectable for tests but production execution uses `subprocess.Popen` without a shell.

- [ ] **Step 1: Write failing tests** using a controlled subprocess seam for successful completion, timeout termination, startup failure, and cleanup.
- [ ] **Step 2: Run** the focused tests and verify they fail before implementation.
- [ ] **Step 3: Implement** bounded process execution and cleanup with no shell interpolation.
- [ ] **Step 4: Run** the focused tests and require all tests to pass.
- [ ] **Step 5: Commit** `feat: execute bounded qemu rsi runs`.

### Task 4: Connect QEMU evidence to source promotion without changing gates

**Files:**
- Modify: `src/sophyane/rsi/controller.py`
- Modify: `src/sophyane/rsi/runtime_services.py`
- Test: `tests/rsi/test_qemu_promotion_integration.py`

**Interfaces:**
- Add an explicit runner selection/configuration path that chooses QEMU only when enabled and fully configured.
- Candidate execution failures become rejected iterations with durable reason data; they do not invoke host execution.
- Existing promotion calls and verification gates remain unchanged except for receiving the QEMU execution result.

- [ ] **Step 1: Write failing integration tests** proving QEMU is opt-in, failed guest execution leaves the active commit unchanged, and a valid result still must pass existing promotion gates.
- [ ] **Step 2: Run** `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi/test_qemu_promotion_integration.py`; verify failures identify the missing selection and failure propagation.
- [ ] **Step 3: Implement** the narrow adapter/configuration bridge and durable rejection reporting.
- [ ] **Step 4: Run** focused QEMU and source-promotion tests.
- [ ] **Step 5: Commit** `feat: integrate qemu runner with rsi promotion`.

### Task 5: Verify host behavior and document guest-image requirements

**Files:**
- Modify: `README.md` or the existing RSI operations documentation location.
- Test: existing `tests/rsi` suite and the full project suite.

- [ ] **Step 1: Add documentation** for guest-image prerequisites, TCG performance, opt-in configuration, and the exact status/error fields.
- [ ] **Step 2: Run** `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/rsi tests/evolution`.
- [ ] **Step 3: Run** the full project test command and record unrelated failures without weakening safety behavior.
- [ ] **Step 4: Run** a non-mutating command-construction smoke check against the installed `qemu-system-aarch64`.
- [ ] **Step 5: Commit** `docs: document qemu rsi execution`.
